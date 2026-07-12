"""Typed inventory list results with an explicit completeness signal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class InventoryListResult(Generic[T]):
    """Items returned by a vendor list operation.

    ``complete`` is true only when FreePBX explicitly reports a successful
    response and includes the expected collection field. Consumers that
    reconcile persisted inventory must not remove or stale unseen rows when it
    is false.
    """

    items: list[T]
    complete: bool
