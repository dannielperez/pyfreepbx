"""Tests for GraphQL-backed SystemService configuration operations."""

from unittest.mock import MagicMock

import pytest

from pyfreepbx.services.system import SystemService


def test_config_reload_status_uses_fetch_need_reload() -> None:
    client = MagicMock()
    client.graphql.query.return_value = {
        "fetchNeedReload": {"status": True, "message": "Doreload is required"}
    }

    result = SystemService(client).config_reload_status()

    assert result.status is True
    assert result.message == "Doreload is required"
    query = client.graphql.query.call_args.args[0]
    assert "fetchNeedReload" in query


def test_apply_config_uses_doreload_and_returns_transaction() -> None:
    client = MagicMock()
    client.graphql.mutation.return_value = {
        "doreload": {
            "status": True,
            "message": "Apply config initiated",
            "transaction_id": "42",
        }
    }

    result = SystemService(client).apply_config()

    assert result.status is True
    assert result.transaction_id == "42"
    query, variables = client.graphql.mutation.call_args.args
    assert "doreload" in query
    assert variables == {"input": {}}


def test_apply_config_timeout_propagates_without_retry() -> None:
    client = MagicMock()
    client.graphql.mutation.side_effect = TimeoutError("response timed out")

    with pytest.raises(TimeoutError, match="response timed out"):
        SystemService(client).apply_config()

    client.graphql.mutation.assert_called_once()
