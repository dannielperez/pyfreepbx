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

    def __init__(self, message: str, errors: list[dict] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class AMIError(FreePBXError):
    """Error from the Asterisk Manager Interface."""


class AMIConnectionError(AMIError):
    """Failed to connect to AMI."""


class AMIAuthError(AMIError, AuthenticationError):
    """AMI authentication failed."""


class NotFoundError(FreePBXError):
    """Requested resource was not found."""


class NotSupportedError(FreePBXError):
    """Operation is not supported by the current backend.

    Raised when a service method requires a GraphQL mutation or AMI action
    that hasn't been confirmed to exist. Prefer this over silently faking
    behavior — it tells library consumers exactly what to expect.
    """
