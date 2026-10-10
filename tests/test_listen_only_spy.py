"""Listen-only ChanSpy originate: exact target, fixed options, no widening."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from pyfreepbx.clients.ami import LISTEN_ONLY_SPY_OPTIONS, AMIClient
from pyfreepbx.config import AMIConfig
from pyfreepbx.exceptions import AMIError
from pyfreepbx.models.call import ActiveChannel

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
