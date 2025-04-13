"""The ista Calista integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientSession
from pycalista_ista import (
    IstaApiError,
    IstaConnectionError,
    IstaLoginError,
    PyCalistaIsta,
)

from homeassistant.components.recorder import get_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

# Assuming const.py defines DOMAIN and PLATFORMS
from .const import DOMAIN, PLATFORMS, CONF_OFFSET
# Assuming coordinator.py defines IstaCoordinator
from .coordinator import IstaCoordinator

# Define the type alias for the config entry specific to this integration
IstaConfigEntry = ConfigEntry[IstaCoordinator]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ista Calista component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Set up ista Calista from a config entry."""
    _LOGGER.debug("Setting up ista Calista integration for entry %s", entry.entry_id)

    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    session = async_get_clientsession(hass)
    ista = PyCalistaIsta(email, password, session)

    try:
        _LOGGER.info("Attempting to login to ista Calista for %s", email)
        await ista.login()
        _LOGGER.info("Login to ista Calista successful for %s", email)

    except IstaLoginError as err:
        _LOGGER.error("Authentication failed for %s: %s", email, err)
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="authentication_exception",
            translation_placeholders={CONF_EMAIL: email},
        ) from err
    except (IstaConnectionError, IstaApiError) as err:
        _LOGGER.error("Failed to connect or communicate with Ista API for %s: %s", email, err)
        raise ConfigEntryNotReady(
             f"Failed to connect to Ista Calista API: {err}"
        ) from err
    except Exception as err:
        _LOGGER.exception("Unexpected error during ista Calista setup for %s", email)
        raise ConfigEntryNotReady(f"Unexpected error during setup: {err}") from err

    coordinator = IstaCoordinator(hass, entry, ista)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    entry.runtime_data = coordinator # Store coordinator for easy access

    _LOGGER.debug("Performing initial data refresh for %s", entry.entry_id)
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.debug("Initial data refresh successful for %s", entry.entry_id)

    _LOGGER.debug("Setting up platforms for %s: %s", entry.entry_id, PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("ista Calista integration setup completed successfully for %s", entry.entry_id)

    # Add listener for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    _LOGGER.debug("Reloading config entry %s due to options update.", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading ista Calista integration for entry %s", entry.entry_id)

    coordinator = hass.data[DOMAIN].get(entry.entry_id)

    # Unload platforms first
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and coordinator:
        # --- Corrected Statistics Clearing ---
        statistic_ids_to_clear = []
        if coordinator.data and coordinator.data.get("devices"):
            devices = coordinator.data["devices"]
            # Import sensor descriptions to know which sensors generate stats
            try:
                 # pylint: disable=import-outside-toplevel
                 from .sensor import SENSOR_DESCRIPTIONS, IstaSensorEntity
            except ImportError:
                 _LOGGER.error("Could not import sensor descriptions for statistics cleanup.")
                 SENSOR_DESCRIPTIONS = [] # Avoid crashing if import fails

            # Iterate through devices and sensor descriptions that generate LTS
            for serial_number in devices:
                 for description in SENSOR_DESCRIPTIONS:
                      if description.generate_lts:
                           # Construct the statistic_id matching the sensor's logic:
                           # domain:DOMAIN_serial_key (derived from entity_id)
                           # Note: This assumes the entity_id format sensor.DOMAIN_serial_key
                           # which is standard when unique_id and has_entity_name=True are used.
                           base_id = f"{DOMAIN}_{serial_number}_{description.key}"
                           stat_id = f"{DOMAIN}:{base_id}"
                           statistic_ids_to_clear.append(stat_id)
                           _LOGGER.debug("Identified potential statistic ID for cleanup: %s", stat_id)

        if statistic_ids_to_clear:
            # Remove duplicates just in case
            unique_statistic_ids = list(set(statistic_ids_to_clear))
            _LOGGER.debug("Attempting to clear statistics for entry %s: %s", entry.entry_id, unique_statistic_ids)
            try:
                get_instance(hass).async_clear_statistics(unique_statistic_ids)
                _LOGGER.info("Cleared statistics for entry %s", entry.entry_id)
            except Exception as e:
                 _LOGGER.error("Error clearing statistics for entry %s: %s", entry.entry_id, e)
        else:
            _LOGGER.debug("No statistics IDs identified for clearing for entry %s", entry.entry_id)
        # --- End Statistics Clearing ---

        # Remove coordinator from hass data
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("Removed coordinator from hass data for %s", entry.entry_id)

        # Close the API client session
        await coordinator.ista.close()
        _LOGGER.debug("Closed PyCalistaIsta API client session for %s", entry.entry_id)

    elif not coordinator:
         _LOGGER.warning("Coordinator not found during unload for entry %s", entry.entry_id)


    _LOGGER.info("ista Calista integration unloaded: %s for entry %s", unload_ok, entry.entry_id)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: IstaConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    _LOGGER.debug("Request to remove device %s from config entry %s", device_entry.id, config_entry.entry_id)
    # Allow removal of any device associated with this entry
    return True


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IstaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    _LOGGER.debug("Generating diagnostics for config entry %s", entry.entry_id)
    # Ensure coordinator is accessed correctly via runtime_data or hass.data
    coordinator = entry.runtime_data or hass.data[DOMAIN].get(entry.entry_id)


    if not coordinator:
        return {"error": "Coordinator not found for this config entry."}

    diag_data = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "version": entry.version,
            "domain": entry.domain,
            "data": {**entry.data, CONF_PASSWORD: "**REDACTED**"},
            "options": entry.options,
            "pref_disable_new_entities": entry.pref_disable_new_entities,
            "pref_disable_polling": entry.pref_disable_polling,
            "source": str(entry.source),
            "unique_id": entry.unique_id,
            "disabled_by": entry.disabled_by,
        },
        "coordinator_status": {
            "last_update_success": coordinator.last_update_success,
            "last_update": coordinator.last_update_success_time.isoformat()
            if coordinator.last_update_success_time
            else None,
            "update_interval": coordinator.update_interval.total_seconds()
             if coordinator.update_interval else None,
            "listeners": len(getattr(coordinator, '_listeners', [])), # Safe access
            "is_ready": getattr(coordinator, 'is_ready', False), # Check readiness property if exists
        },
        "api_data": {},
    }

    if coordinator.data:
        devices_data = []
        for serial, device in coordinator.data.get("devices", {}).items():
             # Simple hash for serial number anonymization
             hashed_serial = str(hash(serial))[-8:] # Take last 8 digits of hash
             devices_data.append({
                 "serial_hash": hashed_serial,
                 "type": device.__class__.__name__,
                 "location": device.location, # Consider if location is sensitive
                 "history_count": len(device.history),
                 "last_reading_date": device.last_reading.date.isoformat() if device.last_reading else None,
             })
        diag_data["api_data"] = {
            "device_count": len(devices_data),
            "devices_summary": devices_data,
            "last_api_update_timestamp": coordinator.data.get("last_update_fetch_time", "N/A"),
            "initial_import_complete": coordinator.data.get("initial_import_complete", "N/A"),
        }
    else:
        diag_data["api_data"] = {"message": "No data available from coordinator."}

    _LOGGER.debug("Diagnostics generated for %s", entry.entry_id)
    return diag_data

