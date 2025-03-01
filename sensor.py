"""Support for Ista Calista sensors.

This platform provides sensors for monitoring utility consumption data from Ista Calista,
including water (hot and cold) and heating meters. It supports:
- Historical data tracking
- Long-term statistics generation
- Multiple device types and locations

For more information about this integration, please visit:
https://www.home-assistant.io/integrations/ista_calista/

Example configuration.yaml entry:
```yaml
sensor:
  - platform: ista_calista
    email: YOUR_EMAIL
    password: YOUR_PASSWORD
```
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from homeassistant.components.recorder.models.statistics import (
    StatisticData, StatisticMetaData)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics, get_instance, get_last_statistics)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
    UnitOfVolume,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntry, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import IstaConfigEntry, IstaCoordinator, IstaDeviceData
from pycalista_ista import (
    ColdWaterDevice,
    Device,
    HeatingDevice,
    HotWaterDevice,
    WaterDevice,
)
_LOGGER: Final = logging.getLogger(__name__)
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
    
    consumption_type: IstaSensorEntity




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

    async_add_entities(
        IstaSensor(coordinator, serial_number, description)
        for description in SENSOR_DESCRIPTIONS
        for serial_number, device in coordinator.data["devices"].items()
        if description.exists_fn(device)
    )


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
        return DeviceInfo(
            identifiers={(DOMAIN, self.serial_number)},
            name=self._generate_name(device),
            manufacturer=MANUFACTURER,
            model="ista Calista",
            sw_version=self.coordinator.config_entry.version,
            configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
            suggested_area=device.location if device.location else None,
        )

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
            return self.hass.config.language.get("sensor.water.name", "Water")
        if isinstance(device, HotWaterDevice):
            return self.hass.config.language.get("sensor.hot_water.name", "Hot water")
        if isinstance(device, HeatingDevice):
            return self.hass.config.language.get("sensor.heating.name", "Heating")
        return self.hass.config.language.get("device.unknown", "Unknown")

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

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return additional state attributes.

        Returns:
            Dictionary of additional attributes to expose.
        """
        device = self.coordinator.data["devices"][self.serial_number]
        attrs = {}

        if isinstance(device, WaterDevice):
            attrs["consumption_type"] = (
                IstaSensorEntity.HOT_WATER
                if isinstance(device, HotWaterDevice)
                else IstaSensorEntity.WATER
            )
        elif isinstance(device, HeatingDevice):
            attrs["consumption_type"] = IstaSensorEntity.HEATING

        return attrs

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state of the sensor.

        Returns:
            The current state value of the sensor, or STATE_UNKNOWN if no data available.
        """

        value = self.entity_description.value_fn(
            self.coordinator.data["devices"][self.serial_number]
        )
        return value if value is not None else STATE_UNKNOWN


    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added.

        Performs initial statistics import when sensor is added to avoid
        waiting for the first coordinator update.
        """
        if self.entity_description.generate_lts:
            await self._update_statistics()
        await super().async_added_to_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.

        Updates statistics if enabled for this sensor.
        """
        if self.entity_description.generate_lts:
            self.hass.async_create_task(self._update_statistics())
        super()._handle_coordinator_update()

    async def _update_statistics(self) -> None:
        """Import historical statistics from Ista Calista.

        This method processes historical readings and generates long-term statistics
        for the sensor, including total consumption and state history.
        """
        try:
            name = self.coordinator.config_entry.options.get(
                f"lts_{self.entity_description.key}_{self.serial_number}"
            )
            if not name:
                name = self.entity_id.removeprefix("sensor.")
                self.hass.config_entries.async_update_entry(
                    entry=self.coordinator.config_entry,
                    options={
                        **self.coordinator.config_entry.options,
                        f"lts_{self.entity_description.key}_{self.serial_number}": name,
                    },
                )

            statistic_id = f"{DOMAIN}:{name}"
            history = self.coordinator.data["devices"][self.serial_number].history

            last_stats_sum = 0.0
            last_stats_state = 0.0
            last_stats_date = None
            last_stats_last_reset = history[0].date

            last_stats = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics,
                self.hass,
                1,
                statistic_id,
                False,
                {"sum", "state", "last_reset"},
            )

            if last_stats:
                last_stats_sum = last_stats[statistic_id][0].get("sum") or 0.0
                last_stats_state = last_stats[statistic_id][0].get("state") or 0.0
                last_stats_last_reset = datetime.fromtimestamp(
                    last_stats[statistic_id][0].get("last_reset") or 0, tz=UTC
                )
                last_stats_date = datetime.fromtimestamp(
                    last_stats[statistic_id][0].get("end") or 0, tz=UTC
                ) + timedelta(days=1)

            joined_history = []
            for i, reading in enumerate(history):
                current_reading = reading.reading
                previous_reading = history[i - 1].reading if i > 0 else last_stats_state

                if previous_reading > current_reading:
                    last_stats_last_reset = reading.date
                    consumption = 0
                else:
                    consumption = current_reading - previous_reading

                last_stats_sum += consumption
                joined_history.append(
                    {
                        "date": reading.date,
                        "current_reading": current_reading,
                        "last_reset": last_stats_last_reset,
                        "statistics_sum_diff": last_stats_sum,
                    }
                )

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

            metadata: StatisticMetaData = {
                "has_mean": False,
                "has_sum": True,
                "name": f"{self._generate_name(self.coordinator.data['devices'][self.serial_number])} {self.name}",
                "source": DOMAIN,
                "statistic_id": statistic_id,
                "unit_of_measurement": self.entity_description.native_unit_of_measurement,
            }

            if statistics:
                _LOGGER.debug("Inserting statistics: %s %s", metadata, statistics)
                async_add_external_statistics(self.hass, metadata, statistics)

        except Exception as err:
            _LOGGER.error("Error updating statistics: %s", err)
