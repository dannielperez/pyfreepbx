"""Tests for AMI idle-timeout classification + the AMI_IDLE sentinel (S5-RT-0).

A pure socket read timeout (``settimeout`` expiry, ``errno is None``) is an
*idle* signal, not a disconnect: ``read_event`` raises :class:`AMITimeout`, and
the listener converts it to the ``AMI_IDLE`` sentinel — never an event, never a
disconnect. An errno-bearing timeout (e.g. ``ETIMEDOUT``) stays a real failure.
"""

from __future__ import annotations

import errno
from unittest.mock import patch

import pytest

from pyfreepbx.clients.ami import AMIClient
from pyfreepbx.clients.ami_listener import AMI_IDLE, AMIEventListener
from pyfreepbx.config import AMIConfig
from pyfreepbx.exceptions import AMITimeout
from pyfreepbx.models.events import NewchannelEvent

_BANNER = b"Asterisk Call Manager/5.0.5\r\n"
_LOGIN_OK = b"Response: Success\r\nMessage: Authentication accepted\r\n\r\n"
_HANDSHAKE = _BANNER + _LOGIN_OK
_NEWCHANNEL = (
    b"Event: Newchannel\r\nChannel: PJSIP/7001-x\r\nChannelStateDesc: Down\r\n"
    b"Uniqueid: 2.2\r\nLinkedid: 2.2\r\n\r\n"
)


def _config() -> AMIConfig:
    return AMIConfig(host="pbx.test", port=5038, username="u", secret="s")


class ScriptedSocket:
    """Serves a scripted recv sequence: bytes to return, an exception to raise,
    or an empty list step exhausted -> ``b""`` (EOF)."""

    def __init__(self, steps: list[bytes | BaseException]) -> None:
        self._steps = list(steps)
        self.sent = bytearray()
        self.closed = False

    def recv(self, bufsize: int) -> bytes:
        if not self._steps:
            return b""  # EOF -> AMIConnectionError in the client
        step = self._steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def close(self) -> None:
        self.closed = True


def _handshook_client(stream_steps: list[bytes | BaseException]) -> AMIClient:
    """Return a connected+authenticated client whose event stream follows steps."""
    sock = ScriptedSocket([_HANDSHAKE, *stream_steps])
    client = AMIClient(_config())
    with patch("socket.create_connection", return_value=sock):
        client.connect()
        client.login()
    return client


def _started_listener(
    stream_steps: list[bytes | BaseException],
    **kwargs: object,
) -> AMIEventListener:
    sock = ScriptedSocket([_HANDSHAKE, *stream_steps])
    listener = AMIEventListener(_config(), clock=lambda: 0.0, **kwargs)  # type: ignore[arg-type]
    with patch("socket.create_connection", return_value=sock):
        listener.start()
    return listener


class TestReadEventClassification:
    def test_idle_recv_timeout_raises_amitimeout(self) -> None:
        client = _handshook_client([TimeoutError()])  # errno is None -> idle
        with pytest.raises(AMITimeout):
            client.read_event()

    def test_etimedout_is_real_failure_not_idle(self) -> None:
        client = _handshook_client([TimeoutError(errno.ETIMEDOUT, "timed out")])
        with pytest.raises(TimeoutError) as excinfo:
            client.read_event()
        assert not isinstance(excinfo.value, AMITimeout)
        assert excinfo.value.errno == errno.ETIMEDOUT

    def test_partial_frame_then_idle_preserves_buffer(self) -> None:
        half = len(_NEWCHANNEL) // 2
        client = _handshook_client(
            [_NEWCHANNEL[:half], TimeoutError(), _NEWCHANNEL[half:]],
        )
        with pytest.raises(AMITimeout):
            client.read_event()  # partial buffered, idle raised mid-frame
        frame = client.read_event()  # resumes and completes the same frame
        assert frame["Event"] == "Newchannel"
        assert frame["Uniqueid"] == "2.2"


class TestSentinelPropagation:
    def test_iter_raw_yields_ami_idle_on_timeout(self) -> None:
        listener = _started_listener([TimeoutError(), _NEWCHANNEL])
        gen = listener.iter_raw()
        assert next(gen) is AMI_IDLE
        assert isinstance(next(gen), dict)

    def test_listen_yields_ami_idle_then_event(self) -> None:
        listener = _started_listener([TimeoutError(), _NEWCHANNEL])
        gen = listener.listen()
        assert next(gen) is AMI_IDLE  # idle tick passes through unparsed
        assert isinstance(next(gen), NewchannelEvent)


class TestRunForeverFiltersIdle:
    def test_run_forever_never_delivers_ami_idle(self) -> None:
        received: list[object] = []
        listener = AMIEventListener(_config(), clock=lambda: 0.0, sleep=lambda _s: None)
        sock = ScriptedSocket([_HANDSHAKE, TimeoutError(), _NEWCHANNEL])

        def on_event(event: object) -> None:
            received.append(event)
            listener.close()  # stop after the first real event

        with patch("socket.create_connection", return_value=sock):
            listener.run_forever(on_event, base_backoff=0.0)

        assert len(received) == 1
        assert isinstance(received[0], NewchannelEvent)
        assert AMI_IDLE not in received


class TestActionPathStillErrors:
    def test_login_read_timeout_is_not_amitimeout(self) -> None:
        # Only read_event() classifies timeouts; the action/login path must keep
        # surfacing a read timeout as a real error.
        listener = AMIEventListener(_config(), clock=lambda: 0.0)
        sock = ScriptedSocket([_BANNER, TimeoutError()])  # banner ok, login read times out
        with (
            patch("socket.create_connection", return_value=sock),
            pytest.raises(TimeoutError) as excinfo,
        ):
            listener.start()
        assert not isinstance(excinfo.value, AMITimeout)
