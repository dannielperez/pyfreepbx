# pyfreepbx

[![CI](https://github.com/dannielperez/pyfreepbx/actions/workflows/ci.yml/badge.svg)](https://github.com/dannielperez/pyfreepbx/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/pyfreepbx)](https://pypi.org/project/pyfreepbx/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyfreepbx)](https://pypi.org/project/pyfreepbx/)
[![License](https://img.shields.io/pypi/l/pyfreepbx)](https://github.com/dannielperez/pyfreepbx/blob/main/LICENSE)
[![Typed](https://img.shields.io/badge/typing-typed-blue)](https://peps.python.org/pep-0561/)

A typed Python library for **Asterisk AMI** and **experimental FreePBX GraphQL** integration.

> **Status: Alpha (v0.x)** — AMI operations use well-documented, stable Asterisk actions and are reliable. GraphQL queries are provisional and need validation against a live FreePBX instance before they can be considered stable.

## What Works

| Layer | Stability | Description |
|-------|-----------|-------------|
| **AMI client** | **Stable** | Typed methods for Ping, CoreStatus, PJSIPShowEndpoints, QueueSummary, QueueStatus, QueueAdd, QueueRemove. Escape hatch for arbitrary actions. |
| **Health monitoring** | **Stable** | Endpoint registration, queue overview, interface health checks — degrades gracefully without AMI. |
| **Queue live ops** | **Stable** | Live stats, member listing, runtime add/remove (changes lost on Asterisk reload). |
| **System info** | **Stable** | Asterisk version, uptime, active calls via AMI CoreStatus. |
| **Extension read** | **Experimental** | GraphQL queries are unvalidated guesses — will likely need adjustment per instance. |
| **Queue config read** | **Experimental** | Queue module GraphQL support is undocumented and may not exist. |
| **Extension CRUD** | **Not implemented** | Raises `NotSupportedError`. FreePBX does not reliably expose write mutations. |

## Installation

```bash
pip install pyfreepbx
```

## Quick Start

```python
from pyfreepbx import FreePBX

with FreePBX.from_env() as pbx:

    # Connect AMI for reliable operational data
    if pbx.ami_available:
        pbx.connect_ami()

        # Queue stats (stable — AMI QueueSummary)
        for qs in pbx.queues.stats():
            print(f"{qs.queue}: {qs.callers} waiting, {qs.available} available")

        # Health overview (stable — AMI PJSIPShowEndpoints)
        summary = pbx.health.endpoint_summary()
        if summary:
            print(f"{summary.registered}/{summary.total} endpoints registered")

    # Extension listing (experimental — GraphQL, may need adjustment)
    for ext in pbx.extensions.list():
        print(f"{ext.extension}  {ext.name}")
```

Or with explicit configuration:

```python
# OAuth2 (preferred)
pbx = FreePBX(
    host="pbx.example.com",
    client_id="my-client-id",
    client_secret="my-client-secret",
    ami_username="admin",       # optional — enables live stats
    ami_secret="your-secret",
)

# From a full URL (extracts host, port, api_base_path)
pbx = FreePBX.from_url(
    "https://pbx.example.com:2443/admin/api/api",
    client_id="my-client-id",
    client_secret="my-client-secret",
)

# From a config dict (framework integration)
pbx = FreePBX.from_dict({
    "url": "https://pbx.example.com:2443/admin/api/api",
    "client_id": "my-client-id",
    "client_secret": "my-client-secret",
})

# Combined status snapshot (health + extensions + queues)
result = pbx.status()
print(f"Health: {result.health.overall.value}, Extensions: {result.extension_count}")
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `FREEPBX_HOST` | Yes | — | FreePBX hostname or IP |
| `FREEPBX_CLIENT_ID` | Auth ¹ | — | OAuth2 client ID (preferred) |
| `FREEPBX_CLIENT_SECRET` | Auth ¹ | — | OAuth2 client secret |
| `FREEPBX_API_TOKEN` | Auth ¹ | — | Static Bearer token (legacy) |
| `FREEPBX_PORT` | No | `443` | HTTPS port |
| `FREEPBX_API_BASE_PATH` | No | `/admin/api/api` | API path prefix |
| `FREEPBX_VERIFY_SSL` | No | `true` | Verify TLS certificates |
| `FREEPBX_TIMEOUT` | No | `30` | HTTP timeout (seconds) |
| `AMI_HOST` | No | `FREEPBX_HOST` | AMI hostname |
| `AMI_PORT` | No | `5038` | AMI TCP port |
| `AMI_USERNAME` | No | — | AMI login username |
| `AMI_SECRET` | No | — | AMI login secret |
| `AMI_TIMEOUT` | No | `10` | AMI socket timeout (seconds) |

¹ Provide either `FREEPBX_CLIENT_ID` + `FREEPBX_CLIENT_SECRET` (OAuth2) or `FREEPBX_API_TOKEN` (static token).

## Architecture

```
FreePBX (facade)
├── .extensions   →  ExtensionService  →  FreePBXClient (GraphQL) ⚠ experimental
├── .queues       →  QueueService      →  FreePBXClient (config, ⚠ experimental) + AMIClient (live, stable)
├── .health       →  HealthService     →  FreePBXClient + AMIClient (stable)
├── .system       →  SystemService     →  AMIClient (stable)
├── .rest         →  RestClient        →  GET/POST/PUT/DELETE escape hatch
├── .status()     →  StatusResult      →  Combined health + extensions + queues
├── .from_url()   →  Construct from full URL (parses host/port/path)
└── .from_dict()  →  Construct from config dict (framework integration)
```

**Design principles:**
- AMI for live operational state — this is the reliable backbone
- GraphQL API for configuration/inventory (experimental, instance-dependent)
- Services accept both clients; AMI is always optional
- `NotSupportedError` for operations not confirmed via schema introspection

## API Overview

### Combined Status

```python
result = pbx.status()  # → StatusResult (health + extensions + queues in one call)
result.ok              # bool — True unless health is "down"
result.health          # HealthSummary | None
result.extensions      # list[Extension]
result.extension_count # int
result.queues          # list[Queue]
result.queue_count     # int
result.endpoints       # EndpointSummary | None (AMI only)
result.error           # str
```

### Health (stable)

```python
pbx.health.summary()                # → HealthSummary (always works)
pbx.health.pbx_info()               # → SystemInfo | None
pbx.health.endpoint_summary()       # → EndpointSummary | None
pbx.health.unregistered_endpoints() # → list[Device] | None
pbx.health.queue_overview()         # → list[QueueStats] | None
```

### Queues — live operations (stable, AMI)

```python
pbx.queues.stats()                       # → list[QueueStats]
pbx.queues.members("400")                # → list[QueueMember]
pbx.queues.add_member_runtime(...)       # AMI QueueAdd (lost on reload)
pbx.queues.remove_member_runtime(...)    # AMI QueueRemove (lost on reload)
```

### Queues — config (experimental, GraphQL)

```python
pbx.queues.list()              # → list[Queue]        ⚠ provisional query
pbx.queues.get("400")          # → Queue              ⚠ provisional query
```

### System (stable, AMI)

```python
pbx.system.info()       # → SystemInfo (AMI CoreStatus)
```

### Extensions (experimental, GraphQL)

```python
pbx.extensions.list()          # → list[Extension]    ⚠ provisional query
pbx.extensions.get("1001")     # → Extension          ⚠ provisional query
# create/update/enable/disable → NotSupportedError
```

## Development

```bash
git clone https://github.com/dannielperez/pyfreepbx.git
cd pyfreepbx
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

```bash
pytest                                  # run tests
pytest --cov=pyfreepbx --cov-report=term-missing  # with coverage
ruff check src/ tests/                  # lint
mypy src/                               # type check
```

## Known Limitations

- **GraphQL queries are provisional** — field names, query names, and response structures are educated guesses based on FreePBX 16/17 documentation. Validate via `{ __schema { queryType { fields { name } } } }` on your instance. Methods emit `UserWarning` at runtime.
- **No extension CRUD** — `create`, `update`, `enable`, `disable` raise `NotSupportedError`. FreePBX does not reliably expose write mutations via the GraphQL API.
- **Runtime-only queue membership** — `add_member_runtime()` / `remove_member_runtime()` changes are lost on Asterisk reload or restart.
- **`sip_peers()` is deprecated** — chan_sip was removed in Asterisk 21. Emits `DeprecationWarning`. Will be removed in v0.2.0.
- **No async support** — planned for a future release.
- **No ARI or direct DB** — intentionally out of scope for v0.1.0.

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

[Apache-2.0](LICENSE) — Copyright 2026 Daniel Perez
