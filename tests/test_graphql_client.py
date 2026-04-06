"""Tests for GraphQLClient."""

from __future__ import annotations

import httpx
import pytest
import respx

from pyfreepbx.clients.graphql import GraphQLClient
from pyfreepbx.config import FreePBXConfig
from pyfreepbx.exceptions import AuthenticationError, GraphQLError


@pytest.fixture
def config() -> FreePBXConfig:
    return FreePBXConfig(
        host="pbx.test",
        api_token="test-token",
        port=443,
        verify_ssl=False,
    )


@pytest.fixture
def client(config: FreePBXConfig) -> GraphQLClient:
    return GraphQLClient(config)


class TestGraphQLClient:
    @respx.mock
    def test_query_success(self, config: FreePBXConfig) -> None:
        respx.post(f"{config.graphql_url}").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"fetchAllExtensions": {"extensions": []}}},
            )
        )
        client = GraphQLClient(config)
        result = client.query("{ fetchAllExtensions { extensions { extension } } }")
        assert "fetchAllExtensions" in result

    @respx.mock
    def test_query_auth_failure(self, config: FreePBXConfig) -> None:
        respx.post(f"{config.graphql_url}").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        client = GraphQLClient(config)
        with pytest.raises(AuthenticationError):
            client.query("{ __typename }")

    @respx.mock
    def test_query_graphql_errors(self, config: FreePBXConfig) -> None:
        respx.post(f"{config.graphql_url}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "errors": [{"message": "Syntax error"}],
                    "data": None,
                },
            )
        )
        client = GraphQLClient(config)
        with pytest.raises(GraphQLError, match="Syntax error") as exc_info:
            client.query("{ bad }")
        assert len(exc_info.value.errors) == 1
