# tasks/todo.md

Active work for lance-tooling. Updated as we go.

---

## Open decisions

- [x] **Decision-1** — CLOSED: vendored Fanuc DLL via ctypes. SDK installed at `C:\Fanuc\FwLib64-runtime\` (`Fwlib64.dll` front-end, `fwlibe64.dll` TCP/IP, `fwlib30i64.dll` processing for FS30i family incl. 0i-MF, `Fwlib64.h` header). `pyfocas` rejected — coverage and maintenance unclear; direct ctypes gives full surface and matches the SDK we've already paid for.
- [ ] **Decision-2** — IN PROGRESS: extract verbatim 0i-MF FOCAS signatures from `C:\Fanuc\FwLib64-runtime\Fwlib64.h` into `tasks/spec-focas-calls.md`. **BLOCKER for `client.py`.**
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
- [ ] `shared/focas/client.py` ctypes wrapper around `Fwlib64.dll` — blocked on Decision-2
- [x] `shared/focas/models.py` with Pydantic types
- [ ] `shared/focas/poller.py` async loop — blocked on client.py
- [x] `shared/focas/mock.py` with canned scenarios (labeled per CLAUDE.md anti-pattern #3)
- [x] Unit tests against mock + models (24 passing)
- [x] Repo skeleton, root `pyproject.toml`, `.gitignore`
- [x] Alembic env with tracker-isolation guard (R1) + 9 unit tests for the guard
- [x] CI workflow (ruff + pytest), tracker-regression job placeholder (disabled)
- [ ] Update mock baseline probe T-number from 99 to 50 (Lance Viper reality, Decision-4)
- [ ] Integration test against Viper (one-shot script)
- [ ] 60-minute soak test against Viper
- [ ] Document call latencies (p50/p95/p99) per FOCAS function
- [ ] Phase 1 gate sign-off

---

## Phase 2 — Persistence + audit (queued)

- [ ] Alembic env config (target tooling + shared schemas only, never tracker)
- [ ] Migration: `shared.machine`, `shared.user`, `shared.audit_log`
- [ ] Migration: `shared.focas_offset_register`, `shared.focas_pot`, `shared.focas_tool_life`
- [ ] Seed data: Viper machine row
- [ ] `shared/focas/snapshot.py` diff + persist
- [ ] `shared/audit.py` writer
- [ ] Unit tests
- [ ] 24-hour Viper soak test
- [ ] Backup/restore drill

---

## Phase 3 — Tooling schema + minimal API (queued)

- [ ] Migration: `tooling.tool_type`, `tooling.tool`, `tooling.assignment`, `tooling.pot_observation`, `tooling.offset_write_request`
- [ ] Seed data: tool_type entries
- [ ] FastAPI scaffold under `apps/tooling/api/`
- [ ] Auth wiring (JWT, role-based)
- [ ] Tools endpoints (GET, POST, PATCH, retire, duplicate)
- [ ] Tool types endpoint
- [ ] Assignments endpoints (no offset writes yet) — **must reject t_number=50 and h_register=50 on Viper LG-1000AP per Decision-4**
- [ ] Machines endpoints (GET, POST, PATCH)
- [ ] Audit endpoint
- [ ] Health endpoint
- [ ] OpenAPI doc reviewed
- [ ] Test coverage > 80%

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

---

## Done

(empty until Phase 0 sign-off)
