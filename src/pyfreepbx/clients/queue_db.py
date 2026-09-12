"""Bounded, read-only access to FreePBX static queue-member configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyfreepbx.clients.base import BaseClient
from pyfreepbx.logging import get_logger

if TYPE_CHECKING:
    from pyfreepbx.config import DBConfig

log = get_logger("clients.queue_db")

_MAX_STATIC_MEMBERS = 500


class QueueConfigDbUnavailableError(RuntimeError):
    """The optional read-only queue configuration source was unavailable."""


class QueueConfigDbReader(BaseClient):
    """Read static queue-member inputs from FreePBX's configuration database."""

    def __init__(
        self,
        config: DBConfig,
        *,
        timeout: float = 15.0,
        table: str = "queues_details",
    ) -> None:
        self._config = config
        self._timeout = timeout
        if not table.isidentifier():
            raise ValueError(f"Invalid queue details table name: {table!r}")
        self._table = table

    def member_lines(self, queue: str) -> list[str]:
        """Return one queue's ordered static-member inputs.

        FreePBX stores the complete generated member line in ``data`` and its
        list position in ``flags``. The extra row detects an unexpectedly large
        result without permitting an unbounded read.
        """
        try:
            import pymysql  # type: ignore[import-untyped]  # lazy: opt-in DB path
        except ImportError as exc:
            raise QueueConfigDbUnavailableError(
                "The optional pymysql driver is not installed."
            ) from exc

        sql = (
            f"SELECT data FROM {self._table} "
            "WHERE id = %s AND keyword = %s "
            "ORDER BY CAST(flags AS UNSIGNED), flags LIMIT %s"
        )
        params: list[Any] = [queue, "member", _MAX_STATIC_MEMBERS + 1]

        try:
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
        except pymysql.MySQLError as exc:
            raise QueueConfigDbUnavailableError(
                "FreePBX queue configuration database read failed."
            ) from exc

        if len(rows) > _MAX_STATIC_MEMBERS:
            raise QueueConfigDbUnavailableError(
                f"Queue {queue!r} exceeds the {_MAX_STATIC_MEMBERS}-member read limit."
            )

        lines: list[str] = []
        for row in rows:
            value = row.get("data") if isinstance(row, dict) else None
            if isinstance(value, bytes):
                value = value.decode("utf-8", "replace")
            if not isinstance(value, str) or not value.strip():
                raise QueueConfigDbUnavailableError(
                    "FreePBX returned an invalid static queue-member database row."
                )
            lines.append(value.strip())

        log.debug("queue_db: fetched %d static members for queue %s", len(lines), queue)
        return lines

    def close(self) -> None:
        """No persistent connection is held; nothing to release."""
