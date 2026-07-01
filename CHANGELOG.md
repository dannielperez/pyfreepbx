# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `docs/FIELD_LEARNINGS.md` — field notes for the SDK (auth precedence, the provisional-GraphQL don't-sweep-on-empty guard, the AMI `AMI_IDLE` idle sentinel, the `originate` 30 s default that consumers pin shorter, `linkedid` call correlation, URL parsing). Each note tagged `[CONTRACT]`/`[PROVISIONAL]`/`[CONSUMER]` by validation status.
- `tests/test_integration_patterns.py` — a 42-test regression net over the public surface a consumer depends on (exports, exception hierarchy, facade construction + URL parsing, config contract, consumed service-method presence across extensions/queues/firewall/health/diagnostics, the AMI event-parsing contract, and `StatusResult` shape). No live FreePBX/socket required.
- `AMIEventListener` — synchronous AMI event listener (connect/login, reconnect/backoff, optional noise filter) yielding typed events; reuses the `AMIClient` socket transport. Stateless: no call-session state or ActionID->Uniqueid map (consumer-owned).
- `pyfreepbx.models.events` — typed AMI event DTOs (Newchannel/Newstate/DialBegin/DialEnd/BridgeEnter/Hangup, Queue* and Agent* queue events, OriginateResponse, Blind/AttendedTransfer, UnknownEvent). `linkedid`-first; never fabricated (e.g. `OriginateResponse` carries no Linkedid).
- `parse_event()` in `pyfreepbx.clients.ami_parser` — pure AMI frame -> typed DTO parser.
- `AMIClient.read_event()` — public event-frame read used by the listener.
- AMI fixture corpus under `tests/fixtures/ami/` (captured + sanitized; blind/attended transfer fixtures are synthetic/spec-derived).
- `FreePBX` facade with `from_env()` and explicit configuration.
- `FreePBX.from_url(url, **kwargs)` — construct from a full URL; auto-extracts host, port, api_base_path.
- `FreePBX.from_dict(config)` — construct from a configuration dictionary; accepts `url` or `host` key.
- `FreePBX.status() → StatusResult` — combined query returning health, extensions, queues, and endpoint summary in one call with graceful per-sub-query degradation.
- `StatusResult` model — Pydantic model bundling ok, error, health, extensions, queues, endpoints.
- `ExtensionService` — list and get extensions via GraphQL.
- `QueueService` — list, get, stats, members, add/remove members.
- `HealthService` — summary, PBX info, endpoint registration, queue overview.
- `SystemService` — core status via AMI.
- `AMIClient` — typed socket client with connection lifecycle, safe action gateway.
- `GraphQLClient` / `FreePBXClient` — httpx-based GraphQL transport.
- `RestClient` — GET/POST/PUT/DELETE escape hatch for `/rest` endpoints.
- `OAuth2Client` — client_credentials token management with auto-refresh.
- Pydantic models for extensions, queues, devices, health checks, system info.
- Input schemas for queue member operations.
- Structured logging under `pyfreepbx.*` namespace.
- `py.typed` marker for PEP 561.
- Exported `StatusResult` and `EndpointSummary` from top-level package.
- CI workflow for Python 3.10–3.13.
- Publish workflow with trusted publishing (TestPyPI → PyPI).
- Examples: list_extensions, queue_stats, queue_health, health_check.

### Fixed
- Added `hatch-vcs` `fallback-version = "0.0.0"` for Docker builds without VCS metadata.
- Removed hardcoded example host from `.env.example`.

### Changed
- **Extension write operations** — `create()`, `update()`, `update_secret()` now implemented via REST API (previously raised `NotSupportedError`)
  - `ExtensionService` accepts optional `RestClient` for write operations
  - `ExtensionCreate` schema extended with `secret` and `email` fields
  - `ExtensionUpdate` schema extended with `secret` and `email` fields
  - Facade wires `RestClient` into `ExtensionService` automatically
- **REST client error hierarchy** — HTTP 409 → `FreePBXConflictError`, 422 → `FreePBXValidationError`, transport errors → `FreePBXTransportError`
- **New exceptions** — `FreePBXValidationError`, `FreePBXConflictError`, `FreePBXTransportError` exported from top-level package

### Added
- **Firewall service** — read-only access to FreePBX Firewall module network definitions
  - `FirewallNetwork` Pydantic model (`name`, `network`, `zone`, `enabled`)
  - `FirewallService.list_networks()` — fetches trusted/blocked network entries via `/rest/firewall/getnetworks`
