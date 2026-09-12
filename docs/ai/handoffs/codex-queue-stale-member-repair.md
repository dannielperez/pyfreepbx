# Queue stale-member repair

## Changed files and why

- `src/pyfreepbx/clients/ami.py`: adds a narrow, read-only typed query for
  generated queue member lines in `queues_additional.conf`.
- `src/pyfreepbx/services/queues.py`: preserves existing channel types,
  penalties, and order from generated config when live queue status is stale;
  retains the existing live-status fallback and fail-closed behavior.
- `tests/test_ami_client.py`, `tests/test_queues.py`: cover ordering, injection
  rejection, stale runtime state, and AMI permission fallback.
- `src/pyfreepbx/models/device.py`, `src/pyfreepbx/services/diagnostics.py`:
  expose a typed, timeout-parameterized endpoint registration convergence wait
  so consumers make one SDK call instead of parsing and polling AMI state.
- `tests/test_diagnostics.py`: covers converged and zero-timeout registration
  waits.
- `CHANGELOG.md`: records the corrected reconciliation behavior.

## Validation

- `uv run --extra dev pytest tests/test_ami_client.py tests/test_queues.py -q`
  — 125 passed.
- `.venv/bin/python -m pytest -q` — 448 passed, 2 expected XPASS synthetic
  fixtures.
- Targeted Ruff and mypy checks for changed source/tests — passed.

## Risks and compatibility

- The new AMI request is bounded by the existing AMI socket timeout and reads
  only one fixed generated configuration file/category.
- If `GetConfig` is denied, reconciliation falls back to the prior live-status
  behavior. If neither source can reconstruct every REST-listed member, no
  queue mutation occurs.

## Blockers and next step

- Owner merge is required. Then UniqueOS must pin the merged SDK commit and ship
  it before retrying the existing UAT provisioning job for extension 119.
