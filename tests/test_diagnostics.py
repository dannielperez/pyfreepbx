"""Tests for pyfreepbx DiagnosticsService."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.system import SystemInfo
from pyfreepbx.services.diagnostics import DiagnosticsService


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


class TestDiagnosticsServiceAsteriskSummary:
    def test_summary_without_ami(self) -> None:
        svc = DiagnosticsService(ami=None)
        summary = svc.asterisk_summary()
        assert summary.active_calls == 0
        assert summary.endpoint_total == 0

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
    def _gql_client(rows, total=None):
        client = MagicMock()
        client.graphql.query.return_value = {
            "fetchAllCdrs": {
                "totalCount": total if total is not None else len(rows),
                "cdrs": rows,
            },
        }
        return client

    def test_graphql_is_primary_path(self) -> None:
        client = self._gql_client(
            [
                {
                    "uniqueid": "175.99",
                    "calldate": "2026-07-11 10:11:12",
                    "src": "2001",
                    "dst": "105",
                    "duration": 42,
                    "billsec": 40,
                    "disposition": "ANSWERED",
                    "recordingfile": "external-105-2001-20260711-101112.wav",
                    "linkedid": "175.99",
                },
            ],
        )

        svc = DiagnosticsService(client=client)
        result = svc.cdr(limit=20)

        assert result.total == 1
        item = result.items[0]
        assert item.unique_id == "175.99"
        assert item.source == "2001"
        assert item.destination == "105"
        assert item.recording_file == "external-105-2001-20260711-101112.wav"
        assert item.raw["recordingfile"] == item.recording_file
        assert isinstance(item.timestamp, datetime)

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
            assert "client is required" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
