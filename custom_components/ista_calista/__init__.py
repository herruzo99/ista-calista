"""The ista Calista integration."""

from __future__ import annotations

import logging

from homeassistant.helpers import config_validation as cv
from homeassistant.components.recorder import get_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType
from pycalista_ista import (
    IstaApiError,
    IstaConnectionError,
    IstaLoginError,
    PyCalistaIsta,
)

from .const import (
    CONF_LOG_LEVEL,
    DEFAULT_LOG_LEVEL,
    DOMAIN,
    LOG_LEVELS,
    PLATFORMS,
)
from .coordinator import IstaCoordinator

type IstaConfigEntry = ConfigEntry[IstaCoordinator]

_LOGGER = logging.getLogger(__name__)

# Maps device models from the device registry to their corresponding sensor key.
MODEL_TO_KEY_MAP = {
    "Cold Water Meter": "water",
    "Hot Water Meter": "hot_water",
    "Heating Meter": "heating",
}

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ista Calista component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Set up ista Calista from a config entry."""
    _LOGGER.debug("Setting up config entry: %s", entry.entry_id)
    session = async_get_clientsession(hass)
    ista = PyCalistaIsta(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], session)

    # Set log level for the library and the integration based on user options
    log_level_str = entry.options.get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL).upper()
    if log_level_str not in LOG_LEVELS:
        _LOGGER.warning(
            "Invalid log level '%s' configured; defaulting to '%s'.",
            log_level_str,
            DEFAULT_LOG_LEVEL,
        )
        log_level_str = DEFAULT_LOG_LEVEL
    log_level_str = log_level_str.upper()
    try:
        # Set log level for the underlying library
        ista.set_log_level(log_level_str)

        # Set log level for the integration's custom component namespace
        integration_logger = logging.getLogger(__name__.split(".")[0])
        level = logging.getLevelName(log_level_str)
        integration_logger.setLevel(level)
        _LOGGER.debug("Log level for '%s' set to %s", DOMAIN, log_level_str)
    except (ValueError, TypeError) as err:
        # This should not happen with the SelectSelector, but is a safeguard.
        _LOGGER.error("Failed to set log level: %s", err)

    try:
        _LOGGER.debug(
            "Attempting to log in to Ista Calista API for account: %s",
            entry.data[CONF_EMAIL],
        )
        await ista.login()
        _LOGGER.info("Successfully logged in for account %s", entry.data[CONF_EMAIL])
    except IstaLoginError as err:
        _LOGGER.warning("Authentication failed for %s", entry.data[CONF_EMAIL])
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="authentication_exception",
            translation_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
        ) from err
    except (IstaConnectionError, IstaApiError) as err:
        _LOGGER.error("Failed to connect to Ista Calista API: %s", err)
        raise ConfigEntryNotReady(
            f"Failed to connect to Ista Calista API: {err}"
        ) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error during ista Calista setup")
        raise ConfigEntryNotReady(f"Unexpected error during setup: {err}") from err

    coordinator = IstaCoordinator(hass, entry, ista)
    entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.debug("Finished setting up config entry: %s", entry.entry_id)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    _LOGGER.info("Reloading config entry %s due to options update.", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading config entry: %s", entry.entry_id)
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = entry.runtime_data
        await coordinator.ista.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop("entities", None)
        _LOGGER.info("Successfully unloaded config entry: %s", entry.entry_id)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of a config entry, including associated statistics."""
    _LOGGER.debug(
        "Starting removal process for config entry %s, including associated statistics.",
        entry.entry_id,
    )

    device_registry = dr.async_get(hass)
    devices_for_entry = dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    )

    if not devices_for_entry:
        _LOGGER.debug(
            "No devices found for config entry %s. No statistics to remove.",
            entry.entry_id,
        )
        return

    statistic_ids_to_clear = []
    for device in devices_for_entry:
        sensor_key = MODEL_TO_KEY_MAP.get(device.model)
        if not sensor_key:
            _LOGGER.warning(
                "Cannot map device model '%s' (Device ID: %s) to a sensor key. "
                "Statistics for this device may not be cleared.",
                device.model,
                device.id,
            )
            continue

        serial_number = next(
            (
                identifier
                for domain, identifier in device.identifiers
                if domain == DOMAIN
            ),
            None,
        )

        if not serial_number:
            _LOGGER.warning(
                "Could not find a serial number identifier for device %s. "
                "Statistics for this device may not be cleared.",
                device.id,
            )
            continue

        # We replace them with underscores to match the sensor's statistic_id generation.
        slug_serial_number = serial_number.replace("-", "_")
        sensor_unique_id = f"{slug_serial_number}_{sensor_key}"
        statistic_id = f"{DOMAIN}:{sensor_unique_id}"
        statistic_ids_to_clear.append(statistic_id)

    if statistic_ids_to_clear:
        _LOGGER.debug(
            "Identified %d statistic ID(s) to clear: %s",
            len(statistic_ids_to_clear),
            statistic_ids_to_clear,
        )
        recorder_instance = get_instance(hass)
        if recorder_instance:
            recorder_instance.async_clear_statistics(statistic_ids_to_clear)
            _LOGGER.info(
                "Successfully scheduled clearing of %d statistic(s) for config entry %s.",
                len(statistic_ids_to_clear),
                entry.entry_id,
            )
        else:
            _LOGGER.warning(
                "Recorder integration not available. Could not clear statistics for entry %s.",
                entry.entry_id,
            )


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: IstaConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Disallow manual removal of devices from the UI."""
    return False
