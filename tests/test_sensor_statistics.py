"""Tests for the statistics import logic of the sensor platform."""

import logging
import copy
from datetime import datetime, timezone
from unittest.mock import patch

from homeassistant.components.recorder.statistics import StatisticData
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pycalista_ista import Reading

from custom_components.ista_calista.const import DOMAIN
from tests.const import (
    MOCK_CONFIG,
    MOCK_DEVICES,
    MOCK_DEVICE_NO_HISTORY,
    MOCK_DEVICE_WITH_NONE_READING,
)


@patch("custom_components.ista_calista.sensor.async_add_external_statistics")
async def test_statistics_import_initial(
    mock_add_stats, recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that initial statistics are imported for sensors."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"]
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert mock_add_stats.call_count == 3  # For 3 devices with LTS

    # Check heating sensor statistics
    heating_call = next(
        call
        for call in mock_add_stats.call_args_list
        if call.args[1]["statistic_id"] == "ista_calista:heating_123_heating"
    )
    stats_data: list[StatisticData] = heating_call.args[2]
    assert len(stats_data) == 3
    assert stats_data[0]["sum"] == 0.0  # First import sum is 0
    assert stats_data[0]["state"] == 1000.0
    assert stats_data[1]["sum"] == 50.5
    assert round(stats_data[2]["sum"], 2) == 80.0


@patch("custom_components.ista_calista.sensor.async_add_external_statistics")
async def test_statistics_import_incremental(
    mock_add_stats, recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that incremental statistics are correctly imported."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"]
    )
    entry.add_to_hass(hass)

    # Simulate existing statistics in the database
    last_stat_time = datetime(2024, 2, 1, 0, 0, tzinfo=timezone.utc)
    mock_last_stats = {
        "ista_calista:heating_123_heating": [
            {
                "end": last_stat_time.timestamp(),
                "start": last_stat_time.timestamp(),
                "last_reset": datetime(
                    2024, 1, 1, 0, 0, tzinfo=timezone.utc
                ).timestamp(),
                "state": 1050.5,
                "sum": 50.5,
            }
        ]
    }
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)

    with patch(
        "custom_components.ista_calista.sensor.get_last_statistics",
        return_value=mock_last_stats,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Only one new reading should be imported for the heating sensor
        heating_call = next(
            call
            for call in mock_add_stats.call_args_list
            if call.args[1]["statistic_id"] == "ista_calista:heating_123_heating"
        )
        stats_data: list[StatisticData] = heating_call.args[2]
        assert len(stats_data) == 1
        assert stats_data[0]["state"] == 1080.0
        assert round(stats_data[0]["sum"], 2) == 80.0  # 50.5 (existing) + 29.5 (new)


@patch("custom_components.ista_calista.sensor.async_add_external_statistics")
async def test_statistics_import_no_history(
    mock_add_stats, caplog, recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that statistics import is skipped for a device with no history."""
    caplog.set_level(logging.DEBUG, logger="custom_components.ista_calista.sensor")
    mock_pycalista.get_devices_history.return_value = {
        "no-hist-dev": MOCK_DEVICE_NO_HISTORY
    }
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The sensor is created, but LTS import should be skipped
    assert "no device data or history available" in caplog.text
    mock_add_stats.assert_not_called()


@patch("custom_components.ista_calista.sensor.async_add_external_statistics")
async def test_statistics_import_no_new_readings(
    mock_add_stats, caplog, recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test statistics import when there are no new readings to add."""
    caplog.set_level(logging.DEBUG, logger="custom_components.ista_calista.sensor")
    # Isolate mock data to only the heating sensor to avoid log pollution
    mock_pycalista.get_devices_history.return_value = {
        "heating-123": copy.deepcopy(MOCK_DEVICES["heating-123"])
    }
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)

    # Simulate last stat time is after the last reading in our mock data
    last_stat_time = dt_util.now()
    mock_last_stats = {
        "ista_calista:heating_123_heating": [{"end": last_stat_time.timestamp()}]
    }

    with patch(
        "custom_components.ista_calista.sensor.get_last_statistics",
        return_value=mock_last_stats,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert "No new readings to import" in caplog.text


@patch("custom_components.ista_calista.sensor.async_add_external_statistics")
async def test_statistics_import_with_none_reading(
    mock_add_stats, caplog, recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that statistics import skips over None readings."""
    caplog.set_level(logging.DEBUG, logger="custom_components.ista_calista.sensor")
    mock_pycalista.get_devices_history.return_value = {
        "water-none-reading": MOCK_DEVICE_WITH_NONE_READING
    }
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "Skipping reading with None value" in caplog.text
    mock_add_stats.assert_called_once()
    stats_data: list[StatisticData] = mock_add_stats.call_args[0][2]

    # Should import the first and third readings, skipping the second (None)
    assert len(stats_data) == 2
    assert stats_data[0]["state"] == 500.0
    assert stats_data[0]["sum"] == 0.0  # First reading
    assert stats_data[1]["state"] == 510.0
    assert stats_data[1]["sum"] == 10.0  # Increase from 500 to 510


@patch("custom_components.ista_calista.sensor.async_add_external_statistics")
async def test_statistics_meter_reset(
    mock_add_stats, recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test statistics import handles a meter reset correctly."""
    local_mock_devices = copy.deepcopy(MOCK_DEVICES)
    reset_device = local_mock_devices["heating-123"]
    reset_device.history = [
        Reading(date=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), reading=1000.0),
        Reading(date=datetime(2024, 2, 1, 0, 0, tzinfo=timezone.utc), reading=1050.5),
        Reading(date=datetime(2024, 3, 1, 0, 0, tzinfo=timezone.utc), reading=5.0),
        Reading(date=datetime(2024, 4, 1, 0, 0, tzinfo=timezone.utc), reading=15.0),
    ]
    mock_pycalista.get_devices_history.return_value = {"heating-123": reset_device}

    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"]
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    heating_call = next(
        call
        for call in mock_add_stats.call_args_list
        if call.args[1]["statistic_id"] == "ista_calista:heating_123_heating"
    )
    stats_data: list[StatisticData] = heating_call.args[2]

    assert len(stats_data) == 4
    # Reading 1: Base reading
    assert stats_data[0]["sum"] == 0.0
    assert stats_data[0]["state"] == 1000.0
    # Reading 2: Normal increase
    assert round(stats_data[1]["sum"], 2) == 50.5
    assert stats_data[1]["state"] == 1050.5
    # Reading 3: Meter reset
    assert round(stats_data[2]["sum"], 2) == 55.5  # 50.5 (previous sum) + 5.0 (new state)
    assert stats_data[2]["state"] == 5.0
    assert stats_data[2]["last_reset"] == datetime(2024, 3, 1, 0, 0, tzinfo=timezone.utc)
    # Reading 4: Normal increase after reset
    assert round(stats_data[3]["sum"], 2) == 65.5  # 55.5 (previous sum) + 10.0 (increase)
    assert stats_data[3]["state"] == 15.0
    assert stats_data[3]["last_reset"] == stats_data[2]["last_reset"]
