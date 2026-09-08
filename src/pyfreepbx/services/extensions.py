"""Extension service — CRUD operations on FreePBX extensions.

Read and write operations use the FreePBX GraphQL API.

The extension queries and mutations are validated against a live FreePBX
instance (2026-07).
"""

from __future__ import annotations

import hmac
from secrets import token_hex
from typing import TYPE_CHECKING

from pyfreepbx.exceptions import (
    FreePBXConflictError,
    FreePBXOperationError,
    FreePBXTimeoutError,
    FreePBXTransportError,
    FreePBXValidationError,
    GraphQLError,
    NotFoundError,
)
from pyfreepbx.logging import get_logger
from pyfreepbx.models.extension import Extension, ExtensionProvisioningResult
from pyfreepbx.models.inventory import InventoryListResult

if TYPE_CHECKING:
    from pyfreepbx.clients.freepbx import FreePBXClient
    from pyfreepbx.clients.rest import RestClient
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

        Validated against a live FreePBX instance (2026-07) — see
        ``FreePBXClient.fetch_all_extensions`` for the schema note.
        """
        raw = self._client.fetch_all_extensions()
        extensions = [Extension.model_validate(item) for item in raw]
        log.debug("Listed %d extensions", len(extensions))
        return extensions

    def list_result(self) -> InventoryListResult[Extension]:
        """Fetch extensions with an authoritative-response signal."""
        raw_result = self._client.fetch_all_extensions_result()
        extensions = [Extension.model_validate(item) for item in raw_result.items]
        log.debug("Listed %d extensions", len(extensions))
        return InventoryListResult(items=extensions, complete=raw_result.complete)

    def get(self, extension_id: str) -> Extension:
        """Fetch a single extension by number.

        Raises:
            NotFoundError: If the extension does not exist.
        """
        raw = self._client.fetch_extension(extension_id)
        if raw is None:
            raise NotFoundError(f"Extension {extension_id!r} not found")
        return Extension.model_validate(raw)

    def get_secret(self, extension_id: str) -> str | None:
        """Fetch the configured SIP secret for one fixed extension.

        The plaintext is returned only to the caller and is never logged.
        ``None`` means FreePBX did not expose a secret for this extension.
        """
        return self._client.fetch_extension_secret(extension_id)

    def create(self, payload: ExtensionCreate) -> Extension:
        """Create a new extension via the FreePBX GraphQL API.

        Raises:
            FreePBXValidationError: If the server rejects the payload.
            FreePBXConflictError: If the extension number already exists.
            FreePBXTransportError: On network failure.
        """
        self._ensure_extension_absent(payload.extension)
        body = _to_graphql_input(payload.model_dump(mode="json", exclude_none=True))
        secret = body.pop("extPassword", None)
        provisional_name = ""
        if isinstance(secret, str) and secret:
            provisional_name = _provisional_create_name(payload.name)
            body["name"] = provisional_name
        if payload.tech.value in {"pjsip", "sip"}:
            # FreePBX 15-17 declare channelName optional, but their Quick Create
            # resolver consumes the normalized channel identity. Supplying it is
            # required by deployed Core variants and mirrors updateExtension.
            body["channelName"] = f"{payload.tech.value.upper()}/{payload.extension}"
        log.info("Creating extension %s via GraphQL", payload.extension)
        try:
            result = self._client.add_extension(body)
        except (FreePBXTransportError, GraphQLError) as exc:
            if not provisional_name:
                raise
            self._matching_extension_after_indeterminate_create(
                payload.extension,
                provisional_name,
                exc,
            )
        else:
            try:
                self._raise_for_failed_mutation("addExtension", result)
            except FreePBXValidationError as exc:
                if not provisional_name:
                    raise
                self._matching_extension_after_indeterminate_create(
                    payload.extension,
                    provisional_name,
                    exc,
                )
        if isinstance(secret, str) and secret:
            # FreePBX addExtensionInput does not expose extPassword, while the
            # update mutation does. Set the generated SIP secret immediately
            # after creation through that supported field.
            self.update_secret(payload.extension, secret, name=payload.name)
        try:
            extension = self.get(payload.extension)
        except FreePBXTimeoutError:
            # The mutation is already confirmed. One bounded retry of this
            # read-only verification cannot duplicate or alter PBX state.
            extension = self.get(payload.extension)
        if extension.name != payload.name:
            raise FreePBXValidationError(
                f"Extension {payload.extension!r} was created but its final name was not verified"
            )
        return extension

    def create_with_generated_secret(
        self,
        payload: ExtensionCreate,
    ) -> ExtensionProvisioningResult:
        """Create once and return FreePBX's generated SIP secret.

        FreePBX 16's ``addExtensionInput`` does not expose ``extPassword``.
        Its ``updateExtension`` resolver deletes and recreates the endpoint, so
        using an immediate update merely to set a caller-generated secret can
        lose the new extension.  The Core quick-create path already generates
        a secret; read that value back instead and never replay a write.
        """
        self._ensure_extension_absent(payload.extension)
        safe_payload = payload.model_copy(update={"secret": None})
        body = _to_graphql_input(safe_payload.model_dump(mode="json", exclude_none=True))
        if safe_payload.tech.value in {"pjsip", "sip"}:
            body["channelName"] = f"{safe_payload.tech.value.upper()}/{safe_payload.extension}"

        log.info("Creating extension %s via GraphQL", safe_payload.extension)
        try:
            result = self._client.add_extension(body)
            self._raise_for_failed_mutation("addExtension", result)
        except (FreePBXTransportError, GraphQLError, FreePBXValidationError) as exc:
            remote_state = "unknown"
            try:
                observed = self.get(safe_payload.extension)
            except (FreePBXTransportError, GraphQLError, NotFoundError):
                pass
            else:
                if (
                    observed.extension == safe_payload.extension
                    and observed.name == safe_payload.name
                ):
                    remote_state = "present"
            # Number + display name cannot prove mutation ownership under a
            # concurrent create. Never consume a secret after an ambiguous
            # response, even when an exact read finds an endpoint.
            raise FreePBXOperationError(
                "FreePBX did not unambiguously confirm extension creation.",
                operation="addExtension",
                phase="create_extension",
                remote_state=remote_state,
                retryable=False,
            ) from exc

        try:
            extension = self.get(safe_payload.extension)
        except (FreePBXTransportError, GraphQLError, NotFoundError) as exc:
            raise FreePBXOperationError(
                "FreePBX created the extension but read-back failed.",
                operation="fetchExtension",
                phase="verify_extension",
                remote_state="unknown",
                retryable=isinstance(exc, FreePBXTransportError),
            ) from exc
        if extension.name != safe_payload.name:
            raise FreePBXOperationError(
                "FreePBX created the extension but its identity was not verified.",
                operation="fetchExtension",
                phase="verify_extension",
                remote_state="present",
            )

        try:
            secret = self.get_secret(safe_payload.extension)
        except (FreePBXTransportError, GraphQLError) as exc:
            raise FreePBXOperationError(
                "FreePBX created the extension but its generated secret was not readable.",
                operation="fetchExtension",
                phase="read_generated_secret",
                remote_state="present",
                retryable=isinstance(exc, FreePBXTransportError),
            ) from exc
        if not secret:
            raise FreePBXOperationError(
                "FreePBX created the extension but did not expose its generated secret.",
                operation="fetchExtension",
                phase="read_generated_secret",
                remote_state="present",
            )
        return ExtensionProvisioningResult(
            extension=extension,
            secret=secret,
            diagnostics=(
                {
                    "provider": "freepbx",
                    "operation": "addExtension",
                    "phase": "create_extension",
                    "category": "success",
                    "remote_state": "present",
                    "retryable": False,
                },
                {
                    "provider": "freepbx",
                    "operation": "fetchExtension",
                    "phase": "read_generated_secret",
                    "category": "success",
                    "remote_state": "present",
                    "retryable": False,
                },
            ),
        )

    def update(self, extension_id: str, payload: ExtensionUpdate) -> Extension:
        """Update an existing extension via the FreePBX GraphQL API.

        Only fields that are explicitly set in ``payload`` will be sent.

        Raises:
            NotFoundError: If the extension does not exist.
            FreePBXValidationError: If the server rejects the payload.
            FreePBXTransportError: On network failure.
        """
        body = _to_graphql_input(payload.model_dump(mode="json", exclude_none=True))
        body["extensionId"] = extension_id
        log.info("Updating extension %s via GraphQL: %s", extension_id, list(body.keys()))
        result = self._client.update_extension(body)
        self._raise_for_failed_mutation("updateExtension", result)
        return self.get(extension_id)

    def update_secret(self, extension_id: str, new_secret: str, *, name: str = "") -> None:
        """Update only the SIP secret for an extension.

        Raises:
            NotFoundError: If the extension does not exist.
            FreePBXTransportError: On network failure.
        """
        log.info("Rotating secret for extension %s via GraphQL", extension_id)
        try:
            result = self._client.update_extension(
                {
                    "extensionId": extension_id,
                    "tech": "pjsip",
                    "channelName": f"PJSIP/{extension_id}",
                    "name": name or extension_id,
                    "extPassword": new_secret,
                }
            )
        except (FreePBXTransportError, GraphQLError) as exc:
            try:
                observed_secret = self.get_secret(extension_id)
            except (FreePBXTransportError, GraphQLError) as readback_exc:
                raise exc from readback_exc
            if observed_secret and hmac.compare_digest(observed_secret, new_secret):
                log.info("Verified extension %s secret after mutation timeout", extension_id)
                return
            raise
        if result.get("status") is True:
            return
        observed_secret = self.get_secret(extension_id)
        if observed_secret and hmac.compare_digest(observed_secret, new_secret):
            log.info("Verified extension %s secret after null mutation status", extension_id)
            return
        self._raise_for_failed_mutation("updateExtension", result)

    def _ensure_extension_absent(self, extension_id: str) -> None:
        """Refuse to mutate when the target number already exists."""
        try:
            self.get(extension_id)
        except NotFoundError:
            return
        except GraphQLError:
            # Some FreePBX Core versions raise an internal GraphQL error for
            # an absent number. The error alone cannot prove absence: require
            # an explicitly complete inventory before allowing the mutation.
            inventory = self.list_result()
            if any(item.extension == extension_id for item in inventory.items):
                raise FreePBXConflictError(f"Extension {extension_id!r} already exists") from None
            if inventory.complete is not True:
                raise
            return
        raise FreePBXConflictError(f"Extension {extension_id!r} already exists")

    def _matching_extension_after_indeterminate_create(
        self,
        extension_id: str,
        provisional_name: str,
        error: Exception,
    ) -> Extension:
        """Reconcile an indeterminate create response without replaying its mutation."""
        try:
            extension = self.get(extension_id)
        except (FreePBXTimeoutError, NotFoundError) as readback_exc:
            raise error from readback_exc
        if extension.extension != extension_id or extension.name != provisional_name:
            raise error
        log.info("Verified extension %s after indeterminate mutation response", extension_id)
        return extension

    @staticmethod
    def _raise_for_failed_mutation(operation: str, result: dict[str, object]) -> None:
        if result.get("status") is not True:
            message = str(result.get("message") or f"{operation} failed")
            raise FreePBXValidationError(message, details=result)


def _to_graphql_input(body: dict[str, object]) -> dict[str, object]:
    """Translate public snake_case schema fields to FreePBX GraphQL names."""
    field_names = {
        "extension": "extensionId",
        "voicemail_enabled": "vmEnable",
        "user_management_enabled": "umEnable",
        "outbound_cid": "outboundCid",
        "secret": "extPassword",
    }
    return {field_names.get(key, key): value for key, value in body.items()}


def _provisional_create_name(name: str) -> str:
    """Build a unique, bounded ownership marker for secret-bearing creates."""
    marker = f" pending-{token_hex(8)}"
    return f"{name[: 100 - len(marker)].rstrip()}{marker}"
