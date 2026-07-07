# tasks/todo.md

Active work for lance-tooling. Updated as we go.

---

## Open decisions

- [x] **Decision-1** — CLOSED: vendored Fanuc DLL via ctypes. SDK installed at `C:\Fanuc\FwLib64-runtime\` (`Fwlib64.dll` front-end, `fwlibe64.dll` TCP/IP, `fwlib30i64.dll` processing for FS30i family incl. 0i-MF, `Fwlib64.h` header). `pyfocas` rejected — coverage and maintenance unclear; direct ctypes gives full surface and matches the SDK we've already paid for.
- [x] **Decision-2** — CLOSED: 20/20 functions verified in `Fwlib64.h`, merged into `tasks/spec-focas-calls.md` (signed off). O1–O8 deferred to integration-test deliverables. `client.py` unblocked.
- [ ] **Decision-3** — DEFERRED to runtime introspection: offset register layout (H_geom / H_wear / D_geom / D_wear band mapping) is read from the control via `cnc_rdtofsinfo` instead of being statically assumed. Non-blocking for Phase 1 prep.
- [x] **Decision-4** — CLOSED: probe locked at **T50, H50** on Viper LG-1000AP. Pot location TBD (read at runtime, treated as observed not commanded per R10). API + UI must reject any assignment to T50 / H50.
- [ ] **Decision-5** — DEFERRED to Phase 8: AG100 IP + FOCAS port test. Non-blocking for Viper-only v1.
- [x] **Decision-6** — CLOSED: 5s polling for live UI updates in v1. WebSocket deferred to v1.1.
- [x] **Decision-7** — CLOSED: **no tracker-auth integration in v1**. Provision fresh users in `shared.user`. Tracker keeps its own user table; tooling does not read or write to it. R5 (shared-auth coupling) is materially reduced — JWT payload schema is owned by tooling alone in v1. Cross-app auth is a v2 question.
- [x] **Decision-8** — CLOSED: keep all `shared.audit_log` rows. Retention revisited post-Phase 10.
- [x] **Decision-9** — CLOSED: write confirmations restricted to tablet/desktop in v1. Phone allowed for read-only views. Revisit after operator feedback.

---

## Phase 0 — Spec lock

- [x] `docs/01-architecture.md` drafted
- [x] `docs/02-data-model.md` drafted
- [x] `docs/03-focas-integration.md` drafted
- [x] `docs/04-api.md` drafted
- [x] `docs/05-ui-flows.md` drafted
- [x] `docs/06-phases.md` drafted
- [x] `docs/07-risks.md` drafted
- [x] `docs/08-glossary.md` drafted
- [x] `CLAUDE.md` refactored for this project
- [x] `README.md` written
- [x] `tasks/todo.md` initialized
- [ ] `tasks/lessons.md` initialized (empty)
- [ ] dbc00per review pass on each doc
- [ ] Repo initialized on GitHub
- [ ] Branch protection on `main`
- [ ] CI scaffolding (lint, test placeholder)
- [ ] Initial PR template + CODEOWNERS

---

## Phase 1 — FOCAS read foundation (in progress, library-agnostic prep landed)

- [x] Library decision (Decision-1) — vendored `Fwlib64` via ctypes
- [ ] Extract verbatim 0i-MF FOCAS signatures into `tasks/spec-focas-calls.md` from `Fwlib64.h` (Decision-2) — **BLOCKER for `client.py`**
- [x] `shared/focas/client.py` ctypes wrapper around `Fwlib64.dll` — DLL loader, decoders, FocasClient with all 8 read methods
- [x] `shared/focas/models.py` with Pydantic types
- [x] `shared/focas/errors.py` FOCAS exception hierarchy
- [x] `shared/focas/ctypes_defs.py` Structure/Union classes for 16 typedefs
- [x] `shared/focas/poller.py` async loop with circuit breaker, stale-handle reconnect, async-iterator snapshot fan-out, health/lag telemetry
- [x] `shared/focas/mock.py` with canned scenarios (labeled per CLAUDE.md anti-pattern #3)
- [x] Unit tests against mock + models (24 passing)
- [x] Repo skeleton, root `pyproject.toml`, `.gitignore`
- [x] Alembic env with tracker-isolation guard (R1) + 9 unit tests for the guard
- [x] CI workflow (ruff + pytest), tracker-regression job placeholder (disabled)
- [x] Update mock baseline probe T-number from 99 to 50 (Lance Viper reality, Decision-4)
- [x] Integration test script (`scripts/focas_smoke.py` + 15 tests against mock; runs against real Viper with `--ip`)
- [ ] **Operator action** — run smoke per `docs/runbooks/phase-1-smoke.md` §1–4 (target Viper at 10.1.10.58, attach `reports/viper-smoke-<ts>.json` to PR)
- [ ] **Operator action** — 60-minute soak per `docs/runbooks/phase-1-smoke.md` §5
- [ ] Latency p50/p95/p99 per FOCAS function — captured in the smoke report's `latency_per_call_ms` block
- [ ] Resolve open questions O1–O8 from observed Viper data (smoke report → spec doc)
- [ ] Phase 1 gate sign-off → squash-merge PR #1

---

## Phase 2 — Persistence + audit (in progress on `claude/phase-2-persistence`)

- [x] Alembic env config (target tooling + shared schemas only, never tracker) — landed Phase 1 R1 commit
- [x] Migration `0001_shared_core`: schemas + pgcrypto + `shared.machine` + `shared.user` + `shared.audit_log` (with FKs + indexes + check constraints)
- [x] Migration `0002_shared_focas_state`: `shared.focas_offset_register` + `shared.focas_pot` + `shared.focas_tool_life`
- [x] Migration tests: structural chain + offline-SQL render runs through R1 runtime guard + per-table presence asserts (17 tests)
- [x] Interface cleanup (bug b): `FocasClient.read_snapshot()` now zero-arg, stores `machine_id` at connect; natively implements `SnapshotSource`; `_ClientWrapper` + smoke mock adapter deleted; 3 tests added (223 pass, ruff clean). Async-poller exit bug (a) left OPEN → deferred to Phase 3.
- [ ] Seed data: Viper machine row — depends on smoke (need verified `series` / `version` / `cnc_type`)
- [x] `shared/db.py` — SQLAlchemy Core table registry mirroring migrations 0001/0002 (offset/pot/tool_life/audit_log)
- [x] `shared/focas/snapshot.py` diff + persist — pure diff layer (15 unit tests) + transactional persist (CASE/IS-DISTINCT-FROM UPSERT, one commit/snapshot). Alarms scoped OUT (no alarm table exists; needs migration 0003)
- [x] `shared/audit.py` writer — `record_audit()` against real audit_log columns (event_type/entity_type/entity_id/before_value/after_value/success/error)
- [x] Wire `--persist` into `scripts/focas_soak_simple.py` (Step 6) — per-cycle DB session → `persist()`, separate persist-latency reporting, DB errors recorded not fatal. `--persist-dsn`/`--machine-uuid` args. Report/stats extracted to `scripts/soak_report.py` (400 LOC cap). 9 unit tests; 247 pass, my files ruff-clean.
- [ ] Reconciliation test: assert `shared/db.py` Table defs match `alembic upgrade head` reflection (drift guard) — needs Docker DB
- [ ] Migration 0003: alarm mirror/event table (deferred — alarms not persisted in Step 4)
- [x] Apply migrations on a real Postgres + verify schema state (dev container, localhost:5433). **Surfaced + fixed 2 latent env.py bugs never caught by offline-only testing:** (1) `alembic_version` had no schema to land in on a fresh DB (search_path excludes public, allowed schemas not yet created) → pre-create schemas + `version_table_schema="shared"`; (2) online migrations silently rolled back (exec before `begin_transaction()` → non-committing no-op) → `connectable.begin()`. Both would have broken the production first-apply. Verified: head=0002, 6 tables in shared, tracker schema absent (R1 held).
- [x] Integration test `tests/integration/test_persist_snapshot.py` (2 tests, `@pytest.mark.integration`, skips w/o DATABASE_URL): persist→mirror+audit, second snapshot audits only the changed register, `last_changed_at` advances on change only, JSONB before/after correct. Passes against live dev DB.
- [ ] 24-hour Viper soak with `--persist` (operator) — Step 8, needs live Viper + the dev DB up
- [ ] Backup/restore drill (operator)

---

## Phase 3 — Tooling schema + minimal API (in progress on `claude/summarize-build-eWINf`)

Plan: `tasks/spec-phase-3.md` (approved 2026-07-06). All §2 decisions signed off.

- [x] Migration `0003_tooling_core`: `tooling.tool_type/tool/assignment/pot_observation/offset_write_request` + `shared.machine.probe_h_register` (D-C). Applied to dev DB (head=0003), downgrade round-trips, R1 held (tracker absent). Revision **0003** (D-A; alarm table → 0004+ when built)
- [x] App-side Core Tables: `shared.machine`/`shared.user` added to `shared/db.py`; `apps/tooling/api/tables.py` for `tooling.*`. Reconciliation drift test (`tests/test_tooling_tables_reconcile.py`) — closes the pending Phase-2 drift-guard task for tooling+shared
- [x] FastAPI scaffold under `apps/tooling/api/` (config/db/security/deps/errors/main + schemas/ + routers/ + services/), all files < 400 LOC
- [x] Auth wiring — JWT (jose HS256, `ver` claim R5), passlib+bcrypt, roles viewer<operator<setter<admin; `/auth/login|refresh|me`. `scripts/manage_users.py` bootstrap
- [x] Tools endpoints (GET list+filters, POST, GET/{id}, PATCH, retire, duplicate)
- [x] Tool-types endpoints (GET any, POST admin)
- [x] Assignments endpoints (list/create/get/patch/confirm/delete) — **rejects t_number=50 AND h_register=50 on Viper (Decision-4/R12)**; uniqueness among active (partial unique indexes, D-B); TSC capability check
- [x] Machines endpoints (GET/POST/PATCH) — POST TCP-probe + `skip_probe` (D-G); FOCAS state inferred from mirror freshness (D-F); + `/offsets`,`/pots`,`/tool-life` mirror reads
- [x] Audit endpoint (admin=all, others=own actions)
- [x] Health endpoint (mirror-freshness connection state)
- [x] OpenAPI reviewed — 18 routes at `/api/tooling/openapi.json`, docs at `/api/tooling/docs`
- [x] Test coverage **94%** on `apps.tooling.api` (>80% gate); 63 API tests + full suite 312 passed/1 skipped; ruff clean; live end-to-end smoke against dev DB verified probe-lock 422s
- [ ] **Operator/seed**: commit a real `shared.machine` Viper row — deferred (needs verified `probe_pot`; tests seed it in-transaction). `manage_users.py` needed to create the first admin
- [ ] Async-poller exit-after-2-3-cycles fix (separate Phase 3 task, not this API deliverable — see lessons.md)

---

## Phase C — backend resume (DONE on `claude/summarize-build-eWINf`)

Two commits: `beec5b9` (pagination + docs), `0bfe67b` (CI). All on dev DB (localhost:5433, head 0003); no installs, no DB safeguards touched.

- [x] **Pagination** — `/assignments` + `/audit` now return the `{items,total,limit,offset}` envelope like `/tools` (breaking response-shape change, confirmed by dbc00per). `/assignments` gained `limit`/`offset` (default 50, max 500). Services do COUNT + paged select; tests updated. Full API suite 55 pass.
- [x] **`/health` auth** — already public in code; docs/04 wording fixed (`any` → `none — public`).
- [x] **docs/04 doc-drift** — added the Auth section (`/auth/login|refresh|me`), `requires_climb` + server-managed `regrind_count`, create-validation `400`→`422`, `/tools/{id}` active-only history note, machine POST `probe_h_register` + `skip_probe`, removed unimplemented `with_assignment`.
- [x] **Tool-type seed run** — `python -m scripts.seed_tool_types` against dev: dry-run + apply = 10 rows verified, DSN guard fired on the dev target; rows deleted afterward to leave the DB clean for the test suite (tool=0, so safe).
- [x] **CI** — added a `mypy` job (scoped to apps/shared/migrations via `[tool.mypy] files`; jose/passlib missing-stub imports ignored, no new deps) + a `postgres:16` service on host port 5433 so `alembic upgrade head` + the integration-marked API tests run in CI. Also fixed the **pre-existing red ruff step** (RUF012/N801 on the tracked `probe_modal_v*` FOCAS scripts) via a per-file-ignore mirroring `ctypes_defs.py`. Local: `ruff check .`, `mypy`, and full suite (326 passed / 1 skipped) all green.

---

## Phase 4–10 (queued — see `docs/06-phases.md`)

Tasks broken down per phase as we approach them.

---

## Implementation backlog (out of phase ordering)

- [ ] Tracker integration regression test suite
- [ ] Production Docker Compose updates
- [ ] nginx config updates
- [ ] Monitoring / alerting setup
- [ ] Operator runbook for offset write failures
- [ ] Operator training material
- [ ] Bring `scripts/` under the mypy gate — 3 pre-existing errors excluded from the Phase-C mypy job: `focas_smoke.py:231` sorted-over-`{None}` (likely a real latent bug — the `pot_sentinels` set comprehension filters `if p.t_number is None`, yielding a set of only `None`; touches FOCAS diagnostic semantics, confirm before changing), and `debug_poller.py`/`focas_soak_simple.py` `sys.stdout.reconfigure` union-attr (mypy false positive on `TextIO` — fix with a targeted `# type: ignore[union-attr]`).

---

## Done

(empty until Phase 0 sign-off)
