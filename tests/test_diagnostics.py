"""Tests for pyfreepbx DiagnosticsService."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.system import SystemInfo
from pyfreepbx.services.diagnostics import DiagnosticsService


class TestDiagnosticsServiceCDR:
    def test_cdr_normalizes_rows(self) -> None:
        rest = MagicMock()
        rest.get.return_value = {
            "items": [
                {
                    "calldate": "2026-04-18 10:11:12",
                    "src": "1001",
                    "dst": "1002",
                    "duration": "30",
                    "billsec": "25",
                    "disposition": "ANSWERED",
                    "queue": "400",
                },
            ],
        }

        svc = DiagnosticsService(rest=rest)
        result = svc.cdr(extension="1001", limit=20)

        assert result.total == 1
        assert result.truncated is False
        assert result.items[0].source == "1001"
        assert result.items[0].destination == "1002"
        assert result.items[0].duration == 30
        assert result.items[0].disposition == "ANSWERED"
        assert result.items[0].queue == "400"
        assert isinstance(result.items[0].timestamp, datetime)

    def test_cdr_enforces_hard_limit(self) -> None:
        rest = MagicMock()
        rest.get.return_value = [{"src": str(i), "dst": "2000"} for i in range(600)]

        svc = DiagnosticsService(rest=rest)
        result = svc.cdr(limit=1000)

        assert len(result.items) == 500
        assert result.total == 600
        assert result.truncated is True


class TestDiagnosticsServiceLogs:
    def test_logs_normalize_text_payload(self) -> None:
        rest = MagicMock()
        rest.get.return_value = "line one\nline two\n"

        svc = DiagnosticsService(rest=rest)
        result = svc.asterisk_logs(limit=50)

        assert result.total == 2
        assert result.lines[0].message == "line one"
        assert result.lines[1].message == "line two"


class TestDiagnosticsServiceEndpointDetails:
    def test_endpoint_details_without_ami(self) -> None:
        svc = DiagnosticsService(rest=MagicMock(), ami=None)
        details = svc.endpoint_details("1001")
        assert details["state"] == "unknown"
        assert details["events"] == []

    def test_endpoint_details_with_ami(self) -> None:
        ami = MagicMock()
        ami.pjsip_endpoint.return_value = [
            {"Event": "EndpointDetail", "DeviceState": "Unavailable"},
            {"Event": "ContactStatusDetail", "URI": "sip:10.0.0.55:5060", "UserAgent": "Yealink"},
        ]
        svc = DiagnosticsService(rest=MagicMock(), ami=ami)
        details = svc.endpoint_details("1001")
        assert details["state"] == "unavailable"
        assert details["ip_address"] == "10.0.0.55"
        assert details["user_agent"] == "Yealink"


class TestDiagnosticsServiceAsteriskSummary:
    def test_summary_without_ami(self) -> None:
        svc = DiagnosticsService(rest=MagicMock(), ami=None)
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

        svc = DiagnosticsService(rest=MagicMock(), ami=ami)
        summary = svc.asterisk_summary()

        assert summary.version == "20.6.0"
        assert summary.active_calls == 3
        assert summary.active_channels == 2
        assert summary.endpoint_total == 3
        assert summary.endpoint_registered == 1
        assert summary.endpoint_unregistered == 1
        assert summary.endpoint_unavailable == 1
