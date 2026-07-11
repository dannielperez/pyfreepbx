"""Firewall service — CRUD for FreePBX Responsive Firewall network definitions.

Read operations use ``FreePBXClient.fetch_all_networks()`` /
``fetch_network()``.  Write operations use ``create_network()`` /
``update_network()``.

.. warning:: All GraphQL queries/mutations are provisional and must be
   validated via introspection against a live FreePBX instance.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from enum import Enum

from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.exceptions import NotFoundError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.firewall import FirewallNetwork
from pyfreepbx.schemas.firewall_create import FirewallNetworkCreate
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
