from pyfreepbx.services.queues import QueueService


def test_queue_member_preserves_pause_owner():
    member = QueueService._member_from_event(
        {
            "Interface": "Local/30199@from-queue/n",
            "Paused": "1",
            "PausedReason": "uniqueos-guard:test",
        }
    )
    assert member.paused
    assert member.paused_reason == "uniqueos-guard:test"


def test_absent_reason_remains_unknown():
    member = QueueService._member_from_event(
        {"Interface": "Local/30199@from-queue/n", "Paused": "1"}
    )
    assert member.paused_reason is None
