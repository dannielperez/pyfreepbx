# Handoff: FreePBX extension timeout reconciliation

## Changed files and why

- `src/pyfreepbx/clients/graphql.py`: normalize HTTP transport failures into
  SDK-owned exceptions without exposing request data.
- `src/pyfreepbx/exceptions.py` and `src/pyfreepbx/__init__.py`: add and export
  `FreePBXTimeoutError` as the timeout-specific `FreePBXTransportError` subtype.
- `src/pyfreepbx/services/extensions.py`: reconcile timeout-ambiguous extension
  creation and SIP-secret updates by read-back without replaying mutations; retry
  only one confirmed-create read.
- `tests/test_graphql_client.py` and `tests/test_extensions.py`: cover transport
  normalization, safe reconciliation, mismatch failure, and bounded read retry.
- `CHANGELOG.md`: document the public behavior and compatibility contract.

## Validation

- Targeted: `uv run --extra dev pytest tests/test_extensions.py tests/test_graphql_client.py -q`
  — 23 passed.
- Full suite: `uv run --extra dev pytest -q` — 335 passed, 2 expected xpasses.
- Ruff on all changed Python files — passed.
- Mypy on changed implementation files — passed.
- `scripts/ai/self_review.sh` from UniqueOS — 0 BLOCK, 0 WARN.
- SDK-boundary reviewer — OK.
- Stability reviewer — OK.

## Risks

- An add timeout is accepted only when a read-back finds the requested extension
  number and exact display name. Any missing, mismatched, or still-unreachable
  state preserves failure.
- Mutation requests are never retried. The only retry is one bounded read-only
  fetch after a confirmed add response.

## Blockers

- None in the SDK patch. No live FreePBX call was made.

## Next step

- Owner reviews and merges the draft pyfreepbx PR. Then pin that exact revision
  in an isolated UniqueOS PR, ship through CI/UAT, and retry the authorized
  Guardia 11 provisioning flow with queue 99 only after deployment verification.
