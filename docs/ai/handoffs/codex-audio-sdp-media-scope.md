# Audio SDP scope and approved media NAT recovery

Owner requested Palacios no-audio diagnosis, fleet detection, durable remediation,
and temporary audio-only operation. This SDK change scopes SDP direction/codec
parsing to audio; send-only video no longer hides missing audio RTP. Audio hold,
ambiguous streams, incomplete captures and bridge safety gates remain excluded.

The separate Python 3 hub guard restores only exact saved, manifest-approved
missing UDP media exemptions after route, peer, freshness and approval checks.
It reports uncertain or conflicting policy without modifying it. Service/timer
examples and deployment/rollback instructions accompany the tool. No production
deployment is included in this branch.

Validation: 38 collector, NAT guard and queue stability tests passed; new Python 3
guard/tests pass Ruff. Collector retains Python 2 compatibility for legacy PBX.
Existing notifyAll deprecation warnings remain. Mocked repair is idempotent and
preserves unrelated rules. A real controlled rule-loss recovery and answered
operator audio acceptance are required during owner-approved activation.

Risk: only fixed UDP ports 10000–20000 and wg0 are supported. Packet/rule health
cannot prove human audibility. Do not automatically enroll unverified endpoints.
The companion UniqueOS branch consumes optional source-scoped guard snapshots.
