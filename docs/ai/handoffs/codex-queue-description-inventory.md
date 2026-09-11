# Queue description inventory

- **Changed:** `QueueService.list()` keeps AMI as the authoritative queue/member
  inventory and optionally enriches queue names from the FreePBX 16 queues REST
  collection (`GET /queues`). Invalid, absent, or unavailable REST enrichment
  falls back to the queue number without hiding live queues.
- **Why:** AMI `QueueSummary` exposes the queue identifier but not the configured
  FreePBX description, so consumers displayed `Queue 99 — 99` instead of the
  operator-facing description.
- **Validation:** `pytest tests/test_queues.py -q` (76 passed); scoped Ruff check
  and format checks passed; `git diff --check` passed.
- **Risk review:** SDK-boundary reviewer `OK`. Stability reviewer initially
  warned that raw HTTP-status or JSON-decoding failures could escape the
  optional enrichment boundary; the implementation now catches those bounded
  response failures and the added regression tests prove AMI inventory still
  falls back to queue numbers.
- **Risk:** low. One additional timeout-bounded REST read occurs per queue
  inventory call only when a REST client is configured. REST failure is
  non-authoritative and degrades to the prior queue-number behavior.
- **Blocker/next:** owner merge is required before UniqueOS can pin the exact SDK
  revision and refresh cached `PBXQueue.name` values on its next inventory sync.
