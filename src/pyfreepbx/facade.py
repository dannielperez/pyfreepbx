"""FreePBX facade — main entry point for the library.

Usage:
    from pyfreepbx import FreePBX

    # From explicit args
    pbx = FreePBX(host="pbx.example.com", client_id="...", client_secret="...")

    # From a full URL (extracts host, port, api_base_path)
    pbx = FreePBX.from_url("https://pbx.example.com:2443/admin/api/api", ...)

    # From a config dict (framework integration)
    pbx = FreePBX.from_dict({"host": "pbx.example.com", "client_id": "...", ...})

    # From environment variables
    pbx = FreePBX.from_env()

    # Combined status (health + extensions + queues)
    result = pbx.status()
"""

from __future__ import annotations

from urllib.parse import urlparse

from pyfreepbx.clients.ami import AMIClient
from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.clients.oauth import OAuth2Client
from pyfreepbx.clients.rest import RestClient
from pyfreepbx.config import AMIConfig, FreePBXConfig
from pyfreepbx.exceptions import ConfigError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.health import StatusResult
from pyfreepbx.services.extensions import ExtensionService
from pyfreepbx.services.firewall import FirewallService
from pyfreepbx.services.health import HealthService
from pyfreepbx.services.queues import QueueService
from pyfreepbx.services.system import SystemService

log = get_logger("facade")


class FreePBX:
    """Unified interface to FreePBX GraphQL API and Asterisk AMI.

    Provides access to domain services via attribute-style access:
        pbx.extensions, pbx.queues, pbx.system
    """

    def __init__(
        self,
        *,
        host: str,
        api_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        port: int = 443,
        scheme: str = "https",
        api_base_path: str = "/admin/api/api",
        verify_ssl: bool = True,
        timeout: float = 30.0,
        ami_host: str | None = None,
        ami_port: int = 5038,
        ami_username: str | None = None,
        ami_secret: str | None = None,
        ami_timeout: float = 10.0,
    ) -> None:
        # GraphQL config (always required)
        self._gql_config = FreePBXConfig(
            host=host,
            api_token=api_token,
            client_id=client_id,
            client_secret=client_secret,
            port=port,
            scheme=scheme,
            api_base_path=api_base_path,
            verify_ssl=verify_ssl,
            timeout=timeout,
        )

        # OAuth2 token provider (when credentials are set)
        self._oauth: OAuth2Client | None = None
        token_provider = None
        if self._gql_config.has_oauth2:
            self._oauth = OAuth2Client(self._gql_config)
            token_provider = self._oauth

        self._client = FreePBXClient(self._gql_config, token_provider=token_provider)

        # REST client
        self._rest_client = RestClient(self._gql_config, token_provider=token_provider)

        # AMI config (optional — needed for live stats and admin actions)
        self._ami_client: AMIClient | None = None
        if ami_username and ami_secret:
            self._ami_config = AMIConfig(
                host=ami_host or host,
                port=ami_port,
                username=ami_username,
                secret=ami_secret,
                timeout=ami_timeout,
            )
            self._ami_client = AMIClient(self._ami_config)

        # Services
        self._extensions = ExtensionService(self._client, self._rest_client)
        self._queues = QueueService(self._client, self._ami_client)
        self._system = SystemService(self._client, self._ami_client)
        self._health = HealthService(self._client, self._ami_client)
        self._firewall = FirewallService(self._rest_client)

        log.debug("FreePBX facade initialized for %s", host)

    @classmethod
    def from_env(cls) -> FreePBX:
        """Create a FreePBX instance from environment variables.

        Authentication (one of):
            FREEPBX_CLIENT_ID + FREEPBX_CLIENT_SECRET — OAuth2 client_credentials (preferred)
            FREEPBX_API_TOKEN — static Bearer token (legacy)

        Required env vars:
            FREEPBX_HOST

        Optional env vars (enable AMI features):
            AMI_HOST (defaults to FREEPBX_HOST),
            AMI_USERNAME, AMI_SECRET,
            AMI_PORT (default 5038), AMI_TIMEOUT (default 10)

        Optional env vars (GraphQL/REST tuning):
            FREEPBX_PORT (default 443),
            FREEPBX_API_BASE_PATH (default /admin/api/api),
            FREEPBX_VERIFY_SSL (default true),
            FREEPBX_TIMEOUT (default 30)
        """
        import os

        host = os.environ.get("FREEPBX_HOST")
        if not host:
            raise ConfigError(
                "FREEPBX_HOST environment variable is required. "
                "Set it or use FreePBX(...) with explicit arguments."
            )

        client_id = os.environ.get("FREEPBX_CLIENT_ID", "")
        client_secret = os.environ.get("FREEPBX_CLIENT_SECRET", "")
        api_token = os.environ.get("FREEPBX_API_TOKEN", "")

        if not (client_id and client_secret) and not api_token:
            raise ConfigError(
                "Either FREEPBX_CLIENT_ID + FREEPBX_CLIENT_SECRET (OAuth2) or "
                "FREEPBX_API_TOKEN (static token) must be set."
            )

        return cls(
            host=host,
            api_token=api_token,
            client_id=client_id,
            client_secret=client_secret,
            port=int(os.environ.get("FREEPBX_PORT", "443")),
            api_base_path=os.environ.get("FREEPBX_API_BASE_PATH", "/admin/api/api"),
            verify_ssl=os.environ.get("FREEPBX_VERIFY_SSL", "true").lower() in ("true", "1"),
            timeout=float(os.environ.get("FREEPBX_TIMEOUT", "30")),
            ami_host=os.environ.get("AMI_HOST"),
            ami_port=int(os.environ.get("AMI_PORT", "5038")),
            ami_username=os.environ.get("AMI_USERNAME"),
            ami_secret=os.environ.get("AMI_SECRET"),
            ami_timeout=float(os.environ.get("AMI_TIMEOUT", "10")),
        )

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        api_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        verify_ssl: bool = True,
        timeout: float = 30.0,
        ami_host: str | None = None,
        ami_port: int = 5038,
        ami_username: str | None = None,
        ami_secret: str | None = None,
        ami_timeout: float = 10.0,
        **kwargs,
    ) -> FreePBX:
        """Create a FreePBX instance from a full URL.

        Parses ``url`` to extract scheme, host, port, and api_base_path.
        Accepts bare hostnames as well (``pbx.example.com``).

        Any extra keyword arguments (e.g. ``port``) override the
        values extracted from the URL.

        Example::

            pbx = FreePBX.from_url(
                "https://pbx.example.com:2443/admin/api/api",
                client_id="my_id",
                client_secret="my_secret",
            )
        """
        scheme, host, port, api_base_path = cls._parse_url(url)
        # Allow explicit kwargs to override URL-derived values
        port = kwargs.pop("port", port)
        return cls(
            host=host,
            port=port,
            scheme=scheme,
            api_base_path=api_base_path,
            api_token=api_token,
            client_id=client_id,
            client_secret=client_secret,
            verify_ssl=verify_ssl,
            timeout=timeout,
            ami_host=ami_host,
            ami_port=ami_port,
            ami_username=ami_username,
            ami_secret=ami_secret,
            ami_timeout=ami_timeout,
        )

    @classmethod
    def from_dict(cls, config: dict) -> FreePBX:
        """Create a FreePBX instance from a configuration dictionary.

        Convenience for framework integration. Accepts the same keys as
        the constructor, plus ``url`` (parsed via :meth:`from_url` logic).

        If ``url`` is present it overrides ``host``, ``port``, and
        ``api_base_path``.
        """
        config = dict(config)  # shallow copy

        url = config.pop("url", None)
        if url:
            scheme, host, port, api_base_path = cls._parse_url(url)
            config.setdefault("scheme", scheme)
            config.setdefault("host", host)
            config.setdefault("port", port)
            config.setdefault("api_base_path", api_base_path)

        if "host" not in config:
            raise ConfigError("Either 'url' or 'host' must be provided in config dict.")

        return cls(**config)

    @staticmethod
    def _parse_url(url: str) -> tuple[str, str, int, str]:
        """Extract (scheme, hostname, port, api_base_path) from a URL or bare hostname."""
        has_scheme = "://" in url
        parsed = urlparse(url if has_scheme else f"https://{url}")
        hostname = parsed.hostname or url
        port = parsed.port or 443
        api_base_path = parsed.path.rstrip("/") or "/admin/api/api"
        if has_scheme:
            scheme = parsed.scheme or "https"
        else:
            # No explicit scheme — infer from port
            scheme = "http" if port in (80, 81, 82, 83) else "https"
        return scheme, hostname, port, api_base_path

    # ------------------------------------------------------------------
    # Service accessors
    # ------------------------------------------------------------------

    @property
    def extensions(self) -> ExtensionService:
        return self._extensions

    @property
    def queues(self) -> QueueService:
        return self._queues

    @property
    def system(self) -> SystemService:
        return self._system

    @property
    def health(self) -> HealthService:
        return self._health

    @property
    def firewall(self) -> FirewallService:
        return self._firewall

    @property
    def rest(self) -> RestClient:
        """Low-level REST API client for ``/rest`` endpoints."""
        return self._rest_client

    # ------------------------------------------------------------------
    # AMI connection management
    # ------------------------------------------------------------------

    @property
    def ami_available(self) -> bool:
        """Whether AMI credentials were provided."""
        return self._ami_client is not None

    def connect_ami(self) -> None:
        """Explicitly connect and authenticate to AMI.

        This is called automatically when AMI-dependent operations are
        used, but can be called manually to fail fast on bad credentials.
        """
        if self._ami_client is None:
            raise ConfigError("AMI is not configured. Provide ami_username and ami_secret.")
        self._ami_client.connect()
        self._ami_client.login()
        log.info("AMI connected: %s", self._ami_client.banner)

    # ------------------------------------------------------------------
    # Combined queries
    # ------------------------------------------------------------------

    def status(self) -> StatusResult:
        """Combined status snapshot: health + extensions + queues.

        Collects health, extension list, and queue list in one call.
        Individual sub-queries that fail are logged and skipped so
        the result always returns.

        If AMI is configured, endpoint registration summary is included.
        """
        result = StatusResult()

        try:
            health = self._health.summary()
            result.health = health
            result.ok = health.overall.value != "down"
        except Exception as exc:
            log.warning("Health check failed: %s", exc)
            result.error = str(exc)
            return result

        # Extensions via GraphQL
        try:
            extensions = self._extensions.list()
            result.extensions = extensions
            result.extension_count = len(extensions)
        except Exception as exc:
            log.debug("Extension listing skipped: %s", exc)

        # Queues via GraphQL
        try:
            queues = self._queues.list()
            result.queues = queues
            result.queue_count = len(queues)
        except Exception as exc:
            log.debug("Queue listing skipped: %s", exc)

        # Endpoint registration summary (AMI only)
        try:
            endpoints = self._health.endpoint_summary()
            if endpoints is not None:
                result.endpoints = endpoints
        except Exception as exc:
            log.debug("Endpoint summary skipped (AMI): %s", exc)

        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close all connections."""
        self._client.close()
        self._rest_client.close()
        if self._oauth is not None:
            self._oauth.close()
        if self._ami_client is not None:
            self._ami_client.disconnect()

    def __enter__(self) -> FreePBX:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        ami_status = "enabled" if self.ami_available else "disabled"
        return f"<FreePBX host={self._gql_config.host!r} ami={ami_status}>"
