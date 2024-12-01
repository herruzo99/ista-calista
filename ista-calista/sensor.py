"""Sensor platform for Ista Calista integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import logging

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
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IstaConfigEntry
from .const import DOMAIN
from .coordinator import IstaCoordinator
from .pycalista_ista import Device, HeatingDevice, WaterDevice

_LOGGER = logging.getLogger(__name__)


class IstaConsumptionType(StrEnum):
    """Types of consumptions from ista."""

    HEATING = "heating"
    HOT_WATER = "warmwater"
    WATER = "water"


@dataclass(kw_only=True)
class CalistaSensorEntityDescription(SensorEntityDescription):
    """Describes Ista Calista sensor entity."""

    exists_fn: Callable[[Device], bool] = lambda _: True
    value_fn: Callable[[Device], StateType]
    generate_lts: bool


SENSOR_DESCRIPTIONS: tuple[CalistaSensorEntityDescription, ...] = (
    CalistaSensorEntityDescription(
        key="total_volume",
        translation_key="water",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda device: device.last_reading.reading
        if device.last_reading
        else None,
        exists_fn=lambda device: isinstance(device, WaterDevice),
        generate_lts = True
    ),
    CalistaSensorEntityDescription(
        key="total_heating",
        translation_key="heating",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda device: device.last_reading.reading
        if device.last_reading
        else None,
        exists_fn=lambda device: isinstance(device, HeatingDevice),
        generate_lts = True
    ),
    CalistaSensorEntityDescription(
        key="last_reading",
        translation_key="last_date",
        native_unit_of_measurement=None,
        device_class=SensorDeviceClass.DATE,
        state_class=None,
        value_fn=lambda device: device.last_reading.date
        if device.last_reading
        else None,
        exists_fn=lambda device: isinstance(device, Device),
        generate_lts = False
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: IstaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ista Calista sensors."""
    _LOGGER.error('called async_setup_entry')
    coordinator = config_entry.runtime_data

    # first_device = next(iter(coordinator.data.values()))  # Get the first device in the dictionary
    # _LOGGER.warning(f"First device SN: {first_device.serial_number}")
    # _LOGGER.warning(f"First device history: {first_device.history}")

    async_add_entities(
        (
            IstaSensor(coordinator, serial_number, description)
            for description in SENSOR_DESCRIPTIONS
            for serial_number, device in coordinator.data.items()
            if description.exists_fn(device)
        )
    )


class IstaSensor(CoordinatorEntity[IstaCoordinator], SensorEntity):
    """Ista Calista sensor."""

    entity_description: CalistaSensorEntityDescription
    _attr_has_entity_name = True
    device_entry: DeviceEntry

    def __init__(
        self,
        coordinator: IstaCoordinator,
        serial_number: str,
        entity_description,
    ) -> None:
        """Initialize the ista Calista sensor."""
        super().__init__(coordinator)
        self.serial_number = serial_number
        self._attr_unique_id = f"{serial_number}_{entity_description.key}"
        self.entity_description = entity_description

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.serial_number)},
            name=f"{self.coordinator.data[self.serial_number].name}",
            manufacturer="ista SE",
            model="ista Calista",
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state of the device."""
        return self.entity_description.value_fn(
            self.coordinator.data[self.serial_number]
        )

    async def async_added_to_hass(self) -> None:
        """When added to hass."""
        # perform initial statistics import when sensor is added, otherwise it would take
        # 1 day when _handle_coordinator_update is triggered for the first time.
        if self.entity_description.generate_lts:
            await self.update_statistics()
        await super().async_added_to_hass()

    async def _handle_coordinator_update(self) -> None:
        """Handle coordinator update."""
        if self.entity_description.generate_lts:
                    await self.update_statistics()

    async def update_statistics(self) -> None:
        """Import ista EcoTrend historical statistics."""

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

        last_stats_sum = 0.0
        last_stats_state = 0.0
        last_stats_date = None
        last_stats_last_reset = None
        history = self.coordinator.data[self.serial_number].history

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
        # Loop through the list with the current and previous reading
        for i in range(len(history)):
            current_reading = history[i].reading

            # If it's the first item, previous reading is 0
            previous_reading = history[i - 1].reading if i > 0 else last_stats_state

            if previous_reading > current_reading:
                last_stats_last_reset = history[i].date
                comsumption = 0
            else:
                comsumption = current_reading - previous_reading

            last_stats_sum += comsumption
            joined_history.append(
                {
                    "date": history[i].date,
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
            "name": f"{self.device_entry.name} {self.name}",
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": self.entity_description.native_unit_of_measurement,
        }
        if statistics:
            _LOGGER.debug("Insert statistics: %s %s", metadata, statistics)
            async_add_external_statistics(self.hass, metadata, statistics)
