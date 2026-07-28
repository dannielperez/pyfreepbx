"""Typed AMI event DTOs for the event listener.

Faithful, **stateless** representations of the Asterisk Manager Interface (AMI)
events the snapshot-on-call listener consumes. Parsing/normalization lives in
:mod:`pyfreepbx.clients.ami_parser`; correlation *state* (call sessions, the
``ActionID``→``Uniqueid`` map) belongs to the consuming application, never here.

Design rules (validated against real PBX capture, 2026-06-17):

* ``linkedid`` is the call/session correlation key; ``uniqueid`` is per-leg.
* ``linkedid`` is exposed on **every** event but is ``None`` when the source
  frame omits it (``OriginateResponse``) or splits it by role (transfers). It is
  **never fabricated** — the consumer resolves the gap.
* Hangup ``cause`` is metadata only; call *disposition* is derived from the event
  sequence by the consumer, not from cause codes.
* Each DTO mirrors one AMI event name. Events this library does not model are
  surfaced faithfully as :class:`UnknownEvent` (carrying the full ``raw`` frame),
  never dropped.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AMIEvent(BaseModel):
    """Base for every parsed AMI event.

    ``raw`` retains the complete original frame so consumers can read fields this
    library has not promoted to typed attributes.
    """

    event: str
    received_at: float
    uniqueid: str | None = None
    linkedid: str | None = None
    channel: str | None = None
    raw: dict[str, str] = Field(default_factory=dict)


class UnknownEvent(AMIEvent):
    """Any AMI event the parser does not model (``VarSet``, ``RTCP*``, status…)."""


# ----------------------------------------------------------------------
# Channel lifecycle
# ----------------------------------------------------------------------


class NewchannelEvent(AMIEvent):
    """A channel was created — ``Newchannel``."""

    channel_state_desc: str | None = None
    caller_id_num: str | None = None
    exten: str | None = None
    context: str | None = None


class NewstateEvent(AMIEvent):
    """A channel changed state — ``Newstate`` (state 5 = Ringing, 6 = Up)."""

    channel_state: str | None = None
    channel_state_desc: str | None = None


class NewConnectedLineEvent(AMIEvent):
    """A channel learned updated caller/connected-line identity."""

    channel_state: str | None = None
    channel_state_desc: str | None = None
    caller_id_num: str | None = None
    caller_id_name: str | None = None
    connected_line_num: str | None = None
    connected_line_name: str | None = None
    exten: str | None = None
    context: str | None = None


class HangupEvent(AMIEvent):
    """A channel was torn down — ``Hangup``.

    ``cause``/``cause_txt`` are **metadata only** — they do not determine
    disposition (a normal answered hangup and a queue abandon both report
    ``cause 16``). See the reconciliation report Δ2.
    """

    cause: str | None = None
    cause_txt: str | None = None


# ----------------------------------------------------------------------
# Dial / bridge
# ----------------------------------------------------------------------


class DialBeginEvent(AMIEvent):
    """A dial attempt started — ``DialBegin``."""

    dest_channel: str | None = None
    dest_uniqueid: str | None = None
    dial_string: str | None = None


class DialEndEvent(AMIEvent):
    """A dial attempt concluded — ``DialEnd``.

    ``dial_status`` (``ANSWER``/``NOANSWER``/``CANCEL``/``BUSY``/``CONGESTION``)
    is the primary direct-call disposition signal.
    """

    dial_status: str | None = None
    dest_channel: str | None = None
    dest_uniqueid: str | None = None


class BridgeEnterEvent(AMIEvent):
    """A channel entered a bridge — ``BridgeEnter`` (direct-call answer signal)."""

    bridge_uniqueid: str | None = None
    bridge_technology: str | None = None


# ----------------------------------------------------------------------
# Queue / agent
# ----------------------------------------------------------------------


class QueueCallerJoinEvent(AMIEvent):
    """A caller entered a queue — ``QueueCallerJoin`` (inbound snapshot trigger)."""

    queue: str | None = None
    position: str | None = None
    count: str | None = None


class QueueCallerAbandonEvent(AMIEvent):
    """A caller left the queue before answer — ``QueueCallerAbandon`` (ABANDONED)."""

    queue: str | None = None
    position: str | None = None
    original_position: str | None = None
    hold_time: str | None = None


class AgentCalledEvent(AMIEvent):
    """A queue member is being rung — ``AgentCalled``."""

    queue: str | None = None
    interface: str | None = None
    member_name: str | None = None


class AgentRingNoAnswerEvent(AMIEvent):
    """A rung queue member did not answer this cycle — ``AgentRingNoAnswer``."""

    queue: str | None = None
    interface: str | None = None
    member_name: str | None = None
    ring_time: str | None = None


class AgentConnectEvent(AMIEvent):
    """A queue member answered — ``AgentConnect`` (queue answer signal)."""

    queue: str | None = None
    interface: str | None = None
    member_name: str | None = None
    hold_time: str | None = None
    ring_time: str | None = None
    dest_channel: str | None = None
    dest_uniqueid: str | None = None


class AgentCompleteEvent(AMIEvent):
    """A queue call ended — ``AgentComplete``."""

    queue: str | None = None
    interface: str | None = None
    member_name: str | None = None
    hold_time: str | None = None
    talk_time: str | None = None
    reason: str | None = None


# ----------------------------------------------------------------------
# Originate (the ActionID→Uniqueid bridge)
# ----------------------------------------------------------------------


class OriginateResponseEvent(AMIEvent):
    """An async ``Originate`` concluded — ``OriginateResponse``.

    The **only** AMI event carrying ``ActionID``. It carries both ``action_id``
    and ``uniqueid`` — the bridge a consumer uses to map its originate
    ``ActionID`` to the call's ``uniqueid``. This frame has **no** ``Linkedid``
    (``linkedid`` stays ``None``); the consumer resolves it from the originated
    channel. ``reason`` codes: ``4`` = answered, ``5`` = busy, ``8`` =
    congestion, ``0``/``1`` = no-answer/cancel.
    """

    action_id: str | None = None
    response: str | None = None
    reason: str | None = None
    caller_id_num: str | None = None


# ----------------------------------------------------------------------
# Transfers — SYNTHETIC: shapes verified against the Asterisk 16 spec, not
# against this deployment (operators do not transfer). linkedid is carried
# per-role, never as a single top-level value; an attended transfer merges two
# linkedids — that merge is the consumer's responsibility.
# ----------------------------------------------------------------------


class BlindTransferEvent(AMIEvent):
    """A blind transfer occurred — ``BlindTransfer`` (synthetic-verified)."""

    result: str | None = None
    transferer_uniqueid: str | None = None
    transferer_linkedid: str | None = None
    transferee_uniqueid: str | None = None
    transferee_linkedid: str | None = None
    extension: str | None = None


class AttendedTransferEvent(AMIEvent):
    """An attended transfer occurred — ``AttendedTransfer`` (synthetic-verified)."""

    result: str | None = None
    orig_transferer_uniqueid: str | None = None
    orig_transferer_linkedid: str | None = None
    second_transferer_uniqueid: str | None = None
    second_transferer_linkedid: str | None = None
    transferee_uniqueid: str | None = None
    transferee_linkedid: str | None = None
    transfer_target_uniqueid: str | None = None
    transfer_target_linkedid: str | None = None
    dest_type: str | None = None


__all__ = [
    "AMIEvent",
    "AgentCalledEvent",
    "AgentCompleteEvent",
    "AgentConnectEvent",
    "AgentRingNoAnswerEvent",
    "AttendedTransferEvent",
    "BlindTransferEvent",
    "BridgeEnterEvent",
    "DialBeginEvent",
    "DialEndEvent",
    "HangupEvent",
    "NewConnectedLineEvent",
    "NewchannelEvent",
    "NewstateEvent",
    "OriginateResponseEvent",
    "QueueCallerAbandonEvent",
    "QueueCallerJoinEvent",
    "UnknownEvent",
]
