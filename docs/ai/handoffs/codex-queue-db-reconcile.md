# Handoff — lossless queue reconciliation from read-only FreePBX DB

## Scope

Fix persistent queue assignment when both AMI `GetConfig` and `QueueStatus`
cannot expose all existing static members. The FreePBX queues REST update
replaces the complete list, so the SDK must recover every existing channel
type, position, and penalty before writing.

## Changed files and why

- `src/pyfreepbx/clients/queue_db.py`: adds a timeout-bounded, parameterized,
  read-only `queues_details` reader with a 500-member hard cap.
- `src/pyfreepbx/services/queues.py`: tries generated AMI config first, the
  direct read-only DB second, and live AMI status last; failures remain closed.
- `src/pyfreepbx/facade.py`: wires the reader whenever existing optional DB
  credentials are supplied.
- `tests/test_queue_db.py`, `tests/test_queues.py`, `tests/test_facade.py`:
  cover query bounds, ordering, malformed/oversized results, error fallback,
  preservation of existing member inputs, and facade wiring.
- `CHANGELOG.md`, `uv.lock`: document the behavior and synchronize the already
  declared optional `pymysql` dependency.

## Validation

- `uv run pytest --cov=pyfreepbx --cov-report=term-missing -q` — 460 passed,
  2 expected xpasses, 92% total coverage.
- Targeted queue/facade suite — 97 passed.
- Ruff on all changed files — passed.
- Mypy on all changed source files — passed.
- `git diff --check` — passed.
- Full-repository Ruff still reports pre-existing non-gating findings in OAuth,
  model/schema import placement, and service/test import formatting; the CI
  workflow marks lint and mypy `continue-on-error`.

## Safety and evidence

FreePBX 16 `Api/Rest/Queues.php` stores generated static member strings in
`queues_details.data` and their list positions in `flags`; its PUT endpoint
deletes and replaces all `member` rows. This change performs only `SELECT data
... WHERE id = %s AND keyword = %s ... LIMIT %s` through the optional read-only
connection. All mutations remain in the supported REST API and no transaction
spans network I/O.

## Deployment prerequisite / blocker

The current documented UAT DB principal has only `SELECT` on `asterisk.cdr`.
An owner-authorized infrastructure change must also grant that same read-only
principal `SELECT` on `asterisk.queues_details`; otherwise this new fallback
will safely report itself unavailable and the existing failure will remain.
Do not broaden the grant beyond this one table.

## Next step

After owner merge, pin the exact SDK merge commit in UniqueOS, pass CI and UAT
ship gates, apply the narrow read grant with explicit owner approval, then retry
only existing provisioning job `17323313-f376-4e82-9253-12b647e73f04` and verify
extension 119 is in queue 99 at penalty 0 before checking device registration.
