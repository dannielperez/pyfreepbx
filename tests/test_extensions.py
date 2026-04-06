"""Tests for ExtensionService."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

from pyfreepbx.exceptions import NotFoundError, NotSupportedError
from pyfreepbx.schemas.extension_create import ExtensionCreate
from pyfreepbx.schemas.extension_update import ExtensionUpdate
from pyfreepbx.services.extensions import ExtensionService


class TestExtensionService:
    def test_list_returns_extensions(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.fetch_all_extensions.return_value = [
            {"extension": "1001", "name": "Alice"},
            {"extension": "1002", "name": "Bob"},
        ]

        svc = ExtensionService(mock_freepbx_client)
        result = svc.list()

        assert len(result) == 2
        assert result[0].extension == "1001"
        assert result[0].name == "Alice"
        assert result[1].extension == "1002"

    def test_list_empty(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.fetch_all_extensions.return_value = []

        svc = ExtensionService(mock_freepbx_client)
        assert svc.list() == []

    def test_get_found(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.fetch_extension.return_value = {
            "extension": "1001", "name": "Alice",
        }

        svc = ExtensionService(mock_freepbx_client)
        ext = svc.get("1001")
        assert ext.extension == "1001"
        assert ext.name == "Alice"

    def test_get_not_found(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.fetch_extension.return_value = None

        svc = ExtensionService(mock_freepbx_client)
        with pytest.raises(NotFoundError):
            svc.get("9999")

    def test_create_raises_not_supported(self, mock_freepbx_client: MagicMock) -> None:
        svc = ExtensionService(mock_freepbx_client)
        payload = ExtensionCreate(extension="1050", name="New User")
        with pytest.raises(NotSupportedError):
            svc.create(payload)

    def test_update_raises_not_supported(self, mock_freepbx_client: MagicMock) -> None:
        svc = ExtensionService(mock_freepbx_client)
        payload = ExtensionUpdate(name="Updated Name")
        with pytest.raises(NotSupportedError):
            svc.update("1001", payload)

    def test_enable_raises_not_supported(self, mock_freepbx_client: MagicMock) -> None:
        svc = ExtensionService(mock_freepbx_client)
        with pytest.raises(NotSupportedError):
            svc.enable("1001")

    def test_disable_raises_not_supported(self, mock_freepbx_client: MagicMock) -> None:
        svc = ExtensionService(mock_freepbx_client)
        with pytest.raises(NotSupportedError):
            svc.disable("1001")


class TestExperimentalWarnings:
    def test_list_emits_graphql_warning(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.fetch_all_extensions.return_value = []

        svc = ExtensionService(mock_freepbx_client)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            svc.list()

        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
        assert len(user_warnings) >= 1
        assert "provisional" in str(user_warnings[0].message).lower()

    def test_get_emits_graphql_warning(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.fetch_extension.return_value = {
            "extension": "1001", "name": "Alice",
        }

        svc = ExtensionService(mock_freepbx_client)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            svc.get("1001")

        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
        assert len(user_warnings) >= 1
        assert "provisional" in str(user_warnings[0].message).lower()
