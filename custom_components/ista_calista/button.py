"""Button platform for ista Calista integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
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
        self._attr_unique_id = f"{account_namespace(config_entry)}_refresh"
        self._attr_device_info = account_device_info(config_entry)

    async def async_press(self) -> None:
        """Trigger an immediate data refresh from the ista Calista API."""
        _LOGGER.debug("Manual refresh requested via button.")
        await self.coordinator.async_request_refresh()
