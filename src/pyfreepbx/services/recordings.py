"""Read-only wrappers for the FreePBX System Recordings module."""

from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.models.recording import SystemRecording


class RecordingService:
    def __init__(self, client: FreePBXClient) -> None:
        self._client = client

    def list(self) -> list[SystemRecording]:
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

    def files(self, search: str = "") -> list[str]:
        return self._client.fetch_recording_files(search)
