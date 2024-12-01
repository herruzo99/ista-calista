"""The ista Calista integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import IstaCoordinator
from .pycalista_ista import LoginError, PyCalistaIsta, ServerError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

type IstaConfigEntry = ConfigEntry[IstaCoordinator]




async def async_setup_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Set up ista Calista from a config entry."""
    ista = PyCalistaIsta(
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )
    try:
        pass #await hass.async_add_executor_job(ista.login)
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
    coordinator = IstaCoordinator(hass, ista)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # async def __back_fill_data(
    #     call: ServiceCall
    # ) -> ServiceResponse:
    #     """Get history data from ista Calista."""
    #     _LOGGER.warning("__back_fill_data")
    #     entities = [
    #         entity
    #         for entity in hass.states.async_all()
    #         if (entity.entity_id.startswith(DOMAIN + ".") if entity.entity_id else False)
    #     ]

    #     # Example: Log and update each entity
    #     for entity in entities:
    #         _LOGGER.warning(f"Found entity: {entity.entity_id}, State: {entity.state}, Object id: {entity.object_id}")
    #         # Optionally trigger state updates or handle data


    # hass.services.async_register(
    #     DOMAIN,
    #     "backfill_long_term_statistics",
    #     service_func=__back_fill_data,
    # )


    return True


async def async_unload_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
