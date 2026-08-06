"""Pydantic models for pyfreepbx."""

from pyfreepbx.models.asterisk import AsteriskSummary
from pyfreepbx.models.call import ActiveChannel, HangupResult, OriginateResult
from pyfreepbx.models.cdr import CallDetailRecord, CDRListResult
from pyfreepbx.models.device import (
    Device,
    DeviceState,
    normalize_device_state,
    normalize_sip_status,
)
from pyfreepbx.models.endpoint_state import (
    ENDPOINT_STATE_NOT_FOUND,
    ENDPOINT_STATE_TO_DEVICE_STATE,
    normalize_registration_state,
)
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
from pyfreepbx.models.system import ApplyConfigResult, ConfigReloadStatus, SystemInfo

__all__ = [
    "ENDPOINT_STATE_NOT_FOUND",
    "ENDPOINT_STATE_TO_DEVICE_STATE",
    "ActiveChannel",
    "ApplyConfigResult",
    "AsteriskLogLine",
    "AsteriskLogResult",
    "AsteriskSummary",
    "CDRListResult",
    "CallDetailRecord",
    "ConfigReloadStatus",
    "Device",
    "DeviceState",
    "EndpointSummary",
    "Extension",
    "ExtensionType",
    "FirewallNetwork",
    "FirewallZone",
    "HangupResult",
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
    "normalize_device_state",
    "normalize_registration_state",
    "normalize_sip_status",
]
