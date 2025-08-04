"""Tests for the options flow."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista.const import (
    CONF_LOG_LEVEL,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

from .const import MOCK_CONFIG


async def test_options_flow(
    hass: HomeAssistant, mock_pycalista, enable_custom_integrations
):
    """Test options flow."""
    # Setup the integration
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Open the options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    # Submit new options
    with patch(
        "custom_components.ista_calista.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_UPDATE_INTERVAL: 12, CONF_LOG_LEVEL: "DEBUG"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_UPDATE_INTERVAL] == 12
    assert entry.options[CONF_LOG_LEVEL] == "DEBUG"

    # Check that the integration was reloaded
    assert len(mock_setup_entry.mock_calls) == 1
