# Passive legacy PBX collector

Standalone Python 2.7/3 scripts for appliances that cannot run the Python 3 SDK.
Vendor parsing belongs here; application code consumes the normalized version-1
snapshot. These tools do not change SIP, tunnels, firewalls, or endpoint settings.

`media_evidence.py` requires Asterisk CLI, tcpdump, timeout, iptables, and optional
AWS CLI. It consumes its JSON config as the first argument; configuration supplies
`pbx_addresses`, `expected_extensions`, `source_id`, `output`, `capture_status`, and
optional `s3_uri`. Deploy `queue_stability.py` beside the collector. The process
requires the appliance privileges needed by packet capture and read-only probes.
The existing firewall probe matches the managed legacy PBX rules; adapt that
probe before using it on another installation.

The collector retains no audio payload or SIP credentials. It correlates live
bridges with independently observed SIP negotiation and counts voice RTP only.
Its `passive_bridge_transport_v1` contract excludes ringing, queue announcements,
DTMF, comfort noise, ambiguous captures and packet loss. Hardware mute and human
operator identity remain unknown, so passive evidence cannot authorize a reboot.

Evidence is emitted every 20 seconds. Overall alert latency also includes upload
and the application's ingestion/delivery schedules. It is not instantaneous and
does not prove human audibility or identify every technical hangup cause.

The optional `queue_log` path defaults to `/var/log/asterisk/queue_log`. Reads are
bounded to 2 MiB. A complete five-minute history is required, including after log
rotation. Three distinct answered calls lasting at most ten seconds are a symptom
of instability, not proof of a network drop. Unanswered and long calls do not count.
Missing/truncated evidence stays unknown, not zero.

The optional `route_guard_status` and `route_guard_manifest` paths default to the
existing appliance guard paths. Only fresh guard readback for explicitly approved
destinations can report a valid return route; deferred/conflicting/saved route
drift reports false. Unapproved sites and stale evidence remain unknown. This is
a PBX return-path check, not a full site firewall or WAN health assessment.

Tests: `PYTHONPATH=src python -m pytest tests/test_media_collector.py tests/test_queue_stability.py`.
The legacy standalone scripts deliberately retain Python 2 syntax and are outside
the Python 3 package's Ruff/mypy targets. Tests run under the supported Python 3 SDK.
