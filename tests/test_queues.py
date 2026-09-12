"""Tests for QueueService."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import httpx
import pytest

from pyfreepbx.exceptions import (
    AMIError,
    FreePBXTimeoutError,
    FreePBXTransportError,
    NotFoundError,
    QueueMemberNotFoundError,
)
from pyfreepbx.models.queue import QueueStats
from pyfreepbx.schemas.queue_member import (
    QueueMemberAdd,
    QueueMemberPause,
    QueueMemberRemove,
)
from pyfreepbx.services.queues import QueueService


class TestQueueList:
    def test_list_returns_ami_queues_with_members(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.queue_summary.return_value = [
            QueueStats(queue="400"),
            QueueStats(queue="401"),
        ]
        mock_ami.queue_status.return_value = [
            {
                "Event": "QueueMember",
                "Queue": "400",
                "Name": "Local/1001@from-queue/n",
                "MemberName": "Alice",
                "Paused": "0",
                "Penalty": "1",
            },
            {
                "Event": "QueueMember",
                "Queue": "401",
                "Name": "PJSIP/2001",
                "MemberName": "Bob",
                "Paused": "1",
            },
        ]

        svc = QueueService(mock_freepbx_client, mock_ami)
        result = svc.list()

        assert len(result) == 2
        assert result[0].queue_number == "400"
        assert result[0].name == "400"
        assert result[0].members[0].extension == "1001"
        assert result[1].queue_number == "401"
        assert result[1].members[0].extension == "2001"
        mock_ami.queue_summary.assert_called_once_with()
        mock_ami.queue_status.assert_called_once_with()

    def test_list_enriches_ami_queues_with_rest_descriptions(
        self,
        mock_freepbx_client: MagicMock,
        mock_ami: MagicMock,
    ) -> None:
        mock_rest = MagicMock()
        mock_ami.queue_summary.return_value = [
            QueueStats(queue="86"),
            QueueStats(queue="99"),
        ]
        mock_ami.queue_status.return_value = []
        mock_rest.get.return_value = {
            "86": {"extension": "86", "name": "Cristina Valencia Queue"},
            "99": {"extension": "99", "name": "uniquesec-queue"},
        }

        result = QueueService(mock_freepbx_client, mock_ami, mock_rest).list()

        assert [(queue.queue_number, queue.name) for queue in result] == [
            ("86", "Cristina Valencia Queue"),
            ("99", "uniquesec-queue"),
        ]
        mock_rest.get.assert_called_once_with("/queues")

    @pytest.mark.parametrize(
        "rest_result",
        [False, [], {"99": {"extension": "99"}}, {"99": "invalid"}],
    )
    def test_list_falls_back_to_queue_number_for_missing_or_invalid_descriptions(
        self,
        mock_freepbx_client: MagicMock,
        mock_ami: MagicMock,
        rest_result: object,
    ) -> None:
        mock_rest = MagicMock()
        mock_ami.queue_summary.return_value = [QueueStats(queue="99")]
        mock_ami.queue_status.return_value = []
        mock_rest.get.return_value = rest_result

        result = QueueService(mock_freepbx_client, mock_ami, mock_rest).list()

        assert result[0].name == "99"

    def test_list_falls_back_when_rest_description_lookup_is_unavailable(
        self,
        mock_freepbx_client: MagicMock,
        mock_ami: MagicMock,
    ) -> None:
        mock_rest = MagicMock()
        mock_ami.queue_summary.return_value = [QueueStats(queue="99")]
        mock_ami.queue_status.return_value = []
        mock_rest.get.side_effect = FreePBXTransportError("unavailable")

        result = QueueService(mock_freepbx_client, mock_ami, mock_rest).list()

        assert result[0].name == "99"

    @pytest.mark.parametrize(
        "rest_error",
        [
            httpx.HTTPStatusError(
                "server error",
                request=httpx.Request("GET", "https://pbx.test/queues"),
                response=httpx.Response(500),
            ),
            ValueError("malformed JSON"),
        ],
    )
    def test_list_falls_back_for_raw_http_or_response_decode_failures(
        self,
        mock_freepbx_client: MagicMock,
        mock_ami: MagicMock,
        rest_error: Exception,
    ) -> None:
        mock_rest = MagicMock()
        mock_ami.queue_summary.return_value = [QueueStats(queue="99")]
        mock_ami.queue_status.return_value = []
        mock_rest.get.side_effect = rest_error

        result = QueueService(mock_freepbx_client, mock_ami, mock_rest).list()

        assert result[0].name == "99"

    def test_list_empty(self, mock_freepbx_client: MagicMock, mock_ami: MagicMock) -> None:
        mock_ami.queue_summary.return_value = []
        mock_ami.queue_status.return_value = []
        svc = QueueService(mock_freepbx_client, mock_ami)
        assert svc.list() == []

    def test_list_result_marks_successful_empty_inventory_complete(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.queue_summary.return_value = []
        mock_ami.queue_status.return_value = []

        result = QueueService(mock_freepbx_client, mock_ami).list_result()

        assert result.items == []
        assert result.complete is True

    def test_list_without_ami_raises(self, mock_freepbx_client: MagicMock) -> None:
        svc = QueueService(mock_freepbx_client)
        with pytest.raises(RuntimeError, match="AMI client is required"):
            svc.list()

    def test_list_connects_and_authenticates_ami(
        self,
        mock_freepbx_client: MagicMock,
        mock_ami: MagicMock,
    ) -> None:
        mock_ami.connected = False
        mock_ami.authenticated = False
        mock_ami.queue_summary.return_value = []
        mock_ami.queue_status.return_value = []

        QueueService(mock_freepbx_client, mock_ami).list()

        mock_ami.connect.assert_called_once_with()
        mock_ami.login.assert_called_once_with(events=False)


class TestQueueGet:
    def test_get_found(self, mock_freepbx_client: MagicMock, mock_ami: MagicMock) -> None:
        mock_ami.queue_summary.return_value = [QueueStats(queue="400")]
        mock_ami.queue_status.return_value = []
        svc = QueueService(mock_freepbx_client, mock_ami)
        q = svc.get("400")
        assert q.queue_number == "400"
        assert q.name == "400"

    def test_get_not_found(self, mock_freepbx_client: MagicMock, mock_ami: MagicMock) -> None:
        mock_ami.queue_summary.return_value = [QueueStats(queue="400")]
        mock_ami.queue_status.return_value = []
        svc = QueueService(mock_freepbx_client, mock_ami)
        with pytest.raises(NotFoundError, match="999"):
            svc.get("999")


class TestQueueStats:
    def test_stats_delegates_to_ami(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        expected = [QueueStats(queue="support", logged_in=3, available=2, callers=1)]
        mock_ami.queue_summary.return_value = expected

        svc = QueueService(mock_freepbx_client, mock_ami)
        result = svc.stats("support")

        assert result == expected
        mock_ami.queue_summary.assert_called_once_with(queue="support")

    def test_stats_all_queues(self, mock_freepbx_client: MagicMock, mock_ami: MagicMock) -> None:
        mock_ami.queue_summary.return_value = []
        svc = QueueService(mock_freepbx_client, mock_ami)
        svc.stats()
        mock_ami.queue_summary.assert_called_once_with(queue=None)

    def test_stats_without_ami_raises(self, mock_freepbx_client: MagicMock) -> None:
        svc = QueueService(mock_freepbx_client, ami=None)
        with pytest.raises(RuntimeError, match="AMI client is required"):
            svc.stats()


class TestQueueMembers:
    def test_members_parses_events(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.queue_status.return_value = [
            {"Event": "QueueParams", "Queue": "400", "Max": "0"},
            {
                "Event": "QueueMember",
                "Queue": "400",
                "Name": "Local/1001@from-queue/n",
                "MemberName": "Alice",
                "Paused": "0",
                "Penalty": "1",
            },
            {
                "Event": "QueueMember",
                "Queue": "400",
                "Name": "Local/1002@from-queue/n",
                "MemberName": "Bob",
                "Paused": "1",
            },
        ]

        svc = QueueService(mock_freepbx_client, mock_ami)
        members = svc.members("400")

        assert len(members) == 2
        assert members[0].extension == "1001"
        assert members[0].name == "Alice"
        assert members[0].paused is False
        assert members[0].penalty == 1
        assert members[1].paused is True
        assert members[1].penalty is None

    def test_members_falls_back_when_queue_filter_is_rejected(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.queue_status.side_effect = [
            AMIError("QueueStatus failed"),
            [
                {
                    "Event": "QueueMember",
                    "Queue": "400",
                    "Name": "Local/1001@from-queue/n",
                    "Penalty": "0",
                },
                {
                    "Event": "QueueMember",
                    "Queue": "401",
                    "Name": "Local/2001@from-queue/n",
                    "Penalty": "0",
                },
            ],
        ]

        members = QueueService(mock_freepbx_client, mock_ami).members("400")

        assert [member.extension for member in members] == ["1001"]
        assert mock_ami.queue_status.call_args_list == [call(queue="400"), call()]

    def test_members_does_not_retry_other_ami_errors(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.queue_status.side_effect = AMIError("Permission denied")

        with pytest.raises(AMIError, match="Permission denied"):
            QueueService(mock_freepbx_client, mock_ami).members("400")

        mock_ami.queue_status.assert_called_once_with(queue="400")

    def test_members_without_ami_raises(self, mock_freepbx_client: MagicMock) -> None:
        svc = QueueService(mock_freepbx_client, ami=None)
        with pytest.raises(RuntimeError, match="AMI client is required"):
            svc.members("400")


class TestQueueMemberManagement:
    def test_add_member_runtime_success(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.run_action.return_value = {"Response": "Success"}

        svc = QueueService(mock_freepbx_client, mock_ami)
        svc.add_member_runtime(QueueMemberAdd(queue="400", extension="1001"))

        mock_ami.run_action.assert_called_once_with(
            "QueueAdd",
            Queue="400",
            Interface="Local/1001@from-queue/n",
            Penalty="0",
            MemberName="1001",
        )

    def test_add_member_runtime_failure(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.run_action.return_value = {
            "Response": "Error",
            "Message": "Queue not found",
        }

        svc = QueueService(mock_freepbx_client, mock_ami)
        with pytest.raises(RuntimeError, match="Queue not found"):
            svc.add_member_runtime(QueueMemberAdd(queue="999", extension="1001"))

    def test_remove_member_runtime_success(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.run_action.return_value = {"Response": "Success"}

        svc = QueueService(mock_freepbx_client, mock_ami)
        svc.remove_member_runtime(QueueMemberRemove(queue="400", extension="1001"))

        mock_ami.run_action.assert_called_once_with(
            "QueueRemove",
            Queue="400",
            Interface="Local/1001@from-queue/n",
        )

    def test_add_member_runtime_without_ami_raises(self, mock_freepbx_client: MagicMock) -> None:
        svc = QueueService(mock_freepbx_client, ami=None)
        with pytest.raises(RuntimeError, match="AMI client is required"):
            svc.add_member_runtime(QueueMemberAdd(queue="400", extension="1001"))

    def test_remove_member_runtime_absent_member_raises_typed_error(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.run_action.return_value = {
            "Response": "Error",
            "Message": "Unable to remove interface: Not there",
        }

        svc = QueueService(mock_freepbx_client, mock_ami)
        with pytest.raises(QueueMemberNotFoundError):
            svc.remove_member_runtime(QueueMemberRemove(queue="400", extension="1001"))

    def test_remove_member_runtime_absent_queue_raises_typed_error(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        mock_ami.run_action.return_value = {
            "Response": "Error",
            "Message": "No such queue",
        }

        svc = QueueService(mock_freepbx_client, mock_ami)
        with pytest.raises(QueueMemberNotFoundError):
            svc.remove_member_runtime(QueueMemberRemove(queue="999", extension="1001"))

    def test_pause_member_runtime_uses_the_shared_member_interface(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        svc = QueueService(mock_freepbx_client, mock_ami)
        svc.pause_member_runtime(
            QueueMemberPause(queue="400", extension="1001", paused=True, reason="lunch")
        )

        mock_ami.queue_pause.assert_called_once_with(
            queue="400",
            interface="Local/1001@from-queue/n",
            paused=True,
            reason="lunch",
        )

    def test_pause_member_runtime_omits_a_blank_reason(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        svc = QueueService(mock_freepbx_client, mock_ami)
        svc.pause_member_runtime(QueueMemberPause(queue="400", extension="1001", paused=False))

        mock_ami.queue_pause.assert_called_once_with(
            queue="400",
            interface="Local/1001@from-queue/n",
            paused=False,
            reason=None,
        )

    def test_pause_member_runtime_without_ami_raises(self, mock_freepbx_client: MagicMock) -> None:
        svc = QueueService(mock_freepbx_client, ami=None)
        with pytest.raises(RuntimeError, match="AMI client is required"):
            svc.pause_member_runtime(QueueMemberPause(queue="400", extension="1001", paused=True))


class TestPersistentQueueMemberManagement:
    def test_ensure_member_preserves_generated_config_when_live_status_is_stale(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": ["100", "101"], "dynmembers": []},
            {"member": ["100", "101", "119"], "dynmembers": []},
        ]
        rest.put.return_value = True
        mock_ami.queue_config_member_lines.return_value = [
            "Local/100@from-queue/n,4,Agent 100,hint:100@ext-local",
            "PJSIP/101,2,Agent 101",
        ]
        mock_ami.queue_status.return_value = []
        svc = QueueService(mock_freepbx_client, mock_ami, rest)

        assert svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="119", penalty=0))

        rest.put.assert_called_once_with(
            "/queues/members/99",
            json={"member": "100,4\nP101,2\n119,0"},
        )

    def test_ensure_member_falls_back_to_unfiltered_queue_status(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": ["1001"], "dynmembers": []},
            {"member": ["1001", "125"], "dynmembers": []},
        ]
        rest.put.return_value = True
        mock_ami.queue_status.side_effect = [
            AMIError("QueueStatus failed"),
            [
                {
                    "Event": "QueueMember",
                    "Queue": "99",
                    "Membership": "static",
                    "Interface": "PJSIP/1001",
                    "Penalty": "4",
                },
                {
                    "Event": "QueueMember",
                    "Queue": "98",
                    "Membership": "static",
                    "Interface": "PJSIP/2001",
                    "Penalty": "2",
                },
            ],
        ]

        changed = QueueService(mock_freepbx_client, mock_ami, rest).ensure_member_persistent(
            QueueMemberAdd(queue="99", extension="125", penalty=0)
        )

        assert changed is True
        rest.put.assert_called_once_with(
            "/queues/members/99",
            json={"member": "P1001,4\n125,0"},
        )
        assert mock_ami.queue_status.call_args_list == [call(queue="99"), call()]

    def test_ensure_member_falls_back_when_generated_config_is_denied(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": ["1001"], "dynmembers": []},
            {"member": ["1001", "119"], "dynmembers": []},
        ]
        rest.put.return_value = True
        mock_ami.queue_config_member_lines.side_effect = AMIError("Permission denied")
        mock_ami.queue_status.return_value = [
            {
                "Event": "QueueMember",
                "Membership": "static",
                "Interface": "PJSIP/1001",
                "Penalty": "4",
            }
        ]

        changed = QueueService(mock_freepbx_client, mock_ami, rest).ensure_member_persistent(
            QueueMemberAdd(queue="99", extension="119", penalty=0)
        )

        assert changed is True
        rest.put.assert_called_once_with(
            "/queues/members/99",
            json={"member": "P1001,4\n119,0"},
        )

    def test_ensure_member_preserves_position_and_corresponding_priority(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": ["1001", "1002"], "dynmembers": ["2001"]},
            {"member": ["1001", "1002", "116"], "dynmembers": ["2001"]},
        ]
        rest.put.return_value = True
        mock_ami.queue_status.return_value = [
            {
                "Event": "QueueMember",
                "Membership": "static",
                "Interface": "PJSIP/1001",
                "Penalty": "4",
            },
            {
                "Event": "QueueMember",
                "Membership": "static",
                "Interface": "Local/1002@from-queue/n",
                "Penalty": "1",
            },
            {
                "Event": "QueueMember",
                "Membership": "dynamic",
                "Interface": "Local/2001@from-queue/n",
                "Penalty": "9",
            },
        ]
        svc = QueueService(mock_freepbx_client, mock_ami, rest)

        changed = svc.ensure_member_persistent(
            QueueMemberAdd(queue="99", extension="116", penalty=2)
        )

        assert changed is True
        assert rest.get.call_count == 2
        rest.get.assert_called_with("/queues/members/99")
        rest.put.assert_called_once_with(
            "/queues/members/99",
            json={"member": "P1001,4\n1002,1\n116,2"},
        )
        mock_ami.queue_status.assert_called_once_with(queue="99")

    def test_ensure_member_is_idempotent(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.return_value = {"member": ["1001", "116"], "dynmembers": []}
        mock_ami.queue_status.return_value = [
            {
                "Event": "QueueMember",
                "Membership": "static",
                "Interface": "Local/1001@from-queue/n",
                "Penalty": "0",
            },
            {
                "Event": "QueueMember",
                "Membership": "static",
                "Interface": "Local/116@from-queue/n",
                "Penalty": "0",
            },
        ]
        svc = QueueService(mock_freepbx_client, mock_ami, rest)

        changed = svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))

        assert changed is False
        rest.put.assert_not_called()

    def test_ensure_member_updates_priority_without_changing_position(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": ["1001", "116"], "dynmembers": []},
            {"member": ["1001", "116"], "dynmembers": []},
        ]
        rest.put.return_value = True
        mock_ami.queue_status.return_value = [
            {
                "Event": "QueueMember",
                "Membership": "static",
                "Interface": "PJSIP/1001",
                "Penalty": "4",
            },
            {
                "Event": "QueueMember",
                "Membership": "static",
                "Interface": "Local/116@from-queue/n",
                "Penalty": "1",
            },
        ]
        svc = QueueService(mock_freepbx_client, mock_ami, rest)

        changed = svc.ensure_member_persistent(
            QueueMemberAdd(queue="99", extension="116", penalty=2)
        )

        assert changed is True
        rest.put.assert_called_once_with(
            "/queues/members/99",
            json={"member": "P1001,4\n116,2"},
        )

    def test_ensure_members_batches_one_queue_before_reload(
        self, mock_freepbx_client: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": [], "dynmembers": []},
            {"member": ["116", "117"], "dynmembers": []},
        ]
        rest.put.return_value = True
        svc = QueueService(mock_freepbx_client, rest=rest)

        changed = svc.ensure_members_persistent(
            [
                QueueMemberAdd(queue="99", extension="116"),
                QueueMemberAdd(queue="99", extension="117", penalty=2),
            ]
        )

        assert changed is True
        rest.put.assert_called_once_with(
            "/queues/members/99",
            json={"member": "116,0\n117,2"},
        )

    def test_ensure_members_rejects_mixed_queues(self, mock_freepbx_client: MagicMock) -> None:
        svc = QueueService(mock_freepbx_client, rest=MagicMock())

        with pytest.raises(ValueError, match="must target one queue"):
            svc.ensure_members_persistent(
                [
                    QueueMemberAdd(queue="99", extension="116"),
                    QueueMemberAdd(queue="100", extension="117"),
                ]
            )

    def test_ensure_members_rejects_conflicting_duplicate_penalties(
        self, mock_freepbx_client: MagicMock
    ) -> None:
        svc = QueueService(mock_freepbx_client, rest=MagicMock())

        with pytest.raises(ValueError, match="Conflicting penalties"):
            svc.ensure_members_persistent(
                [
                    QueueMemberAdd(queue="99", extension="116", penalty=1),
                    QueueMemberAdd(queue="99", extension="116", penalty=2),
                ]
            )

    def test_ensure_member_encodes_queue_path(self, mock_freepbx_client: MagicMock) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": [], "dynmembers": []},
            {"member": ["116"], "dynmembers": []},
        ]
        rest.put.return_value = True
        svc = QueueService(mock_freepbx_client, rest=rest)

        svc.ensure_member_persistent(QueueMemberAdd(queue="sales/east", extension="116"))

        assert rest.get.call_count == 2
        rest.get.assert_called_with("/queues/members/sales%2Feast")

    def test_ensure_member_missing_queue_raises(self, mock_freepbx_client: MagicMock) -> None:
        rest = MagicMock()
        rest.get.return_value = False
        svc = QueueService(mock_freepbx_client, rest=rest)

        with pytest.raises(NotFoundError, match="99"):
            svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))

    @pytest.mark.parametrize(
        "response",
        [None, [], {"member": "116"}, {"member": [116]}],
    )
    def test_ensure_member_rejects_invalid_readback(
        self, mock_freepbx_client: MagicMock, response: object
    ) -> None:
        rest = MagicMock()
        rest.get.return_value = response
        svc = QueueService(mock_freepbx_client, rest=rest)

        with pytest.raises(RuntimeError, match="invalid"):
            svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))

        rest.put.assert_not_called()

    @pytest.mark.parametrize("response", [False, None, {}, "true"])
    def test_ensure_member_requires_positive_update_acknowledgement(
        self, mock_freepbx_client: MagicMock, response: object
    ) -> None:
        rest = MagicMock()
        rest.get.return_value = {"member": [], "dynmembers": []}
        rest.put.return_value = response
        svc = QueueService(mock_freepbx_client, rest=rest)

        with pytest.raises(RuntimeError, match="did not acknowledge"):
            svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))

    @pytest.mark.parametrize(
        "readback",
        [False, None, {}, {"member": []}, {"member": "116"}],
    )
    def test_ensure_member_requires_confirmed_readback(
        self, mock_freepbx_client: MagicMock, readback: object
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": [], "dynmembers": []},
            readback,
        ]
        rest.put.return_value = True
        svc = QueueService(mock_freepbx_client, rest=rest)

        with pytest.raises(RuntimeError, match=r"read-back|complete queue-member set"):
            svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))

    def test_ensure_member_fails_closed_when_static_member_cannot_be_reconciled(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.return_value = {"member": ["1001"], "dynmembers": []}
        mock_ami.queue_status.return_value = []
        system = MagicMock()
        system.config_reload_required.return_value = False
        svc = QueueService(mock_freepbx_client, mock_ami, rest, system=system)

        with pytest.raises(RuntimeError, match="could not reconcile"):
            svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))

        rest.put.assert_not_called()

    def test_ensure_member_applies_pending_config_before_reconciliation(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": ["1001"], "dynmembers": []},
            {"member": ["1001", "116"], "dynmembers": []},
        ]
        rest.put.return_value = True
        mock_ami.queue_status.side_effect = [
            [],
            [
                {
                    "Event": "QueueMember",
                    "Membership": "static",
                    "Interface": "Local/1001@from-queue/n",
                    "Penalty": "3",
                }
            ],
        ]
        system = MagicMock()
        system.config_reload_required.return_value = True
        system.apply_config_and_wait.return_value.converged = True
        svc = QueueService(
            mock_freepbx_client,
            mock_ami,
            rest,
            system=system,
            pending_config_timeout=4.0,
        )

        assert svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116", penalty=0))
        system.config_reload_required.assert_called_once_with(timeout=4.0)
        system.apply_config_and_wait.assert_called_once_with(timeout=4.0)
        rest.put.assert_called_once_with(
            "/queues/members/99",
            json={"member": "1001,3\n116,0"},
        )

    def test_ensure_member_reapplies_when_runtime_drift_exists_without_pending_config(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": ["1001"], "dynmembers": []},
            {"member": ["1001", "116"], "dynmembers": []},
        ]
        rest.put.return_value = True
        mock_ami.queue_status.side_effect = [
            [],
            [
                {
                    "Event": "QueueMember",
                    "Membership": "static",
                    "Interface": "Local/1001@from-queue/n",
                    "Penalty": "3",
                }
            ],
        ]
        system = MagicMock()
        system.config_reload_required.return_value = False
        system.apply_config_and_wait.return_value.converged = True
        svc = QueueService(mock_freepbx_client, mock_ami, rest, system=system)

        assert svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))
        system.config_reload_required.assert_called_once_with(timeout=10.0)
        system.apply_config_and_wait.assert_called_once_with(timeout=10.0)
        rest.put.assert_called_once_with(
            "/queues/members/99",
            json={"member": "1001,3\n116,0"},
        )

    def test_ensure_member_stops_when_pending_config_does_not_converge(
        self, mock_freepbx_client: MagicMock, mock_ami: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.return_value = {"member": ["1001"], "dynmembers": []}
        mock_ami.queue_status.return_value = []
        system = MagicMock()
        system.config_reload_required.return_value = True
        system.apply_config_and_wait.return_value.converged = False
        svc = QueueService(mock_freepbx_client, mock_ami, rest, system=system)

        with pytest.raises(RuntimeError, match="did not converge"):
            svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))

        rest.put.assert_not_called()

    @pytest.mark.parametrize(
        ("interface", "expected"),
        [
            ("Agent/1001", "A1001,3"),
            ("PJSIP/1001", "P1001,3"),
            ("SIP/1001", "S1001,3"),
            ("IAX2/1001", "X1001,3"),
            ("ZAP/1001", "Z1001,3"),
            ("DAHDI/1001", "D1001,3"),
            ("Local/1001@from-queue/n", "1001,3"),
        ],
    )
    def test_persistent_member_input_preserves_type_and_penalty(
        self, interface: str, expected: str
    ) -> None:
        event = {"Interface": interface, "Penalty": "3"}

        assert QueueService._persistent_member_input(event, "1001") == expected

    @pytest.mark.parametrize(
        ("interface", "expected_input"),
        [
            ("Agent/1001", "A1001,3\n116,0"),
            ("PJSIP/1001", "P1001,3\n116,0"),
            ("SIP/1001", "S1001,3\n116,0"),
            ("IAX2/1001", "X1001,3\n116,0"),
            ("ZAP/1001", "Z1001,3\n116,0"),
            ("DAHDI/1001", "D1001,3\n116,0"),
            ("Local/1001@from-queue/n", "1001,3\n116,0"),
        ],
    )
    def test_ensure_member_reconciles_every_supported_static_type(
        self,
        mock_freepbx_client: MagicMock,
        mock_ami: MagicMock,
        interface: str,
        expected_input: str,
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": ["1001"], "dynmembers": []},
            {"member": ["1001", "116"], "dynmembers": []},
        ]
        rest.put.return_value = True
        mock_ami.queue_status.return_value = [
            {
                "Event": "QueueMember",
                "Membership": "static",
                "Interface": interface,
                "Penalty": "3",
            }
        ]
        svc = QueueService(mock_freepbx_client, mock_ami, rest)

        assert svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))
        rest.put.assert_called_once_with(
            "/queues/members/99",
            json={"member": expected_input},
        )

    @pytest.mark.parametrize(
        "event",
        [
            {"Interface": "Custom/1001", "Penalty": "0"},
            {"Interface": "PJSIP/1001", "Penalty": "invalid"},
        ],
    )
    def test_persistent_member_input_rejects_lossy_values(self, event: dict[str, str]) -> None:
        with pytest.raises(RuntimeError):
            QueueService._persistent_member_input(event, "1001")

    def test_ensure_member_reconciles_put_timeout_by_readback(
        self, mock_freepbx_client: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": [], "dynmembers": []},
            {"member": ["116"], "dynmembers": []},
        ]
        rest.put.side_effect = FreePBXTimeoutError("timed out")
        svc = QueueService(mock_freepbx_client, rest=rest)

        changed = svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))

        assert changed is True

    def test_ensure_member_propagates_unreconciled_put_timeout(
        self, mock_freepbx_client: MagicMock
    ) -> None:
        rest = MagicMock()
        rest.get.side_effect = [
            {"member": [], "dynmembers": []},
            {"member": [], "dynmembers": []},
        ]
        timeout = FreePBXTimeoutError("timed out")
        rest.put.side_effect = timeout
        svc = QueueService(mock_freepbx_client, rest=rest)

        with pytest.raises(FreePBXTimeoutError) as raised:
            svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))

        assert raised.value is timeout

    def test_ensure_member_requires_rest_client(self, mock_freepbx_client: MagicMock) -> None:
        svc = QueueService(mock_freepbx_client)

        with pytest.raises(RuntimeError, match="REST client is required"):
            svc.ensure_member_persistent(QueueMemberAdd(queue="99", extension="116"))
