"""Constants for the ista Calista integration."""

from typing import Final

from homeassistant.const import Platform

# --- Core Integration Constants ---
DOMAIN: Final[str] = "ista_calista"
MANUFACTURER: Final[str] = "ista"

# --- Platforms ---
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR, Platform.BINARY_SENSOR]

# --- Configuration Constants ---
# CONF_EMAIL and CONF_PASSWORD are imported from homeassistant.const
CONF_OFFSET: Final[str] = "consumption_offset_date"  # Renamed for clarity
CONF_UPDATE_INTERVAL: Final[str] = "update_interval"
CONF_LOG_LEVEL: Final[str] = "log_level"
CONF_SEASON_START_MONTH: Final[str] = "season_start_month"
CONF_SEASON_START_DAY: Final[str] = "season_start_day"
CONF_SEASON_START: Final[str] = "season_start"

# --- Defaults ---
DEFAULT_UPDATE_INTERVAL_HOURS: Final[int] = 24  # Default update interval
DEFAULT_LOG_LEVEL: Final[str] = "INFO"  # Default log level
DEFAULT_SEASON_START_MONTH: Final[int] = 9
DEFAULT_SEASON_START_DAY: Final[int] = 1
MIN_UPDATE_INTERVAL_HOURS: Final[int] = 1
MAX_UPDATE_INTERVAL_HOURS: Final[int] = 168

# --- Other Constants ---
LOG_LEVELS: Final[list[str]] = [
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
]  # Available log levels
