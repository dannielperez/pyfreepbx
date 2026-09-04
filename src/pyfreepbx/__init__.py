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
    FreePBXTimeoutError,
    FreePBXTransportError,
    FreePBXValidationError,
    GraphQLError,
    NotFoundError,
    NotSupportedError,
    QueueMemberNotFoundError,
)
from pyfreepbx.facade import FreePBX
from pyfreepbx.models.call import ActiveChannel, HangupResult
from pyfreepbx.models.endpoint_state import (
    ENDPOINT_STATE_NOT_FOUND,
    ENDPOINT_STATE_TO_DEVICE_STATE,
    normalize_registration_state,
)
from pyfreepbx.models.events import AMIEvent
from pyfreepbx.models.health import StatusResult
from pyfreepbx.services.firewall import FirewallReplacementResult, FirewallReplacementState

__all__ = [
    "ENDPOINT_STATE_NOT_FOUND",
    "ENDPOINT_STATE_TO_DEVICE_STATE",
    "AMIAuthError",
    "AMIConnectionError",
    "AMIError",
    "AMIEvent",
    "AMIEventListener",
    "ActiveChannel",
    "AuthenticationError",
    "ConfigError",
    "FirewallReplacementResult",
    "FirewallReplacementState",
    "FreePBX",
    "FreePBXConflictError",
    "FreePBXError",
    "FreePBXTimeoutError",
    "FreePBXTransportError",
    "FreePBXValidationError",
    "GraphQLError",
    "HangupResult",
    "NotFoundError",
    "NotSupportedError",
    "QueueMemberNotFoundError",
    "StatusResult",
    "__version__",
    "normalize_registration_state",
]
