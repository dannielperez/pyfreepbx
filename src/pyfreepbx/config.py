"""Connection and authentication settings for FreePBX, AMI, and optional DB."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class FreePBXConfig(BaseSettings):
    """Configuration for the FreePBX GraphQL API connection."""

    model_config = {"env_prefix": "FREEPBX_"}

    host: str = Field(description="FreePBX hostname or IP address")
    api_token: str = Field(description="Bearer token for GraphQL API authentication")
    port: int = Field(default=443, description="HTTPS port")
    verify_ssl: bool = Field(default=True, description="Verify TLS certificates")
    timeout: float = Field(default=30.0, description="HTTP request timeout in seconds")

    @property
    def base_url(self) -> str:
        scheme = "https" if self.port == 443 else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @property
    def graphql_url(self) -> str:
        return f"{self.base_url}/admin/api/api/gql"


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
