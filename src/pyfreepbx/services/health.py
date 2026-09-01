"""Health service — operational visibility across PBX interfaces.

Combines data from GraphQL (config/inventory) and AMI (live state)
to provide a unified operational view. Degrades gracefully when AMI
is not configured — AMI-dependent methods return ``None`` and log
a clear warning instead of raising.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyfreepbx.exceptions import AMIError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.health import (
    AsteriskDetails,
    DiskSpace,
    EndpointSnapshot,
    EndpointSummary,
    HealthCheck,
    HealthStatus,
    HealthSummary,
)

if TYPE_CHECKING:
    from pyfreepbx.clients.ami import AMIClient
    from pyfreepbx.clients.freepbx import FreePBXClient
    from pyfreepbx.models.queue import QueueStats
    from pyfreepbx.models.system import SystemInfo

log = get_logger("services.health")


class HealthService:
    """Operational health and monitoring for FreePBX/Asterisk.

    All methods degrade gracefully when AMI is not available:

    * Methods that require only GraphQL always work.
    * Methods that require AMI return ``None`` (not raise) when
      AMI is unconfigured, allowing callers to handle partial data.
    * :meth:`summary` always returns a :class:`HealthSummary` —
      it simply omits AMI checks when unavailable.
    """

    def __init__(self, client: FreePBXClient, ami: AMIClient | None = None) -> None:
        self._client = client
        self._ami = ami

    def _ensure_ami_session(self) -> bool:
        """Connect + authenticate the AMI client on demand.

        The service receives a *configured but unconnected* :class:`AMIClient`
        (the facade wires it lazily), so every AMI-backed method funnels
        through here — callers never manage the session themselves. Before
        this existed, ``_check_ami``/``endpoint_summary`` pinged an
        unconnected socket and every AMI-configured health check reported
        DOWN ("Not connected to AMI. Call connect() first."), observed live
        2026-07-11.

        Returns ``False`` when AMI is unconfigured. Raises the underlying
        ``AMIError``/``AMIAuthError``/``OSError`` when a configured session
        cannot be established — callers decide whether that is a graceful
        ``None`` or a failed health check.
        """
        if self._ami is None:
            return False
        if not self._ami.connected:
            self._ami.connect()
        if not self._ami.authenticated:
            self._ami.login(events=False)
        return True

    # ------------------------------------------------------------------
    # Aggregate health
    # ------------------------------------------------------------------

    def summary(self) -> HealthSummary:
        """Run health probes against all configured interfaces.

        Returns a :class:`HealthSummary` with per-check results.
        AMI checks are skipped (not failed) when AMI is unconfigured.
        """
        checks: list[HealthCheck] = []

        checks.append(self._check_graphql())

        if self._ami is not None:
            checks.append(self._check_ami())

        return HealthSummary.from_checks(checks)

    # ------------------------------------------------------------------
    # PBX summary
    # ------------------------------------------------------------------

    def pbx_info(self) -> SystemInfo | None:
        """Fetch core Asterisk system info (version, calls, uptime).

        Returns:
            :class:`SystemInfo` if AMI is available, ``None`` otherwise.
        """
        try:
            if not self._ensure_ami_session():
                log.warning("pbx_info requires AMI — skipping.")
                return None
            return self._ami.core_status()
        except Exception as exc:
            log.error("Failed to fetch PBX info: %s", exc)
            return None

    def disk_space(self) -> list[DiskSpace]:
        """Fetch filesystem utilization through the Dashboard GraphQL module."""
        return [DiskSpace.model_validate(row) for row in self._client.check_disk_space()]

    def asterisk_details(self) -> AsteriskDetails:
        """Fetch Asterisk/AMI state through the FreePBX System GraphQL query."""
        row = self._client.fetch_asterisk_details()
        return AsteriskDetails(
            running_status=str(row.get("asteriskStatus") or ""),
            version=str(row.get("asteriskVersion") or ""),
            ami_status=str(row.get("amiStatus") or ""),
        )

    # ------------------------------------------------------------------
    # Endpoint registration
    # ------------------------------------------------------------------

    def endpoint_snapshot(self) -> EndpointSnapshot:
        """Fetch one typed endpoint snapshot with an explicit completeness signal.

        Expected AMI transport/authentication failures become an incomplete
        result. Process-control exceptions are not swallowed.
        """
        try:
            if not self._ensure_ami_session():
                error = "AMI is not configured"
                log.warning("endpoint_snapshot requires AMI — skipping.")
                return EndpointSnapshot(error=error)
            devices = self._ami.pjsip_endpoints()
        except (AMIError, OSError) as exc:
            log.error("Failed to fetch endpoints: %s", exc)
            return EndpointSnapshot(error=str(exc) or "AMI endpoint fetch failed")

        counts: dict[DeviceState, int] = {s: 0 for s in DeviceState}
        for d in devices:
            counts[d.state] = counts.get(d.state, 0) + 1

        return EndpointSnapshot(
            items=devices,
            summary=EndpointSummary(
                total=len(devices),
                registered=counts[DeviceState.REGISTERED],
                unregistered=counts[DeviceState.UNREGISTERED],
                unavailable=counts[DeviceState.UNAVAILABLE],
                unknown=counts[DeviceState.UNKNOWN],
            ),
            complete=True,
        )

    def endpoint_summary(self) -> EndpointSummary | None:
        """Aggregate endpoint registration counts, or ``None`` if incomplete."""
        snapshot = self.endpoint_snapshot()
        return snapshot.summary if snapshot.complete else None

    def unregistered_endpoints(self) -> list[Device] | None:
        """List endpoints that are not currently registered.

        Useful for alerting on phones that have gone offline.

        Returns:
            List of :class:`Device` with state UNREGISTERED or
            UNAVAILABLE, or ``None`` if AMI is unavailable.
        """
        snapshot = self.endpoint_snapshot()
        if not snapshot.complete:
            return None

        offline = [
            d
            for d in snapshot.items
            if d.state in (DeviceState.UNREGISTERED, DeviceState.UNAVAILABLE)
        ]
        log.debug("%d of %d endpoints offline", len(offline), len(snapshot.items))
        return offline

    # ------------------------------------------------------------------
    # Queue / agent overview
    # ------------------------------------------------------------------

    def queue_overview(self) -> list[QueueStats] | None:
        """Fetch live stats for all queues.

        Returns:
            List of :class:`QueueStats`, or ``None`` if AMI is unavailable.
        """
        try:
            if not self._ensure_ami_session():
                log.warning("queue_overview requires AMI — skipping.")
                return None
            return self._ami.queue_summary()
        except Exception as exc:
            log.error("Failed to fetch queue overview: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal probes
    # ------------------------------------------------------------------

    def _check_graphql(self) -> HealthCheck:
        try:
            self._client.graphql.query("{ __typename }")
            return HealthCheck(name="graphql", status=HealthStatus.OK)
        except Exception as exc:
            return HealthCheck(
                name="graphql",
                status=HealthStatus.DOWN,
                detail=str(exc),
            )

    def _check_ami(self) -> HealthCheck:
        try:
            if not self._ensure_ami_session():
                return HealthCheck(name="ami", status=HealthStatus.DOWN, detail="Not configured")
            if self._ami.ping():
                return HealthCheck(name="ami", status=HealthStatus.OK)
            return HealthCheck(
                name="ami",
                status=HealthStatus.DEGRADED,
                detail="Ping returned non-success response",
            )
        except Exception as exc:
            return HealthCheck(
                name="ami",
                status=HealthStatus.DOWN,
                detail=str(exc),
            )
