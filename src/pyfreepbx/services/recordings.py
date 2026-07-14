"""Read-only wrappers for the FreePBX System Recordings module."""

import builtins

from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.models.recording import SystemRecording


class RecordingService:
    def __init__(self, client: FreePBXClient) -> None:
        self._client = client

    # This class exposes a public method named ``list``, which shadows the
    # ``list`` builtin in the class namespace. Class-body annotations evaluate in
    # that namespace at runtime, so a bare ``list[...]`` return annotation would
    # resolve to this method and raise "'function' object is not subscriptable"
    # on Python < 3.14 (eager annotation eval; 3.14 defers per PEP 649 and masked
    # it). Qualify with ``builtins.list`` so runtime and mypy both resolve the
    # builtin, without renaming the public method.
    def list(self) -> builtins.list[SystemRecording]:
        return [
            SystemRecording(
                id=str(row.get("id", "")),
                name=str(row.get("name", "")),
                description=str(row.get("description") or ""),
                feature_code=str(row.get("fcode") or ""),
                language=str(row.get("language") or ""),
                playback=list(row.get("playback") or []),
            )
            for row in self._client.fetch_all_recordings()
        ]

    def files(self, search: str = "") -> builtins.list[str]:
        return self._client.fetch_recording_files(search)
