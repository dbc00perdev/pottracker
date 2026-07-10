# 10 — Fleet Architecture (north star)

**Status**: planning / north-star. Constrains long-term design. **Does not authorize fleet implementation ahead of Viper v1 gates.**  
**Audience**: anyone adding a second machine, a second machine class, or scaling the poller.  
**Related**: `docs/01-architecture.md` (system shape), `docs/02-data-model.md` (entities), `docs/03-focas-integration.md` (FOCAS contract), `docs/11-machine-classes.md` (mill vs lathe product truth), `docs/07-risks.md` (R18–R22), `tasks/spec-focas-calls.md` (per-profile bindings).

---

## 1. Purpose

v1 is intentionally **Viper mill first**: one control, one OEM binding set, read-only mirror + tool library + assignments. The long-term plan is a **shop-wide** application: **10+ machines**, **mostly lathes**, plus the existing mills.

This document freezes the **fleet-scale shape** so that:

1. Viper-specific constants do not become "how the system works."
2. Step-0 poller and machine schema grow toward multi-machine without a rewrite.
3. Onboarding a new control is a **repeatable product path**, not a hero session of reverse engineering alone.

**Non-goal of this doc**: implement lathe FOCAS, multi-cell UI polish, or AG100-specific bindings. Those wait on live hardware + the onboarding gate (§7).

---

## 2. Design principles (fleet)

| # | Principle | Why |
|---|---|---|
| F1 | **Profile, not brand** | Machines are selected by a FOCAS/capability **profile**, not `if name == "Viper"`. |
| F2 | **Class drives UX** | `machine_class` selects which map/offset vocabulary the UI uses (pot map vs turret map, H/D vs X/Z). |
| F3 | **Config owns OEM truth** | PMC addresses, encoding (BCD/raw), pot/turret base, offset type-code map live in **per-machine (or profile) config**, never as process-global defaults once multi-machine ships. |
| F4 | **Capability matrix over feature flags** | UI and API ask "does this machine provide X?" not "is it a mill?" |
| F5 | **Poller is multi-tenant from day one of production shape** | Even with one enabled machine, the loop is `for machine in enabled_machines`. |
| F6 | **Isolation of failure** | One hung control must not starve the fleet (circuit breaker per machine, dedicated FOCAS thread per handle). |
| F7 | **Onboarding is a gate, not a seed script** | No machine is `enabled=true` until identity + capability probe + panel cross-check pass. |
| F8 | **Write policy is global; write surface is per profile** | Double wall + mode lockout apply everywhere; which registers can be written is profile-defined. |
| F9 | **Mirror freshness is a product feature** | Stale fleet data is worse than sparse data (R11). Lag must be visible per machine. |
| F10 | **Tools global, assignments local** | Unchanged from v1: identity is shop-wide; T/H (or station/offset) binding is per machine. |

---

## 3. Target topology

```
                    ┌─────────────────────────────────────────┐
                    │  Tooling SPA  (/tooling/*)              │
                    │  Fleet dashboard → class-routed machine  │
                    └────────────────────┬────────────────────┘
                                         │ /api/tooling/*
                    ┌────────────────────▼────────────────────┐
                    │  Tooling API (FastAPI)                  │
                    │  occupancy/policy modules per class     │
                    └────────────────────┬────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              │ PostgreSQL               │                          │
              │  shared.machine + profile│   shared.focas_* mirrors │
              │  tooling.* library       │   shared.audit_log       │
              └──────────────────────────┼──────────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────┐
                    │  FOCAS poller host (Windows)            │
                    │  • needs Fwlib64 DLLs (not Linux container)│
                    │  • one worker (thread) per machine handle │
                    │  • Task Scheduler / NSSM supervision      │
                    └─┬──────────┬──────────┬──────────┬──────┘
                      │          │          │          │
                      ▼          ▼          ▼          ▼
                  Mill #1    Mill #2    Lathe #1 …  Lathe #N
                  0i-MF      (TBD)      (TBD FOCAS)  …
                  profile:   profile:   profile:     …
                  mighty_    …          …            …
                  viper_0i
```

**Host split (current intent):**

| Concern | Shape | Note |
|---|---|---|
| PostgreSQL | Docker or shared PG instance | Dev `:5433`; prod schema-isolated from tracker |
| Tooling API + SPA | Same box as tracker (or adjacent) | Namespaced routes |
| FOCAS poller | **Windows process** with Fanuc DLLs | Cannot be pure Linux container; DB remains separate |

See Step-0 backlog in `tasks/todo.md`: production poller = supervised forever-loop writing `shared.focas_*`.

---

## 4. Machine class vs FOCAS profile

Two orthogonal axes. Do not collapse them.

### 4.1 `machine_class` (product / UX)

What the operator and UI mean by "this machine":

| Class | v1 | Fleet target | Primary map UI |
|---|---|---|---|
| `mill` | Viper | AG100 + other mills | Pot / magazine map + spindle/NEXT |
| `lathe` | — | bulk of 10+ fleet | Turret / station map (+ spindle if dual) |
| `mill_turn` | — | later if any | Hybrid; explicit later |
| `other` | — | rare | Read-only status until profiled |

Class selects:

- Occupancy / location **policy module**
- Offset **vocabulary** shown in UI (H/D vs X/Z vs …)
- Default tool-type filters and assignment rules
- Which dashboard cards matter (ATC vs turret vs life)

Details: `docs/11-machine-classes.md`.

### 4.2 FOCAS profile (integration)

How we talk to **this** control instance:

| Profile field (conceptual) | Example (Viper) |
|---|---|
| `profile_id` | `mighty_viper_0i_mf` |
| Control family / DLL | FS30i / `fwlib30i64.dll` |
| Expected identity | `cnc_type=0`, `mt_type=M`, `series=D4F1` (or relaxed) |
| Position source | `pmc_d_bcd_pots` (not magazine option) |
| Active tool source | PMC R327 HEAD / R325 NEXT |
| Offset type-code map | empirical Memory-B mapping |
| Offset increment | 0.0001 mm/count (until param 1013 live-check) |
| Macro attribution | `#5061–63` G31 skip → H_GEOM only |
| Write surface | none in v1; Phase 6 mill offsets later |

**Rule:** a second machine with the same `machine_class` may still need a **different profile** (different OEM ladder). A lathe never reuses mill pot bindings.

Viper authoritative bindings today: `tasks/spec-focas-calls.md` § Verified Viper OEM PMC / macro bindings. Fleet promotes that table from "global client constants" → "profile record."

---

## 5. Capability matrix

UI, API, and poller schedule work off **capabilities**, not class alone.

| Capability | Meaning | Possible sources | UI impact if missing |
|---|---|---|---|
| `active_tool` | Tool in cut / spindle / turret index | PMC head, modal, magazine, unknown | No spindle overlay; show "unknown" |
| `next_tool` | Tool staged | PMC next, unknown | No NEXT slot |
| `tool_positions` | Ordered station/pot identity map | PMC table, `cnc_rdmagazine`, manual only | Map empty / manual entry |
| `position_encoding` | How identity is packed | BCD, raw byte, word | Wrong decode = wrong T# |
| `offsets` | Geometry/wear registers | `cnc_rdtofs` + layout | Offset table disabled |
| `offset_layout` | Type codes / banks | `cnc_rdtofsinfo` + panel map | Refuse wrong labeling |
| `tool_life` | Life counters | FOCAS life APIs / none | Life tab placeholder |
| `alarms` | Alarm messages | `cnc_rdalmmsg*` | Alarms placeholder |
| `status` | Mode / running / estop | `cnc_statinfo` | Health degraded |
| `macros` | Macro vars (skip, etc.) | `cnc_rdmacro` | No presetter attribution |
| `write_offsets` | App may write offsets | Phase 6 + double wall | Writes hidden |
| `probe_lock` | Reserved T/H (or equiv.) | machine columns | No probe rejection |

**v1 mill occupancy** (already implemented) is one **policy** built on:

`tool_positions` (identity) + `tooling.assignment` (T→H) + `offsets.h_geom` (presence) + `active_tool`/`next_tool` (location).

Lathe will get a **different policy** (see doc 11). Never force mill occupancy onto lathe data (R20).

---

## 6. Data model evolution (sketch only)

Current `shared.machine` already has IP, port, pot_count, probe locks, poll interval, enabled. Fleet adds **class + profile** without breaking v1 rows.

### 6.1 Columns / entities (conceptual — not a migration yet)

```text
shared.machine
  + machine_class          TEXT  -- 'mill' | 'lathe' | 'mill_turn' | 'other'
  + focas_profile_id       TEXT  -- FK or code to profile catalog
  + control_family         TEXT  -- e.g. 'fs30i', informational
  + identity_expect        JSONB -- optional cnc_type/mt_type/series checks
  + capabilities           JSONB -- resolved capability flags (or derived)
  + focas_binding          JSONB -- OEM addresses/encoding (or join table)
  # existing: ip, port, pot_count, probe_*, poll_interval_seconds, enabled, ...
```

**Binding blob shape (illustrative):**

```json
{
  "position_source": "pmc_d_bcd",
  "pmc": {
    "area_pots": "D",
    "pot_base": 105,
    "pot_count": 24,
    "encoding": "bcd",
    "head_area": "R",
    "head_addr": 327,
    "next_addr": 325
  },
  "offset": {
    "type_map": {"1": "d_geom", "2": "h_wear", "3": "h_geom"},
    "increment_mm": "0.0001",
    "d_wear_focas": false
  },
  "macros": {
    "skip_vars": [5061, 5062, 5063],
    "attribute_h_geom_only": true
  }
}
```

Viper v1 may keep constants in code until Phase 8; the **schema sketch** is the migration target so AG100/lathe #1 do not hardcode a second global.

### 6.2 What stays stable

| Entity | Fleet impact |
|---|---|
| `tooling.tool` | Global identity (GTID); more tool_types for lathe later |
| `tooling.assignment` | Still per-machine T (or station) + offset registers |
| `shared.focas_*` mirrors | Per `machine_id`; no cross-machine rows |
| Audit | Per machine; write events still double-walled |

### 6.3 What must not stay global in client code

| Today (Viper) | Fleet |
|---|---|
| `_PMC_D_POT_BASE`, R327/R325 constants | `focas_binding` / profile |
| Single offset type map | Per profile |
| Single assert_expected_control default | Per machine identity_expect (or "unknown until probed") |
| One occupancy module for all | Class-selected policy |

---

## 7. Onboarding pipeline (mandatory)

No machine enters production polling until **all** stages pass. Same checklist for AG100, lathe #1, and machine #12.

| Stage | Action | Fail behavior |
|---|---|---|
| 0 — Registry draft | Insert `shared.machine` with `enabled=false` | — |
| 1 — Network | TCP connect IP:port (8193) | Leave disabled; document |
| 2 — DLL path | Windows host can load Fwlib family for control | Block poller for that machine |
| 3 — Identity | `cnc_sysinfo` (and friends); record cnc_type / mt_type / series / version | Mismatch vs expect → refuse enable |
| 4 — Capability probe | Run probe pack: status, offsets layout, magazine/PMC, life, alarms, macros | Record capabilities; missing ≠ fatal if class allows |
| 5 — Binding discovery | If PMC path needed: snapshot/diff probes (`probe_pot_table`, head/next); **never copy another OEM** | No binding → positions capability off |
| 6 — Panel cross-check | Operator confirms ≥1 offset, ≥1 position, active tool | Required for enable |
| 7 — Increment / layout lock | Prefer live param 1013 (when bound); refuse silent wrong units | Block write path; warn on read |
| 8 — Soak | N cycles persist clean (duration scales with risk: second mill shorter than first lathe class) | Fix before enable |
| 9 — Enable | `enabled=true`; fleet poller picks it up | — |

Artifacts to keep per machine:

- Smoke/soak report JSON (like Phase 1 Viper)
- Binding table entry in `tasks/spec-focas-calls.md` (or per-profile appendix)
- Panel cross-check notes (who, when, registers)

**Anti-pattern:** enabling from IP alone, or cloning Viper PMC addresses onto a lathe.

---

## 8. Poller topology for N machines

### 8.1 Constraints learned on Viper (non-negotiable)

- FOCAS handles are **thread-affined** on Windows → **one dedicated single-worker executor per machine handle** (not `asyncio.to_thread` pool).
- Sibling DLL load path is fragile (PATH + preload).
- Full snapshot latency on Viper is **tens of seconds** (Phase 1 soak p50 ≈ 34s). Cadence planning must use **measured** cycle time, not "FOCAS is fast."
- Async poller exists; production shape is a **supervised sync-style service** (Step-0) writing the same `persist()` path.

### 8.2 Recommended production shape (fleet)

```text
focas_service (one Windows process, supervised)
  for each enabled machine in parallel (bounded):
      thread / worker dedicated to that machine
          connect → identity check → loop:
              read_snapshot(profile)
              persist(session)
              sleep(max(0, interval - elapsed))
          on failure: circuit breaker, mark lag, backoff
```

| Parameter | Guidance |
|---|---|
| Default poll interval | Per-machine; v1 UI wants ~5s freshness **when snapshot is cheap enough**; Viper full snapshot may force longer interval or **tiered reads** (status/HEAD every 5s, full offsets every 30–60s) |
| Max concurrent machines / host | Start conservative (e.g. 4–8 full-snapshot workers); measure; scale with second host if needed |
| Floor interval | Never under 10s for **full** offset sweeps without explicit reason (existing rule); status-only can be faster |
| Isolation | Failure/backoff is **per machine_id** |
| Supervision | Task Scheduler (startup + restart-on-failure) or NSSM; Docker is for DB, not FOCAS DLLs |
| Consumers | API/UI only read mirrors + freshness; never open FOCAS from request handlers in fleet mode |

### 8.3 Tiered polling (likely required at 10+)

If full `read_snapshot` stays O(30s) per mill, 10 machines × full snapshot every 5s is impossible on one thread pool.

**Target design:**

| Tier | Contents | Cadence (order of magnitude) |
|---|---|---|
| Fast | status, HEAD/NEXT (or lathe equiv.), alarms | 5–15s |
| Medium | pot/turret identity map | 15–60s |
| Slow | full offset table, tool life | 30–120s |

Exact numbers are **measured per profile**, not copied from Viper. Persist path must accept partial updates without wiping sibling mirrors.

### 8.4 Stale data UX (fleet)

Per machine, always surface:

- `last_polled_at` / lag
- connection state (up / breaker open / disabled)
- **never** show a full pot map as "live" when lag exceeds a threshold (badge: Unreachable / Stale)

This is R11 at fleet scale: a green grid that is five minutes old is a ghost map.

---

## 9. API and UI implications (light)

| Surface | Fleet rule |
|---|---|
| `GET /machines` | Include `machine_class`, `capabilities` summary, lag, enabled |
| Machine detail | Route UI by class: MillMachineView vs LatheMachineView (or feature slots) |
| `/pots` | Mill name retained; lathe may expose `/stations` or same resource with `kind` |
| Occupancy | Service selects policy by class |
| Writes | Hidden unless capability `write_offsets` + role + double wall |
| Dashboard | Fleet health grid first; per-machine drill-down second |

Do **not** invent full lathe OpenAPI now. Do **not** return mill pot semantics for lathe machines.

---

## 10. Write path at fleet scale

Unchanged global policy (CLAUDE.md HARD GATE):

1. Mode lockout — not running / not AUTO (precondition).
2. Double wall — explicit ask + gated password entry.
3. Mock-only in tests/scripts against real IPs.
4. Read-after-write + audit.

Fleet additions:

- Write allow-list is **profile-scoped** (mill H/D wear vs lathe X/Z wear, etc.).
- Drift abort and plausibility ranges are **per register family / machine**.
- Bulk writes across machines are **out of scope** until single-machine bulk is proven (Phase 9).

---

## 11. Ops and capacity

| Topic | Intent |
|---|---|
| Monitoring | Per-machine lag, breaker open, reinit alarms, write failures |
| Backup | Schema-scoped dump + extension precreate (existing runbook) scales; still drill restores |
| Deploy | Tooling API deploy ≠ poller restart policy; poller changes need FOCAS regression |
| Tracker | R1/R2 still hold; fleet does not get a free pass to touch `tracker.*` |
| Hosts | Prefer one well-supervised FOCAS host near the machine VLAN; second host only if capacity demands |

---

## 12. Phasing relative to current build

| Horizon | Scope | Doc / gate |
|---|---|---|
| **Now** | Viper read path complete; Step-0 multi-machine-ready poller; tool library data | `tasks/todo.md` |
| **v1 production** | Viper (+ optional second mill if same class) mill write path | Phases 5–6, 10 |
| **Phase 8 (broadened)** | Second machine **or** second profile: onboarding pipeline + configized bindings | This doc §7; was "AG100 only" |
| **Lathe alpha** | First lathe profile after live smoke; thin UI (status + offsets + stations) | `docs/11` open questions closed on hardware |
| **Fleet scale** | 10+ enabled, tiered poll, multi-host if needed, class-complete UX | Ops metrics green |

**Decision-5** (AG100 port test) remains a special case of §7, not a separate architecture.

---

## 13. Explicit non-goals (until gates say otherwise)

- Implementing lathe FOCAS reads from documentation alone
- Hardcoding a second OEM's PMC map "like Viper"
- Linux-container FOCAS poller (DLL reality)
- Cross-machine single assignment of one physical tool without warning (R13 still)
- Assuming `cnc_rdmagazine` exists on every control
- Sub-10s full offset sweeps across the whole fleet on one host without measurement

---

## 14. Acceptance criteria for "fleet-ready architecture"

Architecture (not full product) is fleet-ready when:

1. Machine enablement follows §7 with artifacts.
2. No FOCAS OEM binding is process-global for multi-profile deploys.
3. Poller loops enabled machines with per-machine isolation and thread affinity.
4. API/UI can show class + lag + capabilities without mill-only assumptions crashing lathe rows.
5. Write gate remains global; write register sets are profile-bound.
6. Viper continues to work as profile `mighty_viper_0i_mf` without special cases outside that profile.

---

## 15. Open decisions (fleet)

Track in `tasks/todo.md` when they become blocking:

| ID | Question | Default until decided |
|---|---|---|
| F-D1 | Binding storage: JSONB on machine vs `shared.focas_profile` table | JSONB on machine for first extra profile; normalize if profiles share |
| F-D2 | Tiered poll schedule defaults per class | Measure on first 3 machines |
| F-D3 | Max machines per FOCAS host | Start 4 full-snapshot; revisit |
| F-D4 | Lathe station field naming in API (`pot_number` vs `station`) | Decide at lathe alpha; prefer explicit `station` |
| F-D5 | Second FOCAS host / VLAN | Only if lag SLOs fail |

---

## 16. Document maintenance

- When a new machine is onboarded, append profile + binding to `tasks/spec-focas-calls.md` (or profile appendix) **and** update capability notes here if the matrix gains a new source type.
- When poller topology changes in code, update §8 and risks R18–R19.
- Do not mark lathe sections "done" without live panel cross-check (same bar as Viper Phase 1).
