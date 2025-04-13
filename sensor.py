"""Sensor platform for the Ista Calista integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import logging
import math
from typing import TYPE_CHECKING, Any, Final, cast

from pycalista_ista import ColdWaterDevice, Device, HeatingDevice, HotWaterDevice, Reading
_LOGGER: Final = logging.getLogger(__name__)

# Import recorder components safely
try:
    from homeassistant.components.recorder import Recorder, get_instance
    from homeassistant.components.recorder.models.statistics import (
        StatisticData,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
        get_last_statistics, # Keep sync version for potential executor use if needed
    )
    RECORDER_AVAILABLE = True
except ImportError:
    RECORDER_AVAILABLE = False
    _LOGGER.warning("Recorder component not available. Statistics features will be limited.")


from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
    UnitOfEnergy,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER
from .coordinator import IstaCoordinator

if TYPE_CHECKING:
    from .coordinator import IstaConfigEntry


PARALLEL_UPDATES = 0
STATS_LOCK_TIMEOUT = 60


class IstaSensorEntity(StrEnum):
    """Enum for Ista Calista Sensor Keys."""
    HEATING = "heating"
    HOT_WATER = "hot_water"
    WATER = "water"
    LAST_READING_DATE = "last_reading_date"


@dataclass(frozen=True, kw_only=True)
class CalistaSensorEntityDescription(SensorEntityDescription):
    """Describes an Ista Calista sensor entity."""
    exists_fn: Callable[[Device], bool] = lambda _: True
    value_fn: Callable[[Device], StateType | datetime]
    generate_lts: bool = False
    attr_fn: Callable[[Device], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: Final[tuple[CalistaSensorEntityDescription, ...]] = (
    CalistaSensorEntityDescription(
        key=IstaSensorEntity.WATER,
        translation_key=IstaSensorEntity.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda device: device.last_reading.reading if device.last_reading else None,
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
        value_fn=lambda device: device.last_reading.reading if device.last_reading else None,
        exists_fn=lambda device: isinstance(device, HotWaterDevice),
        generate_lts=True,
        has_entity_name=True,
    ),
    CalistaSensorEntityDescription(
        key=IstaSensorEntity.HEATING,
        translation_key=IstaSensorEntity.HEATING,
        native_unit_of_measurement=None,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda device: device.last_reading.reading if device.last_reading else None,
        exists_fn=lambda device: isinstance(device, HeatingDevice),
        generate_lts=True,
        has_entity_name=True,
    ),
    CalistaSensorEntityDescription(
        key=IstaSensorEntity.LAST_READING_DATE,
        translation_key="last_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda device: device.last_reading.date if device.last_reading else None,
        exists_fn=lambda device: bool(device.last_reading),
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
    """Set up Ista Calista sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    _LOGGER.debug("Setting up Ista Calista sensors for entry %s", config_entry.entry_id)

    if not coordinator.data or not coordinator.data.get("devices"):
        _LOGGER.warning("Coordinator has no device data; skipping sensor setup for %s", config_entry.entry_id)
        return

    devices = coordinator.data["devices"]
    _LOGGER.debug("Found %d devices in coordinator data for %s", len(devices), config_entry.entry_id)

    entities_to_add: list[IstaSensor] = []
    added_entity_keys: set[tuple[str, str]] = set()

    for serial_number, device in devices.items():
         _LOGGER.debug("Processing device - Serial: %s, Type: %s", serial_number, type(device).__name__)
         for description in SENSOR_DESCRIPTIONS:
            entity_key_tuple = (serial_number, description.key)
            # Ensure unique_id is generated before checking existence
            unique_id = f"{DOMAIN}_{serial_number}_{description.key}"
            if entity_key_tuple not in added_entity_keys and description.exists_fn(device):
                _LOGGER.debug(
                    "Creating sensor for %s - Key: %s, UniqueID: %s",
                    serial_number,
                    description.key,
                    unique_id # Log the unique ID being used
                )
                entities_to_add.append(IstaSensor(coordinator, serial_number, description))
                added_entity_keys.add(entity_key_tuple)

    _LOGGER.info("Adding %d Ista Calista sensor entities for %s", len(entities_to_add), config_entry.entry_id)
    if entities_to_add:
        async_add_entities(entities_to_add)


class IstaSensor(CoordinatorEntity[IstaCoordinator], SensorEntity):
    """Representation of an Ista Calista sensor."""

    entity_description: CalistaSensorEntityDescription
    _attr_has_entity_name = True
    _serial_number: str
    _stats_lock: asyncio.Lock

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
        # Set unique_id first, as entity_id generation depends on it
        self._attr_unique_id = f"{DOMAIN}_{serial_number}_{entity_description.key}"
        self._attr_entity_category = entity_description.entity_category
        self._stats_lock = asyncio.Lock()

        self._update_device_info() # Set initial device info

        self._log_prefix = f"[sensor.{self.entity_id}] " # Use actual entity_id once available
        # Note: self.entity_id might be None right after __init__, use unique_id for early logs
        _LOGGER.debug("[%s] Initialized sensor", self._attr_unique_id)


    def _update_device_info(self) -> None:
        """Update the device info based on coordinator data."""
        try:
            device = self.coordinator.data["devices"][self._serial_number]
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self._serial_number)},
                name=self._generate_device_name(device),
                manufacturer=MANUFACTURER,
                model=self._get_device_model(device),
                configuration_url="https://oficina.ista.es/GesCon/MainPageAbo.do",
            )
        except KeyError:
             self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._serial_number)})
             _LOGGER.warning("[%s] Device %s not found in coordinator data during init.", self._attr_unique_id, self._serial_number)
        except Exception as e:
             _LOGGER.error("[%s] Error updating device info for %s: %s", self._attr_unique_id, self._serial_number, e)
             self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._serial_number)})


    def _generate_device_name(self, device: Device) -> str:
        """Generate a friendly name for the device."""
        if device.location:
            base_name = device.location
            # Add type if location isn't specific enough (optional)
            # if isinstance(device, ColdWaterDevice): return f"{base_name} Water"
            return base_name
        # Fallback names using last 4 digits of serial for some uniqueness
        serial_suffix = self._serial_number[-4:] if len(self._serial_number) >= 4 else self._serial_number
        if isinstance(device, ColdWaterDevice): return f"Water Meter {serial_suffix}"
        if isinstance(device, HotWaterDevice): return f"Hot Water Meter {serial_suffix}"
        if isinstance(device, HeatingDevice): return f"Heating Meter {serial_suffix}"
        return f"Ista Device {serial_suffix}"

    def _get_device_model(self, device: Device) -> str:
        """Return a model name based on the device type."""
        if isinstance(device, ColdWaterDevice): return "Cold Water Meter"
        if isinstance(device, HotWaterDevice): return "Hot Water Meter"
        if isinstance(device, HeatingDevice): return "Heating Meter"
        return "Generic Meter"

    @property
    def _device_data(self) -> Device | None:
        """Helper property to safely get the device data from the coordinator."""
        try:
            # Ensure coordinator.data and devices exist before accessing
            if self.coordinator.data and "devices" in self.coordinator.data:
                return self.coordinator.data["devices"].get(self._serial_number)
        except Exception: # Catch potential errors during access
             _LOGGER.exception("[%s] Error accessing device data from coordinator", self._attr_unique_id)
        return None


    @property
    def native_value(self) -> StateType | datetime:
        """Return the state of the sensor."""
        device = self._device_data
        if device is None:
            return STATE_UNAVAILABLE if self.coordinator.last_update_success else STATE_UNKNOWN

        try:
            value = self.entity_description.value_fn(device)
            if isinstance(value, datetime) and value.tzinfo is None:
                value = value.replace(tzinfo=UTC) # Ensure timezone

            if value is None:
                 return STATE_UNKNOWN

            if self.entity_description.state_class == SensorStateClass.TOTAL_INCREASING:
                if not isinstance(value, (int, float)) or value < 0:
                    _LOGGER.warning("[%s] Invalid numeric value for TOTAL_INCREASING sensor: %s", self.entity_id, value)
                    return STATE_UNKNOWN

            return value
        except Exception as err:
            _LOGGER.error("[%s] Error calculating native value: %s", self.entity_id, err, exc_info=True)
            return STATE_UNKNOWN

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Available if coordinator succeeded and the specific device data is present
        return super().available and self._device_data is not None


    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Update log prefix if entity_id is now available
        if not self._log_prefix.startswith(f"[sensor.{self.entity_id}]"):
            self._log_prefix = f"[sensor.{self.entity_id}] "

        if not self.coordinator.last_update_success:
            _LOGGER.debug("%s Coordinator update failed, sensor unavailable", self._log_prefix)
            super()._handle_coordinator_update() # Let CoordinatorEntity handle availability
            return

        if self._device_data is None:
             _LOGGER.warning("%s Device %s missing in coordinator update", self._log_prefix, self._serial_number)
             super()._handle_coordinator_update() # Let CoordinatorEntity handle availability
             return

        self._update_device_info()
        super()._handle_coordinator_update() # Update state
        _LOGGER.debug("%s State updated to: %s", self._log_prefix, self.native_value)

        # --- Statistics Update Logic ---
        if RECORDER_AVAILABLE and self.entity_description.generate_lts:
            _LOGGER.debug("%s Scheduling statistics update task.", self._log_prefix)
            self.hass.async_create_task(
                self._async_update_statistics_task(),
                name=f"{self._attr_unique_id}_incremental_stats_update"
            )
        # --- End Statistics Update Logic ---


    async def async_added_to_hass(self) -> None:
        """Handle entity addition to Home Assistant."""
        await super().async_added_to_hass()
        # Update log prefix once entity_id is assigned
        self._log_prefix = f"[sensor.{self.entity_id}] "
        _LOGGER.debug("%s Sensor added to HASS.", self._log_prefix)
        # --- Statistics Update Logic ---
        _LOGGER.debug("%s Scheduling initial statistics update task.", self._log_prefix)
        self.hass.async_create_task(
            self._async_update_statistics_task(),
            name=f"{self._attr_unique_id}_incremental_stats_update"
        )
        # --- End Statistics Update Logic ---

    def _generate_statistic_id(self) -> str:
        """Generate the statistic_id using the stable unique_id."""
        # Use the unique_id directly for stability: domain:unique_id
        return f"{DOMAIN}:{self._attr_unique_id}"


    async def _async_update_statistics_task(self) -> None:
        """Task to perform statistics import (initial or incremental)."""
        if not self.entity_description.generate_lts or not RECORDER_AVAILABLE:
            return

        try:
            async with asyncio.timeout(STATS_LOCK_TIMEOUT):
                await self._stats_lock.acquire()
        except TimeoutError:
            _LOGGER.warning("%s Statistics update already in progress, skipping.", self._log_prefix)
            return
        except Exception as lock_err:
             _LOGGER.error("%s Error acquiring statistics lock: %s", self._log_prefix, lock_err)
             return

        try:
            _LOGGER.info("%s Starting statistics update", self._log_prefix)
            await self._perform_statistics_update()
            _LOGGER.info("%s Statistics update finished", self._log_prefix)
        except Exception as e:
            _LOGGER.exception("%s Error during statistics update: %s", self._log_prefix, e)
        finally:
            if self._stats_lock.locked():
                self._stats_lock.release()


    async def _perform_statistics_update(self) -> None:
        """Fetch and process data for long-term statistics."""
        device = self._device_data
        if not device or not device.history:
            _LOGGER.warning("%s No device data or history available for statistics.", self._log_prefix)
            return

        # Use the stable statistic ID generation method
        statistic_id = self._generate_statistic_id()
        _LOGGER.debug("%s Preparing statistics for ID: %s", self._log_prefix, statistic_id)

        recorder_instance: Recorder | None = get_instance(self.hass)
        if not recorder_instance:
             _LOGGER.warning("%s Recorder instance not available, cannot update statistics.", self._log_prefix)
             return # Cannot proceed without recorder

        # --- Get Last Statistics ---
        # Use executor for sync get_last_statistics
        last_stats_data = await recorder_instance.async_add_executor_job(
             get_last_statistics, self.hass, 1, statistic_id, True, {"last_reset", "state", "sum", "end"}
        )

        last_stats_sum: float = 0.0
        last_stats_state: float | None = None
        last_reset_ts: float | None = None
        last_stats_end_ts: float | None = None

        if last_stats_data and statistic_id in last_stats_data:
             stats = last_stats_data[statistic_id][0]
             last_stats_sum = stats.get("sum") or 0.0
             last_stats_state = stats.get("state")
             last_reset_ts = stats.get("last_reset")
             last_stats_end_ts = stats.get("end")
             _LOGGER.debug("%s Found existing stats. Last Sum: %s, Last State: %s, Last Reset: %s, Last End: %s",
                           self._log_prefix, last_stats_sum, last_stats_state,
                           dt_util.utc_from_timestamp(last_reset_ts) if last_reset_ts else None,
                           dt_util.utc_from_timestamp(last_stats_end_ts) if last_stats_end_ts else None)
        else:
             _LOGGER.debug("%s No existing statistics found for %s.", self._log_prefix, statistic_id)
             first_reading_date = device.history[0].date if device.history else None
             last_reset_ts = first_reading_date.timestamp() if first_reading_date else None


        # --- Prepare Metadata ---
        device_info = self.device_info or {}
        # Use device name from registry if available, otherwise generate
        device_friendly_name = device_info.get("name") or self._generate_device_name(device)
        # Use sensor name from entity description
        sensor_name = self.entity_description.key

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"{device_friendly_name} {sensor_name}", # Use generated name
            source=DOMAIN,
            statistic_id=statistic_id, # Use the stable ID
            unit_of_measurement=self.entity_description.native_unit_of_measurement,
        )

        # --- Process History and Generate Statistics ---
        new_statistics: list[StatisticData] = []
        current_sum = last_stats_sum
        current_last_reset_ts = last_reset_ts

        readings_to_process = sorted(
            [
                reading for reading in device.history
                if reading.reading is not None and reading.reading >= 0 and
                   (last_stats_end_ts is None or reading.date.timestamp() > last_stats_end_ts) # Add buffer for timestamp comparison
            ],
            key=lambda r: r.date
        )

        if not readings_to_process:
            _LOGGER.debug("%s No new readings found to add to statistics for %s.", self._log_prefix, statistic_id)
            return

        _LOGGER.debug("%s Processing %d new readings for statistics for %s.", self._log_prefix, len(readings_to_process), statistic_id)

        previous_reading_value = last_stats_state

        for reading in readings_to_process:
            current_reading_value = reading.reading
            reading_ts = reading.date.timestamp()
            reading_start_dt = reading.date # Use reading's datetime (already UTC)

            if previous_reading_value is None:
                 consumption_since_last = 0
                 if current_last_reset_ts is None:
                     current_last_reset_ts = reading_ts
            else:
                 if current_reading_value < previous_reading_value:
                     
                     current_sum = current_reading_value
                     consumption_since_last = current_reading_value
                     current_last_reset_ts = reading_ts
                 else:
                     consumption_since_last = round(current_reading_value - previous_reading_value, 4)
                     current_sum += consumption_since_last

            current_sum = max(0.0, round(current_sum, 4))

            stat_data = StatisticData(
                start=reading_start_dt,
                state=round(current_reading_value, 4),
                sum=current_sum,
                last_reset=dt_util.utc_from_timestamp(current_last_reset_ts) if current_last_reset_ts else None,
            )
            new_statistics.append(stat_data)
            previous_reading_value = current_reading_value

        # --- Import Statistics ---
        if new_statistics:
            _LOGGER.info(
                "%s Importing %d new statistics entries for %s",
                self._log_prefix, len(new_statistics), statistic_id
            )
            _LOGGER.debug("%s Statistics metadata: %s", self._log_prefix, metadata)
            _LOGGER.debug("%s First new statistics entry: %s", self._log_prefix, new_statistics[0])
            _LOGGER.debug("%s Last new statistics entry: %s", self._log_prefix, new_statistics[-1])

            try:
                # async_add_external_statistics is awaitable
                async_add_external_statistics(self.hass, metadata, new_statistics)
                _LOGGER.debug("%s Statistics import successful for %s.", self._log_prefix, statistic_id)
            except Exception as import_err:
                 _LOGGER.error("%s Failed to import statistics for %s: %s", self._log_prefix, statistic_id, import_err, exc_info=True)
        else:
            _LOGGER.debug("%s No new statistics generated to import for %s.", self._log_prefix, statistic_id)

