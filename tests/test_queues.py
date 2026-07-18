"""Tests for QueueService."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pyfreepbx.exceptions import NotFoundError
from pyfreepbx.models.queue import QueueStats
from pyfreepbx.schemas.queue_member import QueueMemberAdd, QueueMemberRemove
from pyfreepbx.services.queues import QueueService

if TYPE_CHECKING:
    from unittest.mock import MagicMock


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
        assert members[1].paused is True

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
