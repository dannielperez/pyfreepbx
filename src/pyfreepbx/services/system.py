"""System service — Asterisk system info via AMI.

AMI actions used here (CoreStatus) are stable and well-documented
across Asterisk versions.

Health checks are provided by :class:`~pyfreepbx.services.health.HealthService`.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from pyfreepbx.logging import get_logger
from pyfreepbx.models.system import (
    ApplyConfigConvergenceResult,
    ApplyConfigResult,
    ConfigReloadStatus,
    SystemInfo,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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

    def __init__(
        self,
        client: FreePBXClient,
        ami: AMIClient | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._ami = ami
        self._sleep = sleep
        self._clock = clock

    def info(self) -> SystemInfo:
        """Get Asterisk system information from AMI CoreStatus.

        Reference: https://docs.asterisk.org/Asterisk_16_Documentation/API_Documentation/AMI_Actions/CoreStatus
        """
        if self._ami is None:
            raise RuntimeError("AMI client is required for system info.")

        return self._ami.core_status()

    def config_reload_status(self, *, timeout: float | None = None) -> ConfigReloadStatus:
        """Return FreePBX's ``fetchNeedReload`` response."""
        data = self._client.graphql.query(_FETCH_NEED_RELOAD, timeout=timeout)
        return ConfigReloadStatus.model_validate(data.get("fetchNeedReload") or {})

    def apply_config(self, *, timeout: float | None = None) -> ApplyConfigResult:
        """Start FreePBX's asynchronous ``doreload`` apply-config operation.

        This mutation is not safely retryable: a transport timeout can occur
        after FreePBX accepts the reload but before it returns the transaction
        id. Callers must surface that outcome as indeterminate rather than
        automatically issuing another reload.
        """
        data = self._client.graphql.mutation(
            _DO_RELOAD,
            {"input": {}},
            timeout=timeout,
        )
        return ApplyConfigResult.model_validate(data.get("doreload") or {})

    def apply_config_and_wait(
        self,
        *,
        timeout: float,
        poll_interval: float = 1.0,
    ) -> ApplyConfigConvergenceResult:
        """Apply config once and reconcile FreePBX's authoritative reload state.

        FreePBX 16 can return a false ``doreload`` acknowledgement after it has
        accepted the asynchronous operation. The mutation is therefore never
        replayed. ``fetchNeedReload`` is polled within the caller's aggregate
        timeout and its version-specific message is normalized into a typed
        convergence result.
        """
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and greater than zero")
        if not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("poll_interval must be finite and greater than zero")

        deadline = self._clock() + timeout
        acknowledgement = self.apply_config(timeout=timeout)
        last_status: ConfigReloadStatus | None = None

        while (remaining := deadline - self._clock()) > 0:
            last_status = self.config_reload_status(timeout=remaining)
            if "not required" in last_status.message.lower():
                return ApplyConfigConvergenceResult(
                    acknowledged=acknowledgement.status,
                    converged=True,
                    message=last_status.message,
                    transaction_id=acknowledgement.transaction_id,
                )
            remaining = deadline - self._clock()
            if remaining > 0:
                self._sleep(min(poll_interval, remaining))

        return ApplyConfigConvergenceResult(
            acknowledged=acknowledgement.status,
            converged=False,
            message=last_status.message if last_status is not None else acknowledgement.message,
            transaction_id=acknowledgement.transaction_id,
        )
