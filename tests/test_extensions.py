"""Tests for ExtensionService."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pyfreepbx.exceptions import (
    FreePBXConflictError,
    FreePBXTimeoutError,
    FreePBXValidationError,
    NotFoundError,
)
from pyfreepbx.models.inventory import InventoryListResult
from pyfreepbx.schemas.extension_create import ExtensionCreate
from pyfreepbx.schemas.extension_update import ExtensionUpdate
from pyfreepbx.services.extensions import ExtensionService

if TYPE_CHECKING:
    from unittest.mock import MagicMock


class TestExtensionService:
    def test_list_result_preserves_completeness(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.fetch_all_extensions_result.return_value = InventoryListResult(
            items=[{"extension": "1001", "name": "Alice"}],
            complete=False,
        )

        result = ExtensionService(mock_freepbx_client).list_result()

        assert [item.extension for item in result.items] == ["1001"]
        assert result.complete is False

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

    def test_get_secret_uses_sensitive_single_extension_read(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.fetch_extension_secret.return_value = "existing-secret"

        result = ExtensionService(mock_freepbx_client).get_secret("1001")

        assert result == "existing-secret"
        mock_freepbx_client.fetch_extension_secret.assert_called_once_with("1001")

    def test_create_uses_graphql_and_refetches(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.add_extension.return_value = {
            "status": True,
            "message": "created",
        }
        mock_freepbx_client.fetch_extension.side_effect = [
            None,
            {"extension": "1050", "name": "New User"},
        ]
        svc = ExtensionService(mock_freepbx_client)
        payload = ExtensionCreate(extension="1050", name="New User")
        result = svc.create(payload)

        assert result.extension == "1050"
        mock_freepbx_client.add_extension.assert_called_once_with(
            {
                "extensionId": "1050",
                "name": "New User",
                "tech": "pjsip",
                "channelName": "PJSIP/1050",
                "vmEnable": False,
                "email": "",
            }
        )

    def test_create_disables_userman_for_device_endpoint(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.add_extension.return_value = {"status": True}
        mock_freepbx_client.fetch_extension.side_effect = [
            None,
            {"extension": "116", "name": "Guardia 11"},
        ]

        ExtensionService(mock_freepbx_client).create(
            ExtensionCreate(
                extension="116",
                name="Guardia 11",
                user_management_enabled=False,
            )
        )

        create_input = mock_freepbx_client.add_extension.call_args.args[0]
        assert create_input["umEnable"] is False
        assert create_input["channelName"] == "PJSIP/116"

    @pytest.mark.parametrize("enabled", [False, True])
    def test_create_preserves_explicit_userman_choice(
        self,
        mock_freepbx_client: MagicMock,
        enabled: bool,
    ) -> None:
        mock_freepbx_client.add_extension.return_value = {"status": True}
        mock_freepbx_client.fetch_extension.side_effect = [
            None,
            {"extension": "1050", "name": "New User"},
        ]

        ExtensionService(mock_freepbx_client).create(
            ExtensionCreate(
                extension="1050",
                name="New User",
                user_management_enabled=enabled,
            )
        )

        create_input = mock_freepbx_client.add_extension.call_args.args[0]
        assert create_input["umEnable"] is enabled

    @pytest.mark.parametrize(
        ("tech", "expected_channel"),
        [("sip", "SIP/1050"), ("iax2", None)],
    )
    def test_create_adds_channel_identity_only_for_sip_technologies(
        self,
        mock_freepbx_client: MagicMock,
        tech: str,
        expected_channel: str | None,
    ) -> None:
        mock_freepbx_client.add_extension.return_value = {"status": True}
        mock_freepbx_client.fetch_extension.side_effect = [
            None,
            {"extension": "1050", "name": "Endpoint"},
        ]

        ExtensionService(mock_freepbx_client).create(
            ExtensionCreate(extension="1050", name="Endpoint", tech=tech)
        )

        create_input = mock_freepbx_client.add_extension.call_args.args[0]
        assert create_input.get("channelName") == expected_channel

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

    def test_create_sets_secret_through_supported_update_mutation(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.add_extension.return_value = {"status": True}
        mock_freepbx_client.update_extension.return_value = {"status": True}
        mock_freepbx_client.fetch_extension.side_effect = [
            None,
            {"extension": "1050", "name": "Visitor"},
        ]

        ExtensionService(mock_freepbx_client).create(
            ExtensionCreate(extension="1050", name="Visitor", secret="device-secret")
        )

        create_input = mock_freepbx_client.add_extension.call_args.args[0]
        assert "extPassword" not in create_input
        mock_freepbx_client.update_extension.assert_called_once_with(
            {
                "extensionId": "1050",
                "tech": "pjsip",
                "channelName": "PJSIP/1050",
                "name": "Visitor",
                "extPassword": "device-secret",
            }
        )

    def test_create_reconciles_ambiguous_add_timeout_without_replaying_write(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.add_extension.side_effect = FreePBXTimeoutError("response timed out")
        mock_freepbx_client.fetch_extension.side_effect = [
            None,
            {"extension": "1050", "name": "Guardia 11"},
        ]

        mock_freepbx_client.update_extension.return_value = {"status": True}

        result = ExtensionService(mock_freepbx_client).create(
            ExtensionCreate(
                extension="1050",
                name="Guardia 11",
                secret="device-secret",
            )
        )

        assert result.extension == "1050"
        mock_freepbx_client.add_extension.assert_called_once()
        assert mock_freepbx_client.fetch_extension.call_count == 2
        mock_freepbx_client.update_extension.assert_called_once()

    def test_create_propagates_add_timeout_when_readback_does_not_match(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        timeout = FreePBXTimeoutError("response timed out")
        mock_freepbx_client.add_extension.side_effect = timeout
        mock_freepbx_client.fetch_extension.side_effect = [
            None,
            {"extension": "1050", "name": "Existing endpoint"},
        ]

        with pytest.raises(FreePBXTimeoutError) as excinfo:
            ExtensionService(mock_freepbx_client).create(
                ExtensionCreate(extension="1050", name="Guardia 11")
            )

        assert excinfo.value is timeout
        mock_freepbx_client.add_extension.assert_called_once()

    def test_create_retries_only_final_readback_after_confirmed_write_timeout(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.add_extension.return_value = {"status": True}
        mock_freepbx_client.fetch_extension.side_effect = [
            None,
            FreePBXTimeoutError("first read timed out"),
            {"extension": "1050", "name": "Guardia 11"},
        ]

        result = ExtensionService(mock_freepbx_client).create(
            ExtensionCreate(extension="1050", name="Guardia 11")
        )

        assert result.extension == "1050"
        mock_freepbx_client.add_extension.assert_called_once()
        assert mock_freepbx_client.fetch_extension.call_count == 3

    def test_failed_create_is_not_reported_as_success(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.add_extension.return_value = {
            "status": False,
            "message": "Extension already exists",
        }
        mock_freepbx_client.fetch_extension.side_effect = [None, None]
        svc = ExtensionService(mock_freepbx_client)

        with pytest.raises(FreePBXValidationError, match="Extension already exists"):
            svc.create(ExtensionCreate(extension="1050", name="Duplicate"))
        assert mock_freepbx_client.fetch_extension.call_count == 2

    def test_create_reconciles_false_status_when_matching_extension_was_created(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.add_extension.return_value = {
            "status": False,
            "message": None,
        }
        mock_freepbx_client.fetch_extension.side_effect = [
            None,
            {"extension": "117", "name": "Guardia 11"},
        ]
        mock_freepbx_client.update_extension.return_value = {"status": True}

        result = ExtensionService(mock_freepbx_client).create(
            ExtensionCreate(
                extension="117",
                name="Guardia 11",
                secret="device-secret",
            )
        )

        assert result.extension == "117"
        mock_freepbx_client.add_extension.assert_called_once()
        mock_freepbx_client.update_extension.assert_called_once()

    def test_create_refuses_preexisting_extension_before_mutation(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.fetch_extension.return_value = {
            "extension": "117",
            "name": "Guardia 11",
        }

        with pytest.raises(FreePBXConflictError, match="already exists"):
            ExtensionService(mock_freepbx_client).create(
                ExtensionCreate(extension="117", name="Guardia 11")
            )

        mock_freepbx_client.add_extension.assert_not_called()

    def test_update_secret_uses_ext_password(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.update_extension.return_value = {
            "status": True,
            "message": "updated",
        }
        svc = ExtensionService(mock_freepbx_client)

        svc.update_secret("1001", "new-secret", name="Lobby")

        mock_freepbx_client.update_extension.assert_called_once_with(
            {
                "extensionId": "1001",
                "tech": "pjsip",
                "channelName": "PJSIP/1001",
                "name": "Lobby",
                "extPassword": "new-secret",
            }
        )

    def test_update_secret_verifies_when_mutation_status_is_null(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.update_extension.return_value = {
            "status": None,
            "message": None,
        }
        mock_freepbx_client.fetch_extension_secret.return_value = "new-secret"

        ExtensionService(mock_freepbx_client).update_secret("1001", "new-secret", name="Lobby")

        mock_freepbx_client.fetch_extension_secret.assert_called_once_with("1001")

    def test_update_secret_reconciles_ambiguous_timeout_without_replaying_write(
        self,
        mock_freepbx_client: MagicMock,
    ) -> None:
        mock_freepbx_client.update_extension.side_effect = FreePBXTimeoutError("response timed out")
        mock_freepbx_client.fetch_extension_secret.return_value = "new-secret"

        ExtensionService(mock_freepbx_client).update_secret("1001", "new-secret", name="Guardia 11")

        mock_freepbx_client.update_extension.assert_called_once()
        mock_freepbx_client.fetch_extension_secret.assert_called_once_with("1001")
