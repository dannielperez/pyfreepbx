"""Queue service — config from GraphQL, live stats from AMI.

GraphQL queries are PROVISIONAL (see extensions.py header for details).
AMI actions (QueueSummary, QueueStatus, QueueAdd, QueueRemove) are
well-documented and stable.
"""

from __future__ import annotations

import warnings

from pyfreepbx.clients.ami import AMIClient
from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.exceptions import NotFoundError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.queue import Queue, QueueMember, QueueStats
from pyfreepbx.schemas.queue_member import QueueMemberAdd, QueueMemberRemove

log = get_logger("services.queues")


class QueueService:
    """Operations on FreePBX call queues.

    Config/inventory data comes from FreePBXClient (GraphQL).
    Live operational data comes from AMIClient.
    """

    def __init__(self, client: FreePBXClient, ami: AMIClient | None = None) -> None:
        self._client = client
        self._ami = ami

    # ------------------------------------------------------------------
    # Config queries (GraphQL)
    # ------------------------------------------------------------------

    def list(self) -> list[Queue]:
        """Fetch all queue configurations from GraphQL.

        .. warning:: **Experimental** — the Queue module may not expose
           GraphQL types in all FreePBX versions. This query is the least
           likely to work out-of-the-box. Run a GraphQL introspection
           query on your instance to verify.
        """
        warnings.warn(
            "QueueService.list() uses a provisional GraphQL query. Queue "
            "module GraphQL support is undocumented and may not exist.",
            stacklevel=2,
            category=UserWarning,
        )
        raw = self._client.fetch_all_queues()

        queues: list[Queue] = []
        for item in raw:
            queues.append(
                Queue(
                    queue_number=item.get("extension", item.get("queue_number", "")),
                    name=item.get("name", ""),
                    strategy=item.get("strategy"),
                )
            )

        log.debug("Listed %d queues", len(queues))
        return queues

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
            members.append(
                QueueMember(
                    extension=event.get("Name", event.get("StateInterface", "")),
                    name=event.get("MemberName") or event.get("Name"),
                    paused=event.get("Paused") == "1",
                )
            )

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
            Interface=f"Local/{payload.extension}@from-queue/n",
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
            Interface=f"Local/{payload.extension}@from-queue/n",
        )
        if resp.get("Response") != "Success":
            msg = resp.get("Message", "QueueRemove failed")
            raise RuntimeError(f"Failed to remove member: {msg}")

        log.info("Removed %s from queue %s (runtime)", payload.extension, payload.queue)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_ami(self, operation: str) -> None:
        if self._ami is None:
            raise RuntimeError(
                f"AMI client is required for {operation}. "
                "Configure AMI credentials to enable this feature."
            )
