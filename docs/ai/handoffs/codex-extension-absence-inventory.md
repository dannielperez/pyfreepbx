# Extension creation absence preflight

## Problem and change
On the deployed FreePBX, fetching an absent extension (118 and a separate unused
number) raises GraphQLError/Internal server error; fetching existing extensions
works. The complete extension inventory succeeds. Creation therefore stops in
its absence check before any mutation.

`src/pyfreepbx/services/extensions.py` now falls back to inventory only after a
GraphQL lookup error. It permits creation only if inventory explicitly reports
complete and the requested number is absent. Existing numbers raise a conflict;
incomplete or failed inventory blocks all writes. Normal lookup behavior is
unchanged. `tests/test_extensions.py` covers both creation entry points, complete
absence, incomplete inventory, existing numbers, and fallback transport failure.

## Validation
- `uv run --extra dev pytest tests/test_extensions.py -q`: 37 passed.
- `uv run --extra dev pytest -q`: 402 passed, 2 existing synthetic-fixture XPASS.
- Changed-file Ruff check and format: pass.
- Repository-wide Ruff: 14 existing errors in unchanged files; format check
  flags 10 unchanged files. No unrelated formatting changes made.
- No Django check applies to this standalone SDK.

## Scope and risks
Based on freshly fetched origin/main a1799eb; the fix was absent there and in
existing create-compat and timeout-reconcile worktrees. Local only; no push,
deploy, live mutation, or secret rotation. Inventory adds one bounded read on
the GraphQL error path. The normal preflight-to-create race remains unchanged.
A generic GraphQL error by itself is never interpreted as absence.

Before provisioning Guardia 11 again, reconcile already-created extensions
10099, 116, and 117 rather than allocating more numbers. This correction does
not repair handset registration or establish the cause of the wider outage.
Next step: review this SDK commit, then explicitly authorize release/pinning
and deployment through the usual production process.
