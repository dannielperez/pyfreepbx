"""Tests for the shared device-state vocabulary."""

from __future__ import annotations

import pytest

from pyfreepbx.models.device import DeviceState, normalize_device_state, normalize_sip_status


class TestNormalizeDeviceState:
    def test_not_found_is_unregistered(self) -> None:
        # The motivating regression: an endpoint Asterisk cannot find used to
        # fall through a catch-all and report as REGISTERED.
        assert normalize_device_state("not_found") is DeviceState.UNREGISTERED

    def test_unrecognized_state_is_unknown_not_registered(self) -> None:
        result = normalize_device_state("wibble")
        assert result is DeviceState.UNKNOWN
        assert result is not DeviceState.REGISTERED

    @pytest.mark.parametrize("raw", [None, ""])
    def test_empty_is_unknown(self, raw: str | None) -> None:
        assert normalize_device_state(raw) is DeviceState.UNKNOWN

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Not in use", DeviceState.REGISTERED),
            ("NOT_INUSE", DeviceState.REGISTERED),
            ("In use", DeviceState.REGISTERED),
            ("Busy", DeviceState.REGISTERED),
            ("Ringing", DeviceState.REGISTERED),
            ("On Hold", DeviceState.REGISTERED),
            ("Unavailable", DeviceState.UNAVAILABLE),
            ("Invalid", DeviceState.UNREGISTERED),
            ("Unmonitored", DeviceState.UNKNOWN),
        ],
    )
    def test_spelling_families(self, raw: str, expected: DeviceState) -> None:
        assert normalize_device_state(raw) is expected


class TestNormalizeSipStatus:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("OK (1 ms)", DeviceState.REGISTERED),
            ("Lagged (123 ms)", DeviceState.REGISTERED),
            ("UNREACHABLE", DeviceState.UNREGISTERED),
            ("UNKNOWN", DeviceState.UNKNOWN),
            ("Unmonitored", DeviceState.UNKNOWN),
            ("", DeviceState.UNKNOWN),
        ],
    )
    def test_sippeers_vocabulary(self, raw: str, expected: DeviceState) -> None:
        assert normalize_sip_status(raw) is expected
