"""Sensor platform for the Ista Calista integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from pycalista_ista import ColdWaterDevice, Device, HeatingDevice, HotWaterDevice

from .const import DOMAIN, MANUFACTURER

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


SENSOR_DESCRIPTIONS: Final[tuple[CalistaSensorEntityDescription, ...]] = (
    CalistaSensorEntityDescription(
        key="water",
        translation_key="water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda device: (
            device.last_reading.reading if device.last_reading else None
        ),
        exists_fn=lambda device: isinstance(device, ColdWaterDevice),
        generate_lts=True,
    ),
    CalistaSensorEntityDescription(
        key="hot_water",
        translation_key="hot_water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
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
            device.last_reading.date if device.last_reading else None
        ),
        exists_fn=lambda device: bool(device.last_reading),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ista Calista sensors based on a config entry."""
    coordinator: IstaCoordinator = config_entry.runtime_data
    hass.data.setdefault(DOMAIN, {}).setdefault("entities", set())
    _LOGGER.debug("Setting up sensor platform for entry: %s", config_entry.entry_id)

    @callback
    def _add_entities_callback() -> None:
        """Add entities from coordinator data."""
        _LOGGER.debug("Coordinator update received, checking for new entities.")
        if not coordinator.data or not coordinator.data.get("devices"):
            _LOGGER.debug("No devices in coordinator data. Skipping entity setup.")
            return

        new_entities: list[IstaSensor] = []
        current_entities = hass.data[DOMAIN]["entities"]
        _LOGGER.debug("%d entities already exist.", len(current_entities))

        for serial, device in coordinator.data["devices"].items():
            for description in SENSOR_DESCRIPTIONS:
                unique_id = f"{serial}_{description.key}"
                if unique_id not in current_entities and description.exists_fn(device):
                    _LOGGER.debug(
                        "Found new entity to add: Unique ID=%s, Device SN=%s, Key=%s",
                        unique_id,
                        serial,
                        description.key,
                    )
                    new_entities.append(IstaSensor(coordinator, serial, description))
                    current_entities.add(unique_id)

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
        self._stats_import_lock = asyncio.Lock()

        if device := self._device_data:
            self._attr_device_info = self._create_device_info(device)
        _LOGGER.debug("IstaSensor initialized: %s", self.unique_id)

    def _create_device_info(self, device: Device) -> DeviceInfo:
        """Create a DeviceInfo object for the entity."""
        model_map = {
            ColdWaterDevice: "Cold Water Meter",
            HotWaterDevice: "Hot Water Meter",
            HeatingDevice: "Heating Meter",
        }
        model = model_map.get(type(device), "Generic Meter")
        device_name = (
            device.location
            if device.location
            else f"Ista Meter {self._serial_number[-4:]}"
        )

        return DeviceInfo(
            identifiers={(DOMAIN, self._serial_number)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=model,
            configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("Coordinator update for entity: %s", self.unique_id)
        if device := self._device_data:
            self._attr_device_info = self._create_device_info(device)
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

    def _get_device_name(self, device: Device) -> str:
        """Generate a friendly name for the device."""
        if device.location:
            return device.location
        return f"Ista Device {self._serial_number[-4:]}"

    def _get_device_model(self, device: Device) -> str:
        """Return a model name based on the device type."""
        model_map = {
            ColdWaterDevice: "Cold Water Meter",
            HotWaterDevice: "Hot Water Meter",
            HeatingDevice: "Heating Meter",
        }
        return model_map.get(type(device), "Generic Meter")

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

        statistic_id = f"{DOMAIN}:{self.unique_id.replace('-', '_')}"
        _LOGGER.debug("Starting statistics import for statistic_id: %s", statistic_id)

        async with self._stats_import_lock:
            _LOGGER.debug("Acquired statistics import lock for %s", statistic_id)
            last_stats = await get_instance(self.hass).async_add_executor_job(
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

            device_name = self._get_device_name(device)
            sensor_name = (
                (self.entity_description.translation_key or self.entity_description.key)
                .replace("_", " ")
                .title()
            )

            metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=f"{device_name} {sensor_name}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_of_measurement=self.entity_description.native_unit_of_measurement,
            )

            statistics_to_import = []

            # Determine the state *before* the first new reading.
            if last_state is None:
                try:
                    history_dates = [r.date for r in device.history]
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
            _LOGGER.debug("Releasing statistics import lock for %s", statistic_id)
