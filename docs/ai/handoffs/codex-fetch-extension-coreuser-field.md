# Handoff: `codex/fetch-extension-coreuser-field`

## Changed files and why

- `src/pyfreepbx/clients/freepbx.py`: query `extensionId` only on the outer
  FreePBX extension object and query `extension` on the nested `coreuser`.
- `tests/test_freepbx_client.py`: assert the two GraphQL types retain their
  distinct identifier fields for both identity and secret reads.
- `CHANGELOG.md`: correct the prior field-shape claim and record the schema fix.

## Evidence

- Guardia 11 create-new diagnostic job
  `befebcdf-40e0-43c4-b0bb-6e56c962ab7e` confirmed extension 119 was present,
  then `FetchExtensionSecret` failed GraphQL validation with HTTP 400.
- FreePBX Core `release/16.0` and `release/17.0` define `extensionId` on the
  outer `extension` type and `extension` plus `extPassword` on `coreuser`.

## Validation

- `uv run --extra dev pytest tests/test_freepbx_client.py -q` — 14 passed.
- `uv run --extra dev ruff check src/pyfreepbx/clients/freepbx.py tests/test_freepbx_client.py` — passed.
- `uv run --extra dev ruff format --check src/pyfreepbx/clients/freepbx.py tests/test_freepbx_client.py` — passed.
- `uv run --extra dev pytest -q` — 415 passed, 2 documented XPASS.
- Repository-wide Ruff remains red on 14 pre-existing findings in untouched
  OAuth/model/schema/service/test files; this change adds no lint findings.

## Risks and compatibility

- Low and read-only: this changes only GraphQL field selection. The SDK's
  normalized response remains `{"extension": ...}`.
- No live FreePBX calls were made.

## Next step

- Run focused and complete SDK tests, then self-review and open a draft PR.
