"""Higher-level FreePBX API client built on the GraphQL transport.

This client provides typed helper methods for common FreePBX GraphQL
operations (extensions, queues, etc.) while keeping the raw ``GraphQLClient``
available for ad-hoc queries.

The GraphQL queries here are PROVISIONAL. FreePBX's schema varies by version
and installed modules. Run an introspection query on your instance to confirm::

    { __schema { queryType { fields { name } } } }

See: https://wiki.freepbx.org/display/FPG/GraphQL+API
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyfreepbx.clients.graphql import GraphQLClient
from pyfreepbx.logging import get_logger

if TYPE_CHECKING:
    from pyfreepbx.config import FreePBXConfig

log = get_logger("clients.freepbx")

# ---------------------------------------------------------------------------
# Provisional GraphQL queries — update after schema introspection
# ---------------------------------------------------------------------------

FETCH_ALL_EXTENSIONS = """\
query {
    fetchAllExtensions {
        status
        message
        extension {
            user {
                extension
                name
            }
        }
    }
}
"""

FETCH_EXTENSION = """\
query FetchExtension($extensionId: String!) {
    fetchExtension(extensionId: $extensionId) {
        status
        message
        extension {
            user {
                extension
                name
            }
        }
    }
}
"""

FETCH_ALL_QUEUES = """\
query {
    fetchAllQueues {
        status
        message
        queues {
            extension
            name
            strategy
        }
    }
}
"""

FETCH_ALL_RECORDINGS = """\
query {
    fetchAllRecordings {
        status
        message
        recordings { id name description fcode language playback }
    }
}
"""

FETCH_RECORDING_FILES = """\
query FetchRecordingFiles($search: String) {
    fetchRecordingFiles(search: $search) {
        status
        message
        recodingFiles
    }
}
"""

FETCH_CDR = """\
query FetchCdr($id: ID!) {
    fetchCdr(id: $id) {
        uniqueid calldate src dst duration billsec disposition linkedid recordingfile
        status message
    }
}
"""

CHECK_DISK_SPACE = """\
query {
    checkdiskspace {
        status
        message
        diskspace { id storage_path available_space used_space total_size used_percentage }
    }
}
"""

FETCH_ASTERISK_DETAILS = """\
query {
    fetchAsteriskDetails {
        status
        message
        asteriskStatus
        asteriskVersion
        amiStatus
    }
}
"""

# TODO: addExtension / updateExtension mutations — confirm names and
# input types via introspection before implementing.

# ---------------------------------------------------------------------------
# Firewall queries / mutations (provisional)
# ---------------------------------------------------------------------------

FETCH_ALL_NETWORKS = """\
query {
    fetchAllFirewallNetworks {
        status
        message
        networks {
            network
            name
            zone
            enabled
        }
    }
}
"""

FETCH_NETWORK = """\
query FetchNetwork($network: String!) {
    fetchFirewallNetwork(network: $network) {
        status
        message
        network {
            network
            name
            zone
            enabled
        }
    }
}
"""

CREATE_NETWORK = """\
mutation CreateNetwork($input: FirewallNetworkInput!) {
    addFirewallNetwork(input: $input) {
        status
        message
        network {
            network
            name
            zone
            enabled
        }
    }
}
"""

UPDATE_NETWORK = """\
mutation UpdateNetwork($network: String!, $input: FirewallNetworkInput!) {
    updateFirewallNetwork(network: $network, input: $input) {
        status
        message
        network {
            network
            name
            zone
            enabled
        }
    }
}
"""

DELETE_NETWORK = """\
mutation DeleteNetwork($network: String!) {
    removeFirewallNetwork(network: $network) {
        status
        message
    }
}
"""


class FreePBXClient:
    """Domain-aware HTTP client for FreePBX.

    Wraps ``GraphQLClient`` with methods that know which queries to send
    and how to extract the relevant payload from responses. Services
    should depend on this class rather than calling GraphQL directly.
    """

    def __init__(self, config: FreePBXConfig, *, token_provider: Any = None) -> None:
        self._config = config
        self._gql = GraphQLClient(config, token_provider=token_provider)

    @property
    def graphql(self) -> GraphQLClient:
        """Escape hatch for ad-hoc queries not covered by helper methods."""
        return self._gql

    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------

    def fetch_all_extensions(self) -> list[dict[str, Any]]:
        """Fetch all extensions from FreePBX.

        Validated against a live FreePBX instance (2026-07): the connection
        type is ``ExtensionConnection`` and its list field is the singular
        ``extension`` (the earlier provisional query used ``extensions`` and
        got a schema 400). The legacy plural key is still read as a fallback
        for other FreePBX versions.

        Returns raw user dicts from the GraphQL response. Field names
        depend on your FreePBX version — the service layer normalises
        these into typed models.
        """
        data = self._gql.query(FETCH_ALL_EXTENSIONS)
        result = data.get("fetchAllExtensions", {})
        raw = result.get("extension") or result.get("extensions") or []
        log.debug("Fetched %d raw extensions", len(raw))
        return [item.get("user", item) for item in raw]

    def fetch_extension(self, extension_id: str) -> dict[str, Any] | None:
        """Fetch a single extension by number. Returns None if not found.

        .. warning:: **Experimental** — see :meth:`fetch_all_extensions`.
        """
        import warnings

        warnings.warn(
            "fetch_extension uses a provisional GraphQL query that has "
            "not been validated against a live FreePBX instance.",
            stacklevel=2,
            category=UserWarning,
        )
        data = self._gql.query(
            FETCH_EXTENSION,
            variables={"extensionId": extension_id},
        )
        result = data.get("fetchExtension", {})
        ext = result.get("extension")
        if not ext:
            return None
        return ext.get("user", ext)

    # ------------------------------------------------------------------
    # Queues
    # ------------------------------------------------------------------

    def fetch_all_queues(self) -> list[dict[str, Any]]:
        """Fetch all queue configurations.

        .. warning:: **Experimental** — the Queue module may not expose
           GraphQL types in all FreePBX versions. See
           :meth:`fetch_all_extensions` for details.
        """
        import warnings

        warnings.warn(
            "fetch_all_queues uses a provisional GraphQL query. Queue module "
            "GraphQL support is undocumented and may not exist on your instance.",
            stacklevel=2,
            category=UserWarning,
        )
        data = self._gql.query(FETCH_ALL_QUEUES)
        result = data.get("fetchAllQueues", {})
        raw = result.get("queues", [])
        log.debug("Fetched %d raw queues", len(raw))
        return raw

    # ------------------------------------------------------------------
    # Recordings / CDR / health extras
    # ------------------------------------------------------------------

    def fetch_all_recordings(self) -> list[dict[str, Any]]:
        data = self._gql.query(FETCH_ALL_RECORDINGS)
        return data.get("fetchAllRecordings", {}).get("recordings") or []

    def fetch_recording_files(self, search: str = "") -> list[str]:
        data = self._gql.query(FETCH_RECORDING_FILES, variables={"search": search})
        return data.get("fetchRecordingFiles", {}).get("recodingFiles") or []

    def fetch_cdr(self, record_id: str) -> dict[str, Any] | None:
        data = self._gql.query(FETCH_CDR, variables={"id": record_id})
        result = data.get("fetchCdr") or {}
        return result if result.get("uniqueid") else None

    def check_disk_space(self) -> list[dict[str, Any]]:
        data = self._gql.query(CHECK_DISK_SPACE)
        return data.get("checkdiskspace", {}).get("diskspace") or []

    def fetch_asterisk_details(self) -> dict[str, Any]:
        data = self._gql.query(FETCH_ASTERISK_DETAILS)
        return data.get("fetchAsteriskDetails") or {}

    # ------------------------------------------------------------------
    # Firewall
    # ------------------------------------------------------------------

    def fetch_all_networks(self) -> list[dict[str, Any]]:
        """Fetch all firewall network definitions.

        .. warning:: **Experimental** — provisional GraphQL query.
        """
        data = self._gql.query(FETCH_ALL_NETWORKS)
        result = data.get("fetchAllFirewallNetworks", {})
        raw = result.get("networks", [])
        log.debug("Fetched %d firewall networks", len(raw))
        return raw

    def fetch_network(self, network_cidr: str) -> dict[str, Any] | None:
        """Fetch a single firewall network by CIDR."""
        data = self._gql.query(
            FETCH_NETWORK,
            variables={"network": network_cidr},
        )
        result = data.get("fetchFirewallNetwork", {})
        return result.get("network")

    def create_network(self, variables: dict[str, Any]) -> dict[str, Any]:
        """Create a firewall network definition on the PBX."""
        data = self._gql.query(
            CREATE_NETWORK,
            variables={"input": variables},
        )
        result = data.get("addFirewallNetwork", {})
        return result.get("network", {})

    def update_network(
        self,
        network_cidr: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a firewall network definition on the PBX."""
        data = self._gql.query(
            UPDATE_NETWORK,
            variables={"network": network_cidr, "input": variables},
        )
        result = data.get("updateFirewallNetwork", {})
        return result.get("network", {})

    def delete_network(self, network_cidr: str) -> bool:
        """Delete a firewall network definition from the PBX."""
        data = self._gql.query(
            DELETE_NETWORK,
            variables={"network": network_cidr},
        )
        result = data.get("removeFirewallNetwork", {})
        return result.get("status") == "true"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._gql.close()
