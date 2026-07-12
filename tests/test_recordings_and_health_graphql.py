from unittest.mock import MagicMock

from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.services.health import HealthService
from pyfreepbx.services.recordings import RecordingService


def test_recordings_wrappers_normalize_payload(mock_freepbx_client: MagicMock) -> None:
    mock_freepbx_client.fetch_all_recordings.return_value = [
        {"id": 7, "name": "Greeting", "fcode": "*77", "playback": ["hello.wav"]}
    ]
    mock_freepbx_client.fetch_recording_files.return_value = ["hello.wav"]

    service = RecordingService(mock_freepbx_client)

    assert service.list()[0].model_dump() == {
        "id": "7",
        "name": "Greeting",
        "description": "",
        "feature_code": "*77",
        "language": "",
        "playback": ["hello.wav"],
    }
    assert service.files("hello") == ["hello.wav"]
    mock_freepbx_client.fetch_recording_files.assert_called_once_with("hello")


def test_health_graphql_extras_are_typed(mock_freepbx_client: MagicMock) -> None:
    mock_freepbx_client.check_disk_space.return_value = [
        {"id": "1", "storage_path": "/", "used_percentage": "42%"}
    ]
    mock_freepbx_client.fetch_asterisk_details.return_value = {
        "asteriskStatus": "Running",
        "asteriskVersion": "20.6.0",
        "amiStatus": "Connected",
    }

    service = HealthService(mock_freepbx_client)

    assert service.disk_space()[0].used_percentage == "42%"
    assert service.asterisk_details().version == "20.6.0"


def test_low_level_helpers_extract_freepbx_shapes() -> None:
    client = object.__new__(FreePBXClient)
    client._gql = MagicMock()
    client._gql.query.side_effect = [
        {"fetchRecordingFiles": {"recodingFiles": ["one.wav"]}},
        {"fetchCdr": {"uniqueid": "abc", "recordingfile": "one.wav"}},
        {"checkdiskspace": {"diskspace": [{"id": "1"}]}},
    ]

    assert client.fetch_recording_files("one") == ["one.wav"]
    assert client.fetch_cdr("abc") == {"uniqueid": "abc", "recordingfile": "one.wav"}
    assert client.check_disk_space() == [{"id": "1"}]
