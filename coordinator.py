"""DataUpdateCoordinator for Ista Calista integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any, TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_OFFSET
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from pycalista_ista import Device, LoginError, PyCalistaIsta, ServerError

_LOGGER = logging.getLogger(__name__)

type IstaConfigEntry = ConfigEntry[IstaCoordinator]


class IstaDeviceData(TypedDict):
    """Ista device data."""

    devices: dict[str, Device]
    last_update: date


class IstaCoordinator(DataUpdateCoordinator[IstaDeviceData]):
    """Ista Calista data update coordinator."""

    config_entry: IstaConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: IstaConfigEntry, ista: PyCalistaIsta) -> None:
        """Initialize ista Calista data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(days=1),
        )
        self.ista = ista
        self.details: IstaDeviceData = {}

    async def _async_update_data(self) -> IstaDeviceData:
        """Fetch ista Calista data.
        
        Returns:
            A dictionary containing device data and last update timestamp.
            
        Raises:
            ConfigEntryAuthFailed: If authentication fails.
            UpdateFailed: If server is unreachable or returns invalid data.
        """
        try:
            await self.hass.async_add_executor_job(self.ista.login)
            
            if not self.details:
                self.details = await self.async_get_details(init=True)
            else:
                self.details = await self.async_get_details()

            if self.details.devices:
                raise UpdateFailed("No devices found in ista Calista account")

            return self.details

        except ServerError as err:
            raise UpdateFailed(
                "Unable to connect and retrieve data from ista Calista, try again later"
            ) from err
        except LoginError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_exception",
                translation_placeholders={
                    CONF_EMAIL: self.config_entry.data[CONF_EMAIL]
                },
            ) from err
        except Exception as err:
            _LOGGER.exception("Unexpected error occurred while updating ista Calista data")
            raise UpdateFailed(f"Unexpected error: {err}") from err


    async def async_get_details(self, init : bool = False) -> IstaConfigEntry:
        """Retrieve details of consumption units."""
        if init:
            result = await self.hass.async_add_executor_job(
                        self.ista.get_devices_history,
                        datetime.strptime(self.config_entry.data[CONF_OFFSET], "%Y-%m-%d").date()
                    )
        else:
            result = await self.hass.async_add_executor_job(
                    self.ista.get_devices_history
                )  
        return {
            "devices": result,
            "last_update": datetime.now
        }   