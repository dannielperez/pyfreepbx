"""Queue service backed by Asterisk AMI and the FreePBX queues REST API.

FreePBX 16 exposes no queue fields in GraphQL. QueueSummary supplies live
inventory and QueueStatus supplies runtime members. Persistent queue-member
configuration uses the queues module REST API.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import quote

from pyfreepbx.exceptions import FreePBXTimeoutError, NotFoundError, QueueMemberNotFoundError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.inventory import InventoryListResult
from pyfreepbx.models.queue import Queue, QueueMember, QueueStats

if TYPE_CHECKING:
    from pyfreepbx.clients.ami import AMIClient
    from pyfreepbx.clients.freepbx import FreePBXClient
    from pyfreepbx.clients.rest import RestClient
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

    def __init__(
        self,
        client: FreePBXClient,
        ami: AMIClient | None = None,
        rest: RestClient | None = None,
    ) -> None:
        self._client = client
        self._ami = ami
        self._rest = rest

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
    # Persistent member configuration (FreePBX REST)
    # ------------------------------------------------------------------

    def ensure_member_persistent(self, payload: QueueMemberAdd) -> bool:
        """Persist one static member through the FreePBX queues module API."""
        return self.ensure_members_persistent([payload])

    def ensure_members_persistent(self, payloads: list[QueueMemberAdd]) -> bool:
        """Persist one queue's static members through the FreePBX queues API.

        Returns ``True`` when the configured member list changed and ``False``
        when every extension was already present. All payloads must target the
        same queue. The vendor endpoint replaces
        the complete static-member list, so this method always reads first and
        resubmits every member returned by FreePBX. Dynamic members are left
        untouched by omitting ``dynmembers`` from the update.

        FreePBX 16/17 returns static extension identifiers without their
        original channel type or penalty. Before writing, this method therefore
        reconciles each configured identifier against authoritative AMI
        ``QueueStatus`` data and fails closed unless every existing static
        member can be reconstructed without losing channel type or penalty.
        Existing REST order is retained as the stored membership position;
        additions retain payload order and each payload keeps its own penalty.

        This writes desired configuration but does not reload Asterisk. A
        caller performing one or more updates should invoke
        ``pbx.system.apply_config()`` once after the batch.

        The FreePBX endpoint has no conditional-write token. Callers must hold
        a cross-process lock for this queue across the complete method call.
        """
        if not payloads:
            return False
        queue = payloads[0].queue
        if any(payload.queue != queue for payload in payloads):
            raise ValueError("Persistent queue-member batches must target one queue.")
        additions: dict[str, int] = {}
        for payload in payloads:
            previous = additions.setdefault(payload.extension, payload.penalty)
            if previous != payload.penalty:
                raise ValueError(f"Conflicting penalties for queue member {payload.extension!r}.")

        self._require_rest("persist queue member")
        assert self._rest is not None

        path = f"/queues/members/{quote(queue, safe='')}"
        configured = self._rest.get(path)
        if configured is False:
            raise NotFoundError(f"Queue {queue!r} not found.")
        if not isinstance(configured, dict):
            raise RuntimeError("FreePBX returned an invalid queue-member response.")

        members = configured.get("member", [])
        if not isinstance(members, list) or not all(isinstance(item, str) for item in members):
            raise RuntimeError("FreePBX returned an invalid static-member list.")
        missing_additions = {
            extension: penalty
            for extension, penalty in additions.items()
            if extension not in members
        }
        if not missing_additions:
            return False

        existing_inputs = self._persistent_member_inputs(queue, members)
        submitted_members = [
            *existing_inputs,
            *(f"{extension},{penalty}" for extension, penalty in missing_additions.items()),
        ]
        expected_extensions = {*members, *missing_additions}
        try:
            updated = self._rest.put(path, json={"member": "\n".join(submitted_members)})
        except FreePBXTimeoutError as timeout:
            if self._persistent_readback_contains(path, expected_extensions):
                log.info(
                    "Verified queue %s member %s after mutation timeout",
                    queue,
                    ", ".join(missing_additions),
                )
                return True
            raise timeout
        if updated is not True:
            raise RuntimeError("FreePBX did not acknowledge the queue-member update.")

        if not self._persistent_readback_contains(path, expected_extensions):
            raise RuntimeError("FreePBX did not persist the complete queue-member set.")

        return True

    def _persistent_member_inputs(self, queue: str, extensions: list[str]) -> list[str]:
        if not extensions:
            return []
        self._require_ami("reconcile persistent queue members")
        assert self._ami is not None

        static_events: dict[str, dict[str, str]] = {}
        for event in self._ami.queue_status(queue=queue):
            if event.get("Event") != "QueueMember":
                continue
            if event.get("Membership", "").lower() != "static":
                continue
            extension = self._member_extension(event)
            if extension in static_events:
                raise RuntimeError(f"FreePBX returned duplicate static queue member {extension!r}.")
            static_events[extension] = event

        missing = [extension for extension in extensions if extension not in static_events]
        if missing:
            raise RuntimeError(
                "FreePBX could not reconcile static queue members from live status: "
                + ", ".join(missing)
            )
        return [
            self._persistent_member_input(static_events[extension], extension)
            for extension in extensions
        ]

    @staticmethod
    def _persistent_member_input(event: dict[str, str], extension: str) -> str:
        interface = event.get("Interface") or event.get("Name", "")
        match = re.match(r"^(Agent|PJSIP|SIP|IAX2|ZAP|DAHDI|Local)/", interface, re.IGNORECASE)
        if match is None:
            raise RuntimeError(
                f"FreePBX returned an unsupported interface for static member {extension!r}."
            )
        type_prefix = {
            "agent": "A",
            "pjsip": "P",
            "sip": "S",
            "iax2": "X",
            "zap": "Z",
            "dahdi": "D",
            "local": "",
        }[match.group(1).lower()]
        penalty = event.get("Penalty", "")
        if not penalty.isdigit():
            raise RuntimeError(
                f"FreePBX returned an invalid penalty for static member {extension!r}."
            )
        return f"{type_prefix}{extension},{penalty}"

    def _persistent_readback_contains(self, path: str, expected: set[str]) -> bool:
        assert self._rest is not None
        readback = self._rest.get(path)
        if not isinstance(readback, dict):
            raise RuntimeError("FreePBX returned an invalid queue-member read-back.")
        readback_members = readback.get("member", [])
        if not isinstance(readback_members, list) or not all(
            isinstance(item, str) for item in readback_members
        ):
            raise RuntimeError("FreePBX returned an invalid static-member read-back.")
        return expected.issubset(readback_members)

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

    def _require_rest(self, operation: str) -> None:
        if self._rest is None:
            raise RuntimeError(
                f"REST client is required to {operation}. Configure FreePBX API "
                "credentials to enable this feature."
            )

    @staticmethod
    def _member_interface(extension: str) -> str:
        """The dialplan interface shape shared by QueueAdd/QueueRemove/QueuePause."""
        return f"Local/{extension}@from-queue/n"

    @staticmethod
    def _member_extension(event: dict[str, str]) -> str:
        interface = event.get("StateInterface") or event.get("Interface") or event.get("Name", "")
        match = re.search(
            r"(?:Agent|PJSIP|SIP|IAX2|ZAP|DAHDI|Local)/([^@/]+)",
            interface,
            re.IGNORECASE,
        )
        return match.group(1) if match else interface

    @classmethod
    def _member_from_event(cls, event: dict[str, str]) -> QueueMember:
        return QueueMember(
            extension=cls._member_extension(event),
            name=event.get("MemberName") or event.get("Name"),
            paused=event.get("Paused") == "1",
        )
