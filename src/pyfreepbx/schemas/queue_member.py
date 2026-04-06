"""Schemas for queue member operations.

Queue member add/remove can go through either:
- FreePBX GraphQL mutations (persistent config changes)
- AMI QueueAdd/QueueRemove actions (runtime-only, lost on reload)

The service layer decides which path to use. These schemas just
validate the input.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueueMemberAdd(BaseModel):
    """Input for adding a member to a queue."""

    queue: str = Field(description="Queue number or name")
    extension: str = Field(description="Member extension to add")
    penalty: int = Field(default=0, ge=0, description="Agent penalty (lower = higher priority)")


class QueueMemberRemove(BaseModel):
    """Input for removing a member from a queue."""

    queue: str = Field(description="Queue number or name")
    extension: str = Field(description="Member extension to remove")
