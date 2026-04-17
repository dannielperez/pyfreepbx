"""Firewall models.

Represents network definitions from the FreePBX Firewall module's
REST API (``/rest/firewall/...``). These are the trusted/blocked
network entries technicians manage through the Firewall module.
"""

from __future__ import annotations

from pydantic import BaseModel


class FirewallNetwork(BaseModel):
    """A network definition from the FreePBX Firewall module.

    Provisioned via the Firewall module's REST API.
    Field names follow the FreePBX Firewall REST interface.
    """

    name: str
    network: str                # CIDR notation, e.g. "10.0.0.0/24"
    zone: str = "trusted"       # internal, external, trusted, local, other
    enabled: bool = True

    model_config = {"extra": "allow"}
