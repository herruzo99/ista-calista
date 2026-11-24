import copy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from pycalista_ista import (
    BilledReading,
    ColdWaterDevice,
    Device,
    HeatingDevice,
    HotWaterDevice,
    Invoice,
    Reading,
)

from custom_components.ista_calista.const import CONF_OFFSET, CONF_SEASON_START


@dataclass(frozen=True)
class FakePortalAccount:
    """Stand-in for the library PortalAccount (pycalista-ista >= 0.10.0).

    The frozen contract is ``PortalAccount(account_id: str, label: str)``. The
    class is rebuilt here so the tests do not depend on the installed version.
    """

    account_id: str
    label: str


# Two portal properties of one email, used to prove property isolation.
MOCK_ACCOUNT = FakePortalAccount(account_id="acc-1", label="Calle Mayor 1")
MOCK_ACCOUNT_OTHER = FakePortalAccount(account_id="acc-2", label="Calle Mayor 2")

# Mock user configuration (email, password, and offset date)
MOCK_CONFIG = {
    CONF_EMAIL: "test@example.com",
    CONF_PASSWORD: "test-password",
    CONF_OFFSET: "2024-01-01",
    CONF_SEASON_START: "2024-09-01",
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

# Mock billed readings (one per device, matching MOCK_DEVICES serials)
MOCK_BILLED_READINGS = [
    BilledReading(
        serial_number="heating-123",
        device_type="Radio Distribuidor de costes",
        location="Living Room",
        reading_id=1,
        date=date(2024, 3, 1),
        incidence="4700",
        unit="UN",
        previous_reading=1050.5,
        current_reading=1080.0,
        consumption=29.5,
    ),
    BilledReading(
        serial_number="hot-water-456",
        device_type="Contador Agua Caliente",
        location="Bathroom",
        reading_id=2,
        date=date(2024, 3, 1),
        incidence="4700",
        unit="m3",
        previous_reading=55.2,
        current_reading=58.9,
        consumption=3.7,
    ),
    BilledReading(
        serial_number="cold-water-789",
        device_type="Contador Agua Fría",
        location="Kitchen",
        reading_id=3,
        date=date(2024, 3, 1),
        incidence="4700",
        unit="m3",
        previous_reading=110.7,
        current_reading=120.1,
        consumption=9.4,
    ),
]

# Mock invoices
MOCK_INVOICES = [
    Invoice(
        invoice_id=None,
        invoice_number="4448373/24",
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=45.50,
        device_type="heating",
    ),
]


# --- Second property fixtures (same email, different portal property) ---


def make_second_property_devices():
    """Return meters with serials that differ from MOCK_DEVICES."""
    heating = copy.deepcopy(MOCK_HEATING_DEVICE)
    heating.serial_number = "heating-999"
    heating.location = "Second Property Living Room"
    cold_water = copy.deepcopy(MOCK_COLD_WATER_DEVICE)
    cold_water.serial_number = "cold-water-999"
    cold_water.location = "Second Property Kitchen"
    return {
        heating.serial_number: heating,
        cold_water.serial_number: cold_water,
    }


SECOND_PROPERTY_DEVICES = make_second_property_devices()


class RecordingSessionFactory:
    """Create a fresh mock aiohttp session on every call.

    The integration creates one private session per config entry, so the tests
    need to see each session separately.
    """

    def __init__(self) -> None:
        """Initialize the factory."""
        self.sessions: list[MagicMock] = []

    def __call__(self, *args: object, **kwargs: object) -> MagicMock:
        """Return a new session mock."""
        session = MagicMock(name=f"clientsession-{len(self.sessions)}")
        session.close = AsyncMock()
        session.closed = False
        self.sessions.append(session)
        return session
