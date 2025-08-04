"""Tests for the diagnostics platform."""
from http import HTTPStatus

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from homeassistant.setup import async_setup_component

from custom_components.ista_calista.const import DOMAIN

from .const import MOCK_CONFIG, MOCK_DEVICES
from syrupy.assertion import SnapshotAssertion

from homeassistant.loader import (
    async_get_integrations
)

from http import HTTPStatus
from typing import cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.setup import async_setup_component
from homeassistant.util.json import JsonObjectType

from pytest_homeassistant_custom_component.typing import ClientSessionGenerator



async def test_diagnostics(recorder_mock, 
    hass, hass_client, mock_pycalista, 
    enable_custom_integrations,
    snapshot: SnapshotAssertion):
    """Test diagnostics."""
    

    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    print("AAA", diagnostics)
    #assert diag == snapshot

    assert diagnostics
    assert diagnostics["config_entry"]["entry_id"] == entry.entry_id
    assert diagnostics["config_entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["api_data_summary"]["device_count"] == 3
    assert "devices" in diagnostics["api_data_summary"]
    assert len(diagnostics["api_data_summary"]["devices"]) == 3
    assert "serial_hash" in diagnostics["api_data_summary"]["devices"][0]

   
