# Handoff: secret-update convergence

## Changed files and why

- `src/pyfreepbx/services/extensions.py`: give ambiguous `updateExtension`
  responses a bounded, read-only secret convergence window. The mutation remains
  single-shot and callers may tune the shared deadline.
- `tests/test_extensions.py`: prove delayed GraphQL/read-model convergence,
  single-mutation behavior, bounded per-read timeouts, and validation before I/O.
- `CHANGELOG.md`: document the backward-compatible behavior.

## Validation

- Full SDK suite: 415 passed, 2 documented xpasses.
- Scoped Ruff, mypy, and `git diff --check`: passed.
- SDK-boundary review: OK.
- Stability review: OK.

## Risks

- Ambiguous secret updates may wait up to 2.5 seconds by default. Each read gets
  only the remaining deadline budget, transport failure stops the loop, and the
  secret mutation is never retried.

## Blockers and next step

- Open a draft SDK PR and obtain owner merge. Then pin the exact SDK revision in
  UniqueOS and pass its configured PBX convergence timeout to `update_secret()`.
