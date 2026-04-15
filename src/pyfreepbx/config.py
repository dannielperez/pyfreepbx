"""Connection and authentication settings for FreePBX, AMI, and optional DB."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class FreePBXConfig(BaseSettings):
    """Configuration for the FreePBX API connection.

    Supports two authentication modes:

    1. **OAuth2 (preferred)** — set ``client_id`` and ``client_secret``.
       Tokens are fetched/refreshed automatically from the ``/token`` endpoint.
    2. **Static token (legacy)** — set ``api_token`` with a pre-obtained
       Bearer token.

    The ``api_base_path`` defaults to ``/admin/api/api`` which is the standard
    FreePBX API prefix. All endpoint paths (``/token``, ``/gql``, ``/rest``,
    ``/authorize``) are appended to this base.
    """

    model_config = {"env_prefix": "FREEPBX_"}

    host: str = Field(description="FreePBX hostname or IP address")
    port: int = Field(default=443, description="HTTPS port")
    verify_ssl: bool = Field(default=True, description="Verify TLS certificates")
    timeout: float = Field(default=30.0, description="HTTP request timeout in seconds")
    api_base_path: str = Field(
        default="/admin/api/api",
        description="Base path for the FreePBX API (token, gql, rest, authorize endpoints live under this)",
    )

    # OAuth2 credentials (preferred)
    client_id: str = Field(default="", description="OAuth2 client ID for client_credentials grant")
    client_secret: str = Field(default="", description="OAuth2 client secret")

    # Static token (legacy / backward-compatible)
    api_token: str = Field(default="", description="Pre-obtained Bearer token (used when OAuth2 credentials are not set)")

    @property
    def base_url(self) -> str:
        scheme = "https" if self.port == 443 else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @property
    def graphql_url(self) -> str:
        return f"{self.base_url}{self.api_base_path}/gql"

    @property
    def rest_url(self) -> str:
        return f"{self.base_url}{self.api_base_path}/rest"

    @property
    def token_url(self) -> str:
        return f"{self.base_url}{self.api_base_path}/token"

    @property
    def authorize_url(self) -> str:
        return f"{self.base_url}{self.api_base_path}/authorize"

    @property
    def has_oauth2(self) -> bool:
        """Whether OAuth2 credentials are configured."""
        return bool(self.client_id and self.client_secret)


class AMIConfig(BaseSettings):
    """Configuration for the Asterisk Manager Interface connection."""

    model_config = {"env_prefix": "AMI_"}

    host: str = Field(description="AMI hostname or IP address")
    port: int = Field(default=5038, description="AMI TCP port")
    username: str = Field(description="AMI login username")
    secret: str = Field(description="AMI login secret")
    timeout: float = Field(default=10.0, description="Socket timeout in seconds")


class DBConfig(BaseSettings):
    """Optional configuration for direct Asterisk/FreePBX database access.

    Direct DB access is discouraged — prefer the GraphQL API. This exists
    as an escape hatch for data not yet exposed via the API.
    """

    model_config = {"env_prefix": "DB_"}

    host: str = Field(description="MySQL/MariaDB hostname")
    port: int = Field(default=3306, description="Database port")
    name: str = Field(default="asterisk", description="Database name")
    user: str = Field(description="Database username")
    password: str = Field(description="Database password")
