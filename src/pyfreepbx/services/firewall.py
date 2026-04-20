"""Firewall service — CRUD for FreePBX Responsive Firewall network definitions.

Read operations use ``FreePBXClient.fetch_all_networks()`` /
``fetch_network()``.  Write operations use ``create_network()`` /
``update_network()``.

.. warning:: All GraphQL queries/mutations are provisional and must be
   validated via introspection against a live FreePBX instance.
"""

from __future__ import annotations

import warnings

from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.exceptions import NotFoundError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.firewall import FirewallNetwork
from pyfreepbx.schemas.firewall_create import FirewallNetworkCreate
from pyfreepbx.schemas.firewall_update import FirewallNetworkUpdate

log = get_logger("services.firewall")


class FirewallService:
    """Developer-friendly interface for FreePBX firewall management.

    Usage via the facade::

        pbx = FreePBX.from_env()
        pbx.firewall.list_networks()
        pbx.firewall.get_network("10.0.0.0/24")
        pbx.firewall.create_network(FirewallNetworkCreate(...))
    """

    def __init__(self, client: FreePBXClient) -> None:
        self._client = client

    def list_networks(self) -> list[FirewallNetwork]:
        """Fetch all firewall network definitions.

        .. warning:: **Experimental** — uses a provisional GraphQL query.
        """
        warnings.warn(
            "FirewallService.list_networks() uses a provisional GraphQL query "
            "that has not been validated against a live FreePBX instance.",
            stacklevel=2,
            category=UserWarning,
        )
        raw = self._client.fetch_all_networks()
        networks = [FirewallNetwork.model_validate(item) for item in raw]
        log.debug("Listed %d firewall networks", len(networks))
        return networks

    def get_network(self, network_cidr: str) -> FirewallNetwork:
        """Fetch a single network definition by CIDR.

        Raises:
            NotFoundError: If the network is not found.
        """
        warnings.warn(
            "FirewallService.get_network() uses a provisional GraphQL query "
            "that has not been validated against a live FreePBX instance.",
            stacklevel=2,
            category=UserWarning,
        )
        raw = self._client.fetch_network(network_cidr)
        if raw is None:
            raise NotFoundError(f"Firewall network {network_cidr!r} not found")
        return FirewallNetwork.model_validate(raw)

    def create_network(self, payload: FirewallNetworkCreate) -> FirewallNetwork:
        """Create a new firewall network definition on the PBX.

        .. warning:: **Experimental** — uses a provisional GraphQL mutation.
        """
        warnings.warn(
            "FirewallService.create_network() uses a provisional GraphQL "
            "mutation that has not been validated against a live instance.",
            stacklevel=2,
            category=UserWarning,
        )
        raw = self._client.create_network(payload.model_dump())
        log.info("Created firewall network: %s", payload.network)
        return FirewallNetwork.model_validate(raw)

    def update_network(
        self,
        network_cidr: str,
        payload: FirewallNetworkUpdate,
    ) -> FirewallNetwork:
        """Update an existing firewall network definition.

        .. warning:: **Experimental** — uses a provisional GraphQL mutation.
        """
        warnings.warn(
            "FirewallService.update_network() uses a provisional GraphQL "
            "mutation that has not been validated against a live instance.",
            stacklevel=2,
            category=UserWarning,
        )
        variables = payload.to_variables()
        raw = self._client.update_network(network_cidr, variables)
        log.info("Updated firewall network: %s", network_cidr)
        return FirewallNetwork.model_validate(raw)

    def delete_network(self, network_cidr: str) -> bool:
        """Remove a firewall network definition.

        Returns True if the network was deleted.

        .. warning:: **Experimental** — uses a provisional GraphQL mutation.
        """
        warnings.warn(
            "FirewallService.delete_network() uses a provisional GraphQL "
            "mutation that has not been validated against a live instance.",
            stacklevel=2,
            category=UserWarning,
        )
        result = self._client.delete_network(network_cidr)
        log.info("Deleted firewall network: %s", network_cidr)
        return result
