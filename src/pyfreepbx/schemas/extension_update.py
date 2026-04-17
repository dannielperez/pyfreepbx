"""Schema for updating an existing extension.

All fields are optional — only fields that are set will be included
in the mutation payload (partial update).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pyfreepbx.models.extension import ExtensionType


class ExtensionUpdate(BaseModel):
    """Input payload for updating an existing FreePBX extension.

    Only include fields you want to change. ``None`` values are
    excluded from the mutation variables.
    """

    name: str | None = Field(default=None, max_length=100)
    tech: ExtensionType | None = None
    voicemail_enabled: bool | None = None
    outbound_cid: str | None = None
    enabled: bool | None = None
    secret: str | None = Field(default=None, min_length=8, max_length=64)
    email: str | None = Field(default=None, max_length=200)

    def to_variables(self) -> dict[str, object]:
        """Return only the fields that were explicitly set (non-None)."""
        return {k: v for k, v in self.model_dump().items() if v is not None}
