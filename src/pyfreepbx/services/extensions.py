"""Extension service — CRUD operations on FreePBX extensions.

Read operations (list, get) use the FreePBXClient to query the GraphQL API.
Write operations (create, update, update_secret) use the REST API.

.. warning:: Read methods are **experimental** — the underlying GraphQL
   queries have not been validated against a live FreePBX instance.
"""

from __future__ import annotations

import warnings

from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.clients.rest import RestClient
from pyfreepbx.exceptions import NotFoundError
from pyfreepbx.logging import get_logger
from pyfreepbx.models.extension import Extension
from pyfreepbx.schemas.extension_create import ExtensionCreate
from pyfreepbx.schemas.extension_update import ExtensionUpdate

log = get_logger("services.extensions")


class ExtensionService:
    """Developer-friendly interface for extension management.

    Usage via the facade::

        pbx = FreePBX.from_env()
        pbx.extensions.list()
        pbx.extensions.get("1001")
        pbx.extensions.create(ExtensionCreate(extension="1002", name="Front Desk"))
    """

    def __init__(self, client: FreePBXClient, rest: RestClient | None = None) -> None:
        self._client = client
        self._rest = rest

    def list(self) -> list[Extension]:
        """Fetch all extensions from FreePBX.

        .. warning:: **Experimental** — uses a provisional GraphQL query.
           The query name, response nesting, and field names have not been
           validated against a live FreePBX instance and will likely need
           adjustment. Run a GraphQL introspection query to confirm.
        """
        warnings.warn(
            "ExtensionService.list() uses a provisional GraphQL query that "
            "has not been validated against a live FreePBX instance.",
            stacklevel=2,
            category=UserWarning,
        )
        raw = self._client.fetch_all_extensions()
        extensions = [Extension.model_validate(item) for item in raw]
        log.debug("Listed %d extensions", len(extensions))
        return extensions

    def get(self, extension_id: str) -> Extension:
        """Fetch a single extension by number.

        .. warning:: **Experimental** — see :meth:`list` for GraphQL caveats.

        Raises:
            NotFoundError: If the extension does not exist.
        """
        warnings.warn(
            "ExtensionService.get() uses a provisional GraphQL query that "
            "has not been validated against a live FreePBX instance.",
            stacklevel=2,
            category=UserWarning,
        )
        raw = self._client.fetch_extension(extension_id)
        if raw is None:
            raise NotFoundError(f"Extension {extension_id!r} not found")
        return Extension.model_validate(raw)

    def create(self, payload: ExtensionCreate) -> Extension:
        """Create a new extension via the FreePBX REST API.

        Raises:
            FreePBXValidationError: If the server rejects the payload.
            FreePBXConflictError: If the extension number already exists.
            FreePBXTransportError: On network failure.
        """
        if self._rest is None:
            raise RuntimeError("REST client is required for write operations")

        body = payload.model_dump(exclude_none=True)
        log.info("Creating extension %s via REST", payload.extension)
        result = self._rest.post("/extensions", json=body)

        # REST response may vary; normalise into our Extension model
        if isinstance(result, dict):
            return Extension.model_validate(result)
        # Fallback: return a model from the input payload
        return Extension(
            extension=payload.extension,
            name=payload.name,
            tech=payload.tech,
            voicemail_enabled=payload.voicemail_enabled,
            outbound_cid=payload.outbound_cid,
        )

    def update(self, extension_id: str, payload: ExtensionUpdate) -> Extension:
        """Update an existing extension via the FreePBX REST API.

        Only fields that are explicitly set in ``payload`` will be sent.

        Raises:
            NotFoundError: If the extension does not exist.
            FreePBXValidationError: If the server rejects the payload.
            FreePBXTransportError: On network failure.
        """
        if self._rest is None:
            raise RuntimeError("REST client is required for write operations")

        body = payload.to_variables()
        log.info("Updating extension %s via REST: %s", extension_id, list(body.keys()))
        result = self._rest.put(f"/extensions/{extension_id}", json=body)

        if isinstance(result, dict):
            return Extension.model_validate(result)
        return Extension(extension=extension_id, name=body.get("name", ""))

    def update_secret(self, extension_id: str, new_secret: str) -> None:
        """Update only the SIP secret for an extension.

        Raises:
            NotFoundError: If the extension does not exist.
            FreePBXTransportError: On network failure.
        """
        if self._rest is None:
            raise RuntimeError("REST client is required for write operations")

        log.info("Rotating secret for extension %s via REST", extension_id)
        self._rest.put(f"/extensions/{extension_id}", json={"secret": new_secret})
