"""DataUpdateCoordinator for Ista Calista integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_OFFSET
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .pycalista_ista import LoginError, PyCalistaIsta, ServerError

_LOGGER = logging.getLogger(__name__)


class IstaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Ista Calista data update coordinator."""

    config_entry: ConfigEntry
    first_time: bool

    def __init__(self, hass: HomeAssistant, ista: PyCalistaIsta) -> None:
        """Initialize ista Calista data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(days=1),
        )
        self.ista = ista
    async def _async_setup(self):
        self.first_time = True
        return True

    async def _async_update_data(self):
        """Fetch ista Calista data."""
        try:
            await self.hass.async_add_executor_job(self.ista.login)
            self.last_update = date.today()
            if self.first_time:
                self.first_time = False
                return await self.hass.async_add_executor_job(self.ista.get_devices_history, datetime.strptime(self.config_entry.data[CONF_OFFSET], "%Y-%m-%d").date())

            return await self.hass.async_add_executor_job(self.ista.get_devices_history)

        except ServerError as e:
            raise UpdateFailed(
                "Unable to connect and retrieve data from ista Calista, try again later"
            ) from e
        except (LoginError) as e:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_exception",
                translation_placeholders={
                    CONF_EMAIL: self.config_entry.data[CONF_EMAIL]
                },
            ) from e

