"""Asterisk Manager Interface (AMI) client.

AMI is a line-oriented TCP protocol. Each message is a set of
"Key: Value" lines terminated by a blank line (``\\r\\n\\r\\n``).

This module provides:

* **Low-level transport** — socket management, action/response exchange
* **Typed operational queries** — endpoint status, queue status, ping
* **Safety guardrails** — allow-listed action set for public library use

Reference: https://docs.asterisk.org/Configuration/Interfaces/Asterisk-Manager-Interface-AMI/

Design Notes
~~~~~~~~~~~~
AMI exposes powerful administrative capabilities (Originate, Redirect,
Hangup, ModuleLoad, etc.). This client distinguishes read-only/low-risk
actions from explicit typed mutations. Consumer services own permission,
approval, and audit policy for typed mutations and generic actions.

Read-only and low-risk actions:
    Ping, CoreStatus, CoreSettings, CoreShowChannels,
    SIPpeers, SIPshowpeer, PJSIPShowEndpoints, PJSIPShowEndpoint,
    QueueSummary, QueueStatus, QueueAdd, QueueRemove

Typed mutations requiring consumer policy:
    Originate, QueuePause

Actions that should remain in *service* layer logic (not raw client):
    Redirect, Hangup, Bridge, ModuleLoad/Unload,
    Reload (selective), DBPut/DBGet/DBDel, MailboxCount,
    IAXpeers, ConfbridgeList
"""

from __future__ import annotations

import socket
import uuid
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from pyfreepbx.clients.base import BaseClient
from pyfreepbx.exceptions import AMIAuthError, AMIConnectionError, AMIError, AMITimeout
from pyfreepbx.logging import get_logger
from pyfreepbx.models.call import ActiveChannel, HangupResult, OriginateResult
from pyfreepbx.models.device import (
    Device,
    DeviceState,
    normalize_device_state,
    normalize_sip_status,
)
from pyfreepbx.models.queue import QueueStats
from pyfreepbx.models.system import SystemInfo

if TYPE_CHECKING:
    from pyfreepbx.config import AMIConfig

log = get_logger("clients.ami")

_CRLF = "\r\n"
_END = _CRLF + _CRLF

# Actions considered safe for a public library to expose directly.
# Anything outside this set requires run_action() with explicit intent.
_SAFE_ACTIONS: frozenset[str] = frozenset(
    {
        "Ping",
        "Login",
        "Logoff",
        "CoreStatus",
        "CoreSettings",
        "CoreShowChannels",
        "SIPpeers",
        "SIPshowpeer",
        "PJSIPShowEndpoints",
        "PJSIPShowEndpoint",
        "QueueSummary",
        "QueueStatus",
        "QueueAdd",
        "QueueRemove",
    }
)


class AMIClient(BaseClient):
    """Strongly-typed client for the Asterisk Manager Interface.

    Handles TCP connection lifecycle, authentication, and provides
    typed methods for common operational queries. Inherits from
    :class:`BaseClient` for consistent lifecycle management.

    Usage::

        from pyfreepbx.config import AMIConfig
        from pyfreepbx.clients.ami import AMIClient

        config = AMIConfig(host="pbx.local", username="admin", secret="s3cret")
        with AMIClient(config) as ami:
            ami.connect()
            ami.login()
            info = ami.core_status()
            endpoints = ami.pjsip_endpoints()
    """

    def __init__(self, config: AMIConfig) -> None:
        self._config = config
        self._sock: socket.socket | None = None
        self._buffer: str = ""
        self._connected: bool = False
        self._authenticated: bool = False
        self._banner: str = ""

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether the TCP socket is connected."""
        return self._connected

    @property
    def authenticated(self) -> bool:
        """Whether login has succeeded on this connection."""
        return self._authenticated

    @property
    def banner(self) -> str:
        """Asterisk version banner received on connect."""
        return self._banner

    def connect(self) -> str:
        """Open TCP connection to AMI and read the greeting banner.

        Returns:
            The Asterisk version banner (e.g. ``"Asterisk Call Manager/6.0.0"``).

        Raises:
            AMIConnectionError: If the TCP connection fails.
        """
        host, port = self._config.host, self._config.port
        log.debug("Connecting to AMI at %s:%d", host, port)

        try:
            sock = socket.create_connection(
                (host, port),
                timeout=self._config.timeout,
            )
        except OSError as exc:
            log.error("AMI connection failed: %s", exc)
            raise AMIConnectionError(f"Failed to connect to AMI at {host}:{port}: {exc}") from exc

        self._sock = sock
        self._buffer = ""
        try:
            self._banner = self._read_line()
        except (AMIError, OSError):
            self._invalidate_session()
            raise
        self._connected = True
        self._authenticated = False
        log.info("AMI connected: %s", self._banner)
        return self._banner

    def login(self) -> dict[str, str]:
        """Authenticate with AMI using the configured credentials.

        Returns:
            The raw AMI response dict on success.

        Raises:
            AMIAuthError: If login is rejected.
            AMIError: If not connected.
        """
        self._require_connection()
        log.debug("Logging in as %s", self._config.username)

        response = self._send_action(
            "Login",
            Username=self._config.username,
            Secret=self._config.secret,
        )
        if response.get("Response") != "Success":
            msg = response.get("Message", "Login failed")
            log.error("AMI login failed: %s", msg)
            raise AMIAuthError(f"AMI authentication failed: {msg}")

        self._authenticated = True
        log.info("AMI authenticated as %s", self._config.username)
        return response

    def reconnect(self) -> dict[str, str]:
        """Replace a stale AMI session and authenticate the new connection.

        This method never replays an action that may have been accepted before a
        transport failure. Callers can therefore recover a mid-session drop and
        decide explicitly whether their interrupted operation is safe to retry.
        """
        self.disconnect()
        self.connect()
        return self.login()

    def disconnect(self) -> None:
        """Send Logoff action and close the TCP socket.

        Safe to call multiple times or when not connected.
        """
        if self._sock is not None and self._authenticated:
            with suppress(AMIError, OSError):
                self._send_action("Logoff")
        self._invalidate_session()
        log.debug("AMI disconnected")

    def close(self) -> None:
        """Release underlying connections (BaseClient contract)."""
        self.disconnect()

    # ------------------------------------------------------------------
    # Typed operational queries
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Send an AMI Ping action.

        Returns:
            ``True`` if Asterisk responds with Pong, ``False`` otherwise.
        """
        self._require_auth()
        try:
            resp = self._send_action("Ping")
            return resp.get("Response") == "Success"
        except AMIError:
            return False

    def core_status(self) -> SystemInfo:
        """Fetch Asterisk core status.

        Maps AMI ``CoreStatus`` response fields to :class:`SystemInfo`.

        ``uptime_seconds`` and ``reload_seconds`` are derived from
        ``CoreStartupDate``/``CoreStartupTime`` and
        ``CoreReloadDate``/``CoreReloadTime`` respectively. If parsing
        fails (e.g. unexpected date format), they default to ``0`` and
        a debug message is logged.

        Reference:
            https://docs.asterisk.org/Asterisk_16_Documentation/API_Documentation/AMI_Actions/CoreStatus
        """
        self._require_auth()
        resp = self._send_action("CoreStatus")

        return SystemInfo(
            asterisk_version=resp.get("CoreVersion", resp.get("AsteriskVersion", "")),
            ami_version=resp.get("AMIversion", ""),
            active_calls=int(resp.get("CoreCurrentCalls", 0)),
            uptime_seconds=_parse_uptime(
                resp.get("CoreStartupDate", ""),
                resp.get("CoreStartupTime", ""),
            ),
            reload_seconds=_parse_uptime(
                resp.get("CoreReloadDate", ""),
                resp.get("CoreReloadTime", ""),
            ),
            active_channels=0,
        )

    def queue_summary(self, queue: str | None = None) -> list[QueueStats]:
        """Fetch live queue statistics via AMI ``QueueSummary``.

        Args:
            queue: Restrict to a single queue by name. ``None`` returns all.

        Returns:
            One :class:`QueueStats` per queue.

        Reference:
            https://docs.asterisk.org/Asterisk_16_Documentation/API_Documentation/AMI_Actions/QueueSummary
        """
        self._require_auth()
        params: dict[str, str] = {}
        if queue is not None:
            params["Queue"] = queue

        events = self._collect_events("QueueSummary", **params)
        stats: list[QueueStats] = []
        for event in events:
            stats.append(
                QueueStats(
                    queue=event.get("Queue", ""),
                    logged_in=int(event.get("LoggedIn", 0)),
                    available=int(event.get("Available", 0)),
                    callers=int(event.get("Callers", 0)),
                    hold_time=int(event.get("HoldTime", 0)),
                    talk_time=int(event.get("TalkTime", 0)),
                    longest_hold=int(event.get("LongestHoldTime", 0)),
                )
            )
        log.debug("QueueSummary returned %d queues", len(stats))
        return stats

    def queue_status(self, queue: str | None = None) -> list[dict[str, str]]:
        """Fetch detailed queue member status via AMI ``QueueStatus``.

        Returns raw event dicts — the service layer maps these into
        domain models. QueueStatus returns both ``QueueParams`` and
        ``QueueMember`` events; the caller decides what to extract.

        Args:
            queue: Restrict to a single queue. ``None`` returns all.

        Reference:
            https://docs.asterisk.org/Asterisk_16_Documentation/API_Documentation/AMI_Actions/QueueStatus
        """
        self._require_auth()
        params: dict[str, str] = {}
        if queue is not None:
            params["Queue"] = queue
        return self._collect_events("QueueStatus", **params)

    def queue_pause(
        self,
        *,
        queue: str,
        interface: str,
        paused: bool,
        reason: str | None = None,
    ) -> None:
        """Pause or unpause one queue member through the typed AMI action.

        ``QueuePause`` mutates runtime state, so it is exposed explicitly rather
        than requiring consumers to use the generic action escape hatch.
        """
        self._require_auth()
        params: dict[str, str] = {
            "Queue": queue,
            "Interface": interface,
            "Paused": "true" if paused else "false",
        }
        if reason is not None:
            params["Reason"] = reason
        response = self._send_action("QueuePause", **params)
        if response.get("Response") != "Success":
            raise AMIError(response.get("Message", "QueuePause failed"))

    def pjsip_endpoints(self) -> list[Device]:
        """List all PJSIP endpoints and their registration state.

        Maps AMI ``PJSIPShowEndpoints`` events to :class:`Device` models.

        Reference:
            https://docs.asterisk.org/Asterisk_16_Documentation/API_Documentation/AMI_Actions/PJSIPShowEndpoints
        """
        self._require_auth()
        events = self._collect_events("PJSIPShowEndpoints")

        devices: list[Device] = []
        for event in events:
            if event.get("Event") != "EndpointList":
                continue
            devices.append(
                Device(
                    name=event.get("ObjectName", event.get("Endpoint", "")),
                    extension=event.get("Exten") or event.get("ObjectName"),
                    state=_parse_device_state(event.get("DeviceState", "")),
                    user_agent=event.get("UserAgent"),
                )
            )
        log.debug("PJSIPShowEndpoints returned %d devices", len(devices))
        return devices

    def pjsip_endpoint(self, endpoint: str) -> list[dict[str, str]]:
        """Fetch detailed info for a single PJSIP endpoint.

        Returns raw event dicts (multiple event types are returned).
        The service layer should extract relevant fields.

        Args:
            endpoint: Endpoint name (e.g. ``"1001"``).

        Reference:
            https://docs.asterisk.org/Asterisk_16_Documentation/API_Documentation/AMI_Actions/PJSIPShowEndpoint
        """
        self._require_auth()
        return self._collect_events("PJSIPShowEndpoint", Endpoint=endpoint)

    def sip_peers(self) -> list[Device]:
        """List all SIP (chan_sip) peers and their registration state.

        .. deprecated::
            chan_sip was removed in Asterisk 21. Use :meth:`pjsip_endpoints`
            for PJSIP-based systems. This method will be removed in v0.2.0.

        Maps AMI ``SIPpeers`` events to :class:`Device` models.

        Reference:
            https://docs.asterisk.org/Asterisk_16_Documentation/API_Documentation/AMI_Actions/SIPpeers
        """
        import warnings

        warnings.warn(
            "sip_peers() is deprecated — chan_sip was removed in Asterisk 21. "
            "Use pjsip_endpoints() instead. This method will be removed in v0.2.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._require_auth()
        events = self._collect_events("SIPpeers")

        devices: list[Device] = []
        for event in events:
            if event.get("Event") != "PeerEntry":
                continue
            devices.append(
                Device(
                    name=f"SIP/{event.get('ObjectName', event.get('Channeltype', ''))}",
                    extension=event.get("ObjectName"),
                    state=_parse_sip_status(event.get("Status", "")),
                    ip_address=event.get("IPaddress"),
                )
            )
        log.debug("SIPpeers returned %d devices", len(devices))
        return devices

    # ------------------------------------------------------------------
    # Safe action gateway
    # ------------------------------------------------------------------

    def run_action(self, action: str, **params: Any) -> dict[str, str]:
        """Execute an arbitrary AMI action.

        This is the escape hatch for actions not covered by typed methods.
        All actions pass through; no allow-list is enforced here — the
        caller takes responsibility.

        For event-producing actions, use :meth:`run_action_with_events`.

        Args:
            action: AMI action name.
            **params: Action parameters.

        Returns:
            Response dict.
        """
        self._require_auth()
        if action not in _SAFE_ACTIONS:
            log.warning(
                "Running non-allowlisted AMI action: %s. "
                "Consider wrapping this in a service method.",
                action,
            )
        return self._send_action(action, **params)

    def run_action_with_events(self, action: str, **params: Any) -> list[dict[str, str]]:
        """Execute an action that returns multiple events.

        Same as :meth:`run_action` but collects events until the
        ``*Complete`` marker.
        """
        self._require_auth()
        if action not in _SAFE_ACTIONS:
            log.warning("Running non-allowlisted AMI action: %s", action)
        return self._collect_events(action, **params)

    # ------------------------------------------------------------------
    # Call control (write actions — service-layer use only)
    # ------------------------------------------------------------------

    def originate(
        self,
        *,
        channel: str,
        extension: str,
        context: str = "from-internal",
        priority: int = 1,
        caller_id: str = "",
        timeout_ms: int = 30000,
        action_id: str = "",
        variables: dict[str, str] | None = None,
    ) -> OriginateResult:
        """Place a call via the AMI ``Originate`` action.

        ``Originate`` is a privileged *write* action (it makes the PBX place a
        real call) and is deliberately **not** in :data:`_SAFE_ACTIONS`. It is
        exposed as an explicit typed method — never via the generic
        ``run_action`` escape hatch — so the call contract is reviewable in one
        place. The consumer's service layer owns the policy (permission gate,
        dry-run, audit, circuit breaker); this method owns only the protocol.

        The action is issued **asynchronously** (``Async: true``) so AMI returns
        as soon as the call is queued, echoing the ``ActionID`` we supply. That
        id is returned as :attr:`OriginateResult.action_id` and is the durable
        call reference / idempotency key. Call progress (Ringing/Answered/
        Hangup) arrives later as AMI *events* — consuming those is a separate
        concern (the shared call-event listener), not this method.

        Args:
            channel: Channel to call first, e.g. ``"Local/2001@from-internal"``.
            extension: Extension to connect the answered channel to.
            context: Dialplan context for ``extension``.
            priority: Dialplan priority for ``extension``.
            caller_id: Caller ID to present (already redacted/safe to send).
            timeout_ms: How long to ring before giving up, in milliseconds.
            action_id: Optional caller-supplied id; one is generated if empty.
            variables: Optional channel variables (``Variable: k=v``).

        Returns:
            :class:`OriginateResult` with the (possibly generated) ``action_id``.

        Raises:
            AMIError: If AMI does not acknowledge the originate with
                ``Response: Success`` (a structured vendor refusal — distinct
                from a transport failure, which raises ``AMIConnectionError``).
        """
        self._require_auth()
        aid = action_id or uuid.uuid4().hex
        params: dict[str, Any] = {
            "Channel": channel,
            "Exten": extension,
            "Context": context,
            "Priority": priority,
            "Async": "true",
            "Timeout": timeout_ms,
            "ActionID": aid,
        }
        if caller_id:
            params["CallerID"] = caller_id
        if variables:
            # AMI accepts comma-joined channel variables in a single header.
            params["Variable"] = ",".join(f"{k}={v}" for k, v in variables.items())

        response = self._send_action("Originate", **params)
        if response.get("Response") != "Success":
            raise AMIError(response.get("Message", "Originate was not accepted"))

        return OriginateResult(
            action_id=aid,
            channel=channel,
            extension=extension,
            context=context,
            response=response.get("Response", ""),
            message=response.get("Message", ""),
        )

    def active_channels(self, *, linked_id: str = "") -> list[ActiveChannel]:
        """Return typed live channels, optionally restricted to one linked id."""
        self._require_auth()
        channels: list[ActiveChannel] = []
        for event in self._collect_events("CoreShowChannels"):
            if event.get("Event") != "CoreShowChannel":
                continue
            event_linked_id = event.get("Linkedid", "")
            if linked_id and event_linked_id != linked_id:
                continue
            channels.append(
                ActiveChannel(
                    channel=event.get("Channel", ""),
                    unique_id=event.get("Uniqueid", ""),
                    linked_id=event_linked_id,
                    state=event.get("ChannelStateDesc", ""),
                    caller_id_num=event.get("CallerIDNum", ""),
                    connected_line_num=event.get("ConnectedLineNum", ""),
                )
            )
        return channels

    def hangup_channel(self, *, channel: str, linked_id: str) -> HangupResult:
        """Request hangup only after revalidating an exact live call identity.

        Both values are mandatory. The read-before-write guard prevents a stale
        channel name from terminating a later, unrelated call after Asterisk has
        recycled identifiers. This method never retries the ``Hangup`` action.
        """
        self._require_auth()
        if not channel or not linked_id:
            raise ValueError("channel and linked_id are required")

        matches = [
            item
            for item in self.active_channels(linked_id=linked_id)
            if item.channel == channel
        ]
        if len(matches) != 1:
            return HangupResult(
                channel=channel,
                linked_id=linked_id,
                attempted=False,
                response="NotFound" if not matches else "Ambiguous",
                message=(
                    "The exact live channel was not found."
                    if not matches
                    else "More than one live channel matched the exact identity."
                ),
            )

        response = self._send_action("Hangup", Channel=channel)
        return HangupResult(
            channel=channel,
            linked_id=linked_id,
            attempted=True,
            response=response.get("Response", ""),
            message=response.get("Message", ""),
        )

    # ------------------------------------------------------------------
    # Protocol I/O (private)
    # ------------------------------------------------------------------

    def _send_action(self, action: str, **params: Any) -> dict[str, str]:
        """Send an AMI action and return the response as a dict."""
        if self._sock is None:
            raise AMIError("Not connected to AMI. Call connect() first.")

        lines = [f"Action: {action}"]
        for key, value in params.items():
            lines.append(f"{key}: {value}")
        message = _CRLF.join(lines) + _END

        log.debug(">>> %s (%d params)", action, len(params))
        try:
            self._sock.sendall(message.encode("utf-8"))
            return self._read_response()
        except (AMIConnectionError, OSError):
            self._invalidate_session()
            raise

    def _collect_events(self, action: str, **params: Any) -> list[dict[str, str]]:
        """Send an action and collect events until the *Complete marker."""
        initial = self._send_action(action, **params)
        if initial.get("Response") != "Success":
            msg = initial.get("Message", f"{action} failed")
            raise AMIError(msg)

        events: list[dict[str, str]] = []
        try:
            while True:
                event = self._read_response()
                event_name = event.get("Event", "")
                if event_name.endswith("Complete"):
                    break
                if len(events) >= self._config.max_events:
                    self._invalidate_session()
                    raise AMIError(
                        f"{action} exceeded the {self._config.max_events}-event limit "
                        "without a completion marker"
                    )
                events.append(event)
        except (AMIConnectionError, OSError):
            self._invalidate_session()
            raise

        log.debug("<<< %s returned %d events", action, len(events))
        return events

    def _read_line(self) -> str:
        """Read a single line from the AMI socket."""
        while _CRLF not in self._buffer:
            self._buffer += self._recv()
            self._enforce_frame_bound("AMI banner line")
        line, self._buffer = self._buffer.split(_CRLF, 1)
        return line

    def read_event(self) -> dict[str, str]:
        """Block until one AMI frame arrives and return it as a ``{header: value}`` dict.

        Public wrapper over the response reader, used by the event listener to
        consume the continuous event stream (after ``Events: on``). Reuses the
        same CRLF framing and buffering as request/response exchanges.

        Raises:
            AMIConnectionError: If the connection is closed by the remote host.
            AMITimeout: If no frame arrives within the socket read timeout while
                the connection is alive (``errno is None``). Timeouts that carry
                an errno (e.g. ETIMEDOUT) re-raise unchanged as real failures.
        """
        try:
            return self._read_response()
        except TimeoutError as exc:
            # A pure socket read timeout (settimeout expiry) has no errno and is
            # an *idle* signal, not a disconnect. An errno-bearing TimeoutError
            # (e.g. ETIMEDOUT) is a real failure — re-raise it unchanged.
            if exc.errno is None:
                msg = "AMI idle: no event within read timeout"
                raise AMITimeout(msg) from exc
            raise

    def _read_response(self) -> dict[str, str]:
        """Read a complete AMI response block (terminated by blank line)."""
        while _END not in self._buffer:
            self._buffer += self._recv()
            self._enforce_frame_bound("AMI frame")
        block, self._buffer = self._buffer.split(_END, 1)

        result: dict[str, str] = {}
        for line in block.split(_CRLF):
            if ": " in line:
                key, value = line.split(": ", 1)
                result[key] = value
        return result

    def _enforce_frame_bound(self, label: str) -> None:
        if len(self._buffer.encode("utf-8")) <= self._config.max_frame_bytes:
            return
        limit = self._config.max_frame_bytes
        self._invalidate_session()
        raise AMIError(f"{label} exceeded the {limit}-byte limit")

    def _invalidate_session(self) -> None:
        """Close transport state without sending another protocol action."""
        if self._sock is not None:
            with suppress(OSError):
                self._sock.close()
        self._sock = None
        self._buffer = ""
        self._connected = False
        self._authenticated = False

    def _recv(self) -> str:
        """Receive data from socket, raise on disconnect."""
        if self._sock is None:
            raise AMIError("Socket closed unexpectedly.")
        data = self._sock.recv(4096)
        if not data:
            self._connected = False
            raise AMIConnectionError("AMI connection closed by remote host.")
        return data.decode("utf-8", errors="replace")

    def _require_connection(self) -> None:
        """Raise if not connected."""
        if not self._connected or self._sock is None:
            raise AMIError("Not connected to AMI. Call connect() first.")

    def _require_auth(self) -> None:
        """Raise if not authenticated."""
        self._require_connection()
        if not self._authenticated:
            raise AMIError("Not authenticated. Call login() first.")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_uptime(date_str: str, time_str: str) -> int:
    """Derive seconds-since from AMI CoreStartupDate/CoreStartupTime.

    AMI returns human-readable strings like ``"2026-04-01"`` and
    ``"10:23:45"``. This function combines them into a UTC-naive
    datetime and returns the elapsed seconds since then.

    Returns ``0`` if either string is empty or parsing fails.
    """
    if not date_str or not time_str:
        return 0
    try:
        from datetime import datetime

        combined = f"{date_str} {time_str}"
        startup = datetime.strptime(combined, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - startup
        return max(int(delta.total_seconds()), 0)
    except (ValueError, TypeError):
        log.debug("Could not parse uptime from %r / %r", date_str, time_str)
        return 0


def _parse_device_state(raw: str) -> DeviceState:
    """Map AMI DeviceState strings to the DeviceState enum."""
    return normalize_device_state(raw)


def _parse_sip_status(raw: str) -> DeviceState:
    """Map SIPpeers Status strings to DeviceState.

    SIPpeers Status examples: "OK (1 ms)", "UNKNOWN", "Unmonitored",
    "UNREACHABLE", "Lagged (123 ms)"
    """
    return normalize_sip_status(raw)
