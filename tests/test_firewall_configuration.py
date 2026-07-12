"""FreePBX 16 firewall schema contract tests."""

from unittest.mock import MagicMock

import pytest

from pyfreepbx.exceptions import NotSupportedError
from pyfreepbx.services.firewall import FirewallService


def test_configuration_returns_typed_live_payload() -> None:
    client = MagicMock()
    client.fetch_firewall_configuration.return_value = [
        {
            "status": True,
            "responsiveFirewall": True,
            "chainSip": False,
            "pjSip": True,
            "safemode": "disabled",
            "currentJiffies": "1000",
            "provision": ["external", "other"],
        }
    ]

    result = FirewallService(client).configuration()

    assert result.enabled is True
    assert result.chain_sip is False
    assert result.provision == ["external", "other"]


def test_network_inventory_fails_explicitly() -> None:
    with pytest.raises(NotSupportedError, match="does not expose"):
        FirewallService(MagicMock()).list_networks()
