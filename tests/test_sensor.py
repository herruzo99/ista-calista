"""Tests for the Ista Calista sensor platform."""

import logging
import copy
from unittest.mock import patch

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista.const import DOMAIN

from .const import (
    MOCK_CONFIG,
    MOCK_DEVICES,
    MOCK_DEVICE_NO_LOCATION,
    MOCK_GENERIC_DEVICE,
)


async def test_sensor_creation_and_state(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test sensors are created and have correct initial states."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    heating_device = MOCK_DEVICES["heating-123"]
    expected_value = heating_device.history[-1].reading

    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "heating-123_heating"
    )
    assert entity is not None

    state = hass.states.get(entity)
    assert state is not None
    assert state.state == str(expected_value)


async def test_setup_entry_with_no_devices(
    recorder_mock, caplog, hass, enable_custom_integrations, mock_pycalista
):
    """Test sensor setup when the coordinator has no initial device data."""
    caplog.set_level(logging.DEBUG, logger="custom_components.ista_calista")
    mock_pycalista.get_devices_history.return_value = {}
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The coordinator runs, but no entities should be created
    assert len(hass.states.async_entity_ids("sensor")) == 0
    assert "No devices in coordinator data. Skipping entity setup." in caplog.text


async def test_sensor_device_properties_no_location(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test fallback device name when location is not provided."""
    mock_pycalista.get_devices_history.return_value = {
        "heating-no-loc-123": MOCK_DEVICE_NO_LOCATION
    }
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "heating-no-loc-123_heating"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, "heating-no-loc-123")}
    )
    assert device is not None
    assert device.name == "Ista Meter -123"


async def test_sensor_device_generic_model(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test fallback device model for unknown device types."""
    mock_pycalista.get_devices_history.return_value = {
        "generic-dev-000": MOCK_GENERIC_DEVICE
    }
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, "generic-dev-000")}
    )
    assert device is not None
    assert device.model == "Generic Meter"


async def test_sensor_unavailable_when_device_removed(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that sensors become unavailable when device data is removed."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    heating_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "heating-123_heating"
    )
    assert heating_entity_id is not None
    assert hass.states.get(heating_entity_id).state != STATE_UNAVAILABLE

    # Remove device data
    mock_pycalista.get_devices_history.return_value = {}
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Sensor should now be unavailable
    state = hass.states.get(heating_entity_id)
    assert state.state == STATE_UNAVAILABLE


async def test_sensor_unavailable_and_native_value(
    recorder_mock, caplog, hass, enable_custom_integrations, mock_pycalista
):
    """Test sensor state and logging when it becomes unavailable."""
    caplog.set_level(logging.DEBUG, logger="custom_components.ista_calista.sensor")
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    sensor_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "heating-123_heating"
    )
    assert hass.states.get(sensor_entity_id).state != STATE_UNAVAILABLE

    # Remove the device from coordinator data to make the sensor unavailable
    coordinator = hass.data[DOMAIN][entry.entry_id]
    del coordinator.data["devices"]["heating-123"]
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    state = hass.states.get(sensor_entity_id)
    assert state.state == STATE_UNAVAILABLE
    print(caplog.text)
    assert "Sensor heating-123_heating is unavailable." in caplog.text