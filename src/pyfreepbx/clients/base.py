"""Base client interface for pyfreepbx transport layers.

Defines the contract that all protocol clients (GraphQL, AMI, future ARI)
should follow for lifecycle management. This is intentionally minimal —
the protocol-specific APIs live on each concrete client.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseClient(ABC):
    """Abstract base for pyfreepbx protocol clients.

    Ensures every client supports deterministic cleanup via ``close()``
    and context manager usage.
    """

    @abstractmethod
    def close(self) -> None:
        """Release underlying connections and resources."""

    def __enter__(self) -> BaseClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
