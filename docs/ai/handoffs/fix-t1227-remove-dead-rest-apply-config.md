HANDOFF: fix/t1227-remove-dead-rest-apply-config · 2026-07-12T09:49:07Z
- objective: remove nonexistent diagnostics REST calls and expose typed FreePBX config-reload GraphQL operations
- state: done
- PR: pending draft · changed: diagnostics, system service/models, facade, tests, README/changelog
- validations: pytest 220 passed + 2 xpassed; targeted pytest 56 passed; changed-file Ruff/format OK; targeted mypy OK; self-review 0 BLOCK/0 WARN
- blockers: merge and downstream UniqueOS pin are owner-gated
- next: review draft PR; merge pyfreepbx; pin merged commit in UniqueOS · knowledge: n/a
- risk: apply_config is a remote mutation and must remain consumer approval-gated; timeout-after-acceptance is indeterminate and never auto-retried
- review-fanout: stability WARNING resolved by explicit non-retry contract + timeout test; sdk-boundary OK; migration n/a
