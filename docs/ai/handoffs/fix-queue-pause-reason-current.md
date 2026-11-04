# Queue pause ownership

Expose AMI PausedReason as nullable QueueMember.paused_reason. Required for UniqueOS guard availability to release only its own pauses and preserve manual pauses. Missing reason remains unknown, not an empty/owned pause.

Changed model, AMI mapper, two regression tests. 84 queue tests pass. Targeted lint passes. Repository-wide lint has47 pre-existing findings in tools/pbx_media/media_evidence.py; existing model/service formatting drift remains untouched. No live vendor calls from this SDK change. Additive field, no API removals. Next: review and consume pin in UniqueOS guard-availability PR. Not deployed.
