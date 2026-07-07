# SESSION_NOTES.md

Rolling checkpoint for lance-tooling. Read at session start (CLAUDE.md bootstrap step 5).
Newest entry on top.

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
