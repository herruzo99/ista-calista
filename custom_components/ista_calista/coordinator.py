"""DataUpdateCoordinator for Ista Calista integration."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import logging
from typing import TypedDict

from pycalista_ista import Device, IstaApiError, IstaConnectionError, IstaLoginError, PyCalistaIsta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_OFFSET, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS, DOMAIN

_LOGGER = logging.getLogger(__name__)


class IstaDeviceData(TypedDict):
    """TypedDict for Ista device data stored in the coordinator."""
    devices: dict[str, Device]


class IstaCoordinator(DataUpdateCoordinator[IstaDeviceData]):
    """Ista Calista data update coordinator."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        ista: PyCalistaIsta,
    ) -> None:
        """Initialize ista Calista data update coordinator."""
        self.ista = ista
        self.config_entry = config_entry

        update_interval_hours = config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS
        )
        update_interval = timedelta(hours=update_interval_hours)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.title})",
            update_interval=update_interval,
            config_entry=config_entry,
        )
        _LOGGER.debug(
            "IstaCoordinator initialized for '%s' with update interval: %s",
            config_entry.title,
            update_interval,
        )

    async def _async_update_data(self) -> IstaDeviceData:
        """Fetch latest data and merge with existing history."""
        _LOGGER.debug("Starting data update for account: %s", self.config_entry.title)
        is_initial_fetch = not self.data or not self.data.get("devices")

        try:
            if is_initial_fetch:
                offset_date_str = self.config_entry.data[CONF_OFFSET]
                fetch_start_date = date.fromisoformat(offset_date_str)
                _LOGGER.debug(
                    "Performing initial historical data fetch from %s.",
                    fetch_start_date.isoformat(),
                )
            else:
                # Fetch last 30 days to catch any delayed readings
                fetch_start_date = dt_util.now().date() - timedelta(days=30)
                _LOGGER.debug(
                    "Performing incremental data fetch from %s.",
                    fetch_start_date.isoformat(),
                )

            fetch_end_date = dt_util.now().date()
            new_devices_history = await self.ista.get_devices_history(
                start=fetch_start_date, end=fetch_end_date
            )
            _LOGGER.debug(
                "Fetched data from API for %d device(s) for period %s to %s.",
                len(new_devices_history),
                fetch_start_date.isoformat(),
                fetch_end_date.isoformat(),
            )

            if is_initial_fetch:
                if not new_devices_history:
                    _LOGGER.warning(
                        "No devices found in Ista Calista account during initial fetch. "
                        "This may be normal if the account is new."
                    )
                    return {"devices": {}}
                _LOGGER.info(
                    "Initial fetch successful. Discovered %d device(s).",
                    len(new_devices_history),
                )
                return {"devices": new_devices_history}

            # This is an incremental update. We must handle devices that are removed from the API.
            # We will build a new state dictionary based on the latest API response.
            _LOGGER.debug("Merging new data with existing coordinator data.")
            current_devices = self.data["devices"]
            updated_devices: dict[str, Device] = {}
            total_new_readings = 0

            # The new API response is the source of truth for which devices exist.
            for serial, device_from_api in new_devices_history.items():
                if serial in current_devices:
                    # The device persists. Merge its history to preserve older data.
                    existing_device = current_devices[serial]
                    
                    # Use a dictionary keyed by date to efficiently merge and deduplicate readings.
                    history_by_date = {reading.date: reading for reading in existing_device.history}
                    new_readings_count = 0
                    for new_reading in device_from_api.history:
                        if new_reading.date not in history_by_date:
                            new_readings_count += 1
                        history_by_date[new_reading.date] = new_reading
                    
                    if new_readings_count > 0:
                        _LOGGER.debug(
                            "Found %d new reading(s) for device %s.",
                            new_readings_count,
                            serial,
                        )
                        total_new_readings += new_readings_count

                    # Update the device object with the fully merged and sorted history.
                    device_from_api.history = sorted(history_by_date.values(), key=lambda r: r.date)
                else:
                    # This is a newly discovered device.
                    _LOGGER.info("Discovered new device during update: %s", serial)
                    total_new_readings += len(device_from_api.history)

                updated_devices[serial] = device_from_api

            removed_count = len(current_devices) - len(updated_devices)
            if removed_count > 0:
                _LOGGER.info("Removed %d stale device(s) no longer present in the API.", removed_count)

            _LOGGER.info(
                "Data update successful. Found %d new reading(s) across %d device(s).",
                total_new_readings,
                len(updated_devices),
            )
            # By returning the newly constructed dictionary, we implicitly drop any
            # devices that were not in the latest API response.
            return {"devices": updated_devices}

        except IstaLoginError as err:
            _LOGGER.warning(
                "Authentication failed during data update. Re-authentication required."
            )
            raise ConfigEntryAuthFailed from err
        except (IstaConnectionError, IstaApiError) as err:
            _LOGGER.warning("Error communicating with Ista Calista API: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception:
            _LOGGER.exception("Unexpected error during coordinator data update.")
            raise UpdateFailed("An unexpected error occurred during data update.")