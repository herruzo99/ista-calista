"""Tests for the config flow of ista_calista."""


from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pycalista_ista import IstaApiError, IstaConnectionError, IstaLoginError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista.config_flow import get_default_offset_date
from custom_components.ista_calista.const import CONF_OFFSET, DOMAIN

from .const import MOCK_CONFIG


async def test_show_user_form_initial(recorder_mock, hass, enable_custom_integrations):
    """Test that the user step of config flow shows a form with default offset."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    # Find the schema key for CONF_OFFSET and check its default value.
    # The key is a voluptuous Marker object (Required or Optional).
    offset_key = next(
        (
            key
            for key, value in result["data_schema"].schema.items()
            if key.schema == CONF_OFFSET
        ),
        None,
    )
    assert offset_key is not None
    assert (
        hasattr(offset_key, "description")
        and "suggested_value" in offset_key.description
    )
    assert offset_key.description["suggested_value"] == get_default_offset_date()


async def test_user_flow_success(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test completing the user step with valid credentials."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )
    await hass.async_block_till_done()
    # Expect a config entry to be created
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == MOCK_CONFIG["email"]
    assert result2["data"] == MOCK_CONFIG


async def test_user_flow_invalid_auth(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test user flow handles invalid authentication."""
    mock_pycalista.login.side_effect = IstaLoginError("Invalid credentials")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )
    await hass.async_block_till_done()
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test user flow handles connection errors."""
    mock_pycalista.login.side_effect = IstaConnectionError("No connection")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )
    await hass.async_block_till_done()
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_user_flow_api_error(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test user flow handles generic API errors."""
    mock_pycalista.login.side_effect = IstaApiError("API failure")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )
    await hass.async_block_till_done()
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_exception(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test user flow handles an unknown exception during validation."""
    mock_pycalista.login.side_effect = Exception("Something broke")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"]["base"] == "unknown"


async def test_user_flow_offset_errors(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test invalid offset date inputs produce appropriate errors."""
    # Offset too recent (today's date)
    too_recent = {
        "email": "user@example.com",
        "password": "pw",
        "consumption_offset_date": "2025-08-01",
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=too_recent,
    )
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {CONF_OFFSET: "offset_too_recent"}


async def test_flow_abort_duplicate(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test flow aborts if an entry with the same email already exists."""
    # A unique_id must be set for the duplicate check to work.
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "email": MOCK_CONFIG["email"],
            "password": "pw",
            "consumption_offset_date": "2024-01-01",
        },
        unique_id=MOCK_CONFIG["email"].lower(),
    )
    existing_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG,
    )
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


async def test_reauth_flow_shows_password_form(
    recorder_mock, hass, enable_custom_integrations
):
    """Test the reauthentication flow shows the password entry form."""
    # Reauth flows must be initiated from an existing config entry.
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"].lower()
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_flow_updates_entry(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test completing reauthentication updates the config entry and aborts."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"].lower()
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"password": "newpassword"},
    )
    await hass.async_block_till_done()
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    # Verify the password in the actual config entry was updated.
    assert (
        hass.config_entries.async_get_entry(entry.entry_id).data[CONF_PASSWORD]
        == "newpassword"
    )


async def test_reauth_fails_and_shows_form_again(
    recorder_mock, hass, enable_custom_integrations, mock_pycalista
):
    """Test that a failed reauthentication shows the form again with an error."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=MOCK_CONFIG["email"].lower()
    )
    entry.add_to_hass(hass)
    mock_pycalista.login.side_effect = IstaLoginError("Reauth failed")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"password": "wrongpassword"}
    )
    await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reauth_confirm"
    assert result2["errors"] == {"base": "invalid_auth"}
