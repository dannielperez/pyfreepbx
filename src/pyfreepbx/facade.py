"""FreePBX facade — main entry point for the library.

Usage:
    from pyfreepbx import FreePBX

    pbx = FreePBX.from_env()
    pbx.extensions.list()
"""

from __future__ import annotations

from pyfreepbx.clients.ami import AMIClient
from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.clients.oauth import OAuth2Client
from pyfreepbx.clients.rest import RestClient
from pyfreepbx.config import AMIConfig, FreePBXConfig
from pyfreepbx.exceptions import ConfigError
from pyfreepbx.logging import get_logger
from pyfreepbx.services.extensions import ExtensionService
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
        self._extensions = ExtensionService(self._client)
        self._queues = QueueService(self._client, self._ami_client)
        self._system = SystemService(self._client, self._ami_client)
        self._health = HealthService(self._client, self._ami_client)

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
