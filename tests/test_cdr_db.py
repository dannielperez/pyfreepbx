"""Tests for the direct-DB CDR reader and DiagnosticsService DB routing."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pyfreepbx.clients.cdr_db import CdrDbReader, _jsonable_row, _to_sql_dt
from pyfreepbx.config import DBConfig
from pyfreepbx.services.diagnostics import DiagnosticsService


class TestToSqlDt:
    def test_empty_returns_empty(self) -> None:
        assert _to_sql_dt("", is_end=False) == ""
        assert _to_sql_dt("   ", is_end=True) == ""

    def test_date_only_start_is_midnight(self) -> None:
        assert _to_sql_dt("2026-07-13", is_end=False) == "2026-07-13 00:00:00"

    def test_date_only_end_advances_to_next_midnight(self) -> None:
        # Half-open interval: end of the 13th must include all of the 13th.
        assert _to_sql_dt("2026-07-13", is_end=True) == "2026-07-14 00:00:00"

    def test_datetime_passthrough_not_advanced(self) -> None:
        assert _to_sql_dt("2026-07-13 06:25:22", is_end=True) == "2026-07-13 06:25:22"

    def test_iso_with_tz_reshaped(self) -> None:
        assert _to_sql_dt("2026-07-13T06:25:22+00:00", is_end=False) == "2026-07-13 06:25:22"

    def test_unparseable_returns_empty(self) -> None:
        assert _to_sql_dt("not-a-date", is_end=False) == ""


class TestJsonableRow:
    def test_coerces_scalars(self) -> None:
        row = {
            "calldate": datetime(2026, 7, 13, 6, 25, 22),
            "duration": Decimal("42"),
            "billsec": Decimal("1.5"),
            "clid": b'"Danny" <2701>',
            "disposition": "ANSWERED",
            "src": None,
        }
        out = _jsonable_row(row)
        assert out["calldate"] == "2026-07-13 06:25:22"
        assert out["duration"] == 42 and isinstance(out["duration"], int)
        assert out["billsec"] == 1.5 and isinstance(out["billsec"], float)
        assert out["clid"] == '"Danny" <2701>'
        assert out["disposition"] == "ANSWERED"
        assert out["src"] is None


def _install_fake_pymysql(monkeypatch, rows, capture):
    """Install a fake ``pymysql`` module that records the executed SQL/params."""

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params):
            capture["sql"] = sql
            capture["params"] = list(params)

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
    module.connect = lambda **kwargs: _Conn(**kwargs)  # type: ignore[attr-defined]
    module.cursors = SimpleNamespace(DictCursor=object)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pymysql", module)
    return capture


@pytest.fixture
def db_config() -> DBConfig:
    return DBConfig(host="10.0.0.9", port=3306, name="asterisk", user="ro", password="pw")


class TestCdrDbReader:
    def test_invalid_table_rejected(self, db_config) -> None:
        with pytest.raises(ValueError, match="table"):
            CdrDbReader(db_config, table="cdr; DROP TABLE x")

    def test_sargable_query_never_wraps_calldate(self, monkeypatch, db_config) -> None:
        cap: dict = {}
        _install_fake_pymysql(monkeypatch, rows=[], capture=cap)
        CdrDbReader(db_config).fetch_cdr(date_from="2026-07-13", date_to="2026-07-13", limit=5)

        sql = cap["sql"]
        assert "DATE(calldate)" not in sql  # the whole point: stays sargable
        assert "calldate >= %s" in sql
        assert "calldate < %s" in sql
        assert "ORDER BY calldate DESC" in sql
        assert sql.rstrip().endswith("LIMIT %s")
        # start=midnight of the 13th, end=midnight of the 14th (half-open), limit last
        assert cap["params"] == ["2026-07-13 00:00:00", "2026-07-14 00:00:00", 5]

    def test_extension_filter_binds_three_params(self, monkeypatch, db_config) -> None:
        cap: dict = {}
        _install_fake_pymysql(monkeypatch, rows=[], capture=cap)
        CdrDbReader(db_config).fetch_cdr(date_from="2026-07-13", extension="2701", limit=10)
        assert "(src = %s OR dst = %s OR cnum = %s)" in cap["sql"]
        assert cap["params"] == ["2026-07-13 00:00:00", "2701", "2701", "2701", 10]

    def test_no_window_drops_bounds(self, monkeypatch, db_config) -> None:
        cap: dict = {}
        _install_fake_pymysql(monkeypatch, rows=[], capture=cap)
        CdrDbReader(db_config).fetch_cdr(limit=3)
        assert "WHERE" not in cap["sql"]
        assert cap["params"] == [3]

    def test_rows_returned_json_safe(self, monkeypatch, db_config) -> None:
        rows = [
            {
                "uniqueid": "1783987196.441594",
                "calldate": datetime(2026, 7, 13, 23, 59, 56),
                "duration": Decimal("7"),
                "disposition": "ANSWERED",
            }
        ]
        cap: dict = {}
        _install_fake_pymysql(monkeypatch, rows=rows, capture=cap)
        out = CdrDbReader(db_config).fetch_cdr(date_from="2026-07-13", limit=100)
        assert out[0]["calldate"] == "2026-07-13 23:59:56"
        assert out[0]["duration"] == 7
        assert cap["closed"] is True
        assert cap["connect_kwargs"]["read_timeout"] == 15.0


class TestDiagnosticsCdrRouting:
    def test_db_reader_is_primary_when_present(self) -> None:
        reader = MagicMock()
        reader.fetch_cdr.return_value = [
            {
                "uniqueid": "u1",
                "calldate": "2026-07-13 23:59:56",
                "src": "2701",
                "dst": "99",
                "disposition": "ANSWERED",
                "duration": 7,
                "billsec": 5,
            },
        ]
        gql_client = MagicMock()
        svc = DiagnosticsService(ami=None, client=gql_client, cdr_db=reader)

        result = svc.cdr(date_from="2026-07-13", date_to="2026-07-13", limit=2)

        reader.fetch_cdr.assert_called_once()
        gql_client.graphql.query.assert_not_called()  # DB path bypasses GraphQL
        assert result.total == 1
        assert result.items[0].unique_id == "u1"
        assert result.items[0].source == "2701"
        assert result.items[0].timestamp == datetime(2026, 7, 13, 23, 59, 56, tzinfo=UTC)

    def test_truncated_when_full_page(self) -> None:
        reader = MagicMock()
        reader.fetch_cdr.return_value = [
            {"uniqueid": f"u{i}", "calldate": "2026-07-13 00:00:00"} for i in range(2)
        ]
        svc = DiagnosticsService(ami=None, client=MagicMock(), cdr_db=reader)
        result = svc.cdr(limit=2)
        assert result.truncated is True

    def test_db_path_uses_larger_limit_than_graphql(self) -> None:
        """The sargable direct-DB path takes up to _DB_HARD_LIMIT (5000), not the
        tight GraphQL _HARD_LIMIT (500) — otherwise an incremental sync never
        catches up on a busy PBX."""
        reader = MagicMock()
        reader.fetch_cdr.return_value = []
        svc = DiagnosticsService(ami=None, client=MagicMock(), cdr_db=reader)
        svc.cdr(limit=5000)
        assert reader.fetch_cdr.call_args.kwargs["limit"] == 5000

    def test_falls_back_to_graphql_without_reader(self) -> None:
        gql_client = MagicMock()
        gql_client.graphql.query.return_value = {"fetchAllCdrs": {"totalCount": 0, "cdrs": []}}
        svc = DiagnosticsService(ami=None, client=gql_client, cdr_db=None)
        svc.cdr(date_from="2026-07-13", limit=2)
        gql_client.graphql.query.assert_called_once()

    def test_raises_without_client_or_reader(self) -> None:
        svc = DiagnosticsService(ami=None, client=None, cdr_db=None)
        with pytest.raises(RuntimeError, match="DB reader"):
            svc.cdr(limit=2)
