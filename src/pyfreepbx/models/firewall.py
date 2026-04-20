"""Firewall network definition models.

Represents trusted/local/other network entries in the FreePBX
Responsive Firewall module.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FirewallZone(str, Enum):
    """FreePBX firewall zones."""

    INTERNAL = "internal"
    EXTERNAL = "external"
    OTHER = "other"
    TRUSTED = "trusted"
    LOCAL = "local"


class FirewallNetwork(BaseModel):
    """A firewall network definition from FreePBX.

    Returned from ``pbx.firewall.list_networks()`` and
    ``pbx.firewall.get_network()``.
    """

    network: str = Field(description="CIDR notation, e.g. '10.0.0.0/24' or '1.2.3.4/32'.")
    name: str = Field(default="", description="Human-readable label for this entry.")
    zone: FirewallZone = Field(default=FirewallZone.TRUSTED)
    enabled: bool = True

    model_config = {"extra": "allow"}
