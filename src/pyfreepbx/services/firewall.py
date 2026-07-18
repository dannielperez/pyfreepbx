"""Firewall service — CRUD for FreePBX Responsive Firewall network definitions.

Read operations use ``FreePBXClient.fetch_all_networks()`` /
``fetch_network()``.  Write operations use ``create_network()`` /
``update_network()``.

.. warning:: All GraphQL queries/mutations are provisional and must be
   validated via introspection against a live FreePBX instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from pyfreepbx.exceptions import NotFoundError, NotSupportedError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.firewall_configuration import FirewallConfiguration
from pyfreepbx.models.inventory import InventoryListResult
from pyfreepbx.schemas.firewall_create import FirewallNetworkCreate

if TYPE_CHECKING:
    from pyfreepbx.clients.freepbx import FreePBXClient
    from pyfreepbx.models.firewall import FirewallNetwork
    from pyfreepbx.schemas.firewall_update import FirewallNetworkUpdate

log = get_logger("services.firewall")


class FirewallReplacementState(str, Enum):
    """Remote consistency state after replacing a network identifier."""

    SUCCESS = "success"
    CREATE_FAILED = "create_failed"
    ROLLED_BACK = "rolled_back"
    PARTIAL = "partial"


@dataclass(frozen=True)
class FirewallReplacementResult:
    """Typed outcome for a create/delete/compensate replacement."""

    state: FirewallReplacementState
    error: str = ""
    verification_error: str = ""
    compensation_error: str = ""

    @property
    def ok(self) -> bool:
        return self.state is FirewallReplacementState.SUCCESS


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
        """Network inventory is not exposed by the FreePBX 16 GraphQL schema."""
        raise NotSupportedError("FreePBX 16 does not expose firewall network inventory")

    def list_networks_result(self) -> InventoryListResult[FirewallNetwork]:
        """Fetch network inventory with an authoritative-response signal."""
        return InventoryListResult(items=self.list_networks(), complete=True)

    def configuration(self) -> FirewallConfiguration:
        """Fetch the global firewall configuration supported by FreePBX 16."""
        raw = self._client.fetch_firewall_configuration()
        if len(raw) != 1:
            raise ValueError(f"Expected one firewall configuration, received {len(raw)}")
        return FirewallConfiguration.model_validate(raw[0])

    def get_network(self, network_cidr: str) -> FirewallNetwork:
        """Fetch a single network definition by CIDR.

        Raises:
            NotFoundError: If the network is not found.
        """
        raise NotSupportedError("FreePBX 16 does not expose single firewall network reads")

    def create_network(self, payload: FirewallNetworkCreate) -> FirewallNetwork:
        """Create a new firewall network definition on the PBX.

        .. warning:: **Experimental** — uses a provisional GraphQL mutation.
        """
        raise NotSupportedError("FreePBX 16 does not expose an add-firewall-network mutation")

    def update_network(
        self,
        network_cidr: str,
        payload: FirewallNetworkUpdate,
    ) -> FirewallNetwork:
        """Update an existing firewall network definition.

        .. warning:: **Experimental** — uses a provisional GraphQL mutation.
        """
        raise NotSupportedError("FreePBX 16 does not expose an update-firewall-network mutation")

    def delete_network(self, network_cidr: str) -> bool:
        """Remove a firewall network definition.

        Returns True if the network was deleted.

        .. warning:: **Experimental** — uses a provisional GraphQL mutation.
        """
        raise NotSupportedError("FreePBX 16 does not expose a remove-firewall-network mutation")

    def replace_network(
        self,
        old_network: str,
        new_network: str,
        *,
        name: str,
        zone: str,
    ) -> FirewallReplacementResult:
        """Replace a CIDR create-first, with readback and compensation.

        Mutation exceptions are ambiguous because a timeout can occur after the
        PBX applies a change. Readback determines whether to continue; an
        indeterminate readback is reported as partial and is never followed by a
        second speculative mutation.
        """
        new_exists, verification_error = self._network_exists(new_network)
        if new_exists is True:
            return FirewallReplacementResult(
                state=FirewallReplacementState.CREATE_FAILED,
                error=f"Replacement network {new_network} already exists",
            )
        if new_exists is None:
            return FirewallReplacementResult(
                state=FirewallReplacementState.PARTIAL,
                verification_error=verification_error,
            )

        create_error = ""
        try:
            self.create_network(FirewallNetworkCreate(network=new_network, name=name, zone=zone))
        except Exception as exc:  # vendor exceptions are intentionally normalized
            create_error = str(exc)
            new_exists, verification_error = self._network_exists(new_network)
            if new_exists is False:
                return FirewallReplacementResult(
                    state=FirewallReplacementState.CREATE_FAILED,
                    error=create_error,
                )
            if new_exists is None:
                return FirewallReplacementResult(
                    state=FirewallReplacementState.PARTIAL,
                    error=create_error,
                    verification_error=verification_error,
                )

        delete_error = self._delete_error(old_network)
        if not delete_error:
            return FirewallReplacementResult(state=FirewallReplacementState.SUCCESS)

        old_exists, verification_error = self._network_exists(old_network)
        if old_exists is False:
            return FirewallReplacementResult(state=FirewallReplacementState.SUCCESS)
        if old_exists is None:
            return FirewallReplacementResult(
                state=FirewallReplacementState.PARTIAL,
                error=delete_error,
                verification_error=verification_error,
            )

        compensation_error = self._delete_error(new_network)
        if compensation_error:
            return FirewallReplacementResult(
                state=FirewallReplacementState.PARTIAL,
                error=delete_error,
                compensation_error=compensation_error,
            )
        return FirewallReplacementResult(
            state=FirewallReplacementState.ROLLED_BACK,
            error=delete_error,
        )

    def _network_exists(self, network_cidr: str) -> tuple[bool | None, str]:
        try:
            self.get_network(network_cidr)
        except NotFoundError:
            return False, ""
        except Exception as exc:  # vendor exceptions are intentionally normalized
            return None, str(exc)
        return True, ""

    def _delete_error(self, network_cidr: str) -> str:
        try:
            deleted = self.delete_network(network_cidr)
        except Exception as exc:  # vendor exceptions are intentionally normalized
            return str(exc)
        if deleted is False:
            return f"FreePBX did not delete network {network_cidr}"
        return ""
