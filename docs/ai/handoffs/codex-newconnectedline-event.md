# HANDOFF: codex/newconnectedline-event · 2026-07-28T13:01:31Z

- **objective:** Restore pyfreepbx PR #27 CI after promoting `NewConnectedLine` from `UnknownEvent` to a typed DTO.
- **state:** done; listener replay expectations now include every typed `NewConnectedLine` frame in the answered, missed, and originate fixtures.
- **PR:** #27 draft · changed: `tests/test_ami_listener.py` plus this handoff.
- **validations:** `uv run --extra dev pytest tests/test_ami_listener.py tests/test_ami_parser.py -q` → 32 passed, 2 xpassed; full CI pytest with coverage → 269 passed, 2 xpassed; targeted Ruff check/format and `git diff --check` → OK.
- **baseline:** repository-wide Ruff (19 findings), format (9 files), and mypy (17 errors) remain non-blocking pre-existing debt; tracked in pyfreepbx issue #28.
- **risk:** low; test expectations only, matched to recorded fixture order; no runtime, transport, auth, retry, timeout, or live-vendor behavior changed.
- **blockers:** none.
- **next:** push the follow-up commit and confirm PR #27 GitHub Actions turns green; merge remains owner-only.
