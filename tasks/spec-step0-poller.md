# spec-step0-poller — supervised continuous FOCAS poller service

> Status: DRAFT — awaiting dbc00per sign-off before any code (plan-node gate).
> Track: Step-0 (todo.md "Implementation backlog"). Dev-only, read-only FOCAS,
> non-tracker-coupled. No write path, no HARD-GATE surface.

---

## 1. Goal / why

Make the FOCAS mirror stop being a **fossil**. Today the mirror is only fresh
while a soak script happens to be running by hand; the instant polling stops,
`shared.focas_*` goes stale and the UI badges the machine **"Unreachable ·
polled Nm ago"** even though the map is fully populated (vividly seen 2026-07-09).

The fix is a **supervised, self-healing process that reads the Viper and
`persist()`s every cycle, forever** — the intended R2 production shape and the
path to the Phase-4 gate "reads reflect within 60s."

**Load-bearing finding (verified this session):** the API infers `connected`
purely from mirror freshness — `machines.focas_state()` reads
`max(last_polled_at)` across `focas_offset_register / pot / tool_life /
machine_status` and calls the machine connected when `lag ≤ poll_interval ×
health_stale_multiple`. So a process that keeps `persist()` succeeding is the
*entire* fix — **no API/UI/schema change required.**

## 2. Scope

**In:**
- A sync, forever-running supervisor loop (connect → read → persist → sleep) that
  **reconnects instead of exiting** on FOCAS failure (circuit breaker + backoff).
- Graceful shutdown on SIGINT/SIGTERM (Task Scheduler "End task").
- Single-instance guard (no two services double-writing one machine).
- Heartbeat file for ops/watchdog visibility.
- Task Scheduler runbook (startup trigger + restart-on-failure + run-as).
- CI-safe unit tests (fake client + fake persist, injected clock/sleep).

**Out (explicitly):**
- Any FOCAS **write** path (Phase 5/6, HARD GATE — untouched here).
- New FOCAS reads / new bindings. Uses the existing `FocasClient.read_snapshot()`.
- param-1013 startup guard (Fork C = out; lands with AG100 configize).
- Two-tier fast/slow polling (Fork A = single-tier; loop is structured so a fast
  status tier can be added later without a rewrite).
- API/UI changes, migrations, NSSM install.
- Multi-machine orchestration (Viper-only v1; the loop is per-machine, so a
  second machine = a second scheduled task, not new code).

## 3. Locked decisions

| Fork | Decision | Rationale |
|---|---|---|
| **A — cadence** | **Single-tier**, full snapshot every `--interval 60s`. Effective period = `max(interval, cycle_time)`; full snapshot ≈35s so 60s = ~35s work + ~25s idle. | Satisfies "reads reflect <60s" for offsets+pots+status. 5s live overlay is a later refinement, not the gate. |
| **B — supervision** | **Windows Task Scheduler** (zero-install). Startup trigger + restart-on-failure + run-as a service account. NSSM noted as the nicer install-required upgrade. | Decided 2026-07-09. Poller can't be Docker (needs Windows FOCAS DLLs). |
| **C — param 1013** | **Out of Step-0.** | Adds a new `cnc_rdparam` binding (fresh FOCAS surface); Viper increment is panel-verified. Land with AG100 per-machine configize (Phase 8). |

## 4. Architecture

Split logic from entrypoint so the supervisor is mypy-covered and unit-tested
(the async `Poller` sets the precedent — a breaker deserves tests):

```
shared/focas/service.py     # the supervisor: testable, no DLLs, no argparse
scripts/focas_service.py    # thin entrypoint: args, DLL dir, logging, DSN
                            #   guard, lock, signals → wires real client+persist
docs/runbooks/step0-poller-service.md   # Task Scheduler setup + verify + teardown
tests/focas/test_service.py # CI-safe unit tests (fake client, fake persist)
```

Reuse, don't reinvent: the loop body is exactly `focas_soak_simple.py`'s proven
`connect → read_snapshot() → persist()` (single connection, single thread —
FOCAS handles are thread-affined, and a plain sync loop is inherently one
thread). Step-0 changes the **lifecycle around** that body, not the body.

### 4.1 Supervisor (`shared/focas/service.py`)

A `run_service(...)` function driven by injected dependencies so it's testable:

- `client_factory: Callable[[], SnapshotSource]` — builds/connects a fresh
  `FocasClient` (mirrors the async poller's factory pattern for clean reconnect).
- `persist_fn: Callable[[MachineSnapshot], PersistOutcome]` — the entrypoint
  wraps `Session(engine)` + `persist(session, snap, machine_uuid)`; the
  supervisor stays DB-agnostic and CI-testable.
- `sleep: Callable[[float], None]` and `monotonic: Callable[[], float]` —
  injected so tests drive time without real sleeps.
- `heartbeat_fn: Callable[[Heartbeat], None]` — write state out each cycle.
- `stop: threading.Event` — set by the signal handler for graceful exit.

**State machine (sync analogue of the async poller's breaker):**

- `CONNECTING` → call factory. On success → `HEALTHY`. On failure → count it,
  backoff, retry (never exit on connect failure — the machine may just be off).
- `HEALTHY` → read + persist each cycle. A read `FocasError` increments
  `consecutive_failures`; a persist (DB) error is **logged + recorded but does
  NOT trip the FOCAS breaker** (DB hiccup ≠ FOCAS down — matches the soak's
  "keep polling" rule).
- `consecutive_failures ≥ breaker_threshold` (default 5) → `CIRCUIT_OPEN`:
  close the handle, sleep `cooldown_seconds` (default 60), then `CONNECTING`
  with a **fresh handle** (stale-handle recovery — the R19 network-partition /
  control-reboot case).
- On `stop` set at any point → close handle, exit 0.

**Key difference from the soak:** the soak *aborts non-zero after 5 failures*;
the service *never aborts on FOCAS failure* — it cycles CIRCUIT_OPEN → reconnect
forever. The process only exits on (a) `stop` (clean, 0) or (b) an unexpected
crash (non-zero → Task Scheduler restarts it).

### 4.2 Single-instance guard

PID lockfile (default `reports/.focas-service-<machine-id>.lock`). On start:
if the file exists and its PID is alive → refuse to start (exit non-zero, clear
message). Else write our PID. Remove on clean exit. Prevents two services
double-writing one machine's mirror (double audit rows, racing upserts).

### 4.3 Heartbeat

Write `reports/focas-service-<machine-id>.health.json` each cycle:
`{pid, state, last_cycle_at, last_success_at, consecutive_failures,
cycles_ok, cycles_failed}`. The UI freshness comes from the DB mirror (not this
file); the heartbeat is for humans + the optional watchdog. Line-buffered
logging + `logging.basicConfig(force=True)` (Git-Bash buffering lesson).

### 4.4 Supervision — Task Scheduler (runbook, not code)

- **Trigger:** At startup (+ optional "on logon" if it must run in a session for
  the DLLs). **Restart-on-failure:** every 1 min, up to N attempts — the outer
  watchdog for crash/OOM/reboot.
- **Action:** `.venv\Scripts\python.exe scripts\focas_service.py <args>`,
  **Start in** = repo root (so `FOCAS_DLL_DIR` + relative `reports/` resolve).
- **Run as:** a dedicated service account; "Run whether user is logged on or
  not" — **but** verify FOCAS DLL load works in session-0 (a known Windows
  gotcha; if it fails, fall back to an interactive-session logon trigger and
  document it). This is a runbook verification step, not an assumption.
- **Stop/teardown:** End task sends termination → SIGTERM path → clean exit +
  lockfile removed.

### 4.5 Optional freshness watchdog (documented, not required)

Task Scheduler restarts a *dead* process but can't detect a *hung* one (running
but not polling). The read already has `timeout_seconds=3`, so a true hang is
unlikely, but as belt-and-suspenders the runbook documents a second scheduled
task running a tiny check: if `heartbeat.last_success_at` is older than
`3 × interval`, kill the PID (Task Scheduler then restarts it). Ship this only
if the live soak shows any hang; otherwise leave it documented.

## 5. Failure-mode coverage

| Failure | Recovery | Owner |
|---|---|---|
| Machine powered off / FOCAS down at start | CONNECTING retries with backoff, never exits | supervisor |
| Control reboot / stale handle mid-run (R19) | breaker → close → reconnect fresh handle | supervisor |
| Transient network blip | consecutive_failures < threshold → next cycle recovers | supervisor |
| DB unreachable | persist error recorded, FOCAS polling continues; mirror catches up when DB returns | supervisor |
| Process crash / OOM / host reboot | non-zero exit → Task Scheduler restart | Task Scheduler |
| Process hung (running, not polling) | optional freshness watchdog kills PID → restart | watchdog (opt) |
| Two instances started | lockfile refuses the second | lock guard |

## 6. Dependencies / preconditions

- **A committed `shared.machine` Viper row** — `persist()` keys on
  `shared.machine.id` (UUID). Dev DB is currently clean (0 machines). The
  permanent production row is still gated on a verified `probe_pot` (CHECK pairs
  `probe_pot` with `probe_t_number`) + cutover. For Step-0 **verification** we
  seed a dev Viper row (as prior sessions did) and tear it down after — this
  does NOT close the long-standing "commit the real Viper row" task.
- DSN guard: entrypoint routes the persist DSN through `assert_target_allowed`
  (dev 5433 fingerprint) — same as the soak. Prod refused without `LANCE_ALLOW_PROD`.
- `.venv/Scripts/python` for every run. No installs.

## 7. Testing / verification

1. **Unit (CI-safe, no DLLs/DB)** — `tests/focas/test_service.py` with a fake
   client + fake persist + injected clock/sleep:
   - happy path: N cycles → N persists, heartbeat updated, `last_polled` advances;
   - breaker trips after `threshold` read failures → CIRCUIT_OPEN → reconnect
     (factory called again) after cooldown → resumes;
   - persist error does **not** trip the FOCAS breaker (keeps polling);
   - `stop` event → clean exit, handle closed, lockfile removed;
   - second instance refused by the lock.
2. **Dev run (real DB, mock/short real client)** — run the service against the
   dev DB with a seeded Viper row; confirm `focas_state.connected` flips true and
   `lag_seconds` stays < threshold across several cycles; kill it and watch the
   badge go stale; restart and watch it recover. Tear down (row removed, DB clean).
3. **Live gate (operator, read-only)** — a real Viper soak (like the 07-09
   overlay confirm): start the service, browse the SPA, confirm the map badges
   **Connected** and HEAD/NEXT/pots stay live; pull the machine's network / power
   to prove reconnect; then Task-Scheduler-register it and confirm restart-on-
   reboot. Reads only — no writes, no HARD GATE.
4. `ruff check .` + `mypy` clean (service.py under the mypy gate from the start —
   it's production infra, unlike the grandfathered probe scripts); full suite green.

## 8. Done criteria

- Service runs unattended through: machine-off-at-start, mid-run reboot, DB blip,
  and its own process kill — recovering from each without manual touch.
- Mirror freshness holds `connected=true` continuously while the machine is up.
- Task Scheduler restarts it across a host reboot (runbook-verified).
- Unit tests green in CI; live gate signed off by dbc00per.
- SESSION_NOTES + todo.md updated; the stale "not pushed" note corrected.

## 9. Task checklist

- [ ] `shared/focas/service.py` — supervisor (state machine, breaker, reconnect,
      heartbeat, lock), injected clock/sleep/factory/persist/stop. < 400 LOC.
- [ ] `scripts/focas_service.py` — entrypoint (args, DLL dir, line-buffered
      logging, DSN guard, lockfile, SIGINT/SIGTERM handlers, wire real
      FocasClient factory + `persist`). < 400 LOC.
- [ ] `tests/focas/test_service.py` — CI-safe unit tests (§7.1).
- [ ] `docs/runbooks/step0-poller-service.md` — Task Scheduler setup, session-0
      DLL verification, optional watchdog, verify + teardown.
- [ ] Dev run verification (§7.2); ruff+mypy+suite green (§7.4).
- [ ] (operator) live gate (§7.3) — separate, gated on machine availability.
- [ ] Docs: todo.md Step-0 → done-with-caveats; SESSION_NOTES checkpoint.

## 10. Risks touched

- **R2** (shared poller blast radius) — the whole point is the R2 deploy shape;
  writes stay confined to `shared.focas_*`; per [[tracker-focas-coupling]] the
  tracker doesn't consume FOCAS, so no tracker blast radius. Read-only.
- **R19** (network partition) — the reconnect/breaker path is its mitigation.
- **R17** (audit growth) — status is NOT audited (HEAD/NEXT churn); offset/pot
  changes audit only on change (existing `persist` behavior). Continuous polling
  does not multiply audit rows beyond real changes.

## 11. Long-term / fleet intention (documented, NOT built — no regression conflict)

Recorded so the interim shape is a conscious choice, not drift. **The frozen
production target is `docs/10-fleet-architecture.md` §8.2:** ONE supervised
Windows process looping `for machine in enabled_machines`, a dedicated thread
(handle) per machine, per-machine circuit breaker (F5, F6, §14.3). Step-0 ships
the **per-machine unit** (`FocasService`) plus a **one-process-per-machine**
entrypoint/runbook as the interim — valid and strongly isolated for Viper-only,
but not the §8.2 loop shape.

**Fleet reality (dbc00per, 2026-07-10): ~10 more machines coming —**
- **~7 tool-life + cycle-time monitors.** These do NOT want Viper's full ~35s
  snapshot; they need a **light read profile** (life counters + run/part timers).
  **Cycle-time is a NEW read path** (FANUC timers/params or status timing) that
  no snapshot implements yet.
- **3 are 2026 5-axis dual-spindle lathes.** Each is a `docs/10` §7 onboarding
  project + a `docs/11` lathe class: two spindles/turrets, X/Z(+dual) offset
  vocabulary, unknown OEM PMC bindings, likely new mirror register types. Gated
  on live hardware; must NOT drive today's code.

**Why the interim path carries NO future-regression risk (the check that keeps
us on it):**
1. **Orchestration is additive.** The fleet loop spawns a `FocasService` per
   enabled machine on its own thread. The unit is unchanged; only a new
   orchestrator script is added. Because `FocasService` is synchronous, each
   machine's connect/read/close stays on its own thread → per-handle
   thread-affinity (the hard-won Viper constraint) is preserved for free.
2. **Read profiles are additive.** A `monitor-only` machine gets a different
   `SnapshotSource` (or a profile arg to the factory) returning a **partial**
   `MachineSnapshot`. `persist()` is **additive-upsert** — it upserts observed
   rows and does NOT delete unobserved ones, so a partial snapshot never wipes
   sibling mirrors (satisfies §8.3). No change to the shipped code is forced.
3. **Bindings / lathe class** are already the Phase-8 configize + `docs/11`
   backlog items — orthogonal to Step-0, not blocked by it.

**The one gate before committing the fleet to a single process:** verify that
`fwlib` tolerates **concurrent calls across multiple handles in one process**
(thread-affinity-per-handle is proven; a process-global lock/state is the
unknown). Test at the first 2-machine bring-up. **Fallback if bad:** one process
per OEM *profile* (a Viper process, a lathe process), not per machine — still far
fewer than N tasks, and process-per-machine remains available as the floor.

**Conclusion:** no conflict would force a rewrite of the current build, so the
interim process-per-machine shape proceeds. The fleet loop, `monitor-only` read
profile, and cycle-time read path are tracked follow-ons (todo.md), built as the
machines physically arrive — not ahead of the §7 onboarding gates (§3).
```
