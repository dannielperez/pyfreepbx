"""System service — Asterisk system info via AMI.

AMI actions used here (CoreStatus) are stable and well-documented
across Asterisk versions.

Health checks are provided by :class:`~pyfreepbx.services.health.HealthService`.
"""

from __future__ import annotations

from pyfreepbx.clients.ami import AMIClient
from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.logging import get_logger
from pyfreepbx.models.system import SystemInfo

log = get_logger("services.system")


class SystemService:
    """Asterisk system information via AMI."""

    def __init__(self, client: FreePBXClient, ami: AMIClient | None = None) -> None:
        self._client = client
        self._ami = ami

    def info(self) -> SystemInfo:
        """Get Asterisk system information from AMI CoreStatus.

        Reference: https://docs.asterisk.org/Asterisk_16_Documentation/API_Documentation/AMI_Actions/CoreStatus
        """
        if self._ami is None:
            raise RuntimeError("AMI client is required for system info.")

        return self._ami.core_status()
