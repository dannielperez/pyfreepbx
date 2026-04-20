"""Call detail record models for diagnostics and troubleshooting."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CallDetailRecord(BaseModel):
    """Normalized CDR record used across pyfreepbx and UniqueOS."""

    timestamp: datetime | None = None
    source: str = ""
    destination: str = ""
    duration: int = 0
    billsec: int = 0
    disposition: str = ""
    unique_id: str = ""
    linked_id: str = ""
    queue: str = ""
    raw: dict = {}


class CDRListResult(BaseModel):
    """Bounded CDR query result with normalized records."""

    items: list[CallDetailRecord] = []
    total: int = 0
    truncated: bool = False
