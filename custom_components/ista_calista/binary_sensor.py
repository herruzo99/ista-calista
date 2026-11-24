"""Binary sensor platform for ista Calista integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .account import account_device_info, account_namespace
from .coordinator import IstaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ista Calista binary sensors."""
    coordinator: IstaCoordinator = config_entry.runtime_data
    
    async_add_entities([IstaConnectionBinarySensor(coordinator, config_entry)])


class IstaConnectionBinarySensor(CoordinatorEntity[IstaCoordinator], BinarySensorEntity):
    """Binary sensor for Ista Calista connection status."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IstaCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{account_namespace(config_entry)}_connection_status"
        )
        self._attr_device_info = account_device_info(config_entry)
        self.entity_description = BinarySensorEntityDescription(
            key="connection_status",
            translation_key="connection_status",
        )

    @property
    def is_on(self) -> bool:
        """Return true if the latest update was successful."""
        return self.coordinator.last_update_success
