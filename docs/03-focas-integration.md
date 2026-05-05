# 03 — FOCAS Integration

## Scope

Defines how the application talks to FANUC controls over Ethernet. Covers library choice, connection management, polling strategy, write path, sync state machine, conflict resolution, and the specific FOCAS calls used.

This document is the contract between `shared/focas/` and the rest of the system. Anything outside this layer interacts with FANUC only through `focas.client`, `focas.poller`, and `focas.writer`.

---

## Confirmed environment

- **Control**: FANUC 30i-B series (software ID `D4F1`, edition `15.0`)
- **Embedded Ethernet**: loaded (`EMBED ETHER 658E 0003` in SYS-CONF.TXT)
- **Viper LG-1000AP**: IP `10.1.10.58`, FOCAS port 8193, port test passed (`TcpTestSucceeded: True`)
- **AG100**: IP unknown, FOCAS assumed live, **must be verified before adding to machine registry**

The Embedded Ethernet module being present is necessary but not strictly sufficient for FOCAS — some controls require an additional Data Window option bit. The successful TCP connection on 8193 is the practical confirmation that FOCAS is licensed and responsive on the Viper. Repeat the same TCP test on AG100.

---

## Library choice

### Options

| Option | Notes |
|---|---|
| **`pyfocas` (community)** | Pure Python. MIT-licensed. Wraps Fanuc's `Fwlib32.dll` on Windows. Last meaningful update unclear — verify before commit. Coverage: most read calls, some writes, decent. |
| **Vendored Fanuc DLL via `ctypes`** | Direct calls to `Fwlib32.dll` (Windows) or `libfwlib32.so` (Linux). Maximum control. Need to wrap each function manually. License of the DLL itself is the question — Fanuc distributes it with their FOCAS SDK, which has license terms. |
| **MTConnect adapter** | Higher-level. Read-only. Not appropriate here because we need writes. |
| **`focas-py` / `pyfanuc` / others** | Various community wrappers exist. Triage at implementation time. |

### Decision (provisional, revisit at implementation)

Start with `pyfocas` for the read path. If write coverage or stability is insufficient, fall back to direct `ctypes` against `Fwlib32.dll`. License terms of `Fwlib32.dll` need legal review before shipping a product that includes it; for internal-use-only tools at Lance, this is generally accepted but the question must be raised, not assumed.

This choice goes in `tasks/todo.md` as Decision-1, blocking implementation.

---

## Connection model

### One persistent connection per machine

FOCAS connections are stateful. Re-handshaking on every call is wasteful and adds latency. `focas.client` maintains:

- One async-safe connection wrapper per machine
- Connection lifecycle: open on poller startup, close on shutdown
- Reconnect logic on transient errors (max 3 attempts, exponential backoff)
- Circuit breaker: 5 consecutive failures → mark machine `unreachable` in `shared.focas_state`, alert UI, stop polling for 60s, retry

### Why a circuit breaker

Polling a dead control every 60s wastes resources and floods logs. A control is "dead" most often because it's powered off (operator went home), in alarm, or being serviced. Backing off until it returns is the right behavior.

---

## Polling

### Cadence

Per-machine, configurable. Default 60s. Floor 10s.

Why not faster: FOCAS calls take 50–500ms each, multiple calls per poll cycle, multiplied by N machines. At 24 machines × 5 calls × 200ms = 24s of FOCAS time per cycle. Sub-30s cadence becomes a problem at scale even though v1 is just 2 machines.

### Per-cycle reads (v1)

| Call (logical) | FOCAS function (provisional) | Frequency |
|---|---|---|
| Read all H/D offset registers | `cnc_rdtofs` (length geom + wear), `cnc_rdtofsr` (range read for diameter) | every cycle |
| Read pot table / magazine | `cnc_rdmagazine` or equivalent — verify exact 30i-B name | every cycle |
| Read tool life data | `cnc_rdtoolgrp_id`, `cnc_rd1tlifedata` (or sequence equivalents) | every cycle |
| Read alarm state | `cnc_rdalmmsg` | every cycle |
| Read current T-number | `cnc_rdtcode` | every cycle |
| Read machine mode (auto/MDI/edit/jog) | `cnc_rdmode` | every cycle |

**Important: the exact 30i-B FOCAS function names above are provisional.** The 30i-B series and Series 16/18/21 use different function names for some calls. Implementation step: pull the FOCAS2 SDK header file or developer manual, verify exact names, and document in `tasks/spec-focas-calls.md`. Don't ship code based on guesses.

### Diff and emit

Each cycle:

1. Read all values
2. Compare to prior snapshot in `shared.focas_offset_register`, `shared.focas_pot`, `shared.focas_tool_life`
3. Where changed: update the row, emit an event to in-process pubsub for UI live updates, write `shared.audit_log` entry
4. Where assignments reference changed offsets: flag `tooling.assignment.pending_review = TRUE` if the diff exceeds `0.5mm` (configurable)

### What "changed" means

Floating-point comparison with epsilon `0.0001 mm` (0.0000039 inch). Below epsilon = noise from rounding/conversion, ignored. Above epsilon = real change, emit event.

---

## Write path

### Why writes are gated behind operator confirmation

A FOCAS write to an offset register changes machine behavior immediately on the next tool call. Wrong value = scrap or crash. The cost of one extra confirmation click is trivial; the cost of an unintended write is potentially thousands of dollars.

No exceptions in v1. Every write requires:

1. UI submission with explicit reason
2. UI confirmation dialog showing diff
3. Operator click on confirm

### Write sequence

```
UI: operator submits write intent
  ↓
API: POST /api/tooling/offsets/write
  ↓
Validation:
  - tool exists
  - register number valid (1..400)
  - value plausible (length: 0..500mm, diameter: 0..200mm — configurable per machine)
  - machine reachable (FOCAS state = 'connected')
  - not in active machining cycle (FOCAS mode != AUTO running)
  ↓
Insert row in tooling.offset_write_request (state: requested)
  ↓
Return request_id to UI
  ↓
UI: render confirmation dialog with diff (current value → intended value)
  ↓
Operator confirms
  ↓
API: POST /api/tooling/offsets/write/{request_id}/confirm
  ↓
Update row: confirmed_at, confirmed_by
  ↓
focas.writer.execute(request_id):
  - re-read current value (FOCAS read of same register)
  - if current value differs from snapshot taken at request time by > 0.001mm: ABORT, mark failed("value drifted between request and execute")
  - FOCAS write call (cnc_wrtofs or equivalent)
  - FOCAS read same register (verification)
  - if read != written by > epsilon: ABORT, mark failed("verification mismatch"), attempt revert
  - if read == written: mark success
  ↓
audit_log entry written regardless of outcome
  ↓
UI updated via pubsub
```

### Why re-read before write

Race condition: between operator submitting intent and confirming, a probe macro on the machine could have updated the same register. The pre-execution re-read catches that. If the value drifted, abort and force operator to re-evaluate.

### Why verification read after write

FOCAS write returns success codes that don't always mean the value took effect. Could be a parameter mode lockout, an active alarm, an option bit issue. Read-after-write is the only way to confirm.

### Mode lockout

Writes refused if machine is in AUTO mode running a program. Acceptable modes for offset writes: MDI, EDIT, JOG, REF. This is enforced at the writer level, not just UI — UI gating is convenience, writer gating is safety.

---

## Sync state machine

For each `tooling.assignment` row:

```
                  ┌──────────────┐
                  │  unassigned  │  no assignment row exists
                  └──────┬───────┘
                         │ operator assigns tool to T#/H#/D#
                         ▼
                  ┌──────────────┐
                  │   assigned   │  assignment row exists, last_confirmed_at IS NOT NULL
                  └──┬────────┬──┘
                     │        │
                     │        │ FOCAS poll detects offset diff > 0.5mm
                     │        ▼
                     │  ┌─────────────────┐
                     │  │ pending_review  │  pending_review = TRUE
                     │  └────────┬────────┘
                     │           │ operator confirms in UI
                     │           ▼
                     │  ┌──────────────┐
                     └─►│   assigned   │  pending_review = FALSE, last_confirmed_at = now()
                        └──────────────┘
```

Operator can also explicitly mark an assignment as "needs review" or "retired."

---

## Conflict resolution

### Scenario A: operator updates app, FOCAS poll then sees machine value differs

Machine wins until operator confirms. App-side edits to assignment metadata (tool_id binding, pot expectations, notes) don't affect FOCAS. App-side edits to expected offset values are not allowed — offset values flow only from FOCAS to app, never the other way except through a write_request.

### Scenario B: two operators try to assign different tools to same T# at the same time

DB constraint `UNIQUE (machine_id, t_number)` rejects the second one. UI shows "T25 was just assigned by [user] — refresh." No silent override.

### Scenario C: write request submitted, but machine probe runs before confirmation

Pre-execution re-read catches the drift, aborts the write, surfaces "machine state changed since you submitted — review and re-submit if still appropriate."

### Scenario D: FOCAS reports a tool in pot N, app says different tool in pot N

App's pot expectation is informational. FOCAS pot reading is authoritative. UI shows the discrepancy as an alert: "Pot 5 expected T25, machine reports T31 — investigate." Doesn't auto-correct.

### Scenario E: multiple machines see "the same" tool

Allowed by design. A tool can be assigned to Viper and AG100 simultaneously, but it's one physical cutter — physically impossible. UI shows "this tool has multiple active assignments" warning, requires explicit override or retirement of one. (For consumable-class tools, this warning is suppressed.)

---

## Mock harness for development

`shared/focas/mock.py` — a fake FOCAS client that returns canned responses. Used in tests and dev without a control connected.

- Mock pot table, mock offset table, mock alarms
- Configurable scenarios: "probe just ran on T125", "alarm raised", "control unreachable"
- Same interface as real `focas.client`
- Never enabled in production builds (env var `FOCAS_MODE=mock|real`, defaults to `real`, mock requires explicit env)

---

## Logging

Every FOCAS interaction logged at appropriate level:

- DEBUG: every read call with response time
- INFO: connection state changes, successful writes
- WARNING: retries, transient failures, value drifts caught
- ERROR: write verification failures, persistent connection failures, alarm conditions

Logs go to stdout (Docker captures), structured JSON, `machine_id` always included.

---

## Open questions for implementation

1. Confirm exact 30i-B FOCAS function names for all calls listed above. Source: FANUC FOCAS2 SDK documentation, not assumption.
2. Confirm offset register layout for the Vipers (which register numbers correspond to H_geom vs H_wear vs D_geom vs D_wear). 30i-M default is documented but Lance machines may have customizations.
3. Determine maximum simultaneous FOCAS connections supported by 30i-B (relevant for multi-instance polling).
4. Confirm `pyfocas` write call coverage matches needs. If insufficient, plan ctypes wrappers.
5. Determine whether tool life write-back is required v1 (operator marks tool expired in app → push to FANUC), or read-only is sufficient.
