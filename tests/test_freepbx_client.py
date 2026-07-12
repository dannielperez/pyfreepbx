"""Tests for FreePBXClient payload extraction."""

from __future__ import annotations

import httpx
import pytest
import respx

from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.config import FreePBXConfig


@pytest.fixture
def config() -> FreePBXConfig:
    return FreePBXConfig(
        host="pbx.test",
        api_token="test-token",
        port=443,
        verify_ssl=False,
    )


class TestFetchAllExtensions:
    @respx.mock
    def test_parses_live_singular_extension_key(self, config: FreePBXConfig) -> None:
        """Live FreePBX (validated 2026-07) nests the list under the singular
        ``extension`` field of ``ExtensionConnection``."""
        respx.post(f"{config.graphql_url}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "fetchAllExtensions": {
                            "status": True,
                            "message": "Extension's found successfully",
                            "extension": [
                                {"user": {"extension": "100", "name": "Centro"}},
                                {"user": {"extension": "10001", "name": "Entrada"}},
                            ],
                        }
                    }
                },
            )
        )
        client = FreePBXClient(config)
        assert client.fetch_all_extensions() == [
            {"extension": "100", "name": "Centro"},
            {"extension": "10001", "name": "Entrada"},
        ]

    @respx.mock
    def test_parses_legacy_plural_extensions_key(self, config: FreePBXConfig) -> None:
        """The pre-validation plural key is still accepted as a fallback."""
        respx.post(f"{config.graphql_url}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "fetchAllExtensions": {
                            "extensions": [
                                {"user": {"extension": "200", "name": "Legacy"}},
                            ],
                        }
                    }
                },
            )
        )
        client = FreePBXClient(config)
        assert client.fetch_all_extensions() == [{"extension": "200", "name": "Legacy"}]

    @respx.mock
    def test_empty_result(self, config: FreePBXConfig) -> None:
        respx.post(f"{config.graphql_url}").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"fetchAllExtensions": {"extension": []}}},
            )
        )
        client = FreePBXClient(config)
        assert client.fetch_all_extensions() == []


class TestFetchFirewallConfiguration:
    @respx.mock
    def test_parses_live_configuration_key(self, config: FreePBXConfig) -> None:
        configuration = {
            "status": True,
            "responsiveFirewall": True,
            "chainSip": True,
            "pjSip": True,
            "safemode": "disabled",
            "currentJiffies": "1000",
            "provision": ["external", "other"],
        }
        respx.post(config.graphql_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "fetchFirewallConfiguration": {
                            "status": True,
                            "message": "List of firewall configurations",
                            "configurations": [configuration],
                        }
                    }
                },
            )
        )

        client = FreePBXClient(config)
        assert client.fetch_firewall_configuration() == [configuration]

    @respx.mock
    def test_missing_configuration_is_not_silent_empty(self, config: FreePBXConfig) -> None:
        respx.post(config.graphql_url).mock(
            return_value=httpx.Response(
                200,
                json={"data": {"fetchFirewallConfiguration": {"status": False}}},
            )
        )

        client = FreePBXClient(config)
        with pytest.raises(ValueError, match="omitted firewall configurations"):
            client.fetch_firewall_configuration()
