from datetime import datetime, timezone

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from pycalista_ista import (
    ColdWaterDevice,
    Device,
    HeatingDevice,
    HotWaterDevice,
    Reading,
)

from custom_components.ista_calista.const import CONF_OFFSET

# Mock user configuration (email, password, and offset date)
MOCK_CONFIG = {
    CONF_EMAIL: "test@example.com",
    CONF_PASSWORD: "test-password",
    CONF_OFFSET: "2024-01-01",
}

# Mock device data from the pycalista_ista library

# Heating Device mock data
MOCK_HEATING_DEVICE = HeatingDevice(
    serial_number="heating-123",
    location="Living Room",
)
# Timestamps must be at the top of the hour for statistics.
MOCK_HEATING_DEVICE.history = [
    Reading(date=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), reading=1000.0),
    Reading(date=datetime(2024, 2, 1, 0, 0, tzinfo=timezone.utc), reading=1050.5),
    Reading(date=datetime(2024, 3, 1, 0, 0, tzinfo=timezone.utc), reading=1080.0),
]

# Hot Water Device mock data
MOCK_HOT_WATER_DEVICE = HotWaterDevice(
    serial_number="hot-water-456",
    location="Bathroom",
)
MOCK_HOT_WATER_DEVICE.history = [
    Reading(date=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), reading=50.0),
    Reading(date=datetime(2024, 2, 1, 0, 0, tzinfo=timezone.utc), reading=55.2),
    Reading(date=datetime(2024, 3, 1, 0, 0, tzinfo=timezone.utc), reading=58.9),
]

# Cold Water Device mock data
MOCK_COLD_WATER_DEVICE = ColdWaterDevice(
    serial_number="cold-water-789",
    location="Kitchen",
)
MOCK_COLD_WATER_DEVICE.history = [
    Reading(date=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), reading=100.0),
    Reading(date=datetime(2024, 2, 1, 0, 0, tzinfo=timezone.utc), reading=110.7),
    Reading(date=datetime(2024, 3, 1, 0, 0, tzinfo=timezone.utc), reading=120.1),
]

# --- Edge Case Mock Devices ---

# Device with no location specified
MOCK_DEVICE_NO_LOCATION = HeatingDevice(
    serial_number="heating-no-loc-123", location=None
)
MOCK_DEVICE_NO_LOCATION.history = [
    Reading(date=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), reading=200.0)
]

# Device with history that contains a None reading
MOCK_DEVICE_WITH_NONE_READING = ColdWaterDevice(
    serial_number="water-none-reading", location="Garage"
)
MOCK_DEVICE_WITH_NONE_READING.history = [
    Reading(date=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), reading=500.0),
    Reading(date=datetime(2024, 2, 1, 0, 0, tzinfo=timezone.utc), reading=None),
    Reading(date=datetime(2024, 3, 1, 0, 0, tzinfo=timezone.utc), reading=510.0),
]

# Device with no history readings
MOCK_DEVICE_NO_HISTORY = HotWaterDevice(
    serial_number="hot-water-no-hist", location="Basement"
)
MOCK_DEVICE_NO_HISTORY.history = []

# Generic device to test model fallback
MOCK_GENERIC_DEVICE = Device(serial_number="generic-dev-000", location="Utility Closet")
MOCK_GENERIC_DEVICE.history = [
    Reading(date=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), reading=1.0)
]


# Combined mock devices dictionary
MOCK_DEVICES = {
    MOCK_HEATING_DEVICE.serial_number: MOCK_HEATING_DEVICE,
    MOCK_HOT_WATER_DEVICE.serial_number: MOCK_HOT_WATER_DEVICE,
    MOCK_COLD_WATER_DEVICE.serial_number: MOCK_COLD_WATER_DEVICE,
}
