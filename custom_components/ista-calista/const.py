"""Constants for the ista Calista integration."""

from typing import Final

from homeassistant.const import Platform

# --- Core Integration Constants ---
DOMAIN: Final[str] = "ista_calista"
MANUFACTURER: Final[str] = "ista"

# --- Platforms ---
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR]

# --- Configuration Constants ---
# CONF_EMAIL and CONF_PASSWORD are imported from homeassistant.const
CONF_OFFSET: Final[str] = "consumption_offset_date" # Renamed for clarity
CONF_UPDATE_INTERVAL: Final[str] = "update_interval" # New constant for options flow

# --- Defaults ---
DEFAULT_UPDATE_INTERVAL_HOURS: Final[int] = 24 # Default update interval

# --- Other Constants ---
# Add any other integration-specific constants here

