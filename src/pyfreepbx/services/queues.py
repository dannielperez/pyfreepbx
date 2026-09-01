"""Queue service backed by Asterisk AMI.

FreePBX 16 exposes no queue fields in GraphQL. QueueSummary supplies inventory
and QueueStatus supplies the members for each queue.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pyfreepbx.exceptions import NotFoundError, QueueMemberNotFoundError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.inventory import InventoryListResult
from pyfreepbx.models.queue import Queue, QueueMember, QueueStats

if TYPE_CHECKING:
    from pyfreepbx.clients.ami import AMIClient
    from pyfreepbx.clients.freepbx import FreePBXClient
    from pyfreepbx.schemas.queue_member import (
        QueueMemberAdd,
        QueueMemberPause,
        QueueMemberRemove,
    )

log = get_logger("services.queues")


class QueueService:
    """Operations on FreePBX call queues.

    Inventory and live operational data come from AMIClient.
    """

    def __init__(self, client: FreePBXClient, ami: AMIClient | None = None) -> None:
        self._client = client
        self._ami = ami

    # ------------------------------------------------------------------
    # Inventory (AMI)
    # ------------------------------------------------------------------

    def list(self) -> list[Queue]:
        """Fetch queue inventory and members from AMI."""
        self._require_ami("queue inventory")
        assert self._ami is not None
        summaries = self._ami.queue_summary()
        members_by_queue: dict[str, list[QueueMember]] = {}
        for event in self._ami.queue_status():
            if event.get("Event") != "QueueMember":
                continue
            queue_number = event.get("Queue", "")
            members_by_queue.setdefault(queue_number, []).append(self._member_from_event(event))
        queues = [
            Queue(
                queue_number=summary.queue,
                name=summary.queue,
                members=members_by_queue.get(summary.queue, []),
            )
            for summary in summaries
        ]

        log.debug("Listed %d queues", len(queues))
        return queues

    def list_result(self) -> InventoryListResult[Queue]:
        """Fetch queue inventory with an authoritative-response signal.

        AMI queue methods return only after receiving their ``*Complete``
        marker, so a successful result is authoritative even when empty.
        """
        return InventoryListResult(items=self.list(), complete=True)

    def get(self, queue_number: str) -> Queue:
        """Fetch a single queue by number.

        .. warning:: **Experimental** — see :meth:`list` for GraphQL caveats.

        Currently filters from the full list.

        Raises:
            NotFoundError: If the queue does not exist.
        """
        for q in self.list():
            if q.queue_number == queue_number:
                return q
        raise NotFoundError(f"Queue {queue_number!r} not found.")

    # ------------------------------------------------------------------
    # Live status (AMI)
    # ------------------------------------------------------------------

    def stats(self, queue: str | None = None) -> list[QueueStats]:
        """Fetch live queue statistics from AMI QueueSummary.

        Args:
            queue: Optional queue name to filter. ``None`` returns all.

        Returns:
            One :class:`QueueStats` per queue.
        """
        self._require_ami("queue stats")
        assert self._ami is not None
        return self._ami.queue_summary(queue=queue)

    def members(self, queue_number: str) -> list[QueueMember]:
        """Fetch live member status for a queue via AMI QueueStatus.

        Returns the current runtime members with their state. This
        reflects the actual Asterisk runtime, not the FreePBX config.

        Args:
            queue_number: Queue to query.

        Returns:
            List of :class:`QueueMember` for the given queue.
        """
        self._require_ami("queue members")
        assert self._ami is not None

        events = self._ami.queue_status(queue=queue_number)

        members: list[QueueMember] = []
        for event in events:
            if event.get("Event") != "QueueMember":
                continue
            members.append(self._member_from_event(event))

        log.debug("Queue %s has %d live members", queue_number, len(members))
        return members

    # ------------------------------------------------------------------
    # Member management (AMI — runtime only)
    # ------------------------------------------------------------------

    def add_member_runtime(self, payload: QueueMemberAdd) -> None:
        """Add a member to a queue at runtime via AMI QueueAdd.

        **Runtime-only** — the member will be lost on Asterisk reload
        or restart. For persistent config changes, use the FreePBX
        admin UI or a confirmed GraphQL mutation.

        Args:
            payload: Validated add-member input.
        """
        self._require_ami("add queue member")
        assert self._ami is not None

        resp = self._ami.run_action(
            "QueueAdd",
            Queue=payload.queue,
            Interface=self._member_interface(payload.extension),
            Penalty=str(payload.penalty),
            MemberName=payload.extension,
        )
        if resp.get("Response") != "Success":
            msg = resp.get("Message", "QueueAdd failed")
            raise RuntimeError(f"Failed to add member: {msg}")

        log.info("Added %s to queue %s (runtime)", payload.extension, payload.queue)

    def remove_member_runtime(self, payload: QueueMemberRemove) -> None:
        """Remove a member from a queue at runtime via AMI QueueRemove.

        **Runtime-only** — same caveats as :meth:`add_member_runtime`.

        Args:
            payload: Validated remove-member input.
        """
        self._require_ami("remove queue member")
        assert self._ami is not None

        resp = self._ami.run_action(
            "QueueRemove",
            Queue=payload.queue,
            Interface=self._member_interface(payload.extension),
        )
        if resp.get("Response") != "Success":
            msg = resp.get("Message", "QueueRemove failed")
            # Asterisk reports an already-absent member/queue in English
            # ("Unable to remove interface: Not there" / "No such queue").
            # Interpreting that wording is a vendor quirk owned HERE, so
            # consumers can catch a typed error instead of matching strings.
            lowered = msg.lower()
            if "not there" in lowered or "no such" in lowered:
                raise QueueMemberNotFoundError(msg)
            raise RuntimeError(f"Failed to remove member: {msg}")

        log.info("Removed %s from queue %s (runtime)", payload.extension, payload.queue)

    def pause_member_runtime(self, payload: QueueMemberPause) -> None:
        """Pause/unpause a runtime queue member via AMI QueuePause.

        Targets the same ``Local/<ext>@from-queue/n`` member interface that
        :meth:`add_member_runtime` creates, so pause always addresses the
        member QueueAdd registered.

        Args:
            payload: Validated pause input.
        """
        self._require_ami("pause queue member")
        assert self._ami is not None

        self._ami.queue_pause(
            queue=payload.queue,
            interface=self._member_interface(payload.extension),
            paused=payload.paused,
            reason=payload.reason or None,
        )
        log.info(
            "%s %s in queue %s (runtime)",
            "Paused" if payload.paused else "Unpaused",
            payload.extension,
            payload.queue,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_ami(self, operation: str) -> None:
        if self._ami is None:
            raise RuntimeError(
                f"AMI client is required for {operation}. "
                "Configure AMI credentials to enable this feature."
            )
        if not self._ami.connected:
            self._ami.connect()
        if not self._ami.authenticated:
            self._ami.login(events=False)

    @staticmethod
    def _member_interface(extension: str) -> str:
        """The dialplan interface shape shared by QueueAdd/QueueRemove/QueuePause."""
        return f"Local/{extension}@from-queue/n"

    @staticmethod
    def _member_extension(event: dict[str, str]) -> str:
        interface = event.get("StateInterface") or event.get("Name", "")
        match = re.search(r"(?:Local|PJSIP|SIP)/([^@/]+)", interface)
        return match.group(1) if match else interface

    @classmethod
    def _member_from_event(cls, event: dict[str, str]) -> QueueMember:
        return QueueMember(
            extension=cls._member_extension(event),
            name=event.get("MemberName") or event.get("Name"),
            paused=event.get("Paused") == "1",
        )
