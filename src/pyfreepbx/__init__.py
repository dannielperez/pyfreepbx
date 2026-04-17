"""pyfreepbx — Python library for FreePBX and Asterisk management."""

from pyfreepbx._version import __version__
from pyfreepbx.exceptions import (
    AMIAuthError,
    AMIConnectionError,
    AMIError,
    AuthenticationError,
    ConfigError,
    FreePBXConflictError,
    FreePBXError,
    FreePBXTransportError,
    FreePBXValidationError,
    GraphQLError,
    NotFoundError,
    NotSupportedError,
)
from pyfreepbx.facade import FreePBX
from pyfreepbx.models.health import StatusResult

__all__ = [
    "AMIAuthError",
    "AMIConnectionError",
    "AMIError",
    "AuthenticationError",
    "ConfigError",
    "FreePBX",
    "FreePBXConflictError",
    "FreePBXError",
    "FreePBXTransportError",
    "FreePBXValidationError",
    "GraphQLError",
    "NotFoundError",
    "NotSupportedError",
    "StatusResult",
    "__version__",
]
