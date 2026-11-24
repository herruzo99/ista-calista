"""Account (portal property) identity helpers for ista Calista.

One config entry represents exactly one portal property. These helpers build
the account device and the account-level unique-ID namespace from the entry,
so that two properties under the same email stay separate.

Nothing in this module logs an account ID or a property label.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_ACCOUNT_LABEL, DOMAIN, MANUFACTURER

ACCOUNT_MODEL = "Ista Calista Account"
CONFIGURATION_URL = "https://oficina.ista.es/GesCon/MainPageAbo.do"


def account_label(entry: ConfigEntry) -> str | None:
    """Return the user-facing property label, when one is known."""
    label = entry.data.get(CONF_ACCOUNT_LABEL)
    return str(label) if label else None


def account_email(entry: ConfigEntry) -> str:
    """Return the account email of the entry."""
    return str(entry.data.get(CONF_EMAIL, ""))


def account_device_name(entry: ConfigEntry) -> str:
    """Return the name of the account device for this entry.

    The property label distinguishes the properties of one email. Without a
    label the email is used, which keeps the pre-0.10.0 names.
    """
    label = account_label(entry)
    if label:
        return f"Ista Account {label}"
    return f"Ista Account {account_email(entry)}"


def account_namespace(entry: ConfigEntry) -> str:
    """Return the stable prefix for account-level unique IDs.

    The entry unique ID is ``<email>:<account_id>`` once the property is known.
    The entry ID is the fallback, for example when a legacy entry is inspected
    before its setup resolves the account.
    """
    return entry.unique_id or entry.entry_id


def account_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the DeviceInfo of the account device of this entry."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=account_device_name(entry),
        manufacturer=MANUFACTURER,
        model=ACCOUNT_MODEL,
        configuration_url=CONFIGURATION_URL,
    )


def slug(value: str | None) -> str:
    """Return a lower-case, underscore separated token for an optional value."""
    if not value:
        return "unknown"
    return str(value).lower().replace(" ", "_")
