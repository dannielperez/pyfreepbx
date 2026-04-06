"""Run health checks against FreePBX and Asterisk.

Usage:
    export FREEPBX_HOST=pbx.example.com
    export FREEPBX_API_TOKEN=your-token
    export AMI_USERNAME=admin        # optional
    export AMI_SECRET=your-secret    # optional
    python examples/health_check.py
"""

from pyfreepbx import FreePBX

with FreePBX.from_env() as pbx:
    if pbx.ami_available:
        pbx.connect_ami()

    result = pbx.health.summary()
    print(f"Overall: {result.overall.value}\n")

    for check in result.checks:
        symbol = "✓" if check.status.value == "ok" else "✗"
        detail = f"  ({check.detail})" if check.detail else ""
        print(f"  {symbol} {check.name}: {check.status.value}{detail}")
