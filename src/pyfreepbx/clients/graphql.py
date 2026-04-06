"""FreePBX GraphQL API client."""

from __future__ import annotations

from typing import Any

import httpx

from pyfreepbx.clients.base import BaseClient
from pyfreepbx.config import FreePBXConfig
from pyfreepbx.exceptions import AuthenticationError, GraphQLError
from pyfreepbx.logging import get_logger

log = get_logger("clients.graphql")


class GraphQLClient(BaseClient):
    """Low-level client for the FreePBX GraphQL API.

    Handles HTTP transport, authentication, and raw query execution.
    Does not interpret results — that's the service layer's job.
    """

    def __init__(self, config: FreePBXConfig) -> None:
        self._config = config
        self._http = httpx.Client(
            base_url=config.base_url,
            headers={
                "Authorization": f"Bearer {config.api_token}",
                "Content-Type": "application/json",
            },
            verify=config.verify_ssl,
            timeout=config.timeout,
        )
        log.debug("GraphQL client initialized for %s", config.base_url)

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL query and return the data payload.

        Raises:
            AuthenticationError: If the API returns 401/403.
            GraphQLError: If the response contains GraphQL-level errors.
        """
        return self._execute(query, variables)

    def mutation(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL mutation. Same transport as query."""
        return self._execute(query, variables)

    def _execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        log.debug("GraphQL request to %s", self._config.graphql_url)

        response = self._http.post(self._config.graphql_url, json=payload)

        if response.status_code in (401, 403):
            log.warning("GraphQL authentication failed: HTTP %d", response.status_code)
            raise AuthenticationError(
                f"GraphQL authentication failed: HTTP {response.status_code}"
            )
        response.raise_for_status()

        body = response.json()

        if "errors" in body:
            errors = body["errors"]
            first_msg = errors[0].get("message", "Unknown GraphQL error") if errors else ""
            log.error("GraphQL error: %s", first_msg)
            raise GraphQLError(first_msg, errors=errors)

        return body.get("data", {})

    def close(self) -> None:
        self._http.close()
        log.debug("GraphQL client closed")
