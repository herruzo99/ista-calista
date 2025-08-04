"""Config flow for ista Calista integration."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import voluptuous as vol
from dateutil.relativedelta import relativedelta
from pycalista_ista import IstaApiError, IstaConnectionError, IstaLoginError, PyCalistaIsta

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    DateSelector,
    DateSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

# This is the correct source for our integration's specific constants.
from .const import (
    CONF_LOG_LEVEL,
    CONF_OFFSET,
    CONF_UPDATE_INTERVAL,
    DEFAULT_LOG_LEVEL,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    LOG_LEVELS,
)

_LOGGER = logging.getLogger(__name__)


def get_default_offset_date() -> str:
    """Return the default offset date (1 year ago)."""
    return (dt_util.now().date() - relativedelta(years=1)).isoformat()


def get_min_offset_date() -> date:
    """Return the minimum allowed offset date (1 month ago)."""
    return dt_util.now().date() - relativedelta(months=1)


class IstaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ista Calista."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> IstaOptionsFlowHandler:
        """Get the options flow for this handler."""
        return IstaOptionsFlowHandler()

    async def _validate_user_input(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Validate user input for credentials and settings."""
        errors: dict[str, str] = {}
        email = user_input[CONF_EMAIL]
        password = user_input[CONF_PASSWORD]
        _LOGGER.debug("Starting input validation for user: %s", email)

        if CONF_OFFSET in user_input:
            try:
                offset_date = date.fromisoformat(user_input[CONF_OFFSET])
                min_date = get_min_offset_date()
                if offset_date > min_date:
                    _LOGGER.warning(
                        "Validation failed: Offset date %s is more recent than minimum allowed %s.",
                        offset_date,
                        min_date,
                    )
                    errors[CONF_OFFSET] = "offset_too_recent"
            except ValueError:
                _LOGGER.warning("Validation failed: Invalid date format for offset.")
                errors[CONF_OFFSET] = "invalid_date_format"

        if errors:
            _LOGGER.debug("Input validation failed: %s", errors)
            return errors

        session = async_get_clientsession(self.hass)
        ista = PyCalistaIsta(email, password, session)
        try:
            _LOGGER.debug("Attempting to log in to Ista API to validate credentials.")
            await ista.login()
            _LOGGER.debug("Ista API login validation successful for %s.", email)
        except IstaLoginError:
            _LOGGER.warning("Authentication failed during validation for user %s.", email)
            errors["base"] = "invalid_auth"
        except (IstaConnectionError, IstaApiError) as e:
            _LOGGER.error("API connection failed during validation: %s", e)
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception during validation for %s", email)
            errors["base"] = "unknown"
        finally:
            await ista.close()
            _LOGGER.debug("Ista API session closed after validation.")

        return errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        _LOGGER.debug(
            "Handling 'user' step. User input provided: %s", user_input is not None
        )

        if user_input is not None:
            errors = await self._validate_user_input(user_input)
            if not errors:
                email = user_input[CONF_EMAIL]
                _LOGGER.info("Validation successful. Creating config entry for %s", email)
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=email, data=user_input)

        suggested_values = user_input or {}
        if CONF_OFFSET not in suggested_values:
            suggested_values[CONF_OFFSET] = get_default_offset_date()
        _LOGGER.debug("Showing user form with suggested values: %s", suggested_values)

        schema = self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_EMAIL): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.EMAIL, autocomplete="email"
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
            ),
            suggested_values=suggested_values,
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle initiation of re-authentication."""
        _LOGGER.debug(
            "Handling 'reauth' step for entry: %s", entry_data.get(CONF_EMAIL)
        )
        self.context["entry_data"] = entry_data
        self.context["title_placeholder"] = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication confirmation (password step)."""
        errors: dict[str, str] = {}
        entry_data = self.context["entry_data"]
        email = entry_data[CONF_EMAIL]
        _LOGGER.debug(
            "Handling 'reauth_confirm' step for %s. User input provided: %s",
            email,
            user_input is not None,
        )

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            validation_input = {CONF_EMAIL: email, CONF_PASSWORD: password}
            _LOGGER.debug("Validating new password for re-authentication.")
            errors = await self._validate_user_input(validation_input)

            if not errors:
                _LOGGER.info("Re-authentication successful for %s.", email)
                existing_entry = await self.async_set_unique_id(email.lower())
                if existing_entry:
                    self.hass.config_entries.async_update_entry(
                        existing_entry, data={**entry_data, CONF_PASSWORD: password}
                    )
                    await self.hass.config_entries.async_reload(
                        existing_entry.entry_id
                    )
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={CONF_EMAIL: email},
        )


class IstaOptionsFlowHandler(OptionsFlow):
    """Handle options flow for ista Calista."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        _LOGGER.debug(
            "Handling options 'init' step. User input provided: %s",
            user_input is not None,
        )
        if user_input is not None:
            _LOGGER.info(
                "Updating options for entry %s with: %s",
                self.config_entry.entry_id,
                user_input,
            )
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=168,
                        step=1,
                        mode=NumberSelectorMode.SLIDER,
                        unit_of_measurement="hours",
                    )
                ),
                vol.Optional(
                    CONF_LOG_LEVEL,
                    default=self.config_entry.options.get(
                        CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=LOG_LEVELS,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="log_level",
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)