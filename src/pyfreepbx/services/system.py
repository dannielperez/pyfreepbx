"""System service — Asterisk system info via AMI.

AMI actions used here (CoreStatus) are stable and well-documented
across Asterisk versions.

Health checks are provided by :class:`~pyfreepbx.services.health.HealthService`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyfreepbx.logging import get_logger
from pyfreepbx.models.system import ApplyConfigResult, ConfigReloadStatus, SystemInfo

if TYPE_CHECKING:
    from pyfreepbx.clients.ami import AMIClient
    from pyfreepbx.clients.freepbx import FreePBXClient

log = get_logger("services.system")

_FETCH_NEED_RELOAD = """\
query FetchNeedReload {
    fetchNeedReload {
        status
        message
    }
}
"""

_DO_RELOAD = """\
mutation ApplyConfig($input: doreloadInput!) {
    doreload(input: $input) {
        status
        message
        transaction_id
    }
}
"""


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

    def config_reload_status(self) -> ConfigReloadStatus:
        """Return FreePBX's ``fetchNeedReload`` response."""
        data = self._client.graphql.query(_FETCH_NEED_RELOAD)
        return ConfigReloadStatus.model_validate(data.get("fetchNeedReload") or {})

    def apply_config(self) -> ApplyConfigResult:
        """Start FreePBX's asynchronous ``doreload`` apply-config operation."""
        data = self._client.graphql.mutation(
            _DO_RELOAD,
            {"input": {"clientMutationId": "pyfreepbx"}},
        )
        return ApplyConfigResult.model_validate(data.get("doreload") or {})
