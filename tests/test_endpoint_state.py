"""Tests for the canonical endpoint-state vocabulary."""

from __future__ import annotations

import pytest

from pyfreepbx import ENDPOINT_STATE_NOT_FOUND
from pyfreepbx.models.device import DeviceState
from pyfreepbx.models.endpoint_state import (
    ENDPOINT_STATE_TO_DEVICE_STATE,
    normalize_registration_state,
)

EXPECTED_ENDPOINT_STATES = {
    "registered": DeviceState.REGISTERED,
    "reachable": DeviceState.REGISTERED,
    "in_use": DeviceState.REGISTERED,
    "ringing": DeviceState.REGISTERED,
    "not_inuse": DeviceState.REGISTERED,
    "idle": DeviceState.REGISTERED,
    "unregistered": DeviceState.UNREGISTERED,
    "not_found": DeviceState.UNREGISTERED,
    "unavailable": DeviceState.UNAVAILABLE,
    "unknown": DeviceState.UNKNOWN,
}


@pytest.mark.parametrize(
    ("state", "expected"),
    EXPECTED_ENDPOINT_STATES.items(),
)
def test_every_endpoint_state_maps_to_expected_device_state(
    state: str,
    expected: DeviceState,
) -> None:
    assert ENDPOINT_STATE_TO_DEVICE_STATE == EXPECTED_ENDPOINT_STATES
    assert normalize_registration_state(state) is expected


@pytest.mark.parametrize("state", ["NOT-INUSE", "Not_InUse", " reachable "])
def test_state_spelling_is_normalized(state: str) -> None:
    assert normalize_registration_state(state) is DeviceState.REGISTERED


@pytest.mark.parametrize("state", ["bogus", "REGISTERED_MAYBE"])
def test_unrecognized_state_is_unknown_and_never_registered(state: str) -> None:
    result = normalize_registration_state(state)

    assert result is DeviceState.UNKNOWN
    assert result is not DeviceState.REGISTERED


@pytest.mark.parametrize("state", [None, ""])
def test_empty_state_is_unknown(state: str | None) -> None:
    assert normalize_registration_state(state) is DeviceState.UNKNOWN


def test_not_found_is_public_and_unregistered() -> None:
    assert ENDPOINT_STATE_NOT_FOUND == "not_found"
    assert normalize_registration_state(ENDPOINT_STATE_NOT_FOUND) is DeviceState.UNREGISTERED
