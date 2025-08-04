"""Test the Ista Calista data update coordinator."""

import copy
from datetime import datetime, timedelta, timezone

import pytest
from homeassistant.util import dt as dt_util
from pycalista_ista import IstaApiError, IstaConnectionError, IstaLoginError, Reading
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ista_calista.const import DOMAIN

from .const import MOCK_CONFIG, MOCK_DEVICES


async def test_initial_fetch(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that initial fetch populates data correctly."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.last_update_success is True
    # Check that devices from MOCK_DEVICES are present
    assert set(coordinator.data["devices"].keys()) == set(MOCK_DEVICES.keys())


async def test_incremental_update_merging(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test incremental update merges new readings and drops removed devices."""
    initial_data = copy.deepcopy(MOCK_DEVICES)
    mock_pycalista.get_devices_history.return_value = initial_data
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    # Prepare updated data with an additional reading for the heating device
    updated_heating = copy.deepcopy(initial_data["heating-123"])
    # Statistics timestamps must be at the top of the hour.
    new_reading_date = datetime(2024, 4, 1, 0, 0, tzinfo=timezone.utc)
    new_reading = Reading(date=new_reading_date, reading=1100.0)
    updated_heating.history.append(new_reading)
    mock_pycalista.get_devices_history.return_value = {"heating-123": updated_heating}
    # Advance time to trigger update
    future_time = dt_util.now() + timedelta(
        hours=coordinator.update_interval.total_seconds() / 3600 + 1
    )
    async_fire_time_changed(hass, future_time)
    await hass.async_block_till_done()

    # Check that new reading is merged into coordinator data
    coor_heating = coordinator.data["devices"]["heating-123"]
    assert any(r.reading == 1100.0 for r in coor_heating.history)


async def test_device_removal(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that devices no longer in the API response are removed from coordinator data."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert len(coordinator.data["devices"]) == 3

    # API update now only returns the heating device
    updated_devices = {"heating-123": MOCK_DEVICES["heating-123"]}
    mock_pycalista.get_devices_history.return_value = updated_devices
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Verify that only the heating device remains in the coordinator data
    assert len(coordinator.data["devices"]) == 1
    assert "heating-123" in coordinator.data["devices"]
    assert "hot-water-456" not in coordinator.data["devices"]
    assert "cold-water-789" not in coordinator.data["devices"]


@pytest.mark.parametrize(
    "error_cls",
    [IstaLoginError, IstaConnectionError, IstaApiError, Exception],
)
async def test_update_errors(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista, error_cls
):
    """Test that errors during update set last_update_success to False."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    # Simulate error on update
    mock_pycalista.get_devices_history.side_effect = error_cls("API error")
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
