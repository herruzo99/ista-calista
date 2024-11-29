"""Sensor platform for Ista Calista integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import logging
from typing import Callable, Dict

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
from homeassistant.helpers.device_registry import (
    DeviceEntry,
    DeviceInfo,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IstaConfigEntry
from .const import DOMAIN
from .coordinator import IstaCoordinator

_LOGGER = logging.getLogger(__name__)


class IstaConsumptionType(StrEnum):
    """Types of consumptions from ista."""

    HEATING = "heating"
    HOT_WATER = "warmwater"
    WATER = "water"


@dataclass(kw_only=True)
class CalistaSensorEntityDescription(SensorEntityDescription):
    """Describes Ista Calista sensor entity."""

    exists_fn: Callable[[Dict[str, any]], bool] = lambda _: True
    value_fn: Callable[[Dict[str, any]], StateType]


SENSOR_DESCRIPTIONS: tuple[CalistaSensorEntityDescription, ...] = (
    CalistaSensorEntityDescription(
        key="total_volume",
        translation_key="water",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: data["lectura_actual"],
        exists_fn=lambda data: data["tipo_equipo"]
        != "Radio Distribuidor de Costes de Calefacción",
    ),
    CalistaSensorEntityDescription(
        key="relative_heating",
        translation_key="heating",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: data["lectura_actual"],
        exists_fn=lambda data: data["tipo_equipo"]
        == "Radio Distribuidor de Costes de Calefacción",
    ),
    CalistaSensorEntityDescription(
        key="last_reading",
        translation_key="last_date",
        native_unit_of_measurement=None,
        device_class=SensorDeviceClass.DATE,
        state_class=None,
        value_fn=lambda data: datetime.strptime(data["fecha"], "%d/%m/%Y"),
        exists_fn=lambda data: True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: IstaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ista Calista sensors."""

    coordinator = config_entry.runtime_data

    # Check if coordinator is ready and data is available
    if coordinator.data is None:
        # If data is not available, wait for it asynchronously
        await coordinator.async_refresh()
        # Ensure the data is populated after refresh
        if coordinator.data is None:
            return False  # No data available, so we stop setting up the entities

    _LOGGER.info(
        (sensor_id, data, description)
        for description in SENSOR_DESCRIPTIONS
        for sensor_id, data in coordinator.data.items()
        if description.exists_fn(data)
    )

    async_add_entities(
        IstaSensor(coordinator, sensor_id, data, description)
        for description in SENSOR_DESCRIPTIONS
        for sensor_id, data in coordinator.data.items()
        if description.exists_fn(data)
    )


class IstaSensor(CoordinatorEntity[IstaCoordinator], SensorEntity):
    """Ista Calista sensor."""

    entity_description: CalistaSensorEntityDescription
    _attr_has_entity_name = True
    device_entry: DeviceEntry

    def __init__(
        self,
        coordinator: IstaCoordinator,
        sensor_id: str,
        data: str,
        entity_description,
    ) -> None:
        """Initialize the ista Calista sensor."""
        super().__init__(coordinator)
        self.sensor_id = sensor_id

        self._attr_unique_id = f"{sensor_id}_{entity_description.key}"
        self.entity_description = entity_description

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.sensor_id)},
            name=f"{self.coordinator.data[self.sensor_id]['tipo_equipo']} - {self.coordinator.data[self.sensor_id]['ubicacion']}",
            manufacturer="ista SE",
            model="ista Calista",
            model_id="TBD",
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state of the device."""
        return self.entity_description.value_fn(self.coordinator.data[self.sensor_id])

    async def async_added_to_hass(self) -> None:
        """When added to hass."""
        # perform initial statistics import when sensor is added, otherwise it would take
        # 1 day when _handle_coordinator_update is triggered for the first time.
        await super().async_added_to_hass()

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update."""
        asyncio.run_coroutine_threadsafe(self.update_statistics(), self.hass.loop)
