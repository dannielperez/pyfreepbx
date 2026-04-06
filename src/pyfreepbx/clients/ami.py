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
Hangup, ModuleLoad, etc.). This client intentionally restricts the
public surface to **read-only and low-risk actions**. Dangerous actions
are only available through ``run_action()`` which requires explicit
opt-in by the caller.

Actions exposed as typed methods (safe for any consumer):
    Ping, CoreStatus, CoreSettings, CoreShowChannels,
    SIPpeers, SIPshowpeer, PJSIPShowEndpoints, PJSIPShowEndpoint,
    QueueSummary, QueueStatus, QueueAdd, QueueRemove

Actions that should remain in *service* layer logic (not raw client):
    Originate, Redirect, Hangup, Bridge, ModuleLoad/Unload,
    Reload (selective), DBPut/DBGet/DBDel, MailboxCount,
    IAXpeers, ConfbridgeList
"""

from __future__ import annotations

import socket
from typing import Any

from pyfreepbx.clients.base import BaseClient
from pyfreepbx.config import AMIConfig
from pyfreepbx.exceptions import AMIAuthError, AMIConnectionError, AMIError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.queue import QueueStats
from pyfreepbx.models.system import SystemInfo

log = get_logger("clients.ami")

_CRLF = "\r\n"
_END = _CRLF + _CRLF

# Actions considered safe for a public library to expose directly.
# Anything outside this set requires run_action() with explicit intent.
_SAFE_ACTIONS: frozenset[str] = frozenset({
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
    "QueuePause",
    "Command",
})


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
            raise AMIConnectionError(
                f"Failed to connect to AMI at {host}:{port}: {exc}"
            ) from exc

        self._sock = sock
        self._buffer = ""
        self._connected = True
        self._authenticated = False

        self._banner = self._read_line()
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

    def disconnect(self) -> None:
        """Send Logoff action and close the TCP socket.

        Safe to call multiple times or when not connected.
        """
        if self._sock is not None:
            if self._authenticated:
                try:
                    self._send_action("Logoff")
                except OSError:
                    pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._connected = False
        self._authenticated = False
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

    def run_action_with_events(
        self, action: str, **params: Any
    ) -> list[dict[str, str]]:
        """Execute an action that returns multiple events.

        Same as :meth:`run_action` but collects events until the
        ``*Complete`` marker.
        """
        self._require_auth()
        if action not in _SAFE_ACTIONS:
            log.warning("Running non-allowlisted AMI action: %s", action)
        return self._collect_events(action, **params)

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
        self._sock.sendall(message.encode("utf-8"))
        return self._read_response()

    def _collect_events(self, action: str, **params: Any) -> list[dict[str, str]]:
        """Send an action and collect events until the *Complete marker."""
        initial = self._send_action(action, **params)
        if initial.get("Response") != "Success":
            msg = initial.get("Message", f"{action} failed")
            raise AMIError(msg)

        events: list[dict[str, str]] = []
        while True:
            event = self._read_response()
            event_name = event.get("Event", "")
            if event_name.endswith("Complete"):
                break
            events.append(event)

        log.debug("<<< %s returned %d events", action, len(events))
        return events

    def _read_line(self) -> str:
        """Read a single line from the AMI socket."""
        while _CRLF not in self._buffer:
            self._buffer += self._recv()
        line, self._buffer = self._buffer.split(_CRLF, 1)
        return line

    def _read_response(self) -> dict[str, str]:
        """Read a complete AMI response block (terminated by blank line)."""
        while _END not in self._buffer:
            self._buffer += self._recv()
        block, self._buffer = self._buffer.split(_END, 1)

        result: dict[str, str] = {}
        for line in block.split(_CRLF):
            if ": " in line:
                key, value = line.split(": ", 1)
                result[key] = value
        return result

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
    lower = raw.lower()
    if "not_inuse" in lower or "inuse" in lower:
        return DeviceState.REGISTERED
    if "unavailable" in lower:
        return DeviceState.UNAVAILABLE
    if "unknown" in lower:
        return DeviceState.UNKNOWN
    # DeviceState values: NOT_INUSE, INUSE, BUSY, UNAVAILABLE, RINGING, etc.
    # If the device reports any active state, it's registered.
    if lower and lower not in ("unavailable", "unknown"):
        return DeviceState.REGISTERED
    return DeviceState.UNKNOWN


def _parse_sip_status(raw: str) -> DeviceState:
    """Map SIPpeers Status strings to DeviceState.

    SIPpeers Status examples: "OK (1 ms)", "UNKNOWN", "Unmonitored",
    "UNREACHABLE", "Lagged (123 ms)"
    """
    upper = raw.upper()
    if upper.startswith("OK") or upper.startswith("LAGGED"):
        return DeviceState.REGISTERED
    if "UNREACHABLE" in upper:
        return DeviceState.UNREGISTERED
    if "UNKNOWN" in upper or "UNMONITORED" in upper:
        return DeviceState.UNKNOWN
    return DeviceState.UNKNOWN
