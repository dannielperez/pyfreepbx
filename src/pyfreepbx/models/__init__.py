"""Pydantic models for pyfreepbx."""

from pyfreepbx.models.device import Device, DeviceState
from pyfreepbx.models.extension import Extension, ExtensionType
from pyfreepbx.models.health import HealthCheck, HealthStatus, HealthSummary
from pyfreepbx.models.queue import Queue, QueueMember, QueueStats
from pyfreepbx.models.system import SystemInfo

__all__ = [
    "Device",
    "DeviceState",
    "Extension",
    "ExtensionType",
    "HealthCheck",
    "HealthStatus",
    "HealthSummary",
    "Queue",
    "QueueMember",
    "QueueStats",
    "SystemInfo",
]
