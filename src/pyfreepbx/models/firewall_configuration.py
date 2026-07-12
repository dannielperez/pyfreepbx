"""Typed FreePBX firewall configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FirewallConfiguration(BaseModel):
    """Global firewall state returned by ``fetchFirewallConfiguration``."""

    enabled: bool = Field(alias="status")
    responsive_firewall: bool = Field(alias="responsiveFirewall")
    chain_sip: bool = Field(alias="chainSip")
    pjsip: bool = Field(alias="pjSip")
    safe_mode: str = Field(alias="safemode")
    current_jiffies: str = Field(alias="currentJiffies")
    provision: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "extra": "allow"}
