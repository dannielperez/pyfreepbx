"""Tests for pyfreepbx DiagnosticsService."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.system import SystemInfo
from pyfreepbx.services.diagnostics import DiagnosticsService

FIXTURES = Path(__file__).parent / "fixtures" / "consumer_contracts"


def _load_fixture(name: str) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads((FIXTURES / name).read_text(encoding="utf-8")))


class TestDiagnosticsServiceEndpointDetails:
    def test_endpoint_details_without_ami(self) -> None:
        svc = DiagnosticsService(ami=None)
        details = svc.endpoint_details("1001")
        assert details["state"] == "unknown"
        assert details["events"] == []

    def test_endpoint_details_with_ami(self) -> None:
        ami = MagicMock()
        ami.pjsip_endpoint.return_value = [
            {"Event": "EndpointDetail", "DeviceState": "Unavailable"},
            {"Event": "ContactStatusDetail", "URI": "sip:10.0.0.55:5060", "UserAgent": "Yealink"},
        ]
        svc = DiagnosticsService(ami=ami)
        details = svc.endpoint_details("1001")
        assert details["state"] == "unavailable"
        assert details["ip_address"] == "10.0.0.55"
        assert details["user_agent"] == "Yealink"

    def test_endpoint_details_lazily_connects_and_logs_in(self) -> None:
        """The facade hands over an unconnected AMIClient; the read must open
        the session itself instead of raising ``Not connected to AMI``."""
        ami = MagicMock()
        ami.connected = False
        ami.authenticated = False
        ami.pjsip_endpoint.return_value = []
        svc = DiagnosticsService(ami=ami)

        svc.endpoint_details("1001")

        ami.connect.assert_called_once_with()
        ami.login.assert_called_once_with(events=False)
        ami.pjsip_endpoint.assert_called_once_with("1001")

    def test_endpoint_details_reuses_an_authenticated_session(self) -> None:
        ami = MagicMock()
        ami.connected = True
        ami.authenticated = True
        ami.pjsip_endpoint.return_value = []
        svc = DiagnosticsService(ami=ami)

        svc.endpoint_details("1001")

        ami.connect.assert_not_called()
        ami.login.assert_not_called()


class TestDiagnosticsServiceAsteriskSummary:
    def test_summary_without_ami(self) -> None:
        svc = DiagnosticsService(ami=None)
        summary = svc.asterisk_summary()
        assert summary.active_calls == 0
        assert summary.endpoint_total == 0

    def test_summary_lazily_connects_and_logs_in(self) -> None:
        ami = MagicMock()
        ami.connected = False
        ami.authenticated = False
        ami.core_status.return_value = SystemInfo(asterisk_version="20.6.0", active_calls=0)
        ami.pjsip_endpoints.return_value = []
        ami.run_action_with_events.return_value = []

        DiagnosticsService(ami=ami).asterisk_summary()

        ami.connect.assert_called_once_with()
        ami.login.assert_called_once_with(events=False)

    def test_summary_with_ami(self) -> None:
        ami = MagicMock()
        ami.core_status.return_value = SystemInfo(asterisk_version="20.6.0", active_calls=3)
        ami.pjsip_endpoints.return_value = [
            Device(name="1001", extension="1001", state=DeviceState.REGISTERED),
            Device(name="1002", extension="1002", state=DeviceState.UNREGISTERED),
            Device(name="1003", extension="1003", state=DeviceState.UNAVAILABLE),
        ]
        ami.run_action_with_events.return_value = [
            {"Event": "CoreShowChannel"},
            {"Event": "CoreShowChannel"},
            {"Event": "CoreShowChannelsComplete"},
        ]

        svc = DiagnosticsService(ami=ami)
        summary = svc.asterisk_summary()

        assert summary.version == "20.6.0"
        assert summary.active_calls == 3
        assert summary.active_channels == 2
        assert summary.endpoint_total == 3
        assert summary.endpoint_registered == 1
        assert summary.endpoint_unregistered == 1
        assert summary.endpoint_unavailable == 1


class TestDiagnosticsServiceCDRGraphQL:
    """FreePBX 16 serves CDR via GraphQL fetchAllCdrs — the REST /cdr resource
    does not exist there (every call 404s, verified live 2026-07-12)."""

    @staticmethod
    def _gql_client(
        rows: list[dict[str, Any]],
        total: int | None = None,
    ) -> MagicMock:
        client = MagicMock()
        client.graphql.query.return_value = {
            "fetchAllCdrs": {
                "totalCount": total if total is not None else len(rows),
                "cdrs": rows,
            },
        }
        return client

    def test_graphql_is_primary_path(self) -> None:
        fixture = _load_fixture("cdr_graphql.json")
        client = MagicMock()
        client.graphql.query.return_value = fixture

        svc = DiagnosticsService(client=client)
        result = svc.cdr(limit=20)

        assert result.total == 2
        assert result.truncated is False
        item = result.items[0]
        assert item.unique_id == "fixture-call-001"
        assert item.linked_id == "fixture-linked-001"
        assert item.source == "2001"
        assert item.destination == "105"
        assert item.duration == 42
        assert item.billsec == 40
        assert item.disposition == "ANSWERED"
        assert item.recording_file == "fixture-105-2001-20260711-101112.wav"
        assert item.raw["recordingfile"] == item.recording_file
        assert isinstance(item.timestamp, datetime)
        assert item.timestamp == datetime(2026, 7, 11, 10, 11, 12, tzinfo=timezone.utc)

    def test_explicit_cdr_offset_is_preserved(self) -> None:
        client = self._gql_client(
            [
                {
                    "uniqueid": "offset",
                    "calldate": "2026-07-11T06:11:12-04:00",
                },
            ],
        )

        item = DiagnosticsService(client=client).cdr(limit=1).items[0]

        assert item.timestamp is not None
        assert item.timestamp.isoformat() == "2026-07-11T06:11:12-04:00"

    def test_extension_filter_is_client_side(self) -> None:
        client = self._gql_client(
            [
                {"uniqueid": "1", "calldate": "2026-07-11 10:00:00", "src": "2001", "dst": "105"},
                {"uniqueid": "2", "calldate": "2026-07-11 10:01:00", "src": "3003", "dst": "104"},
            ],
        )

        svc = DiagnosticsService(client=client)
        result = svc.cdr(extension="2001", limit=20)

        assert [i.unique_id for i in result.items] == ["1"]

    def test_iso_dates_are_normalized_for_graphql(self) -> None:
        client = self._gql_client([])

        svc = DiagnosticsService(client=client)
        svc.cdr(date_from="2026-07-10T15:38:51+00:00", date_to="2026-07-11", limit=5)

        variables = client.graphql.query.call_args.args[1]
        assert variables["startDate"] == "2026-07-10 15:38:51"
        assert variables["endDate"] == "2026-07-11 00:00:00"
        assert variables["first"] == 5

    def test_graphql_failure_propagates_without_dead_rest_retry(self) -> None:
        client = MagicMock()
        client.graphql.query.side_effect = ConnectionError("gql down")

        svc = DiagnosticsService(client=client)
        try:
            svc.cdr(limit=20)
        except ConnectionError:
            pass
        else:
            raise AssertionError("expected the GraphQL error to propagate")

    def test_truncation_reflects_total_count(self) -> None:
        rows = [
            {"uniqueid": str(i), "calldate": "2026-07-11 10:00:00", "src": "1", "dst": "2"}
            for i in range(3)
        ]
        client = self._gql_client(rows, total=50)

        svc = DiagnosticsService(client=client)
        result = svc.cdr(limit=3)

        assert result.total == 50
        assert result.truncated is True

    def test_no_client_at_all_raises(self) -> None:
        svc = DiagnosticsService()
        try:
            svc.cdr()
        except RuntimeError as exc:
            assert "required for CDR queries" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
