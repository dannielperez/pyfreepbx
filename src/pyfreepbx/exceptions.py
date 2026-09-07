"""Exception hierarchy for pyfreepbx."""

from __future__ import annotations

import hashlib
import re
from typing import Any


class FreePBXError(Exception):
    """Base exception for all pyfreepbx errors."""


class ConfigError(FreePBXError):
    """Missing or invalid configuration."""


class AuthenticationError(FreePBXError):
    """Authentication failed (API token or AMI credentials)."""


class GraphQLError(FreePBXError):
    """Error returned by the FreePBX GraphQL API."""

    def __init__(
        self,
        message: str,
        errors: list[dict[str, object]] | None = None,
        *,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = errors or []
        self.http_status = http_status


class FreePBXOperationError(FreePBXError):
    """A failed SDK operation with safe, structured reconciliation state."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        phase: str,
        remote_state: str = "unknown",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.phase = phase
        self.remote_state = remote_state
        self.retryable = retryable


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


_SAFE_GRAPHQL_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_SAFE_GRAPHQL_PATH = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def safe_error_diagnostics(
    exc: BaseException,
    *,
    phase: str = "unknown",
    remote_state: str = "unknown",
) -> dict[str, Any]:
    """Return bounded diagnostics without exception messages or request payloads.

    GraphQL messages can echo mutation variables, including SIP secrets.  Only
    stable types, allowlisted codes/paths, HTTP status, and a one-way message
    fingerprint cross this boundary.
    """
    operation = "freepbx"
    retryable = isinstance(exc, FreePBXTransportError)
    if isinstance(exc, FreePBXOperationError):
        operation = exc.operation
        phase = exc.phase
        remote_state = exc.remote_state
        retryable = exc.retryable

    cause: BaseException = exc
    while cause.__cause__ is not None and cause.__cause__ is not cause:
        cause = cause.__cause__

    if isinstance(cause, GraphQLError):
        category = "graphql"
    elif isinstance(cause, AuthenticationError):
        category = "authentication"
    elif isinstance(cause, FreePBXTimeoutError):
        category = "timeout"
    elif isinstance(cause, FreePBXTransportError):
        category = "transport"
    elif isinstance(cause, FreePBXConflictError):
        category = "conflict"
    elif isinstance(cause, NotFoundError):
        category = "not_found"
    elif isinstance(cause, FreePBXValidationError):
        category = "validation"
    else:
        category = "unexpected"

    diagnostics: dict[str, Any] = {
        "provider": "freepbx",
        "operation": operation,
        "phase": phase,
        "category": category,
        "exception_type": type(cause).__name__,
        "remote_state": remote_state,
        "retryable": retryable,
    }
    if isinstance(cause, GraphQLError):
        messages: list[str] = []
        codes: list[str] = []
        paths: list[list[str | int]] = []
        for error in cause.errors[:5]:
            message = error.get("message")
            if isinstance(message, str):
                messages.append(message)
            extensions = error.get("extensions")
            code = extensions.get("code") if isinstance(extensions, dict) else None
            if isinstance(code, str) and _SAFE_GRAPHQL_CODE.fullmatch(code):
                codes.append(code)
            path = error.get("path")
            if isinstance(path, list):
                safe_path = [
                    part
                    for part in path[:8]
                    if isinstance(part, int)
                    or (isinstance(part, str) and _SAFE_GRAPHQL_PATH.fullmatch(part))
                ]
                if safe_path:
                    paths.append(safe_path)
        if not messages:
            messages.append(str(cause))
        diagnostics["graphql"] = {
            "http_status": cause.http_status,
            "codes": sorted(set(codes)),
            "paths": paths,
            "message_fingerprint": hashlib.sha256(
                "\n".join(messages).encode("utf-8", errors="replace")
            ).hexdigest()[:16],
        }
    return diagnostics
