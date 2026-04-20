"""Schema for updating a firewall network definition."""

from __future__ import annotations

from pydantic import BaseModel, Field

from pyfreepbx.models.firewall import FirewallZone


class FirewallNetworkUpdate(BaseModel):
    """Partial-update payload for a firewall network entry.

    Only include fields you want to change.
    """

    name: str | None = Field(default=None, max_length=200)
    zone: FirewallZone | None = None
    enabled: bool | None = None

    def to_variables(self) -> dict[str, object]:
        """Return only the fields that were explicitly set (non-None)."""
        return {k: v for k, v in self.model_dump().items() if v is not None}
