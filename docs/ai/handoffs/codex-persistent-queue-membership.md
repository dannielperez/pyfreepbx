# Handoff: codex/persistent-queue-membership

## Changed files and why

- `src/pyfreepbx/services/queues.py`: add an SDK-owned, idempotent persistent
  static queue-member operation and same-queue batch API using the FreePBX
  queues REST API, with lossless type/penalty reconstruction from AMI and
  full-set read-back.
- `src/pyfreepbx/clients/rest.py`: map HTTP timeouts to the existing typed
  `FreePBXTimeoutError` contract so indeterminate PUTs can be reconciled.
- `src/pyfreepbx/facade.py`: provide the existing REST client to QueueService.
- `tests/test_queues.py`: cover merge/preserve behavior, idempotency, path
  encoding, malformed responses, negative acknowledgements, and read-back.
- `CHANGELOG.md`: document the public SDK method and caller-owned batch reload.

## Validation

- Targeted queue/facade/REST tests: `86 passed`.
- Full SDK: `379 passed, 2 xpassed`. The two XPASS cases are pre-existing
  synthetic AMI transfer cases.
  synthetic AMI transfer cases.
- Ruff check and `git diff --check`: passed.
- SDK-boundary review: OK.
- Runtime-stability review: OK, conditional on the documented UniqueOS
  cross-process per-queue lock spanning the complete SDK call.

## Risks

- The official FreePBX 16/17 REST read response omits static member channel
  types and penalties. The SDK reconciles them from AMI and fails closed if
  every existing static member cannot be reconstructed exactly.
- FreePBX exposes no ETag or atomic add route. Consumers must serialize
  concurrent desired-config writes for the same queue.
- Multiple new members for one queue can be submitted in one SDK call, so no
  intermediate apply is required before a later member can be reconciled.
- The method writes desired configuration but intentionally does not reload
  Asterisk. Consumers should perform one bounded `apply_config()` after all
  queue updates in a batch.

## Blockers and next step

- Owner merge is required before UniqueOS can pin and consume this method.
- After merge, update the UniqueOS queue provider to persist selected
  memberships, apply configuration once, and validate live membership.
