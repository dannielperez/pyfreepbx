"""Extension models.

Field names are provisional — the actual FreePBX GraphQL schema varies
by version and installed modules. After introspecting your instance,
update the field names to match. ``extra = "allow"`` ensures unknown
fields from the API are preserved rather than dropped.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ExtensionType(str, Enum):
    """Known extension technologies in FreePBX."""

    SIP = "sip"
    PJSIP = "pjsip"
    IAX2 = "iax2"
    DAHDI = "dahdi"
    CUSTOM = "custom"
    VIRTUAL = "virtual"


class Extension(BaseModel):
    """A FreePBX extension (user/device endpoint).

    Returned from ``pbx.extensions.list()`` and ``pbx.extensions.get()``.
    """

    extension: str
    name: str
    tech: ExtensionType | None = None
    voicemail_enabled: bool | None = None
    enabled: bool = True
    outbound_cid: str | None = Field(
        default=None,
        description="Outbound caller ID. Field name varies by FreePBX version.",
    )
    # TODO: ring_time, call_group, pickup_group — confirm from GraphQL introspection

    model_config = {"extra": "allow"}
