"""Tests for AMI frame → typed DTO parsing.

Each modelled event is parsed from a real captured fixture block and checked for
the correct DTO type and key fields. Transfer events use synthetic (spec-derived)
fixtures and are marked ``xfail(strict=False)`` — non-blocking for S3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyfreepbx.clients.ami_parser import KNOWN_EVENTS, parse_event
from pyfreepbx.models.events import (
    AgentCompleteEvent,
    AgentConnectEvent,
    AttendedTransferEvent,
    BlindTransferEvent,
    BridgeEnterEvent,
    DialBeginEvent,
    DialEndEvent,
    HangupEvent,
    NewchannelEvent,
    NewstateEvent,
    OriginateResponseEvent,
    QueueCallerAbandonEvent,
    QueueCallerJoinEvent,
    UnknownEvent,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ami"

# Transfer fixtures are spec-derived, not captured (operators on the target PBX
# do not transfer). Their tests are xfail(strict=False) — explicit, non-blocking.
_SYNTHETIC = "synthetic fixture; shape unverified against a real PBX"


def _frames(name: str) -> list[dict[str, str]]:
    """Parse a fixture file into AMI frame dicts (CRLF-faithful)."""
    text = (FIXTURES / name).read_bytes().decode("utf-8")
    frames: list[dict[str, str]] = []
    for block in text.split("\r\n\r\n"):
        if not block.strip():
            continue
        frame: dict[str, str] = {}
        for line in block.split("\r\n"):
            if ": " in line:
                key, value = line.split(": ", 1)
                frame.setdefault(key, value)
        frames.append(frame)
    return frames


def _first(name: str, event: str) -> dict[str, str]:
    for frame in _frames(name):
        if frame.get("Event") == event:
            return frame
    raise AssertionError(f"no {event} event in {name}")


def _parse_first(name: str, event: str):
    return parse_event(_first(name, event), received_at=123.0)


class TestChannelLifecycle:
    def test_newchannel(self) -> None:
        ev = _parse_first("answered.txt", "Newchannel")
        assert isinstance(ev, NewchannelEvent)
        assert ev.uniqueid and ev.linkedid and ev.channel
        assert ev.channel_state_desc
        assert ev.received_at == 123.0

    def test_newstate_ringing(self) -> None:
        frame = next(
            f
            for f in _frames("answered.txt")
            if f.get("Event") == "Newstate" and f.get("ChannelStateDesc") == "Ringing"
        )
        ev = parse_event(frame, received_at=1.0)
        assert isinstance(ev, NewstateEvent)
        assert ev.channel_state == "5"
        assert ev.channel_state_desc == "Ringing"

    def test_hangup_cause_is_metadata(self) -> None:
        ev = _parse_first("answered.txt", "Hangup")
        assert isinstance(ev, HangupEvent)
        assert ev.cause is not None  # present, but it does not drive disposition
        assert ev.cause_txt is not None
        assert ev.linkedid


class TestDialBridge:
    def test_dial_begin(self) -> None:
        ev = _parse_first("answered.txt", "DialBegin")
        assert isinstance(ev, DialBeginEvent)
        assert ev.dest_uniqueid
        assert ev.dial_string  # carries the dialed target (sanitized)

    def test_dial_end_answer(self) -> None:
        ev = _parse_first("answered.txt", "DialEnd")
        assert isinstance(ev, DialEndEvent)
        assert ev.dial_status == "ANSWER"

    def test_dial_end_noanswer(self) -> None:
        ev = _parse_first("missed.txt", "DialEnd")
        assert isinstance(ev, DialEndEvent)
        assert ev.dial_status == "NOANSWER"

    def test_bridge_enter(self) -> None:
        ev = _parse_first("answered.txt", "BridgeEnter")
        assert isinstance(ev, BridgeEnterEvent)
        assert ev.bridge_uniqueid


class TestQueue:
    def test_queue_caller_join(self) -> None:
        ev = _parse_first("queue.txt", "QueueCallerJoin")
        assert isinstance(ev, QueueCallerJoinEvent)
        assert ev.queue and ev.position
        assert ev.uniqueid == ev.linkedid  # caller channel is the call root

    def test_agent_connect(self) -> None:
        ev = _parse_first("queue.txt", "AgentConnect")
        assert isinstance(ev, AgentConnectEvent)
        assert ev.queue and ev.interface and ev.member_name
        assert ev.hold_time is not None and ev.ring_time is not None
        assert ev.dest_uniqueid

    def test_agent_complete(self) -> None:
        ev = _parse_first("queue.txt", "AgentComplete")
        assert isinstance(ev, AgentCompleteEvent)
        assert ev.talk_time is not None
        assert ev.reason in {"caller", "agent", "transfer"}

    def test_queue_caller_abandon(self) -> None:
        ev = _parse_first("abandoned.txt", "QueueCallerAbandon")
        assert isinstance(ev, QueueCallerAbandonEvent)
        assert ev.queue and ev.hold_time is not None and ev.position


class TestOriginate:
    def test_originate_response_is_actionid_uniqueid_bridge(self) -> None:
        ev = _parse_first("originate.txt", "OriginateResponse")
        assert isinstance(ev, OriginateResponseEvent)
        # the only event carrying ActionID, alongside Uniqueid:
        assert ev.action_id
        assert ev.uniqueid
        assert ev.reason == "4"  # answered

    def test_originate_response_has_no_linkedid(self) -> None:
        # OriginateResponse carries no Linkedid header — must NOT be fabricated.
        ev = _parse_first("originate.txt", "OriginateResponse")
        assert ev.linkedid is None


class TestNormalizationAndUnknown:
    def test_unknown_event_passthrough(self) -> None:
        # NewConnectedLine is not modelled -> UnknownEvent, raw preserved.
        ev = _parse_first("answered.txt", "NewConnectedLine")
        assert isinstance(ev, UnknownEvent)
        assert ev.event == "NewConnectedLine"
        assert ev.raw["Event"] == "NewConnectedLine"

    def test_unmodelled_keeps_base_correlation_fields(self) -> None:
        ev = _parse_first("answered.txt", "NewConnectedLine")
        assert ev.uniqueid and ev.linkedid  # base fields still normalized

    def test_linkedid_present_on_standard_events(self) -> None:
        for event in ("Newchannel", "DialEnd", "BridgeEnter", "Hangup"):
            assert _parse_first("answered.txt", event).linkedid is not None

    def test_every_known_event_name_has_a_dto(self) -> None:
        # guards the parser map against silent drift
        assert {"Newchannel", "DialEnd", "AgentConnect", "OriginateResponse"} <= KNOWN_EVENTS


class TestTransfersSynthetic:
    """Transfer fixtures are spec-derived (operators don't transfer on this PBX).

    These validate the parser shape only; marked xfail(strict=False) so they are
    explicit and non-blocking for S3, never gating a merge.
    """

    @pytest.mark.xfail(reason=_SYNTHETIC, strict=False)
    def test_blind_transfer(self) -> None:
        ev = _parse_first("transfer_blind.txt", "BlindTransfer")
        assert isinstance(ev, BlindTransferEvent)
        assert ev.result == "Success"
        assert ev.transferer_uniqueid and ev.transferee_uniqueid
        assert ev.extension  # blind target
        assert ev.linkedid is None  # carried per-role, not top-level
        assert ev.transferer_linkedid and ev.transferee_linkedid

    @pytest.mark.xfail(reason=_SYNTHETIC, strict=False)
    def test_attended_transfer(self) -> None:
        ev = _parse_first("transfer_attended.txt", "AttendedTransfer")
        assert isinstance(ev, AttendedTransferEvent)
        assert ev.result == "Success"
        # attended transfer ties two calls together (consumer merges the linkedids)
        assert ev.orig_transferer_linkedid and ev.second_transferer_linkedid
        assert ev.transferee_uniqueid and ev.transfer_target_uniqueid
        assert ev.dest_type
        assert ev.linkedid is None
