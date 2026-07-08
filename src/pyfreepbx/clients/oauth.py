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

import threading
import time

import httpx

from pyfreepbx.config import FreePBXConfig
from pyfreepbx.exceptions import AuthenticationError
from pyfreepbx.logging import get_logger

log = get_logger("clients.oauth")

# Refresh tokens 60 seconds before they actually expire
_EXPIRY_BUFFER_SECONDS = 60

# Process-wide token cache, shared across OAuth2Client instances.
#
# A common consumer pattern is a short-lived facade: build a FreePBX client,
# make one call, close it — repeated per resource in a loop. Because each
# facade owns its own OAuth2Client with an empty in-memory cache, that pattern
# re-mints a token on *every* request (client_credentials → bcrypt on the PBX),
# which is real, sustained CPU load on a small box. This cache lets a fresh
# instance reuse a still-valid token minted by a sibling instance.
#
# Keyed by (token_url, client_id) — the identity the token is scoped to. Values
# are (access_token, expires_at monotonic seconds). Guarded by a lock so the
# dict stays consistent under a threaded worker pool. Note: a rotated
# client_secret is not reflected until the cached token expires (≤ its lifetime)
# or ``invalidate()`` is called — acceptable for the token lifetimes in play.
_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_TOKEN_CACHE_LOCK = threading.Lock()


def clear_token_cache() -> None:
    """Drop all cached tokens (test isolation / forced global re-auth)."""
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.clear()


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

    @property
    def _cache_key(self) -> tuple[str, str]:
        return (self.token_url, self._config.client_id)

    def get_token(self) -> str:
        """Return a valid access token, refreshing if necessary.

        Checks this instance's token first, then the process-wide
        :data:`_TOKEN_CACHE` (so a freshly-built sibling instance reuses a
        still-valid token instead of re-minting), and only mints a new one
        when neither is live.

        Raises:
            AuthenticationError: If the token endpoint rejects the credentials.
        """
        # Fast path: this instance already holds a live token.
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token

        # Cross-instance cache: reuse a token a sibling instance minted.
        with _TOKEN_CACHE_LOCK:
            cached = _TOKEN_CACHE.get(self._cache_key)
            if cached is not None and time.monotonic() < cached[1]:
                self._access_token, self._expires_at = cached
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

        # Publish to the process-wide cache so sibling instances reuse it.
        with _TOKEN_CACHE_LOCK:
            _TOKEN_CACHE[self._cache_key] = (self._access_token, self._expires_at)

        log.debug("OAuth2 token acquired, expires in %ds", expires_in)
        return self._access_token

    def invalidate(self) -> None:
        """Force the next :meth:`get_token` call to fetch a fresh token."""
        self._access_token = ""
        self._expires_at = 0.0
        with _TOKEN_CACHE_LOCK:
            _TOKEN_CACHE.pop(self._cache_key, None)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()
