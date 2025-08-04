"""Test entry lifecycle: reload behavior."""
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.ista_calista.const import DOMAIN
from .const import MOCK_CONFIG

async def test_reload_entry(recorder_mock,  hass, enable_custom_integrations, mock_pycalista):
    """Test reloading a config entry reloads the integration."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
