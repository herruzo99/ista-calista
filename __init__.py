"""The ista Calista integration."""

from __future__ import annotations

import logging

from pycalista_ista import LoginError, PyCalistaIsta, ServerError

from homeassistant.components.recorder import get_instance
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import IstaConfigEntry, IstaCoordinator

# Set up logging
LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Setup the ista Calista integration.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry to setup.

    Returns:
        True if setup was successful, False otherwise.

    Raises:
        ConfigEntryNotReady: If unable to connect to ista Calista.
        ConfigEntryAuthFailed: If authentication fails.
    """
    LOGGER.debug("Setting up ista Calista integration")

    ista = PyCalistaIsta(
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )

    try:
        LOGGER.info("Attempting to login to ista Calista")
        await hass.async_add_executor_job(ista.login)
        LOGGER.info("Login to ista Calista successful")
    except ServerError as e:
        LOGGER.error("Connection to ista Calista failed: %s", str(e))
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connection_exception",
        ) from e
    except LoginError as e:
        LOGGER.error(
            "Authentication to ista Calista failed for %s: %s",
            entry.data[CONF_EMAIL],
            str(e),
        )
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="authentication_exception",
            translation_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
        ) from e

    coordinator = IstaCoordinator(hass, entry, ista)

    # Do the first refresh before setting up platforms
    try:
        LOGGER.info("Performing initial data refresh")
        await coordinator.async_config_entry_first_refresh()
        LOGGER.debug("Initial data refresh successful")
    except ConfigEntryNotReady as err:
        LOGGER.error("Failed to load initial data: %s", str(err))
        raise ConfigEntryNotReady("Failed to load initial data") from err

    entry.runtime_data = coordinator

    LOGGER.info("Setting up platform: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.info("ista Calista integration setup completed successfully")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Unload a config entry."""
    LOGGER.info("Unloading ista Calista integration")

    statistic_ids = [f"{DOMAIN}:{name}" for name in entry.options.values()]
    LOGGER.debug("Clearing statistics: %s", statistic_ids)
    get_instance(hass).async_clear_statistics(statistic_ids)

    result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    LOGGER.info("ista Calista integration unloaded: %s", result)

    return result
