"""Tests for RestClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
import respx

from pyfreepbx.clients.rest import RestClient
from pyfreepbx.config import FreePBXConfig
from pyfreepbx.exceptions import AuthenticationError, NotFoundError


@pytest.fixture
def config() -> FreePBXConfig:
    return FreePBXConfig(
        host="pbx.test",
        api_token="test-token",
        port=443,
        verify_ssl=False,
    )


@pytest.fixture
def oauth_config() -> FreePBXConfig:
    return FreePBXConfig(
        host="pbx.test",
        client_id="cid",
        client_secret="csecret",
        port=443,
        verify_ssl=False,
    )


@pytest.fixture
def client(config: FreePBXConfig) -> RestClient:
    return RestClient(config)


BASE = "https://pbx.test:443/admin/api/api/rest"


class TestRestClientURLs:
    def test_rest_url(self, client: RestClient) -> None:
        assert client.rest_url == BASE

    def test_url_construction(self, client: RestClient) -> None:
        assert client._url("extensions") == f"{BASE}/extensions"
        assert client._url("/extensions") == f"{BASE}/extensions"


class TestRestClientAuth:
    def test_static_token_header(self, config: FreePBXConfig) -> None:
        rest = RestClient(config)
        headers = rest._auth_headers()
        assert headers == {"Authorization": "Bearer test-token"}

    def test_oauth_token_provider(self, oauth_config: FreePBXConfig) -> None:
        provider = MagicMock()
        provider.get_token.return_value = "oauth-tok"
        rest = RestClient(oauth_config, token_provider=provider)
        headers = rest._auth_headers()
        assert headers == {"Authorization": "Bearer oauth-tok"}

    def test_no_auth(self) -> None:
        cfg = FreePBXConfig(host="pbx.test", port=443, verify_ssl=False)
        rest = RestClient(cfg)
        assert rest._auth_headers() == {}


class TestRestClientHTTP:
    @respx.mock
    def test_get_json(self, client: RestClient) -> None:
        respx.get(f"{BASE}/extensions").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        result = client.get("extensions")
        assert result == {"items": []}

    @respx.mock
    def test_get_with_params(self, client: RestClient) -> None:
        route = respx.get(f"{BASE}/extensions").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        client.get("extensions", params={"limit": "10"})
        assert route.calls[0].request.url.params["limit"] == "10"

    @respx.mock
    def test_post_json(self, client: RestClient) -> None:
        respx.post(f"{BASE}/extensions").mock(
            return_value=httpx.Response(201, json={"id": 1})
        )
        result = client.post("extensions", json={"name": "test"})
        assert result == {"id": 1}

    @respx.mock
    def test_put_json(self, client: RestClient) -> None:
        respx.put(f"{BASE}/extensions/1").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = client.put("extensions/1", json={"name": "updated"})
        assert result == {"ok": True}

    @respx.mock
    def test_delete(self, client: RestClient) -> None:
        respx.delete(f"{BASE}/extensions/1").mock(
            return_value=httpx.Response(200, json={"deleted": True})
        )
        result = client.delete("extensions/1")
        assert result == {"deleted": True}

    @respx.mock
    def test_401_raises_auth_error(self, client: RestClient) -> None:
        respx.get(f"{BASE}/secret").mock(
            return_value=httpx.Response(401)
        )
        with pytest.raises(AuthenticationError):
            client.get("secret")

    @respx.mock
    def test_403_raises_auth_error(self, client: RestClient) -> None:
        respx.get(f"{BASE}/forbidden").mock(
            return_value=httpx.Response(403)
        )
        with pytest.raises(AuthenticationError):
            client.get("forbidden")

    @respx.mock
    def test_404_raises_not_found(self, client: RestClient) -> None:
        respx.get(f"{BASE}/missing").mock(
            return_value=httpx.Response(404)
        )
        with pytest.raises(NotFoundError):
            client.get("missing")

    @respx.mock
    def test_text_response(self, client: RestClient) -> None:
        respx.get(f"{BASE}/status").mock(
            return_value=httpx.Response(
                200,
                text="OK",
                headers={"content-type": "text/plain"},
            )
        )
        result = client.get("status")
        assert result == "OK"
