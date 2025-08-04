"""Test the ista_calista integration setup and teardown."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from pycalista_ista import IstaConnectionError, IstaLoginError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista.const import DOMAIN

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
    dr.async_entries_for_config_entry(device_registry, entry.entry_id)

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
