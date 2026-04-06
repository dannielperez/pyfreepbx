"""Tests for FreePBXConfig and AMIConfig."""

from __future__ import annotations

import os

import pytest

from pyfreepbx.config import AMIConfig, FreePBXConfig


class TestFreePBXConfig:
    def test_base_url_https(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", api_token="tok", port=443)
        assert cfg.base_url == "https://pbx.local:443"

    def test_base_url_http(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", api_token="tok", port=8080)
        assert cfg.base_url == "http://pbx.local:8080"

    def test_graphql_url(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", api_token="tok")
        assert cfg.graphql_url.endswith("/admin/api/api/gql")

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FREEPBX_HOST", "env-host")
        monkeypatch.setenv("FREEPBX_API_TOKEN", "env-token")
        monkeypatch.setenv("FREEPBX_PORT", "8443")
        cfg = FreePBXConfig()  # type: ignore[call-arg]
        assert cfg.host == "env-host"
        assert cfg.api_token == "env-token"
        assert cfg.port == 8443


class TestAMIConfig:
    def test_defaults(self) -> None:
        cfg = AMIConfig(host="ami.local", username="admin", secret="pass")
        assert cfg.port == 5038
        assert cfg.timeout == 10.0
