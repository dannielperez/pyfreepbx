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
    secret: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        description="SIP secret (password). Generated server-side if omitted.",
    )
    email: str | None = Field(
        default=None,
        max_length=200,
        description="Email address for the extension user",
    )
