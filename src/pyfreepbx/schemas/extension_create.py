"""Schema for creating a new extension.

Field names are provisional — the actual GraphQL mutation input type
depends on FreePBX version. After introspection, update field names
and validation rules to match the real mutation schema.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pyfreepbx.models.extension import ExtensionType


class ExtensionCreate(BaseModel):
    """Input payload for creating a new FreePBX extension."""

    extension: str = Field(
        min_length=1, max_length=20,
        description="Extension number (e.g. '1001')",
    )
    name: str = Field(
        min_length=1, max_length=100,
        description="Display name for the extension",
    )
    tech: ExtensionType = Field(
        default=ExtensionType.PJSIP,
        description="Channel technology",
    )
    voicemail_enabled: bool = Field(
        default=False,
        description="Whether to create a voicemail box",
    )
    outbound_cid: str | None = Field(
        default=None,
        description="Outbound caller ID override",
    )
    # TODO: Add fields as discovered from introspecting the addExtension
    # mutation input type. Common ones: secret, ring_time, call_group.
