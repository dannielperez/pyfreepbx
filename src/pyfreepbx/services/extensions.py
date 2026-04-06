"""Extension service — CRUD operations on FreePBX extensions.

Read operations (list, get) use the FreePBXClient to query the GraphQL API.
Write operations (create, update, enable, disable) are wired up structurally
but raise ``NotSupportedError`` until the GraphQL mutation names and input
types are confirmed via introspection on a live instance.

.. warning:: Read methods are **experimental** — the underlying GraphQL
   queries have not been validated against a live FreePBX instance.
"""

from __future__ import annotations

import warnings

from pyfreepbx.clients.freepbx import FreePBXClient
from pyfreepbx.exceptions import NotFoundError, NotSupportedError
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
    """

    def __init__(self, client: FreePBXClient) -> None:
        self._client = client

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
        """Create a new extension.

        Raises:
            NotSupportedError: The GraphQL mutation for creating extensions
                has not been confirmed yet. Introspect your FreePBX instance
                and implement ``FreePBXClient.create_extension()`` to enable.
        """
        # TODO: Implement once the addExtension (or equivalent) mutation
        # input type is confirmed via GraphQL introspection.
        raise NotSupportedError(
            "Extension creation is not yet implemented. "
            "The GraphQL mutation name and input schema need to be confirmed "
            "via introspection on a live FreePBX instance. "
            "See: https://wiki.freepbx.org/display/FPG/GraphQL+API"
        )

    def update(self, extension_id: str, payload: ExtensionUpdate) -> Extension:
        """Update an existing extension.

        Raises:
            NotSupportedError: The GraphQL mutation for updating extensions
                has not been confirmed yet.
        """
        # TODO: Implement once the updateExtension (or equivalent) mutation
        # is confirmed. Use payload.to_variables() for partial updates.
        raise NotSupportedError(
            "Extension update is not yet implemented. "
            "The GraphQL mutation name and input schema need to be confirmed "
            "via introspection on a live FreePBX instance."
        )

    def enable(self, extension_id: str) -> Extension:
        """Enable a disabled extension.

        Raises:
            NotSupportedError: If the backend does not support toggling
                extension state via the API.
        """
        # TODO: May map to an updateExtension mutation with enabled=true,
        # or a dedicated enableExtension mutation. Confirm via introspection.
        raise NotSupportedError(
            "Extension enable is not yet implemented. "
            "Confirm whether FreePBX supports this via the GraphQL API."
        )

    def disable(self, extension_id: str) -> Extension:
        """Disable an extension.

        Raises:
            NotSupportedError: If the backend does not support toggling
                extension state via the API.
        """
        raise NotSupportedError(
            "Extension disable is not yet implemented. "
            "Confirm whether FreePBX supports this via the GraphQL API."
        )
