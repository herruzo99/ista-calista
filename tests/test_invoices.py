"""Invoice coverage tests: pagination, merge, sorting and bill entities.

The portal serves the invoice list as pages of 15 rows. The library follows all
pages; this integration must then keep every invoice, including the older IDs,
and must not crash on rows with missing values.
"""

import copy
from datetime import date
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pycalista_ista import Invoice
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista.const import (
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_LABEL,
    DOMAIN,
)

from .const import MOCK_ACCOUNT, MOCK_CONFIG, MOCK_DEVICES

NAMESPACE = f"{MOCK_CONFIG['email']}:{MOCK_ACCOUNT.account_id}"


def _entry() -> MockConfigEntry:
    """Return the config entry of the test property."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=NAMESPACE,
        data={
            **MOCK_CONFIG,
            CONF_ACCOUNT_ID: MOCK_ACCOUNT.account_id,
            CONF_ACCOUNT_LABEL: MOCK_ACCOUNT.label,
        },
    )


def _paged_invoices(count: int) -> list[Invoice]:
    """Return ``count`` invoices with an ID, as several pages give them."""
    invoices = []
    for index in range(count):
        month = 1 + index % 12
        year = 2020 + index // 12
        invoices.append(
            Invoice(
                invoice_id=f"HTM-{index:03d}",
                invoice_number=f"{4000000 + index}/24",
                invoice_date=date(year, month, 1),
                period_start=date(year, month, 1),
                period_end=date(year, month, 28),
                amount=float(10 + index),
                device_type="heating",
            )
        )
    return invoices


async def test_all_pages_are_kept(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """18 invoices (more than one page of 15) are all available to Home Assistant."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    # The library follows the pages and returns the merged list.
    mock_pycalista.get_invoices.return_value = _paged_invoices(18)
    mock_pycalista.get_invoice_xls.return_value = []

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    invoice_ids = {invoice.invoice_id for invoice in coordinator.data["invoices"]}
    assert len(invoice_ids) == 18
    # An invoice that only the last page holds is present too.
    assert "HTM-017" in invoice_ids

    # Every invoice with an identity becomes a bill entity.
    registry = er.async_get(hass)
    bill_entities = [
        item
        for item in registry.entities.values()
        if item.config_entry_id == entry.entry_id
        and item.unique_id.startswith(f"{NAMESPACE}_bill_")
        and not item.unique_id.startswith(f"{NAMESPACE}_bill_name_")
    ]
    assert len(bill_entities) == 18

    response = await hass.services.async_call(
        DOMAIN, "get_invoices", {}, blocking=True, return_response=True
    )
    returned_ids = {invoice["invoice_id"] for invoice in response["invoices"]}
    assert returned_ids == invoice_ids


async def test_invoice_merge_handles_missing_amount_and_type(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """A row without an amount or a device type does not break the merge."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    # The XLS history has no ID and no amount; the list has the same row with an
    # ID. Rows with None must not be compared with arithmetic.
    xls_row = Invoice(
        invoice_id=None,
        invoice_number=None,
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=None,
        device_type=None,
    )
    listed_row = Invoice(
        invoice_id="HTM-NO-AMOUNT",
        invoice_number=None,
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=None,
        device_type=None,
    )
    mock_pycalista.get_invoice_xls.return_value = [xls_row]
    mock_pycalista.get_invoices.return_value = [listed_row]

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state.name == "LOADED"
    invoices = hass.data[DOMAIN][entry.entry_id].data["invoices"]
    assert len(invoices) == 1
    # The ID of the invoice list is merged into the XLS row.
    assert invoices[0].invoice_id == "HTM-NO-AMOUNT"
    assert invoices[0].amount is None


async def test_invoices_are_sorted_newest_first_and_none_last(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Merged invoices come newest first, and undated invoices come last."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    undated = Invoice(
        invoice_id=None,
        invoice_number="OLD-NO-DATE",
        invoice_date=None,
        period_start=None,
        period_end=None,
        amount=1.0,
        device_type="heating",
    )
    april = Invoice(
        invoice_id="HTM-APR",
        invoice_number="A/24",
        invoice_date=date(2024, 4, 1),
        period_start=date(2024, 2, 1),
        period_end=date(2024, 4, 1),
        amount=30.0,
        device_type="heating",
    )
    february = Invoice(
        invoice_id="HTM-FEB",
        invoice_number="F/24",
        invoice_date=date(2024, 2, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 2, 1),
        amount=20.0,
        device_type="heating",
    )
    mock_pycalista.get_invoice_xls.return_value = [february, undated, april]
    mock_pycalista.get_invoices.return_value = []

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    invoices = hass.data[DOMAIN][entry.entry_id].data["invoices"]
    assert [invoice.invoice_id for invoice in invoices] == ["HTM-APR", "HTM-FEB", None]
    assert invoices[-1].invoice_date is None


async def test_bill_sensor_without_device_type(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """An invoice without a device type still creates a bill entity."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    row = Invoice(
        invoice_id="HTM-NO-TYPE",
        invoice_number="X/24",
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=12.5,
        device_type=None,
    )
    mock_pycalista.get_invoice_xls.return_value = [row]
    mock_pycalista.get_invoices.return_value = []

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state.name == "LOADED"
    registry = er.async_get(hass)
    unique_id = f"{NAMESPACE}_bill_X/24_unknown"
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "12.5"


async def test_invoice_with_id_but_without_number_has_no_bill_entity(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """A paged HTML invoice without a number must not create a numbered bill."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    row = Invoice(
        invoice_id="HTM-ONLY-ID",
        invoice_number=None,
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=7.5,
        device_type="heating",
    )
    mock_pycalista.get_invoice_xls.return_value = []
    mock_pycalista.get_invoices.return_value = [row]

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{NAMESPACE}_bill_HTM-ONLY-ID_heating"
    )
    assert entity_id is None


async def test_invoice_failures_are_not_fatal(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """A failing invoice endpoint only drops the invoices."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    mock_pycalista.get_invoices = AsyncMock(side_effect=RuntimeError("HTML failed"))
    mock_pycalista.get_invoice_xls = AsyncMock(side_effect=RuntimeError("XLS failed"))

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state.name == "LOADED"
    assert hass.data[DOMAIN][entry.entry_id].data["invoices"] == []


async def test_get_invoices_deduplicates_by_invoice_id(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Two rows with the same invoice ID give one service entry."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    first = _paged_invoices(1)[0]
    # Same ID, other amount: the coordinator keeps both rows, the service does not.
    from dataclasses import replace

    duplicate = replace(first, amount=99.0)
    mock_pycalista.get_invoice_xls.return_value = [first]
    mock_pycalista.get_invoices.return_value = []

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.data["invoices"] = [first, duplicate]

    response = await hass.services.async_call(
        DOMAIN, "get_invoices", {}, blocking=True, return_response=True
    )
    assert len(response["invoices"]) == 1
    assert response["invoices"][0]["invoice_id"] == first.invoice_id


def _same_shape_rows(count: int, with_id: bool) -> list[Invoice]:
    """Return ``count`` rows of the live 63-row shape.

    Rows differ by date; the HTML rows are the same invoices as the XLS rows,
    but they carry the opaque invoice ID.
    """
    rows = []
    for index in range(count):
        year = 2020 + index // 12
        month = 1 + index % 12
        rows.append(
            Invoice(
                invoice_id=f"HTM-{index:03d}" if with_id else None,
                invoice_number=None,
                invoice_date=date(year, month, 1),
                period_start=date(year, month, 1),
                period_end=date(year, month, 28),
                amount=float(20 + index),
                device_type="heating",
            )
        )
    return rows


async def test_full_history_63_xls_and_63_html_rows(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """63 history rows and 63 detailed rows merge to 63 invoices with 63 IDs."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    xls_rows = _same_shape_rows(63, with_id=False)
    html_rows = _same_shape_rows(63, with_id=True)
    mock_pycalista.get_invoice_xls.return_value = list(xls_rows)
    mock_pycalista.get_invoices.return_value = list(html_rows)

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    invoices = hass.data[DOMAIN][entry.entry_id].data["invoices"]
    assert len(invoices) == 63
    invoice_ids = {invoice.invoice_id for invoice in invoices}
    assert invoice_ids == {row.invoice_id for row in html_rows}
    assert len(invoice_ids) == 63
    # The full history survives: every date of the XLS is still there.
    assert {invoice.invoice_date for invoice in invoices} == {
        row.invoice_date for row in xls_rows
    }


async def test_rows_with_the_same_values_keep_distinct_ids(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Two detailed rows with the same date, type and amount keep both IDs.

    The history holds one row of that shape. The first detailed row claims it;
    the second row is a distinct invoice and is kept as its own row. A history
    row that looks the same twice is a duplicate and is collapsed.
    """
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    history_row = Invoice(
        invoice_id=None,
        invoice_number=None,
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=40.0,
        device_type="heating",
    )
    first = Invoice(
        invoice_id="HTM-A",
        invoice_number=None,
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=40.0,
        device_type="heating",
    )
    second = Invoice(
        invoice_id="HTM-B",
        invoice_number=None,
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=40.0,
        device_type="heating",
    )
    mock_pycalista.get_invoice_xls.return_value = [history_row, copy.copy(history_row)]
    mock_pycalista.get_invoices.return_value = [first, second]

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    invoices = hass.data[DOMAIN][entry.entry_id].data["invoices"]
    # The two history rows are the same invoice; both detailed IDs survive.
    assert len(invoices) == 2
    assert {invoice.invoice_id for invoice in invoices} == {"HTM-A", "HTM-B"}


async def test_duplicate_detailed_row_is_ignored(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """The same detailed invoice twice is one invoice."""
    mock_pycalista.get_devices_history.return_value = copy.deepcopy(MOCK_DEVICES)
    row = Invoice(
        invoice_id="HTM-SAME",
        invoice_number="S/24",
        invoice_date=date(2024, 3, 1),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 1),
        amount=15.0,
        device_type="heating",
    )
    mock_pycalista.get_invoice_xls.return_value = []
    mock_pycalista.get_invoices.return_value = [row, copy.copy(row)]

    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    invoices = hass.data[DOMAIN][entry.entry_id].data["invoices"]
    assert len(invoices) == 1
    assert invoices[0].invoice_id == "HTM-SAME"
