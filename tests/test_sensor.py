"""Tests for the Ista Calista sensor platform."""

from homeassistant.const import STATE_UNAVAILABLE
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista.const import DOMAIN

from .const import MOCK_CONFIG, MOCK_DEVICES


async def test_sensor_creation_and_state(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test sensors are created and have correct initial states."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Find the sensor corresponding to the heating device by its value
    heating_device = MOCK_DEVICES["heating-123"]
    expected_value = heating_device.history[-1].reading
    sensors = [
        state
        for state in hass.states.async_all("sensor")
        if state.state != STATE_UNAVAILABLE
    ]
    heating_states = [s for s in sensors if s.state == str(expected_value)]
    assert heating_states, "Heating sensor state not found or incorrect"
    heating_state = heating_states[0]
    # Ensure the entity ID reflects the heating sensor
    assert "heating" in heating_state.entity_id or "energy" in heating_state.entity_id


async def test_sensor_unavailable_when_device_removed(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that sensors become unavailable when device data is removed."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Ensure heating sensor is available initially
    heating_device = MOCK_DEVICES["heating-123"]
    heating_value = heating_device.history[-1].reading
    heating_states = [
        s for s in hass.states.async_all("sensor") if s.state == str(heating_value)
    ]
    assert heating_states, "Heating sensor should exist"
    heating_entity_id = heating_states[0].entity_id

    # Remove device data
    mock_pycalista.get_devices_history.return_value = {}
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Sensor should now be unavailable
    state = hass.states.get(heating_entity_id)
    assert state.state == STATE_UNAVAILABLE
