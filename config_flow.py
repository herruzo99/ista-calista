"""Config flow for ista Calista integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (ConfigEntry, ConfigFlow,
                                          ConfigFlowResult)
from homeassistant.const import CONF_EMAIL, CONF_OFFSET, CONF_PASSWORD
from homeassistant.helpers.selector import (DateSelector, DateSelectorConfig,
                                            TextSelector, TextSelectorConfig,
                                            TextSelectorType)
from pycalista_ista import LoginError, PyCalistaIsta, ServerError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

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


class IstaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ista Calista."""

    VERSION = 1
    entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                ista = PyCalistaIsta(
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )
                await self.hass.async_add_executor_job(ista.login)
                ista.import_datetime_start = user_input[CONF_OFFSET]
                info = ista.get_account()
            except ServerError:
                errors["base"] = "cannot_connect"
            except LoginError:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                if TYPE_CHECKING:
                    assert info
                await self.async_set_unique_id(info)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info or "ista Calista",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauth when credentials become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth confirmation."""
        errors: dict[str, str] = {}

        reauth_entry = self._get_reauth_entry()
        if user_input is not None and self.entry:
            try:
                ista = PyCalistaIsta(
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )
                await self.hass.async_add_executor_job(ista.login)
            except ServerError:
                errors["base"] = "cannot_connect"
            except LoginError:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(reauth_entry, data=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                data_schema=STEP_USER_DATA_SCHEMA,
                suggested_values={
                    CONF_EMAIL: (
                        user_input[CONF_EMAIL]
                        if user_input is not None
                        else reauth_entry.data[CONF_EMAIL]
                    )
                },
            ),
            description_placeholders={
                CONF_EMAIL: reauth_entry.data[CONF_EMAIL],
            },
            errors=errors,
        )
