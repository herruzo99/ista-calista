"""Tests for the diagnostics platform."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.ista_calista.const import DOMAIN

from .const import MOCK_CONFIG, MOCK_DEVICE_NO_HISTORY, MOCK_DEVICES


async def test_diagnostics(
    recorder_mock,
    hass,
    hass_client,
    mock_pycalista,
    enable_custom_integrations,
):
    """Test diagnostics."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics
    assert diagnostics["config_entry"]["entry_id"] == entry.entry_id
    assert diagnostics["config_entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["api_data_summary"]["device_count"] == 3
    assert "devices" in diagnostics["api_data_summary"]
    assert len(diagnostics["api_data_summary"]["devices"]) == 3
    assert "serial_hash" in diagnostics["api_data_summary"]["devices"][0]


async def test_diagnostics_no_data(
    recorder_mock, hass, hass_client, mock_pycalista, enable_custom_integrations
):
    """Test diagnostics when the coordinator has no data."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Simulate a failed update where coordinator data is None
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.data = None
    coordinator.last_update_success = False

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["coordinator_status"]["last_update_success"] is False
    assert diagnostics["api_data_summary"] == {
        "message": "No data available from coordinator."
    }


async def test_diagnostics_device_with_no_history(
    recorder_mock, hass, hass_client, mock_pycalista, enable_custom_integrations
):
    """Test diagnostics for a device that has no consumption history."""
    mock_pycalista.get_devices_history.return_value = {
        "no-hist-dev": MOCK_DEVICE_NO_HISTORY
    }
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    device_summary = diagnostics["api_data_summary"]["devices"][0]

    assert device_summary["history_count"] == 0
    assert device_summary["last_reading_date"] is None
