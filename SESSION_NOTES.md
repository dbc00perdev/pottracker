# SESSION_NOTES.md

Rolling checkpoint for lance-tooling. Read at session start (CLAUDE.md bootstrap step 5).
Newest entry on top.

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
