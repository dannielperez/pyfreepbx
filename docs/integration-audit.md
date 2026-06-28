# pyfreepbx — downstream application Integration Audit

How downstream application consumes `pyfreepbx`, and the public surface pinned by
`tests/test_integration_patterns.py`. pyfreepbx is the **most-used** vendor SDK
in downstream application (16 call-site files) and was, before this audit, the least
contracted — no field-learnings doc and no consumption-pattern test. This
mirrors the `pyruijie` audit pattern (`docs/integration-audit.md` there).

## Summary

downstream application uses pyfreepbx through the `FreePBX` facade and the `parse_event` /
`AMIEventListener` AMI surface. The **AMI** half is the stable, exercised path
(live call ingestion + gated originate). The **GraphQL** half (extensions,
queues, firewall reads) is SDK-declared *provisional* and is consumed
defensively (don't-sweep-on-empty). No breaking issues found; the gaps were
*documentation* and *a regression net*, both added here.

## Integration points

| downstream application file | pyfreepbx surface used | Purpose |
|---|---|---|
| `access_control/call_ingestion.py` | `parse_event`, `AMIEvent` + event DTOs | Parse AMI frames → upsert `CallSession` by `linkedid` |
| `access_control/call_listener.py` | `AMIEventListener`, `AMI_IDLE`, `AMIConfig`, `AMIConnectionError`, `AMIError` | Long-lived per-account event stream + reconnect breaker |
| `access_control/originate.py` | `FreePBX.originate`, `AMIConnectionError`, `AMIError` | Gated resident-approval call (dry-run, 15 s timeout) |
| `devices/services/freepbx.py` | `FreePBX.from_url`, `.health.summary()`, `.status()`, `FreePBXError`, `AuthenticationError`, `AMIConnectionError` | Device adapter: connection test + status snapshot |
| `devices/services/pbx_sync.py` | `FreePBX` (type), `.extensions.list()`, `.queues.list()`, `.firewall.list_networks()` | Sync extensions/queues/firewall → upsert rows |
| `devices/services/pbx_provisioning.py` | `ExtensionCreate` schema | Build extension-create payload |
| `devices/services/firewall_management.py` | facade firewall surface | Firewall posture |
| `organizations/services/connections.py` | `FreePBX.from_url`, `.health.summary()`, `FreePBXError` | Interactive connection test (15 s timeout) |

## Public surface downstream application depends on (pinned by the test)

**Facade** (`FreePBX`): `from_url`, `from_dict`, `from_env`, `status`,
`originate`, `connect_ami`, `close`, context manager, and the service
properties `extensions`, `queues`, `system`, `health`, `firewall`,
`diagnostics`, `rest`, plus `ami_available`.

**Services** (method names the call sites invoke, all pinned by the test):
`ExtensionService.{list,get,create,update,update_secret}`,
`QueueService.{list,add_member_runtime}`,
`FirewallService.{list_networks,create_network,update_network,delete_network}`,
`HealthService.{summary,endpoint_summary,unregistered_endpoints}`,
`DiagnosticsService.{cdr,asterisk_logs,asterisk_summary,endpoint_details}`.

**Config:** `FreePBXConfig` (incl. `has_oauth2`, URL properties), `AMIConfig`.

**AMI:** `AMIEventListener`, `AMI_IDLE` sentinel (identity-compared),
`parse_event(raw, received_at)`.

**Exceptions** (the hierarchy the call sites catch):

```
FreePBXError
├── ConfigError
├── AuthenticationError
│   └── AMIAuthError        (also subclasses AMIError)
├── GraphQLError            (.errors)
├── AMIError
│   ├── AMIConnectionError
│   ├── AMITimeout          (→ AMI_IDLE; never a disconnect)
│   └── AMIAuthError
├── NotFoundError
├── NotSupportedError
├── FreePBXValidationError  (.details, HTTP 422)
├── FreePBXConflictError    (HTTP 409)
└── FreePBXTransportError   (network)
```

The transport-vs-refusal split (`AMIConnectionError` trips the breaker; a bare
`AMIError` means the box is healthy but refused) is load-bearing for
`originate.py` and `call_listener.py` — the test pins it.

## Serialization / model contract

Sync paths normalise SDK models into Django rows. The pinned model field-sets
(`Extension`, `Queue`, `FirewallNetwork`, `StatusResult`, `AMIEvent`) are a
public contract: renaming a field breaks the consumer's row mapping. The test
asserts presence of the fields downstream application reads, so a future rename fails here
first.

## Write-operation risk (future)

| Operation | Path | Risk | Gate |
|---|---|---|---|
| `originate` (place call) | AMI | Medium | permission + dry-run + breaker + audit (`originate.py`) |
| `extensions.create` | REST | Medium | validation/conflict errors; provisioning workflow |
| firewall mutate | GraphQL (provisional) | High | `NotSupportedError` until introspected; owner-gated |

## What this audit added

1. `docs/FIELD_LEARNINGS.md` — auth precedence, provisional-GraphQL guard, AMI
   idle sentinel, originate timeout pin, `linkedid` correlation, URL parsing.
2. `docs/integration-audit.md` — this map.
3. `tests/test_integration_patterns.py` — a regression net over the public
   surface above (exports, exception hierarchy, facade construction/URL
   parsing, service-method presence, AMI event contract). No live server or
   socket required.
