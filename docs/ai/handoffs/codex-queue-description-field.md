# HANDOFF: codex/queue-description-field

- objective: Preserve FreePBX queue descriptions in synced operator inventory.
- state: done
- changed: `QueueService` now uses the exact `/queues/` collection route; regression expectation and changelog updated.
- validation: live read proved `/queues` returns 404 while `/queues/` returns queue 99 as `uniquesec-queue`; full SDK suite passed (465 passed, 2 expected XPASS); targeted Ruff and `git diff --check` passed.
- risks: read-only REST enrichment remains optional and still falls back to numeric queue IDs on any transport, permission, or payload failure.
- next: merge the SDK PR, pin the immutable commit in UniqueOS, deploy to UAT, run PBX inventory sync, and verify queue 99 renders as `Queue 99 — uniquesec-queue`.
