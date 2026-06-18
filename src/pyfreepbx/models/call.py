"""Call-control models.

Result types for AMI write actions that place/redirect calls. These are
*signaling* results only — they describe the action AMI accepted, not media.
"""

from __future__ import annotations

from pydantic import BaseModel


class OriginateResult(BaseModel):
    """Outcome of an AMI ``Originate`` action.

    Originate is issued asynchronously (``Async: true``) so AMI returns as soon
    as the call is *queued*, echoing back the ``ActionID`` we supplied. That
    ``action_id`` is the durable call reference — the caller persists it as the
    idempotency key and later correlates call-progress events (Ringing/Answered/
    Hangup) to this attempt. It is **not** a guarantee the call connected; the
    connect/answer outcome arrives later as AMI events.

    ``response``/``message`` are the raw AMI acknowledgement headers, retained
    for audit/troubleshooting.
    """

    action_id: str
    channel: str = ""
    extension: str = ""
    context: str = ""
    response: str = ""
    message: str = ""

    @property
    def queued(self) -> bool:
        """Whether AMI acknowledged the originate as successfully queued."""
        return self.response == "Success"
