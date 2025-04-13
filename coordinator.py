"""DataUpdateCoordinator for Ista Calista integration."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import logging
from typing import Any, TypedDict

from pycalista_ista import (
    Device,
    IstaApiError,
    IstaConnectionError,
    IstaLoginError,
    IstaParserError,
    PyCalistaIsta,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_OFFSET
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util # Use dt_util

# Import constants including the new ones
from .const import DOMAIN, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS

_LOGGER = logging.getLogger(__name__)

type IstaConfigEntry = ConfigEntry[IstaCoordinator]


class IstaDeviceData(TypedDict, total=False): # Use total=False if keys might be missing initially
    """TypedDict for Ista device data stored in the coordinator."""
    devices: dict[str, Device]
    last_update_fetch_time: datetime # Timestamp of when the fetch completed


class IstaCoordinator(DataUpdateCoordinator[IstaDeviceData]):
    """Ista Calista data update coordinator using async library."""

    config_entry: IstaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: IstaConfigEntry,
        ista: PyCalistaIsta,
    ) -> None:
        """Initialize ista Calista data update coordinator."""
        self.ista = ista
        self.coordinator_id = f"ista_coord_{config_entry.entry_id[:8]}"
        self._log_prefix = f"[{self.coordinator_id}] "


    
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} ({config_entry.title})",
            update_interval=timedelta(hours=DEFAULT_UPDATE_INTERVAL_HOURS), # Use interval from options
        )
        _LOGGER.debug(
            "%s Initializing coordinator with update interval: %s",
            self._log_prefix,
            self.update_interval,
        )


    @property
    def is_ready(self) -> bool:
        """Return True if the coordinator has successfully fetched data at least once."""
        return self.last_update_success and bool(self.data.get("devices"))


    async def _async_update_data(self) -> IstaDeviceData:
        """Fetch latest ista Calista data asynchronously."""
        _LOGGER.debug("%s Starting data update cycle", self._log_prefix)

        configured_init_date_str = self.config_entry.data.get(CONF_OFFSET)
        if not configured_init_date_str:
             _LOGGER.error("%s Missing configuration offset date.", self._log_prefix)
             raise UpdateFailed("Configuration offset date is missing.")

        try:
            configured_init_date = date.fromisoformat(configured_init_date_str)
        except ValueError:
            _LOGGER.error("%s Invalid configuration offset date format: %s", self._log_prefix, configured_init_date_str)
            raise UpdateFailed("Invalid configuration offset date format.")

        today = dt_util.now().date() # Use timezone aware now().date()
        if not self.last_update_success or not self.data or not self.data.get("devices"):
            fetch_start_date = configured_init_date
            fetch_end_date = today
            _LOGGER.info("%s Performing initial/recovery data fetch from %s to %s",
                         self._log_prefix, fetch_start_date, fetch_end_date)
        else:
            last_update_fetch_time = self.data.get('last_update_fetch_time', configured_init_date)

            fetch_start_date = today - timedelta(days=30)
            fetch_start_date = max(fetch_start_date, last_update_fetch_time)
            fetch_end_date = today
            _LOGGER.debug("%s Performing incremental data fetch from %s to %s",
                          self._log_prefix, fetch_start_date, fetch_end_date)

        try:
            devices_history = await self.ista.get_devices_history(
                start=fetch_start_date,
                end=fetch_end_date,
            )

            device_count = len(devices_history)
            _LOGGER.debug("%s Retrieved history for %d devices", self._log_prefix, device_count)

            if not devices_history and not self.data.get("devices"):
                 _LOGGER.error("%s No devices found in Ista Calista account during initial fetch.", self._log_prefix)
                 raise UpdateFailed("No devices found in Ista Calista account.")

            new_data: IstaDeviceData = {
                "devices": devices_history,
                "last_update_fetch_time": dt_util.now(), # Use timezone aware now()
            }

            _LOGGER.info(
                "%s Successfully updated data with %d devices. Last fetch: %s",
                self._log_prefix,
                device_count,
                new_data["last_update_fetch_time"].isoformat(),
            )

            return new_data

        except IstaLoginError as err:
            _LOGGER.error("%s Authentication failed: %s", self._log_prefix, err)
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_exception",
                translation_placeholders={CONF_EMAIL: self.config_entry.data[CONF_EMAIL]},
            ) from err
        except (IstaConnectionError, IstaParserError, IstaApiError, ValueError) as err:
            _LOGGER.error("%s Error communicating with Ista Calista API: %s", self._log_prefix, err)
            raise UpdateFailed(f"Error communicating with Ista Calista API: {err}") from err
        except Exception as err:
            _LOGGER.exception("%s Unexpected error occurred during data update", self._log_prefix)
            raise UpdateFailed(f"Unexpected error during data update: {err}") from err
