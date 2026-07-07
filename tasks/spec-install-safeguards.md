# spec-install-safeguards.md

> Plan for: install all deps with maximum protection for the live production DB.
> Status: **DONE — Phase A safeguards + Phase B installs complete, committed (`de39367`, `bdd7dd6`).**
> Phase C (backend resume) is the next session — see SESSION_NOTES.md.
> Author session: 2026-07-07. HEAD `defae31`, branch `claude/summarize-build-eWINf`.
>
> Phase B result: `.venv` completed (httpx/passlib/pytest-cov) + **bcrypt pinned 4.0.1**
> (= tracker's version); `constraints.txt` lock; frontend toolchain pinned via bun
> (Vite 8/React 19/TS 6/Tailwind 4, no scaffold/shadcn). Suite 326 pass in `.venv`.
> Sandbox caught 2 breakages system Python masked (bcrypt/passlib, psycopg2) — R3 in action.

## Phase A results (done this session, no installs)

- **#2 DSN guard** — `shared/dsn_guard.py` + wired into all 5 entry points
  (migrations/env, api/db, seed, manage_users, soak). 11 unit tests. Proven through
  Alembic: prod-like DSN refused (`ProdConnectionRefused`, never connects), dev DSN
  passes (head 0003), `LANCE_ALLOW_PROD=1` lets it through. Escape hatch
  `LANCE_DSN_GUARD_DISABLE=1` for precedence unit tests.
- **#3 R1 reaffirm** — 50 guard tests pass; dev `alembic current`=0003; tracker absent.
- **#4 backup/restore** — drilled on dev: dump tooling+shared → restore into scratch DB →
  head 0003 + 12/12 tables + row-count parity → scratch dropped → dev untouched.
  Runbook `docs/runbooks/backup-restore.md`. **Found the pgcrypto gotcha** (schema-scoped
  dump omits the extension; target must pre-create it) — captured in lessons.md.
- **#6 GRANT lockdown** — `scripts/sql/prod_grant_lockdown.sql` (idempotent, parameterized)
  + rolled-back drill on dev asserting `t t t t f f t` (tooling/shared DDL granted,
  tracker DDL denied, tracker-table grant REVOKE'd, blessed view readable). Role + sim
  tracker rolled back; dev pristine.
- Full suite: **326 passed, 1 skipped**, ruff clean. `.gitignore` gains `*.dump`.

Recommendations locked for Phase B/C: frontend = **toolchain + pinned package.json only**
(defer shadcn/ui init to Phase 4); GRANT drill = **dev, rolled-back** (done).

---

## Goal

Install every dependency the project needs, behind layered safeguards so no install
or subsequent migration/app/seed run can reach or corrupt the production database.
Installs are filesystem-only and cannot touch the DB directly; the real DB risk is
in the *workflow* (migrations/seeds/app connecting to prod, or a shared-dep bump
breaking tracker — R3). Guard the whole workflow, belt-and-suspenders.

**Order:** safeguards first (Phase A, no installs), then installs (Phase B, needs GO),
then resume backend items (Phase C).

---

## Current-state findings (read-only audit, this session)

1. **`.venv` already exists and is already isolated.** `C:\Users\dbc00\dev\pottracker\.venv`,
   own interpreter (Python 3.13.3), `include-system-site-packages = false`, gitignored,
   `lance-tooling` installed editable. Safeguard `#1` (sandbox) is *structurally already
   in place* — it just needs completion + pinning. It is NOT a fresh create.
   - **Present:** fastapi 0.119, sqlalchemy 2.0.49, alembic 1.18.4, psycopg[binary] 3.3.4,
     python-jose 3.5 + cryptography 48, pydantic 2.13, uvicorn 0.34, starlette 0.48,
     mypy 1.20, ruff 0.6.9, pytest 8.4.2, pytest-asyncio 0.26.
   - **MISSING:** `passlib`, `bcrypt` (api extra — auth/`manage_users`/`security.py`),
     `pytest-cov` (dev extra — CI coverage gate), `httpx`.
2. **`httpx` is an undeclared dependency.** `tests/api/conftest.py` uses
   `fastapi.testclient.TestClient`, which imports `httpx`. It is in neither `pyproject`
   nor the `.venv`. API tests cannot run in the `.venv` until it is added. Fix: add
   `httpx` to the `[dev]` extra (small, correct diff).
3. **Dev DB healthy and correct.** `pottracker-dev-pg` up 17h healthy, port 5433.
   `alembic current` = `0003_tooling_core (head)`. Schemas = `public, shared, tooling`.
   **`tracker` absent → R1 held.** DB name is `pottracker` (user `pottracker_dev`).
4. **No lock file** anywhere (`requirements*.txt` / `*.lock` absent). Safeguard `#5` is unstarted.
5. **Frontend empty.** `apps/tooling/web/` has only `.gitkeep`. bun 1.3.12 present, pnpm absent.
6. **DSN entry points (5)** that build an engine and must gain the preflight guard `#2`:
   `migrations/env.py`, `apps/tooling/api/db.py`, `scripts/seed_tool_types.py`,
   `scripts/manage_users.py`, `scripts/focas_soak_simple.py` (persist path).

---

## Safeguard #1 — Python venv sandbox (R3 core mitigation)

**Status: mostly done; needs completion + is the target for #5 pinning.**

Isolation is the primary defense against a tooling install changing what the *tracker*
app imports (R3): separate interpreter, no system-site-packages, gitignored — nothing
installed here can alter system Python or the tracker's environment.

**Action (Phase B, needs GO):**
```bash
# add httpx to [dev] in pyproject first (see #2 findings), then:
.venv/Scripts/python -m pip install -e '.[api,dev]'
```
Fills `passlib`, `bcrypt`, `pytest-cov`, `httpx`. No upgrade of already-satisfied,
in-range packages is forced (pip leaves satisfied deps alone).

**Verify:** `.venv/Scripts/python -m pip check` clean; full test suite green from
inside `.venv` (currently API tests can't run there — no httpx).

**Reversible:** deleting `.venv` and re-creating is trivial; nothing outside it changes.

---

## Safeguard #2 — DSN preflight guard (NEW code)

A single source of truth that **refuses to connect to any non-dev target unless
`LANCE_ALLOW_PROD=1` is explicitly set**, and always prints the target first.

**New module `shared/dsn_guard.py`** (~60 LOC, pure + testable):
```python
def assert_target_allowed(url: str, *, action: str) -> None:
    """Print the target, then allow dev freely / refuse prod unless LANCE_ALLOW_PROD=1."""
```
- Parse with `sqlalchemy.engine.make_url` (handles the `+psycopg` prefix). Extract
  host / port / database.
- **Dev fingerprint** = host in `{localhost, 127.0.0.1, ::1}` **and** port `5433`.
  (Production is never on localhost:5433; this is the robust discriminator — not the
  DB name, which is `pottracker` in both places.)
- Always emit `"[dsn-guard] {action}: about to hit {host}:{port}/{database}"`.
- Dev → return. Non-dev + `LANCE_ALLOW_PROD=1` → loud warning, return. Non-dev without
  the flag → raise with instructions.
- **Test-safety:** skip non-network URLs (sqlite/empty) and honor `LANCE_DSN_GUARD_DISABLE=1`
  so existing unit tests that fabricate URLs aren't broken. Acceptance = full suite stays green.

**Wire into all 5 entry points** (additive one-liner each; no behavior change on dev):
`migrations/env.py`, `apps/tooling/api/db.py::_build_engine`, `scripts/seed_tool_types.py::_engine`,
`scripts/manage_users.py::_engine`, `scripts/focas_soak_simple.py` (persist engine).

**Tests:** `tests/test_dsn_guard.py` — dev accepted (all host forms), prod refused,
prod+flag allowed, driver-prefix normalization, sqlite/empty skipped, disable env.

**Risk note:** touches `migrations/env.py` (R1-adjacent) and shared script paths, but
is purely additive safety — no schema, no FOCAS, no offset math. Verified by full-suite green.

---

## Safeguard #3 — Reaffirm the R1 migration guard (verify only, no code)

- Run `tests/test_alembic_guard.py` + `tests/test_migrations.py` — confirm the 50 guard
  tests pass (layered R1 defense in `migrations/_guard.py` active).
- Confirm dev DB `alembic current` = `0003` and `tracker` schema absent (already true this session).
- Everything stays on dev 5433 until an explicit, backed-up, confirmed cutover.

No change to guard code. This is a standing-verification step.

---

## Safeguard #4 — Backup + restore drill (NEW runbook, tested on dev)

**New `docs/runbooks/backup-restore.md`** documenting and *demonstrating*:
- `pg_dump` of `tooling.*` + `shared.*` (schema-scoped, never `tracker`), run inside the
  container: `docker compose -f docker-compose.dev.yml exec -T postgres pg_dump -U pottracker_dev -d pottracker --schema=tooling --schema=shared -Fc -f /tmp/lance_backup.dump`.
- Restore into a **scratch DB** in the same dev container (`pottracker_restore_test`),
  then assert `alembic current` head + per-table row counts match source, then `DROP DATABASE`.
- Copy the dump out to `reports/` for the record.

**Tested this phase against dev** so the procedure is proven *before* it is ever needed
for a production migration (R15 / open Phase-2 task). Prod is never touched. Fully reversible
(scratch DB dropped at the end).

---

## Safeguard #5 — Pin dependency versions (lock, reproducible installs)

`pyproject` keeps compatibility **ranges** (source of truth); add a committed **lock**
capturing exact resolved versions for reproducible installs — no surprise floats.

**Action (Phase B, after #1 completes):**
```bash
.venv/Scripts/python -m pip freeze --exclude-editable > constraints.txt
```
- Commit `constraints.txt`. Document `pip install -e '.[api,dev]' -c constraints.txt`
  as the reproducible-install command in README + this spec.
- **No new tooling** (`pip freeze` is built-in — avoids adding pip-tools/uv, which would
  themselves be installs to argue about).

**Frontend lock:** `bun install` produces `bun.lockb`, committed (see #7).

---

## Safeguard #6 — Production GRANT lockdown (prepared + verified on dev)

Turn the R1 GRANT template (docs/07) into a real, idempotent, **parameterized** script
and *prove it works* against the dev DB without touching prod.

**New `scripts/sql/prod_grant_lockdown.sql`** — the docs/07 R1 template as runnable SQL:
role gets `USAGE, CREATE` on `tooling`+`shared` and default-privilege `ALL ON TABLES`;
`REVOKE ALL` on `tracker` schema/tables/sequences; `SELECT` granted only on named
`tracker.*` views. Idempotent.

**Verification drill (dev, fully rolled back):** in one transaction on the dev DB —
`CREATE ROLE lance_tooling_probe`, simulate a `tracker` schema + a table + a view,
apply the grants, then assert via `has_schema_privilege` / `has_table_privilege`:
- CREATE on `tooling` + `shared` = true
- any privilege on `tracker.<table>` = false
- SELECT on `tracker.<view>` = true
— then **`ROLLBACK`** the whole thing. Nothing persists: no role, no `tracker` schema
left behind (R1 invariant preserved), dev DB pristine.

**⚠ Needs explicit consent:** this drill *temporarily* creates a simulated `tracker`
schema on the dev DB inside a transaction that is rolled back — it is never committed and
the real `_guard` runtime listener is not in this psql path. Flagging per "no assumed
intent." If you'd rather, I can run the verification against a throwaway *separate* DB
instead of the dev DB.

---

## Safeguard #7 — Frontend install (apps/tooling/web) — needs GO + a scope decision

Isolated from Postgres + Python by construction (JS toolchain, own lockfile).

- **Package manager: bun** (1.3.12 present; global store + hardlinks, no heavy duplicated
  `node_modules`). pnpm is absent — using bun avoids installing another PM.
- **Stack:** Vite + React + TypeScript + Tailwind + **shadcn/ui**, pinned exact versions,
  `bun.lockb` committed.
- **Scope question (see Approval gate):** this is ~175 packages and is really Phase 4
  foundation work. Options: (a) full scaffold + Tailwind + shadcn/ui init now, (b) toolchain
  install + pinned `package.json` only (no components yet), (c) defer entirely to Phase 4.

---

## Sequencing

**Phase A — safeguards, NO installs (uses the existing `.venv`, already has pytest):**
1. `#2` DSN guard: `shared/dsn_guard.py` + wire 5 entry points + `tests/test_dsn_guard.py`.
2. `#3` Reaffirm R1: run guard + migration test suites; confirm dev head 0003, tracker absent.
3. `#4` Backup/restore runbook + run the drill on dev.
4. `#6` GRANT script + run the rolled-back verification drill on dev (pending consent).
5. Full test suite green.

**Phase B — installs, NEEDS GO:**
6. `#1` add `httpx` to `[dev]`; `pip install -e '.[api,dev]'` into `.venv`; `pip check`.
7. `#5` `pip freeze -> constraints.txt`; document reproducible install.
8. `#7` frontend install per the chosen scope; commit `bun.lockb`.
9. Full test suite green from inside `.venv` (now incl. API tests).

**Phase C — resume backend items (from SESSION_NOTES):**
- Pagination: envelope `/assignments` + `/audit` to match `/tools` (`{items,total,limit,offset}`) — recommended.
- `/health` auth: keep public, fix docs/04 wording — recommended.
- docs/04 doc-drift fixes (auth endpoints, skip_probe, probe_h_register, 400→422, etc.).
- Commit + run the `tool_type` seed against dev.
- Add a CI `mypy` job (+ run API integration tests in CI).

---

## Reversibility summary

| Safeguard | Touches | Reversible? |
|---|---|---|
| #1 venv complete | filesystem (.venv) | yes — delete/recreate |
| #2 DSN guard | new module + additive wiring | yes — pure additive code |
| #3 R1 reaffirm | nothing (verify only) | n/a |
| #4 backup drill | dev DB scratch db (dropped) | yes — scratch dropped |
| #5 lock | new committed file | yes |
| #6 GRANT drill | dev DB in a rolled-back txn | yes — rolled back |
| #7 frontend | apps/tooling/web filesystem | yes — delete node_modules/lock |

**Prod DB: never touched anywhere in this plan.**

---

## Approval gate

Blocking on GO before Phase B installs (`#1` completion, `#7` frontend). Also need:
1. Consent for the `#6` GRANT drill approach (rolled-back tracker sim on dev, vs a separate throwaway DB).
2. Frontend scope for `#7` (full scaffold+shadcn / toolchain-only / defer to Phase 4).
</content>
</invoke>
