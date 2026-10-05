# Handoff: fix/t4212-ami-frame-crlf

- Scope: T-4212 / SEC-08. Reject CR, LF, and NUL in every rendered AMI action name, field name, and field value before socket I/O; apply the same validation to queue-member schemas.
- Files: `src/pyfreepbx/clients/ami.py`, `src/pyfreepbx/schemas/queue_member.py`, `tests/test_ami_client.py`, and `tests/test_queues.py`.
- Validation: focused security cases 9 passed; affected suites 139 passed; full SDK suite 520 passed and 2 xpassed; Ruff check passed; `git diff --check` passed.
- Baseline: Ruff format-check remains red on four touched files because of four pre-existing formatting differences outside this patch; `ruff format --diff` confirmed the candidate hunks are not implicated.
- Review: bypass/regression review `ship`; SDK-boundary review `OK`; stability review `OK`.
- Risk: malformed inputs now raise `ValueError` before any write while the authenticated socket remains usable. Normal action values, integers, Unicode, blank reasons, and public signatures are unchanged.
- Next: review and merge the SDK PR; only then advance UniqueOS's `vendor/pyfreepbx` gitlink to the reviewed merged commit and finalize the parent T-4212 PR.
