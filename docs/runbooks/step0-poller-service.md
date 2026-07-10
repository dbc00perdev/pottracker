# Runbook — Step-0 supervised FOCAS poller service

Operating the continuous poll service (`scripts/focas_service.py`) that keeps the
`shared.focas_*` mirror fresh so the app stops badging a live machine
"Unreachable · polled Nm ago". Read-only FOCAS; writes only to `shared.focas_*`.

> Spec: `tasks/spec-step0-poller.md`. Supervisor logic + tests:
> `shared/focas/service.py`, `tests/shared/focas/test_service.py`.

---

## 1. What it does

One process per machine. Forever: `connect → read_snapshot() → persist() → sleep`.
It **never exits on FOCAS failure** — read errors trip a circuit breaker that
closes the handle, waits a cooldown, and reconnects with a fresh handle
(control-reboot / network-partition recovery, R19). A DB hiccup is logged but
does not stop polling. The process exits only on a stop signal (clean) or an
unexpected crash (non-zero → Task Scheduler restarts it).

Side effects while running:
- A **heartbeat file** `reports/focas-service-<machine-id>.health.json` (ops
  telemetry: state, last cycle/success, failure counts). The UI's freshness
  comes from the DB mirror, not this file.
- A **PID lockfile** `reports/.focas-service-<machine-id>.lock` (single-instance
  guard). A stale lock (dead PID) is reclaimed automatically on next start.

## 2. Prerequisites

- The tooling `.venv` (`.venv/Scripts/python`). No global Python.
- FOCAS DLLs at `C:\Fanuc\FwLib64-runtime` (or set `FOCAS_DLL_DIR`).
- The dev DB up (localhost:5433) — the DSN guard only allows the dev fingerprint
  unless `LANCE_ALLOW_PROD=1` is set (do NOT set it here).
- **A committed `shared.machine` row for the machine**, and its `id` (UUID) —
  `persist()` keys on it. Get it with:
  ```
  $ psql "$DATABASE_URL" -c "select id, name, ip_address from shared.machine;"
  ```
  (If no row exists yet, that's the still-open "commit the real Viper row" task —
  it needs a verified `probe_pot`. For a throwaway test you may seed one and
  delete it after, leaving the DB clean.)

## 3. Manual run (foreground — for testing before scheduling)

```
$ export DATABASE_URL='postgresql+psycopg://pottracker_dev:...@localhost:5433/pottracker'
$ .venv/Scripts/python scripts/focas_service.py \
    --ip 10.1.10.58 --machine-id viper-lg-1000ap \
    --machine-uuid <shared.machine.id> \
    --interval-seconds 60
```

Watch the log: `connected; polling …` then `cycle OK: …ms head=… next=… offsets=…`
each interval. **Stop with Ctrl+C or Ctrl+Break** — it releases the lock and
exits 0. Confirm the machine badges **Connected** in the app while it runs
(`GET /api/tooling/health` → `focas_connected: true`, `lag_seconds` small).

Flags: `--port` (8193), `--timeout-seconds` (3), `--breaker-threshold` (5),
`--cooldown-seconds` (60), `--lock-path`, `--heartbeat-path`, `--dsn`
(overrides `DATABASE_URL`).

## 4. Install under Task Scheduler (production supervision)

Task Scheduler is the outer watchdog: it restarts the process on crash, OOM, or
host reboot. Zero-install (NSSM is a nicer upgrade if we later want a real
service — deferred).

### 4.1 Session-0 DLL check (DO THIS FIRST)

"Run whether user is logged on or not" runs the task in **session 0**, where the
Fanuc DLLs sometimes fail to load. **Verify before committing to it:**

```
# Simulate a non-interactive run — if this connects and polls one cycle, the
# DLLs load in a service-like context.
$ .venv/Scripts/python scripts/focas_service.py --ip 10.1.10.58 \
    --machine-id viper-lg-1000ap --machine-uuid <uuid> --interval-seconds 5
```

- If it connects → use "Run whether user is logged on or not" (§4.2).
- If it fails with `EW_NODLL` / a DLL load error → **fall back** to a
  "Run only when user is logged on" task with an **At log on** trigger on the
  shop account, and document that the box must stay logged in. (This is the
  known session-0 FOCAS limitation, not a bug in the service.)

### 4.2 Create the task

GUI (Task Scheduler → Create Task), or `schtasks` from an elevated shell. A
`schtasks` skeleton (edit paths/account):

```
schtasks /Create /TN "LanceTooling\focas-service-viper" /SC ONSTART /RL HIGHEST ^
  /RU "SHOP\\lance_svc" /RP * ^
  /TR "cmd /c cd /d C:\Users\dbc00\dev\pottracker && .venv\Scripts\python.exe scripts\focas_service.py --ip 10.1.10.58 --machine-id viper-lg-1000ap --machine-uuid <uuid>"
```

Then, in the task's properties (GUI — these aren't all exposed by `schtasks`):
- **General:** "Run whether user is logged on or not" (only if §4.1 passed);
  "Run with highest privileges".
- **Triggers:** At startup. (Optionally also "At log on" per §4.1 fallback.)
- **Settings:**
  - ✅ "If the task fails, restart every **1 minute**, up to **999** times"
    (the restart-on-failure watchdog).
  - ❌ "Stop the task if it runs longer than…" — **uncheck** (it runs forever).
  - ✅ "If the running task does not end when requested, force it to stop."
  - "Start in" = repo root `C:\Users\dbc00\dev\pottracker` (so `FOCAS_DLL_DIR`
    and the relative `reports/` path resolve).
- **Environment:** the task can't read your shell's `DATABASE_URL`. Either pass
  `--dsn` in the command, or set `DATABASE_URL` as a **machine** env var for the
  run-as account. Never put the prod DSN here — dev only.

### 4.3 Verify the scheduled task

```
$ schtasks /Run  /TN "LanceTooling\focas-service-viper"
$ cat reports/focas-service-viper-lg-1000ap.health.json   # state:"healthy", cycles_ok climbing
# app shows the machine Connected; /health lag_seconds < interval*health_stale_multiple
$ shutdown /r /t 0     # reboot test → after boot, confirm the task auto-started and the mirror is fresh
```

## 5. Stop / teardown

- Graceful: `schtasks /End /TN "…"` (or Ctrl+Break in a foreground run). Lock
  released, exit 0.
- Hard kill (`taskkill /F`, TerminateProcess) is **safe** — the lockfile is left
  behind but reclaimed on the next start because its PID is dead.
- Remove the task: `schtasks /Delete /TN "LanceTooling\focas-service-viper" /F`.
- Delete a seeded test `shared.machine` row afterward to leave the dev DB clean.

## 6. Optional freshness watchdog (ship only if needed)

Task Scheduler restarts a **dead** process but can't detect a **hung** one
(running, not polling). The 3 s read timeout makes true hangs unlikely, so this
is belt-and-suspenders — add it only if a live soak actually shows a hang. Shape:
a second scheduled task every few minutes that reads the heartbeat and, if
`last_success_at` is older than `3 × interval`, `taskkill /F` the PID (Task
Scheduler then restarts the main task). Not built yet — documented for when/if
the failure mode appears.

## 7. Troubleshooting

| Symptom | Likely cause / action |
|---|---|
| `--dsn or DATABASE_URL required` | No DSN. Pass `--dsn` or set the env var for the run-as account (§4.2). |
| DSN guard refuses to start | Target isn't the dev fingerprint (localhost:5433). Do NOT set `LANCE_ALLOW_PROD` here — this is dev-only until cutover. |
| `EW_NODLL` under the scheduled task, but fine in a shell | Session-0 DLL load (§4.1) — use the logged-on fallback. |
| `service already running … refusing to start` (exit 3) | A live instance holds the lock. Only one poller per machine. If it's stale, confirm the PID is dead and delete the lockfile. |
| App still badges "Unreachable" while service logs `cycle OK` | Wrong `--machine-uuid` (persisting to a different machine's mirror), or the app's `poll_interval_seconds × health_stale_multiple` is shorter than the poll interval. |
| No log output in Git Bash | Already handled (line-buffered), but if piping elsewhere, tee to a file. |
```
