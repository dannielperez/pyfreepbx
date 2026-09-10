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


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Doreload is required", True),
        ("Reload not required", False),
    ],
)
def test_config_reload_required_normalizes_freepbx_messages(message: str, expected: bool) -> None:
    client = MagicMock()
    client.graphql.query.return_value = {"fetchNeedReload": {"status": True, "message": message}}

    assert SystemService(client).config_reload_required() is expected


def test_config_reload_required_rejects_ambiguous_response() -> None:
    client = MagicMock()
    client.graphql.query.return_value = {
        "fetchNeedReload": {"status": True, "message": "Operation complete"}
    }

    with pytest.raises(RuntimeError, match="ambiguous"):
        SystemService(client).config_reload_required()


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


def test_apply_config_and_wait_reconciles_false_acknowledgement() -> None:
    client = MagicMock()
    client.graphql.mutation.return_value = {
        "doreload": {"status": False, "message": "Reload failed"}
    }
    client.graphql.query.side_effect = [
        {"fetchNeedReload": {"status": True, "message": "Doreload is required"}},
        {"fetchNeedReload": {"status": True, "message": "Reload not required"}},
    ]
    now = {"value": 0.0}
    sleeps: list[float] = []

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        now["value"] += delay

    service = SystemService(
        client,
        sleep=sleep,
        clock=lambda: now["value"],
    )

    result = service.apply_config_and_wait(timeout=2.0, poll_interval=0.25)

    assert result.acknowledged is False
    assert result.converged is True
    assert result.message == "Reload not required"
    assert sleeps == [0.25]
    client.graphql.mutation.assert_called_once()
    assert client.graphql.query.call_count == 2


def test_apply_config_and_wait_returns_pending_at_deadline_without_replay() -> None:
    client = MagicMock()
    client.graphql.mutation.return_value = {
        "doreload": {"status": False, "message": "Reload failed"}
    }
    client.graphql.query.return_value = {
        "fetchNeedReload": {"status": True, "message": "Doreload is required"}
    }
    now = {"value": 0.0}

    service = SystemService(
        client,
        sleep=lambda delay: now.__setitem__("value", now["value"] + delay),
        clock=lambda: now["value"],
    )

    result = service.apply_config_and_wait(timeout=0.5, poll_interval=0.25)

    assert result.acknowledged is False
    assert result.converged is False
    assert result.message == "Doreload is required"
    client.graphql.mutation.assert_called_once()
    assert client.graphql.query.call_count == 2


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan")])
def test_apply_config_and_wait_rejects_invalid_timeout_before_mutation(timeout: float) -> None:
    client = MagicMock()

    with pytest.raises(ValueError, match="timeout must be finite"):
        SystemService(client).apply_config_and_wait(timeout=timeout)

    client.graphql.mutation.assert_not_called()
