# HANDOFF: codex/registration-queue-fallback-hardening

- objective: Keep queue-backed registration verification bounded and activate it only for AMI permission denial.
- state: done
- changed: typed `AMIPermissionError`; one-snapshot multi-queue member read; diagnostics fallback and regression tests; changelog.
- validation: `uv run --extra dev python -m pytest tests/test_ami_client.py tests/test_diagnostics.py tests/test_queues.py -q` (149 passed); targeted Ruff and `git diff --check` passed.
- risks: permission typing recognizes Asterisk's observed exact `Permission denied` response; other AMI failures remain terminal and fail closed.
- next: merge the SDK PR, pin that immutable commit in UniqueOS, then validate the UAT provisioning registration step.
