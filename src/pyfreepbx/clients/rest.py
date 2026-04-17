"""REST API client for FreePBX.

Provides typed HTTP methods (GET, POST, PUT, DELETE) against the FreePBX
REST endpoint (``/rest``). Authentication is handled via OAuth2 tokens
from :class:`~pyfreepbx.clients.oauth.OAuth2Client`, or a static Bearer
token when OAuth2 credentials are not configured.

Usage::

    from pyfreepbx.config import FreePBXConfig
    from pyfreepbx.clients.rest import RestClient

    config = FreePBXConfig(host="pbx.example.com", client_id="...", client_secret="...")
    rest = RestClient(config)
    extensions = rest.get("/rest/extensions")
"""

from __future__ import annotations

from typing import Any

import httpx

from pyfreepbx.clients.base import BaseClient
from pyfreepbx.config import FreePBXConfig
from pyfreepbx.exceptions import (
    AuthenticationError,
    FreePBXConflictError,
    FreePBXTransportError,
    FreePBXValidationError,
    NotFoundError,
)
from pyfreepbx.logging import get_logger

log = get_logger("clients.rest")


class RestClient(BaseClient):
    """HTTP client for the FreePBX REST API.

    Handles authentication (OAuth2 or static token), base URL construction,
    and standard error mapping. The caller provides paths relative to the
    API base (e.g. ``"/extensions"``), and this client prepends the full
    REST URL.
    """

    def __init__(self, config: FreePBXConfig, *, token_provider: Any = None) -> None:
        """
        Args:
            config: FreePBX connection settings.
            token_provider: An object with a ``get_token() -> str`` method
                (typically :class:`~pyfreepbx.clients.oauth.OAuth2Client`).
                When not provided, falls back to ``config.api_token``.
        """
        self._config = config
        self._token_provider = token_provider
        self._http = httpx.Client(
            verify=config.verify_ssl,
            timeout=config.timeout,
        )

    @property
    def rest_url(self) -> str:
        return f"{self._config.base_url}{self._config.api_base_path}/rest"

    def _auth_headers(self) -> dict[str, str]:
        if self._token_provider is not None:
            token = self._token_provider.get_token()
        elif self._config.api_token:
            token = self._config.api_token
        else:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def _url(self, path: str) -> str:
        """Build full URL from a path relative to the REST root."""
        path = path.lstrip("/")
        return f"{self.rest_url}/{path}"

    def _handle_response(self, response: httpx.Response) -> Any:
        if response.status_code in (401, 403):
            log.warning("REST authentication failed: HTTP %d", response.status_code)
            raise AuthenticationError(f"REST API authentication failed: HTTP {response.status_code}")
        if response.status_code == 404:
            raise NotFoundError(f"REST resource not found: {response.url}")
        if response.status_code == 409:
            raise FreePBXConflictError(f"Resource conflict: {response.url}")
        if response.status_code == 422:
            details = None
            if response.headers.get("content-type", "").startswith("application/json"):
                details = response.json()
            raise FreePBXValidationError(
                f"Validation failed: {response.url}",
                details=details,
            )
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text

    # ------------------------------------------------------------------
    # HTTP methods
    # ------------------------------------------------------------------

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """Send a GET request to the REST API."""
        log.debug("REST GET %s", path)
        try:
            response = self._http.get(self._url(path), params=params, headers=self._auth_headers())
        except httpx.TransportError as exc:
            raise FreePBXTransportError(f"Transport error on GET {path}: {exc}") from exc
        return self._handle_response(response)

    def post(self, path: str, *, json: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> Any:
        """Send a POST request to the REST API."""
        log.debug("REST POST %s", path)
        try:
            response = self._http.post(self._url(path), json=json, data=data, headers=self._auth_headers())
        except httpx.TransportError as exc:
            raise FreePBXTransportError(f"Transport error on POST {path}: {exc}") from exc
        return self._handle_response(response)

    def put(self, path: str, *, json: dict[str, Any] | None = None) -> Any:
        """Send a PUT request to the REST API."""
        log.debug("REST PUT %s", path)
        try:
            response = self._http.put(self._url(path), json=json, headers=self._auth_headers())
        except httpx.TransportError as exc:
            raise FreePBXTransportError(f"Transport error on PUT {path}: {exc}") from exc
        return self._handle_response(response)

    def delete(self, path: str) -> Any:
        """Send a DELETE request to the REST API."""
        log.debug("REST DELETE %s", path)
        try:
            response = self._http.delete(self._url(path), headers=self._auth_headers())
        except httpx.TransportError as exc:
            raise FreePBXTransportError(f"Transport error on DELETE {path}: {exc}") from exc
        return self._handle_response(response)

    def close(self) -> None:
        self._http.close()
        log.debug("REST client closed")
