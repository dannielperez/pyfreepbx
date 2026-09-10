# Pending FreePBX queue configuration reconciliation

## Changed files and why

- `src/pyfreepbx/services/system.py`: normalize `fetchNeedReload` into an
  explicit, fail-closed boolean.
- `src/pyfreepbx/services/queues.py`: when configured static members are absent
  from live AMI state, apply an explicitly pending FreePBX configuration once,
  wait for bounded convergence, then reread before the replace-style write.
- `src/pyfreepbx/facade.py`: share the system service with the queue service.
- `tests/test_system_service.py`, `tests/test_queues.py`: cover required,
  current, ambiguous, converged, and non-converged recovery paths.
- `CHANGELOG.md`: document the compatibility recovery.

## Validation

- `uv run pytest`: 432 passed, 2 documented synthetic-fixture xpasses.
- Changed-file Ruff check and format check: passed.
- `git diff --check`: passed.

## Risks

- The recovery can issue one FreePBX config reload, but only after the
  authoritative reload-status endpoint explicitly reports that a reload is
  required. It never retries the mutation and stops before the queue write if
  convergence is not confirmed.
- Existing static member order, channel type, and penalty remain fail-closed and
  are reread from live AMI state after convergence.

## Blockers

- None locally. Human review/merge and downstream UniqueOS SDK pin are required
  before the UAT job can be retried.

## Next step

- Merge the SDK PR, pin its exact merge revision in UniqueOS, ship through the
  normal UAT gates, then retry the existing extension-125/queue-99 job once.
