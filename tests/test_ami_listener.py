"""Tests for the synchronous AMI event listener (OPS-SNAP-3, #494).

Drives the listener by replaying captured fixtures through a fake socket,
including across arbitrary recv boundaries, plus noise-filter and
reconnect/backoff behaviour.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from pyfreepbx.clients.ami_listener import AMIEventListener
from pyfreepbx.config import AMIConfig
from pyfreepbx.exceptions import AMIConnectionError
from pyfreepbx.models.events import AMIEvent, NewchannelEvent, UnknownEvent

FIXTURES = Path(__file__).parent / "fixtures" / "ami"

_BANNER = b"Asterisk Call Manager/5.0.5\r\n"
_LOGIN_OK = b"Response: Success\r\nMessage: Authentication accepted\r\n\r\n"
_VARSET = (
    b"Event: VarSet\r\nChannel: PJSIP/7001-x\r\nVariable: FOO\r\nValue: bar\r\n"
    b"Uniqueid: 1.1\r\nLinkedid: 1.1\r\n\r\n"
)
_NEWCHANNEL = (
    b"Event: Newchannel\r\nChannel: PJSIP/7001-x\r\nChannelStateDesc: Down\r\n"
    b"Uniqueid: 2.2\r\nLinkedid: 2.2\r\n\r\n"
)


class FakeSocket:
    """A socket stand-in that serves a fixed byte payload then EOFs.

    ``chunk_size`` forces small ``recv`` returns to exercise frame reassembly
    across recv boundaries (including a CRLF split mid-frame).
    """

    def __init__(self, payload: bytes, *, chunk_size: int | None = None) -> None:
        self._data = payload
        self._pos = 0
        self._chunk = chunk_size
        self.sent = bytearray()
        self.closed = False

    def recv(self, bufsize: int) -> bytes:
        if self._pos >= len(self._data):
            return b""  # EOF -> AMIConnectionError in the client
        n = bufsize if self._chunk is None else min(self._chunk, bufsize)
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def close(self) -> None:
        self.closed = True


def _config() -> AMIConfig:
    return AMIConfig(host="pbx.test", port=5038, username="u", secret="s")


def _payload(fixture: str) -> bytes:
    return _BANNER + _LOGIN_OK + (FIXTURES / fixture).read_bytes()


def _typed_names(events: list[AMIEvent]) -> list[str]:
    return [e.event for e in events if not isinstance(e, UnknownEvent)]


def _collect(listener: AMIEventListener) -> list[AMIEvent]:
    out: list[AMIEvent] = []
    try:
        for event in listener.listen():
            out.append(event)
    except AMIConnectionError:
        pass  # EOF on the fake socket = end of this connection's stream
    return out


def _run(payload: bytes, *, chunk_size: int | None = None, **kwargs: object) -> list[AMIEvent]:
    listener = AMIEventListener(_config(), clock=lambda: 0.0, **kwargs)  # type: ignore[arg-type]
    sock = FakeSocket(payload, chunk_size=chunk_size)
    with patch("socket.create_connection", return_value=sock):
        listener.start()
        return _collect(listener)


# Ground-truth typed-event order extracted from the fixtures.
_EXPECTED = {
    "answered.txt": [
        "Newchannel",
        "Newchannel",
        "DialBegin",
        "Newstate",
        "Newstate",
        "DialEnd",
        "Newstate",
        "BridgeEnter",
        "BridgeEnter",
        "Hangup",
        "Hangup",
    ],
    "missed.txt": [
        "Newchannel",
        "Newchannel",
        "DialBegin",
        "Newstate",
        "DialEnd",
        "Hangup",
        "Newstate",
        "Hangup",
    ],
    "originate.txt": [
        "Newchannel",
        "Newchannel",
        "OriginateResponse",
        "Newstate",
        "Newstate",
    ],
}


class TestReplaySequence:
    @pytest.mark.parametrize("fixture", list(_EXPECTED))
    def test_typed_sequence(self, fixture: str) -> None:
        events = _run(_payload(fixture))
        assert _typed_names(events) == _EXPECTED[fixture]

    def test_queue_answered_invariants(self) -> None:
        events = _run(_payload("queue.txt"))
        names = _typed_names(events)
        assert "QueueCallerJoin" in names
        assert "AgentConnect" in names  # operator answered from the queue
        assert "AgentComplete" in names
        assert names[-1] == "Hangup"

    def test_abandoned_invariants(self) -> None:
        events = _run(_payload("abandoned.txt"))
        names = _typed_names(events)
        assert "QueueCallerJoin" in names
        assert "QueueCallerAbandon" in names
        assert "AgentConnect" not in names  # nobody answered

    def test_linkedid_constant_across_call(self) -> None:
        # one call -> one linkedid shared by every leg that carries one
        events = _run(_payload("answered.txt"))
        linkedids = {e.linkedid for e in events if e.linkedid is not None}
        assert len(linkedids) == 1


class TestRecvBoundaries:
    @pytest.mark.parametrize("chunk_size", [1, 3, 7, 64])
    def test_framing_reassembles_across_recv(self, chunk_size: int) -> None:
        events = _run(_payload("answered.txt"), chunk_size=chunk_size)
        assert _typed_names(events) == _EXPECTED["answered.txt"]


class TestNoiseFilter:
    def test_noise_dropped_by_default(self) -> None:
        payload = _BANNER + _LOGIN_OK + _VARSET + _NEWCHANNEL
        events = _run(payload)  # filter_noise defaults True
        assert all(e.event != "VarSet" for e in events)
        assert [e.event for e in events] == ["Newchannel"]

    def test_noise_surfaced_when_disabled(self) -> None:
        payload = _BANNER + _LOGIN_OK + _VARSET + _NEWCHANNEL
        events = _run(payload, filter_noise=False)
        assert any(isinstance(e, UnknownEvent) and e.event == "VarSet" for e in events)


class TestReconnect:
    def test_reconnects_with_backoff_after_drop(self) -> None:
        sleeps: list[float] = []
        events: list[AMIEvent] = []
        listener = AMIEventListener(_config(), clock=lambda: 0.0, sleep=sleeps.append)

        def on_event(event: AMIEvent) -> None:
            events.append(event)
            listener.close()  # stop after the first event from connection #2

        sock1 = FakeSocket(_BANNER + _LOGIN_OK)  # drops immediately (EOF)
        sock2 = FakeSocket(_BANNER + _LOGIN_OK + _NEWCHANNEL)
        with patch("socket.create_connection", side_effect=[sock1, sock2]):
            listener.run_forever(on_event, base_backoff=1.0)

        assert sleeps == [1.0]  # exactly one backoff between the two connects
        assert len(events) == 1
        assert isinstance(events[0], NewchannelEvent)

    def test_listen_is_iterator(self) -> None:
        listener = AMIEventListener(_config())
        assert isinstance(listener.listen(), Iterator)
