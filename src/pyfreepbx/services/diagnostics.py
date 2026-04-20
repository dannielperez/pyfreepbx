"""Diagnostics service for CDR, logs, and Asterisk runtime visibility."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pyfreepbx.clients.ami import AMIClient
from pyfreepbx.clients.rest import RestClient
from pyfreepbx.logging import get_logger
from pyfreepbx.models.asterisk import AsteriskSummary
from pyfreepbx.models.cdr import CDRListResult, CallDetailRecord
from pyfreepbx.models.device import DeviceState
from pyfreepbx.models.logs import AsteriskLogLine, AsteriskLogResult

log = get_logger("services.diagnostics")


class DiagnosticsService:
    """Read-path diagnostics API for CDR and Asterisk visibility.

    This service is intentionally bounded and normalization-focused:
    - all list methods enforce a hard max limit
    - responses are converted to typed models
    - missing backend capabilities degrade gracefully
    """

    _HARD_LIMIT = 500

    def __init__(self, rest: RestClient | None = None, ami: AMIClient | None = None) -> None:
        self._rest = rest
        self._ami = ami

    def cdr(
        self,
        *,
        extension: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 100,
    ) -> CDRListResult:
        """Fetch and normalize CDR rows from FreePBX REST API."""
        if self._rest is None:
            raise RuntimeError("REST client is required for CDR queries")

        bounded_limit = max(1, min(limit, self._HARD_LIMIT))
        params: dict[str, Any] = {"limit": bounded_limit}
        if extension:
            params["extension"] = extension
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        payload = self._rest.get("cdr", params=params)
        rows = _extract_rows(payload)
        items = [_to_cdr_item(row) for row in rows[:bounded_limit]]
        return CDRListResult(
            items=items,
            total=len(rows),
            truncated=len(rows) > bounded_limit,
        )

    def asterisk_logs(
        self,
        *,
        extension: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 200,
    ) -> AsteriskLogResult:
        """Fetch and normalize Asterisk logs from FreePBX REST API.

        Expected backend endpoint: /rest/asterisk/logs
        Falls back to parsing raw list/string payloads.
        """
        if self._rest is None:
            raise RuntimeError("REST client is required for log queries")

        bounded_limit = max(1, min(limit, self._HARD_LIMIT))
        params: dict[str, Any] = {"limit": bounded_limit}
        if extension:
            params["extension"] = extension
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        payload = self._rest.get("asterisk/logs", params=params)
        rows = _extract_rows(payload)
        lines = [_to_log_line(row) for row in rows[:bounded_limit]]
        return AsteriskLogResult(
            lines=lines,
            total=len(rows),
            truncated=len(rows) > bounded_limit,
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


def _extract_rows(payload: Any) -> list[Any]:
    """Normalize list-ish payloads from REST into a list of rows."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "rows", "data", "logs", "cdr", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    if isinstance(payload, str):
        lines = [line for line in payload.splitlines() if line.strip()]
        return [{"raw": line} for line in lines]
    return []


def _to_cdr_item(row: Any) -> CallDetailRecord:
    if not isinstance(row, dict):
        row = {"raw": row}

    timestamp = _parse_datetime(
        row.get("calldate")
        or row.get("timestamp")
        or row.get("time")
        or row.get("start")
        or ""
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
        raw=row,
    )


def _to_log_line(row: Any) -> AsteriskLogLine:
    if isinstance(row, str):
        return AsteriskLogLine(raw=row, message=row)
    if not isinstance(row, dict):
        row = {"raw": str(row)}

    raw = str(row.get("raw") or row.get("line") or row.get("message") or "")
    timestamp = _parse_datetime(str(row.get("timestamp") or row.get("time") or ""))
    level = str(row.get("level") or "")
    message = str(row.get("message") or raw)
    return AsteriskLogLine(
        timestamp=timestamp,
        level=level,
        message=message,
        raw=raw or message,
    )


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
