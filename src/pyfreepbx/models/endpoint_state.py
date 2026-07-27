"""Canonical FreePBX/Asterisk endpoint-state vocabulary."""

from __future__ import annotations

from pyfreepbx.models.device import DeviceState

ENDPOINT_STATE_NOT_FOUND = "not_found"

ENDPOINT_STATE_TO_DEVICE_STATE: dict[str, DeviceState] = {
    "registered": DeviceState.REGISTERED,
    "reachable": DeviceState.REGISTERED,
    "in_use": DeviceState.REGISTERED,
    "ringing": DeviceState.REGISTERED,
    "not_inuse": DeviceState.REGISTERED,
    "idle": DeviceState.REGISTERED,
    "unregistered": DeviceState.UNREGISTERED,
    ENDPOINT_STATE_NOT_FOUND: DeviceState.UNREGISTERED,
    "unavailable": DeviceState.UNAVAILABLE,
    "unknown": DeviceState.UNKNOWN,
}


def normalize_registration_state(state: str | None) -> DeviceState:
    """Map a FreePBX/Asterisk endpoint state onto a ``DeviceState``.

    State spelling is case- and separator-normalized before lookup. A state
    outside the vendor vocabulary degrades to UNKNOWN, never to the healthy
    REGISTERED state.
    """
    key = (state or "").strip().lower().replace("-", "_")
    return ENDPOINT_STATE_TO_DEVICE_STATE.get(key, DeviceState.UNKNOWN)
