"""Tests for constants in the ista_calista integration."""

from homeassistant.const import Platform

from custom_components.ista_calista.const import (
    CONF_LOG_LEVEL,
    CONF_OFFSET,
    CONF_UPDATE_INTERVAL,
    DEFAULT_LOG_LEVEL,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    LOG_LEVELS,
    MANUFACTURER,
    PLATFORMS,
)


def test_domain_and_manufacturer():
    """Test the domain and manufacturer constants."""
    assert DOMAIN == "ista_calista"
    assert MANUFACTURER == "ista"


def test_platforms():
    """Test that the sensor platform is specified."""
    assert isinstance(PLATFORMS, list)
    assert Platform.SENSOR in PLATFORMS


def test_config_constants():
    """Test that configuration constants are present and correct."""
    assert CONF_OFFSET == "consumption_offset_date"
    assert CONF_UPDATE_INTERVAL == "update_interval"
    assert CONF_LOG_LEVEL == "log_level"


def test_default_values_and_log_levels():
    """Test default values and available log levels."""
    assert DEFAULT_UPDATE_INTERVAL_HOURS == 24
    assert DEFAULT_LOG_LEVEL == "INFO"
    for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
        assert level in LOG_LEVELS
