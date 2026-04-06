"""Structured logging for pyfreepbx.

Provides a consistent logger factory so all library internals
use the same format and level. Library consumers can reconfigure
by adjusting the "pyfreepbx" logger in standard logging.
"""

from __future__ import annotations

import logging
import sys

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_configured = False


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the ``pyfreepbx`` hierarchy.

    Args:
        name: Subcomponent name (e.g. ``"clients.graphql"``).
              Will be prefixed with ``pyfreepbx.``.
    """
    _ensure_configured()
    return logging.getLogger(f"pyfreepbx.{name}")


def _ensure_configured() -> None:
    """Attach a default handler to the root ``pyfreepbx`` logger.

    Only runs once. If the consumer has already configured the
    ``pyfreepbx`` logger (or root logger), this is a no-op because
    NullHandler is only added when no handlers exist.
    """
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger("pyfreepbx")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)
        root.setLevel(logging.WARNING)
