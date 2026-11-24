"""Account (portal property) identity helpers for ista Calista.

One config entry represents exactly one portal property. These helpers build
the account device and the account-level unique-ID namespace from the entry,
so that two properties under the same email stay separate.

Nothing in this module logs an account ID or a property label.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_ACCOUNT_LABEL, DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

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


# Account-level entity unique IDs that follow an identity change.
STABLE_SUFFIXES: tuple[str, ...] = (
    "latest_invoice_amount",
    "last_billed_date",
    "connection_status",
    "refresh",
)
STABLE_PREFIXES: tuple[str, ...] = (
    "invoice_",
    "bill_name_",
    "billed_date_",
)


def migrated_unique_id(
    old_unique_id: str, old_prefix: str, new_prefix: str, legacy: bool
) -> str | None:
    """Return the unique ID in the new namespace, or None to keep it.

    ``legacy`` also maps the pre-0.10.0 shape: any ``<old prefix>_<key>`` and
    the un-prefixed ``bill_*`` / ``bill_name_*`` / ``billed_date_*`` IDs.
    """
    if not old_prefix or old_prefix == new_prefix:
        return None
    for prefix in STABLE_PREFIXES:
        if old_unique_id.startswith(f"{old_prefix}_{prefix}"):
            return f"{new_prefix}_{old_unique_id[len(old_prefix) + 1:]}"
    for suffix in STABLE_SUFFIXES:
        if old_unique_id == f"{old_prefix}_{suffix}":
            return f"{new_prefix}_{suffix}"
    if not legacy:
        return None
    for prefix in STABLE_PREFIXES:
        if old_unique_id.startswith(prefix):
            return f"{new_prefix}_{old_unique_id}"
    if old_unique_id.startswith("bill_") and not old_unique_id.startswith(
        "bill_name_"
    ):
        return f"{new_prefix}_{old_unique_id}"
    return None


async def async_migrate_account_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    old_prefix: str | None,
    new_prefix: str,
    drop_old_bills: bool = False,
) -> None:
    """Move account-level entity unique IDs into the property namespace.

    ``er.async_migrate_entries`` updates the registry entry in place, so the
    entity ID, the disabled state and the history stay. With
    ``drop_old_bills`` the per-invoice entities of the old namespace are
    removed: they belong to a property that the entry no longer reads. Meter
    entities keep their serial based unique IDs.
    """
    if not old_prefix or old_prefix == new_prefix:
        return

    registry = er.async_get(hass)
    if drop_old_bills:
        for entity_entry in list(
            er.async_entries_for_config_entry(registry, entry.entry_id)
        ):
            unique_id = entity_entry.unique_id
            if unique_id.startswith(f"{old_prefix}_bill_") and not unique_id.startswith(
                f"{old_prefix}_bill_name_"
            ):
                registry.async_remove(entity_entry.entity_id)

    @callback
    def _update(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
        new_unique_id = migrated_unique_id(
            entity_entry.unique_id, old_prefix, new_prefix, legacy=not drop_old_bills
        )
        if new_unique_id is None or new_unique_id == entity_entry.unique_id:
            return None
        existing = registry.async_get_entity_id(
            entity_entry.domain, entity_entry.platform, new_unique_id
        )
        if existing is not None and existing != entity_entry.entity_id:
            existing_entry = registry.async_get(existing)
            if (
                existing_entry is not None
                and existing_entry.config_entry_id == entry.entry_id
            ):
                # An intermediate build could create both shapes. Keep the
                # already-migrated entity and remove the stale duplicate.
                registry.async_remove(entity_entry.entity_id)
                return None
            _LOGGER.warning(
                "Cannot migrate entity %s: its new unique ID belongs to another "
                "config entry.",
                entity_entry.entity_id,
            )
            return None
        return {"new_unique_id": new_unique_id}

    await er.async_migrate_entries(hass, entry.entry_id, _update)
