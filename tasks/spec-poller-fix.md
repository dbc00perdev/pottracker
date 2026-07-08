# Spec — Async Poller "exits after 2–3 cycles" fix

Status: **DONE (2026-07-08, #5).** Outcome ≠ the original plan, and that's the point of the
Step-1 gate. **Defect A ("exits after 2-3 cycles") is NO LONGER REPRODUCIBLE** — mock 20/20
(`scripts/debug_poller.py`, Py 3.13) and **live Viper 6/6** clean cycles (instrumented DEBUG
soak; every sleep `timeout (normal)`, clean stop). It was resolved by fixes landed after this
bug was logged — the **thread-affinity single-worker executor** + the **`cnc_sysinfo`
connection-prime**. The §3 `wait_for`/`CancelledError` hypothesis was a red herring (that path
is provably healthy on 3.13), so **Step 2 (cadence rewrite) was correctly NOT done.** **Defect
B was real and is fixed:** `run()`'s `finally` now sets `self._stop.set()` first (before the
disconnect `await`, so a cancel can't skip it), turning any unexpected `run()` exit into a
clean end of `snapshots()` instead of a stranded-consumer hang. Deterministic regression test
`test_unexpected_run_exit_does_not_hang_snapshots` (mock, CI-safe) added and proven to have
teeth. Root cause + rule captured in `tasks/lessons.md`. R2 note: the tracker does not use
FOCAS ([[../memory]] `tracker-focas-coupling`), so this had no live blast radius. **Still open
(Step 0, separate task):** productionize the sync poller as a supervised process + watchdog —
the intended R2 deploy shape / continuous-freshness path; not blocking.

The original plan follows for history.

---

Status (original): **DRAFT — not started.** Investigation/fix plan for the open bug carried
since Phase 1/2. Do **not** execute mid-Phase-4; this is a deliberate, gated change to shared
FOCAS infrastructure. Owner: dbc00per.

Target file: `shared/focas/poller.py` (the `Poller.run()` loop + `snapshots()`).
Related: `tasks/lessons.md` (thread-affinity, line-buffering, async-exit findings),
`docs/07-risks.md` R2 (shared poller crash), `scripts/focas_soak_simple.py` (sync fallback).

---

## 1. Symptom (observed against the real Viper)

The async `Poller.run()` loop exits cleanly after 2–3 successful cycles: `state` →
`SHUTDOWN`, no *error*-level log seen, `_stop` never set by user code. The consumer
`async for snap in poller.snapshots()` then **hangs forever**. The sync soak
(`focas_soak_simple.py`) does not have this problem (23/23 cycles clean) — it's the
async lifecycle specifically.

## 2. Why the clean exit becomes a hang (two stacked defects)

**Defect A — run() exits early (root cause still a hypothesis, see §3).**

**Defect B — an unexpected run() exit strands consumers.** `run()`'s `finally`
(poller.py ~L349) closes the source and sets `state = SHUTDOWN`, but **never sets
`self._stop` and never signals `self._queue`**. So `snapshots()` (~L452) blocks
forever: its `getter = queue.get()` never fires (producer dead) and its
`stop_waiter = self._stop.wait()` never fires (`_stop` never set). Defect B is
independently fixable and turns "silent stale hang" into "clean end" — the property
that actually matters for a shop-floor live view.

## 3. Leading hypothesis for Defect A (unconfirmed)

The cadence sleep is `await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)`
(~L313), inside `except BaseException: … raise` (~L324). On several CPython versions
`asyncio.wait_for` can surface a **`CancelledError` instead of `TimeoutError`** when the
timeout fires while the inner future is being cancelled. `CancelledError` is a
`BaseException` → the handler **re-raises** → `run()` dies with no error log, `finally`
sets `SHUTDOWN`, consumer hangs. The "2–3 cycles then die" cadence fits a low-probability
per-iteration race. Note the confounder (separate lesson): Git Bash **block-buffers
stdout**, so a re-raised `CancelledError`'s debug line may simply never have flushed —
"no exception logged" ≠ "no exception occurred."

This is a lead, not a verdict. §4 Step 1 confirms it before we change the loop.

## 4. Plan (in order; Option 1 runs in parallel as the safety net)

### Step 0 — Safety net, independent of the bug: productionize the sync poller
The design (R2) already wants the poller as a **separate supervised process**, not inside
the API worker. `focas_soak_simple.py` is proven. Extract its sync loop into a small
supervised entrypoint (one thread/process per machine) that writes `shared.focas_*` under
Docker `restart: always`. This makes the "reads reflect FOCAS within 60s" gate **not
depend on the async poller at all** — the async loop becomes an optimization, not
critical path. Do this first so no downstream phase (4 UI, 6 writes, 10 cutover) is
blocked on the async fix.

### Step 1 — Instrument and confirm (cheap; turns hypothesis into fact)
- Apply the known line-buffering fix to the async soak entrypoint:
  `sys.stdout.reconfigure(line_buffering=True)` + `logging.basicConfig(..., force=True)`.
- Run one async soak against the Viper (dev), capture the flushed debug trace, and read
  which exit path fires: the `wait_for` `BaseException` branch (~L324), the outer
  `except BaseException` (~L341), or a genuine `_stop` set. Record the exact exception
  type/traceback in the report.
- **Gate:** do not proceed to Step 2 until the real exit path is captured. If it is *not*
  the `wait_for`/`CancelledError` path, revise §3 before editing.

### Step 2 — Fix the cadence primitive (likely the actual fix)
Replace the fragile `wait_for(event.wait())` idiom with the 3.11+ `asyncio.timeout()`
context manager, which has well-defined cancellation semantics and no `BaseException`
re-raise:

```python
# was: await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)  + except BaseException: raise
try:
    async with asyncio.timeout(sleep_for):
        await self._stop.wait()      # woke early → stop requested → loop exits next check
except TimeoutError:
    pass                              # cadence elapsed → poll again
```
Removes the path that conflates "cadence elapsed" with "task cancelled." Keep genuine
`CancelledError` (real cancellation from `stop()`) propagating — that's correct shutdown.

### Step 3 — Make it self-healing regardless of cause (belt)
1. In `run()`'s `finally`: always `self._stop.set()` **and** push a sentinel / close the
   queue so `snapshots()` can never hang (fixes Defect B directly).
2. Add an outer **watchdog** (in the supervised entrypoint, not the API): if `state`
   becomes `SHUTDOWN` while the machine should be polling, log and restart the poller
   task with backoff. Even if Defect A recurs, the mirror recovers instead of silently
   going stale.

## 5. Test plan (no hardware required for most of it)
- **Defect B regression (deterministic, mock source):** construct a `Poller` with a fake
  `SnapshotSource`, start it, cancel the run task (or make the source raise), and assert
  `snapshots()` **terminates** rather than hangs (wrap the drain in
  `asyncio.wait_for(..., 1.0)` and assert no `TimeoutError`). This locks Defect B closed
  forever and is pure-asyncio (CI-safe, no DLLs).
- **Cadence primitive:** unit test that a healthy poller with a short interval completes N
  cycles and only stops on `stop()` (already partially covered; extend to N≥5 to catch a
  regression of the 2–3-cycle death in the mock).
- **Real-hardware confirm:** re-run the async soak against the Viper for ≥60 min after
  Step 2/3; expect continuous cycles, `lag_seconds` bounded, clean stop on Ctrl-C.
- **Tracker regression:** R2 — the poller is shared infra; run tracker's FOCAS-consumer
  suite (or the placeholder once wired) before merge.

## 6. Process / rollout (gates)
- **Confirm-before-change:** poller edits touch shared FOCAS infrastructure (CLAUDE.md
  FOCAS + shared-schema rules, R2). Get explicit go before editing `poller.py`.
- Dev only (localhost:5433 mirror); no prod poller change without the Phase-10 cutover.
- No mocking-around: keep the mock harness labeled; the real confirm is the Viper soak.
- Land as its own branch/PR, separate from Phase-4 UI, with the tracker regression green.

## 7. Acceptance criteria
- Async soak runs ≥60 min against the Viper with no unexpected `SHUTDOWN`; `snapshots()`
  yields continuously; clean stop on signal.
- Defect-B regression test present and green in CI (mock, no hardware).
- Root cause documented in `tasks/lessons.md` (replace the "open" finding with the
  confirmed cause + fix).
- Sync supervised poller (Step 0) available as the operational path irrespective of the
  async outcome.
```
