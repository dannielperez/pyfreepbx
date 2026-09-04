"""Exception hierarchy for pyfreepbx."""

from __future__ import annotations


class FreePBXError(Exception):
    """Base exception for all pyfreepbx errors."""


class ConfigError(FreePBXError):
    """Missing or invalid configuration."""


class AuthenticationError(FreePBXError):
    """Authentication failed (API token or AMI credentials)."""


class GraphQLError(FreePBXError):
    """Error returned by the FreePBX GraphQL API."""

    def __init__(self, message: str, errors: list[dict[str, object]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class AMIError(FreePBXError):
    """Error from the Asterisk Manager Interface."""


class AMIConnectionError(AMIError):
    """Failed to connect to AMI."""


class AMITimeout(AMIError):  # noqa: N818 — mirrors builtin TimeoutError; cross-repo contract name
    """Idle read timeout: no frame within the read window, socket still alive.

    A non-failure transport signal — the event reader converts it to the
    ``AMI_IDLE`` sentinel; it is never a disconnect. Subclasses :class:`AMIError`
    so a legacy broad ``except AMIError`` cannot crash on it, but it is always
    caught more-specifically first.
    """


class AMIAuthError(AMIError, AuthenticationError):
    """AMI authentication failed."""


class NotFoundError(FreePBXError):
    """Requested resource was not found."""


class QueueMemberNotFoundError(AMIError):
    """A runtime queue-member operation targeted a member/queue that is absent.

    Raised so consumers can treat "already removed" as an idempotent success
    instead of substring-matching Asterisk's English error text.
    """


class NotSupportedError(FreePBXError):
    """Operation is not supported by the current backend.

    Raised when a service method requires a GraphQL mutation or AMI action
    that hasn't been confirmed to exist. Prefer this over silently faking
    behavior — it tells library consumers exactly what to expect.
    """


class FreePBXValidationError(FreePBXError):
    """Server rejected the payload due to validation errors (HTTP 422)."""

    def __init__(
        self,
        message: str,
        details: dict[str, object] | list[object] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = details or {}


class FreePBXConflictError(FreePBXError):
    """Resource conflict (HTTP 409) — e.g. duplicate extension number."""


class FreePBXTransportError(FreePBXError):
    """Network-level failure (timeout, connection refused, DNS error)."""


class FreePBXTimeoutError(FreePBXTransportError):
    """A bounded FreePBX request timed out with an indeterminate outcome."""
