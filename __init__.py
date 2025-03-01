"""The ista Calista integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import IstaConfigEntry, IstaCoordinator
from pycalista_ista import LoginError, PyCalistaIsta, ServerError

_LOGGER = logging.getLogger(__name__)

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
    ista = PyCalistaIsta(
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )
    try:
        await hass.async_add_executor_job(ista.login)
    except ServerError as e:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connection_exception",
        ) from e
    except LoginError as e:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="authentication_exception",
            translation_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
        ) from e

    coordinator = IstaCoordinator(hass, entry, ista)
    
    # Do the first refresh before setting up platforms
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        raise ConfigEntryNotReady("Failed to load initial data") from err

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
