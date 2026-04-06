"""pyfreepbx — Python library for FreePBX and Asterisk management."""

from pyfreepbx._version import __version__
from pyfreepbx.exceptions import (
    AMIAuthError,
    AMIConnectionError,
    AMIError,
    AuthenticationError,
    ConfigError,
    FreePBXError,
    GraphQLError,
    NotFoundError,
    NotSupportedError,
)
from pyfreepbx.facade import FreePBX

__all__ = [
    "AMIAuthError",
    "AMIConnectionError",
    "AMIError",
    "AuthenticationError",
    "ConfigError",
    "FreePBX",
    "FreePBXError",
    "GraphQLError",
    "NotFoundError",
    "NotSupportedError",
    "__version__",
]
