"""Diagnostics service for CDR, logs, and Asterisk runtime visibility."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pyfreepbx.logging import get_logger
from pyfreepbx.models.asterisk import AsteriskSummary
from pyfreepbx.models.cdr import CallDetailRecord, CDRListResult
from pyfreepbx.models.device import DeviceState

log = get_logger("services.diagnostics")

if TYPE_CHECKING:
    from pyfreepbx.clients.ami import AMIClient
    from pyfreepbx.clients.cdr_db import CdrDbReader
    from pyfreepbx.clients.freepbx import FreePBXClient

# FreePBX 16+ exposes CDR through the api module's GraphQL schema; the REST
# /cdr resource this service originally targeted does not exist there (every
# call 404s — verified live against FreePBX 16 / api 16.0.18, 2026-07-12).
# Field set introspected from a live FreePBX 16 schema.
_CDR_GQL_QUERY = """
query FetchAllCdrs($first: Int, $after: Int, $startDate: String, $endDate: String) {
  fetchAllCdrs(first: $first, after: $after, startDate: $startDate, endDate: $endDate) {
    totalCount
    cdrs {
      uniqueid
      calldate
      timestamp
      clid
      src
      dst
      dcontext
      channel
      dstchannel
      lastapp
      duration
      billsec
      disposition
      accountcode
      did
      recordingfile
      cnum
      linkedid
      sequence
    }
  }
}
"""


class DiagnosticsService:
    """Read-path diagnostics API for CDR and Asterisk visibility.

    This service is intentionally bounded and normalization-focused:
    - all list methods enforce a hard max limit
    - responses are converted to typed models
    - missing backend capabilities degrade gracefully
    """

    _HARD_LIMIT = 500

    def __init__(
        self,
        ami: AMIClient | None = None,
        client: FreePBXClient | None = None,
        cdr_db: CdrDbReader | None = None,
    ) -> None:
        self._ami = ami
        self._client = client
        self._cdr_db = cdr_db

    def cdr(
        self,
        *,
        extension: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 100,
    ) -> CDRListResult:
        """Fetch and normalize CDR rows.

        When a direct-DB reader is configured it is the primary path — a
        bounded, sargable query that avoids the FreePBX 16 ``fetchAllCdrs``
        full-scan/filesort at scale (see ``clients.cdr_db``). Otherwise CDR is
        read via the api module's GraphQL ``fetchAllCdrs``. The legacy REST
        ``/cdr`` resource does not exist on FreePBX 16 and is not retried.
        """
        bounded_limit = max(1, min(limit, self._HARD_LIMIT))

        if self._cdr_db is not None:
            return self._cdr_via_db(
                extension=extension,
                date_from=date_from,
                date_to=date_to,
                limit=bounded_limit,
            )

        if self._client is None:
            raise RuntimeError("A GraphQL client or DB reader is required for CDR queries")

        return self._cdr_via_graphql(
            extension=extension,
            date_from=date_from,
            date_to=date_to,
            limit=bounded_limit,
        )

    def _cdr_via_db(
        self,
        *,
        extension: str,
        date_from: str,
        date_to: str,
        limit: int,
    ) -> CDRListResult:
        """Fetch CDR rows via the read-only direct-DB reader (primary path)."""
        reader = self._cdr_db
        if reader is None:  # private-helper guard for static type safety
            raise RuntimeError("A DB reader is required for the direct-DB CDR path")
        rows = reader.fetch_cdr(
            date_from=date_from,
            date_to=date_to,
            extension=extension,
            limit=limit,
        )
        items = [_to_cdr_item(row) for row in rows]
        # A full page implies more rows exist beyond the window's newest slice;
        # exact totals are deliberately not computed (the COUNT(*) is what makes
        # the GraphQL path slow). The consumer upserts idempotently regardless.
        return CDRListResult(
            items=items,
            total=len(items),
            truncated=len(rows) >= limit,
        )

    def _cdr_via_graphql(
        self,
        *,
        extension: str,
        date_from: str,
        date_to: str,
        limit: int,
    ) -> CDRListResult:
        """Fetch CDR rows via the api module's ``fetchAllCdrs`` GraphQL query.

        ``fetchAllCdrs`` has no extension argument, so extension filtering is
        applied client-side against src/cnum/dst.
        """
        variables: dict[str, Any] = {"first": limit, "after": 0}
        start = _to_cdr_gql_date(date_from)
        end = _to_cdr_gql_date(date_to)
        if start:
            variables["startDate"] = start
        if end:
            variables["endDate"] = end

        client = self._client
        if client is None:  # private helper guard for static type safety
            raise RuntimeError("A GraphQL client is required for CDR queries")
        data = client.graphql.query(_CDR_GQL_QUERY, variables)
        connection = data.get("fetchAllCdrs") or {}
        rows = [row for row in (connection.get("cdrs") or []) if isinstance(row, dict)]

        if extension:
            rows = [
                row
                for row in rows
                if extension
                in (
                    str(row.get("src") or ""),
                    str(row.get("cnum") or ""),
                    str(row.get("dst") or ""),
                )
            ]

        total = connection.get("totalCount")
        if not isinstance(total, int):
            total = len(rows)
        items = [_to_cdr_item(row) for row in rows[:limit]]
        return CDRListResult(
            items=items,
            total=total,
            truncated=total > len(items),
        )

    def endpoint_details(self, extension: str) -> dict[str, Any]:
        """Fetch endpoint detail via AMI when available."""
        if self._ami is None:
            return {
                "extension": extension,
                "state": "unknown",
                "ip_address": "",
                "user_agent": "",
                "events": [],
            }

        events = self._ami.pjsip_endpoint(extension)
        state = "unknown"
        ip_address = ""
        user_agent = ""
        for event in events:
            if event.get("Event") == "EndpointDetail":
                device_state = event.get("DeviceState", "")
                state = _map_device_state(device_state)
            if event.get("Event") == "ContactStatusDetail":
                uri = event.get("URI", "")
                if uri.startswith("sip:"):
                    ip_address = uri.replace("sip:", "").split(":")[0]
                user_agent = event.get("UserAgent", "")

        return {
            "extension": extension,
            "state": state,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "events": events,
        }

    def asterisk_summary(self) -> AsteriskSummary:
        """Build a compact Asterisk summary from AMI data when available."""
        if self._ami is None:
            return AsteriskSummary()

        core = self._ami.core_status()
        endpoints = self._ami.pjsip_endpoints()
        channels = self._ami.run_action_with_events("CoreShowChannels")

        active_channels = sum(1 for event in channels if event.get("Event") == "CoreShowChannel")
        registered = sum(1 for d in endpoints if d.state == DeviceState.REGISTERED)
        unregistered = sum(1 for d in endpoints if d.state == DeviceState.UNREGISTERED)
        unavailable = sum(1 for d in endpoints if d.state == DeviceState.UNAVAILABLE)
        unknown = sum(1 for d in endpoints if d.state == DeviceState.UNKNOWN)

        return AsteriskSummary(
            version=core.asterisk_version,
            active_calls=core.active_calls,
            active_channels=active_channels,
            endpoint_total=len(endpoints),
            endpoint_registered=registered,
            endpoint_unregistered=unregistered,
            endpoint_unavailable=unavailable,
            endpoint_unknown=unknown,
        )


def _to_cdr_item(row: Any) -> CallDetailRecord:
    if not isinstance(row, dict):
        row = {"raw": row}

    timestamp = _parse_datetime(
        row.get("calldate") or row.get("timestamp") or row.get("time") or row.get("start") or ""
    )

    return CallDetailRecord(
        timestamp=timestamp,
        source=str(row.get("src") or row.get("source") or row.get("from") or ""),
        destination=str(row.get("dst") or row.get("destination") or row.get("to") or ""),
        duration=_to_int(row.get("duration")),
        billsec=_to_int(row.get("billsec")),
        disposition=str(row.get("disposition") or ""),
        unique_id=str(row.get("uniqueid") or row.get("unique_id") or ""),
        linked_id=str(row.get("linkedid") or row.get("linked_id") or ""),
        queue=str(row.get("queue") or row.get("queue_name") or ""),
        recording_file=str(row.get("recordingfile") or row.get("recording_file") or ""),
        raw=row,
    )


def _to_cdr_gql_date(value: str) -> str:
    """Normalize a caller-supplied date string for ``fetchAllCdrs``.

    The cdr GraphQL provider compares against MySQL ``calldate`` strings, so
    ISO-8601 inputs (``2026-07-10T15:38:51+00:00``) must be reshaped to
    ``YYYY-MM-DD HH:MM:SS``. Unparseable inputs pass through unchanged.
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _map_device_state(value: str) -> str:
    lowered = (value or "").strip().lower()
    if "avail" in lowered and "unavail" not in lowered:
        return "registered"
    if "unavail" in lowered:
        return "unavailable"
    if "unreg" in lowered or "offline" in lowered:
        return "unregistered"
    return "unknown"
