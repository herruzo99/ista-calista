"""DataUpdateCoordinator for Ista Calista integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from pycalista_ista import (
    BilledReading,
    Device,
    Invoice,
    IstaApiError,
    IstaConnectionError,
    IstaLoginError,
    PyCalistaIsta,
)

from .const import (
    CONF_OFFSET,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class IstaDeviceData(TypedDict):
    """TypedDict for Ista device data stored in the coordinator."""

    devices: dict[str, Device]
    billed_readings: list[BilledReading]
    invoices: list[Invoice]


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
        self.ista: PyCalistaIsta = ista
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

        devices_result, billed_result, invoice_result, invoice_xls_result = await asyncio.gather(
            self.ista.get_devices_history(start=fetch_start_date, end=fetch_end_date),
            self.ista.get_billed_consumption(),
            self.ista.get_invoices(),
            self.ista.get_invoice_xls(),
            return_exceptions=True,
        )

        # Device history failure is fatal
        if isinstance(devices_result, IstaLoginError):
            _LOGGER.warning(
                "Authentication failed during data update. Re-authentication required."
            )
            raise ConfigEntryAuthFailed from devices_result
        if isinstance(devices_result, (IstaConnectionError, IstaApiError)):
            _LOGGER.warning("Error communicating with Ista Calista API: %s", devices_result)
            raise UpdateFailed(
                f"Error communicating with API: {devices_result}"
            ) from devices_result
        if isinstance(devices_result, Exception):
            _LOGGER.exception("Unexpected error during coordinator data update.")
            raise UpdateFailed(
                "An unexpected error occurred during data update."
            ) from devices_result

        new_devices_history: dict[str, Device] = devices_result
        _LOGGER.debug(
            "Fetched data from API for %d device(s) for period %s to %s.",
            len(new_devices_history),
            fetch_start_date.isoformat(),
            fetch_end_date.isoformat(),
        )

        # Non-fatal billing failures
        billed_readings: list[BilledReading] = []
        if isinstance(billed_result, Exception):
            _LOGGER.warning("Failed to fetch billed consumption: %s", billed_result)
        else:
            billed_readings = billed_result

        # Handle invoices: Merge list (with IDs) and XLS (with history)
        invoices_list: list[Invoice] = []
        if isinstance(invoice_result, Exception):
            _LOGGER.warning("Failed to fetch detailed invoice list: %s", invoice_result)
        else:
            invoices_list = invoice_result

        invoices_xls: list[Invoice] = []
        if isinstance(invoice_xls_result, Exception):
            _LOGGER.warning("Failed to fetch invoice XLS: %s", invoice_xls_result)
        else:
            invoices_xls = invoice_xls_result

        # Merge strategy: Use XLS as base (full history), but update with data from the list (which has IDs)
        # Use a more robust key to avoid collisions with null invoice numbers
        def _get_inv_key(i):
            return (i.invoice_number, i.invoice_date, i.device_type, i.amount)

        merged_invoices: dict[tuple, Invoice] = {}
        
        # Add XLS ones first (full history/metadata)
        for inv in invoices_xls:
            merged_invoices[_get_inv_key(inv)] = inv
            
        # Update/Add detailed ones (they have invoice_id)
        for inv in invoices_list:
            key = _get_inv_key(inv)
            if key in merged_invoices:
                existing = merged_invoices[key]
                from dataclasses import replace
                merged_invoices[key] = replace(existing, invoice_id=inv.invoice_id)
            else:
                # If exact match fails, try matching by (date, type, amount) if invoice_number is None
                if inv.invoice_number is None:
                    match_found = False
                    for existing_key, existing_inv in merged_invoices.items():
                        if (existing_inv.invoice_date == inv.invoice_date and 
                            existing_inv.device_type == inv.device_type and 
                            abs(existing_inv.amount - inv.amount) < 0.01):
                            merged_invoices[existing_key] = replace(existing_inv, invoice_id=inv.invoice_id)
                            match_found = True
                            break
                    if not match_found:
                        merged_invoices[key] = inv
                else:
                    merged_invoices[key] = inv

        invoices = list(merged_invoices.values())

        if is_initial_fetch:
            if not new_devices_history:
                _LOGGER.warning(
                    "No devices found in Ista Calista account during initial fetch. "
                    "This may be normal if the account is new."
                )
                return {"devices": {}, "billed_readings": billed_readings, "invoices": invoices}
            _LOGGER.info(
                "Initial fetch successful. Discovered %d device(s).",
                len(new_devices_history),
            )
            return {
                "devices": new_devices_history,
                "billed_readings": billed_readings,
                "invoices": invoices,
            }

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
                history_by_date = {
                    reading.date: reading for reading in existing_device.history
                }
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
                device_from_api.history = sorted(
                    history_by_date.values(), key=lambda r: r.date
                )
            else:
                # This is a newly discovered device.
                _LOGGER.info("Discovered new device during update: %s", serial)
                total_new_readings += len(device_from_api.history)

            updated_devices[serial] = device_from_api

        removed_count = len(current_devices) - len(updated_devices)
        if removed_count > 0:
            _LOGGER.info(
                "Removed %d stale device(s) no longer present in the API.",
                removed_count,
            )

        _LOGGER.info(
            "Data update successful. Found %d new reading(s) across %d device(s).",
            total_new_readings,
            len(updated_devices),
        )
        # By returning the newly constructed dictionary, we implicitly drop any
        # devices that were not in the latest API response.
        return {
            "devices": updated_devices,
            "billed_readings": billed_readings,
            "invoices": invoices,
        }
