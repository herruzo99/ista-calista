"""Constants for the ista Calista integration."""

from typing import Final

import aiohttp

from homeassistant.const import Platform

# --- Core Integration Constants ---
DOMAIN: Final[str] = "ista_calista"
MANUFACTURER: Final[str] = "ista"

# --- Platforms ---
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

# --- Events ---
LTS_UPDATED_EVENT: Final[str] = "ista_calista_lts_updated"

# --- Configuration Constants ---
# CONF_EMAIL and CONF_PASSWORD are imported from homeassistant.const
CONF_OFFSET: Final[str] = "consumption_offset_date"  # Renamed for clarity
CONF_UPDATE_INTERVAL: Final[str] = "update_interval"
CONF_LOG_LEVEL: Final[str] = "log_level"
CONF_SEASON_START_MONTH: Final[str] = "season_start_month"
CONF_SEASON_START_DAY: Final[str] = "season_start_day"
CONF_SEASON_START: Final[str] = "season_start"
CONF_ACCOUNT_ID: Final[str] = "account_id"
CONF_ACCOUNT_LABEL: Final[str] = "account_label"

# --- Sessions ---
# One private session per config entry and per config-flow validation. The
# library closes only the sessions that it created itself.
SESSION_TIMEOUT: Final[aiohttp.ClientTimeout] = aiohttp.ClientTimeout(total=30)

# --- Multi-property support ---
# Every config entry owns one portal property. Entries made before 0.10.0 have
# no account_id in their data and are resolved once during setup.

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
