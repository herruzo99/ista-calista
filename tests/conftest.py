"""Shared fixtures for the ista_calista tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .const import MOCK_ACCOUNT, RecordingSessionFactory


@pytest.fixture
def mock_pycalista():
    """Patch the PyCalistaIsta library in both __init__ and config_flow."""
    mock_instance = MagicMock()
    # Async methods of the library
    mock_instance.login = AsyncMock(return_value=True)
    mock_instance.list_accounts = AsyncMock(return_value=[MOCK_ACCOUNT])
    mock_instance.select_account = AsyncMock(return_value=None)
    mock_instance.get_devices_history = AsyncMock(return_value={})
    mock_instance.get_billed_consumption = AsyncMock(return_value=[])
    mock_instance.get_invoices = AsyncMock(return_value=[])
    mock_instance.get_invoice_xls = AsyncMock(return_value=[])
    mock_instance.get_invoice_pdf = AsyncMock(return_value=b"fake pdf content")
    mock_instance.close = AsyncMock()
    mock_instance.set_log_level = MagicMock()
    mock_class = MagicMock(return_value=mock_instance)

    session_factory = RecordingSessionFactory()
    # Expose the class mock and the sessions so tests can inspect them.
    mock_instance.client_class = mock_class
    mock_instance.session_factory = session_factory

    with (
        patch(
            "custom_components.ista_calista.PyCalistaIsta",
            new=mock_class,
        ),
        patch(
            "custom_components.ista_calista.config_flow.PyCalistaIsta",
            new=mock_class,
        ),
        patch(
            "custom_components.ista_calista.async_create_clientsession",
            new=session_factory,
        ),
        patch(
            "custom_components.ista_calista.config_flow.async_create_clientsession",
            new=session_factory,
        ),
    ):
        yield mock_instance
