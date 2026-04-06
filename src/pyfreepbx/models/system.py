"""System info models.

SystemInfo fields come from AMI CoreStatus / CoreSettings actions,
which are stable and well-documented across Asterisk versions.
Health check models live in ``models/health.py``.
"""

from __future__ import annotations

from pydantic import BaseModel


class SystemInfo(BaseModel):
    """Asterisk system info from AMI CoreStatus action.

    These fields map directly to AMI CoreStatus response headers,
    which are stable across Asterisk versions.

    ``uptime_seconds`` and ``reload_seconds`` are derived from
    ``CoreStartupDate``/``CoreStartupTime`` and
    ``CoreReloadDate``/``CoreReloadTime``. They are ``0`` when
    AMI does not return those fields or the date format is unexpected.

    ``active_channels`` is not returned by CoreStatus and is always
    ``0``. Use AMI ``CoreShowChannels`` to get a channel count.
    """

    asterisk_version: str = ""
    ami_version: str = ""
    uptime_seconds: int = 0
    reload_seconds: int = 0
    active_channels: int = 0  # Not in CoreStatus — requires CoreShowChannels
    active_calls: int = 0
