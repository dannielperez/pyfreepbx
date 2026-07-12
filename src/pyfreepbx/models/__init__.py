"""Pydantic models for pyfreepbx."""

from pyfreepbx.models.asterisk import AsteriskSummary
from pyfreepbx.models.call import OriginateResult
from pyfreepbx.models.cdr import CallDetailRecord, CDRListResult
from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.extension import Extension, ExtensionType
from pyfreepbx.models.firewall import FirewallNetwork, FirewallZone
from pyfreepbx.models.health import (
    EndpointSummary,
    HealthCheck,
    HealthStatus,
    HealthSummary,
    StatusResult,
)
from pyfreepbx.models.inventory import InventoryListResult
from pyfreepbx.models.logs import AsteriskLogLine, AsteriskLogResult
from pyfreepbx.models.queue import Queue, QueueMember, QueueStats
from pyfreepbx.models.system import SystemInfo

__all__ = [
    "AsteriskLogLine",
    "AsteriskLogResult",
    "AsteriskSummary",
    "CDRListResult",
    "CallDetailRecord",
    "Device",
    "DeviceState",
    "EndpointSummary",
    "Extension",
    "ExtensionType",
    "FirewallNetwork",
    "FirewallZone",
    "HealthCheck",
    "HealthStatus",
    "HealthSummary",
    "InventoryListResult",
    "OriginateResult",
    "Queue",
    "QueueMember",
    "QueueStats",
    "StatusResult",
    "SystemInfo",
]
