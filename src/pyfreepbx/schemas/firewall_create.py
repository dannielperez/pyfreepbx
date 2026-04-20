"""Schema for creating a firewall network definition."""

from __future__ import annotations

from pydantic import BaseModel, Field

from pyfreepbx.models.firewall import FirewallZone


class FirewallNetworkCreate(BaseModel):
    """Input payload for adding a network to the FreePBX firewall."""

    network: str = Field(
        min_length=1,
        max_length=50,
        description="CIDR notation, e.g. '10.0.0.0/24' or '1.2.3.4/32'.",
    )
    name: str = Field(
        default="",
        max_length=200,
        description="Human-readable label for the entry.",
    )
    zone: FirewallZone = Field(
        default=FirewallZone.TRUSTED,
        description="Firewall zone to place this network in.",
    )
