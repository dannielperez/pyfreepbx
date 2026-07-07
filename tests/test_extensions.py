"""Tests for ExtensionService."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

from pyfreepbx.exceptions import NotFoundError
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

    def test_create_requires_rest_client(self, mock_freepbx_client: MagicMock) -> None:
        # write operations require a REST client; GraphQL-only construction cannot create
        svc = ExtensionService(mock_freepbx_client)
        payload = ExtensionCreate(extension="1050", name="New User")
        with pytest.raises(RuntimeError, match="REST client is required"):
            svc.create(payload)

    def test_update_requires_rest_client(self, mock_freepbx_client: MagicMock) -> None:
        svc = ExtensionService(mock_freepbx_client)
        payload = ExtensionUpdate(name="Updated Name")
        with pytest.raises(RuntimeError, match="REST client is required"):
            svc.update("1001", payload)


class TestExperimentalWarnings:
    def test_list_emits_no_warning(self, mock_freepbx_client: MagicMock) -> None:
        """list() is validated against a live FreePBX (2026-07) — the
        provisional-query warning must be gone."""
        mock_freepbx_client.fetch_all_extensions.return_value = []

        svc = ExtensionService(mock_freepbx_client)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            svc.list()

        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
        assert user_warnings == []

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
