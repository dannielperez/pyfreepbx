"""OAuth2 client for FreePBX API token management.

Handles the client_credentials grant type against the FreePBX token
endpoint (``/token``). Tokens are cached and automatically refreshed
when they expire.

Usage::

    from pyfreepbx.config import FreePBXConfig
    from pyfreepbx.clients.oauth import OAuth2Client

    config = FreePBXConfig(host="pbx.example.com", client_id="...", client_secret="...")
    oauth = OAuth2Client(config)
    token = oauth.get_token()  # cached, auto-refreshes
"""

from __future__ import annotations

import time

import httpx

from pyfreepbx.config import FreePBXConfig
from pyfreepbx.exceptions import AuthenticationError
from pyfreepbx.logging import get_logger

log = get_logger("clients.oauth")

# Refresh tokens 60 seconds before they actually expire
_EXPIRY_BUFFER_SECONDS = 60


class OAuth2Client:
    """Manages OAuth2 client_credentials tokens for the FreePBX API.

    Tokens are fetched from the ``/token`` endpoint and cached in memory.
    Subsequent calls to :meth:`get_token` return the cached token unless
    it's within ``_EXPIRY_BUFFER_SECONDS`` of expiry, in which case a
    fresh token is obtained automatically.
    """

    def __init__(self, config: FreePBXConfig) -> None:
        self._config = config
        self._http = httpx.Client(
            verify=config.verify_ssl,
            timeout=config.timeout,
        )
        self._access_token: str = ""
        self._expires_at: float = 0.0

    @property
    def token_url(self) -> str:
        return f"{self._config.base_url}{self._config.api_base_path}/token"

    def get_token(self) -> str:
        """Return a valid access token, refreshing if necessary.

        Raises:
            AuthenticationError: If the token endpoint rejects the credentials.
        """
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token

        return self._fetch_token()

    def _fetch_token(self) -> str:
        """Request a new token via the client_credentials grant."""
        log.debug("Requesting OAuth2 token from %s", self.token_url)

        response = self._http.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
            },
        )

        if response.status_code in (400, 401, 403):
            body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = body.get("error_description") or body.get("error") or f"HTTP {response.status_code}"
            log.error("OAuth2 authentication failed: %s", error_msg)
            raise AuthenticationError(f"OAuth2 token request failed: {error_msg}")

        response.raise_for_status()
        body = response.json()

        self._access_token = body["access_token"]
        expires_in = int(body.get("expires_in", 3600))
        self._expires_at = time.monotonic() + expires_in - _EXPIRY_BUFFER_SECONDS

        log.debug("OAuth2 token acquired, expires in %ds", expires_in)
        return self._access_token

    def invalidate(self) -> None:
        """Force the next :meth:`get_token` call to fetch a fresh token."""
        self._access_token = ""
        self._expires_at = 0.0

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()
