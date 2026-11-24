"""The ista Calista integration."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterator
from functools import partial
from typing import TYPE_CHECKING, Any, Final

import aiohttp
import voluptuous as vol

from homeassistant.components.recorder import get_instance  # type: ignore[attr-defined]
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import slugify
from pycalista_ista import (
    IstaApiError,
    IstaConnectionError,
    IstaLoginError,
    PyCalistaIsta,
)

from .const import (
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_LABEL,
    CONF_LOG_LEVEL,
    DEFAULT_LOG_LEVEL,
    DOMAIN,
    LOG_LEVELS,
    PLATFORMS,
    SESSION_TIMEOUT,
)
from .account import async_migrate_account_entities
from .coordinator import IstaCoordinator

type IstaConfigEntry = ConfigEntry[IstaCoordinator]

_LOGGER = logging.getLogger(__name__)

# Maps device models from the device registry to their corresponding sensor key.
MODEL_TO_KEY_MAP: Final[dict[str, str]] = {
    "Cold Water Meter": "water",
    "Hot Water Meter": "hot_water",
    "Heating Meter": "heating",
}

# One private session per config entry. The library only closes sessions that it
# created itself, so this integration closes the session it creates.
SERVICE_DOWNLOAD_INVOICE: Final[str] = "download_invoice"
SERVICE_GET_INVOICES: Final[str] = "get_invoices"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

if TYPE_CHECKING:
    from pycalista_ista import Invoice


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ista Calista component."""
    hass.data.setdefault(DOMAIN, {})
    # Services are registered once for the domain, not once per config entry.
    _async_register_services(hass)
    return True


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the domain services exactly once."""
    if hass.services.has_service(DOMAIN, SERVICE_DOWNLOAD_INVOICE):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_INVOICE,
        partial(_async_handle_download_invoice, hass),
        schema=vol.Schema(
            {
                vol.Required("invoice_id"): cv.string,
                vol.Optional("entry_id"): cv.string,
                vol.Optional("account_id"): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_INVOICES,
        partial(_async_handle_get_invoices, hass),
        # A response is optional here: the pre-0.10.0 registration allowed both.
        supports_response=True,
    )


def _iter_coordinators(hass: HomeAssistant) -> Iterator[IstaCoordinator]:
    """Yield the coordinator of every loaded entry."""
    for value in list(hass.data.get(DOMAIN, {}).values()):
        if isinstance(value, IstaCoordinator):
            yield value


def _invoice_matches(
    hass: HomeAssistant, invoice_id: str
) -> list[tuple[IstaCoordinator, "Invoice"]]:
    """Return every loaded (entry, invoice) pair with this invoice ID.

    The invoice ID is opaque and property scoped; nothing proves it is unique
    across properties, so every match is kept.
    """
    matches: list[tuple[IstaCoordinator, "Invoice"]] = []
    for coordinator in _iter_coordinators(hass):
        data = coordinator.data or {}
        for invoice in data.get("invoices", []):
            if invoice.invoice_id == invoice_id:
                matches.append((coordinator, invoice))
    return matches


def _select_invoice(
    hass: HomeAssistant, call: ServiceCall
) -> tuple[IstaCoordinator, "Invoice"]:
    """Return the one entry and invoice that a download must use.

    ``invoice_id`` is required. ``entry_id`` (preferred) or ``account_id``
    select the property when the ID exists more than once. Without a selector
    an ambiguous ID is an error: this code never picks the first match.
    """
    invoice_id: str = call.data["invoice_id"]
    entry_id: str | None = call.data.get("entry_id")
    account_id: str | None = call.data.get("account_id")

    # Collapse to one row per property first: a coordinator can hold the same
    # invoice ID more than once (history and list rows), and that is not an
    # ambiguity between properties.
    by_entry: dict[str, tuple[IstaCoordinator, "Invoice"]] = {}
    for coordinator, invoice in _invoice_matches(hass, invoice_id):
        by_entry.setdefault(coordinator.config_entry.entry_id, (coordinator, invoice))
    matches = list(by_entry.values())

    if entry_id:
        matches = [
            (coordinator, invoice)
            for coordinator, invoice in matches
            if coordinator.config_entry.entry_id == entry_id
        ]
    if account_id:
        matches = [
            (coordinator, invoice)
            for coordinator, invoice in matches
            if str(coordinator.config_entry.data.get(CONF_ACCOUNT_ID)) == account_id
        ]

    if not matches:
        if entry_id or account_id:
            raise ServiceValidationError(
                f"Invoice with ID {invoice_id} not found for the selected "
                "property. Please run 'Get invoices' first."
            )
        raise ServiceValidationError(
            f"Invoice with ID {invoice_id} not found in the local cache. "
            "Please run 'Get invoices' first."
        )

    if len(matches) > 1:
        options = ", ".join(
            sorted(coordinator.config_entry.entry_id for coordinator, _ in matches)
        )
        raise ServiceValidationError(
            f"Invoice ID {invoice_id} exists for {len(matches)} properties. "
            f"Set entry_id to one of: {options}."
        )

    return matches[0]


def _safe_file_token(value: str | None, fallback: str) -> str:
    """Return a lower-case file-name token with no path separator.

    The portal value is not trusted: ``slugify`` drops every character that is
    not a letter, a digit or the separator, so ``/``, ``\\`` and ``..`` cannot
    change the path. An empty result falls back to a fixed token.
    """
    if not value:
        return fallback
    token = slugify(str(value), separator="_")
    if not token or "/" in token or "\\" in token or token.strip(".") == "":
        return fallback
    return token


def _filename_parts(invoice: "Invoice") -> tuple[str, str]:
    """Return the device type and the date text used in the file name."""
    date_str = (
        invoice.invoice_date.strftime("%Y%m%d")
        if invoice.invoice_date
        else "unknown_date"
    )
    device_type_str = _safe_file_token(invoice.device_type, "invoice")
    return device_type_str, date_str


def _properties_with_same_filename(
    hass: HomeAssistant, device_type_str: str, date_str: str
) -> set[str]:
    """Return the entries that hold an invoice with this file name pattern."""
    entry_ids: set[str] = set()
    for coordinator in _iter_coordinators(hass):
        for candidate in (coordinator.data or {}).get("invoices", []):
            if _filename_parts(candidate) == (device_type_str, date_str):
                entry_ids.add(coordinator.config_entry.entry_id)
                break
    return entry_ids


def _invoice_filename(
    hass: HomeAssistant, coordinator: IstaCoordinator, invoice: "Invoice"
) -> str:
    """Return a file name that another property cannot overwrite.

    The historical name has no property in it, so deep pagination makes two
    properties with the same device type and date share one file. One matching
    property keeps the old name; more than one adds a short entry token. The
    token is derived from the entry ID, so no property label or account ID is
    written to disk.
    """
    device_type_str, date_str = _filename_parts(invoice)
    suffix = ""
    if len(_properties_with_same_filename(hass, device_type_str, date_str)) > 1:
        suffix = "_" + hashlib.sha256(
            coordinator.config_entry.entry_id.encode("utf-8")
        ).hexdigest()[:8]
    name = f"ista_{device_type_str}_{date_str}{suffix}.pdf"
    # Belt and braces: the name must stay one file name below the www folder.
    if os.path.basename(name) != name or "/" in name or "\\" in name:
        return f"ista_invoice_{date_str}{suffix}.pdf"
    return name


def _invoice_identity(coordinator: IstaCoordinator) -> dict[str, Any]:
    """Return the entry identity fields added to service responses."""
    entry = coordinator.config_entry
    return {
        "entry_id": entry.entry_id,
        "account_id": entry.data.get(CONF_ACCOUNT_ID),
        "account_label": entry.data.get(CONF_ACCOUNT_LABEL),
        "email": entry.data.get(CONF_EMAIL),
    }


async def _async_handle_download_invoice(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, str | None]:
    """Download a specific invoice by ID."""
    invoice_id = call.data["invoice_id"]
    _LOGGER.debug("Service called: download_invoice")

    coordinator, invoice = _select_invoice(hass, call)

    try:
        content = await coordinator.ista.get_invoice_pdf(invoice_id)
    except (IstaApiError, IstaConnectionError) as err:
        raise ServiceValidationError(
            f"Failed to download invoice PDF for ID {invoice_id}: {err}"
        ) from err

    filename = _invoice_filename(hass, coordinator, invoice)

    base_path = hass.config.path("www")
    if not os.path.exists(base_path):
        await hass.async_add_executor_job(
            partial(os.makedirs, base_path, mode=0o777, exist_ok=True)
        )

    filepath = os.path.join(base_path, filename)

    def save_file() -> None:
        with open(filepath, "wb") as file_handle:
            file_handle.write(content)

    await hass.async_add_executor_job(save_file)
    _LOGGER.info("Saved invoice to %s", filepath)

    return {
        "success": "true",
        "filename": filename,
        "path": filepath,
        **_invoice_identity(coordinator),
    }


async def _async_handle_get_invoices(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, list[dict[str, Any]]]:
    """Return the invoices of all loaded entries."""
    _LOGGER.debug("Service called: get_invoices")

    seen: dict[Any, dict[str, Any]] = {}
    for coordinator in _iter_coordinators(hass):
        identity = _invoice_identity(coordinator)
        data = coordinator.data or {}
        for invoice in data.get("invoices", []):
            record: dict[str, Any] = {
                "invoice_id": invoice.invoice_id,
                "invoice_number": invoice.invoice_number,
                "device_type": invoice.device_type,
                "amount": invoice.amount,
                "date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                "period_start": (
                    invoice.period_start.isoformat() if invoice.period_start else None
                ),
                "period_end": (
                    invoice.period_end.isoformat() if invoice.period_end else None
                ),
                **identity,
            }
            # The same invoice ID can exist on two properties, so the key holds
            # the entry. Without an ID, keep the pre-0.10.0 fields in the key.
            key: Any = (
                ("id", identity["entry_id"], invoice.invoice_id)
                if invoice.invoice_id
                else (
                    "row",
                    identity["entry_id"],
                    invoice.invoice_number,
                    record["date"],
                    invoice.device_type,
                    invoice.amount,
                )
            )
            seen.setdefault(key, record)

    invoices_list = sorted(
        seen.values(), key=lambda item: item["date"] or "", reverse=True
    )
    _LOGGER.debug("Found %d invoices", len(invoices_list))
    return {"invoices": invoices_list}


async def async_setup_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Set up ista Calista from a config entry."""
    _LOGGER.debug("Setting up config entry: %s", entry.entry_id)
    hass.data.setdefault(DOMAIN, {})
    _async_register_services(hass)

    # A private session per entry: two properties must never share cookies.
    session = async_create_clientsession(hass, timeout=SESSION_TIMEOUT)
    try:
        ista = await _async_create_client(hass, entry, session)
        coordinator = IstaCoordinator(hass, entry, ista, session=session)
        entry.runtime_data = coordinator
        hass.data[DOMAIN][entry.entry_id] = coordinator

        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except (ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady):
        # Do not keep the private session or the coordinator of a failed entry.
        hass.data[DOMAIN].pop(entry.entry_id, None)
        session.detach()
        raise
    except Exception as err:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        session.detach()
        _LOGGER.exception("Unexpected error during ista Calista setup")
        raise ConfigEntryNotReady(
            f"Unexpected error during setup: {err}"
        ) from err

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.debug("Finished setting up config entry: %s", entry.entry_id)
    return True


def _async_apply_log_level(entry: IstaConfigEntry, client: PyCalistaIsta) -> None:
    """Apply the configured log level to the library and the integration."""
    log_level_str = entry.options.get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL).upper()
    if log_level_str not in LOG_LEVELS:
        _LOGGER.warning(
            "Invalid log level '%s' configured; defaulting to '%s'.",
            log_level_str,
            DEFAULT_LOG_LEVEL,
        )
        log_level_str = DEFAULT_LOG_LEVEL
    try:
        client.set_log_level(log_level_str)
        integration_logger = logging.getLogger(__name__.split(".")[0])
        level = logging.getLevelName(log_level_str)
        integration_logger.setLevel(level)
        _LOGGER.debug("Log level for '%s' set to %s", DOMAIN, log_level_str)
    except (ValueError, TypeError) as err:
        # This should not happen with the SelectSelector, but is a safeguard.
        _LOGGER.error("Failed to set log level: %s", err)


async def _async_login(client: PyCalistaIsta, entry: IstaConfigEntry) -> None:
    """Log in to the portal for one entry."""
    email = entry.data[CONF_EMAIL]
    try:
        _LOGGER.debug("Attempting to log in to Ista Calista API.")
        await client.login()
        _LOGGER.info("Successfully logged in for account %s", email)
    except IstaLoginError as err:
        _LOGGER.warning("Authentication failed for %s", email)
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="authentication_exception",
            translation_placeholders={CONF_EMAIL: email},
        ) from err
    except (IstaConnectionError, IstaApiError) as err:
        _LOGGER.error("Failed to connect to Ista Calista API: %s", err)
        raise ConfigEntryNotReady(
            f"Failed to connect to Ista Calista API: {err}"
        ) from err


async def _async_property_is_missing(
    entry: IstaConfigEntry, session: aiohttp.ClientSession
) -> bool:
    """Return True when the account no longer lists the stored property.

    A login without ``account_id`` is used, so the check is about the property
    list only. Any error here means "cannot classify", and the caller keeps the
    transient retry path.
    """
    account_id = entry.data.get(CONF_ACCOUNT_ID)
    if account_id is None:
        return False
    probe = PyCalistaIsta(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], session)
    try:
        await probe.login()
        accounts = list(await probe.list_accounts())
    except (IstaLoginError, IstaConnectionError, IstaApiError):
        return False
    finally:
        await probe.close()
    return str(account_id) not in {str(account.account_id) for account in accounts}


async def _async_create_client(
    hass: HomeAssistant, entry: IstaConfigEntry, session: aiohttp.ClientSession
) -> PyCalistaIsta:
    """Create and log in the client of one entry, resolving legacy entries."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    account_id = entry.data.get(CONF_ACCOUNT_ID)

    if account_id is not None:
        client = PyCalistaIsta(email, password, session, account_id=account_id)
        _async_apply_log_level(entry, client)
        try:
            await _async_login(client, entry)
        except ConfigEntryNotReady as err:
            # The login can fail because the stored property is no longer
            # linked. Check that before this becomes a permanent retry loop.
            if await _async_property_is_missing(entry, session):
                _LOGGER.warning(
                    "The stored property of entry %s is no longer linked to the "
                    "account. Reconfigure required.",
                    entry.entry_id,
                )
                raise ConfigEntryError(
                    "The property of this entry is no longer linked to the "
                    f"account {email}. Reconfigure the integration and select a "
                    "property."
                ) from err
            raise
        # Safe on every load: only old IDs are matched.
        await async_migrate_account_entities(hass, entry, email.lower(), entry.unique_id or entry.entry_id)
        return client

    # Legacy (pre-0.10.0) entry: resolve the property once, then keep it.
    client = PyCalistaIsta(email, password, session)
    _async_apply_log_level(entry, client)
    await _async_login(client, entry)

    try:
        accounts = list(await client.list_accounts())
    except (IstaLoginError, IstaConnectionError, IstaApiError) as err:
        raise ConfigEntryNotReady(
            f"Failed to read the properties of the account: {err}"
        ) from err

    if not accounts:
        raise ConfigEntryError(
            f"No property was found for {email}. Check the ista Calista portal "
            "account, then reconfigure the integration."
        )
    if len(accounts) > 1:
        _LOGGER.warning(
            "Account %s has several properties. Reconfigure required.", email
        )
        raise ConfigEntryError(
            f"The account {email} has several properties. Reconfigure the "
            "integration and select one property for this entry."
        )

    # Select the property explicitly: invoice IDs are session and property
    # specific, so the client must show the same property as the entry.
    try:
        await client.select_account(str(accounts[0].account_id))
    except IstaLoginError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="authentication_exception",
            translation_placeholders={CONF_EMAIL: email},
        ) from err
    except (IstaConnectionError, IstaApiError) as err:
        raise ConfigEntryNotReady(
            f"Failed to select the property of the account: {err}"
        ) from err

    old_unique_id = entry.unique_id or email.lower()
    _async_persist_account(hass, entry, accounts[0])
    await async_migrate_account_entities(
        hass, entry, old_unique_id, entry.unique_id or entry.entry_id
    )
    return client


def _async_persist_account(
    hass: HomeAssistant, entry: IstaConfigEntry, account: Any
) -> None:
    """Store the resolved property in a legacy entry."""
    email = entry.data[CONF_EMAIL]
    account_id = str(account.account_id)
    label = getattr(account, "label", None)
    unique_id = f"{email.lower()}:{account_id}"

    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry.entry_id and other.unique_id == unique_id:
            raise ConfigEntryError(
                "Another config entry already uses this property. Reconfigure "
                "this entry and select a different property."
            )

    data = {**entry.data, CONF_ACCOUNT_ID: account_id}
    if label:
        data[CONF_ACCOUNT_LABEL] = label
    title = f"{email} \u2014 {label}" if label else email

    hass.config_entries.async_update_entry(
        entry, data=data, unique_id=unique_id, title=title
    )
    _LOGGER.info("Resolved the property of legacy entry %s", entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate an old config entry to the current version.

    Version 1 entries hold no property (`account_id`). The migration itself is
    offline and only bumps the version: the property is resolved during setup,
    where a portal login is available.
    """
    _LOGGER.debug(
        "Migrating config entry %s from version %s",
        config_entry.entry_id,
        config_entry.version,
    )
    if config_entry.version > 2:
        return False
    if config_entry.version == 1:
        hass.config_entries.async_update_entry(config_entry, version=2)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    _LOGGER.info("Reloading config entry %s due to options update.", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IstaConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading config entry: %s", entry.entry_id)
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = entry.runtime_data
        await coordinator.ista.close()
        if coordinator.session is not None:
            # A clientsession of async_create_clientsession must be detached,
            # not closed: its close() only reports usage. detach() is
            # idempotent, so the detach that Home Assistant registered on entry
            # unload is safe too. Never touch a session that HA owns.
            coordinator.session.detach()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.info("Successfully unloaded config entry: %s", entry.entry_id)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of a config entry, including associated statistics."""
    _LOGGER.debug(
        "Starting removal process for config entry %s, including associated statistics.",
        entry.entry_id,
    )

    device_registry = dr.async_get(hass)
    devices_for_entry = dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    )

    if not devices_for_entry:
        _LOGGER.debug(
            "No devices found for config entry %s. No statistics to remove.",
            entry.entry_id,
        )
        return

    statistic_ids_to_clear: list[str] = []
    for device in devices_for_entry:
        if device.model is None:
            _LOGGER.warning(
                "Device %s has no model set. Statistics for this device may not be cleared.",
                device.id,
            )
            continue
        sensor_key = MODEL_TO_KEY_MAP.get(device.model)
        if not sensor_key:
            _LOGGER.warning(
                "Cannot map device model '%s' (Device ID: %s) to a sensor key. "
                "Statistics for this device may not be cleared.",
                device.model,
                device.id,
            )
            continue

        serial_number = next(
            (
                identifier
                for domain, identifier in device.identifiers
                if domain == DOMAIN
            ),
            None,
        )

        if not serial_number:
            _LOGGER.warning(
                "Could not find a serial number identifier for device %s. "
                "Statistics for this device may not be cleared.",
                device.id,
            )
            continue

        # We replace them with underscores to match the sensor's statistic_id generation.
        slug_serial_number = serial_number.replace("-", "_")
        sensor_unique_id = f"{slug_serial_number}_{sensor_key}"
        statistic_id = f"{DOMAIN}:{sensor_unique_id}"
        statistic_ids_to_clear.append(statistic_id)

    if statistic_ids_to_clear:
        _LOGGER.debug(
            "Identified %d statistic ID(s) to clear: %s",
            len(statistic_ids_to_clear),
            statistic_ids_to_clear,
        )
        recorder_instance = get_instance(hass)
        if recorder_instance:
            recorder_instance.async_clear_statistics(statistic_ids_to_clear)
            _LOGGER.info(
                "Successfully scheduled clearing of %d statistic(s) for config entry %s.",
                len(statistic_ids_to_clear),
                entry.entry_id,
            )
        else:
            _LOGGER.warning(
                "Recorder integration not available. Could not clear statistics for entry %s.",
                entry.entry_id,
            )


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: IstaConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Disallow manual removal of devices from the UI."""
    return False
