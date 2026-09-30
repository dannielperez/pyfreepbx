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

## Audio SDP scope

Audio direction, codec mappings and hold state are evaluated inside the audio
media section, inheriting session direction only when audio has no override.
Send-only video does not invalidate send/receive audio. Multiple audio streams,
zero audio ports, audio hold, truncated messages and ambiguous renegotiation stay
unclassified. This repair does not relax the independent bridge or packet-loss
gates, and does not make packet evidence a human audibility test.

## Approved VPN media NAT guard (Python 3, VPN hub only)

`media_nat_guard.py` is a separate, opt-in writer. It restores **missing runtime
rules only** when the root-owned manifest and exact saved WireGuard PostUp and
PostDown commands approve the same pair, live peer ownership and routes agree,
and both peers have fresh handshakes. It never invents exemptions for newly
observed phones, edits saved configuration, flushes conntrack, restarts a tunnel
or phone, or rewrites another rule. Duplicate/misordered rules and saved policy
drift require review. Unknown evidence is never reported healthy.

Manifest example (replace example addresses and public peer identities with
reviewed inventory; no private keys belong here):

```json
{
  "version": 1,
  "source_id": "monitored-pbx-uuid",
  "approved": [{
    "extension": "1234",
    "panel": "10.40.1.241",
    "pbx": "10.254.250.11",
    "panel_peer": "verified-site-public-key",
    "pbx_peer": "verified-pbx-public-key",
    "comment": "approved-panel-media"
  }]
}
```

For each direction, the approved saved rule must be an exact `/32` pair, `-o
wg0 -p udp --dport 10000:20000 -m comment --comment <comment> -j ACCEPT` in the
nat POSTROUTING chain. PostUp inserts it at position 1; PostDown deletes the
same rule. Review other port ranges separately; this guard deliberately supports
only the legacy 10000–20000 media range. It reads `/etc/wireguard/wg0.conf` and
never emits its credential-bearing content.

Run without `--apply` first. After review, install the supplied oneshot service
and one-minute timer, create `/var/lib/media-nat-guard` mode 0700, and install the
manifest mode 0600, root-owned. Keep the script root-owned/non-writable by other
users. Add `--s3-uri s3://<private-bucket>/<approved-key>` to ExecStart to publish
the bounded status through existing AWS permissions. No payload or secrets are
uploaded. Uploads have a 15-second timeout; failure leaves consumers to mark the
previous snapshot stale. A local exclusive lock prevents overlapping runs;
inspections are bounded and stop starting new endpoints after 45 seconds.

Saved startup hooks restore policy after a tunnel restart; the timer restores a
missing runtime rule after a later firewall reset. Neither is a guarantee against
all causes of audio failure. A repair status verifies rules, not speech. Re-test
an answered operator call in both directions before closing an audio incident.

Rollback: disable this timer/service, remove only their installation files, and
preserve approved rules unless intentionally reverting their separately reviewed
network change. Do not restore an entire older WireGuard configuration.
