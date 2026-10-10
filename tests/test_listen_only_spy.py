"""Listen-only ChanSpy originate: exact target, fixed options, no widening."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from pyfreepbx.clients.ami import LISTEN_ONLY_SPY_OPTIONS, AMIClient, monitor_line_channel
from pyfreepbx.config import AMIConfig
from pyfreepbx.exceptions import AMIError
from pyfreepbx.models.call import ActiveChannel, ListenOnlySpyState

TARGET = "PJSIP/1901-0000002a"
LINKED = "1700000000.42"
MONITOR = "PJSIP/1905"


@pytest.fixture
def client() -> AMIClient:
    ami = AMIClient(AMIConfig(host="ami.test", port=5038, username="u", secret="s"))
    ami._sock = MagicMock(spec=socket.socket)
    ami._connected = True
    ami._authenticated = True
    return ami


def _live(state: str = "Up", channel: str = TARGET) -> list[ActiveChannel]:
    return [ActiveChannel(channel=channel, unique_id="u1", linked_id=LINKED, state=state)]


def test_options_are_listen_only() -> None:
    assert set(LISTEN_ONLY_SPY_OPTIONS) == set("uqbES")
    for forbidden in "dwWBrXceo":
        assert forbidden not in LISTEN_ONLY_SPY_OPTIONS


def test_originates_chanspy_for_the_exact_live_bridged_target(client: AMIClient) -> None:
    with (
        patch.object(client, "active_channels", return_value=_live()) as read,
        patch.object(
            client,
            "_send_action",
            return_value={"Response": "Success", "Message": "Originate successfully queued"},
        ) as send,
    ):
        result = client.start_listen_only_spy(
            monitor_channel=MONITOR,
            target_channel=TARGET,
            target_linked_id=LINKED,
            channel_id="uqmon-abc",
            account_code="uniqueos-monitor",
            caller_id="Supervisor listen",
            action_id="mon-1",
            variables={"UNIQUEOS_MONITOR": "abc-123"},
        )

    read.assert_called_once_with(linked_id=LINKED)
    send.assert_called_once_with(
        "Originate",
        Channel=MONITOR,
        Application="ChanSpy",
        Data=f"{TARGET},uqbES",
        Async="true",
        Timeout=20000,
        ActionID="mon-1",
        ChannelId="uqmon-abc",
        Account="uniqueos-monitor",
        CallerID="Supervisor listen",
        Variable="UNIQUEOS_MONITOR=abc-123",
    )
    assert result.queued is True
    assert result.options == "uqbES"
    assert result.channel_id == "uqmon-abc"


@pytest.mark.parametrize(
    ("channels", "expected"),
    [
        ([], "NotFound"),
        (_live() + _live(), "Ambiguous"),
        (_live(state="Ringing"), "NotBridged"),
        (_live(channel="PJSIP/1901-0000002b"), "NotFound"),
    ],
)
def test_stale_or_unbridged_target_sends_nothing(
    client: AMIClient,
    channels: list[ActiveChannel],
    expected: str,
) -> None:
    with (
        patch.object(client, "active_channels", return_value=channels),
        patch.object(client, "_send_action") as send,
    ):
        result = client.start_listen_only_spy(
            monitor_channel=MONITOR,
            target_channel=TARGET,
            target_linked_id=LINKED,
            channel_id="uqmon-1",
        )

    send.assert_not_called()
    assert result.attempted is False
    assert result.queued is False
    assert result.response == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"monitor_channel": "Local/1905@from-internal"},
        {"monitor_channel": "PJSIP/1905,w"},
        {"target_channel": "PJSIP/1901"},  # endpoint prefix would match any call
        {"target_channel": f"{TARGET},dB"},
        {"target_channel": f"{TARGET}\r\nAction: Hangup"},
        {"target_channel": "PJSIP/1905-0000002a"},  # the monitor's own line
        {"target_linked_id": "abc"},
        {"caller_id": "x\r\nAction: Originate"},
        {"variables": {"BAD-NAME": "1"}},
        {"variables": {"OK": "a,b"}},
        {"channel_id": ""},
        {"channel_id": "uqmon 1"},
        {"account_code": "mon\r\nAction: Hangup"},
    ],
)
def test_malformed_requests_are_refused_before_any_io(
    client: AMIClient,
    kwargs: dict,
) -> None:
    request = {
        "monitor_channel": MONITOR,
        "target_channel": TARGET,
        "target_linked_id": LINKED,
        "channel_id": "uqmon-1",
        **kwargs,
    }
    with (
        patch.object(client, "active_channels") as read,
        patch.object(client, "_send_action") as send,
        pytest.raises(ValueError),
    ):
        client.start_listen_only_spy(**request)

    read.assert_not_called()
    send.assert_not_called()


def test_vendor_refusal_raises(client: AMIClient) -> None:
    with (
        patch.object(client, "active_channels", return_value=_live()),
        patch.object(
            client,
            "_send_action",
            return_value={"Response": "Error", "Message": "Permission denied"},
        ),
        pytest.raises(AMIError, match="Permission denied"),
    ):
        client.start_listen_only_spy(
            monitor_channel=MONITOR,
            target_channel=TARGET,
            target_linked_id=LINKED,
            channel_id="uqmon-1",
        )


def test_requires_auth() -> None:
    ami = AMIClient(AMIConfig(host="ami.test", port=5038, username="u", secret="s"))
    with pytest.raises(AMIError, match="Not connected"):
        ami.start_listen_only_spy(
            monitor_channel=MONITOR,
            target_channel=TARGET,
            target_linked_id=LINKED,
            channel_id="uqmon-1",
        )


# ---------------------------------------------------------------------------
# Target resolution and stop
# ---------------------------------------------------------------------------


def _channel(name: str, *, linked: str = LINKED, unique: str = "u") -> ActiveChannel:
    return ActiveChannel(channel=name, unique_id=unique, linked_id=linked, state="Up")


def test_endpoint_channel_finds_the_operators_own_leg(client: AMIClient) -> None:
    live = [
        _channel("PJSIP/trunk-0000001f"),
        _channel("PJSIP/1901-0000002a"),
        _channel("PJSIP/19010-0000002b"),  # a longer endpoint name, not 1901
    ]
    with patch.object(client, "active_channels", return_value=live) as read:
        found = client.endpoint_channel(endpoint="1901", linked_id=LINKED)

    read.assert_called_once_with(linked_id=LINKED)
    assert found is not None
    assert found.channel == "PJSIP/1901-0000002a"


@pytest.mark.parametrize(
    "live",
    [
        [],
        [_channel("PJSIP/1901-0000002a"), _channel("PJSIP/1901-0000002c")],
    ],
    ids=["absent", "ambiguous"],
)
def test_endpoint_channel_never_guesses(client: AMIClient, live: list) -> None:
    with patch.object(client, "active_channels", return_value=live):
        assert client.endpoint_channel(endpoint="1901", linked_id=LINKED) is None


@pytest.mark.parametrize(
    ("endpoint", "linked_id"),
    [("19.*", LINKED), ("1901,x", LINKED), ("1901", "not-a-linkedid")],
)
def test_endpoint_channel_rejects_malformed_input(
    client: AMIClient,
    endpoint: str,
    linked_id: str,
) -> None:
    with (
        patch.object(client, "active_channels") as read,
        pytest.raises(ValueError),
    ):
        client.endpoint_channel(endpoint=endpoint, linked_id=linked_id)
    read.assert_not_called()


def test_stop_hangs_up_only_the_monitor_leg(client: AMIClient) -> None:
    live = [
        _channel("PJSIP/1905-0000003a", linked="uqmon-1", unique="uqmon-1"),
        # Defensive: a channel reported under another linked id is never touched.
        _channel("PJSIP/1901-0000002a", linked=LINKED),
    ]
    with (
        patch.object(client, "active_channels", return_value=live) as read,
        patch.object(client, "_send_action", return_value={"Response": "Success"}) as send,
    ):
        result = client.stop_listen_only_spy(channel_id="uqmon-1")

    read.assert_called_once_with(linked_id="uqmon-1")
    send.assert_called_once_with("Hangup", Channel="PJSIP/1905-0000003a")
    assert result.attempted is True
    assert result.channels == ["PJSIP/1905-0000003a"]


def test_stop_of_an_ended_monitor_sends_nothing(client: AMIClient) -> None:
    with (
        patch.object(client, "active_channels", return_value=[]),
        patch.object(client, "_send_action") as send,
    ):
        result = client.stop_listen_only_spy(channel_id="uqmon-1")

    send.assert_not_called()
    assert result.attempted is False


def test_stop_rejects_a_malformed_identity(client: AMIClient) -> None:
    with (
        patch.object(client, "active_channels") as read,
        pytest.raises(ValueError),
    ):
        client.stop_listen_only_spy(channel_id="uqmon 1\r\nAction: Hangup")
    read.assert_not_called()


def _spy_leg(state: str, application: str) -> ActiveChannel:
    return ActiveChannel(
        channel="PJSIP/1905-0000003a",
        unique_id="uqmon-1",
        linked_id="uqmon-1",
        state=state,
        application=application,
    )


@pytest.mark.parametrize(
    ("live", "expected"),
    [
        ([_spy_leg("Up", "ChanSpy")], ListenOnlySpyState.LISTENING),
        ([_spy_leg("Up", "")], ListenOnlySpyState.RINGING),  # answered, not attached
        ([_spy_leg("Ringing", "")], ListenOnlySpyState.RINGING),
        ([], ListenOnlySpyState.ENDED),
        (
            [_channel("Local/x-00000001;2", linked="uqmon-1", unique="17.9")],
            ListenOnlySpyState.ENDED,
        ),
    ],
)
def test_spy_state_is_typed_provider_truth(
    client: AMIClient,
    live: list,
    expected: ListenOnlySpyState,
) -> None:
    with patch.object(client, "active_channels", return_value=live) as read:
        assert client.listen_only_spy_state(channel_id="uqmon-1") is expected
    read.assert_called_once_with(linked_id="uqmon-1")


def test_spy_state_rejects_a_malformed_identity(client: AMIClient) -> None:
    with patch.object(client, "active_channels") as read, pytest.raises(ValueError):
        client.listen_only_spy_state(channel_id="uqmon 1")
    read.assert_not_called()


def test_active_channels_types_the_running_application(client: AMIClient) -> None:
    with patch.object(
        client,
        "_collect_events",
        return_value=[
            {
                "Event": "CoreShowChannel",
                "Channel": "PJSIP/1905-0000003a",
                "Uniqueid": "uqmon-1",
                "Linkedid": "uqmon-1",
                "ChannelStateDesc": "Up",
                "Application": "ChanSpy",
            },
        ],
    ):
        (channel,) = client.active_channels(linked_id="uqmon-1")
    assert channel.application == "ChanSpy"


@pytest.mark.parametrize(
    ("tech", "extension", "expected"),
    [("pjsip", "1905", "PJSIP/1905"), ("SIP", "1905", "SIP/1905")],
)
def test_monitor_line_channel(tech: str, extension: str, expected: str) -> None:
    assert monitor_line_channel(tech, extension) == expected


@pytest.mark.parametrize(
    ("tech", "extension"),
    [("iax2", "1905"), ("", "1905"), ("pjsip", "1905,w"), ("pjsip", "")],
)
def test_monitor_line_channel_refuses_what_cannot_monitor(tech: str, extension: str) -> None:
    with pytest.raises(ValueError):
        monitor_line_channel(tech, extension)


def test_facade_delegates_monitor_operations() -> None:
    from pyfreepbx.facade import FreePBX

    pbx = FreePBX.__new__(FreePBX)
    ami = MagicMock()
    ami.authenticated = True
    pbx._ami_client = ami

    pbx.endpoint_channel(endpoint="1901", linked_id=LINKED)
    pbx.start_listen_only_spy(
        monitor_channel=MONITOR,
        target_channel=TARGET,
        target_linked_id=LINKED,
        channel_id="uqmon-1",
    )
    pbx.stop_listen_only_spy(channel_id="uqmon-1")
    pbx.listen_only_spy_state(channel_id="uqmon-1")

    ami.endpoint_channel.assert_called_once_with(endpoint="1901", linked_id=LINKED)
    ami.start_listen_only_spy.assert_called_once()
    ami.stop_listen_only_spy.assert_called_once_with(channel_id="uqmon-1")
    ami.listen_only_spy_state.assert_called_once_with(channel_id="uqmon-1")
