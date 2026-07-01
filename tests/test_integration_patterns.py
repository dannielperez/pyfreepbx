"""Integration-pattern tests — how a downstream consumer uses pyfreepbx.

These tests pin the public surface a consumer's call sites depend on, so an
accidental rename/removal fails *here* instead of silently breaking the consumer.

They require no live FreePBX instance and open no socket — every assertion is
against the importable public API, the exception hierarchy, pure URL parsing,
and the AMI event-parsing contract. See ``docs/FIELD_LEARNINGS.md`` for the
quirks.
"""

from __future__ import annotations

import inspect

import pytest

import pyfreepbx
from pyfreepbx import (
    AMIAuthError,
    AMIConnectionError,
    AMIError,
    AMIEvent,
    AMIEventListener,
    AuthenticationError,
    ConfigError,
    FreePBX,
    FreePBXConflictError,
    FreePBXError,
    FreePBXTransportError,
    FreePBXValidationError,
    GraphQLError,
    NotFoundError,
    NotSupportedError,
    StatusResult,
)
from pyfreepbx.clients.ami_listener import AMI_IDLE
from pyfreepbx.clients.ami_parser import parse_event
from pyfreepbx.config import AMIConfig, FreePBXConfig
from pyfreepbx.exceptions import AMITimeout
from pyfreepbx.models.events import HangupEvent, UnknownEvent

# ---------------------------------------------------------------------------
# Public exports — the names a consumer imports
# ---------------------------------------------------------------------------


class TestPublicExports:
    def test_all_names_importable(self) -> None:
        # Every name in __all__ must resolve on the package.
        for name in pyfreepbx.__all__:
            assert hasattr(pyfreepbx, name), f"pyfreepbx.{name} missing from package"

    def test_version_is_nonempty_string(self) -> None:
        assert isinstance(pyfreepbx.__version__, str)
        assert pyfreepbx.__version__

    def test_consumer_critical_names_exported(self) -> None:
        # The exact symbols a consumer's call sites import.
        required = {
            "FreePBX",
            "AMIEvent",
            "AMIEventListener",
            "StatusResult",
            "FreePBXError",
            "AuthenticationError",
            "AMIError",
            "AMIConnectionError",
            "NotFoundError",
            "NotSupportedError",
        }
        assert required <= set(pyfreepbx.__all__)


# ---------------------------------------------------------------------------
# Exception hierarchy — the catches the call sites rely on
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_all_derive_from_freepbx_error(self) -> None:
        for exc in (
            ConfigError,
            AuthenticationError,
            GraphQLError,
            AMIError,
            AMIConnectionError,
            AMIAuthError,
            NotFoundError,
            NotSupportedError,
            FreePBXValidationError,
            FreePBXConflictError,
            FreePBXTransportError,
        ):
            assert issubclass(exc, FreePBXError)

    def test_ami_connection_error_is_ami_error(self) -> None:
        # AMIConnectionError trips the breaker, a bare AMIError is a
        # healthy-box refusal — the split must hold for consumers.
        assert issubclass(AMIConnectionError, AMIError)

    def test_ami_timeout_is_ami_error_but_distinct(self) -> None:
        # AMITimeout subclasses AMIError so a legacy broad `except AMIError`
        # can't crash on an idle tick — but it is its own type.
        assert issubclass(AMITimeout, AMIError)
        assert AMITimeout is not AMIError

    def test_ami_auth_error_is_both_ami_and_authentication(self) -> None:
        assert issubclass(AMIAuthError, AMIError)
        assert issubclass(AMIAuthError, AuthenticationError)

    def test_graphql_error_carries_errors_list(self) -> None:
        exc = GraphQLError("boom", errors=[{"message": "x"}])
        assert exc.errors == [{"message": "x"}]
        assert GraphQLError("boom").errors == []

    def test_validation_error_carries_details(self) -> None:
        exc = FreePBXValidationError("bad", details={"extension": "required"})
        assert exc.details == {"extension": "required"}
        assert FreePBXValidationError("bad").details == {}


# ---------------------------------------------------------------------------
# Facade construction & URL parsing — exactly how a consumer builds the client
# ---------------------------------------------------------------------------


class TestFacadeConstruction:
    def test_from_url_full_url(self) -> None:
        # connections.py / freepbx.py build via from_url.
        scheme, host, port, path = FreePBX._parse_url("https://pbx.example.com:2443/admin/api/api")
        assert scheme == "https"
        assert host == "pbx.example.com"
        assert port == 2443
        assert path == "/admin/api/api"

    def test_from_url_bare_hostname_defaults(self) -> None:
        scheme, host, port, path = FreePBX._parse_url("pbx.example.com")
        assert scheme == "https"
        assert host == "pbx.example.com"
        assert port == 443
        assert path == "/admin/api/api"

    def test_from_url_infers_http_for_low_port(self) -> None:
        scheme, _host, port, _path = FreePBX._parse_url("pbx.example.com:81")
        assert scheme == "http"
        assert port == 81

    def test_from_dict_requires_host_or_url(self) -> None:
        with pytest.raises(ConfigError):
            FreePBX.from_dict({"client_id": "x", "client_secret": "y"})

    def test_build_without_ami_disables_ami(self) -> None:
        pbx = FreePBX(host="pbx.example.com", api_token="t")
        try:
            assert pbx.ami_available is False
            with pytest.raises(ConfigError):
                pbx.connect_ami()
            with pytest.raises(ConfigError):
                pbx.originate(channel="PJSIP/1000", extension="2000", context="from-internal")
        finally:
            pbx.close()

    def test_service_accessors_present(self) -> None:
        # The service properties a sync/adapter consumer reaches through.
        pbx = FreePBX(host="pbx.example.com", api_token="t")
        services = ("extensions", "queues", "system", "health", "firewall", "diagnostics", "rest")
        try:
            for attr in services:
                assert getattr(pbx, attr) is not None
        finally:
            pbx.close()


class TestConfigContract:
    def test_oauth2_detection(self) -> None:
        # has_oauth2 drives the facade's token-provider wiring + consumer auth-mode precedence.
        assert FreePBXConfig(host="h", client_id="a", client_secret="b").has_oauth2 is True
        assert FreePBXConfig(host="h", api_token="tok").has_oauth2 is False

    def test_url_properties(self) -> None:
        cfg = FreePBXConfig(host="h", port=2443, api_base_path="/admin/api/api")
        assert cfg.graphql_url == "https://h:2443/admin/api/api/gql"
        assert cfg.token_url.endswith("/token")
        assert cfg.rest_url.endswith("/rest")

    def test_ami_config_defaults(self) -> None:
        cfg = AMIConfig(host="h", username="u", secret="s")
        assert cfg.port == 5038
        assert cfg.timeout == 10.0


# ---------------------------------------------------------------------------
# Service method surface — the methods the sync/adapter call sites invoke
# ---------------------------------------------------------------------------


class TestServiceMethodSurface:
    @pytest.fixture
    def pbx(self) -> FreePBX:
        client = FreePBX(host="pbx.example.com", api_token="t")
        yield client
        client.close()

    @pytest.mark.parametrize(
        ("service", "method"),
        [
            # read/upsert sweep
            ("extensions", "list"),
            ("queues", "list"),
            ("firewall", "list_networks"),
            ("health", "summary"),
            ("health", "endpoint_summary"),
            ("health", "unregistered_endpoints"),
            # pbx_provisioning.py — extension lifecycle (REST writes)
            ("extensions", "get"),
            ("extensions", "create"),
            ("extensions", "update"),
            ("extensions", "update_secret"),
            # firewall_management.py — firewall CRUD
            ("firewall", "create_network"),
            ("firewall", "update_network"),
            ("firewall", "delete_network"),
            # pbx_provisioning_orchestrator.py — runtime queue membership
            ("queues", "add_member_runtime"),
            # freepbx.py adapter — diagnostics surface
            ("diagnostics", "cdr"),
            ("diagnostics", "asterisk_logs"),
            ("diagnostics", "asterisk_summary"),
            ("diagnostics", "endpoint_details"),
        ],
    )
    def test_consumed_methods_exist(self, pbx: FreePBX, service: str, method: str) -> None:
        svc = getattr(pbx, service)
        assert callable(getattr(svc, method)), f"{service}.{method} not callable"

    def test_originate_signature_accepts_timeout_ms(self) -> None:
        # A consumer pins timeout_ms=15000 — the keyword must be accepted.
        sig = inspect.signature(FreePBX.originate)
        # originate(**kwargs) delegates; ensure it is var-keyword so timeout_ms passes through.
        assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())


# ---------------------------------------------------------------------------
# AMI event contract — parse_event + AMI_IDLE sentinel
# ---------------------------------------------------------------------------


class TestAMIEventContract:
    def test_parse_known_event_to_typed_subclass(self) -> None:
        frame = {
            "Event": "Hangup",
            "Linkedid": "100.1",
            "Uniqueid": "100.2",
            "Channel": "PJSIP/1000-x",
        }
        ev = parse_event(frame, received_at=42.0)
        assert isinstance(ev, HangupEvent)
        assert isinstance(ev, AMIEvent)
        assert ev.linkedid == "100.1"
        assert ev.received_at == 42.0

    def test_unknown_event_never_raises(self) -> None:
        # parse_event must never raise on an unmodelled Event — consumers rely on it.
        ev = parse_event({"Event": "TotallyMadeUpEvent"}, received_at=1.5)
        assert isinstance(ev, UnknownEvent)
        assert ev.event == "TotallyMadeUpEvent"
        assert ev.received_at == 1.5
        assert ev.linkedid is None

    def test_ami_idle_is_a_distinct_identity_sentinel(self) -> None:
        # Consumers filter with `event is AMI_IDLE`; it must not be an AMIEvent.
        assert AMI_IDLE is AMI_IDLE
        assert not isinstance(AMI_IDLE, AMIEvent)

    def test_listener_constructible_without_socket(self) -> None:
        # A consumer instantiates AMIEventListener(config); construction must not connect.
        listener = AMIEventListener(AMIConfig(host="h", username="u", secret="s"))
        assert hasattr(listener, "listen")
        assert callable(listener.listen)


# ---------------------------------------------------------------------------
# StatusResult shape — freepbx.py adapter reads these fields
# ---------------------------------------------------------------------------


class TestStatusResultContract:
    def test_default_status_result_shape(self) -> None:
        result = StatusResult()
        for field in ("ok", "error", "extensions", "queues", "endpoints"):
            assert hasattr(result, field), f"StatusResult.{field} missing"
        assert result.ok is False
        assert result.extensions == []
        assert result.queues == []
