"""Config flow for ista Calista integration."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import voluptuous as vol
from dateutil.relativedelta import relativedelta
from pycalista_ista import (
    IstaApiError,
    IstaConnectionError,
    IstaLoginError,
    PyCalistaIsta,
)

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_OFFSET, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    DateSelector,
    DateSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS, DOMAIN

_LOGGER = logging.getLogger(__name__)

# --- Helper Functions ---

def get_default_offset_date() -> str:
    """Return the default offset date (1 year ago)."""
    return (dt_util.now().date() - relativedelta(years=1)).isoformat()

def get_min_offset_date() -> date:
    """Return the minimum allowed offset date (1 month ago)."""
    return dt_util.now().date() - relativedelta(months=1)

# --- Schemas ---

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.EMAIL,
                autocomplete="email",
            )
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD,
                autocomplete="current-password",
            )
        ),
        vol.Required(CONF_OFFSET): DateSelector(DateSelectorConfig()),
    }
)

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD,
                autocomplete="current-password",
            )
        ),
    }
)

# --- Config Flow ---

class IstaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ista Calista."""

    VERSION = 1

    async def _validate_user_input(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate user input common to user and reauth steps."""
        errors: dict[str, str] = {}
        email = user_input[CONF_EMAIL]
        password = user_input[CONF_PASSWORD]

        if CONF_OFFSET in user_input:
            try:
                selected_offset_date = date.fromisoformat(user_input[CONF_OFFSET])
                min_allowed_date = get_min_offset_date()
                if selected_offset_date > min_allowed_date:
                     _LOGGER.warning(
                         "Validation failed: Offset date %s is too recent (must be before %s)",
                         selected_offset_date, min_allowed_date
                     )
                     # Use the key defined in strings.json
                     errors[CONF_OFFSET] = "offset_too_recent"
            except ValueError:
                errors[CONF_OFFSET] = "invalid_date_format" # Use key from strings.json

        if errors:
             return errors

        session = async_get_clientsession(self.hass)
        ista = PyCalistaIsta(email, password, session)
        try:
            _LOGGER.info("Attempting API login validation for %s", email)
            await ista.login()
            _LOGGER.info("API login validation successful for %s", email)
        except IstaLoginError:
            _LOGGER.warning("Invalid authentication for %s during validation", email)
            errors["base"] = "invalid_auth" # Use key from strings.json
        except (IstaConnectionError, IstaApiError) as err:
            _LOGGER.error("Connection/API error during validation for %s: %s", email, err)
            errors["base"] = "cannot_connect" # Use key from strings.json
        except Exception:
            _LOGGER.exception("Unexpected exception during validation for %s", email)
            errors["base"] = "unknown" # Use key from strings.json

        return errors


    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_user_input(user_input)

            if not errors:
                email = user_input[CONF_EMAIL]
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured(updates=user_input)

                config_data = {
                    CONF_EMAIL: email,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_OFFSET: user_input[CONF_OFFSET],
                }

                _LOGGER.info("Creating new config entry for %s", email)
                return self.async_create_entry(title=email, data=config_data)

        suggested_values = user_input or {}
        if CONF_OFFSET not in suggested_values:
             suggested_values[CONF_OFFSET] = get_default_offset_date()

        data_schema = self.add_suggested_values_to_schema(
            STEP_USER_DATA_SCHEMA, suggested_values=suggested_values
        )

        # Pass the errors dictionary here. HA should look up the keys.
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=None,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle initiation of re-authentication."""
        _LOGGER.debug("Starting reauth flow for %s", entry_data.get(CONF_EMAIL))
        self.context["entry_data"] = entry_data
        self.context["title_placeholder"] = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication confirmation (password step)."""
        errors: dict[str, str] = {}
        original_entry_data = self.context.get("entry_data", {})
        email = original_entry_data.get(CONF_EMAIL)

        if not email:
             _LOGGER.error("Reauth flow missing email in context.")
             return self.async_abort(reason="unknown")

        if user_input is not None:
            validation_input = {
                 CONF_EMAIL: email,
                 CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            errors = await self._validate_user_input(validation_input)

            if not errors:
                existing_entry = await self.async_set_unique_id(email.lower())
                if existing_entry:
                    updated_data = {**existing_entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                    self.hass.config_entries.async_update_entry(
                        existing_entry, data=updated_data
                    )
                    await self.hass.config_entries.async_reload(existing_entry.entry_id)
                    _LOGGER.info("Re-authentication successful and entry updated for %s", email)
                    return self.async_abort(reason="reauth_successful")
                else:
                     _LOGGER.error("Could not find existing entry during reauth for %s", email)
                     errors["base"] = "unknown"

        # Pass the errors dictionary here. HA should look up the keys.
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={CONF_EMAIL: email},
        )