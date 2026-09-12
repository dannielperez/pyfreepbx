# Handoff — normalize FreePBX queue-member identity hints

## Scope

Fix false-negative queue membership verification when FreePBX reports a live
member as `Local/<extension>@from-queue/n` with a separate
`StateInterface=hint:<extension>@ext-local`.

## Changed files and why

- `src/pyfreepbx/services/queues.py`: prefers the member channel identity over
  the device-state hint and normalizes the hint form when it is the only
  available identity.
- `tests/test_queues.py`: covers the real mixed channel/hint event shape and the
  hint-only fallback.
- `CHANGELOG.md`: records the corrected public queue-member normalization.

## Validation

- Full SDK suite: 461 passed, 2 expected xpasses.
- Focused queue suite: 81 passed.
- Ruff and format checks on changed files: passed.
- Full-repository Ruff surfaced unrelated existing baseline findings, tracked
  in UniqueOS as T-3858.
- `git diff --check`: passed.

## Risk and boundaries

The change is read-only normalization inside the vendor SDK. It does not issue
additional requests, change mutation payloads, retry writes, or broaden
credentials. Unknown member shapes retain the prior raw-value fallback.

## Next step

After owner merge, pin the exact SDK merge commit in UniqueOS and ship the
consumer-side bounded worker verification fix. Then retry the existing failed
provisioning job before creating another extension.
