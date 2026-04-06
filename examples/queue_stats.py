"""Fetch live queue statistics via AMI.

Usage:
    export FREEPBX_HOST=pbx.example.com
    export FREEPBX_API_TOKEN=your-token
    export AMI_USERNAME=admin
    export AMI_SECRET=your-ami-secret
    python examples/queue_stats.py
"""

from pyfreepbx import FreePBX

with FreePBX.from_env() as pbx:
    pbx.connect_ami()

    stats = pbx.queues.stats()
    for qs in stats:
        print(
            f"  {qs.queue:15s}  "
            f"agents={qs.logged_in}  "
            f"available={qs.available}  "
            f"callers={qs.callers}  "
            f"avg_hold={qs.hold_time}s"
        )

    if not stats:
        print("  No queues found.")
