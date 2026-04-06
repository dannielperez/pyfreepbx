"""Queue health and operational overview.

Demonstrates the HealthService for queue/endpoint monitoring
alongside the QueueService for config data.

Usage:
    export FREEPBX_HOST=pbx.example.com
    export FREEPBX_API_TOKEN=your-token
    export AMI_USERNAME=admin
    export AMI_SECRET=your-ami-secret
    python examples/queue_health.py
"""

from pyfreepbx import FreePBX

with FreePBX.from_env() as pbx:
    # --- Config data (GraphQL only, always works) ---
    print("=== Queue Configuration ===")
    queues = pbx.queues.list()
    for q in queues:
        print(f"  {q.queue_number:6s}  {q.name:20s}  strategy={q.strategy}")
    if not queues:
        print("  No queues configured.")
    print()

    # --- Live data (requires AMI) ---
    if not pbx.ami_available:
        print("AMI not configured — skipping live stats.")
        raise SystemExit(0)

    pbx.connect_ami()

    # Endpoint registration
    print("=== Endpoint Registration ===")
    ep = pbx.health.endpoint_summary()
    if ep:
        print(f"  Total: {ep.total}  Registered: {ep.registered}  "
              f"Unregistered: {ep.unregistered}  Unavailable: {ep.unavailable}")

    offline = pbx.health.unregistered_endpoints()
    if offline:
        print(f"\n  Offline endpoints ({len(offline)}):")
        for d in offline:
            print(f"    {d.name:20s}  state={d.state.value}")
    print()

    # Queue stats
    print("=== Queue Live Stats ===")
    stats = pbx.health.queue_overview()
    if stats:
        for qs in stats:
            print(
                f"  {qs.queue:15s}  "
                f"agents={qs.logged_in}  "
                f"available={qs.available}  "
                f"callers={qs.callers}  "
                f"avg_hold={qs.hold_time}s"
            )
    else:
        print("  No queue data available.")
