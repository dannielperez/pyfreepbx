"""Device models.

Devices represent the physical or software endpoints that register
to Asterisk (phones, softphones, ATAs). In FreePBX, devices are
tightly coupled to extensions via the "Device and User Mode" setting,
but at the protocol level they have their own identity (SIP peer, etc.).

These fields are provisional — confirm against your FreePBX version.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel


class DeviceState(str, Enum):
    """Registration states for a SIP/PJSIP device."""

    REGISTERED = "registered"
    UNREGISTERED = "unregistered"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


# The one device-state vocabulary. Asterisk spells the same state several ways
# across AMI actions ("Not in use", "NOT_INUSE", "not in use"), so the lookup is
# keyed on a normalized spelling — never on a substring, which is how
# "not_found" used to be read as an active state.
_DEVICE_STATE_TABLE: dict[str, DeviceState] = {
    "not_inuse": DeviceState.REGISTERED,
    "not_in_use": DeviceState.REGISTERED,
    "inuse": DeviceState.REGISTERED,
    "in_use": DeviceState.REGISTERED,
    "busy": DeviceState.REGISTERED,
    "ringing": DeviceState.REGISTERED,
    "ringinuse": DeviceState.REGISTERED,
    "ring_inuse": DeviceState.REGISTERED,
    "ring_in_use": DeviceState.REGISTERED,
    "onhold": DeviceState.REGISTERED,
    "on_hold": DeviceState.REGISTERED,
    "registered": DeviceState.REGISTERED,
    "reachable": DeviceState.REGISTERED,
    "ok": DeviceState.REGISTERED,
    "avail": DeviceState.REGISTERED,
    "available": DeviceState.REGISTERED,
    "idle": DeviceState.REGISTERED,
    "unregistered": DeviceState.UNREGISTERED,
    "not_found": DeviceState.UNREGISTERED,
    "unreachable": DeviceState.UNREGISTERED,
    "invalid": DeviceState.UNREGISTERED,
    "offline": DeviceState.UNREGISTERED,
    "unavailable": DeviceState.UNAVAILABLE,
    "unknown": DeviceState.UNKNOWN,
    "unmonitored": DeviceState.UNKNOWN,
}

_STATE_SEPARATORS = re.compile(r"[\s-]+")


def normalize_device_state(raw: str | None) -> DeviceState:
    """Map any Asterisk/FreePBX device-state spelling to :class:`DeviceState`.

    The contract: an unrecognized state — including ``None``, ``""`` and any
    spelling not in the table — resolves to ``DeviceState.UNKNOWN``, never to a
    healthy status. A device Asterisk cannot describe is not a registered
    device.
    """
    if not raw:
        return DeviceState.UNKNOWN
    key = _STATE_SEPARATORS.sub("_", raw.strip().lower().replace(",", ""))
    return _DEVICE_STATE_TABLE.get(key, DeviceState.UNKNOWN)


def normalize_sip_status(raw: str | None) -> DeviceState:
    """Map a SIPpeers ``Status`` string to :class:`DeviceState`.

    SIPpeers carries a latency suffix — ``"OK (1 ms)"``, ``"Lagged (123 ms)"`` —
    which is dropped before the shared vocabulary is consulted. "Lagged" is a
    reachable peer, so it maps to ``REGISTERED``; everything unrecognized falls
    through to ``UNKNOWN``.
    """
    if not raw:
        return DeviceState.UNKNOWN
    status = raw.split("(", 1)[0].strip()
    if status.lower().startswith("lagged"):
        return DeviceState.REGISTERED
    return normalize_device_state(status)


class Device(BaseModel):
    """A registered device (SIP peer / PJSIP endpoint).

    This model captures what Asterisk knows at the protocol level.
    For user/extension metadata, see ``Extension``.
    """

    name: str                                # e.g. "PJSIP/1001"
    extension: str | None = None             # linked extension number
    state: DeviceState = DeviceState.UNKNOWN
    ip_address: str | None = None
    user_agent: str | None = None            # e.g. "Yealink SIP-T46U"
    # TODO: Confirm whether device list comes from AMI (SIPpeers/PJSIPShowEndpoints)
    # or GraphQL. AMI is more likely for live registration state.

    model_config = {"extra": "allow"}
