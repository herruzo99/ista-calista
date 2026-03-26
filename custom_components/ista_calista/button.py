"""Button platform for ista Calista integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import IstaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ista Calista button entities."""
    coordinator: IstaCoordinator = config_entry.runtime_data
    async_add_entities([IstaRefreshButton(coordinator, config_entry)])


class IstaRefreshButton(CoordinatorEntity[IstaCoordinator], ButtonEntity):
    """Button that triggers a manual data refresh from the ista Calista API."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_data"

    def __init__(
        self, coordinator: IstaCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{config_entry.unique_id}_refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"Ista Account {config_entry.data.get(CONF_EMAIL, '')}",
            manufacturer=MANUFACTURER,
            model="Ista Calista Account",
            configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
        )

    async def async_press(self) -> None:
        """Trigger an immediate data refresh from the ista Calista API."""
        _LOGGER.debug("Manual refresh requested via button.")
        await self.coordinator.async_request_refresh()
