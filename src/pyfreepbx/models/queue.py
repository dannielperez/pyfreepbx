"""Queue models.

Config fields (Queue, QueueMember) come from the FreePBX GraphQL API
and may vary by version. Stats fields (QueueStats) come from AMI
QueueSummary/QueueStatus actions — these are well-documented in
Asterisk and stable across versions.
"""

from __future__ import annotations

from pydantic import BaseModel


class QueueMember(BaseModel):
    """A member (agent) assigned to a queue.

    TODO: Fields are provisional for the GraphQL side. AMI-sourced
    fields (status, calls_taken, paused) are well-known.
    """

    extension: str
    name: str | None = None
    paused: bool = False
    # TODO: penalty, state_interface — confirm from GraphQL or AMI

    model_config = {"extra": "allow"}


class Queue(BaseModel):
    """A call queue configuration from FreePBX.

    TODO: Field names are provisional. Run a GraphQL introspection
    query (fetchAllQueues or similar) to confirm the actual schema.
    """

    queue_number: str
    name: str
    strategy: str | None = None  # ringall, roundrobin, leastrecent, etc.
    members: list[QueueMember] = []
    # TODO: timeout, retry, wrapuptime, maxlen — confirm from schema

    model_config = {"extra": "allow"}


class QueueStats(BaseModel):
    """Live queue statistics from AMI QueueSummary action.

    These fields are well-documented in Asterisk AMI and stable.
    Reference: https://docs.asterisk.org/Asterisk_16_Documentation/API_Documentation/AMI_Actions/QueueSummary
    """

    queue: str
    logged_in: int = 0
    available: int = 0
    callers: int = 0
    hold_time: int = 0       # average hold time in seconds
    talk_time: int = 0       # average talk time in seconds
    longest_hold: int = 0    # longest current hold time in seconds
