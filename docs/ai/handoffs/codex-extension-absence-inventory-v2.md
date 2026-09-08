# Extension creation absence preflight

## Problem and change

On the deployed FreePBX, fetching an absent extension (118 and a separate unused
number) raises `GraphQLError`/HTTP 400 with an internal-server-error fingerprint;
fetching existing extensions works, and the complete extension inventory succeeds.
Creation therefore stops in its absence check before any mutation.

`src/pyfreepbx/services/extensions.py` now falls back to inventory only after a
GraphQL lookup error. It permits creation only if inventory explicitly reports
complete and the requested number is absent. Existing numbers raise a conflict;
incomplete or failed inventory blocks all writes. Normal lookup behavior is
unchanged. `tests/test_extensions.py` covers both creation entry points, complete
absence, incomplete inventory, existing numbers, and fallback transport failure.

## Validation

- `uv run --extra dev pytest tests/test_extensions.py -q`: 37 passed.
- `uv run --extra dev pytest -q`: 402 passed, 2 documented synthetic-fixture XPASS.
- `uv run --extra dev ruff check src/pyfreepbx/services/extensions.py tests/test_extensions.py`: pass.
- `uv run --extra dev ruff format --check src/pyfreepbx/services/extensions.py tests/test_extensions.py`: pass.
- No Django check applies to this standalone SDK.

## Scope and risks

Refreshed onto `origin/main` at `3604a6471358ff2904c0a295ad04d3b4001c258e`,
preserving the merged single-extension `user.extensionId` compatibility fix. The
inventory fallback adds one bounded read only on the GraphQL-error path. A generic
GraphQL error by itself is never interpreted as absence, and incomplete inventory
fails closed. The normal preflight-to-create race remains unchanged.

No deployment, live mutation, credential read, or retry was performed from this
branch. The next step is owner review and merge of the SDK PR, followed by an exact
UniqueOS pin bump and ordinary CI/UAT deployment. A new Guardia 11 attempt remains
separately action-time owner-gated after deployment.
