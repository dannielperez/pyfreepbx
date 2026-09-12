"""Tests for the bounded, read-only queue configuration DB reader."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from pyfreepbx.clients.queue_db import (
    _MAX_STATIC_MEMBERS,
    QueueConfigDbReader,
    QueueConfigDbUnavailableError,
)
from pyfreepbx.config import DBConfig


def _install_fake_pymysql(monkeypatch, rows, capture, *, execute_error=False):
    class _MySqlError(Exception):
        pass

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params):
            capture["sql"] = sql
            capture["params"] = list(params)
            if execute_error:
                raise _MySqlError("denied")

        def fetchall(self):
            return rows

    class _Conn:
        def __init__(self, **kwargs):
            capture["connect_kwargs"] = kwargs

        def cursor(self):
            return _Cursor()

        def close(self):
            capture["closed"] = True

    module = ModuleType("pymysql")
    module.MySQLError = _MySqlError  # type: ignore[attr-defined]
    module.connect = lambda **kwargs: _Conn(**kwargs)  # type: ignore[attr-defined]
    module.cursors = SimpleNamespace(DictCursor=object)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pymysql", module)


@pytest.fixture
def db_config() -> DBConfig:
    return DBConfig(host="10.0.0.9", port=3306, name="asterisk", user="ro", password="pw")


def test_member_lines_uses_bounded_parameterized_ordered_select(monkeypatch, db_config) -> None:
    capture: dict = {}
    _install_fake_pymysql(
        monkeypatch,
        [
            {"data": "PJSIP/100,4"},
            {"data": b"Local/119@from-queue/n,0"},
        ],
        capture,
    )

    result = QueueConfigDbReader(db_config).member_lines("99")

    assert result == ["PJSIP/100,4", "Local/119@from-queue/n,0"]
    assert "WHERE id = %s AND keyword = %s" in capture["sql"]
    assert "ORDER BY CAST(flags AS UNSIGNED), flags" in capture["sql"]
    assert capture["params"] == ["99", "member", _MAX_STATIC_MEMBERS + 1]
    assert capture["closed"] is True
    assert capture["connect_kwargs"]["read_timeout"] == 15.0


def test_member_lines_rejects_invalid_table(db_config) -> None:
    with pytest.raises(ValueError, match="table"):
        QueueConfigDbReader(db_config, table="queues_details; DROP TABLE users")


def test_member_lines_fails_closed_at_hard_cap(monkeypatch, db_config) -> None:
    capture: dict = {}
    rows = [{"data": f"{index},0"} for index in range(_MAX_STATIC_MEMBERS + 1)]
    _install_fake_pymysql(monkeypatch, rows, capture)

    with pytest.raises(QueueConfigDbUnavailableError, match="read limit"):
        QueueConfigDbReader(db_config).member_lines("99")


def test_member_lines_wraps_database_errors_and_closes(monkeypatch, db_config) -> None:
    capture: dict = {}
    _install_fake_pymysql(monkeypatch, [], capture, execute_error=True)

    with pytest.raises(QueueConfigDbUnavailableError, match="database read failed"):
        QueueConfigDbReader(db_config).member_lines("99")

    assert capture["closed"] is True


@pytest.mark.parametrize("row", [{}, {"data": None}, {"data": ""}, {"data": 119}])
def test_member_lines_rejects_invalid_rows(monkeypatch, db_config, row) -> None:
    capture: dict = {}
    _install_fake_pymysql(monkeypatch, [row], capture)

    with pytest.raises(QueueConfigDbUnavailableError, match="invalid"):
        QueueConfigDbReader(db_config).member_lines("99")
