"""Firewall service — read firewall network definitions.

Uses the FreePBX Firewall module's REST API to list network
definitions (trusted sources, blocked networks). Write operations
are not supported in this version.

The FreePBX Firewall REST API is not officially documented.
Endpoints discovered via browser inspection of the Firewall module UI:
  GET  /rest/firewall/getnetworks   — list network definitions
  POST /rest/firewall/addnetwork    — add (not used here)
  POST /rest/firewall/deletenetwork — remove (not used here)
"""

from __future__ import annotations

from pyfreepbx.clients.rest import RestClient
from pyfreepbx.logging import get_logger
from pyfreepbx.models.firewall import FirewallNetwork

log = get_logger("services.firewall")


class FirewallService:
    """Read-only access to FreePBX Firewall network definitions.

    Requires the FreePBX Firewall module to be installed and the
    REST API to be accessible.
    """

    def __init__(self, rest: RestClient) -> None:
        self._rest = rest

    def list_networks(self) -> list[FirewallNetwork]:
        """Fetch all network definitions from the Firewall module.

        Returns:
            List of :class:`FirewallNetwork`. Empty list on error.
        """
        try:
            data = self._rest.get("/firewall/getnetworks")
        except Exception as exc:
            log.error("Failed to fetch firewall networks: %s", exc)
            return []

        if isinstance(data, dict):
            # API may return {"networks": [...]} or a flat list
            items = data.get("networks", data.get("data", []))
            if isinstance(items, dict):
                # dict keyed by name/id
                items = list(items.values())
        elif isinstance(data, list):
            items = data
        else:
            log.warning("Unexpected firewall response type: %s", type(data).__name__)
            return []

        networks: list[FirewallNetwork] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                networks.append(FirewallNetwork(**item))
            except Exception as exc:
                log.warning("Skipping unparseable firewall entry: %s", exc)

        log.debug("Fetched %d firewall networks", len(networks))
        return networks
