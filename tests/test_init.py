"""Test the ista_calista integration setup and teardown."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pycalista_ista import IstaApiError, IstaConnectionError, IstaLoginError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista.const import CONF_LOG_LEVEL, DOMAIN

from .const import MOCK_CONFIG, MOCK_DEVICES


async def test_setup_entry_success(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test successful setup of a config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.entry_id in hass.data[DOMAIN]


async def test_setup_entry_invalid_auth(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test setup of a config entry with invalid auth."""
    mock_pycalista.login.side_effect = IstaLoginError("Auth failed")
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_connection_error(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test setup of a config entry with connection issues."""
    mock_pycalista.login.side_effect = IstaConnectionError("Connection failed")
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_api_error(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test setup of a config entry with a generic API error."""
    mock_pycalista.login.side_effect = IstaApiError("API failure")
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_generic_exception(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test setup fails with a generic, unexpected exception."""
    mock_pycalista.login.side_effect = Exception("Unexpected error")
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_invalid_log_level(
    recorder_mock, caplog, hass: HomeAssistant, mock_pycalista, enable_custom_integrations
):
    """Test setup with an invalid log level in options logs a warning."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        options={CONF_LOG_LEVEL: "INVALID_LEVEL"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        "Invalid log level 'INVALID_LEVEL' configured; defaulting to 'INFO'"
        in caplog.text
    )


async def test_setup_entry_set_log_level_fails(
    recorder_mock, caplog, hass: HomeAssistant, mock_pycalista, enable_custom_integrations
):
    """Test that a failure to set the log level is caught and logged."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, options={CONF_LOG_LEVEL: "DEBUG"}
    )
    entry.add_to_hass(hass)

    with patch(
        "logging.Logger.setLevel", side_effect=ValueError("Invalid level")
    ) as mock_set_level:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert "Failed to set log level: Invalid level" in caplog.text
    mock_set_level.assert_called()


async def test_unload_entry(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test unloading a config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    # Also verify that integration-specific data is cleaned up
    assert hass.data[DOMAIN] == {}


async def test_remove_entry_clears_stats(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that removing the config entry clears associated statistics."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"]
    )
    entry.add_to_hass(hass)

    # Setup the component and entities
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Get the devices before they are removed. The device registry is cleared
    # before async_remove_entry is called.
    device_registry = dr.async_get(hass)
    devices_before_remove = dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    )
    assert len(devices_before_remove) > 0

    with patch(
        "custom_components.ista_calista.get_instance",
    ) as mock_get_instance:
        mock_recorder_instance = mock_get_instance.return_value
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

        # Assert that the recorder's clear_statistics method was called
        mock_recorder_instance.async_clear_statistics.assert_called_once()

        # Verify the statistic_ids passed are correct (slugified)
        called_ids = mock_recorder_instance.async_clear_statistics.call_args[0][0]
        expected_ids = [
            "ista_calista:heating_123_heating",
            "ista_calista:hot_water_456_hot_water",
            "ista_calista:cold_water_789_water",
        ]
        assert sorted(called_ids) == sorted(expected_ids)


async def test_remove_entry_no_devices(
    recorder_mock, hass, mock_pycalista, enable_custom_integrations
):
    """Test removing an entry that has no devices does not fail."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG[CONF_EMAIL])
    entry.add_to_hass(hass)

    with patch("custom_components.ista_calista.dr.async_entries_for_config_entry", return_value=[]), patch(
        "homeassistant.components.recorder.Recorder.async_clear_statistics"
    ) as mock_clear_stats:
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
        mock_clear_stats.assert_not_called()


async def test_remove_entry_device_mapping_fails(
    recorder_mock, caplog, hass, mock_pycalista, enable_custom_integrations
):
    """Test statistics removal handles devices with unmapped models or bad identifiers."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG[CONF_EMAIL])
    entry.add_to_hass(hass)
    device_registry = dr.async_get(hass)

    # Create mock devices: one with an unmapped model, one with no domain identifier
    unmapped_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "unmapped-123")},
        model="Unknown Model",
    )
    bad_identifier_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("other_domain", "bad-id-456")},
        model="Cold Water Meter",
    )

    with patch(
        "homeassistant.components.recorder.Recorder.async_clear_statistics"
    ) as mock_clear_stats:
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

        assert (
            f"Cannot map device model 'Unknown Model' (Device ID: {unmapped_device.id}) to a sensor key"
            in caplog.text
        )
        assert (
            f"Could not find a serial number identifier for device {bad_identifier_device.id}"
            in caplog.text
        )
        mock_clear_stats.assert_not_called()


async def test_remove_entry_no_recorder(
    recorder_mock, caplog, hass, mock_pycalista, enable_custom_integrations
):
    """Test statistics removal when recorder integration is not available."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG[CONF_EMAIL])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch("custom_components.ista_calista.get_instance", return_value=None):
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

    assert (
        f"Recorder integration not available. Could not clear statistics for entry {entry.entry_id}"
        in caplog.text
    )


async def test_remove_device_disallowed(hass: HomeAssistant, enable_custom_integrations):
    """Test that manually removing a device via the UI is disallowed."""
    from custom_components.ista_calista import async_remove_config_entry_device

    assert (
        await async_remove_config_entry_device(
            hass, MockConfigEntry(), dr.DeviceEntry()
        )
        is False
    )