# HANDOFF: codex/registration-queue-evidence

- objective: Verify SIP registration through live queue-member state when endpoint AMI actions are denied.
- state: done
- changed: typed queue-member device state; bounded registration fallback; tests and changelog.
- validation: `uv run --extra dev python -m pytest tests/test_diagnostics.py tests/test_queues.py -q` (99 passed); targeted Ruff checks passed.
- risks: fallback is used only when endpoint reads raise AMIError and the caller supplies selected queues; unknown/missing queue state still fails closed.
- next: pin the merged SDK commit in UniqueOS and pass the provisioning job's selected queue numbers.
