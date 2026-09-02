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
from pyfreepbx.models.inventory import InventoryListResult

if TYPE_CHECKING:
    from pyfreepbx.config import FreePBXConfig

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
                extension: extensionId
                name
            }
        }
    }
}
"""

FETCH_EXTENSION_SECRET = """\
query FetchExtensionSecret($extensionId: ID!) {
    fetchExtension(extensionId: $extensionId) {
        status
        message
        user {
            extension
            extPassword
        }
    }
}
"""

ADD_EXTENSION = """\
mutation AddExtension($input: addExtensionInput!) {
    addExtension(input: $input) {
        status
        message
        clientMutationId
    }
}
"""

UPDATE_EXTENSION = """\
mutation UpdateExtension($input: updateExtensionInput!) {
    updateExtension(input: $input) {
        status
        message
        clientMutationId
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

# ---------------------------------------------------------------------------
# Firewall queries (validated against FreePBX 16 / firewall 16.x)
# ---------------------------------------------------------------------------

FETCH_FIREWALL_CONFIGURATION = """\
query {
    fetchFirewallConfiguration {
        status
        message
        configurations {
            status
            responsiveFirewall
            chainSip
            pjSip
            safemode
            currentJiffies
            provision
        }
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
        return self.fetch_all_extensions_result().items

    def fetch_all_extensions_result(self) -> InventoryListResult[dict[str, Any]]:
        """Fetch extensions and report whether the response is authoritative."""
        data = self._gql.query(FETCH_ALL_EXTENSIONS)
        result = data.get("fetchAllExtensions")
        if not isinstance(result, dict):
            return InventoryListResult(items=[], complete=False)
        collection_key = next(
            (key for key in ("extension", "extensions") if key in result),
            None,
        )
        raw_value = result.get(collection_key) if collection_key else None
        raw = raw_value if isinstance(raw_value, list) else []
        items = [item.get("user", item) for item in raw if isinstance(item, dict)]
        complete = (
            result.get("status") is True
            and collection_key is not None
            and isinstance(raw_value, list)
            and len(items) == len(raw)
        )
        log.debug("Fetched %d raw extensions (complete=%s)", len(items), complete)
        return InventoryListResult(items=items, complete=complete)

    def fetch_extension(self, extension_id: str) -> dict[str, Any] | None:
        """Fetch a single extension by number. Returns None if not found."""
        data = self._gql.query(
            FETCH_EXTENSION,
            variables={"extensionId": extension_id},
        )
        result = data.get("fetchExtension", {})
        ext = result.get("extension")
        if not ext:
            return None
        return ext.get("user", ext)

    def fetch_extension_secret(self, extension_id: str) -> str | None:
        """Fetch the configured SIP secret for one fixed extension.

        FreePBX Core 16/17 exposes ``coreuser.extPassword`` and resolves it via
        ``Core->getSipSecret()``. Keep this separate from normal inventory reads
        so secrets never enter bulk extension payloads or debug logging.
        """
        data = self._gql.query(
            FETCH_EXTENSION_SECRET,
            variables={"extensionId": extension_id},
        )
        result = data.get("fetchExtension")
        if not isinstance(result, dict) or result.get("status") is not True:
            return None
        user = result.get("user")
        if not isinstance(user, dict):
            return None
        secret = user.get("extPassword")
        return secret if isinstance(secret, str) and secret else None

    def add_extension(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Create an extension with the live-confirmed FreePBX mutation."""
        data = self._gql.mutation(ADD_EXTENSION, variables={"input": input_data})
        result = data.get("addExtension")
        if not isinstance(result, dict):
            raise ValueError("FreePBX omitted addExtension from its response")
        return result

    def update_extension(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Update an extension with the live-confirmed FreePBX mutation."""
        data = self._gql.mutation(UPDATE_EXTENSION, variables={"input": input_data})
        result = data.get("updateExtension")
        if not isinstance(result, dict):
            raise ValueError("FreePBX omitted updateExtension from its response")
        return result

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

    def fetch_firewall_configuration(self) -> list[dict[str, Any]]:
        """Fetch the supported FreePBX 16 firewall configuration payload."""
        data = self._gql.query(FETCH_FIREWALL_CONFIGURATION)
        result = data.get("fetchFirewallConfiguration", {})
        raw = result.get("configurations")
        if raw is None:
            raise ValueError("FreePBX omitted firewall configurations from its response")
        log.debug("Fetched %d firewall configurations", len(raw))
        return raw

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._gql.close()
