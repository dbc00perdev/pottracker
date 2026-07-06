# SESSION_NOTES.md

Rolling checkpoint for lance-tooling. Read at session start (CLAUDE.md bootstrap step 5).
Newest entry on top.

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
