"""Direct-DB CDR reader — bounded, read-only, sargable.

FreePBX 16's ``fetchAllCdrs`` GraphQL resolver builds a non-sargable query
(``WHERE DATE(calldate) BETWEEN ...`` + ``ORDER BY`` a computed alias) and, on
a large ``cdr`` table (millions of rows), full-scans + filesorts on every call
— it times out regardless of the date window or ``first`` limit (verified live
against FreePBX 16 / cdr 16.0.50 on a 6.3M-row table, 2026-07-13).

This reader is the escape hatch: it connects directly to the Asterisk CDR
database with a **read-only** account and issues a sargable, index-friendly,
bounded query (``calldate >= %s AND calldate < %s ORDER BY calldate DESC LIMIT
%s`` — never wrapping ``calldate`` in a function), which uses the table's
existing ``calldate`` index and returns in milliseconds.

It is read-only by construction (only ``SELECT`` is ever issued) and returns
JSON-safe row dicts shaped like the GraphQL ``cdrs`` rows, so the diagnostics
service normalizes both paths identically.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pyfreepbx.clients.base import BaseClient
from pyfreepbx.logging import get_logger

if TYPE_CHECKING:
    from pyfreepbx.config import DBConfig

log = get_logger("clients.cdr_db")

# Columns mirror the fields the GraphQL ``fetchAllCdrs`` path returns, so
# DiagnosticsService._to_cdr_item normalizes DB rows and GraphQL rows the same.
_CDR_COLUMNS = (
    "uniqueid",
    "calldate",
    "clid",
    "src",
    "dst",
    "dcontext",
    "channel",
    "dstchannel",
    "lastapp",
    "duration",
    "billsec",
    "disposition",
    "accountcode",
    "did",
    "recordingfile",
    "cnum",
    "linkedid",
    "sequence",
)


class CdrDbReader(BaseClient):
    """Read-only, bounded direct reader for the Asterisk ``cdr`` table."""

    def __init__(self, config: DBConfig, *, timeout: float = 15.0, table: str = "cdr") -> None:
        self._config = config
        self._timeout = timeout
        # Table name is not user-supplied (fixed default / deployment config),
        # but validate it is a bare identifier so it can never inject.
        if not table.isidentifier():
            msg = f"Invalid CDR table name: {table!r}"
            raise ValueError(msg)
        self._table = table

    def fetch_cdr(
        self,
        *,
        date_from: str = "",
        date_to: str = "",
        extension: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` CDR rows in the window, newest first.

        The window is a half-open ``[start, end)`` interval on the real
        ``calldate`` column so the existing index is used. A date-only bound is
        expanded to a day boundary (``end`` becomes the following midnight, so
        the ``date_to`` day is included). An absent bound is simply omitted.
        """
        import pymysql  # type: ignore[import-untyped]  # lazy: opt-in DB path

        limit = max(1, int(limit))
        where = ["calldate >= %s"] if date_from else []
        params: list[Any] = []

        start = _to_sql_dt(date_from, is_end=False)
        if start:
            params.append(start)
        elif date_from:
            # Unparseable non-empty date_from: drop the lower bound rather than
            # silently returning nothing.
            where = []

        end = _to_sql_dt(date_to, is_end=True)
        if end:
            where.append("calldate < %s")
            params.append(end)

        if extension:
            where.append("(src = %s OR dst = %s OR cnum = %s)")
            params.extend([extension, extension, extension])

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        sql = (
            f"SELECT {', '.join(_CDR_COLUMNS)} FROM {self._table}"
            f"{where_sql} ORDER BY calldate DESC LIMIT %s"
        )
        params.append(limit)

        conn = pymysql.connect(
            host=self._config.host,
            port=self._config.port,
            user=self._config.user,
            password=self._config.password,
            database=self._config.name,
            connect_timeout=self._timeout,
            read_timeout=self._timeout,
            write_timeout=self._timeout,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()

        log.debug("cdr_db: fetched %d rows (limit=%d)", len(rows), limit)
        return [_jsonable_row(row) for row in rows]

    def close(self) -> None:
        """No persistent connection is held; nothing to release."""


def _to_sql_dt(value: str, *, is_end: bool) -> str:
    """Normalize a caller date string to ``YYYY-MM-DD HH:MM:SS`` for binding.

    A date-only ``value`` on the ``is_end`` side is advanced to the following
    midnight so the half-open ``calldate < end`` still includes that whole day.
    Empty or unparseable input returns ``""`` (the bound is dropped).
    """
    text = (value or "").strip()
    if not text:
        return ""
    parsed: datetime | None = None
    date_only = False
    try:
        parsed = datetime.fromisoformat(text)
        date_only = len(text) <= 10  # e.g. "2026-07-13"
    except ValueError:
        for fmt, only in (("%Y-%m-%d %H:%M:%S", False), ("%Y-%m-%d", True)):
            try:
                parsed = datetime.strptime(text, fmt)
                date_only = only
                break
            except ValueError:
                continue
    if parsed is None:
        return ""
    if is_end and date_only:
        parsed = _next_midnight(parsed)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _next_midnight(dt: datetime) -> datetime:
    from datetime import timedelta

    return datetime(dt.year, dt.month, dt.day) + timedelta(days=1)


def _jsonable_row(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce a DB row to JSON-safe scalars (datetime→str, Decimal→number)."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, date):
            out[key] = value.isoformat()
        elif isinstance(value, Decimal):
            out[key] = int(value) if value == value.to_integral_value() else float(value)
        elif isinstance(value, bytes):
            out[key] = value.decode("utf-8", "replace")
        else:
            out[key] = value
    return out
