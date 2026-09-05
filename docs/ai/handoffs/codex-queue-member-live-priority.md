# Queue member live priority handoff

## Changed files and why

- `src/pyfreepbx/models/queue.py`: expose the AMI queue-member penalty as typed live state.
- `src/pyfreepbx/services/queues.py`: update an existing static member's requested penalty without changing its list position, and parse live penalty from AMI.
- `tests/test_queues.py`: cover live penalty parsing, idempotence, and an in-place priority update.

## Validation

- `PYTHONPATH=src .../pytest -q tests/test_queues.py`: 62 passed.
- `PYTHONPATH=src .../pytest -q`: 385 passed, 2 expected xpasses.
- Targeted Ruff on changed files: passed.
- Repository-wide Ruff still reports 14 pre-existing findings in unrelated files.
- `git diff --check`: passed.

## Risks and blockers

- The FreePBX REST read-back omits penalty, so callers must apply configuration and verify the requested penalty through AMI before reporting success.
- No live PBX or credential access was performed.

## Next step

- Owner reviews and merges the SDK PR. UniqueOS can then pin the merged revision and use the typed live penalty for bounded post-apply verification.
