HANDOFF: fix/t1228-ami-resilience · 2026-07-12T10:01:50Z
- objective: harden AMI recovery, multi-event bounds, and privileged-action surfaces for T-1228
- state: done · PR: pending draft · changed: AMI client/config and focused tests
- validations: `.venv/bin/python -m pytest` OK 233 passed + 2 xpassed; changed-file Ruff OK; targeted mypy OK
- review-fanout: stability-reviewer OK; sdk-boundary-reviewer OK; migration-safety n/a (no schema/data change)
- blockers: none
- risk: RISK:med · reconnect never replays an interrupted action; QueuePause remains an explicit runtime mutation
- next: self-review, commit, push, open draft PR · knowledge: n/a
