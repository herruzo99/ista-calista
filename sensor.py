from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import logging
from typing import Final

from pycalista_ista import ColdWaterDevice, Device, HeatingDevice, HotWaterDevice

from homeassistant.components.recorder.models.statistics import (
    StatisticData,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_instance,
    get_last_statistics,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import STATE_UNKNOWN, EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntry, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import IstaConfigEntry, IstaCoordinator

# Enhanced logging configuration
_LOGGER: Final = logging.getLogger(__name__)
_LOGGER.setLevel("DEBUG")
# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0


class IstaSensorEntity(StrEnum):
    """Ista EcoTrend Entities."""

    HEATING = "heating"
    HOT_WATER = "hot_water"
    WATER = "water"
    LAST_READING = "last_reading"


@dataclass(frozen=True, kw_only=True)
class CalistaSensorEntityDescription(SensorEntityDescription):
    """Describes an Ista Calista sensor entity.

    Attributes:
        exists_fn: Function to determine if this sensor type exists for a given device
        value_fn: Function to extract the sensor value from a device
        generate_lts: Whether to generate long-term statistics for this sensor
        entity_category: Entity category for the sensor
    """

    exists_fn: Callable[[Device], bool] = lambda _: True
    value_fn: Callable[[Device], StateType]
    generate_lts: bool
    entity_category: EntityCategory | None = None


SENSOR_DESCRIPTIONS: Final[tuple[CalistaSensorEntityDescription, ...]] = (
    CalistaSensorEntityDescription(
        key=IstaSensorEntity.WATER,
        translation_key=IstaSensorEntity.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda device: (
            device.last_reading.reading if device.last_reading else None
        ),
        exists_fn=lambda device: isinstance(device, ColdWaterDevice),
        generate_lts=True,
        has_entity_name=True,
    ),
    CalistaSensorEntityDescription(
        key=IstaSensorEntity.HOT_WATER,
        translation_key=IstaSensorEntity.HOT_WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda device: (
            device.last_reading.reading if device.last_reading else None
        ),
        exists_fn=lambda device: isinstance(device, HotWaterDevice),
        generate_lts=True,
        has_entity_name=True,
    ),
    CalistaSensorEntityDescription(
        key=IstaSensorEntity.HEATING,
        translation_key=IstaSensorEntity.HEATING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=2,
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda device: (
            device.last_reading.reading if device.last_reading else None
        ),
        exists_fn=lambda device: isinstance(device, HeatingDevice),
        generate_lts=True,
        has_entity_name=True,
    ),
    CalistaSensorEntityDescription(
        key=IstaSensorEntity.LAST_READING,
        translation_key=IstaSensorEntity.LAST_READING,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda device: (
            device.last_reading.date if device.last_reading else None
        ),
        exists_fn=lambda device: isinstance(device, Device),
        generate_lts=False,
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: IstaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ista Calista sensors based on a config entry.

    Args:
        hass: The Home Assistant instance.
        config_entry: The config entry being set up.
        async_add_entities: Callback to register new entities.
    """
    coordinator = config_entry.runtime_data
    _LOGGER.debug("Setting up Ista Calista sensors with coordinator: %s", coordinator)

    # Log device information
    device_count = len(coordinator.data["devices"])
    _LOGGER.debug("Found %d devices in coordinator data", device_count)
    for serial_number, device in coordinator.data["devices"].items():
        _LOGGER.debug(
            "Device found - Serial: %s, Type: %s, Location: %s, Has readings: %s",
            serial_number,
            type(device).__name__,
            device.location,
            bool(device.last_reading),
        )

    entities = []
    for description in SENSOR_DESCRIPTIONS:
        for serial_number, device in coordinator.data["devices"].items():
            if description.exists_fn(device):
                entity_id = f"{serial_number}_{description.key}"
                _LOGGER.debug(
                    "[%s] Creating sensor - Serial: %s, Type: %s, Description: %s",
                    entity_id,
                    serial_number,
                    type(device).__name__,
                    description.key,
                )
                entities.append(IstaSensor(coordinator, serial_number, description))

    _LOGGER.info("Adding %d Ista Calista sensor entities", len(entities))
    async_add_entities(entities)


class IstaSensor(CoordinatorEntity[IstaCoordinator], SensorEntity):
    """Representation of an Ista Calista sensor.

    This sensor entity represents various types of utility consumption meters
    from Ista Calista, including water and heating meters. It supports real-time
    readings and historical data tracking.

    Attributes:
        entity_description: Description of the sensor entity
        _attr_has_entity_name: Whether the entity has a friendly name
        device_entry: Associated device entry in the device registry
    """

    entity_description: CalistaSensorEntityDescription
    _attr_has_entity_name = True
    device_entry: DeviceEntry

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this entity.

        Returns:
            Device information for the device registry.
        """
        device = self.coordinator.data["devices"][self.serial_number]
        device_info = DeviceInfo(
            identifiers={(DOMAIN, self.serial_number)},
            name=self._generate_name(device),
            manufacturer=MANUFACTURER,
            model="ista Calista",
            sw_version=self.coordinator.config_entry.version,
            configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
        )
        _LOGGER.debug(
            "[%s] Device info for %s: name=%s, area=%s",
            self._attr_unique_id,
            self.serial_number,
            device_info["name"],
            device_info.get("suggested_area"),
        )
        return device_info

    def _generate_name(self, device: Device) -> str:
        """Generate a friendly name for the device.

        Args:
            device: The device to generate a name for.

        Returns:
            A user-friendly name based on the device type and location.
        """
        if device.location:
            return device.location
        if isinstance(device, ColdWaterDevice):
            return "Water"
        if isinstance(device, HotWaterDevice):
            return "Hot water"
        if isinstance(device, HeatingDevice):
            return "Heating"
        return "Unknown"

    def __init__(
        self,
        coordinator: IstaCoordinator,
        serial_number: str,
        entity_description: CalistaSensorEntityDescription,
    ) -> None:
        """Initialize the Ista Calista sensor.

        Args:
            coordinator: The data update coordinator
            serial_number: Unique serial number of the device
            entity_description: Description of the sensor entity
        """
        super().__init__(coordinator)
        self.serial_number = serial_number
        self._attr_unique_id = f"{serial_number}_{entity_description.key}"
        self.entity_description = entity_description
        self._attr_entity_category = entity_description.entity_category

        _LOGGER.debug(
            "[%s] Initialized IstaSensor - Serial: %s, Entity ID: %s, Type: %s",
            self._attr_unique_id,
            serial_number,
            self._attr_unique_id,
            entity_description.key,
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state of the sensor.

        Returns:
            The current state value of the sensor, or STATE_UNKNOWN if no data available.
        """
        try:
            device = self.coordinator.data["devices"][self.serial_number]
            value = self.entity_description.value_fn(device)

            return value if value is not None else STATE_UNKNOWN
        except Exception as err:
            _LOGGER.error(
                "[%s] Error getting native value for %s: %s",
                self._attr_unique_id,
                self._attr_unique_id,
                str(err),
                exc_info=True,
            )
            return STATE_UNKNOWN

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added.

        Performs initial statistics import when sensor is added to avoid
        waiting for the first coordinator update.
        """
        _LOGGER.debug(
            "[%s] Entity description details - Key: %s, Generate LTS: %s",
            self._attr_unique_id,
            self.entity_description.key,
            self.entity_description.generate_lts,
        )

        if self.entity_description.generate_lts:
            _LOGGER.debug(
                "[%s] Generating initial statistics for %s",
                self._attr_unique_id,
                self._attr_unique_id,
            )
            await self._update_statistics()
        else:
            _LOGGER.debug(
                "[%s] Skipping statistics generation for %s (not enabled)",
                self._attr_unique_id,
                self._attr_unique_id,
            )

        await super().async_added_to_hass()

    @callback
    async def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.

        Updates statistics if enabled for this sensor.
        """
        _LOGGER.debug(
            "[%s] Coordinator update for %s", self._attr_unique_id, self._attr_unique_id
        )

        if self.entity_description.generate_lts:
            _LOGGER.debug(
                "[%s] Scheduling statistics update for %s",
                self._attr_unique_id,
                self._attr_unique_id,
            )
            self._update_statistics()

        super()._handle_coordinator_update()

    def _update_statistics(self) -> None:
        """Import historical statistics from Ista Calista.

        This method processes historical readings and generates long-term statistics
        for the sensor, including total consumption and state history.
        """
        try:
            _LOGGER.debug(
                "[%s] Updating statistics for %s",
                self._attr_unique_id,
                self._attr_unique_id,
            )

            # Get the saved statistics name or generate one
            name = self.coordinator.config_entry.options.get(
                f"lts_{self.entity_description.key}_{self.serial_number}"
            )
            if not name:
                name = self.entity_id.removeprefix("sensor.")
                _LOGGER.debug(
                    "[%s] No saved statistics name for %s, using %s",
                    self._attr_unique_id,
                    self._attr_unique_id,
                    name,
                )
                self.hass.config_entries.async_update_entry(
                    entry=self.coordinator.config_entry,
                    options={
                        **self.coordinator.config_entry.options,
                        f"lts_{self.entity_description.key}_{self.serial_number}": name,
                    },
                )

            statistic_id = f"{DOMAIN}:{name}"
            _LOGGER.debug("[%s] Statistics ID: %s", self._attr_unique_id, statistic_id)

            # Get device history
            device = self.coordinator.data["devices"][self.serial_number]
            history = device.history

            if not history:
                _LOGGER.warning(
                    "[%s] No history available for %s",
                    self._attr_unique_id,
                    self._attr_unique_id,
                )
                return

            _LOGGER.debug(
                "[%s] Found %d historical readings for %s",
                self._attr_unique_id,
                len(history),
                self._attr_unique_id,
            )

            # Get last statistics from database
            last_stats = get_instance(self.hass).async_add_executor_job(
                get_last_statistics,
                self.hass,
                1,
                statistic_id,
                False,
                {"sum", "state", "last_reset"},
            )

            if last_stats and statistic_id in last_stats:
                _LOGGER.debug(
                    "[%s] Found existing statistics for %s",
                    self._attr_unique_id,
                    statistic_id,
                )
                last_stats_sum = last_stats[statistic_id][0].get("sum") or 0.0
                last_stats_state = last_stats[statistic_id][0].get("state") or None
                last_stats_last_reset = datetime.fromtimestamp(
                    last_stats[statistic_id][0].get("last_reset") or 0, tz=UTC
                )
                last_stats_date = datetime.fromtimestamp(
                    last_stats[statistic_id][0].get("end") or 0, tz=UTC
                ) + timedelta(days=1)

            else:
                last_stats_sum = 0.0
                last_stats_state = None
                last_stats_date = None
                last_stats_last_reset = history[0].date

                _LOGGER.debug(
                    "[%s] No existing statistics found for %s",
                    self._attr_unique_id,
                    statistic_id,
                )
            _LOGGER.debug(
                "[%s] Last statistics - Sum: %f, State: %s, Last Reset: %s, Date: %s",
                self._attr_unique_id,
                last_stats_sum,
                last_stats_state,
                last_stats_last_reset,
                last_stats_date,
            )
            readings_after_last_stats = [
                reading
                for reading in history
                if last_stats_date is None or reading.date > last_stats_date
            ]
            # Process history and build statistics
            joined_history = []
            for i, reading in enumerate(readings_after_last_stats):
                current_reading = reading.reading
                previous_reading = (
                    readings_after_last_stats[i - 1].reading
                    if i > 0
                    else last_stats_state
                )

                if previous_reading is None:
                    previous_reading = current_reading

                # Check for meter reset
                if previous_reading > current_reading:
                    _LOGGER.debug(
                        "[%s] Meter reset detected at %s",
                        self._attr_unique_id,
                        reading.date,
                    )
                    last_stats_last_reset = reading.date
                    consumption = 0
                else:
                    consumption = current_reading - previous_reading

                last_stats_sum += consumption
                _LOGGER.debug(
                    "[%s] Adding history point - Date: %s, Reading: %f, Last Reset: %s, Sum: %f",
                    self._attr_unique_id,
                    reading.date.isoformat(),
                    current_reading,
                    last_stats_last_reset.isoformat(),
                    last_stats_sum,
                )
                joined_history.append(
                    {
                        "date": reading.date,
                        "current_reading": current_reading,
                        "last_reset": last_stats_last_reset,
                        "statistics_sum_diff": last_stats_sum,
                    }
                )
                _LOGGER.debug("[%s]%s", self._attr_unique_id, reading.date)

            # Create statistics entries
            statistics: list[StatisticData] = [
                {
                    "start": history_data["date"],
                    "state": history_data["current_reading"],
                    "sum": history_data["statistics_sum_diff"],
                    "last_reset": history_data["last_reset"],
                }
                for history_data in joined_history
                if last_stats_date is None or history_data["date"] > last_stats_date
            ]

            # Create statistics metadata
            metadata: StatisticMetaData = {
                "has_mean": False,
                "has_sum": True,
                "name": f"{self._generate_name(device)} {self.name}",
                "source": DOMAIN,
                "statistic_id": statistic_id,
                "unit_of_measurement": self.entity_description.native_unit_of_measurement,
            }

            if statistics:
                _LOGGER.info(
                    "[%s] Inserting %d statistics entries for %s",
                    self._attr_unique_id,
                    len(statistics),
                    statistic_id,
                )
                _LOGGER.debug(
                    "[%s] Statistics metadata: %s", self._attr_unique_id, metadata
                )
                _LOGGER.debug(
                    "[%s] First statistics entry: %s",
                    self._attr_unique_id,
                    statistics[0],
                )
                _LOGGER.debug(
                    "[%s] Last statistics entry: %s",
                    self._attr_unique_id,
                    statistics[-1],
                )

                async_add_external_statistics(self.hass, metadata, statistics)
            else:
                _LOGGER.debug(
                    "[%s] No new statistics to insert for %s",
                    self._attr_unique_id,
                    statistic_id,
                )

        except Exception:
            _LOGGER.exception(
                "[%s] Error updating statistics for %s:",
                self._attr_unique_id,
                self._attr_unique_id,
            )
