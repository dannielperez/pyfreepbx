# pyfreepbx — Field Learnings

> Integration field notes for `pyfreepbx`. Much of the GraphQL surface is
> **SDK-declared provisional** (not yet validated against a live FreePBX
> instance). Each item below is tagged with its validation status so a consumer
> knows what to trust:
>
> - **[CONTRACT]** — a stable API/transport contract verified in the SDK source.
> - **[PROVISIONAL]** — the SDK itself flags this unvalidated against a live box;
>   treat results defensively until introspected.
> - **[CONSUMER]** — a guard/quirk worth knowing when calling the SDK.

## Auth — two modes, OAuth2 preferred

- **[CONTRACT]** `FreePBXConfig.has_oauth2` is `bool(client_id and client_secret)`.
  When both are set the facade wires an `OAuth2Client` token provider
  (client-credentials grant, auto-refresh); otherwise it falls back to the
  static `api_token` Bearer. Mirror this precedence in a consumer
  (`auth_mode > api_token > oauth2`). Don't add a third auth path — converge on
  these two.

## GraphQL reads are PROVISIONAL — empty ≠ authoritative-zero

- **[PROVISIONAL]** Every `*Service.list()` / `fetch_all_*` GraphQL read emits a
  `UserWarning` and uses a provisional query whose **field names depend on the
  FreePBX version**. `FreePBXClient.fetch_all_extensions()` does
  `data.get("fetchAllExtensions", {}).get("extensions", [])` — so a schema
  mismatch returns **`[]` silently**, never raising. Same shape for queues and
  the firewall reads.
- **[CONSUMER]** Because empty is indistinguishable from a genuine zero, a
  consumer that syncs SDK results into its own store **must skip any destructive
  "mark missing / retire" sweep when a fetch returns empty** — never delete rows
  on an empty provisional fetch.
- **Action:** validate the queries via introspection
  (`{ __schema { queryType { fields { name } } } }`) on a live box, then drop the
  provisional warnings. Until then, treat counts as best-effort.

## Writes raise `NotSupportedError` rather than fake success

- **[CONTRACT]** Service methods that need an unconfirmed GraphQL mutation or AMI
  action raise `NotSupportedError` instead of silently no-op'ing. This is a
  feature: it tells the caller exactly what isn't wired yet. Extension/firewall
  **creates** go through the REST client (`pbx.rest` / `ExtensionService.create`)
  and raise `FreePBXValidationError` (HTTP 422) / `FreePBXConflictError` (409) /
  `FreePBXTransportError` (network) — catch these specifically.

## AMI — stable, blocking, with an idle sentinel

- **[CONTRACT]** AMI is the **stable** half of the SDK (live events + privileged
  actions over TCP 5038). `AMIEventListener.listen()` is a synchronous,
  blocking generator that yields parsed `AMIEvent` DTOs. On a read-timeout it
  yields the **`AMI_IDLE` sentinel** (an `_IdleTick`, compared by identity
  `event is AMI_IDLE`) — a *liveness tick*, never a disconnect and never an
  event. Consumers MUST filter it.
- **[CONTRACT]** `AMITimeout` subclasses `AMIError` so a legacy broad
  `except AMIError` can't crash on an idle tick, but it is always caught
  more-specifically first. Distinguish **transport failure** (`AMIConnectionError`
  → trip a circuit breaker) from **vendor refusal** (other `AMIError` → the box
  is healthy, the action was rejected).
- **[CONSUMER] originate timeout:** `AMIClient.originate(timeout_ms=30000)`
  defaults to **30 s** — too long for an interactive operator panel. Pin
  something shorter (e.g. 15 s) and pass an explicit `timeout_ms` for any
  interactive call path.
- **[CONSUMER]** AMI is **optional**: the facade only builds an `AMIClient` when
  `ami_username` *and* `ami_secret` are provided; `pbx.ami_available` reflects
  this, and `connect_ami()` / `originate()` raise `ConfigError` when AMI is
  unconfigured. Connection is **lazy** (first AMI op auto-connects).

## Call correlation — `linkedid`, not Hangup cause

- **[CONTRACT]** `AMIEvent.linkedid` is the call/session correlation key
  (`uniqueid` is per-leg). `linkedid` is present on **every** event but is
  `None` on `OriginateResponse` (the consumer resolves it from the originated
  channel). `parse_event(raw: dict[str, str], received_at: float)` maps a raw
  AMI frame to a typed subclass; unknown `Event` values become `UnknownEvent`
  (never raises). Key call-session rows on `linkedid` and derive disposition
  from the **event sequence**, not the Hangup cause code.

## URL parsing — bare hostnames and scheme inference

- **[CONTRACT]** `FreePBX.from_url()` accepts a full URL **or a bare hostname**.
  With no scheme it infers `http` for ports 80–83, else `https`; the path
  defaults to `/admin/api/api` (the standard FreePBX API prefix, under which
  `/token`, `/gql`, `/rest`, `/authorize` all live). Explicit kwargs (e.g.
  `port=`) override URL-derived values. Prefer this constructor over hand-building
  `FreePBXConfig`.

## Timeouts — every external call must have one

- GraphQL/REST: `FreePBXConfig.timeout` (default 30 s). Interactive callers pin
  shorter — e.g. 15 s for a connection test.
- AMI socket: `AMIConfig.timeout` (default 10 s) drives the idle-read window
  that produces `AMI_IDLE`.

---

See `tests/test_integration_patterns.py` for the public-surface contract these
notes describe.
