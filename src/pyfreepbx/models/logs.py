"""Asterisk log models for troubleshooting and diagnostics."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AsteriskLogLine(BaseModel):
    """Normalized Asterisk log line with optional parsed timestamp."""

    timestamp: datetime | None = None
    level: str = ""
    message: str = ""
    raw: str = ""


class AsteriskLogResult(BaseModel):
    """Bounded log query result."""

    lines: list[AsteriskLogLine] = []
    total: int = 0
    truncated: bool = False
