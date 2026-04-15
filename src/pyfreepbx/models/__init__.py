"""Pydantic models for pyfreepbx."""

from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.extension import Extension, ExtensionType
from pyfreepbx.models.health import (
    EndpointSummary,
    HealthCheck,
    HealthStatus,
    HealthSummary,
    StatusResult,
)
from pyfreepbx.models.queue import Queue, QueueMember, QueueStats
from pyfreepbx.models.system import SystemInfo

__all__ = [
    "Device",
    "DeviceState",
    "EndpointSummary",
    "Extension",
    "ExtensionType",
    "HealthCheck",
    "HealthStatus",
    "HealthSummary",
    "Queue",
    "QueueMember",
    "QueueStats",
    "StatusResult",
    "SystemInfo",
]
