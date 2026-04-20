"""Asterisk runtime summary models for operational visibility."""

from __future__ import annotations

from pydantic import BaseModel


class AsteriskSummary(BaseModel):
    """High-level Asterisk summary for dashboards and diagnostics."""

    version: str = ""
    active_calls: int = 0
    active_channels: int = 0
    endpoint_total: int = 0
    endpoint_registered: int = 0
    endpoint_unregistered: int = 0
    endpoint_unavailable: int = 0
    endpoint_unknown: int = 0
