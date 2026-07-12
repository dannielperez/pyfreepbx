"""Tests for ExtensionService."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pyfreepbx.exceptions import FreePBXValidationError, NotFoundError
from pyfreepbx.schemas.extension_create import ExtensionCreate
from pyfreepbx.schemas.extension_update import ExtensionUpdate
from pyfreepbx.services.extensions import ExtensionService

if TYPE_CHECKING:
    from unittest.mock import MagicMock


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
            "extension": "1001",
            "name": "Alice",
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

    def test_create_uses_graphql_and_refetches(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.add_extension.return_value = {
            "status": True,
            "message": "created",
        }
        mock_freepbx_client.fetch_extension.return_value = {
            "extension": "1050",
            "name": "New User",
        }
        svc = ExtensionService(mock_freepbx_client)
        payload = ExtensionCreate(extension="1050", name="New User")
        result = svc.create(payload)

        assert result.extension == "1050"
        mock_freepbx_client.add_extension.assert_called_once_with(
            {
                "extensionId": "1050",
                "name": "New User",
                "tech": "pjsip",
                "vmEnable": False,
            }
        )

    def test_update_uses_graphql_without_fabricated_result(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.update_extension.return_value = {
            "status": True,
            "message": "updated",
        }
        mock_freepbx_client.fetch_extension.return_value = {
            "extension": "1001",
            "name": "Updated Name",
        }
        svc = ExtensionService(mock_freepbx_client)
        payload = ExtensionUpdate(name="Updated Name")
        result = svc.update("1001", payload)

        assert result.name == "Updated Name"
        mock_freepbx_client.update_extension.assert_called_once_with(
            {"name": "Updated Name", "extensionId": "1001"}
        )

    def test_failed_create_is_not_reported_as_success(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.add_extension.return_value = {
            "status": False,
            "message": "Extension already exists",
        }
        svc = ExtensionService(mock_freepbx_client)

        with pytest.raises(FreePBXValidationError, match="Extension already exists"):
            svc.create(ExtensionCreate(extension="1050", name="Duplicate"))
        mock_freepbx_client.fetch_extension.assert_not_called()

    def test_update_secret_uses_ext_password(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.update_extension.return_value = {
            "status": True,
            "message": "updated",
        }
        svc = ExtensionService(mock_freepbx_client)

        svc.update_secret("1001", "new-secret")

        mock_freepbx_client.update_extension.assert_called_once_with(
            {"extensionId": "1001", "extPassword": "new-secret"}
        )
