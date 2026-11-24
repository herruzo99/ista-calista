"""Config flow for ista Calista integration."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import voluptuous as vol
from dateutil.relativedelta import relativedelta
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
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
from pycalista_ista import (
    IstaApiError,
    IstaConnectionError,
    IstaLoginError,
    PyCalistaIsta,
)

# This is the correct source for our integration's specific constants.
from .account import async_migrate_account_entities
from .const import (
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_LABEL,
    CONF_LOG_LEVEL,
    CONF_OFFSET,
    CONF_SEASON_START,
    CONF_SEASON_START_DAY,
    CONF_SEASON_START_MONTH,
    CONF_UPDATE_INTERVAL,
    DEFAULT_LOG_LEVEL,
    DEFAULT_SEASON_START_DAY,
    DEFAULT_SEASON_START_MONTH,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    LOG_LEVELS,
    MAX_UPDATE_INTERVAL_HOURS,
    MIN_UPDATE_INTERVAL_HOURS,
    SESSION_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


def get_default_offset_date() -> str:
    """Return the default offset date (1 year ago)."""
    result: date = dt_util.now().date() - relativedelta(years=1)
    return result.isoformat()


def get_min_offset_date() -> date:
    """Return the minimum allowed offset date (1 month ago)."""
    result: date = dt_util.now().date() - relativedelta(months=1)
    return result


def entry_title(email: str, label: str | None) -> str:
    """Return the config entry title of one property."""
    return f"{email} \u2014 {label}" if label else email


def unique_id_for(email: str, account_id: str) -> str:
    """Return the config entry unique ID of one property."""
    return f"{email.lower()}:{account_id}"


class IstaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ista Calista."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the flow."""
        self._accounts: list[Any] = []
        self._pending_input: dict[str, Any] = {}
        self._reconfigure_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> IstaOptionsFlowHandler:
        """Get the options flow for this handler."""
        return IstaOptionsFlowHandler()

    # ------------------------------------------------------------------ helpers

    def _validate_dates(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate the local settings. Does not touch the network."""
        errors: dict[str, str] = {}
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
        return errors

    async def _validate_user_input(
        self, user_input: dict[str, Any], account_id: str | None = None
    ) -> dict[str, str]:
        """Validate the credentials and read the properties of the account.

        The result is ``errors``; on success ``self._accounts`` holds the
        properties of the account.
        """
        errors = self._validate_dates(user_input)
        self._accounts = []
        if errors:
            _LOGGER.debug("Input validation failed: %s", errors)
            return errors

        email = user_input[CONF_EMAIL]
        password = user_input[CONF_PASSWORD]
        _LOGGER.debug("Starting input validation for user: %s", email)

        # A private session per validation attempt: two flows of one email must
        # not share cookies. The library does not close an injected session, so
        # this flow closes its own in the `finally` block.
        session = async_create_clientsession(self.hass, timeout=SESSION_TIMEOUT)
        ista: PyCalistaIsta | None = None
        try:
            # The constructor can raise (empty password). It stays inside the
            # try so that the session is always detached.
            if account_id:
                ista = PyCalistaIsta(email, password, session, account_id=account_id)
            else:
                ista = PyCalistaIsta(email, password, session)
            _LOGGER.debug("Attempting to log in to Ista API to validate credentials.")
            await ista.login()
            _LOGGER.debug("Ista API login validation successful for %s.", email)
            self._accounts = list(await ista.list_accounts())
            _LOGGER.debug(
                "Portal account holds %d propert(y/ies).", len(self._accounts)
            )
        except IstaLoginError:
            _LOGGER.warning(
                "Authentication failed during validation for user %s.", email
            )
            errors["base"] = "invalid_auth"
        except (IstaConnectionError, IstaApiError) as e:
            _LOGGER.error("API connection failed during validation: %s", e)
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception during validation for %s", email)
            errors["base"] = "unknown"
        finally:
            if ista is not None:
                await ista.close()
            # detach(), not close(): a clientsession of async_create_clientsession
            # has a close() that only reports usage.
            session.detach()
            _LOGGER.debug("Ista API session detached after validation.")

        return errors

    def _account_for(self, account_id: str) -> Any | None:
        """Return the known property with this ID, if any."""
        return next(
            (a for a in self._accounts if a.account_id == account_id),
            None,
        )

    def _resolve_existing_account(
        self, entry: ConfigEntry, allow_stored: bool = True
    ) -> Any | None:
        """Return the property an entry keeps, or None when a choice is needed."""
        account_id = entry.data.get(CONF_ACCOUNT_ID) if allow_stored else None
        if account_id is None:
            # A legacy entry can adopt the only property without a second form.
            return self._accounts[0] if len(self._accounts) == 1 else None
        return self._account_for(str(account_id))

    def _has_conflict(
        self,
        email: str,
        account_id: str,
        ignore_entry_id: str | None = None,
    ) -> bool:
        """Return True when another entry already uses this property.

        A legacy entry holds no property yet; it may become any property of the
        same email, so it conflicts too.
        """
        email_key = email.lower()
        for other in self._async_current_entries():
            if other.entry_id == ignore_entry_id:
                continue
            if str(other.data.get(CONF_EMAIL, "")).lower() != email_key:
                continue
            other_account = other.data.get(CONF_ACCOUNT_ID)
            if other_account is None or str(other_account) == account_id:
                return True
        return False

    def _entry_data(self, account: Any) -> dict[str, Any]:
        """Return the config entry data of one property."""
        data = {
            **self._pending_input,
            CONF_ACCOUNT_ID: str(account.account_id),
        }
        label = getattr(account, "label", None)
        if label:
            data[CONF_ACCOUNT_LABEL] = label
        return data

    async def _async_create_account_entry(self, account: Any) -> ConfigFlowResult:
        """Create the config entry of one property."""
        email = self._pending_input[CONF_EMAIL]
        account_id = str(account.account_id)
        await self.async_set_unique_id(unique_id_for(email, account_id))
        self._abort_if_unique_id_configured()
        if self._has_conflict(email, account_id):
            return self.async_abort(reason="already_configured")
        return self.async_create_entry(
            title=entry_title(email, getattr(account, "label", None)),
            data=self._entry_data(account),
        )

    # ------------------------------------------------------------------- steps

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
                if not self._accounts:
                    errors["base"] = "no_accounts"
                else:
                    self._pending_input = user_input
                    if len(self._accounts) == 1:
                        _LOGGER.info(
                            "Validation successful. One property found; creating "
                            "the config entry without an extra step."
                        )
                        return await self._async_create_account_entry(
                            self._accounts[0]
                        )
                    _LOGGER.info(
                        "Validation successful. Several properties found; asking "
                        "the user to select one."
                    )
                    return await self.async_step_select_account()

        suggested_values = dict(user_input or {})
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
                    vol.Required(
                        CONF_SEASON_START,
                        default=f"{date.today().year}-{DEFAULT_SEASON_START_MONTH:02d}-{DEFAULT_SEASON_START_DAY:02d}",
                    ): DateSelector(DateSelectorConfig()),
                }
            ),
            suggested_values=suggested_values,
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_select_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which portal property belongs to this entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            account = self._account_for(str(user_input[CONF_ACCOUNT_ID]))
            if account is None:
                errors["base"] = "account_not_found"
            elif self._reconfigure_entry is not None:
                return await self._async_update_reconfigure(
                    self._reconfigure_entry, account
                )
            else:
                return await self._async_create_account_entry(account)

        options = [
            {
                "value": str(account.account_id),
                "label": getattr(account, "label", None) or str(account.account_id),
            }
            for account in self._accounts
        ]
        return self.async_show_form(
            step_id="select_account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                CONF_EMAIL: self._pending_input.get(CONF_EMAIL, "")
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration (credentials, property, or start date)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        _LOGGER.debug(
            "Handling 'reconfigure' step for entry: %s. User input provided: %s",
            entry.entry_id,
            user_input is not None,
        )

        if user_input is not None:
            email_changed = (
                user_input[CONF_EMAIL].lower()
                != str(entry.data[CONF_EMAIL]).lower()
            )
            # The stored property belongs to the old login. A new email must be
            # validated without it, then choose one of its own properties.
            errors = await self._validate_user_input(
                user_input,
                account_id=None if email_changed else entry.data.get(CONF_ACCOUNT_ID),
            )
            if not errors:
                self._pending_input = user_input
                self._reconfigure_entry = entry
                if not self._accounts:
                    errors["base"] = "no_accounts"
                else:
                    account = self._resolve_existing_account(
                        entry, allow_stored=not email_changed
                    )
                    if account is not None:
                        return await self._async_update_reconfigure(entry, account)
                    if len(self._accounts) > 1:
                        # Several properties: let the user select the property
                        # of this entry.
                        return await self.async_step_select_account()
                    # The entry keeps a property that the account no longer
                    # lists, and the email did not change.
                    errors["base"] = "account_not_found"

        suggested_values = dict(
            user_input
            or {
                CONF_EMAIL: entry.data[CONF_EMAIL],
                CONF_OFFSET: entry.data.get(CONF_OFFSET, get_default_offset_date()),
                CONF_SEASON_START: entry.data.get(
                    CONF_SEASON_START,
                    f"{date.today().year}-{entry.data.get(CONF_SEASON_START_MONTH, DEFAULT_SEASON_START_MONTH):02d}-{entry.data.get(CONF_SEASON_START_DAY, DEFAULT_SEASON_START_DAY):02d}",
                ),
            }
        )
        _LOGGER.debug(
            "Showing reconfigure form with suggested values: %s", suggested_values
        )

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
                    vol.Required(CONF_SEASON_START): DateSelector(DateSelectorConfig()),
                }
            ),
            suggested_values=suggested_values,
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
        )

    async def _async_update_reconfigure(
        self, entry: ConfigEntry, account: Any
    ) -> ConfigFlowResult:
        """Store the new identity of a reconfigured entry."""
        email = self._pending_input[CONF_EMAIL]
        account_id = str(account.account_id)
        if self._has_conflict(email, account_id, ignore_entry_id=entry.entry_id):
            return self.async_abort(reason="already_configured")
        _LOGGER.info(
            "Reconfiguration validated. Updating entry %s.",
            entry.entry_id,
        )
        # The account entities follow the new identity: stable ones move in
        # place, per-invoice entities of the old property are removed.
        old_namespace = entry.unique_id or entry.data.get(CONF_EMAIL, "").lower()
        new_namespace = unique_id_for(email, account_id)
        if old_namespace != new_namespace:
            await async_migrate_account_entities(
                self.hass,
                entry,
                old_namespace,
                new_namespace,
                drop_old_bills=True,
            )
        return self.async_update_reload_and_abort(
            entry,
            title=entry_title(email, getattr(account, "label", None)),
            unique_id=unique_id_for(email, account_id),
            data_updates=self._entry_data(account),
            reason="reconfigure_successful",
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle initiation of re-authentication."""
        _LOGGER.debug("Handling 'reauth' step for entry.")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication confirmation (password step)."""
        entry = self._get_reauth_entry()
        email: str = entry.data[CONF_EMAIL]
        errors: dict[str, str] = {}
        _LOGGER.debug(
            "Handling 'reauth_confirm' for %s. User input provided: %s",
            email,
            user_input is not None,
        )

        if user_input is not None:
            password: str = user_input[CONF_PASSWORD]
            _LOGGER.debug("Validating new password for re-authentication.")
            # Do not force the stored property: it can be gone. Authenticate
            # first, then compare the stored property with the current list.
            errors = await self._validate_user_input(
                {CONF_EMAIL: email, CONF_PASSWORD: password}, account_id=None
            )

            if not errors:
                stored_id = entry.data.get(CONF_ACCOUNT_ID)
                if stored_id is not None and self._account_for(str(stored_id)) is None:
                    # The property is no longer linked: a password cannot repair
                    # that, so ask for a reconfigure instead of retrying forever.
                    _LOGGER.warning(
                        "The stored property of entry %s is no longer linked.",
                        entry.entry_id,
                    )
                    return self.async_abort(reason="reconfigure_required")
                if stored_id is None and len(self._accounts) > 1:
                    # A legacy entry with several properties cannot be resolved
                    # without a choice.
                    return self.async_abort(reason="reconfigure_required")
                _LOGGER.info("Re-authentication successful for %s.", email)
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: password},
                    reason="reauth_successful",
                )

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
                        min=MIN_UPDATE_INTERVAL_HOURS,
                        max=MAX_UPDATE_INTERVAL_HOURS,
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
                    )
                ),
                vol.Optional(
                    CONF_SEASON_START,
                    default=self.config_entry.options.get(
                        CONF_SEASON_START,
                        self.config_entry.data.get(
                            CONF_SEASON_START,
                            f"{date.today().year}-{self.config_entry.data.get(CONF_SEASON_START_MONTH, DEFAULT_SEASON_START_MONTH):02d}-{self.config_entry.data.get(CONF_SEASON_START_DAY, DEFAULT_SEASON_START_DAY):02d}",
                        ),
                    ),
                ): DateSelector(DateSelectorConfig()),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
