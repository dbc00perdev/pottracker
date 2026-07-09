# SESSION_NOTES.md

Rolling checkpoint for lance-tooling. Read at session start (CLAUDE.md bootstrap step 5).
Newest entry on top.

---

## 2026-07-09 (pm-2) — Track B part 1: tool-library intake pipeline DONE

Branch `claude/summarize-build-eWINf`. Dev DB migrated to head **0006**, left
**clean** (0 tools/types/assignments/machines). Not yet committed (staged for review).
All dev-only, tooling-schema only (no tracker coupling).

**Why:** the pot map reads "unverified" everywhere without tool identities, and the
physical 100+ library isn't digitized yet — so we built the *intake machine* ahead of
the data. Documenting the crib later is now pure data entry that imports in one command.

**Design settled with dbc00per (industry-standard, sourced):** significant vs
non-significant part numbers — went **non-significant GTID** (identity must never
"lie"; ISO 13399 attribute model). GTID = the existing unique `tooling.tool.short_id`
running serial (no new column). Associative/human nomenclature = a **generated**
description (derived from attributes, so it can't go stale) — the brother's "smart
number" instinct belongs on the *label/description*, not the identity. Added dedicated
`manufacturer` + `edp_number` (maker + EDP reorder key), distinct from vendor/distributor.
See `tasks/spec-tool-numbering.md` + [[tool-numbering-strategy]].

**Shipped:**
- **Migration 0006** — `tooling.tool.manufacturer` + `edp_number` (nullable). Head 0006,
  downgrade round-trips, reconcile test green, R1 held. Wired: tables.py, tool schemas,
  `list_tools` search, frontend Tool type + detail page.
- **Generated description** — `apps/tooling/api/services/tool_label.py` (`tool_description`,
  pure) → `ToolOut.description`. Format `<Ø> <flutes>FL <TYPE> [R<cr>] <SUBSTRATE> <COATING>`
  e.g. `0.5in 4FL SQ EM CARBIDE TIALN`. 7 unit tests.
- **Bulk importer** `scripts/import_tools.py` — CSV → `tooling.tool`, **upsert on GTID**
  (never touches `regrind_count`/`created_at`), tool_type-by-code, **fail-closed**
  validation, dry-run default + `--apply`, DSN-guarded. Optional resident-assignment cols
  (H=D=T default, probe T/H rejected R12, absent machine → skip-with-note). Pure
  `build_rows` + `_apply` split for testability.
- **Intake template** `docs/templates/tool-intake.csv` (header + 2 examples; column
  dictionary in the spec).
- **Proven end-to-end vs dev DB:** seeded tool_types → dry-run (correct GTIDs + generated
  descriptions, Viper assignment skipped as machine absent) → `--apply` (2 tools w/
  manufacturer+EDP) → re-run idempotent (0 new/2 update, still 2 rows, regrind preserved)
  → cleaned up (tools + seeded types removed so they don't collide with suite fixtures).

**Verified:** full suite **407 passed / 1 skipped** (dev DSN, integration ran; +17 Track B:
7 tool_label + 10 import_tools); `ruff check .` + `mypy` (57 files) clean; frontend
typecheck + `vite build` + **18 vitest** green.

**BLOCKED (by design, needs data):** the assignment seed-run with real tools — waits on the
digitized library + a committed `shared.machine` row. Once tools + a machine exist, fill the
template and `import_tools.py --apply` turns "unverified" pots into identified/loaded.

**Queued next (independent):** Track A part 2 (supervised poller + Task-Scheduler runbook);
barcode/QR scan; CAMWorks TechDB sync.

---

## 2026-07-09 (pm) — Track A part 1: Spindle/NEXT overlay (persist + UI) DONE

Branch `claude/summarize-build-eWINf`. Dev DB (localhost:5433) migrated to head
**0005** and left with **0 machines** (clean). Not yet committed (staged for review).
All in-repo, read-only FOCAS, no tracker coupling.

**Decisions locked with dbc00per this session:**
- **Docker is NOT the poller's shape** — the poller needs the Windows-only FOCAS
  DLLs, so it can't be a Linux container. It's a plain Python process; the dev DB
  Docker is only the database, isolated from the tracker's native Postgres (:5432
  vs our :5433). Supervision (part 2) = **Task Scheduler** (zero-install; startup
  trigger + restart-on-failure), NSSM noted as the nicer-but-install upgrade.
- **Scope split:** part 1 = the in-repo persist + overlay (this entry); **part 2**
  (next) = `scripts/focas_service.py` self-healing forever-loop + Task-Scheduler
  runbook.

**Shipped (Track A part 1 — Spindle/NEXT overlay):**
- **Migration 0005 `shared.focas_machine_status`** — one row/machine (PK machine_id,
  FK cascade): head_t_number/next_t_number/mode/running/emergency_stop + last_polled/
  changed. Applied to dev (head 0005), downgrade round-trips, R1 held (tracker absent).
- **`snapshot.py` split** (was 515 LOC, over cap): pure diff layer → new
  `snapshot_diff.py`; I/O stays in `snapshot.py`, re-exports the pure symbols so
  `from shared.focas.snapshot import persist/diff_*` is unchanged. Both files < cap.
- **Status persistence:** `diff_status` (pure) + `_load_status`/`_upsert_status`
  (advance last_changed_at only on change, IS DISTINCT FROM); `persist()` upserts it;
  `PersistResult.status_changed`. **NOT audited** (HEAD/NEXT change every tool call; R17).
- **API:** occupancy tags each pot `location` (spindle/next/null) server-side from the
  status mirror; new `GET /machines/{id}/spindle` (`SpindleOut`); `PotOut.location`
  (non-breaking); `focas_machine_status` added to `_last_polled` freshness.
- **Frontend:** `Pot.location`/`Spindle` types, `useSpindle` (5s), **PotMap.tsx** overlay
  — Spindle + Next slots above the grid; a pot whose tool is HEAD/NEXT is drawn
  vacated ("→ spindle"/"→ next"), never a loaded ghost.

**Verified:** full suite **390 passed / 1 skipped** (dev DSN so integration ran);
`ruff check .` + `mypy` (55 files) clean; frontend typecheck + `vite build` + **18
vitest** (4 new PotMap overlay tests) green. Live openapi check on a running uvicorn
(ephemeral :8055, then stopped): `/spindle` GET route + `SpindleOut` + `PotOut-Output.
location` all present. New tests: `diff_status` + re-export parity (unit), status-mirror
upsert + last_changed-tracks-head (integration), `_pot_location` + occupancy overlay
(occupancy), `/spindle` + pots-location (API), PotMap overlay (vitest).

**✅ LIVE-CONFIRMED on the real Viper (10.1.10.58), 2026-07-09:** ran a live read+persist
soak (10s target, ~35s/cycle for the full 1200-register snapshot) into a seeded demo
machine + browsed the overlay in the running SPA. **First time the new HEAD/NEXT status
persist ran on hardware — cycle 1 clean, 1200 offsets + pots + status persisted, 0 errors.**
`/spindle` returned real **HEAD=T25 / NEXT=T18** (machine in MEM), and pot #6 (identity T18)
was tagged `location:next` → drawn vacated in the pot map. Operator cross-checked accurate.
The overlay is now proven unit → integration → live. (Occupancy read mostly "unverified"
because there's no tool library / assignments yet — honest, and the motivation for Track B.)
Demo torn down after; **dev DB back to clean (0 machines/users/tools, head 0005)**; demo
API/vite + soak all stopped.

**NEXT chosen (2026-07-09): Track B — tool-library INTAKE PIPELINE (build ahead of the data).**
The physical 100+ tool library is on-site but **not digitized to any DB yet**, so the importer's
real seed run is blocked — but everything else is buildable now: `tasks/spec-tool-numbering.md`
(from the locked [[tool-numbering-strategy]]), the bulk CSV→`tooling.tool` importer (tested on
synthetic fixtures), and a **blank validated intake template** so documenting the crib becomes
pure data entry that imports in one command. Deferred: Track A part 2 (supervised poller —
`focas_service.py` + Task-Scheduler runbook; automation of the polling just proven by hand).

---

## 2026-07-09 — closeout: #4/#5 shipped, tracker-FOCAS settled, live full-stack demo

Continuation of the 07-08 session (below). Branch `claude/summarize-build-eWINf`,
**HEAD after this closeout ≈ the docs commit below.** Dev DB (localhost:5433) **wiped
back to clean/empty**; all demo servers **stopped** (tracker on 5173/8001 untouched
throughout). Everything committed.

**Roadmap #1-#5 all DONE + committed** (see the FOCAS-wiring section in `tasks/todo.md`):
- #1 pot map, #2 presetter attribution, #3 occupancy — from 07-08 (with #1/#2 confirmed
  live on the machine).
- **#4** — consolidated Viper OEM bindings into `spec-focas-calls.md`.
- **#5 (async poller)** — Defect A ("exits after 2-3 cycles") **not reproducible** (mock
  20/20 + live Viper 6/6); Defect B (stranded-consumer hang) **fixed** (`run()` finally sets
  `_stop` first, cancellation-safe) + teeth-verified regression test.

**Tracker coupling settled (read-only audit of `C:\Users\dbc00\dev\Lance_CnC_Tracker_App`):**
the live tracker **does not use FOCAS** — JobBoss-ERP FastAPI web app; R2 shared-poller
coupling is aspirational, not live. Memory `tracker-focas-coupling`.

**Live full-stack demo (then torn down):** started tooling API :8002 + vite :5180 (free
ports; tracker holds 8001/5173) against a live Viper snapshot + seeded login (`demo/demo1234`)
+ illustrative T→H assignments → browsed the real pot map (3 loaded✓ / 12 unverified / 8
empty / 1 probe), 400 offsets, audit tags. **Design output — a genuine gap surfaced:** the pot
map shows identity + presence but **not LOCATION**. Caught a tool change mid-session — HEAD=T50
(spindle), NEXT=T33 (pre); the persisted map (pot2=T50) went stale on exactly the moving tools.
Captured in `tasks/lessons.md` + two build-ready backlog items in `tasks/todo.md`:
**Spindle/NEXT overlay** (persist HEAD/NEXT + PotMap overlay + vacated-pot rule; no new FOCAS
read) and **Step-0** (supervised continuous poller — the fix for the "polled 5m ago / Unreachable"
fossil).

**Tool-numbering strategy — decided (design only, not built).** For the 100+ (growing) physical
library + ~50 tools in the two machines, tied into the app AND the **CAMWorks TechDB** (downstream
programming DB). Locked: **3 number-spaces** (GTID identity / per-machine T-number / observed pot),
GTID = **preset-assembly** identity (running serial; regrind→same GTID re-preset, rebuild→new GTID),
**individual** tracking for preset/unique + **class** for cheap consumables, **HYBRID** T-numbering
(permanent core T1–T20 + job band T21–T24 + T50/H50 probe; H=T) — hybrid forced by 24-pot ≪ library
and by CAMWorks cribs being the resident-core+job-adds model. Pot tracker = master tool DB; CAMWorks
TechDB library + per-machine crib synced from it. Full detail in memory `tool-numbering-strategy`.
Build deliverables (not started): bulk tool importer, barcode/QR label+scan, `spec-tool-numbering.md`.

**NEXT session (code) — two tracks, both dev-only / non-tracker-coupled:**
1. **Step-0: supervised continuous poller + watchdog** (highest value) — makes the mirror stop being a
   fossil, unblocks the Phase-4 "reads reflect <60s" gate. Pairs with the **spindle/NEXT overlay**
   (persist HEAD/NEXT + PotMap overlay).
2. **Tool-numbering build** — write `tasks/spec-tool-numbering.md` from the locked strategy, then the
   bulk tool importer (CSV → `tooling.tool`) + assignments for the ~50 resident tools (turns the
   "unverified" pots into identified/loaded). This is what makes the pot matrix mean something.

---

## 2026-07-08 (pm) — FOCAS pot/presetter/occupancy wired into the app (#1-#3, committed)

Three roadmap items shipped on `claude/summarize-build-eWINf`, all read-only FOCAS.
**HEAD = `7d3c24c`** (feat arc) on top of **`2bf0425`** (probe-lint CI fix). Dev DB
(localhost:5433) now at head **0004**, and **reset to a clean empty state** (last
session's demo data — 1 machine / demo user / 1200 offsets / 3 tools / 1 assignment /
10 tool_types — wiped per operator OK; it was blocking the local API integration
suite via a machine-name collision). Full suite **372 passed / 1 skipped** WITH the
dev DSN (all integration ran). `ruff check .` + mypy + frontend typecheck/build/vitest green.

- **#1 pot map** — `read_pots()` reads the PMC D-area (pot N at D(104+N), packed BCD via
  `decode_pot_bcd`); `cnc_rdmagazine` kept as `_read_pots_magazine` (Phase-8 dispatch).
  Identity only. Offline-proven vs the captured T30↔T50 probe bytes.
- **#2 presetter attribution** — bound `cnc_rdmacro` (`ODBM`; length arg **10**, not the
  padded sizeof 12). Skip vars #5061-63 → `MachineSnapshot.macros` → mirror
  **`shared.focas_macro_var`** (migration **0004**, downgrade round-trips, R1 held).
  `persist` tags an **H_GEOM** offset change coincident with a fresh skip as
  `presetter_verified` (else `manual_edit`) in `audit_log.after_value` — scoped to H_GEOM
  because G31 is shared with the spindle probe; first-observation never tagged. Two
  integration tests prove the path vs the real DB.
- **#3 occupancy model** — `apps/tooling/api/services/occupancy.py`: pot identity →
  `tooling.assignment.h_register` → h_geom offset (T≠H). States loaded/empty/unverified/
  probe + `verified` (reads #2's tag). `GET /machines/{id}/pots` enriched (backward-compat);
  **PotMap.tsx** now color-coded + legend + ✓ badge. **Reinit alarm** in `persist`
  (`detect_pot_reinit`, ≥4 pots→ordinal in one cycle → `pot_reinit_suspected` event).

**Operator gates — ✅ BOTH CONFIRMED LIVE on the real Viper (10.1.10.58), 2026-07-08:**
1. **#1 pot map** — `read_pots()` cross-checked vs the panel: spindle=T21 (D104 & R327 agree),
   next=T50 (R325), anchor pots (1=T1, 3=T33, 4=T30, 5=T84, 6=T83, 21=T90) all match. BCD read
   works on hardware. (Pots 18-24 read ordinals = sticky/empty — the ambiguity #3 resolves.)
2. **#2 presetter attribution** — baseline-persist → operator zeroed reg#19 (4.6123→0) → presetter
   (→10.121 → back to original) → 2nd persist caught **reg#19 4.6123→4.6130** + skip **#5063
   3.2946→3.276**, tagged **`presetter_verified`**. Full G31→macro→attribution chain proven live.
   (Two-shot manual persist caught the net only via presetter repeatability; the continuous 5s
   poller (#5) would catch each transition — reinforces why #5 matters.)
   Dev DB cleaned after (temp verify machine removed; back to empty).

**Deferred:** D104 spindle-overlay in occupancy (needs status/spindle persistence — small
follow-up).

**#4 (DONE):** consolidated the verified Viper bindings into `tasks/spec-focas-calls.md`
(authoritative OEM PMC/macro table + identity-vs-presence rules; corrected stale O5).

**Tracker coupling settled (read-only audit of `C:\Users\dbc00\dev\Lance_CnC_Tracker_App`):**
the **live Lance Tracker does NOT use FOCAS** — it's a JobBoss-ERP-sourced FastAPI web app
(no pyfocas/fwlib/ctypes; the only FOCAS mention is an archived "NO CODE EXISTS" plan). So
pottracker's **R2 shared-poller coupling is aspirational, not a live dependency** — poller
edits have no tracker blast radius. Real couplings = shared Postgres (R1, separate schemas) +
shared deps if same env (R3, isolated by `.venv`) + same box. Saved as memory `tracker-focas-coupling`.

**#5 (DONE — async poller):** With R2 de-risked, ran it here. **Defect A ("exits after 2-3
cycles") is NO LONGER REPRODUCIBLE** — mock 20/20 + **live Viper 6/6** clean cycles (read-only
instrumented soak). Resolved by the earlier thread-affinity + sysinfo-prime fixes; `wait_for`
hypothesis was a red herring → no cadence rewrite. **Defect B (real, fixed):** `run()`'s
`finally` now `self._stop.set()` first (cancellation-safe) so an unexpected exit ends
`snapshots()` cleanly, never hangs a consumer. Deterministic regression test (teeth-verified).
**Still open (not blocking):** Step-0 productionize the sync poller as a supervised process +
watchdog — the intended R2 deploy shape / the Phase-4 "reads reflect <60s" path.

---

## 2026-07-08 — Phase 4 frontend build-complete + FOCAS pot/presetter cracked live

Huge session on `claude/summarize-build-eWINf`. HEAD after closeout ≈ **`f306b81`+** (docs).
Dev DB (localhost:5433) untouched except demo data (safe to wipe). Demo servers stopped.

**Phase 4 — Frontend foundation: BUILD-COMPLETE (read-only) — 9 commits (`bdd6963`→`1807ac1`).**
Stack approved + installed (`--exact`): TanStack Query 5 / React Router 7 / shadcn-style
(cva/tailwind-merge/clsx/lucide) / Vitest+RTL. Delivered: scaffold (Vite8/React19/TS6/Tailwind4,
`@/`, `/api/tooling` dev-proxy to **:8001** — 8000 is the tracker), **auth slice** (401→refresh→retry,
AuthProvider, protected routes), **app shell** (role-filtered sidebar/topbar/responsive drawer),
**Tools** list+detail, **Machines** list + MachineView read tabs (PotMap/Offsets/ToolLife, Alarms
placeholder), **Dashboard** (live /health + pending-reviews) + **Audit**, **a11y** (focus-trap drawer,
keyboard tabs, skip link). 14 tests, typecheck+build green. **web CI job** added. Every data surface
**live-contract-verified** against the API (temp dev rows created+deleted each time; DB left clean).
Gate remainder: full manual per-role walkthrough + "reads within 60s" (blocked on the poller).

**FOCAS breakthrough — reverse-engineered the Viper's tool state that FOCAS said was unavailable
(5 commits `fe1e117`→`f306b81`, all read-only probes; findings in `tasks/lessons.md`):**
- **Pot table** = PMC **`D105..D128`** (pot 1..24), **`D104`** = spindle tool, **BCD-encoded**.
  Verified vs operator (pot1=T1, pot2=T90, pot3=T33). `cnc_rdmagazine` is EW_NOOPT here.
  Traps documented: BCD (T90=`0x90`=144) breaks a raw-value search / 0..99 filter.
- **Empty pots are STICKY** (retain last tool # / reinit to ordinal) — pot cell = *identity only*.
- **Offset = the occupancy/verification truth.** Proven LIVE: zeroed geom offset **#21** (3.4744→0),
  ran the presetter, it wrote **5.6883** back to h_geom #21 — read back verbatim via `read_offsets()`.
  Coincided with a fresh **G31 skip** (`#5061-63`). So: presetter G31 touch → skip latched → macro
  computes → writes H-geom → app reads it. **Attribution:** offset-change + fresh skip = presetter-
  verified; no skip = manual edit (R11 signal). `cnc_rdmacro` decode: `mcr_val/10^dec_val`, dec_val −1=vacant.
- **Live full-stack demo worked earlier**: persisted a real snapshot → the browser showed the Viper
  Connected with the real 400-register offset table.
- New read-only probes committed: `scripts/probe_pot_table.py`, `scripts/probe_presetter.py`.

**New enquiry doc:** `docs/09-enquiry-tooling-recall-crib.md` — v2 feature (proven tooling recipes +
static crib + push-offset-back-on-recall). **Phase-6 (write) dependent.** Key tightening captured:
stale-offset hazard (never push blind; re-verify changeable tools), provenance = presetter-verified+
ran-good, T≠H so recall carries the real H/D.

**Memory added:** `working-style-domain-vetting` — dbc00per vets domain/correctness logic deeply
before coding; brother is the on-site machine/FOCAS expert giving live ground truth.

**NEXT SESSION (all confirm-gated — FOCAS/offset/pot/shared-schema):**
1. Wire `read_pots` (PMC D104/D105-128 BCD) → mirror → **UI pot map lights up** (identity).
2. Bind `cnc_rdmacro` in the client (read-only) → read `#5061-63` in the snapshot → presetter attribution.
3. Occupancy model in the app: offset≠0=loaded, +skip=verified; reinit-detection alarm (pots→ordinals).
4. Consolidate the Viper bindings into `tasks/spec-focas-calls.md` (R327/R325, D104/D105-128 BCD, #5061-63, offset=truth).
5. **Async-poller fix** (`tasks/spec-poller-fix.md`) — needed for *continuous* live freshness; still parked.
6. Phase-4 gate: seeded per-role walkthrough; watch CI green on Actions (gh not authed here).

---

## 2026-07-07 (pm-2) — Phase C: backend resume done (2 commits)

All 5 Phase-C items landed on `claude/summarize-build-eWINf`. HEAD = **`0bfe67b`**. No
installs, no DB safeguards touched; dev DB (localhost:5433) still at head `0003`.

- **`beec5b9`** feat(api): envelope `/assignments` + `/audit` pagination; docs/04 drift fixes
- **`0bfe67b`** ci: add mypy job + run API integration tests against a Postgres service

**What landed:**
1. **Pagination (breaking shape change, confirmed by dbc00per):** `/assignments` + `/audit`
   now return `{items,total,limit,offset}` like `/tools`. `/assignments` gained `limit`/`offset`
   (default 50, max 500); services do COUNT + paged select. Tests updated to read `["items"]`.
2. **`/health`** already public in code — only docs/04 wording fixed (`any` → `none — public`).
3. **docs/04 drift:** added Auth section (`/auth/login|refresh|me`), `requires_climb` +
   server-managed `regrind_count`, `400`→`422`, `/tools/{id}` active-only history, machine POST
   `probe_h_register` + `skip_probe`, dropped unimplemented `with_assignment`.
4. **Tool-type seed:** ran `scripts.seed_tool_types` against dev — dry-run + apply = **10 rows**
   verified (DSN guard fired on dev target), then **deleted the rows** to leave the DB clean for
   the test suite (tool=0 → safe). DB baseline restored.
5. **CI:** new **mypy** job (scoped apps/shared/migrations via `[tool.mypy] files`; jose/passlib
   missing stubs ignored — no new deps) + a **`postgres:16` service on host port 5433** so
   `alembic upgrade head` + the `integration`-marked API tests run in CI (5433 = the DSN guard's
   dev fingerprint, so no `LANCE_ALLOW_PROD` needed).

**Real finding (fixed):** CI's `ruff check .` was **already red** since `75eebe1` — the tracked
`scripts/probe_modal_v*.py` FOCAS probes trip RUF012/N801. Never caught because `gh` isn't authed
here and local ruff was only run on changed files. Fixed with a per-file-ignore glob mirroring
`ctypes_defs.py`; `ruff check .` is green again. Lesson captured (run CI's exact command over CI's
exact file set; local-green ≠ pipeline-green).

**Verification (all local, inside `.venv`):** `ruff check .` clean · `mypy` clean (51 files) ·
full suite **326 passed / 1 skipped** with `DATABASE_URL` set (integration tests ran) ·
`alembic upgrade head` works through the guard.

**Couldn't verify:** CI runs themselves (`gh auth` not configured on this box) — the workflow is
validated by local reproduction of each step, not by a live Actions run. First push should be
watched. **Follow-up filed (todo backlog):** bring `scripts/` under the mypy gate — 3 pre-existing
errors excluded, incl. a likely real latent bug in `focas_smoke.py:231` (`sorted({… if is None})`
→ set of only `None`; touches FOCAS diagnostic logic, confirm before changing).

**NEXT SESSION:** watch the first CI run on this branch (confirm the postgres service + migrate +
integration + mypy jobs go green on Actions). Then Phase 4 = React/Vite frontend foundation
(read-only browse of tools + machine state) — toolchain already pinned in `apps/tooling/web`
(no app scaffold yet: Phase 4 owns tsconfig/vite.config/src + shadcn init). Same constraints:
explicit approval before any install; `.venv/Scripts/python` for all tooling; dev DB only.

---

## 2026-07-07 (pm) — Closeout: install safeguards + deps installed & pinned (2 commits)

Goal met: **all deps installed behind maximum DB safeguards.** Everything on the dev
container (localhost:5433, head 0003); **production DB never touched.** Two commits on
`claude/summarize-build-eWINf`:
- **`de39367`** feat(safeguards): DSN preflight guard + complete & pin the tooling venv (16 files)
- **`bdd7dd6`** feat(web): pin frontend toolchain (Vite 8 / React 19 / TS 6 / Tailwind 4) (2 files)

**Safeguards landed (all verified on dev):**
- **DSN preflight guard** `shared/dsn_guard.py` — refuses any non-dev target unless
  `LANCE_ALLOW_PROD=1`, prints "about to hit <db>" first. Wired into all 5 DB entry points
  (alembic env, api/db, seed_tool_types, manage_users, soak persist). 11 unit tests
  (`tests/test_dsn_guard.py`). Proven through alembic: prod refused, dev passes, override honored.
  Escape hatch `LANCE_DSN_GUARD_DISABLE=1` for fabricated-DSN unit tests.
- **R1 migration guard** reaffirmed (50 tests pass); dev `alembic current`=0003; tracker absent.
- **Backup/restore runbook** `docs/runbooks/backup-restore.md`, drilled end-to-end on dev.
  **Found a real trap:** schema-scoped `pg_dump` omits the `pgcrypto` extension →
  fresh-DB restore fails on `shared.gen_random_uuid()`. Fix (pre-create extension in target)
  documented + in lessons.md.
- **Prod GRANT lockdown** `scripts/sql/prod_grant_lockdown.sql` (idempotent, parameterized),
  verified via a rolled-back drill on dev (`t t t t f f t`: tooling/shared DDL granted, tracker
  DDL denied, tracker-table grant REVOKE'd, blessed view readable). Dev left pristine.
- **Locks:** `constraints.txt` (Python, 52 pkgs) + `apps/tooling/web/bun.lock`.

**Installs (fully isolated — system Python untouched, proven):**
- `.venv` (already existed, isolated) **completed**: added `httpx` (undeclared — TestClient needs
  it), `passlib`, `pytest-cov`. **bcrypt pinned `>=4.0.1,<4.1`** in `[api]`.
- Frontend toolchain in `apps/tooling/web` via **bun --exact**: react/react-dom 19.2.7, vite 8.1.3,
  typescript 6.0.3, @vitejs/plugin-react 6.0.3, tailwindcss + @tailwindcss/vite 4.3.2.
  **No app scaffold / no shadcn yet** — Phase 4 owns tsconfig/vite.config/src + shadcn init.
- Full suite **326 passed, 1 skipped** INSIDE `.venv`.

**The isolation earned its keep — sandbox caught 2 breakages system Python masked (R3 in action):**
1. **bcrypt 5.0 vs passlib 1.7.4 (EOL):** passlib's init probe hashes a >72-byte string; bcrypt
   >=4.1 hard-errors instead of truncating. Pinned bcrypt 4.0.1 = **the exact version the live
   tracker runs (<5.0)**. Tracker context confirmed: tooling+tracker would share a system-Python
   pool, but tooling's dedicated `.venv` (system-site-packages=false) is the permanent fix — our
   install did NOT move system bcrypt (still 4.0.1). Both isolated AND version-matched.
2. **psycopg2 missing:** `test_persist_snapshot` built its engine from a bare `postgresql://` DSN
   (→ defaults to psycopg2, not shipped). Fixed to `postgresql+psycopg://` v3 like the rest.

**Discipline going forward (the one footgun):** ALWAYS use `.venv/Scripts/python` for tooling
installs/runs — never bare `python` (system). A stray `pip install` into system Python is the only
way tooling could move the tracker's shared bcrypt/fastapi. Reproducible install:
`.venv/Scripts/python -m pip install -e '.[api,dev]' -c constraints.txt`.

**Rollback markers on disk (untracked, `reports/`):** `venv-rollback-phaseB.txt`,
`venv-marker-pre-bcrypt-pin-*.txt`, `frontend-marker-pre-install-*.txt`. `constraints.txt` +
`bun.lock` + git history are the durable known-good; the markers are session scratch (safe to delete).

**NEXT SESSION — Phase C: resume backend items (none touch installs or the DB safeguards):**
1. **Pagination** — envelope `/assignments` + `/audit` to `{items,total,limit,offset}` matching
   `/tools`. Response-shape change (recommended, was unanswered). Update schemas + tests + docs/04.
2. **`/health` auth** — keep public, fix docs/04 wording (recommended).
3. **docs/04 doc-drift** fixes (auth endpoints, skip_probe, probe_h_register, requires_climb/
   regrind_count undocumented; 400→422; `/tools/{id}` "full history" vs active-only; `with_assignment`
   param not implemented). Mostly doc edits + 1–2 small code changes.
4. **Commit + run the tool-type seed** against dev (`python -m scripts.seed_tool_types`; verify 10 rows).
5. **CI: add a mypy job** + run API integration tests (lessons.md gap).
   Run everything via `.venv/Scripts/python`. `DATABASE_URL` = the dev DSN (localhost:5433).

---

## 2026-07-07 — Closeout: audits + seed script; NEXT = install deps with DB safeguards

Short session. No installs (per dbc00per). Everything committed + pushed (branch
`claude/summarize-build-eWINf`, HEAD after this = the seed-script commit).

**Landed:**
- `scripts/seed_tool_types.py` — idempotent upsert of the v1 canonical tool-type set
  (em_square, em_ball, em_corner_radius, face_mill, chamfer, spot_drill, drill, reamer,
  tap, probe). Verified: dry-run + 2× apply = 10 rows (idempotent), demonstrated rolled-back
  so the dev DB stays clean for the test suite (which creates its own em_square/drill fixtures).
- **Read-only env audits** (no installs): backend = **every** pyproject dep already satisfied
  (fastapi/sqlalchemy/alembic/psycopg/jose/passlib+bcrypt/pytest/pytest-cov/mypy/ruff/httpx) →
  zero installs needed for backend/API/CI work. Frontend = **nothing installed** (empty
  `apps/tooling/web`, no package.json); a build needs ~**175 npm packages** (React 19 / Vite 8 /
  TS 6 / RR7 / Tailwind 4), mostly already in the 6.2 GB npm cache. Node 22.16 + npm 10.9 +
  **bun 1.3.12** all present.
- **API contract review** (subagent, docs/04 ⟷ code): paths/methods/auth-roles all match.
  Open items carried to next session (below).

**dbc00per's concern (addressed):** installs are filesystem-only and cannot touch/corrupt the DB;
the real DB risks are migrations/seeds/running-against-prod, all kept on the **dev container
(localhost:5433, `pottracker_dev`)** this whole project — production DSN never touched. The
legitimate install caution is about **shared Python deps vs the tracker app (R3)** + the fragile
PC, not the database.

**NEXT SESSION — install all deps WITH live-DB safeguards (dbc00per's explicit ask):**
1. **Python venv for tooling** (`.venv`) — sandbox all installs from the tracker app + system
   Python so no install can conflict (R3). Reinstall `pip install -e .[api,dev]` into it. This IS
   the "install everything," done isolated. **Strongest safeguard for the install-conflict worry.**
2. **DSN preflight guard** — refuse any migration/app/seed run whose target host/db isn't the dev
   target unless `LANCE_ALLOW_PROD=1` is explicitly set. Print "about to hit <db>" before acting.
3. **Reaffirm R1 migration guard** (migrations/_guard.py, 50 tests) is active; keep everything on
   dev 5433 until an explicit, backed-up cutover.
4. **Backup + restore drill** (`pg_dump tooling.* + shared.*`) documented + tested before any prod
   migration (R15 / open Phase-2 task).
5. **Pin dependency versions** (pyproject/lock) so installs are reproducible — no surprise floats.
6. **Prod GRANT lockdown** (docs/07 R1 template) prepared + verified: `lance_tooling` role gets DDL
   only on tooling+shared, SELECT only on named tracker views — physical DB-level belt for cutover.
7. **Frontend install** in apps/tooling/web via **bun or pnpm** (global store + hardlinks, not a
   heavy duplicated node_modules), pinned versions — isolated from Postgres + Python by construction.

**Open contract decisions (were mid-question when we stopped):**
- Pagination convention: /tools is enveloped {items,total,limit,offset}; /assignments + /audit are
  bare arrays. Recommend enveloping all three. (unanswered)
- /health auth: currently fully public; docs say "any". Recommend keep-public + fix doc. (unanswered)
- Doc-drift fixes to docs/04 (auth endpoints, skip_probe, probe_h_register, requires_climb/
  regrind_count undocumented; 400→422; /tools/{id} "full history" vs active-only; with_assignment
  param not implemented). Mostly doc edits + 1–2 small code changes.
- CI: add a mypy job + run API integration tests (lessons.md gap).

---

## 2026-07-06 — Phase 3: tooling schema + minimal FastAPI API

**Branch:** `claude/summarize-build-eWINf` (continues Phases 0–2). **Not yet merged to main.**

**State:** Phase 3 complete and verified. Full suite **312 passed, 1 skipped**; ruff + mypy clean
on all new code; API coverage **94%** (gate >80%). Dev DB at **head `0003`** (localhost:5433).

### What landed
- **Migration `0003_tooling_core`** — `tooling.{tool_type,tool,assignment,pot_observation,offset_write_request}`
  + `shared.machine.probe_h_register`. Applied to dev DB; downgrade round-trips; `tracker` absent (R1 held).
  - Assignment uniqueness = **partial unique indexes** `WHERE deleted_at IS NULL` (D-B): T#/H#/D# free up
    after soft-delete. NOT deferrable → atomic register swaps deferred to Phase 5.
  - `offset_write_request` created **schema-only** (D-D); no write path (Phase 6).
- **FastAPI app** `apps/tooling/api/` — 18 routes under `/api/tooling`, router↔service split, all files <400 LOC.
  - Auth: JWT (jose HS256, `ver` claim), passlib+bcrypt, roles viewer<operator<setter<admin; `/auth/login|refresh|me`.
  - tools / tool-types / assignments / machines / audit / health. RFC7807 problem+json errors.
  - **Probe-lock (Decision-4/R12):** assignment POST rejects `t_number==probe_t_number` AND
    `h_register==probe_h_register` (422). Verified live: T50→422, H50→422.
  - FOCAS "connected" **inferred from mirror freshness** (D-F) — no live poller in the API this phase.
  - Machine POST does a **TCP reachability probe** (D-G) with `skip_probe=true` override.
- `shared/db.py` gained `machine` + `user` Table defs. `apps/tooling/api/tables.py` mirrors `tooling.*`.
- **Reconciliation drift test** (`tests/test_tooling_tables_reconcile.py`) — Core Tables ⟷ migrated DB
  (closes the pending Phase-2 drift-guard task for shared+tooling).
- `scripts/manage_users.py` — create/set-password/list for `shared.user` (auth bootstrap).
- Deps: added `pytest-cov` (approved) to `[dev]`; moved `passlib[bcrypt]` into the `api` extra.

### Test harness note (for future API tests)
API integration tests hit the live dev DB, marked `integration`, skip without `DATABASE_URL`.
Isolation = outer transaction on one connection, rolled back at teardown; app's `get_session` is
overridden to yield sessions bound to that connection (`join_transaction_mode="create_savepoint"`),
so per-request commits become savepoint releases the outer rollback undoes. Seed fixtures `commit()`
(savepoint release) so app request-sessions see them. See `tests/api/conftest.py`.

### Open / next (see tasks/todo.md Phase 3 tail)
- **Commit a real `shared.machine` Viper row** — deferred: needs a verified `probe_pot` value
  (CHECK constraint pairs `probe_pot` with `probe_t_number`). Tests seed it in-transaction.
- **Async-poller exit-after-2-3-cycles bug** — still OPEN, separate Phase 3 task (not the API deliverable).
  Sync soak is the operational path. Investigate `Poller.run()` exit path per lessons.md.
- **Full manual OpenAPI ⟷ docs/04 contract review** before Phase 4 UI builds on it (only spot-reviewed so far).
- Phase 4 = React/Vite frontend foundation (read-only browse of tools + machine state).

### Gotchas surfaced
- Data-model gap: `shared.machine` had `probe_t_number` but no `probe_h_register` — added in 0003.
  Lesson captured (paired locked resources each need a column, never a hardcoded constant).
- pytest-cov + coverage were missing; installed pytest-cov (approved). argon2/email-validator absent
  (unused — email is plain str, hashing is bcrypt).
