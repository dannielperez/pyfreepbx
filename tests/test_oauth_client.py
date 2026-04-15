"""Tests for OAuth2Client."""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from pyfreepbx.clients.oauth import OAuth2Client
from pyfreepbx.config import FreePBXConfig
from pyfreepbx.exceptions import AuthenticationError


@pytest.fixture
def oauth_config() -> FreePBXConfig:
    return FreePBXConfig(
        host="pbx.test",
        client_id="test-client",
        client_secret="test-secret",
        port=443,
        verify_ssl=False,
    )


@pytest.fixture
def client(oauth_config: FreePBXConfig) -> OAuth2Client:
    return OAuth2Client(oauth_config)


class TestOAuth2Client:
    def test_token_url(self, client: OAuth2Client) -> None:
        assert client.token_url == "https://pbx.test:443/admin/api/api/token"

    @respx.mock
    def test_get_token_success(self, client: OAuth2Client) -> None:
        respx.post("https://pbx.test:443/admin/api/api/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok-123", "expires_in": 3600},
            )
        )
        token = client.get_token()
        assert token == "tok-123"

    @respx.mock
    def test_get_token_cached(self, client: OAuth2Client) -> None:
        route = respx.post("https://pbx.test:443/admin/api/api/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok-cached", "expires_in": 3600},
            )
        )
        assert client.get_token() == "tok-cached"
        assert client.get_token() == "tok-cached"
        assert route.call_count == 1  # only one HTTP call

    @respx.mock
    def test_get_token_401(self, client: OAuth2Client) -> None:
        respx.post("https://pbx.test:443/admin/api/api/token").mock(
            return_value=httpx.Response(
                401,
                json={"error": "invalid_client"},
            )
        )
        with pytest.raises(AuthenticationError, match="invalid_client"):
            client.get_token()

    @respx.mock
    def test_get_token_400_with_description(self, client: OAuth2Client) -> None:
        respx.post("https://pbx.test:443/admin/api/api/token").mock(
            return_value=httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "Bad creds"},
            )
        )
        with pytest.raises(AuthenticationError, match="Bad creds"):
            client.get_token()

    @respx.mock
    def test_invalidate_forces_refetch(self, client: OAuth2Client) -> None:
        route = respx.post("https://pbx.test:443/admin/api/api/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok-1", "expires_in": 3600},
            )
        )
        assert client.get_token() == "tok-1"
        client.invalidate()
        assert client.get_token() == "tok-1"
        assert route.call_count == 2

    @respx.mock
    def test_token_refresh_on_expiry(self, client: OAuth2Client, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        def fake_monotonic() -> float:
            # First call (during _fetch_token): returns 0
            # Subsequent: returns a time past expiry
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return 0.0
            return 99999.0

        respx.post("https://pbx.test:443/admin/api/api/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok-refreshed", "expires_in": 60},
            )
        )
        monkeypatch.setattr(time, "monotonic", fake_monotonic)
        client.get_token()  # first fetch
        client.get_token()  # should re-fetch because "expired"
