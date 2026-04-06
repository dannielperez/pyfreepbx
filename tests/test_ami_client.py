"""Tests for AMIClient protocol handling."""

from __future__ import annotations

import socket
import warnings
from unittest.mock import MagicMock, patch

import pytest

from pyfreepbx.clients.ami import AMIClient, _parse_device_state, _parse_sip_status, _parse_uptime
from pyfreepbx.config import AMIConfig
from pyfreepbx.exceptions import AMIAuthError, AMIConnectionError, AMIError
from pyfreepbx.models.device import DeviceState


@pytest.fixture
def config() -> AMIConfig:
    return AMIConfig(host="ami.test", port=5038, username="admin", secret="secret")


@pytest.fixture
def client(config: AMIConfig) -> AMIClient:
    return AMIClient(config)


def _make_connected(client: AMIClient) -> MagicMock:
    """Helper: attach a mock socket and mark the client as connected + authed."""
    mock_sock = MagicMock(spec=socket.socket)
    client._sock = mock_sock
    client._connected = True
    client._authenticated = True
    return mock_sock


class TestConnection:
    def test_connect_failure(self, client: AMIClient) -> None:
        with patch("socket.create_connection", side_effect=OSError("refused")):
            with pytest.raises(AMIConnectionError, match="refused"):
                client.connect()
        assert not client.connected

    def test_connect_reads_banner(self, client: AMIClient) -> None:
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recv.return_value = b"Asterisk Call Manager/6.0.0\r\n"
        with patch("socket.create_connection", return_value=mock_sock):
            banner = client.connect()
        assert banner == "Asterisk Call Manager/6.0.0"
        assert client.connected
        assert client.banner == banner
        assert not client.authenticated

    def test_disconnect_idempotent(self, client: AMIClient) -> None:
        # Disconnecting when not connected should not raise
        client.disconnect()
        client.disconnect()
        assert not client.connected


class TestLogin:
    def test_login_success(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        client._authenticated = False  # not yet

        response_bytes = (
            b"Response: Success\r\n"
            b"Message: Authentication accepted\r\n"
            b"\r\n"
        )
        mock_sock.recv.return_value = response_bytes

        result = client.login()
        assert result["Response"] == "Success"
        assert client.authenticated

    def test_login_failure(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        client._authenticated = False

        response_bytes = (
            b"Response: Error\r\n"
            b"Message: Authentication failed\r\n"
            b"\r\n"
        )
        mock_sock.recv.return_value = response_bytes

        with pytest.raises(AMIAuthError, match="Authentication failed"):
            client.login()
        assert not client.authenticated

    def test_login_requires_connection(self, client: AMIClient) -> None:
        with pytest.raises(AMIError, match="Not connected"):
            client.login()


class TestPing:
    def test_ping_success(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: Success\r\nPing: Pong\r\n\r\n"

        assert client.ping() is True

    def test_ping_returns_false_on_failure(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.side_effect = AMIError("disconnected")

        assert client.ping() is False


class TestTypedQueries:
    def test_core_status(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\n"
            b"CoreVersion: 18.17.0\r\n"
            b"AMIversion: 6.0.0\r\n"
            b"CoreCurrentCalls: 3\r\n"
            b"CoreStartupDate: 2026-04-01\r\n"
            b"CoreStartupTime: 10:00:00\r\n"
            b"CoreReloadDate: 2026-04-05\r\n"
            b"CoreReloadTime: 08:00:00\r\n"
            b"\r\n"
        )

        info = client.core_status()
        assert info.asterisk_version == "18.17.0"
        assert info.ami_version == "6.0.0"
        assert info.active_calls == 3
        # uptime_seconds should be derived from startup date/time
        assert info.uptime_seconds > 0
        # reload_seconds should be derived from reload date/time
        assert info.reload_seconds > 0
        assert info.uptime_seconds >= info.reload_seconds

    def test_core_status_missing_dates(self, client: AMIClient) -> None:
        """When AMI doesn't return date fields, uptime defaults to 0."""
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\n"
            b"CoreVersion: 18.17.0\r\n"
            b"CoreCurrentCalls: 0\r\n"
            b"\r\n"
        )

        info = client.core_status()
        assert info.uptime_seconds == 0
        assert info.reload_seconds == 0

    def test_queue_summary(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\n\r\n"
            b"Event: QueueSummary\r\nQueue: support\r\nLoggedIn: 3\r\nAvailable: 2\r\nCallers: 1\r\n\r\n"
            b"Event: QueueSummaryComplete\r\nEventList: Complete\r\n\r\n"
        )

        stats = client.queue_summary()
        assert len(stats) == 1
        assert stats[0].queue == "support"
        assert stats[0].logged_in == 3
        assert stats[0].available == 2

    def test_queue_summary_with_filter(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\n\r\n"
            b"Event: QueueSummary\r\nQueue: sales\r\nLoggedIn: 5\r\n\r\n"
            b"Event: QueueSummaryComplete\r\nEventList: Complete\r\n\r\n"
        )

        stats = client.queue_summary(queue="sales")
        assert len(stats) == 1
        assert stats[0].queue == "sales"

        # Verify Queue param was sent
        sent = mock_sock.sendall.call_args[0][0].decode("utf-8")
        assert "Queue: sales" in sent

    def test_pjsip_endpoints(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\n\r\n"
            b"Event: EndpointList\r\nObjectName: 1001\r\nDeviceState: Not in use\r\nUserAgent: Yealink T46U\r\n\r\n"
            b"Event: EndpointList\r\nObjectName: 1002\r\nDeviceState: Unavailable\r\n\r\n"
            b"Event: EndpointListComplete\r\nEventList: Complete\r\n\r\n"
        )

        devices = client.pjsip_endpoints()
        assert len(devices) == 2
        assert devices[0].name == "1001"
        assert devices[0].state == DeviceState.REGISTERED
        assert devices[0].user_agent == "Yealink T46U"
        assert devices[1].name == "1002"
        assert devices[1].state == DeviceState.UNAVAILABLE

    def test_sip_peers(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\n\r\n"
            b"Event: PeerEntry\r\nObjectName: 2001\r\nStatus: OK (12 ms)\r\nIPaddress: 10.0.0.5\r\n\r\n"
            b"Event: PeerEntry\r\nObjectName: 2002\r\nStatus: UNREACHABLE\r\n\r\n"
            b"Event: PeerlistComplete\r\nEventList: Complete\r\n\r\n"
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            devices = client.sip_peers()

        assert len(devices) == 2
        assert devices[0].name == "SIP/2001"
        assert devices[0].state == DeviceState.REGISTERED
        assert devices[0].ip_address == "10.0.0.5"
        assert devices[1].state == DeviceState.UNREGISTERED

        # Verify DeprecationWarning was emitted
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "sip_peers" in str(w[0].message)
        assert "pjsip_endpoints" in str(w[0].message)


class TestRunAction:
    def test_send_action_format(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: Success\r\nPing: Pong\r\n\r\n"

        result = client.run_action("Ping")
        assert result["Response"] == "Success"

        sent = mock_sock.sendall.call_args[0][0].decode("utf-8")
        assert sent.startswith("Action: Ping\r\n")
        assert sent.endswith("\r\n\r\n")

    def test_run_action_with_events(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\n\r\n"
            b"Event: QueueSummary\r\nQueue: support\r\nLoggedIn: 3\r\n\r\n"
            b"Event: QueueSummary\r\nQueue: sales\r\nLoggedIn: 5\r\n\r\n"
            b"Event: QueueSummaryComplete\r\nEventList: Complete\r\n\r\n"
        )

        events = client.run_action_with_events("QueueSummary")
        assert len(events) == 2
        assert events[0]["Queue"] == "support"
        assert events[1]["Queue"] == "sales"

    def test_requires_auth(self, client: AMIClient) -> None:
        with pytest.raises(AMIError, match="Not connected"):
            client.run_action("Ping")


class TestStateHelpers:
    def test_parse_device_state(self) -> None:
        assert _parse_device_state("Not in use") == DeviceState.REGISTERED
        assert _parse_device_state("InUse") == DeviceState.REGISTERED
        assert _parse_device_state("Unavailable") == DeviceState.UNAVAILABLE
        assert _parse_device_state("UNKNOWN") == DeviceState.UNKNOWN
        assert _parse_device_state("Ringing") == DeviceState.REGISTERED
        assert _parse_device_state("") == DeviceState.UNKNOWN

    def test_parse_sip_status(self) -> None:
        assert _parse_sip_status("OK (1 ms)") == DeviceState.REGISTERED
        assert _parse_sip_status("Lagged (123 ms)") == DeviceState.REGISTERED
        assert _parse_sip_status("UNREACHABLE") == DeviceState.UNREGISTERED
        assert _parse_sip_status("UNKNOWN") == DeviceState.UNKNOWN
        assert _parse_sip_status("Unmonitored") == DeviceState.UNKNOWN

    def test_parse_uptime_valid(self) -> None:
        from datetime import datetime, timedelta
        past = datetime.now() - timedelta(hours=2)
        date_str = past.strftime("%Y-%m-%d")
        time_str = past.strftime("%H:%M:%S")
        # Should be roughly 7200 seconds, allow some tolerance
        result = _parse_uptime(date_str, time_str)
        assert 7100 < result < 7300

    def test_parse_uptime_empty_strings(self) -> None:
        assert _parse_uptime("", "") == 0
        assert _parse_uptime("2026-04-01", "") == 0
        assert _parse_uptime("", "10:00:00") == 0

    def test_parse_uptime_invalid_format(self) -> None:
        assert _parse_uptime("not-a-date", "not-a-time") == 0


class TestContextManager:
    def test_context_manager_calls_disconnect(self, config: AMIConfig) -> None:
        client = AMIClient(config)
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: Goodbye\r\n\r\n"

        with client:
            assert client.connected
        assert not client.connected
