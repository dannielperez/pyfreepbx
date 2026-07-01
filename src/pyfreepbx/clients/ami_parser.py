"""Pure AMI-frame → typed-DTO parsing for the event listener.

A single pure function, :func:`parse_event`, maps one parsed AMI frame (a
``{header: value}`` dict, as produced by the AMI transport) to a typed
:class:`~pyfreepbx.models.events.AMIEvent`. It has **no I/O and no state** — all
correlation state belongs to the consumer.

Normalization rules (see :mod:`pyfreepbx.models.events`):

* ``uniqueid``/``linkedid``/``channel`` are read from the frame when present and
  left ``None`` otherwise — **never fabricated**.
* Frames whose ``Event`` name is not modelled become :class:`UnknownEvent`,
  carrying the full ``raw`` frame (faithful passthrough, never dropped).
"""

from __future__ import annotations

from typing import Any

from pyfreepbx.models.events import (
    AgentCalledEvent,
    AgentCompleteEvent,
    AgentConnectEvent,
    AgentRingNoAnswerEvent,
    AMIEvent,
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

# AMI event name -> (DTO class, {dto_attribute: AMI header}). Base attributes
# (uniqueid/linkedid/channel) are mapped generically and are NOT repeated here.
_FIELD_MAP: dict[str, tuple[type[AMIEvent], dict[str, str]]] = {
    "Newchannel": (
        NewchannelEvent,
        {
            "channel_state_desc": "ChannelStateDesc",
            "caller_id_num": "CallerIDNum",
            "exten": "Exten",
            "context": "Context",
        },
    ),
    "Newstate": (
        NewstateEvent,
        {"channel_state": "ChannelState", "channel_state_desc": "ChannelStateDesc"},
    ),
    "Hangup": (HangupEvent, {"cause": "Cause", "cause_txt": "Cause-txt"}),
    "DialBegin": (
        DialBeginEvent,
        {
            "dest_channel": "DestChannel",
            "dest_uniqueid": "DestUniqueid",
            "dial_string": "DialString",
        },
    ),
    "DialEnd": (
        DialEndEvent,
        {
            "dial_status": "DialStatus",
            "dest_channel": "DestChannel",
            "dest_uniqueid": "DestUniqueid",
        },
    ),
    "BridgeEnter": (
        BridgeEnterEvent,
        {"bridge_uniqueid": "BridgeUniqueid", "bridge_technology": "BridgeTechnology"},
    ),
    "QueueCallerJoin": (
        QueueCallerJoinEvent,
        {"queue": "Queue", "position": "Position", "count": "Count"},
    ),
    "QueueCallerAbandon": (
        QueueCallerAbandonEvent,
        {
            "queue": "Queue",
            "position": "Position",
            "original_position": "OriginalPosition",
            "hold_time": "HoldTime",
        },
    ),
    "AgentCalled": (
        AgentCalledEvent,
        {"queue": "Queue", "interface": "Interface", "member_name": "MemberName"},
    ),
    "AgentRingNoAnswer": (
        AgentRingNoAnswerEvent,
        {
            "queue": "Queue",
            "interface": "Interface",
            "member_name": "MemberName",
            "ring_time": "RingTime",
        },
    ),
    "AgentConnect": (
        AgentConnectEvent,
        {
            "queue": "Queue",
            "interface": "Interface",
            "member_name": "MemberName",
            "hold_time": "HoldTime",
            "ring_time": "RingTime",
            "dest_channel": "DestChannel",
            "dest_uniqueid": "DestUniqueid",
        },
    ),
    "AgentComplete": (
        AgentCompleteEvent,
        {
            "queue": "Queue",
            "interface": "Interface",
            "member_name": "MemberName",
            "hold_time": "HoldTime",
            "talk_time": "TalkTime",
            "reason": "Reason",
        },
    ),
    "OriginateResponse": (
        OriginateResponseEvent,
        {
            "action_id": "ActionID",
            "response": "Response",
            "reason": "Reason",
            "caller_id_num": "CallerIDNum",
        },
    ),
    "BlindTransfer": (
        BlindTransferEvent,
        {
            "result": "Result",
            "transferer_uniqueid": "TransfererUniqueid",
            "transferer_linkedid": "TransfererLinkedid",
            "transferee_uniqueid": "TransfereeUniqueid",
            "transferee_linkedid": "TransfereeLinkedid",
            "extension": "Extension",
        },
    ),
    "AttendedTransfer": (
        AttendedTransferEvent,
        {
            "result": "Result",
            "orig_transferer_uniqueid": "OrigTransfererUniqueid",
            "orig_transferer_linkedid": "OrigTransfererLinkedid",
            "second_transferer_uniqueid": "SecondTransfererUniqueid",
            "second_transferer_linkedid": "SecondTransfererLinkedid",
            "transferee_uniqueid": "TransfereeUniqueid",
            "transferee_linkedid": "TransfereeLinkedid",
            "transfer_target_uniqueid": "TransferTargetUniqueid",
            "transfer_target_linkedid": "TransferTargetLinkedid",
            "dest_type": "DestType",
        },
    ),
}

# Event names this library models. Exposed so the listener's noise filter and
# consumers can reason about coverage without importing the map.
KNOWN_EVENTS: frozenset[str] = frozenset(_FIELD_MAP)


def parse_event(raw: dict[str, str], received_at: float) -> AMIEvent:
    """Parse one AMI frame into a typed event.

    Args:
        raw: The frame as ``{header: value}`` (from the AMI transport).
        received_at: Listener arrival time (epoch seconds) — AMI carries no
            native event timestamp, so the listener stamps it.

    Returns:
        A typed :class:`AMIEvent` subclass for modelled events, else
        :class:`UnknownEvent`. ``uniqueid``/``linkedid``/``channel`` are taken
        from the frame when present and ``None`` otherwise.
    """
    name = raw.get("Event", "")
    kwargs: dict[str, Any] = {
        "event": name,
        "received_at": received_at,
        "uniqueid": raw.get("Uniqueid"),
        "linkedid": raw.get("Linkedid"),
        "channel": raw.get("Channel"),
        "raw": raw,
    }

    mapping = _FIELD_MAP.get(name)
    if mapping is None:
        return UnknownEvent(**kwargs)

    cls, field_map = mapping
    for attr, header in field_map.items():
        kwargs[attr] = raw.get(header)
    return cls(**kwargs)


__all__ = ["KNOWN_EVENTS", "parse_event"]
