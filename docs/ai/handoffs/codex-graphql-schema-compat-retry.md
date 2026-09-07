# HANDOFF: codex/graphql-schema-compat-retry

- objective: Unblock fresh extension provisioning before the add mutation.
- state: implementation complete; awaiting owner review and merge.
- changed:
  - `src/pyfreepbx/clients/freepbx.py` declares both `fetchExtension`
    operations with an `ID!` variable, matching FreePBX Core 16/17's
    `extensionId: ID` argument.
  - `tests/test_freepbx_client.py` locks the exact GraphQL variable contract
    for ordinary and generated-secret reads.
  - `CHANGELOG.md` records the compatibility correction.
- why: UAT job `e0a0b9c8-e46d-4713-b252-85b4d4d52147` failed with an HTTP 400
  GraphQL validation error before `addExtension`; its diagnostic operation was
  the generic `freepbx` read rather than `addExtension`. The SDK used
  `String!`, while FreePBX Core release/16.0 defines `extensionId` as `ID`.
- validation:
  - `uv run --extra dev pytest tests/test_freepbx_client.py -q` — 15 passed.
  - `uv run --extra dev pytest -q` — 394 passed, 2 documented synthetic XPASS.
  - changed-file Ruff check and format check — passed.
  - `git diff --check` — passed.
- risk: low. GraphQL serializes the existing string extension number as an ID;
  request count, timeout behavior, mutation behavior, and response parsing do
  not change.
- blockers: live validation and deployment remain owner-gated.
- next: open a draft pyfreepbx PR, wait for owner merge, pin that exact revision
  in UniqueOS, then repeat one owner-approved UAT provisioning attempt.
