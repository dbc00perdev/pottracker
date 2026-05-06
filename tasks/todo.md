# tasks/todo.md

Active work for lance-tooling. Updated as we go.

---

## Open decisions

- [ ] **Decision-1**: `pyfocas` vs vendored `Fwlib32.dll` ctypes wrapper. Triage at start of Phase 1.
- [ ] **Decision-2**: Confirm exact 30i-B FOCAS function names (offset read/write, pot/magazine read, tool life, alarm, mode). Source: FOCAS2 SDK doc, not assumption. Output: `tasks/spec-focas-calls.md`.
- [ ] **Decision-3**: Verify offset register layout on Vipers — which numbers are H_geom vs H_wear vs D_geom vs D_wear. Default 30i-M layout assumed; Lance customizations possible.
- [ ] **Decision-4**: Confirm probe T-number on Viper. Default assumed T99; verify with macro or controls vendor.
- [ ] **Decision-5**: AG100 IP + FOCAS port test. Cannot enter Phase 8 without this.
- [ ] **Decision-6**: WebSocket vs polling for live UI updates. Default: 5s polling for v1, defer WS to v1.1.
- [ ] **Decision-7**: Auth integration with tracker — does tracker have an existing user table to share, or do we provision fresh? Affects Phase 3 Alembic plan.
- [ ] **Decision-8**: Backup retention policy for `shared.audit_log`. Default: keep all, revisit post-Phase 10.
- [ ] **Decision-9**: Operator phone restriction — should phone be allowed for write confirmations, or tablet/desktop only? Default: tablet/desktop only for v1, revisit post-feedback.

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

- [ ] Library decision (Decision-1) — **BLOCKER for client.py / poller.py**
- [ ] Verify FOCAS function names against 30i-B doc (Decision-2, Decision-3, Decision-4) — **BLOCKER**, fill rows in `tasks/spec-focas-calls.md`
- [ ] `shared/focas/client.py` with read methods — blocked on Decision-1, Decision-2
- [x] `shared/focas/models.py` with Pydantic types
- [ ] `shared/focas/poller.py` async loop — blocked on client.py
- [x] `shared/focas/mock.py` with canned scenarios (labeled per CLAUDE.md anti-pattern #3)
- [x] Unit tests against mock + models (24 passing)
- [x] Repo skeleton, root `pyproject.toml`, `.gitignore`
- [x] Alembic env with tracker-isolation guard (R1) + 9 unit tests for the guard
- [x] CI workflow (ruff + pytest), tracker-regression job placeholder (disabled)
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
- [ ] Assignments endpoints (no offset writes yet)
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
