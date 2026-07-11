"""pyfreepbx — Python library for FreePBX and Asterisk management."""

from pyfreepbx._version import __version__
from pyfreepbx.clients.ami_listener import AMIEventListener
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
from pyfreepbx.models.events import AMIEvent
from pyfreepbx.models.health import StatusResult
from pyfreepbx.services.firewall import FirewallReplacementResult, FirewallReplacementState

__all__ = [
    "AMIAuthError",
    "AMIConnectionError",
    "AMIError",
    "AMIEvent",
    "AMIEventListener",
    "AuthenticationError",
    "ConfigError",
    "FirewallReplacementResult",
    "FirewallReplacementState",
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
