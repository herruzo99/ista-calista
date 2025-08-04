from datetime import datetime, timezone
from pycalista_ista import ColdWaterDevice, HotWaterDevice, HeatingDevice, Reading
from custom_components.ista_calista.const import CONF_OFFSET
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

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

# Combined mock devices dictionary
MOCK_DEVICES = {
    MOCK_HEATING_DEVICE.serial_number: MOCK_HEATING_DEVICE,
    MOCK_HOT_WATER_DEVICE.serial_number: MOCK_HOT_WATER_DEVICE,
    MOCK_COLD_WATER_DEVICE.serial_number: MOCK_COLD_WATER_DEVICE,
}