"""Schemas for queue member operations.

Queue member add/remove can go through either:
- FreePBX GraphQL mutations (persistent config changes)
- AMI QueueAdd/QueueRemove actions (runtime-only, lost on reload)

The service layer decides which path to use. These schemas just
validate the input.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field


def _reject_ami_frame_delimiters(value: str) -> str:
    if any(delimiter in value for delimiter in ("\r", "\n", "\x00")):
        raise ValueError("AMI fields must not contain CR, LF, or NUL characters.")
    return value


_AMIField = Annotated[str, AfterValidator(_reject_ami_frame_delimiters)]


class QueueMemberAdd(BaseModel):
    """Input for adding a member to a queue."""

    queue: _AMIField = Field(description="Queue number or name")
    extension: _AMIField = Field(description="Member extension to add")
    penalty: int = Field(
        default=0,
        ge=0,
        description=(
            "Per-membership FreePBX penalty/priority (lower penalty = higher priority)"
        ),
    )


class QueueMemberRemove(BaseModel):
    """Input for removing a member from a queue."""

    queue: _AMIField = Field(description="Queue number or name")
    extension: _AMIField = Field(description="Member extension to remove")


class QueueMemberPause(BaseModel):
    """Input for pausing/unpausing a runtime queue member."""

    queue: _AMIField = Field(description="Queue number or name")
    extension: _AMIField = Field(description="Member extension to pause/unpause")
    paused: bool = Field(description="True to pause, False to resume")
    reason: _AMIField = Field(default="", description="Optional pause reason")
