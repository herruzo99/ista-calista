"""Unit selection from the unit the portal reports."""

from __future__ import annotations

from homeassistant.const import UnitOfEnergy, UnitOfVolume

from custom_components.ista_calista.sensor import (
    _device_unit,
    _statistics_unit,
    _unit_class,
)
from pycalista_ista.models.cold_water_device import ColdWaterDevice
from pycalista_ista.models.heating_device import HeatingDevice


def test_allocator_entity_has_no_unit():
    device = HeatingDevice("141740872", "(1-Cocina1)", "UN")
    assert _device_unit(device) is None
    assert _unit_class(_device_unit(device)) is None


def test_allocator_statistics_stay_kwh_for_the_energy_panel():
    # The entity is unit-less, but the Energy dashboard only accepts kWh or m3.
    device = HeatingDevice("141740872", "(1-Cocina1)", "UN")
    assert _statistics_unit(device) == UnitOfEnergy.KILO_WATT_HOUR
    assert _unit_class(_statistics_unit(device)) == "energy"


def test_water_statistics_keep_cubic_metres():
    device = ColdWaterDevice("414293326", "(1-Baño)", "m3")
    assert _statistics_unit(device) == UnitOfVolume.CUBIC_METERS


def test_heating_meter_without_a_unit_keeps_kwh():
    device = HeatingDevice("141740872", "(1-Cocina1)", "")
    assert _device_unit(device) == UnitOfEnergy.KILO_WATT_HOUR
    assert _unit_class(_device_unit(device)) == "energy"


def test_water_meter_reports_m3():
    device = ColdWaterDevice("414293326", "(1-Baño)", "m3")
    assert _device_unit(device) == UnitOfVolume.CUBIC_METERS
    assert _unit_class(_device_unit(device)) == "volume"


def test_unknown_unit_falls_back_to_the_device_type():
    assert _device_unit(HeatingDevice("1", "x", "furlongs")) == UnitOfEnergy.KILO_WATT_HOUR
    assert _device_unit(ColdWaterDevice("2", "y", "??")) == UnitOfVolume.CUBIC_METERS


def test_unit_is_case_and_space_insensitive():
    assert _device_unit(HeatingDevice("1", "x", " un ")) is None
    assert _device_unit(ColdWaterDevice("2", "y", "M3")) == UnitOfVolume.CUBIC_METERS
