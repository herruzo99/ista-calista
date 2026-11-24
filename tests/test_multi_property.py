"""Tests for the experimental multi-property support.

One config entry must represent exactly one portal property. Two properties of
the same email must use private sessions, distinct identities and distinct
invoices. The portal of the test account holds one property only, so these
tests use two synthetic properties.
"""

import asyncio
import contextlib
import copy
import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pycalista_ista import Invoice
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista import async_migrate_entry
from custom_components.ista_calista.const import (
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_LABEL,
    DOMAIN,
)

from .const import (
    MOCK_ACCOUNT,
    MOCK_ACCOUNT_OTHER,
    MOCK_CONFIG,
    MOCK_DEVICES,
    SECOND_PROPERTY_DEVICES,
    RecordingSessionFactory,
)

PROPERTY_ONE = MOCK_ACCOUNT.account_id
PROPERTY_TWO = MOCK_ACCOUNT_OTHER.account_id
NAMESPACE_ONE = f"{MOCK_CONFIG[CONF_EMAIL]}:{PROPERTY_ONE}"
NAMESPACE_TWO = f"{MOCK_CONFIG[CONF_EMAIL]}:{PROPERTY_TWO}"


def _invoice(account_id: str, invoice_id: str, number: str, day: int) -> Invoice:
    """Return an invoice of one property."""
    return Invoice(
        invoice_id=invoice_id,
        invoice_number=number,
        invoice_date=date(2024, 3, day),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, day),
        amount=10.0 + day,
        device_type="heating",
    )


async def _setup_two_entries(
    hass: HomeAssistant, first: MockConfigEntry, second: MockConfigEntry
) -> None:
    """Set up the component, which sets up both entries at the same time.

    Home Assistant loads all entries of a domain concurrently when the
    component is set up, so this is the real concurrent-setup path.
    """
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


def _entry(account_id: str, label: str, unique_id: str) -> MockConfigEntry:
    """Return a version 2 config entry of one property."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=f"{MOCK_CONFIG[CONF_EMAIL]} \u2014 {label}",
        unique_id=unique_id,
        data={
            **MOCK_CONFIG,
            CONF_ACCOUNT_ID: account_id,
            CONF_ACCOUNT_LABEL: label,
        },
    )


@pytest.fixture
def two_properties():
    """Patch the library with one client and one session per property."""
    clients: dict[str, MagicMock] = {}
    sessions = RecordingSessionFactory()

    def _factory(
        email: str,
        password: str,
        session: object | None = None,
        account_id: str | None = None,
    ) -> MagicMock:
        client = MagicMock(name=f"client-{account_id}")
        client.login = AsyncMock(return_value=True)
        client.close = AsyncMock()
        client.set_log_level = MagicMock()
        client.list_accounts = AsyncMock(
            return_value=[MOCK_ACCOUNT, MOCK_ACCOUNT_OTHER]
        )
        client.select_account = AsyncMock(return_value=None)
        devices = (
            SECOND_PROPERTY_DEVICES
            if account_id == PROPERTY_TWO
            else MOCK_DEVICES
        )
        client.get_devices_history = AsyncMock(return_value=copy.deepcopy(devices))
        client.get_billed_consumption = AsyncMock(return_value=[])
        client.get_invoice_xls = AsyncMock(return_value=[])
        day = 2 if account_id == PROPERTY_TWO else 1
        client.invoices = [
            _invoice(account_id or "unknown", f"INV-{account_id}-1", f"9-{account_id}", day)
        ]
        client.get_invoices = AsyncMock(return_value=client.invoices)
        client.get_invoice_pdf = AsyncMock(return_value=b"fake pdf content")
        client.session = session
        client.account_id = account_id
        clients[account_id or "legacy"] = client
        return client

    client_class = MagicMock(side_effect=_factory)
    with (
        patch("custom_components.ista_calista.PyCalistaIsta", new=client_class),
        patch(
            "custom_components.ista_calista.config_flow.PyCalistaIsta", new=client_class
        ),
        patch(
            "custom_components.ista_calista.async_create_clientsession", new=sessions
        ),
        patch(
            "custom_components.ista_calista.config_flow.async_create_clientsession",
            new=sessions,
        ),
    ):
        yield clients, sessions, client_class


# --------------------------------------------------------------------- migration


async def test_migrate_entry_bumps_version_without_network(
    hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """A v1 entry is migrated offline and keeps its data."""
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=dict(MOCK_CONFIG))
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    migrated = hass.config_entries.async_get_entry(entry.entry_id)
    assert migrated is not None
    assert migrated.version == 2
    assert migrated.data == MOCK_CONFIG
    # No login and no session: the migration is offline.
    mock_pycalista.client_class.assert_not_called()
    assert mock_pycalista.session_factory.sessions == []


async def test_migrate_entry_refuses_newer_version(
    hass: HomeAssistant, enable_custom_integrations
):
    """A version newer than this integration cannot be migrated."""
    entry = MockConfigEntry(domain=DOMAIN, version=3, data=dict(MOCK_CONFIG))
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry) is False


# ------------------------------------------------------- legacy (v1) resolution


async def test_legacy_entry_resolves_its_only_property(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """A v1 entry with one property adopts that property during setup."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data=dict(MOCK_CONFIG),
        unique_id=MOCK_CONFIG[CONF_EMAIL],
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    resolved = hass.config_entries.async_get_entry(entry.entry_id)
    assert resolved is not None
    assert resolved.state is ConfigEntryState.LOADED
    assert resolved.version == 2
    assert resolved.data[CONF_ACCOUNT_ID] == PROPERTY_ONE
    assert resolved.data[CONF_ACCOUNT_LABEL] == MOCK_ACCOUNT.label
    assert resolved.unique_id == NAMESPACE_ONE
    assert resolved.title == f"{MOCK_CONFIG[CONF_EMAIL]} \u2014 {MOCK_ACCOUNT.label}"
    # The single property is selected explicitly in the client.
    mock_pycalista.select_account.assert_awaited_once_with(PROPERTY_ONE)


async def test_legacy_entry_with_two_properties_requires_reconfigure(
    recorder_mock,
    hass: HomeAssistant,
    caplog,
    enable_custom_integrations,
    mock_pycalista,
):
    """A v1 entry with several properties asks for a reconfigure."""
    mock_pycalista.list_accounts.return_value = [MOCK_ACCOUNT, MOCK_ACCOUNT_OTHER]
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, data=dict(MOCK_CONFIG), unique_id=MOCK_CONFIG[CONF_EMAIL]
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    failed = hass.config_entries.async_get_entry(entry.entry_id)
    assert failed is not None
    assert failed.state is ConfigEntryState.SETUP_ERROR
    assert CONF_ACCOUNT_ID not in failed.data
    assert "Reconfigure required" in caplog.text
    # The property is not selected silently.
    mock_pycalista.select_account.assert_not_called()


async def test_legacy_entry_without_property_fails(
    recorder_mock,
    hass: HomeAssistant,
    caplog,
    enable_custom_integrations,
    mock_pycalista,
):
    """An account without a property cannot be set up."""
    mock_pycalista.list_accounts.return_value = []
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, data=dict(MOCK_CONFIG), unique_id=MOCK_CONFIG[CONF_EMAIL]
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    failed = hass.config_entries.async_get_entry(entry.entry_id)
    assert failed is not None
    assert failed.state is ConfigEntryState.SETUP_ERROR
    assert "No property was found" in caplog.text


# ------------------------------------------------------------------- config flow


async def test_two_property_user_flow_creates_two_entries(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """The user adds one entry per property under the same email."""
    mock_pycalista.list_accounts.return_value = [MOCK_ACCOUNT, MOCK_ACCOUNT_OTHER]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_account"
    options = result["data_schema"].schema[next(iter(result["data_schema"].schema))]
    assert {option["value"] for option in options.config["options"]} == {
        PROPERTY_ONE,
        PROPERTY_TWO,
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_ACCOUNT_ID: PROPERTY_ONE}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    first = result["result"]
    assert first.unique_id == NAMESPACE_ONE
    assert first.data[CONF_ACCOUNT_ID] == PROPERTY_ONE
    assert first.data[CONF_ACCOUNT_LABEL] == MOCK_ACCOUNT.label

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_ACCOUNT_ID: PROPERTY_TWO}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    second = result["result"]
    assert second.unique_id == NAMESPACE_TWO
    assert second.data[CONF_ACCOUNT_ID] == PROPERTY_TWO

    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


async def test_user_flow_rejects_duplicate_property(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """The same email and property cannot be added twice."""
    mock_pycalista.list_accounts.return_value = [MOCK_ACCOUNT, MOCK_ACCOUNT_OTHER]
    _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_ACCOUNT_ID: PROPERTY_ONE}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_rejects_legacy_entry_of_same_email(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """A legacy entry of the same email may become any property, so it conflicts."""
    mock_pycalista.list_accounts.return_value = [MOCK_ACCOUNT, MOCK_ACCOUNT_OTHER]
    MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data=dict(MOCK_CONFIG),
        unique_id=MOCK_CONFIG[CONF_EMAIL],
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )
    assert result["step_id"] == "select_account"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_ACCOUNT_ID: PROPERTY_ONE}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_legacy_entry_selects_its_property(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Reconfiguring a legacy entry of a two-property account asks which one."""
    mock_pycalista.list_accounts.return_value = [MOCK_ACCOUNT, MOCK_ACCOUNT_OTHER]
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, data=dict(MOCK_CONFIG), unique_id=MOCK_CONFIG[CONF_EMAIL]
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_account"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_ACCOUNT_ID: PROPERTY_TWO}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated is not None
    assert updated.data[CONF_ACCOUNT_ID] == PROPERTY_TWO
    assert updated.unique_id == NAMESPACE_TWO


async def test_reauth_keeps_the_property(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Reauthentication uses the account ID of the entry."""
    entry = _entry(PROPERTY_TWO, MOCK_ACCOUNT_OTHER.label, NAMESPACE_TWO)
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PASSWORD: "new-password"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated is not None
    assert updated.data[CONF_PASSWORD] == "new-password"
    assert updated.data[CONF_ACCOUNT_ID] == PROPERTY_TWO
    assert mock_pycalista.client_class.call_args.kwargs["account_id"] == PROPERTY_TWO


# ---------------------------------------------------------- two loaded properties


async def test_two_entries_are_isolated(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, two_properties
):
    """Two entries of one email keep separate sessions, devices and invoices."""
    clients, sessions, _client_class = two_properties
    first = _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE)
    second = _entry(PROPERTY_TWO, MOCK_ACCOUNT_OTHER.label, NAMESPACE_TWO)
    first.add_to_hass(hass)
    second.add_to_hass(hass)

    await _setup_two_entries(hass, first, second)

    assert first.state is ConfigEntryState.LOADED
    assert second.state is ConfigEntryState.LOADED

    # One private session per entry, and each client got its own session.
    assert len(sessions.sessions) == 2
    assert sessions.sessions[0] is not sessions.sessions[1]
    assert clients[PROPERTY_ONE].session is sessions.sessions[0]
    assert clients[PROPERTY_TWO].session is sessions.sessions[1]
    assert clients[PROPERTY_ONE].account_id == PROPERTY_ONE
    assert clients[PROPERTY_TWO].account_id == PROPERTY_TWO

    # Distinct devices: two account devices and the meters of both properties.
    device_registry = dr.async_get(hass)
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, first.entry_id)})
        is not None
    )
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, second.entry_id)})
        is not None
    )
    for serial in SECOND_PROPERTY_DEVICES:
        assert device_registry.async_get_device(identifiers={(DOMAIN, serial)}) is not None

    # Distinct invoices: the coordinator of each entry holds only its own.
    assert [i.invoice_id for i in hass.data[DOMAIN][first.entry_id].data["invoices"]] == [
        f"INV-{PROPERTY_ONE}-1"
    ]
    assert [i.invoice_id for i in hass.data[DOMAIN][second.entry_id].data["invoices"]] == [
        f"INV-{PROPERTY_TWO}-1"
    ]


async def test_account_unique_ids_do_not_collide(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, two_properties
):
    """Account-level entities of two properties have different unique IDs."""
    first = _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE)
    second = _entry(PROPERTY_TWO, MOCK_ACCOUNT_OTHER.label, NAMESPACE_TWO)
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    await _setup_two_entries(hass, first, second)

    registry = er.async_get(hass)
    unique_ids = [
        entry.unique_id
        for entry in registry.entities.values()
        if entry.config_entry_id in (first.entry_id, second.entry_id)
    ]
    assert len(unique_ids) == len(set(unique_ids))
    for account_level in (
        "latest_invoice_amount",
        "bill_name_heating",
        "connection_status",
        "refresh",
    ):
        assert f"{NAMESPACE_ONE}_{account_level}" in unique_ids
        assert f"{NAMESPACE_TWO}_{account_level}" in unique_ids

    # Meter entities keep their serial based unique IDs (and their statistics).
    assert "heating-123_heating" in unique_ids
    assert "cold-water-999_water" in unique_ids


async def test_unload_one_entry_keeps_the_other(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, two_properties
):
    """Unloading one property closes only its own session."""
    clients, sessions, _client_class = two_properties
    first = _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE)
    second = _entry(PROPERTY_TWO, MOCK_ACCOUNT_OTHER.label, NAMESPACE_TWO)
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    await _setup_two_entries(hass, first, second)

    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    assert first.state is ConfigEntryState.NOT_LOADED
    assert second.state is ConfigEntryState.LOADED
    # The unloaded entry detaches its private session exactly once, and never
    # uses close(), which only reports usage on a Home Assistant clientsession.
    sessions.sessions[0].detach.assert_called_once_with()
    sessions.sessions[0].close.assert_not_called()
    sessions.sessions[1].detach.assert_not_called()
    assert first.entry_id not in hass.data[DOMAIN]
    assert second.entry_id in hass.data[DOMAIN]
    assert hass.data[DOMAIN][second.entry_id].last_update_success is True
    # Only the client that was unloaded is closed.
    assert clients[PROPERTY_ONE].close.await_count == 1
    assert clients[PROPERTY_TWO].close.await_count == 0

    # The entities of the remaining property are still there.
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{NAMESPACE_TWO}_latest_invoice_amount"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None


# ----------------------------------------------------------------------- services


async def test_services_are_registered_with_no_entry(
    hass: HomeAssistant, enable_custom_integrations
):
    """The services exist before any entry, and answer with an empty list."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "get_invoices")
    assert hass.services.has_service(DOMAIN, "download_invoice")
    response = await hass.services.async_call(
        DOMAIN, "get_invoices", {}, blocking=True, return_response=True
    )
    assert response == {"invoices": []}


async def test_services_registered_once_for_two_entries(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, two_properties
):
    """Two entries share one service registration."""
    first = _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE)
    second = _entry(PROPERTY_TWO, MOCK_ACCOUNT_OTHER.label, NAMESPACE_TWO)
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    await _setup_two_entries(hass, first, second)

    assert set(hass.services.async_services()[DOMAIN]) == {
        "get_invoices",
        "download_invoice",
    }

    response = await hass.services.async_call(
        DOMAIN, "get_invoices", {}, blocking=True, return_response=True
    )
    invoices = response["invoices"]
    assert len(invoices) == 2
    assert {invoice["account_id"] for invoice in invoices} == {
        PROPERTY_ONE,
        PROPERTY_TWO,
    }
    assert {invoice["entry_id"] for invoice in invoices} == {
        first.entry_id,
        second.entry_id,
    }
    assert {invoice["account_label"] for invoice in invoices} == {
        MOCK_ACCOUNT.label,
        MOCK_ACCOUNT_OTHER.label,
    }
    # Newest first: property two holds the more recent invoice.
    assert invoices[0]["invoice_id"] == f"INV-{PROPERTY_TWO}-1"


async def test_download_invoice_uses_the_owning_entry(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, two_properties
):
    """A download goes through the client that owns the invoice ID."""
    clients, _sessions, _client_class = two_properties
    first = _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE)
    second = _entry(PROPERTY_TWO, MOCK_ACCOUNT_OTHER.label, NAMESPACE_TWO)
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    await _setup_two_entries(hass, first, second)

    with (
        patch("homeassistant.core.Config.path", return_value="/tmp/www"),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open()),
    ):
        response = await hass.services.async_call(
            DOMAIN,
            "download_invoice",
            {"invoice_id": f"INV-{PROPERTY_TWO}-1"},
            blocking=True,
            return_response=True,
        )

    assert response["success"] == "true"
    assert response["account_id"] == PROPERTY_TWO
    assert response["entry_id"] == second.entry_id
    clients[PROPERTY_TWO].get_invoice_pdf.assert_awaited_once_with(
        f"INV-{PROPERTY_TWO}-1"
    )
    clients[PROPERTY_ONE].get_invoice_pdf.assert_not_called()


async def test_download_invoice_of_an_unloaded_property_fails(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, two_properties
):
    """An invoice of an unloaded entry is not in the cache."""
    first = _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE)
    second = _entry(PROPERTY_TWO, MOCK_ACCOUNT_OTHER.label, NAMESPACE_TWO)
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    await _setup_two_entries(hass, first, second)
    await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError, match="not found in the local cache"):
        await hass.services.async_call(
            DOMAIN,
            "download_invoice",
            {"invoice_id": f"INV-{PROPERTY_TWO}-1"},
            blocking=True,
            return_response=True,
        )


# ------------------------------------------------ config-flow session isolation


async def test_concurrent_flows_use_private_sessions(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Two flows of one email never share a cookie jar.

    Each validation attempt creates its own session, and each flow closes the
    session that it created.
    """
    # Two properties keep both flows on the select_account form, so no entry is
    # created and both validations run in the same event-loop step.
    mock_pycalista.list_accounts.return_value = [MOCK_ACCOUNT, MOCK_ACCOUNT_OTHER]
    flow_ids = []
    for _ in range(2):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        flow_ids.append(result["flow_id"])

    results = await asyncio.gather(
        *(
            hass.config_entries.flow.async_configure(
                flow_id, user_input=dict(MOCK_CONFIG)
            )
            for flow_id in flow_ids
        )
    )
    await hass.async_block_till_done()

    assert [result["step_id"] for result in results] == [
        "select_account",
        "select_account",
    ]
    sessions = mock_pycalista.session_factory.sessions
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    for session in sessions:
        session.detach.assert_called_once_with()
        session.close.assert_not_called()
    # Each client was built with its own private session.
    built_sessions = [
        call.args[2] for call in mock_pycalista.client_class.call_args_list
    ]
    assert built_sessions == sessions


# -------------------------------------------------- invoice file name isolation


async def test_download_filename_does_not_overwrite_other_property(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, two_properties
):
    """Two properties with the same device type and date get different files."""
    clients, _sessions, _client_class = two_properties
    first = _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE)
    second = _entry(PROPERTY_TWO, MOCK_ACCOUNT_OTHER.label, NAMESPACE_TWO)
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    await _setup_two_entries(hass, first, second)

    # Give both properties an invoice with the same device type and date.
    clients[PROPERTY_ONE].get_invoices.return_value = [
        _invoice(PROPERTY_ONE, f"INV-{PROPERTY_ONE}-1", "S-1", 1)
    ]
    clients[PROPERTY_TWO].get_invoices.return_value = [
        _invoice(PROPERTY_TWO, f"INV-{PROPERTY_TWO}-1", "S-2", 1)
    ]
    for entry in (first, second):
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()

    names = []
    with (
        patch("homeassistant.core.Config.path", return_value="/tmp/www"),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open()),
    ):
        for account_id in (PROPERTY_ONE, PROPERTY_TWO):
            response = await hass.services.async_call(
                DOMAIN,
                "download_invoice",
                {"invoice_id": f"INV-{account_id}-1"},
                blocking=True,
                return_response=True,
            )
            names.append(response["filename"])

    assert names[0] != names[1]
    # The old name is kept as the prefix, and the property token is appended.
    assert names[0].startswith("ista_heating_20240301")
    assert names[1].startswith("ista_heating_20240301")
    assert len({name for name in names}) == 2


async def test_download_filename_keeps_old_name_for_one_property(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, two_properties
):
    """A device type and date that only one property has keeps the old name."""
    clients, _sessions, _client_class = two_properties
    first = _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE)
    second = _entry(PROPERTY_TWO, MOCK_ACCOUNT_OTHER.label, NAMESPACE_TWO)
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    await _setup_two_entries(hass, first, second)

    clients[PROPERTY_ONE].get_invoices.return_value = [
        _invoice(PROPERTY_ONE, f"INV-{PROPERTY_ONE}-1", "S-1", 1)
    ]
    clients[PROPERTY_TWO].get_invoices.return_value = [
        _invoice(PROPERTY_TWO, f"INV-{PROPERTY_TWO}-1", "S-2", 9)
    ]
    for entry in (first, second):
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()

    with (
        patch("homeassistant.core.Config.path", return_value="/tmp/www"),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open()),
    ):
        response = await hass.services.async_call(
            DOMAIN,
            "download_invoice",
            {"invoice_id": f"INV-{PROPERTY_ONE}-1"},
            blocking=True,
            return_response=True,
        )

    assert response["filename"] == "ista_heating_20240301.pdf"


async def test_download_filename_cannot_escape_the_www_folder(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """A portal device type with path characters cannot change the saved path."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    unsafe = "a/b\\c"
    invoice = Invoice(
        invoice_id="HTM-UNSAFE",
        invoice_number="U/24",
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=11.0,
        device_type=unsafe,
    )
    escaped = Invoice(
        invoice_id="HTM-DOTS",
        invoice_number="D/24",
        invoice_date=date(2024, 4, 1),
        period_start=date(2024, 2, 1),
        period_end=date(2024, 4, 1),
        amount=12.0,
        device_type="../escape",
    )
    mock_pycalista.get_invoice_xls.return_value = []
    mock_pycalista.get_invoices.return_value = [invoice, escaped]

    entry = _entry(PROPERTY_ONE, MOCK_ACCOUNT.label, NAMESPACE_ONE)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    names = []
    with (
        patch("homeassistant.core.Config.path", return_value="/tmp/www"),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open()),
    ):
        for invoice_id in ("HTM-UNSAFE", "HTM-DOTS"):
            response = await hass.services.async_call(
                DOMAIN,
                "download_invoice",
                {"invoice_id": invoice_id},
                blocking=True,
                return_response=True,
            )
            names.append(response["filename"])

    for name in names:
        assert "/" not in name
        assert "\\" not in name
        assert os.path.basename(name) == name
        assert name.startswith("ista_")
        assert name.endswith(".pdf")
        assert ".." not in name
    assert names == ["ista_a_b_c_20240301.pdf", "ista_escape_20240401.pdf"]


async def test_real_clientsession_detach_is_the_supported_cleanup(
    hass: HomeAssistant, enable_custom_integrations
):
    """detach() closes a real Home Assistant clientsession, and close() does not.

    ``async_create_clientsession`` replaces ``close`` with a wrapper that only
    reports usage, so ``detach`` is the supported cleanup. Two sessions detach
    independently, and detach is idempotent.
    """
    import aiohttp

    from homeassistant.helpers.aiohttp_client import (
        async_create_clientsession as create_real_session,
    )

    first = create_real_session(hass, timeout=aiohttp.ClientTimeout(total=30))
    second = create_real_session(hass, timeout=aiohttp.ClientTimeout(total=30))

    assert first.closed is False
    assert second.closed is False
    assert first is not second

    # close() is replaced by a usage reporter on these sessions, so it does not
    # close anything. In a test Home Assistant may also raise from the reporter.
    with contextlib.suppress(Exception):
        await first.close()
    assert first.closed is False

    first.detach()
    assert first.closed is True
    # The other session is untouched.
    assert second.closed is False

    # detach is idempotent, so Home Assistant may detach again on unload.
    first.detach()
    second.detach()
    assert second.closed is True
