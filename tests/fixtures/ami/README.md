# AMI fixture corpus — FreePBX/Asterisk call lifecycle

Permanent fixture corpus for the `pyfreepbx` AMI event listener and a downstream
consumer's call-session ingestion layer. Each file is a verbatim slice of one
real call's AMI event stream, captured from a production PBX and sanitized.

## Provenance

- **Source:** a production FreePBX/Asterisk instance (read-only AMI).
- **Asterisk:** 16.30.0 · **AMI protocol:** `Asterisk Call Manager/5.0.5` · channel tech **PJSIP**.
- **Captured:** 2026-06-17 (UTC) via passive `Events: on` AMI sessions + one authorized
  self-contained echo-test `Originate` (`originate.txt`).
- Captures were taken with `manager.conf` **unchanged** (`timestampevents` is off on
  this box, so raw AMI frames carry no per-event timestamp — see findings report).

## Wire format (preserved exactly)

- Line ending: **CRLF** (`\r\n`). Records separated by a blank line (`\r\n\r\n`).
- **Event names, field names, and field order within each block are byte-faithful**
  to what Asterisk emitted.
- `Uniqueid`, `Linkedid`, `DestUniqueid`, `DestLinkedid`, `BridgeUniqueid` are
  **preserved unmodified** — the correlation relationships are the whole point of
  the corpus.

## Sanitization (what was changed, and why)

Captured from real customer traffic, so PII is pseudonymized **consistently across
the entire corpus** (extension `7006` is the same party in every file):

| Original | Replacement | Notes |
|---|---|---|
| Real device extensions (`105`, `2801`, `30201`, …) | `70xx` | consistent map; applied inside `Channel`/`Interface`/`*Num`/`Exten` |
| Customer display names (`CallerIDName`, `ConnectedLineName`, `MemberName`, …) | `Ext 70xx` (tied to the number) or `Party N` | these were customer **site names** — the main PII |
| Queue ids (`88`, `99`), feature codes (`*43`), `<unknown>`, `s`/`h` | **kept verbatim** | operational identifiers, not PII |
| AMI login secret | never written to any file | extracted server-side at capture time only |

> Channel instance suffixes (e.g. `-001600e9`, `;1`/`;2`) and `Uniqueid`s are
> ephemeral epoch-based ids, not PII, and are kept to preserve relationships.

## Curation

To keep fixtures parser-focused, high-volume non-signaling events were dropped:
`VarSet`, `Newexten`, `RTCPSent`, `RTCPReceived`, `DTMFBegin`/`End`,
`MusicOnHold*`, `MixMonitor*`, `DeviceStateChange`, `ContactStatus`,
`ExtensionStatus`, `PeerStatus`, `Cdr`. **Real streams interleave these** (a busy
PBX emits ~50–100 `VarSet`/`RTCP` per call); the listener must tolerate and skip
unknown/uninteresting events. `abandoned.txt` has 3 of its 5 identical agent
ring-cycles elided.

## Files

| File | Scenario | Captured? | Terminal marker |
|---|---|---|---|
| `answered.txt` | Direct ext→ext call, answered, bridged, hung up | ✅ real | `BridgeEnter` ×2 → `Hangup` |
| `missed.txt` | Direct call, callee never answers | ✅ real | `DialEnd` `DialStatus: NOANSWER`, no bridge |
| `abandoned.txt` | Intercom → operator **queue**, caller gives up before answer | ✅ real | `QueueCallerAbandon` → `QueueCallerLeave` |
| `queue.txt` | Intercom → operator **queue**, operator answers | ✅ real | `AgentConnect` → `BridgeEnter` → `AgentComplete` |
| `originate.txt` | AMI `Originate` (Async) lifecycle | ✅ real (echo test) | `OriginateResponse` (carries `ActionID`+`Uniqueid`) |
| `transfer_blind.txt` | Blind transfer `BlindTransfer` event | ⚠️ **SYNTHETIC** | spec-derived (see below) |
| `transfer_attended.txt` | Attended transfer `AttendedTransfer` event | ⚠️ **SYNTHETIC** | spec-derived (see below) |

### ⚠️ Transfer fixtures are synthetic

`transfer_blind.txt` and `transfer_attended.txt` were **not captured** — they are
hand-built from the Asterisk 16 AMI event schema, using this corpus's `70xx`
naming. **Reason:** operators on this deployment *do not transfer* — they pick up
calls from the queue as those ring on their own extensions (confirmed by the
operator). No `BlindTransfer`/`AttendedTransfer` event appeared in **~35 minutes**
of production capture. These two files are provided so the listener can be coded
against the event shape, but **must be replaced with a real capture in a lab /
maintenance window before any transfer-dependent behavior is relied upon.**

## How a test would use these

Feed the bytes through the AMI frame splitter (`split on \r\n\r\n`), parse each
block to a `dict`, and assert the listener derives the right `CallSession`
state machine transitions keyed on `Linkedid`. See `PROTOCOL_FINDINGS.md` for the
exact correlation model these fixtures validate.
