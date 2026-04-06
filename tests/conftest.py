"""Shared test fixtures for pyfreepbx tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pyfreepbx.clients.ami import AMIClient
from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.clients.graphql import GraphQLClient
from pyfreepbx.config import AMIConfig, FreePBXConfig


@pytest.fixture
def graphql_config() -> FreePBXConfig:
    return FreePBXConfig(
        host="pbx.example.com",
        api_token="test-token-123",
        port=443,
        verify_ssl=False,
        timeout=5.0,
    )


@pytest.fixture
def ami_config() -> AMIConfig:
    return AMIConfig(
        host="pbx.example.com",
        port=5038,
        username="admin",
        secret="test-secret",
        timeout=5.0,
    )


@pytest.fixture
def mock_graphql(graphql_config: FreePBXConfig) -> MagicMock:
    """A mocked GraphQLClient — use mock.query.return_value to set responses."""
    mock = MagicMock(spec=GraphQLClient)
    mock._config = graphql_config
    return mock


@pytest.fixture
def mock_freepbx_client() -> MagicMock:
    """A mocked FreePBXClient — use to mock service dependencies."""
    mock = MagicMock(spec=FreePBXClient)
    mock.graphql = MagicMock(spec=GraphQLClient)
    return mock


@pytest.fixture
def mock_ami(ami_config: AMIConfig) -> MagicMock:
    """A mocked AMIClient — use mock.send_action.return_value to set responses."""
    mock = MagicMock(spec=AMIClient)
    mock._config = ami_config
    return mock
