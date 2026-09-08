# Handoff: post-create convergence

## Changed files and why

- `src/pyfreepbx/services/extensions.py`: reconcile an acknowledged extension
  create through complete bulk inventory when the immediate exact read lags,
  then poll only read operations within one 2.5-second wall-clock deadline.
  Mutation replay remains forbidden and transport timeouts fail immediately.
- `src/pyfreepbx/clients/graphql.py` and `clients/freepbx.py`: accept an optional
  per-read timeout override so every convergence request is capped to the
  deadline's remaining budget without changing the default public behavior.
- `tests/test_extensions.py`: cover the live failure shape, bounded delay
  schedule, secret-safe errors, single mutation, and no multiplied transport
  timeout.
- `CHANGELOG.md`: document the corrected provisioning contract.

## Validation

- Focused extension/client tests: 62 passed.
- Full SDK suite: 406 passed, 2 documented xpasses.
- Scoped Ruff: passed.
- `git diff --check`: passed.
- Repository self-review: 0 BLOCK, 0 WARN.
- SDK-boundary review: OK.
- Stability review: OK after adding the shared monotonic deadline and
  remaining-budget request timeouts.
- Repository-wide Ruff and mypy remain red on pre-existing unrelated files;
  no reported finding points at the changed service or tests.

## Risks

- The complete bulk inventory can verify only non-secret extension identity;
  the secret is still read through the narrow single-extension query and never
  logged.
- Identity and secret convergence share one 2.5-second wall-clock deadline;
  each GraphQL request is capped to its remaining budget. Transport failures
  are not retried.

## Blockers and next step

- No implementation blocker. Open a draft SDK PR, pass CI, and obtain an owner
  merge. Then pin the exact merged SDK revision in UniqueOS, validate and ship
  through the owner-controlled UAT path before recovering extension 118 or
  attempting another live provisioning run.
