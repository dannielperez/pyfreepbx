"""Health service — operational visibility across PBX interfaces.

Combines data from GraphQL (config/inventory) and AMI (live state)
to provide a unified operational view. Degrades gracefully when AMI
is not configured — AMI-dependent methods return ``None`` and log
a clear warning instead of raising.
"""

from __future__ import annotations

from pyfreepbx.clients.ami import AMIClient
from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.logging import get_logger
from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.health import (
    EndpointSummary,
    HealthCheck,
    HealthStatus,
    HealthSummary,
)
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
        if self._ami is None:
            log.warning("pbx_info requires AMI — skipping.")
            return None
        try:
            return self._ami.core_status()
        except Exception as exc:
            log.error("Failed to fetch PBX info: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Endpoint registration
    # ------------------------------------------------------------------

    def endpoint_summary(self) -> EndpointSummary | None:
        """Aggregate endpoint registration counts.

        Returns:
            :class:`EndpointSummary` with totals per state,
            or ``None`` if AMI is unavailable.
        """
        if self._ami is None:
            log.warning("endpoint_summary requires AMI — skipping.")
            return None

        try:
            devices = self._ami.pjsip_endpoints()
        except Exception as exc:
            log.error("Failed to fetch endpoints: %s", exc)
            return None

        counts: dict[DeviceState, int] = {s: 0 for s in DeviceState}
        for d in devices:
            counts[d.state] = counts.get(d.state, 0) + 1

        return EndpointSummary(
            total=len(devices),
            registered=counts[DeviceState.REGISTERED],
            unregistered=counts[DeviceState.UNREGISTERED],
            unavailable=counts[DeviceState.UNAVAILABLE],
            unknown=counts[DeviceState.UNKNOWN],
        )

    def unregistered_endpoints(self) -> list[Device] | None:
        """List endpoints that are not currently registered.

        Useful for alerting on phones that have gone offline.

        Returns:
            List of :class:`Device` with state UNREGISTERED or
            UNAVAILABLE, or ``None`` if AMI is unavailable.
        """
        if self._ami is None:
            log.warning("unregistered_endpoints requires AMI — skipping.")
            return None

        try:
            devices = self._ami.pjsip_endpoints()
        except Exception as exc:
            log.error("Failed to fetch endpoints: %s", exc)
            return None

        offline = [
            d for d in devices
            if d.state in (DeviceState.UNREGISTERED, DeviceState.UNAVAILABLE)
        ]
        log.debug("%d of %d endpoints offline", len(offline), len(devices))
        return offline

    # ------------------------------------------------------------------
    # Queue / agent overview
    # ------------------------------------------------------------------

    def queue_overview(self) -> list[QueueStats] | None:
        """Fetch live stats for all queues.

        Returns:
            List of :class:`QueueStats`, or ``None`` if AMI is unavailable.
        """
        if self._ami is None:
            log.warning("queue_overview requires AMI — skipping.")
            return None

        try:
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
            if self._ami is None:
                return HealthCheck(
                    name="ami", status=HealthStatus.DOWN, detail="Not configured"
                )
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
