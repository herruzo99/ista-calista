from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_pycalista():
    """Patch the PyCalistaIsta library in both __init__ and config_flow."""
    mock_instance = MagicMock()
    # Async methods of the library
    mock_instance.login = AsyncMock(return_value=True)
    mock_instance.get_devices_history = AsyncMock(return_value={})
    mock_instance.close = AsyncMock()
    mock_instance.set_log_level = MagicMock()
    mock_class = MagicMock(return_value=mock_instance)

    with (
        patch(
            "custom_components.ista_calista.PyCalistaIsta",
            new=mock_class,
        ),
        patch(
            "custom_components.ista_calista.config_flow.PyCalistaIsta",
            new=mock_class,
        ),
    ):
        yield mock_instance
