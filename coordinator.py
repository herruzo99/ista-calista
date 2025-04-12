"""DataUpdateCoordinator for Ista Calista integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any, TypedDict

from pycalista_ista import Device, LoginError, PyCalistaIsta, ServerError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_OFFSET
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel("DEBUG")

type IstaConfigEntry = ConfigEntry[IstaCoordinator]


class IstaDeviceData(TypedDict):
    """Ista device data."""

    devices: dict[str, Device]
    last_update: date


class IstaCoordinator(DataUpdateCoordinator[IstaDeviceData]):
    """Ista Calista data update coordinator."""

    config_entry: IstaConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: IstaConfigEntry, ista: PyCalistaIsta
    ) -> None:
        """Initialize ista Calista data update coordinator."""
        self.coordinator_id = f"coordinator_{config_entry.entry_id[:8]}"
        _LOGGER.debug(
            "[%s] Initializing Ista coordinator with config entry ID: %s",
            self.coordinator_id,
            config_entry.entry_id,
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(days=1),
        )

        self.ista = ista
        self.details: IstaDeviceData = {}
        _LOGGER.debug(
            "[%s] Coordinator initialized with update interval: %s",
            self.coordinator_id,
            timedelta(days=1),
        )

    async def _async_update_data(self) -> IstaDeviceData:
        """Fetch ista Calista data.

        Returns:
            A dictionary containing device data and last update timestamp.

        Raises:
            ConfigEntryAuthFailed: If authentication fails.
            UpdateFailed: If server is unreachable or returns invalid data.
        """
        _LOGGER.debug("[%s] Starting data update", self.coordinator_id)

        try:
            _LOGGER.debug("[%s] Attempting login to Ista Calista", self.coordinator_id)
            await self.hass.async_add_executor_job(self.ista.login)
            _LOGGER.debug("[%s] Login successful", self.coordinator_id)

            if not self.details:
                _LOGGER.debug(
                    "[%s] No existing details, fetching full history",
                    self.coordinator_id,
                )
                self.details = await self.async_get_details(init=True)
            else:
                _LOGGER.debug("[%s] Updating existing details", self.coordinator_id)
                self.details = await self.async_get_details()

            device_count = (
                len(self.details["devices"]) if self.details.get("devices") else 0
            )
            _LOGGER.debug(
                "[%s] Retrieved %d devices", self.coordinator_id, device_count
            )

            if not self.details["devices"]:
                _LOGGER.error(
                    "[%s] No devices found in Ista Calista account", self.coordinator_id
                )
                raise UpdateFailed("No devices found in ista Calista account")

            _LOGGER.info(
                "[%s] Successfully updated data with %d devices, last update: %s",
                self.coordinator_id,
                device_count,
                self.details["last_update"],
            )

            return self.details

        except ServerError as err:
            _LOGGER.error(
                "[%s] Server error while connecting to Ista Calista: %s",
                self.coordinator_id,
                str(err),
            )
            raise UpdateFailed(
                "Unable to connect and retrieve data from ista Calista, try again later"
            ) from err

        except LoginError as err:
            _LOGGER.error(
                "[%s] Authentication failed for account %s: %s",
                self.coordinator_id,
                self.config_entry.data[CONF_EMAIL],
                str(err),
            )
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_exception",
                translation_placeholders={
                    CONF_EMAIL: self.config_entry.data[CONF_EMAIL]
                },
            ) from err

        except Exception as err:
            _LOGGER.exception(
                "[%s] Unexpected error occurred while updating Ista Calista data: %s",
                self.coordinator_id,
                str(err),
            )
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_get_details(self, init: bool = False) -> IstaDeviceData:
        """Retrieve details of consumption units."""
        configured_init_date = datetime.strptime(
            self.config_entry.data[CONF_OFFSET], "%Y-%m-%d"
        ).date()

        if init:
            _LOGGER.debug(
                "[%s] Fetching full device history since %s",
                self.coordinator_id,
                configured_init_date,
            )
            result = await self.hass.async_add_executor_job(
                self.ista.get_devices_history, configured_init_date
            )
        else:
            fetch_date = max(configured_init_date, date.today() - timedelta(days=30))
            _LOGGER.debug(
                "[%s] Fetching incremental device history since %s",
                self.coordinator_id,
                fetch_date,
            )
            result = await self.hass.async_add_executor_job(
                self.ista.get_devices_history, fetch_date
            )

        # Log details about each device retrieved
        for serial, device in result.items():
            _LOGGER.debug(
                "[%s] Retrieved device - Serial: %s, Type: %s, Location: %s, Readings: %d",
                self.coordinator_id,
                serial,
                type(device).__name__,
                device.location,
                len(device.history) if device.history else 0,
            )

        current_time = datetime.now()
        _LOGGER.debug(
            "[%s] Completed fetching details at %s with %d devices",
            self.coordinator_id,
            current_time,
            len(result),
        )

        return {"devices": result, "last_update": current_time}
