"""Tests for HealthService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.health import HealthStatus
from pyfreepbx.models.queue import QueueStats
from pyfreepbx.models.system import SystemInfo
from pyfreepbx.services.health import HealthService


class TestSummary:
    def test_graphql_only(self, mock_freepbx_client: MagicMock) -> None:
        """Without AMI, summary should contain only the GraphQL check."""
        mock_freepbx_client.graphql.query.return_value = {"__typename": "Query"}

        svc = HealthService(mock_freepbx_client, ami=None)
        result = svc.summary()

        assert len(result.checks) == 1
        assert result.checks[0].name == "graphql"
        assert result.checks[0].status == HealthStatus.OK
        assert result.overall == HealthStatus.OK

    def test_graphql_down(self, mock_freepbx_client: MagicMock) -> None:
        mock_freepbx_client.graphql.query.side_effect = ConnectionError("refused")

        svc = HealthService(mock_freepbx_client, ami=None)
        result = svc.summary()

        assert result.checks[0].status == HealthStatus.DOWN
        assert "refused" in result.checks[0].detail
        assert result.overall == HealthStatus.DOWN

    def test_both_interfaces(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_freepbx_client.graphql.query.return_value = {"__typename": "Query"}
        mock_ami.ping.return_value = True

        svc = HealthService(mock_freepbx_client, mock_ami)
        result = svc.summary()

        assert len(result.checks) == 2
        names = {c.name for c in result.checks}
        assert names == {"graphql", "ami"}
        assert result.overall == HealthStatus.OK

    def test_ami_degraded(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_freepbx_client.graphql.query.return_value = {"__typename": "Query"}
        mock_ami.ping.return_value = False

        svc = HealthService(mock_freepbx_client, mock_ami)
        result = svc.summary()

        ami_check = next(c for c in result.checks if c.name == "ami")
        assert ami_check.status == HealthStatus.DEGRADED
        assert result.overall == HealthStatus.DEGRADED


class TestPbxInfo:
    def test_returns_system_info(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        expected = SystemInfo(asterisk_version="18.17.0", active_calls=3)
        mock_ami.core_status.return_value = expected

        svc = HealthService(mock_freepbx_client, mock_ami)
        result = svc.pbx_info()

        assert result is not None
        assert result.asterisk_version == "18.17.0"
        assert result.active_calls == 3

    def test_none_without_ami(self, mock_freepbx_client: MagicMock) -> None:
        svc = HealthService(mock_freepbx_client, ami=None)
        assert svc.pbx_info() is None

    def test_none_on_ami_error(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.core_status.side_effect = ConnectionError("timeout")

        svc = HealthService(mock_freepbx_client, mock_ami)
        assert svc.pbx_info() is None


class TestEndpointSummary:
    @staticmethod
    def _devices() -> list[Device]:
        return [
            Device(name="1001", state=DeviceState.REGISTERED),
            Device(name="1002", state=DeviceState.REGISTERED),
            Device(name="1003", state=DeviceState.UNREGISTERED),
            Device(name="1004", state=DeviceState.UNAVAILABLE),
            Device(name="1005", state=DeviceState.UNKNOWN),
        ]

    def test_counts_by_state(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.pjsip_endpoints.return_value = self._devices()

        svc = HealthService(mock_freepbx_client, mock_ami)
        result = svc.endpoint_summary()

        assert result is not None
        assert result.total == 5
        assert result.registered == 2
        assert result.unregistered == 1
        assert result.unavailable == 1
        assert result.unknown == 1

    def test_none_without_ami(self, mock_freepbx_client: MagicMock) -> None:
        svc = HealthService(mock_freepbx_client, ami=None)
        assert svc.endpoint_summary() is None

    def test_none_on_error(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.pjsip_endpoints.side_effect = RuntimeError("boom")
        svc = HealthService(mock_freepbx_client, mock_ami)
        assert svc.endpoint_summary() is None


class TestUnregisteredEndpoints:
    def test_filters_offline(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        devices = [
            Device(name="1001", state=DeviceState.REGISTERED),
            Device(name="1002", state=DeviceState.UNREGISTERED),
            Device(name="1003", state=DeviceState.UNAVAILABLE),
        ]
        mock_ami.pjsip_endpoints.return_value = devices

        svc = HealthService(mock_freepbx_client, mock_ami)
        result = svc.unregistered_endpoints()

        assert result is not None
        assert len(result) == 2
        names = {d.name for d in result}
        assert names == {"1002", "1003"}

    def test_empty_when_all_registered(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.pjsip_endpoints.return_value = [
            Device(name="1001", state=DeviceState.REGISTERED),
        ]
        svc = HealthService(mock_freepbx_client, mock_ami)
        result = svc.unregistered_endpoints()
        assert result == []

    def test_none_without_ami(self, mock_freepbx_client: MagicMock) -> None:
        svc = HealthService(mock_freepbx_client, ami=None)
        assert svc.unregistered_endpoints() is None


class TestQueueOverview:
    def test_returns_stats(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        expected = [
            QueueStats(queue="support", logged_in=3, available=2, callers=1),
            QueueStats(queue="sales", logged_in=5, available=4, callers=0),
        ]
        mock_ami.queue_summary.return_value = expected

        svc = HealthService(mock_freepbx_client, mock_ami)
        result = svc.queue_overview()

        assert result is not None
        assert len(result) == 2
        assert result[0].queue == "support"

    def test_none_without_ami(self, mock_freepbx_client: MagicMock) -> None:
        svc = HealthService(mock_freepbx_client, ami=None)
        assert svc.queue_overview() is None

    def test_none_on_error(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.queue_summary.side_effect = ConnectionError("lost")
        svc = HealthService(mock_freepbx_client, mock_ami)
        assert svc.queue_overview() is None
