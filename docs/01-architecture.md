# 01 — Architecture

## System purpose

Single source of truth for **tool identity** at Lance Industries, two-way synced with FANUC offset and pot tables on the Viper LG-1000AP and AG100 (and future shop machines). Decouples tool identity from FANUC register slots, enables cross-machine tool reuse, eliminates manual handwritten tool tables, audits every offset change.

## High-level shape

```
┌────────────────────────────────────────────────────────────────────┐
│                       Lance Floor Application                      │
│  (single host, single domain, modular FastAPI + Vite frontend)     │
│                                                                    │
│  ┌──────────────┐    ┌──────────────┐    ┌─────────────────────┐   │
│  │   Tracker    │    │   Tooling    │    │   Shared services   │   │
│  │ (existing)   │    │   (new)      │    │  - auth             │   │
│  │              │    │              │    │  - machines         │   │
│  │              │    │              │    │  - users            │   │
│  └──────┬───────┘    └──────┬───────┘    │  - audit log        │   │
│         │                   │            │  - FOCAS poller     │   │
│         └───────────┬───────┘            └──────────┬──────────┘   │
│                     │                               │              │
│                     ▼                               ▼              │
│              ┌─────────────┐                ┌──────────────┐       │
│              │ PostgreSQL  │                │   FOCAS      │       │
│              │ schemas:    │                │   client     │       │
│              │  tracker    │                │   (Python)   │       │
│              │  tooling    │                └──────┬───────┘       │
│              │  shared     │                       │               │
│              └─────────────┘                       │               │
└────────────────────────────────────────────────────┼───────────────┘
                                                     │ TCP/8193
                                ┌────────────────────┼────────────────┐
                                │                    │                │
                                ▼                    ▼                ▼
                       ┌─────────────────┐  ┌─────────────────┐  ┌─────────┐
                       │ Viper LG-1000AP │  │     AG100       │  │  ...    │
                       │ FANUC 0i-MF     │  │  FANUC 0i-MF    │  │ future  │
                       │ 10.1.10.58      │  │  (TBD)          │  │         │
                       └─────────────────┘  └─────────────────┘  └─────────┘
```

## Deployment model

Same host as Lance CNC Tracker. Separate FastAPI worker process. Shared PostgreSQL instance. Shared nginx ingress, namespaced routes:

- `/api/tracker/*` → tracker worker
- `/api/tooling/*` → tooling worker
- `/api/shared/*` → shared services worker
- `/tracker/*` → tracker frontend bundle
- `/tooling/*` → tooling frontend bundle

Schemas in PostgreSQL:

| Schema | Owner | Purpose |
|---|---|---|
| `shared` | both | machines, users, audit log, FOCAS connection state |
| `tracker` | tracker | existing tracker tables, untouched by tooling |
| `tooling` | tooling | tools, assignments, offsets, pot table snapshots |

## FOCAS layer

Lives in `shared/focas/` as a separately deployable Python package. Three components:

| Component | Role |
|---|---|
| `focas.client` | Thin wrapper over `pyfocas` (or vendored Fanuc DLL). One connection per machine, connection pool, circuit breaker. |
| `focas.poller` | Background asyncio task per machine. Reads offsets, pot table, alarms, tool life on configurable cadence. Writes to `shared.focas_state`. |
| `focas.writer` | Mediates write requests from tooling/tracker. Enforces operator-confirmation requirement, audit logging, read-after-write verification. |

Both tracker and tooling consume from `focas.poller` outputs (DB state, not direct calls). Only tooling currently writes via `focas.writer`. Tracker remains read-only.

## Data flow — read path (offset polled from machine)

1. `focas.poller` reads offset table for Viper every 60s
2. Diff against last snapshot in `shared.focas_state.offsets`
3. Changed registers → emit event to `shared.audit.offset_change`
4. `tooling.assignment` rows referencing changed registers updated with new values
5. UI (live via WebSocket or polling) reflects new offsets within ~60s of operator probe completion
6. Operator sees diff card in UI: "Offset H125 changed from 2.4567 to 2.4612 — confirm?"
7. Operator confirms → `tooling.assignment.confirmed_at` updated. Now authoritative.
8. Until confirmed, assignment shows "pending operator review" badge.

## Data flow — write path (offset pushed from app to machine)

1. Operator action in UI: "Reset H125 wear to 0" / "Update D125 to 6.350" / "Push preset offsets to machine"
2. Frontend → `POST /api/tooling/offsets/write` with intent + reason
3. Backend validates: tool exists, register in valid range, value in plausible range, machine reachable
4. Confirmation dialog rendered with diff: old value → new value, expected impact
5. Operator confirms in UI (second confirmation, distinct from intent submission)
6. `focas.writer.write_offset(machine, register, value, user, reason)`
7. FOCAS write executed
8. **Read-after-write**: same register re-read, compared to written value
9. If match → audit log entry (success), return to UI
10. If mismatch → audit log entry (FAILED), alarm raised, write reversed if possible, error to UI

## Identity model — decoupled

Three layers, never collapsed:

| Layer | Lives in | Stable across |
|---|---|---|
| **Tool identity** (`tooling.tool`) | App DB | Machine moves, pot moves, regrinds |
| **Machine assignment** (`tooling.assignment`) | App DB | Pot moves within a machine |
| **FANUC register state** (`shared.focas_state`) | Mirror of FANUC | Reflects whatever the control says right now |

A tool can exist in the library without being assigned. An assignment binds a tool to a machine + H register + D register. The pot it currently sits in is tracked but is allowed to drift (random-access ATC) — pot is observed state, not commanded state.

## Random-access ATC handling

Viper LG-1000AP changes pots at will to optimize tool change time. App must:

- **Never assume pot mapping is stable** between cycles
- **Read pot table from FANUC** (FOCAS function `cnc_rdtofs` for offsets, `cnc_rdmagazine` or equivalent for pot data — verify exact call in implementation)
- **Show "current pot"** in UI as informational only
- **Show "load pot"** as the pot the operator should drop the tool into when first loading — typically lowest-numbered free pot, but configurable

The probe pot is fixed and reserved. Its T-number is configurable per machine (default: T99 or whatever the machine's probe macro expects).

## Multi-machine

v1 supports Viper + AG100. Architecture supports N machines. Each machine has:

- IP address + FOCAS port (default 8193)
- Pot count (default 24, includes probe pot)
- Offset register count (default 400)
- Offset banks layout (configurable — different controls organize H1-H99 vs H100-H199 vs H200-H299 differently)
- Tool change strategy (random-access vs sequential)
- Through-spindle-coolant capability (boolean, used to filter tool compatibility)

Tools carry capability flags. Assignment is rejected if tool capability isn't supported by machine (e.g., assigning a TSC-required drill to a non-TSC machine).

## Auth

Shared with tracker. JWT bearer, refresh token, role-based:

- `viewer` — read-only, can see tools/assignments, no writes
- `operator` — confirm offset changes, request offset writes (requires their second confirmation in UI), assign tools to pots
- `setter` — full assignment authority, can override operator confirmations
- `admin` — user management, machine config, audit log access

Audit log records `user_id` on every state change. No anonymous writes.

## Frontend

React + Vite + TypeScript. Tailwind. Single SPA, routed at `/tooling/*`. Shared component library with tracker (planned, post-v1). For v1, tooling has its own components, no forced abstraction yet.

## Out of scope (v1) — design supports, not built

- Offline presetter integration (Zoller, Speroni, Parlec). Hooks reserved in `focas.writer` interface.
- Tool regrind tracking. Tool entity has `regrind_count` field reserved.
- Inventory / consumables / stocking levels.
- Cost accounting per tool / per part.
- Mobile-native app. Web app is mobile-responsive.
- Label printing (Brady/Zebra/Dymo). API endpoint `/tooling/tools/{id}/label` reserved, returns 501 in v1.
- Barcode/QR scanning for pot loading. UI affordance reserved.

## Open architectural questions

Tracked in `tasks/todo.md` as decisions pending implementation:

1. `pyfocas` (community) vs vendored Fanuc DLL wrapper — license + reliability tradeoff
2. WebSocket vs polling for UI live updates — start with 5s polling, upgrade if perceived lag
3. AG100 FOCAS verification — required before AG100 added to machine registry
4. Probe pot T-number per machine — confirm with controls vendor for both machines
5. Exact FOCAS function calls for pot/magazine table read on 0i-MF (FS30i-family processing DLL `fwlib30i64.dll`) — verify against `Fwlib64.h` in `tasks/spec-focas-calls.md`, not assumed
