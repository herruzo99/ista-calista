"""Sensor platform for the Ista Calista integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Final

from homeassistant.components.recorder import get_instance  # type: ignore[attr-defined]
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONF_EMAIL, EntityCategory, UnitOfEnergy, UnitOfVolume
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from pycalista_ista import BilledReading, ColdWaterDevice, Device, HeatingDevice, HotWaterDevice, Invoice

from .const import (
    CONF_SEASON_START,
    CONF_SEASON_START_DAY,
    CONF_SEASON_START_MONTH,
    DEFAULT_SEASON_START_DAY,
    DEFAULT_SEASON_START_MONTH,
    DOMAIN,
    LTS_UPDATED_EVENT,
    MANUFACTURER,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import IstaCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CalistaSensorEntityDescription(SensorEntityDescription):
    """Describes an Ista Calista sensor entity."""

    exists_fn: Callable[[Device], bool] = lambda _: True
    value_fn: Callable[[Device], StateType]
    generate_lts: bool = False


@dataclass(frozen=True, kw_only=True)
class CalistaBilledSensorEntityDescription(SensorEntityDescription):
    """Describes a billed-consumption sensor (per device, from BilledReading)."""

    value_fn: Callable[[BilledReading], StateType]


@dataclass(frozen=True, kw_only=True)
class CalistaAccountSensorEntityDescription(SensorEntityDescription):
    """Describes an account-level sensor (e.g., latest invoice)."""

    value_fn: Callable[[dict], StateType]


@dataclass(frozen=True, kw_only=True)
class CalistaInvoiceSensorEntityDescription(SensorEntityDescription):
    """Describes an invoice-level sensor (per service type)."""

    device_type: str
    value_fn: Callable[[list[Invoice], str], StateType]


SENSOR_DESCRIPTIONS: Final[tuple[CalistaSensorEntityDescription, ...]] = (
    CalistaSensorEntityDescription(
        key="water",
        translation_key="water",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        value_fn=lambda device: (
            device.last_reading.reading if device.last_reading else None
        ),
        exists_fn=lambda device: isinstance(device, ColdWaterDevice),
        generate_lts=True,
    ),
    CalistaSensorEntityDescription(
        key="hot_water",
        translation_key="hot_water",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        value_fn=lambda device: (
            device.last_reading.reading if device.last_reading else None
        ),
        exists_fn=lambda device: isinstance(device, HotWaterDevice),
        generate_lts=True,
    ),
    CalistaSensorEntityDescription(
        key="heating",
        translation_key="heating",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda device: (
            device.last_reading.reading if device.last_reading else None
        ),
        exists_fn=lambda device: isinstance(device, HeatingDevice),
        generate_lts=True,
    ),
    CalistaSensorEntityDescription(
        key="last_reading_date",
        translation_key="last_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda device: (
            dt_util.as_utc(device.last_reading.date) if device.last_reading else None
        ),
        exists_fn=lambda device: bool(device.last_reading),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

BILLED_SENSOR_DESCRIPTIONS: Final[tuple[CalistaBilledSensorEntityDescription, ...]] = (
    CalistaBilledSensorEntityDescription(
        key="billed_reading",
        translation_key="billed_reading",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda r: r.current_reading,
    ),
)

ACCOUNT_SENSOR_DESCRIPTIONS: Final[tuple[CalistaAccountSensorEntityDescription, ...]] = (
    CalistaAccountSensorEntityDescription(
        key="latest_invoice_amount",
        translation_key="latest_invoice_amount",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: data.get("invoices", [])[0].amount if data.get("invoices") else None,
    ),
    CalistaAccountSensorEntityDescription(
        key="last_billed_date",
        translation_key="last_billed_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            dt_util.as_utc(datetime.combine(max(r.date for r in data["billed_readings"]), datetime.min.time()))
            if data.get("billed_readings") else None
        ),
    ),
)


def _make_device_info(device: Device, serial_number: str) -> DeviceInfo:
    """Create a DeviceInfo object for a meter device."""
    model_map: dict[type[Device], str] = {
        ColdWaterDevice: "Cold Water Meter",
        HotWaterDevice: "Hot Water Meter",
        HeatingDevice: "Heating Meter",
    }
    model = model_map.get(type(device))
    if model is None:
        _LOGGER.warning(
            "Unknown device type '%s' for serial %s; falling back to 'Generic Meter'.",
            type(device).__name__,
            serial_number,
        )
        model = "Generic Meter"
    device_name = (
        device.location
        if device.location
        else f"Ista Meter {serial_number[-4:]}"
    )

    return DeviceInfo(
        identifiers={(DOMAIN, serial_number)},
        name=device_name,
        manufacturer=MANUFACTURER,
        model=model,
        configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
    )


class IstaAverageDailySensor(CoordinatorEntity["IstaCoordinator"], SensorEntity):
    """Sensor showing the average daily consumption over the last 30 days."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IstaCoordinator,
        serial_number: str,
        device: Device,
    ) -> None:
        """Initialize the average daily consumption sensor."""
        super().__init__(coordinator)
        self._serial_number = serial_number
        self._attr_unique_id = f"{serial_number}_average_daily_consumption"

        if isinstance(device, HeatingDevice):
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        else:
            self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

        self._attr_device_info = _make_device_info(device, serial_number)
        self.entity_description = SensorEntityDescription(
            key="average_daily_consumption",
            translation_key="average_daily_consumption",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
        )

    @property
    def native_value(self) -> float | None:
        """Return the average daily consumption."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None
        device = self.coordinator.data["devices"].get(self._serial_number)
        if not device or not device.history or len(device.history) < 2:
            return None

        now = dt_util.now()
        thirty_days_ago = now - timedelta(days=30)

        # Get readings within the last 30 days, skipping None values
        recent_readings = [r for r in device.history if r.date >= thirty_days_ago and r.reading is not None]

        if not recent_readings or len(recent_readings) < 2:
            # Fallback to last 2 valid readings if we don't have enough in 30 days
            recent_readings = [r for r in device.history if r.reading is not None][-2:]

        if len(recent_readings) < 2:
            return None

        first = recent_readings[0]
        last = recent_readings[-1]

        timespan = (last.date - first.date).total_seconds()
        if timespan <= 0:
            return None

        consumption = last.reading - first.reading
        if consumption < 0:  # Meter reset probably
            return None

        days = timespan / (24 * 3600)
        if days == 0:
            return None
        return round(consumption / days, 2)


class IstaSeasonalConsumptionSensor(CoordinatorEntity["IstaCoordinator"], SensorEntity):
    """Sensor showing consumption for a specific season."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IstaCoordinator,
        serial_number: str,
        device: Device,
        start_month: int,
        start_day: int,
    ) -> None:
        """Initialize the seasonal consumption sensor."""
        super().__init__(coordinator)
        self._serial_number = serial_number
        self._start_month = start_month
        self._start_day = start_day

        self._attr_unique_id = f"{serial_number}_seasonal_consumption"
        self._attr_translation_key = "seasonal_consumption"

        if isinstance(device, HeatingDevice):
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        else:
            self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

        self._attr_device_info = _make_device_info(device, serial_number)

    @property
    def _current_season(self) -> tuple[int, str]:
        """Return the current season start year and name."""
        today = dt_util.now().date()
        start_year = today.year
        if today < date(today.year, self._start_month, self._start_day):
            start_year -= 1
        return start_year, f"{start_year}-{start_year + 1}"

    @property
    def native_value(self) -> float | None:
        """Return the consumption of the current season."""
        if not self.coordinator.data or "devices" not in self.coordinator.data:
            return None
        device = self.coordinator.data["devices"].get(self._serial_number)
        if not device or not device.history:
            return None

        start_year, _ = self._current_season
        start_date = date(start_year, self._start_month, self._start_day)

        # Filter readings for the current season, skipping None values
        season_readings = [
            r for r in device.history if r.date.date() >= start_date and r.reading is not None
        ]
        if not season_readings:
            return None

        first = season_readings[0]
        last = season_readings[-1]
        return round(last.reading - first.reading, 2)

    @property
    def extra_state_attributes(self) -> dict:
        """Return historical seasons as attributes."""
        attrs = {}
        device = self.coordinator.data["devices"].get(self._serial_number)
        if not device or not device.history:
            return attrs

        # Calculate consumption for all seasons
        seasons: dict[int, float] = {}
        # Simple grouping by season start year
        readings_by_season: dict[int, list] = {}
        for r in device.history:
            s_year = r.date.year
            if r.date.date() < date(r.date.year, self._start_month, self._start_day):
                s_year -= 1
            readings_by_season.setdefault(s_year, []).append(r)

        for s_year, readings in readings_by_season.items():
            if len(readings) >= 2:
                consumption = round(readings[-1].reading - readings[0].reading, 2)
                seasons[s_year] = consumption

        attrs["seasons"] = {f"{y}-{y+1}": cons for y, cons in sorted(seasons.items())}
        _, season_name = self._current_season
        attrs["current_season"] = season_name
        return attrs


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ista Calista sensors based on a config entry."""
    coordinator: IstaCoordinator = config_entry.runtime_data
    _LOGGER.debug("Setting up sensor platform for entry: %s", config_entry.entry_id)

    tracked_entity_ids: set[str] = set()
    billed_tracked: set[str] = set()
    invoice_tracked: set[str] = set()
    account_sensors_added = False

    @callback
    def _add_entities_callback() -> None:
        """Add entities from coordinator data."""
        nonlocal account_sensors_added
        _LOGGER.debug("Coordinator update received, checking for new entities.")
        if not coordinator.data:
            _LOGGER.debug("No coordinator data. Skipping entity setup.")
            return

        new_entities: list[SensorEntity] = []
        _LOGGER.debug("%d entities already tracked.", len(tracked_entity_ids))

        if not coordinator.data.get("devices"):
            _LOGGER.debug("No devices in coordinator data. Skipping entity setup.")
        else:
            for serial, device in coordinator.data["devices"].items():
                for description in SENSOR_DESCRIPTIONS:
                    unique_id = f"{serial}_{description.key}"
                    if unique_id not in tracked_entity_ids and description.exists_fn(device):
                        _LOGGER.debug(
                            "Found new entity to add: Unique ID=%s, Device SN=%s, Key=%s",
                            unique_id,
                            serial,
                            description.key,
                        )
                        new_entities.append(IstaSensor(coordinator, serial, description))
                        tracked_entity_ids.add(unique_id)

                        if description.generate_lts:
                            lts_uid = f"{serial}_{description.key}_lts_last_import"
                            if lts_uid not in tracked_entity_ids:
                                new_entities.append(
                                    IstaLtsLastImportSensor(serial, description.key, device)
                                )
                                tracked_entity_ids.add(lts_uid)

                # Average daily consumption sensor
                avg_unique_id = f"{serial}_average_daily_consumption"
                if avg_unique_id not in tracked_entity_ids:
                    new_entities.append(IstaAverageDailySensor(coordinator, serial, device))
                    tracked_entity_ids.add(avg_unique_id)

                # Seasonal consumption sensor (single entity)
                if device.history:
                    # Determine current season start Month/Day
                    season_start_str = config_entry.options.get(
                        CONF_SEASON_START,
                        config_entry.data.get(CONF_SEASON_START)
                    )
                    
                    if season_start_str:
                        # Format is YYYY-MM-DD from DateSelector
                        try:
                            start_date = date.fromisoformat(season_start_str)
                            start_month = start_date.month
                            start_day = start_date.day
                        except (ValueError, TypeError):
                            # Fallback if legacy or corrupted
                            start_month = DEFAULT_SEASON_START_MONTH
                            start_day = DEFAULT_SEASON_START_DAY
                    else:
                        # Fallback to legacy separate inputs or defaults
                        start_month = int(
                            config_entry.options.get(
                                CONF_SEASON_START_MONTH,
                                config_entry.data.get(
                                    CONF_SEASON_START_MONTH, DEFAULT_SEASON_START_MONTH
                                ),
                            )
                        )
                        start_day = int(
                            config_entry.options.get(
                                CONF_SEASON_START_DAY,
                                config_entry.data.get(
                                    CONF_SEASON_START_DAY, DEFAULT_SEASON_START_DAY
                                ),
                            )
                        )

                    s_unique_id = f"{serial}_seasonal_consumption"
                    if s_unique_id not in tracked_entity_ids:
                        new_entities.append(
                            IstaSeasonalConsumptionSensor(
                                coordinator,
                                serial,
                                device,
                                start_month,
                                start_day,
                            )
                        )
                        tracked_entity_ids.add(s_unique_id)

            if not account_sensors_added:
                for description in ACCOUNT_SENSOR_DESCRIPTIONS:
                    new_entities.append(
                        IstaAccountSensor(coordinator, config_entry, description)
                    )
                account_sensors_added = True

        # Invoice sensors — dynamic based on device_type found in history
        invoices = coordinator.data.get("invoices", [])
        device_types = {inv.device_type for inv in invoices if inv.device_type}
        for d_type in device_types:
            unique_id = f"{config_entry.unique_id}_invoice_{d_type.lower().replace(' ', '_')}"
            if unique_id not in invoice_tracked:
                description = CalistaInvoiceSensorEntityDescription(
                    key="invoice_amount",
                    translation_key="invoice_amount",
                    translation_placeholders={"device_type": d_type},
                    native_unit_of_measurement="EUR",
                    device_class=SensorDeviceClass.MONETARY,
                    state_class=SensorStateClass.TOTAL,
                    device_type=d_type,
                    value_fn=lambda invs, dt: next(
                        (i.amount for i in invs if i.device_type == dt), None
                    ),
                )
                new_entities.append(
                    IstaInvoiceSensor(coordinator, config_entry, description)
                )
                invoice_tracked.add(unique_id)

        # Billed sensors — numeric readings per serial
        devices = coordinator.data.get("devices", {})
        billed_readings = coordinator.data.get("billed_readings", [])
        
        # Track which types have billed readings for date sensors
        types_with_readings: dict[str, BilledReading] = {}

        for reading in billed_readings:
            device = devices.get(reading.serial_number)
            if device is not None:
                # Capture one reading per type for the date sensor
                d_type = reading.device_type
                if d_type not in types_with_readings:
                    types_with_readings[d_type] = reading
                
                for description in BILLED_SENSOR_DESCRIPTIONS:
                    unique_id = f"{reading.serial_number}_{description.key}"
                    if unique_id not in billed_tracked:
                        new_entities.append(
                            IstaBilledDeviceSensor(
                                coordinator, config_entry, reading.serial_number, device, description
                            )
                        )
                        billed_tracked.add(unique_id)

        # Billed Date sensors — one per type
        for d_type, reading in types_with_readings.items():
            unique_id = f"billed_date_{d_type.lower().replace(' ', '_')}"
            if unique_id not in billed_tracked:
                new_entities.append(
                    IstaBilledDateTypeSensor(coordinator, config_entry, d_type, reading)
                )
                billed_tracked.add(unique_id)

        # Bill Name Entities (to facilitate download action)
        for d_type in device_types:
            inv_dev_type = (d_type or "unknown").lower().replace(" ", "_")
            unique_id = f"bill_name_{inv_dev_type}"
            if unique_id not in invoice_tracked:
                new_entities.append(IstaBillNameSensor(coordinator, config_entry, d_type))
                invoice_tracked.add(unique_id)

        # Individual Bill Entities
        for invoice in invoices:
            if not invoice.invoice_number:
                continue
            inv_dev_type = (invoice.device_type or "unknown").lower().replace(" ", "_")
            unique_id = f"bill_{invoice.invoice_number}_{inv_dev_type}"
            if unique_id not in invoice_tracked:
                new_entities.append(IstaBillSensor(coordinator, config_entry, invoice))
                invoice_tracked.add(unique_id)

        if new_entities:
            _LOGGER.info(
                "Adding %d new Ista Calista sensor entities.", len(new_entities)
            )
            async_add_entities(new_entities)
        else:
            _LOGGER.debug("No new entities to add.")

    config_entry.async_on_unload(coordinator.async_add_listener(_add_entities_callback))
    _LOGGER.debug("Initial entity check for entry %s.", config_entry.entry_id)
    _add_entities_callback()


class IstaSensor(CoordinatorEntity["IstaCoordinator"], SensorEntity):
    """Representation of an Ista Calista sensor."""

    entity_description: CalistaSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IstaCoordinator,
        serial_number: str,
        entity_description: CalistaSensorEntityDescription,
    ) -> None:
        """Initialize the Ista Calista sensor."""
        super().__init__(coordinator)
        self._serial_number = serial_number
        self.entity_description = entity_description
        self._attr_unique_id = f"{serial_number}_{entity_description.key}"
        self._attr_translation_key = entity_description.translation_key
        self._stats_import_lock = asyncio.Lock()

        self._attr_device_info = _make_device_info(coordinator.data["devices"][serial_number], serial_number)
        _LOGGER.debug("IstaSensor initialized: %s", self.unique_id)

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        attrs = {}
        device = self.coordinator.data["devices"].get(self._serial_number)
        if device and device.last_reading:
            attrs["last_reading_date"] = dt_util.as_utc(device.last_reading.date).isoformat()
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("Coordinator update for entity: %s", self.unique_id)
        if device := self._device_data:
            self._attr_device_info = _make_device_info(device, self._serial_number)
            if self.entity_description.generate_lts:
                _LOGGER.debug(
                    "LTS generation is enabled, creating statistics import task for %s",
                    self.unique_id,
                )
                self.hass.async_create_task(self.async_import_statistics())
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        """Handle entity addition."""
        await super().async_added_to_hass()
        _LOGGER.debug("Entity %s added to hass.", self.unique_id)
        if self.entity_description.generate_lts:
            _LOGGER.debug(
                "LTS generation is enabled, creating initial statistics import task for %s",
                self.unique_id,
            )
            self.hass.async_create_task(self.async_import_statistics())

    @property
    def _device_data(self) -> Device | None:
        """Safely get the device data from the coordinator."""
        if self.coordinator.data and "devices" in self.coordinator.data:
            return self.coordinator.data["devices"].get(self._serial_number)
        return None

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if (device := self._device_data) is None:
            return None
        return self.entity_description.value_fn(device)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        is_available = super().available and self._device_data is not None
        if not is_available:
            _LOGGER.debug("Sensor %s is unavailable.", self.unique_id)
        return is_available

    async def async_import_statistics(self) -> None:
        """Import historical data as long-term statistics."""
        device = self._device_data
        if not device or not device.history:
            _LOGGER.debug(
                "Skipping statistics import for %s: no device data or history available.",
                self.unique_id,
            )
            return

        assert self.unique_id is not None
        statistic_id = f"{DOMAIN}:{self.unique_id.replace('-', '_')}"
        _LOGGER.debug("Starting statistics import for statistic_id: %s", statistic_id)

        async with self._stats_import_lock:
            _LOGGER.debug("Acquired statistics import lock for %s", statistic_id)
            recorder = get_instance(self.hass)
            if recorder is None:
                _LOGGER.warning(
                    "Recorder not available; skipping statistics import for %s.",
                    statistic_id,
                )
                return
            last_stats = await recorder.async_add_executor_job(
                get_last_statistics,
                self.hass,
                1,
                statistic_id,
                True,
                {"end", "state", "sum", "last_reset"},
            )

            last_stat_end_ts: float = 0.0
            running_sum: float = 0.0
            last_state: float | None = None
            last_reset_ts: float | None = None

            if last_stats and statistic_id in last_stats and last_stats[statistic_id]:
                stats = last_stats[statistic_id][0]
                last_stat_end_ts = stats.get("end") or 0.0
                running_sum = stats.get("sum") or 0.0
                last_state = stats.get("state")
                last_reset_ts = stats.get("last_reset")
                _LOGGER.debug(
                    "Found existing statistics for %s. Last timestamp: %s, Last sum: %s, Last state: %s",
                    statistic_id,
                    last_stat_end_ts,
                    running_sum,
                    last_state,
                )
            else:
                _LOGGER.debug(
                    "No existing statistics found for %s. Will import all new readings.",
                    statistic_id,
                )

            new_readings = sorted(
                (r for r in device.history if r.date.timestamp() > last_stat_end_ts),
                key=lambda r: r.date,
            )

            if not new_readings:
                _LOGGER.debug("No new readings to import for %s.", statistic_id)
                self.hass.bus.async_fire(
                    LTS_UPDATED_EVENT,
                    {
                        "statistic_id": statistic_id,
                        "timestamp": dt_util.now().isoformat(),
                    },
                )
                return

            _LOGGER.debug(
                "Found %d new readings to import as statistics for %s.",
                len(new_readings),
                statistic_id,
            )

            if last_reset_ts is None and new_readings:
                first_reading_date = new_readings[0].date
                last_reset_ts = first_reading_date.timestamp()
                _LOGGER.debug(
                    "Setting initial last_reset timestamp to %s for %s",
                    last_reset_ts,
                    statistic_id,
                )

            device_name = device.location if device.location else f"Ista Device {self._serial_number[-4:]}"
            _fallback_name = (
                (self.entity_description.translation_key or self.entity_description.key)
                .replace("_", " ")
                .title()
            )
            sensor_name = self.name or _fallback_name

            _unit = self.entity_description.native_unit_of_measurement
            if _unit == UnitOfEnergy.KILO_WATT_HOUR:
                _unit_class = "energy"
            elif _unit == UnitOfVolume.CUBIC_METERS:
                _unit_class = "volume"
            else:
                _unit_class = None

            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{device_name} {sensor_name}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_of_measurement=_unit,
                unit_class=_unit_class,
            )

            statistics_to_import: list[StatisticData] = []

            # Determine the state *before* the first new reading.
            if last_state is None:
                try:
                    history_dates: list[datetime] = [r.date for r in device.history]
                    first_new_reading_idx = history_dates.index(new_readings[0].date)
                    if first_new_reading_idx > 0:
                        # If there's a reading in our history just before the new ones,
                        # use that as the baseline for calculating the first increase.
                        last_state = device.history[first_new_reading_idx - 1].reading
                        _LOGGER.debug(
                            "Initialized 'last_state' for sum calculation to %s from previous reading in history.",
                            last_state,
                        )
                except (ValueError, IndexError):
                    _LOGGER.debug(
                        "Could not determine previous state for sum calculation. The first reading will establish the baseline."
                    )
                    pass

            # This is the main logic correction.
            is_first_import = last_state is None

            for reading in new_readings:
                if reading.reading is None:
                    _LOGGER.debug("Skipping reading with None value.")
                    continue

                current_state = reading.reading

                # If this is the very first import for this sensor, the first reading's
                # sum is 0, as it represents the starting point, not an increase.
                if is_first_import:
                    increase = 0.0
                    is_first_import = (
                        False  # Subsequent readings in this batch will be cumulative.
                    )
                else:
                    increase = current_state - last_state

                if increase < 0:
                    _LOGGER.info(
                        "Detected a meter reset for %s. Current reading (%s) is less than "
                        "previous reading (%s). Resetting sum and last_reset timestamp.",
                        statistic_id,
                        current_state,
                        last_state,
                    )
                    running_sum += current_state
                    last_reset_ts = reading.date.timestamp()
                else:
                    running_sum += increase

                statistics_to_import.append(
                    StatisticData(
                        start=reading.date,
                        state=current_state,
                        sum=running_sum,
                        last_reset=(
                            dt_util.utc_from_timestamp(last_reset_ts)
                            if last_reset_ts
                            else None
                        ),
                    )
                )
                last_state = current_state

            if statistics_to_import:
                _LOGGER.info(
                    "Importing %d new statistic(s) for %s.",
                    len(statistics_to_import),
                    statistic_id,
                )
                async_add_external_statistics(self.hass, metadata, statistics_to_import)
                self.hass.bus.async_fire(
                    LTS_UPDATED_EVENT,
                    {
                        "statistic_id": statistic_id,
                        "timestamp": dt_util.now().isoformat(),
                    },
                )
            _LOGGER.debug("Releasing statistics import lock for %s", statistic_id)


class IstaLtsLastImportSensor(RestoreSensor):
    """Diagnostic sensor showing when LTS statistics were last successfully imported for a device."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = False

    def __init__(self, serial_number: str, key: str, device: Device) -> None:
        """Initialize the LTS last import sensor."""
        self._attr_unique_id = f"{serial_number}_{key}_lts_last_import"
        self._attr_translation_key = "lts_last_import"
        self._attr_device_info = _make_device_info(device, serial_number)
        sensor_unique_id = f"{serial_number}_{key}"
        self._statistic_id = f"{DOMAIN}:{sensor_unique_id.replace('-', '_')}"

    async def async_added_to_hass(self) -> None:
        """Restore last state and subscribe to LTS update events."""
        await super().async_added_to_hass()
        if (last_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last_data.native_value
        self.async_on_remove(
            self.hass.bus.async_listen(LTS_UPDATED_EVENT, self._handle_lts_updated)
        )

    @callback
    def _handle_lts_updated(self, event: Event) -> None:
        """Handle an LTS import completion event from the paired IstaSensor."""
        if event.data.get("statistic_id") == self._statistic_id:
            self._attr_native_value = dt_util.parse_datetime(event.data["timestamp"])
            self.async_write_ha_state()


class IstaBilledDeviceSensor(CoordinatorEntity["IstaCoordinator"], SensorEntity):
    """Sensor showing the latest billed reading for a device (Account level)."""

    entity_description: CalistaBilledSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IstaCoordinator,
        config_entry: ConfigEntry,
        serial_number: str,
        device: Device,
        description: CalistaBilledSensorEntityDescription,
    ) -> None:
        """Initialize the billed reading sensor."""
        super().__init__(coordinator)
        self._serial_number = serial_number
        self.entity_description = description
        self._attr_unique_id = f"{serial_number}_{description.key}"
        self._attr_translation_key = f"{description.translation_key}_at_location"
        self._attr_translation_placeholders = {"location": device.location or serial_number}

        # Unit determined by device type (except for timestamps)
        if description.device_class != SensorDeviceClass.TIMESTAMP:
            if isinstance(device, HeatingDevice):
                self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            else:
                self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        self._attr_device_info = _make_device_info(device, serial_number)
        _LOGGER.debug("IstaBilledDeviceSensor initialized: %s", self.unique_id)

    @property
    def _latest_billed(self) -> BilledReading | None:
        """Return the latest BilledReading for this device's serial number."""
        billed = self.coordinator.data.get("billed_readings", []) if self.coordinator.data else []
        return next((r for r in billed if r.serial_number == self._serial_number), None)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        reading = self._latest_billed
        return self.entity_description.value_fn(reading) if reading else None

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        reading = self._latest_billed
        if not reading:
            return {}
        return {
            "incidence": reading.incidence_name,
            "is_estimated": reading.is_estimated,
            "date": reading.date.isoformat(),
            "previous_reading": reading.previous_reading,
            "consumption": reading.consumption,
        }


class IstaAccountSensor(CoordinatorEntity["IstaCoordinator"], SensorEntity):
    """Account-level sensor (e.g., latest invoice amount)."""

    entity_description: CalistaAccountSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IstaCoordinator,
        config_entry: ConfigEntry,
        description: CalistaAccountSensorEntityDescription,
    ) -> None:
        """Initialize the account sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self.entity_description = description
        self._attr_unique_id = f"{config_entry.unique_id}_{description.key}"
        self._attr_translation_key = description.translation_key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"Ista Account {config_entry.data.get(CONF_EMAIL, '')}",
            manufacturer=MANUFACTURER,
            model="Ista Calista Account",
            configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
        )
        _LOGGER.debug("IstaAccountSensor initialized: %s", self.unique_id)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and bool(
            self.coordinator.data and self.coordinator.data.get("invoices")
        )


class IstaInvoiceSensor(CoordinatorEntity["IstaCoordinator"], SensorEntity):
    """Sensor showing the latest invoice for a specific service type."""

    entity_description: CalistaInvoiceSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IstaCoordinator,
        config_entry: ConfigEntry,
        description: CalistaInvoiceSensorEntityDescription,
    ) -> None:
        """Initialize the invoice sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self.entity_description = description
        self._attr_unique_id = (
            f"{config_entry.unique_id}_invoice_"
            f"{description.device_type.lower().replace(' ', '_')}"
        )
        self._attr_translation_key = description.translation_key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"Ista Account {config_entry.data.get(CONF_EMAIL, '')}",
            manufacturer=MANUFACTURER,
            model="Ista Calista Account",
            configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
        )
        _LOGGER.debug("IstaInvoiceSensor initialized: %s", self.unique_id)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        invoices: list[Invoice] = (
            self.coordinator.data.get("invoices", []) if self.coordinator.data else []
        )
        return self.entity_description.value_fn(invoices, self.entity_description.device_type)

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        invoices: list[Invoice] = (
            self.coordinator.data.get("invoices", []) if self.coordinator.data else []
        )
        invoice = next(
            (i for i in invoices if i.device_type == self.entity_description.device_type),
            None,
        )
        if not invoice:
            return {}
        return {
            "invoice_id": invoice.invoice_id,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            "period_start": invoice.period_start.isoformat() if invoice.period_start else None,
            "period_end": invoice.period_end.isoformat() if invoice.period_end else None,
            "device_type": invoice.device_type,
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        invoices: list[Invoice] = (
            self.coordinator.data.get("invoices", []) if self.coordinator.data else []
        )
        return super().available and any(
            i.device_type == self.entity_description.device_type for i in invoices
        )


class IstaBillSensor(CoordinatorEntity["IstaCoordinator"], SensorEntity):
    """Sensor showing an individual bill (invoice)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IstaCoordinator,
        config_entry: ConfigEntry,
        invoice: Invoice,
    ) -> None:
        """Initialize the bill sensor."""
        super().__init__(coordinator)
        self._invoice_number = invoice.invoice_number
        self._device_type = invoice.device_type
        self._attr_unique_id = f"bill_{invoice.invoice_number}_{invoice.device_type.lower().replace(' ', '_')}"
        self._attr_translation_key = "individual_bill"
        self._attr_translation_placeholders = {
            "invoice_id": invoice.invoice_id,
            "invoice_number": invoice.invoice_number,
            "device_type": invoice.device_type,
        }
        self._attr_native_unit_of_measurement = "EUR"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"Ista Account {config_entry.data.get(CONF_EMAIL, '')}",
            manufacturer=MANUFACTURER,
            model="Ista Calista Account",
            configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
        )
        _LOGGER.debug("IstaBillSensor initialized: %s", self.unique_id)

    @property
    def native_value(self) -> float | None:
        """Return the amount of the invoice."""
        if not self.coordinator.data or "invoices" not in self.coordinator.data:
            return None
        invoice = next(
            (i for i in self.coordinator.data["invoices"] if i.invoice_number == self._invoice_number),
            None,
        )
        return invoice.amount if invoice else None

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        if not self.coordinator.data or "invoices" not in self.coordinator.data:
            return {}
        invoice = next(
            (i for i in self.coordinator.data["invoices"] if i.invoice_number == self._invoice_number),
            None,
        )
        if not invoice:
            return {}
        return {
            "invoice_id": invoice.invoice_id,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            "period_start": invoice.period_start.isoformat() if invoice.period_start else None,
            "period_end": invoice.period_end.isoformat() if invoice.period_end else None,
            "device_type": invoice.device_type,
        }


class IstaBillNameSensor(CoordinatorEntity["IstaCoordinator"], SensorEntity):
    """Sensor showing a valid billing name for download action."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IstaCoordinator,
        config_entry: ConfigEntry,
        device_type: str,
    ) -> None:
        """Initialize the bill name sensor."""
        super().__init__(coordinator)
        self._device_type = device_type
        self._attr_unique_id = f"bill_name_{device_type.lower().replace(' ', '_')}"
        self._attr_translation_key = "bill_name"
        self._attr_translation_placeholders = {"device_type": device_type}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"Ista Account {config_entry.data.get(CONF_EMAIL, '')}",
            manufacturer=MANUFACTURER,
            model="Ista Calista Account",
            configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
        )
        _LOGGER.debug("IstaBillNameSensor initialized: %s", self.unique_id)

    @property
    def native_value(self) -> str | None:
        """Return latest invoice ID for this type."""
        invoices = self.coordinator.data.get("invoices", []) if self.coordinator.data else []
        latest = next((i for i in invoices if i.device_type == self._device_type), None)
        return latest.invoice_id if latest else None

    @property
    def extra_state_attributes(self) -> dict:
        """Return latest invoice ID for this type."""
        invoices = self.coordinator.data.get("invoices", []) if self.coordinator.data else []
        latest = next((i for i in invoices if i.device_type == self._device_type), None)
        if latest:
            return {"latest_invoice_id": latest.invoice_id}
        return {}


class IstaBilledDateTypeSensor(CoordinatorEntity["IstaCoordinator"], SensorEntity):
    """Sensor showing the latest billed date for a service type (Account level)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IstaCoordinator,
        config_entry: ConfigEntry,
        device_type: str,
        reading: BilledReading,
    ) -> None:
        """Initialize the billed date sensor."""
        super().__init__(coordinator)
        self._device_type = device_type
        self._attr_unique_id = f"billed_date_{device_type.lower().replace(' ', '_')}"
        self._attr_translation_key = "last_billed_date_type"
        self._attr_translation_placeholders = {"device_type": device_type}
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"Ista Account {config_entry.data.get(CONF_EMAIL, '')}",
            manufacturer=MANUFACTURER,
            model="Ista Calista Account",
            configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
        )
        _LOGGER.debug("IstaBilledDateTypeSensor initialized: %s", self.unique_id)

    @property
    def available(self) -> bool:
        """Return True if the coordinator has valid data."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def native_value(self) -> datetime | None:
        """Return the latest billed date for this type."""
        billed_readings = self.coordinator.data.get("billed_readings", []) if self.coordinator.data else []
        
        # Filter readings by device type (BilledReading has device_type, Device does not have type)
        type_dates = [
            r.date for r in billed_readings
            if r.device_type == self._device_type
        ]
        
        if not type_dates:
            return None
        
        latest_date = max(type_dates)
        return dt_util.as_utc(datetime.combine(latest_date, datetime.min.time()))
