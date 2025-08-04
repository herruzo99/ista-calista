"""Diagnostics platform for ista EcoTrend integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import IstaConfigEntry
from homeassistant.const import CONF_PASSWORD
import logging 

_LOGGER = logging.getLogger(__name__)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IstaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    _LOGGER.error("Generating diagnostics for config entry: %s", entry.entry_id)
    coordinator = entry.runtime_data

    redacted_data = {**entry.data}
    redacted_data[CONF_PASSWORD] = "**REDACTED**"

    last_update_iso = None
    if coordinator.last_update_success and coordinator.data:
        # Find the most recent reading across all devices to serve as the last update time.
        all_readings = [
            reading.date
            for device in coordinator.data.get("devices", {}).values()
            for reading in device.history
        ]
        if all_readings:
            last_update_iso = max(all_readings).isoformat()

    diag_data = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "version": entry.version,
            "data": redacted_data,
            "options": entry.options,
            "source": str(entry.source),
            "unique_id": entry.unique_id,
        },
        "coordinator_status": {
            "last_update_success": coordinator.last_update_success,
            "last_update": last_update_iso,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
        },
        "api_data_summary": {},
    }

    if coordinator.data and coordinator.data.get("devices"):
        devices_summary = []
        for serial, device in coordinator.data["devices"].items():
            hashed_serial = str(hash(serial))[-8:]
            devices_summary.append({
                "serial_hash": hashed_serial,
                "type": device.__class__.__name__,
                "location": device.location,
                "history_count": len(device.history),
                "last_reading_date": (
                    device.last_reading.date.isoformat() if device.last_reading else None
                ),
            })
        diag_data["api_data_summary"] = {
            "device_count": len(devices_summary),
            "devices": devices_summary,
        }
    else:
        _LOGGER.debug("No coordinator data available for diagnostics.")
        diag_data["api_data_summary"] = {"message": "No data available from coordinator."}

    return diag_data