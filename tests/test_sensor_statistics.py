"""Tests for the statistics import logic of the sensor platform."""

from datetime import datetime, timezone
from unittest.mock import patch

from homeassistant.components.recorder.statistics import StatisticData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista.const import DOMAIN
from tests.const import MOCK_CONFIG, MOCK_DEVICES


@patch("custom_components.ista_calista.sensor.async_add_external_statistics")
async def test_statistics_import_initial(
    mock_add_stats, recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that initial statistics are imported for sensors."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
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
    assert stats_data[2]["sum"] == 80.0


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
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES

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
async def test_statistics_meter_reset(
    mock_add_stats, recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test statistics import handles a meter reset correctly."""
    reset_device = MOCK_DEVICES["heating-123"].__class__(
        serial_number="heating-123", location="Living Room"
    )
    reset_device.history = [
        MOCK_DEVICES["heating-123"].history[0],
        MOCK_DEVICES["heating-123"].history[1],
        # Meter resets, reading is lower
        type(MOCK_DEVICES["heating-123"].history[2])(
            date=datetime(2024, 3, 1, tzinfo=timezone.utc), reading=5.0
        ),
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

    assert len(stats_data) == 3
    assert stats_data[0]["sum"] == 0.0
    assert stats_data[1]["sum"] == 50.5
    # After reset, sum becomes the new reading
    assert stats_data[2]["sum"] == 5.0 + 50.5
    # last_reset should be updated to the time of the reset
    assert stats_data[2]["last_reset"] == datetime(2024, 3, 1, tzinfo=timezone.utc)
