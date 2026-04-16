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
        cfg = FreePBXConfig(host="pbx.local", api_token="tok", port=8080, scheme="http")
        assert cfg.base_url == "http://pbx.local:8080"

    def test_base_url_https_non_standard_port(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", api_token="tok", port=2443)
        assert cfg.base_url == "https://pbx.local:2443"

    def test_graphql_url(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", api_token="tok")
        assert cfg.graphql_url.endswith("/admin/api/api/gql")

    def test_rest_url(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", port=443)
        assert cfg.rest_url == "https://pbx.local:443/admin/api/api/rest"

    def test_token_url(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", port=443)
        assert cfg.token_url == "https://pbx.local:443/admin/api/api/token"

    def test_authorize_url(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", port=443)
        assert cfg.authorize_url == "https://pbx.local:443/admin/api/api/authorize"

    def test_has_oauth2_with_creds(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", client_id="cid", client_secret="cs")
        assert cfg.has_oauth2 is True

    def test_has_oauth2_without_creds(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", api_token="tok")
        assert cfg.has_oauth2 is False

    def test_custom_api_base_path(self) -> None:
        cfg = FreePBXConfig(host="pbx.local", port=2443, api_base_path="/custom/api")
        assert cfg.graphql_url == "https://pbx.local:2443/custom/api/gql"
        assert cfg.rest_url == "https://pbx.local:2443/custom/api/rest"
        assert cfg.token_url == "https://pbx.local:2443/custom/api/token"

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
