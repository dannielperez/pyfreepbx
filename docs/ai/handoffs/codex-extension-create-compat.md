# HANDOFF: codex/extension-create-compat

- objective: Make fresh device-only SIP extension creation compatible with the
  FreePBX Core Quick Create contract used by releases 15, 16, and 17.
- state: implementation complete; awaiting independent review and owner merge.
- changed:
  - `src/pyfreepbx/schemas/extension_create.py` adds an explicit
  nullable `user_management_enabled` option; omission preserves the public SDK
  behavior and device-only consumers can explicitly disable User Management.
  - `src/pyfreepbx/services/extensions.py` maps that option to `umEnable` and
    supplies the normalized `PJSIP/<extension>` or `SIP/<extension>` channel.
  - `tests/test_extensions.py` locks the live-shaped Guardia 11 create payload.
  - `CHANGELOG.md` records the compatibility fix.
- why: The deployed Guardia 11 job selected extension 116 correctly but failed
  inside FreePBX `addExtension` with `GraphQLError`. The only provisioning job
  that reached device push reused extension 4401 and therefore never exercised
  `addExtension`. FreePBX Core's official 15/16/17 resolver defaults omitted
  `umEnable` to the User Management path and consumes `channelName` in Quick
  Create even though GraphQL declares both fields optional.
- validation:
  - `uv run --extra dev pytest tests/test_extensions.py -q` — 21 passed.
  - `uv run --extra dev pytest -q` — 340 passed, 2 pre-existing synthetic XPASS.
  - touched-file Ruff check and format check — passed.
  - touched-source mypy — passed.
  - `git diff --check` — passed.
- risk: low-to-medium. The payload adds fields accepted by the official FreePBX
  15/16/17 `addExtensionInput` schemas. Existing callers still omit `umEnable`;
  no mutation retry, timeout, or secret behavior changes. Non-SIP technologies
  do not receive a fabricated channel.
- review-fanout:
  - stability-reviewer: OK — no extra calls/retries; existing timeout and
    ambiguous-write reconciliation behavior is unchanged.
  - sdk-boundary-reviewer: OK — compatibility mapping remains inside pyfreepbx
    and omission preserves the public SDK contract.
  - migration-safety-reviewer: n/a — no model, migration, or backfill changes.
- blockers: live validation and deployment remain owner-gated. The actual UAT
  GraphQL message was intentionally redacted by UniqueOS, so the deployed result
  still requires a single owner-approved post-deploy provisioning validation.
- next:
  1. independent SDK-boundary and stability review;
  2. open a draft pyfreepbx PR and wait for owner merge;
  3. pin the merged SDK commit in an isolated UniqueOS PR;
  4. separately remediate the AMI QueueAdd permission/configuration gap.
