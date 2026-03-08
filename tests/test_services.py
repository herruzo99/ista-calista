"""Test the ista_calista services."""

from unittest.mock import AsyncMock, patch, mock_open
import os
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ista_calista.const import DOMAIN
from .const import MOCK_CONFIG, MOCK_DEVICES, MOCK_INVOICES

async def test_get_invoices_service(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Test the get_invoices service."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    mock_pycalista.get_invoice_xls.return_value = MOCK_INVOICES
    # Mocking get_invoices list with same data to test deduplication
    mock_pycalista.get_invoices.return_value = MOCK_INVOICES

    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Call service
    response = await hass.services.async_call(
        DOMAIN, "get_invoices", {}, blocking=True, return_response=True
    )

    assert response is not None
    assert "invoices" in response
    # MOCK_INVOICES has 1 entry. 1 XLS + 1 List = 1 unique invoice
    assert len(response["invoices"]) == 1
    assert response["invoices"][0]["invoice_number"] == "4448373/24"

async def test_download_invoice_service_success(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Test the download_invoice service success case."""
    # Ensure invoice has an ID for service to find it
    from pycalista_ista import Invoice
    from dataclasses import replace
    inv = replace(MOCK_INVOICES[0], invoice_id="INV001")
    
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    mock_pycalista.get_invoice_xls.return_value = [inv]
    mock_pycalista.get_invoice_pdf = AsyncMock(return_value=b"fake pdf content")

    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Call service
    with patch("homeassistant.core.Config.path", return_value="/tmp/www"), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open()):
        response = await hass.services.async_call(
            DOMAIN, 
            "download_invoice", 
            {"invoice_id": "INV001"}, 
            blocking=True, 
            return_response=True
        )

    assert response is not None
    assert response["success"] == "true"
    assert "ista_heating_20240301.pdf" in response["filename"]

async def test_download_invoice_not_found(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Test the download_invoice service with non-existent invoice."""
    mock_pycalista.get_devices_history.return_value = MOCK_DEVICES
    mock_pycalista.get_invoice_xls.return_value = []

    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError, match="not found in the local cache"):
        await hass.services.async_call(
            DOMAIN, 
            "download_invoice", 
            {"invoice_id": "UNKNOWN"}, 
            blocking=True, 
            return_response=True
        )

async def test_download_invoice_empty_data(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, mock_pycalista
):
    """Test the download_invoice service when coordinator has no data."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    
    # Manually clear data 
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.data = {}

    with pytest.raises(ServiceValidationError, match="not found in the local cache"):
        await hass.services.async_call(
            DOMAIN, 
            "download_invoice", 
            {"invoice_id": "INV001"}, 
            blocking=True, 
            return_response=True
        )
