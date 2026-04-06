"""Device models.

Devices represent the physical or software endpoints that register
to Asterisk (phones, softphones, ATAs). In FreePBX, devices are
tightly coupled to extensions via the "Device and User Mode" setting,
but at the protocol level they have their own identity (SIP peer, etc.).

These fields are provisional — confirm against your FreePBX version.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class DeviceState(str, Enum):
    """Registration states for a SIP/PJSIP device."""

    REGISTERED = "registered"
    UNREGISTERED = "unregistered"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


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
