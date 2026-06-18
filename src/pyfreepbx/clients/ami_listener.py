"""Synchronous AMI event listener (OPS-SNAP-3, #494).

Connects to AMI, authenticates, and streams **typed events**. Synchronous and
stateless by design (owner decision 2026-06-17):

* Reuses the existing :class:`~pyfreepbx.clients.ami.AMIClient` socket transport
  (no asyncio, no new runtime dependencies).
* Holds **no** call-session state and **no** ``ActionID``→``Uniqueid`` map — those
  belong to the consuming application.
* A consumer needing async (e.g. a long-lived downstream application runner) bridges this with
  a thread + queue; the listener itself just yields events.

Event delivery relies on AMI's default behaviour: an authenticated manager
connection receives every event its ``read`` privileges allow. The listener does
**not** issue an explicit ``Events`` action — doing so would race with the
already-flowing asynchronous event stream.
"""

from __future__ import annotations

import time
from contextlib import suppress
from typing import TYPE_CHECKING

from pyfreepbx.clients.ami import AMIClient
from pyfreepbx.clients.ami_parser import parse_event
from pyfreepbx.exceptions import AMIConnectionError, AMIError, AMITimeout
from pyfreepbx.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pyfreepbx.config import AMIConfig
    from pyfreepbx.models.events import AMIEvent

log = get_logger("clients.ami_listener")


class _IdleTick:
    """Transport-only sentinel: one read window elapsed, socket alive, no frame.

    NOT an :class:`~pyfreepbx.models.events.AMIEvent` — a liveness signal only,
    yielded by :meth:`AMIEventListener.iter_raw`/:meth:`listen` on an idle read
    timeout. Compared by identity (``is AMI_IDLE``); never parsed or delivered as
    an event.
    """

    __slots__ = ()


AMI_IDLE = _IdleTick()


# High-volume / low-signal events dropped by the optional noise filter. A busy
# PBX emits ~10x more of these than call-signalling events (capture 2026-06-17).
_NOISE_EVENTS: frozenset[str] = frozenset(
    {
        "VarSet",
        "Newexten",
        "RTCPSent",
        "RTCPReceived",
        "DTMFBegin",
        "DTMFEnd",
        "MusicOnHoldStart",
        "MusicOnHoldStop",
        "MixMonitorStart",
        "MixMonitorStop",
        "DeviceStateChange",
        "ContactStatus",
        "ExtensionStatus",
        "PeerStatus",
    }
)


class AMIEventListener:
    """Stream typed AMI events from one PBX, with reconnect/backoff.

    Usage::

        listener = AMIEventListener(config)
        listener.run_forever(lambda ev: handle(ev))   # blocks; reconnects on drops

    or, for one connection's worth of events::

        listener.start()
        for event in listener.listen():
            if event is AMI_IDLE:      # transport liveness tick, not an event
                continue
            handle(event)
    """

    def __init__(
        self,
        config: AMIConfig,
        *,
        client: AMIClient | None = None,
        filter_noise: bool = True,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Args:
        config: AMI connection settings.
        client: Optional pre-built client (tests inject one; otherwise created).
        filter_noise: Drop high-volume non-signalling events before parsing.
        clock: Arrival-time source (epoch seconds); injectable for tests.
        sleep: Backoff sleep function; injectable for tests.
        """
        self._config = config
        self._client = client if client is not None else AMIClient(config)
        self._filter_noise = filter_noise
        self._clock = clock
        self._sleep = sleep
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the connection and authenticate (events flow immediately after)."""
        self._client.connect()
        self._client.login()

    def close(self) -> None:
        """Stop the listener and release the connection. Idempotent.

        Swallows teardown errors: the client's ``Logoff`` round-trip can fail on
        an already-dropped socket, which must not propagate out of ``close()``.
        """
        self._closed = True
        with suppress(AMIError, OSError):
            self._client.close()

    def __enter__(self) -> AMIEventListener:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def iter_raw(self) -> Iterator[dict[str, str] | _IdleTick]:
        """Yield raw AMI event frames for one connection.

        Skips frames with no ``Event`` header (action/command responses such as
        the login ack) and — when ``filter_noise`` is set — the high-volume
        non-signalling events. Raises :class:`AMIConnectionError` when the
        connection drops (the caller decides whether to reconnect).

        On an idle read timeout (:class:`AMITimeout`) yields the ``AMI_IDLE``
        sentinel instead of a frame — a liveness tick, never call data.
        """
        while not self._closed:
            try:
                frame = self._client.read_event()
            except AMITimeout:
                yield AMI_IDLE
                continue
            if "Event" not in frame:
                continue
            if self._filter_noise and frame.get("Event") in _NOISE_EVENTS:
                continue
            yield frame

    def listen(self) -> Iterator[AMIEvent | _IdleTick]:
        """Yield typed events for one connection (call :meth:`start` first).

        Passes the ``AMI_IDLE`` transport sentinel through untouched; only real
        frames are parsed into events. Consumers must filter ``AMI_IDLE``.
        """
        for item in self.iter_raw():
            yield item if isinstance(item, _IdleTick) else parse_event(item, self._clock())

    def run_forever(
        self,
        on_event: Callable[[AMIEvent], None],
        *,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        """Stream events to ``on_event`` forever, reconnecting with backoff on drops.

        Returns only after :meth:`close`. A dropped connection is caught and
        retried with exponential backoff (reset on each clean connect); the loop
        degrades gracefully rather than crashing on a transient vendor drop.
        """
        backoff = base_backoff
        while not self._closed:
            try:
                self.start()
                backoff = base_backoff
                for event in self.listen():
                    if isinstance(event, _IdleTick):
                        continue  # transport liveness tick — never an event
                    on_event(event)
            except (AMIConnectionError, OSError) as exc:
                if self._closed:
                    break
                log.warning("AMI listener connection lost: %s; reconnecting in %.1fs", exc, backoff)
                self._sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            except AMIError as exc:
                if self._closed:
                    break
                log.error("AMI listener error: %s; reconnecting in %.1fs", exc, backoff)
                self._sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            finally:
                # Release the socket before the next attempt; the Logoff
                # round-trip may fail on a dropped socket — never let it abort
                # the reconnect loop.
                with suppress(AMIError, OSError):
                    self._client.disconnect()


__all__ = ["AMI_IDLE", "AMIEventListener"]
