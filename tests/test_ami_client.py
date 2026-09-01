"""Tests for AMIClient protocol handling."""

from __future__ import annotations

import socket
import warnings
from unittest.mock import MagicMock, patch

import pytest

from pyfreepbx.clients.ami import AMIClient, _parse_device_state, _parse_sip_status, _parse_uptime
from pyfreepbx.config import AMIConfig
from pyfreepbx.exceptions import AMIAuthError, AMIConnectionError, AMIError
from pyfreepbx.models.call import ActiveChannel
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
        with (
            patch("socket.create_connection", side_effect=OSError("refused")),
            pytest.raises(AMIConnectionError, match="refused"),
        ):
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

    def test_connect_banner_failure_invalidates_session(self, client: AMIClient) -> None:
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recv.return_value = b""
        with (
            patch("socket.create_connection", return_value=mock_sock),
            pytest.raises(AMIConnectionError, match="closed by remote host"),
        ):
            client.connect()

        mock_sock.close.assert_called_once_with()
        assert not client.connected
        assert not client.authenticated

    def test_disconnect_idempotent(self, client: AMIClient) -> None:
        # Disconnecting when not connected should not raise
        client.disconnect()
        client.disconnect()
        assert not client.connected

    def test_reconnect_replaces_and_authenticates_session(self, client: AMIClient) -> None:
        old_sock = _make_connected(client)
        old_sock.recv.return_value = b""  # session dropped before reconnect
        new_sock = MagicMock(spec=socket.socket)
        new_sock.recv.side_effect = [
            b"Asterisk Call Manager/6.0.0\r\n",
            b"Response: Success\r\nMessage: Authentication accepted\r\n\r\n",
        ]

        with patch("socket.create_connection", return_value=new_sock):
            response = client.reconnect()

        old_sock.close.assert_called_once_with()
        assert response["Response"] == "Success"
        assert client.connected
        assert client.authenticated


class TestLogin:
    def test_login_success(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        client._authenticated = False  # not yet

        response_bytes = b"Response: Success\r\nMessage: Authentication accepted\r\n\r\n"
        mock_sock.recv.return_value = response_bytes

        result = client.login()
        assert result["Response"] == "Success"
        assert client.authenticated
        sent = mock_sock.sendall.call_args.args[0].decode("utf-8")
        assert "Events: on\r\n" in sent

    def test_login_can_disable_unsolicited_events(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        client._authenticated = False
        mock_sock.recv.return_value = (
            b"Response: Success\r\nMessage: Authentication accepted\r\n\r\n"
        )

        client.login(events=False)

        sent = mock_sock.sendall.call_args.args[0].decode("utf-8")
        assert "Events: off\r\n" in sent

    def test_login_failure(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        client._authenticated = False

        response_bytes = b"Response: Error\r\nMessage: Authentication failed\r\n\r\n"
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
            b"Response: Success\r\nCoreVersion: 18.17.0\r\nCoreCurrentCalls: 0\r\n\r\n"
        )

        info = client.core_status()
        assert info.uptime_seconds == 0
        assert info.reload_seconds == 0

    def test_queue_summary(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\n\r\n"
            b"Event: QueueSummary\r\nQueue: support\r\nLoggedIn: 3\r\n"
            b"Available: 2\r\nCallers: 1\r\n\r\n"
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
            b"Event: EndpointList\r\nObjectName: 1001\r\n"
            b"DeviceState: Not in use\r\nUserAgent: Yealink T46U\r\n\r\n"
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
            b"Event: PeerEntry\r\nObjectName: 2001\r\nStatus: OK (12 ms)\r\n"
            b"IPaddress: 10.0.0.5\r\n\r\n"
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

    def test_multi_event_action_is_bounded(self, config: AMIConfig) -> None:
        config.max_events = 2
        client = AMIClient(config)
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\n\r\n"
            b"Event: QueueSummary\r\nQueue: one\r\n\r\n"
            b"Event: QueueSummary\r\nQueue: two\r\n\r\n"
            b"Event: QueueSummary\r\nQueue: three\r\n\r\n"
        )

        with pytest.raises(AMIError, match="2-event limit"):
            client.run_action_with_events("QueueSummary")
        assert not client.connected
        with pytest.raises(AMIError, match="Not connected"):
            client.run_action("Ping")

    def test_command_is_not_allowlisted(
        self, client: AMIClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: Success\r\n\r\n"

        client.run_action("Command", Command="core show version")

        assert "Running non-allowlisted AMI action: Command" in caplog.text

    def test_oversized_frame_invalidates_session(self) -> None:
        config = AMIConfig(
            host="ami.test",
            username="admin",
            secret="secret",
            max_frame_bytes=16,
        )
        client = AMIClient(config)
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: " + (b"x" * 32)

        with pytest.raises(AMIError, match="16-byte limit"):
            client.run_action("Ping")
        assert not client.connected

    def test_action_transport_timeout_invalidates_without_replay(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.side_effect = TimeoutError("response timed out")

        with pytest.raises(TimeoutError, match="response timed out"):
            client.run_action("QueuePause", Queue="support", Interface="PJSIP/2001")

        assert mock_sock.sendall.call_count == 1
        assert not client.connected
        assert not client.authenticated
        with pytest.raises(AMIError, match="Not connected"):
            client.run_action("Ping")

    def test_multi_event_timeout_invalidates_session(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.side_effect = [
            b"Response: Success\r\n\r\n",
            TimeoutError("event stream timed out"),
        ]

        with pytest.raises(TimeoutError, match="event stream timed out"):
            client.run_action_with_events("QueueSummary")

        assert not client.connected
        assert not client.authenticated


class TestQueuePause:
    def test_queue_pause_sends_typed_action(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: Success\r\n\r\n"

        client.queue_pause(
            queue="support",
            interface="PJSIP/2001",
            paused=True,
            reason="break",
        )

        sent = mock_sock.sendall.call_args[0][0].decode("utf-8")
        assert sent.startswith("Action: QueuePause\r\n")
        assert "Queue: support\r\n" in sent
        assert "Interface: PJSIP/2001\r\n" in sent
        assert "Paused: true\r\n" in sent
        assert "Reason: break\r\n" in sent

    def test_generic_queue_pause_is_not_allowlisted(
        self, client: AMIClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: Success\r\n\r\n"

        client.run_action("QueuePause", Queue="support", Interface="PJSIP/2001")

        assert "Running non-allowlisted AMI action: QueuePause" in caplog.text

    def test_queue_pause_rejection_raises(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: Error\r\nMessage: Member not found\r\n\r\n"

        with pytest.raises(AMIError, match="Member not found"):
            client.queue_pause(queue="support", interface="PJSIP/404", paused=False)

    def test_requires_auth(self, client: AMIClient) -> None:
        with pytest.raises(AMIError, match="Not connected"):
            client.run_action("Ping")


class TestOriginate:
    def test_originate_success_returns_action_id(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Success\r\nMessage: Originate successfully queued\r\n\r\n"
        )

        result = client.originate(
            channel="Local/2001@from-internal",
            extension="1500",
            caller_id="Visitor 7",
            action_id="abc123",
        )

        assert result.action_id == "abc123"
        assert result.queued is True
        assert result.channel == "Local/2001@from-internal"

        sent = mock_sock.sendall.call_args[0][0].decode("utf-8")
        assert sent.startswith("Action: Originate\r\n")
        # Issued async so AMI returns immediately with our ActionID (the call_ref).
        assert "Async: true\r\n" in sent
        assert "ActionID: abc123\r\n" in sent
        assert "CallerID: Visitor 7\r\n" in sent

    def test_originate_generates_action_id_when_absent(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: Success\r\n\r\n"

        result = client.originate(channel="Local/2001@from-internal", extension="1500")
        assert result.action_id  # non-empty generated id
        sent = mock_sock.sendall.call_args[0][0].decode("utf-8")
        assert f"ActionID: {result.action_id}\r\n" in sent

    def test_originate_encodes_channel_variables(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = b"Response: Success\r\n\r\n"

        client.originate(
            channel="Local/2001@from-internal",
            extension="1500",
            variables={"VISITOR": "7", "GATE": "north"},
        )
        sent = mock_sock.sendall.call_args[0][0].decode("utf-8")
        assert "Variable: VISITOR=7,GATE=north\r\n" in sent

    def test_originate_vendor_refusal_raises_amierror(self, client: AMIClient) -> None:
        mock_sock = _make_connected(client)
        mock_sock.recv.return_value = (
            b"Response: Error\r\nMessage: Extension does not exist\r\n\r\n"
        )

        with pytest.raises(AMIError, match="Extension does not exist"):
            client.originate(channel="Local/2001@from-internal", extension="9999")

    def test_originate_requires_auth(self, client: AMIClient) -> None:
        with pytest.raises(AMIError, match="Not connected"):
            client.originate(channel="Local/2001@from-internal", extension="1500")


class TestHangup:
    def test_active_channels_maps_and_filters_linked_id(self, client: AMIClient) -> None:
        _make_connected(client)
        events = [
            {
                "Event": "CoreShowChannel",
                "Channel": "PJSIP/door-0001",
                "Uniqueid": "1700.1",
                "Linkedid": "1700.1",
                "ChannelStateDesc": "Up",
                "CallerIDNum": "door",
                "ConnectedLineNum": "600",
            },
            {
                "Event": "CoreShowChannel",
                "Channel": "PJSIP/other-0002",
                "Uniqueid": "1700.2",
                "Linkedid": "1700.2",
            },
        ]
        with patch.object(client, "_collect_events", return_value=events):
            result = client.active_channels(linked_id="1700.1")

        assert result == [
            ActiveChannel(
                channel="PJSIP/door-0001",
                unique_id="1700.1",
                linked_id="1700.1",
                state="Up",
                caller_id_num="door",
                connected_line_num="600",
            )
        ]

    def test_hangup_revalidates_exact_channel_before_write(self, client: AMIClient) -> None:
        _make_connected(client)
        channels = [
            ActiveChannel(
                channel="PJSIP/door-0001",
                unique_id="1700.1",
                linked_id="1700.1",
            )
        ]
        with (
            patch.object(client, "active_channels", return_value=channels),
            patch.object(
                client,
                "_send_action",
                return_value={"Response": "Success", "Message": "Channel Hungup"},
            ) as send,
        ):
            result = client.hangup_channel(
                channel="PJSIP/door-0001",
                linked_id="1700.1",
            )

        assert result.accepted is True
        send.assert_called_once_with("Hangup", Channel="PJSIP/door-0001")

    def test_hangup_stale_channel_does_not_write(self, client: AMIClient) -> None:
        _make_connected(client)
        with (
            patch.object(client, "active_channels", return_value=[]),
            patch.object(client, "_send_action") as send,
        ):
            result = client.hangup_channel(
                channel="PJSIP/door-stale",
                linked_id="1700.1",
            )

        assert result.attempted is False
        assert result.response == "NotFound"
        send.assert_not_called()

    @pytest.mark.parametrize("channel,linked_id", [("", "1700.1"), ("PJSIP/door", "")])
    def test_hangup_requires_both_exact_identifiers(
        self,
        client: AMIClient,
        channel: str,
        linked_id: str,
    ) -> None:
        _make_connected(client)
        with pytest.raises(ValueError, match="channel and linked_id are required"):
            client.hangup_channel(channel=channel, linked_id=linked_id)


class TestStateHelpers:
    def test_parse_device_state(self) -> None:
        assert _parse_device_state("Not in use") == DeviceState.REGISTERED
        assert _parse_device_state("InUse") == DeviceState.REGISTERED
        assert _parse_device_state("Unavailable") == DeviceState.UNAVAILABLE
        assert _parse_device_state("UNKNOWN") == DeviceState.UNKNOWN
        assert _parse_device_state("Ringing") == DeviceState.REGISTERED
        assert _parse_device_state("") == DeviceState.UNKNOWN
        # An endpoint Asterisk cannot find is not a registered endpoint.
        assert _parse_device_state("not_found") == DeviceState.UNREGISTERED

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
