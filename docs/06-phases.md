# 06 — Build Phases

Phased delivery to land usable value early, prove FOCAS integration before building UI on top, and keep risk bounded. Each phase has gate criteria — don't proceed until met.

---

## Phase 0 — Spec lock

**Goal**: Architecture, data model, FOCAS contract, API surface frozen for v1.

Deliverables:
- `docs/01-architecture.md` ✓
- `docs/02-data-model.md` ✓
- `docs/03-focas-integration.md` ✓
- `docs/04-api.md` ✓
- `docs/05-ui-flows.md` ✓
- `docs/06-phases.md` (this file) ✓
- `docs/07-risks.md` ✓
- `docs/08-glossary.md` ✓
- Repo initialized, CI scaffolding, branch protection
- Decisions logged in `tasks/todo.md`

Gate: dbc00per signs off on each doc, or open issues against them. No code until this phase closes.

---

## Phase 1 — FOCAS read foundation

**Goal**: Confirm we can read everything we need from the Viper, reliably, on a cadence.

Deliverables:
- `shared/focas/client.py` — connection wrapper (read-only methods)
- `shared/focas/models.py` — Pydantic models for FOCAS responses
- `shared/focas/poller.py` — async polling loop, single machine
- `shared/focas/mock.py` — mock harness with canned scenarios
- Unit tests against mock (covers diff detection, circuit breaker, reconnect)
- Integration test — script that connects to real Viper, reads everything, dumps to JSON, verifies expected ranges

Gate criteria:
- Successful FOCAS read of: full offset table (all 4 register types), pot table, tool life data, alarms, current T#, machine mode
- All read calls verified against actual 30i-B FOCAS function names (not assumed) — documented in `tasks/spec-focas-calls.md`
- Poller runs continuously for 60 minutes against Viper without leaks or stale data
- Circuit breaker trips correctly when Viper unreachable, recovers when restored
- All reads measured for latency, p50/p95/p99 logged

**No app yet. No DB writes. No UI. Just the layer that talks to FANUC.**

If FOCAS doesn't behave as documented, this phase is where we find out, while it's cheap to pivot.

---

## Phase 2 — Persistence + audit

**Goal**: FOCAS reads land in PostgreSQL with diff detection and audit logging.

Deliverables:
- Alembic migrations for `shared.machine`, `shared.user`, `shared.audit_log`, `shared.focas_*` tables
- `shared/focas/snapshot.py` — diff and persist logic
- `shared/audit.py` — audit log writer
- Unit tests
- Integration: poller writes to DB, snapshots persist, diffs trigger audit entries
- Database seeded with Viper machine row

Gate criteria:
- 24 hours of continuous polling against Viper, all changes captured in DB
- Audit log entries created for every diff
- DB schema reviewed for correctness (no surprises in cardinality or types)
- Backup/restore procedure documented

---

## Phase 3 — Tooling schema + minimal API

**Goal**: Tool library exists. CRUD endpoints work. No FOCAS writes yet.

Deliverables:
- Alembic migrations for `tooling.*` schema
- `apps/tooling/api/` — FastAPI app with tools, tool-types, assignments, machines endpoints (read + create/update for tools and assignments)
- Authentication wired (JWT, role-based)
- Unit + integration tests

Gate criteria:
- `POST /api/tooling/tools` creates record, retrieves cleanly
- Assignment creation enforces all unique constraints
- Tool capability validation works (TSC mismatch rejected)
- All endpoints documented (OpenAPI auto-generated, manually reviewed)
- Test suite > 80% coverage on this module

---

## Phase 4 — Frontend foundation

**Goal**: SPA that lets users see what's in the system.

Deliverables:
- React + Vite + TypeScript scaffold under `apps/tooling/web/`
- Tailwind, component library decisions
- Routing
- Auth flow (login, JWT storage, refresh)
- Tools list + detail pages
- Machine view: pot map (read-only), offset table (read-only), tool life
- Live updates via 5s polling (not WebSocket yet)

Gate criteria:
- Operator can log in, browse tools, browse machine state
- All read flows match `docs/05-ui-flows.md` for the read-only paths
- Responsive on tablet
- Dashboards reflect FOCAS state within 60 seconds of underlying change

---

## Phase 5 — Assignment workflow

**Goal**: Assign tools to machines through the UI.

Deliverables:
- Frontend assignment flow per `docs/05-ui-flows.md`
- Pending review queue UI
- Tool capability checks visible in UI
- Confirm/retire actions

Gate criteria:
- Setter user can assign a tool, system enters `pending_review` state
- After Viper probe runs, FOCAS poll picks up new offsets, UI shows pending review notification within 60s
- Operator can confirm, state transitions to `confirmed`
- Audit log captures every assignment + confirmation event
- End-to-end test: create tool → assign → confirm → retire, all reflected in DB and audit log

---

## Phase 6 — FOCAS write path

**Goal**: Operator can push offset values from app to machine.

This is the highest-risk phase. Maximum care.

Deliverables:
- `shared/focas/writer.py` — write methods, mode lockout, read-after-write verification
- `tooling.offset_write_request` table + migrations
- API: `POST /api/tooling/offsets/write`, `confirm`, `cancel`, `GET /writes`
- Frontend: write request flow per `docs/05-ui-flows.md`
- Two-stage confirmation enforced
- Mode lockout enforced (no writes during AUTO running)
- Read-after-write verification mandatory

Gate criteria:
- 50 successful write+verify cycles against Viper test register (use a register not currently in production use)
- 5 deliberate failure scenarios tested: machine unreachable, mode lockout, value drift, write rejected by control, verification mismatch
- Operator confirmation flow tested with 3 different users
- All writes audit-logged with user, reason, before/after, success/failure
- Documented runbook for offset write failures

**Production gate**: dbc00per personally validates one full cycle on a real tool before opening to operators.

---

## Phase 7 — G10 export

**Goal**: Useful side feature — operators can dump the offset table as a FANUC G10 program for backup, sharing, machine cloning.

Deliverables:
- `apps/tooling/api/g10.py` — G10 generator, G10 parser
- API endpoints
- Frontend: download button, format options
- Round-trip test: export, parse, compare to source — must be lossless

Gate criteria:
- Generated G10 program runs cleanly on a Fanuc simulator
- Parse output matches generated input bit-for-bit (within numeric precision)
- Operator can export Viper offsets, store backup file

---

## Phase 8 — AG100 onboarding

**Goal**: Add second machine to the live system.

Deliverables:
- AG100 IP confirmed, FOCAS port test passed
- Machine config row added
- Full poll cycle verified
- All UI flows tested against AG100
- Through-spindle-coolant capability flag verified (Viper has TSC, AG100 does not — confirm)
- Tool reuse across machines tested (assign same tool to both, different H/D registers)

Gate criteria:
- AG100 polling 24h continuous without errors
- Tool assignment + write flows work on AG100
- Cross-machine tool reuse tested

---

## Phase 9 — G10 import + bulk operations

**Goal**: Migration path for "we already have a manual table to import."

Deliverables:
- G10 file upload + parse
- Diff view in UI
- Bulk write request (multiple register writes from one operator action)
- Bulk confirmation modal

Gate criteria:
- Can import dbc00per's existing handwritten table (after manual conversion to G10) and see it reflected
- Bulk confirm requires explicit acknowledgment
- All bulk-applied writes audit-logged individually

---

## Phase 10 — Production cutover

**Goal**: Move from dev/staging environment to production deployment alongside Lance CNC Tracker.

Deliverables:
- Docker Compose updated with tooling worker
- nginx config updated
- Production DB migrations applied
- Backup strategy verified (daily PG dumps include `tooling.*` and `shared.*`)
- Monitoring / alerting hooked up (FOCAS connection drops, write failures, poll lag)
- Operator training session
- Runbook for common failures

Gate criteria:
- 1 week shadow operation: app polls, audits, but operators continue manual workflow
- 1 week limited operation: operators use app for assignments only
- 2 weeks full operation: writes enabled, tracker integrity verified after each release
- No tracker regressions detected in monitoring

---

## Out of v1 (explicitly deferred)

- Tool regrind tracking (`docs/02-data-model.md` reserves fields)
- Inventory / stocking levels
- Cost accounting
- Label printing integration
- Barcode/QR scanning
- Mobile-native app
- Offline presetter integration (architecture supports, no UI/connector built)
- WebSocket live updates (5s polling sufficient for v1)
- Multi-shop / multi-site
- API for third-party integration
- Tool life write-back to FANUC
- Per-tool feeds & speeds library
- CAM system integration

---

## Risk-driven phase ordering

Why this order matters:

- **Phase 1 first** because if FOCAS reads don't work, the whole project is in trouble. Find out before building UI.
- **Phase 6 (writes) deep into the schedule** because the riskiest operation should land last, after everything else is stable. Operators should trust the app's reads before they trust its writes.
- **AG100 onboarding (Phase 8)** is its own phase, not bundled with multi-machine support, because we don't yet know if AG100's FOCAS is licensed and we shouldn't pretend we do.
- **G10 export (Phase 7)** before G10 import (Phase 9) because export is read-only and easier; import involves staging + writes.
