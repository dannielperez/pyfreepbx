# Apply-config convergence

- **Changed:** `SystemService.apply_config_and_wait()` performs one non-retryable
  `doreload`, polls `fetchNeedReload` within a caller-supplied aggregate timeout,
  and returns a typed acknowledgement/convergence result. GraphQL mutations and
  reload-status reads accept a remaining per-call timeout.
- **Why:** FreePBX 16 can return `status=false` after accepting the asynchronous
  reload. Consumers must verify authoritative reload state without interpreting
  vendor messages or replaying the mutation.
- **Validation:** 423 tests passed with two documented synthetic-fixture xpasses;
  focused Ruff, format, mypy, and diff checks passed. Repository-wide Ruff/mypy
  remain red on unrelated baseline files that this branch does not touch.
- **Risk:** low-to-medium. Existing `apply_config()` and
  `config_reload_status()` callers remain compatible; the new facade method is
  opt-in and every external call is timeout-bounded.
- **Next:** publish a draft SDK PR, then pin its owner-merged revision in the
  UniqueOS consumer PR. Never merge or release from this lane.
