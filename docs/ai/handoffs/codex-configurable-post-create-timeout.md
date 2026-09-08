# Handoff: configurable post-create timeout

## Changed files and why

- `src/pyfreepbx/services/extensions.py`: expose the already-bounded
  post-create convergence window as the keyword-only `convergence_timeout`
  parameter, retaining the 2.5-second default.
- `tests/test_extensions.py`: prove a caller-supplied deadline controls the
  remaining request budget and reject non-positive values before any PBX read
  or write.
- `CHANGELOG.md`: document the backward-compatible public option.

## Validation

- Full SDK suite: 410 passed, 2 documented xpasses.
- Scoped Ruff and `git diff --check`: passed.
- Self-review must be rerun after this handoff is committed.
- SDK-boundary and stability reviews pending.

## Risks

- A caller may choose a longer wait, but each request remains capped to the
  shared deadline and no mutation retry is possible.

## Blockers and next step

- Validate, open a draft follow-up PR, and obtain owner merge before UniqueOS
  pins the SDK and passes an explicit convergence timeout.
