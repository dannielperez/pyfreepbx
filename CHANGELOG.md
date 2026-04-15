# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `FreePBX.from_url(url, **kwargs)` — construct from a full URL; auto-extracts host, port, api_base_path.
- `FreePBX.from_dict(config)` — construct from a configuration dictionary; accepts `url` or `host` key.
- `FreePBX._parse_url()` — static helper for URL decomposition (bare hostnames accepted).
- `FreePBX.status() → StatusResult` — combined query returning health, extensions, queues, and endpoint summary in one call with graceful per-sub-query degradation.
- `StatusResult` model — Pydantic model bundling ok, error, health, extensions, queues, endpoints.
- Exported `StatusResult` from top-level `pyfreepbx` package.
- Exported `EndpointSummary` from `pyfreepbx.models`.

### Fixed
- Added `hatch-vcs` `fallback-version = "0.0.0"` for Docker builds without VCS metadata.
- Removed hardcoded example host from `.env.example`.

## [Unreleased - Initial]

### Added
- `FreePBX` facade with `from_env()` and explicit configuration
- `ExtensionService` — list and get extensions via GraphQL
- `QueueService` — list, get, stats, members, add/remove members
- `HealthService` — summary, PBX info, endpoint registration, queue overview
- `SystemService` — core status, health checks, reload
- `AMIClient` — typed socket client with connection lifecycle, safe action gateway
- `GraphQLClient` / `FreePBXClient` — httpx-based GraphQL transport
- Pydantic models for extensions, queues, devices, health checks, system info
- Input schemas for queue member operations
- Structured logging under `pyfreepbx.*` namespace
- `py.typed` marker for PEP 561
- CI workflow for Python 3.10–3.13
- Examples: list_extensions, queue_stats, queue_health, health_check
