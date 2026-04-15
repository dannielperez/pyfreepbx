"""Health check models.

Separated from system.py so health checks can be extended independently
(e.g. adding check for database connectivity, SIP trunk registration, etc.)
without bloating the system info model.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class HealthCheck(BaseModel):
    """Result of a single health check probe."""

    name: str
    status: HealthStatus
    detail: str = ""


class HealthSummary(BaseModel):
    """Aggregated result of all health checks."""

    overall: HealthStatus
    checks: list[HealthCheck]

    @classmethod
    def from_checks(cls, checks: list[HealthCheck]) -> HealthSummary:
        if any(c.status == HealthStatus.DOWN for c in checks):
            overall = HealthStatus.DOWN
        elif any(c.status == HealthStatus.DEGRADED for c in checks):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.OK
        return cls(overall=overall, checks=checks)


class EndpointSummary(BaseModel):
    """Aggregated view of endpoint registration state."""

    total: int = 0
    registered: int = 0
    unregistered: int = 0
    unavailable: int = 0
    unknown: int = 0


class StatusResult(BaseModel):
    """Combined status snapshot from a FreePBX instance.

    Returned by ``FreePBX.status()``. Bundles health, extension,
    and queue information into a single result.
    """

    ok: bool = False
    error: str = ""
    health: HealthSummary | None = None
    extensions: list = []
    extension_count: int = 0
    queues: list = []
    queue_count: int = 0
    endpoints: EndpointSummary | None = None
