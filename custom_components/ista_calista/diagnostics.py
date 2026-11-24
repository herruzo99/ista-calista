"""Diagnostics platform for ista EcoTrend integration."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import IstaConfigEntry
from .const import CONF_ACCOUNT_ID, CONF_ACCOUNT_LABEL

REDACTED = "**REDACTED**"


def _account_id_token(account_id: str) -> str:
    """Return a short, non-reversible token for a property ID."""
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:8]


def _redact_unique_id(unique_id: str | None, account_id: str | None) -> str | None:
    """Remove the property ID from a unique ID.

    The unique ID is ``<email>:<account_id>``. The email is a known,
    pre-existing diagnostics gap; the property ID is replaced by a short hash,
    so the ID is not recoverable from the diagnostics.
    """
    if not unique_id or not account_id:
        return unique_id
    return unique_id.replace(account_id, _account_id_token(account_id))


def _redact_title(title: str, label: str | None) -> str:
    """Remove the property label from the entry title."""
    if not label:
        return title
    return title.replace(label, REDACTED)

_LOGGER = logging.getLogger(__name__)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IstaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    _LOGGER.debug("Generating diagnostics for config entry: %s", entry.entry_id)
    coordinator = entry.runtime_data

    redacted_data: dict[str, Any] = {**entry.data}
    redacted_data[CONF_PASSWORD] = REDACTED
    # The property label is user-facing and can be an address, and the property
    # ID identifies the portal account. Both stay out of diagnostics.
    account_id = entry.data.get(CONF_ACCOUNT_ID)
    label = entry.data.get(CONF_ACCOUNT_LABEL)
    if CONF_ACCOUNT_ID in redacted_data:
        redacted_data[CONF_ACCOUNT_ID] = REDACTED
    if CONF_ACCOUNT_LABEL in redacted_data:
        redacted_data[CONF_ACCOUNT_LABEL] = REDACTED

    last_update_iso = None
    if coordinator.last_update_success and coordinator.data:
        # Find the most recent reading across all devices to serve as the last update time.
        all_readings: list[datetime] = [
            reading.date
            for device in coordinator.data.get("devices", {}).values()
            for reading in device.history
        ]
        if all_readings:
            last_update_iso = max(all_readings).isoformat()

    diag_data = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "title": _redact_title(entry.title, label),
            "version": entry.version,
            "data": redacted_data,
            "options": entry.options,
            "source": str(entry.source),
            "unique_id": _redact_unique_id(entry.unique_id, account_id),
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
        devices_summary: list[dict[str, Any]] = []
        for serial, device in coordinator.data["devices"].items():
            hashed_serial = hashlib.sha256(serial.encode()).hexdigest()[:8]
            devices_summary.append(
                {
                    "serial_hash": hashed_serial,
                    "type": device.__class__.__name__,
                    "location": device.location,
                    "history_count": len(device.history),
                    "last_reading_date": (
                        device.last_reading.date.isoformat()
                        if device.last_reading
                        else None
                    ),
                }
            )
        diag_data["api_data_summary"] = {
            "device_count": len(devices_summary),
            "devices": devices_summary,
        }
    else:
        _LOGGER.debug("No coordinator data available for diagnostics.")
        diag_data["api_data_summary"] = {
            "message": "No data available from coordinator."
        }

    return diag_data
