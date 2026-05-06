# lance-tooling

[![ci](https://github.com/dbc00perdev/pottracker/actions/workflows/ci.yml/badge.svg)](https://github.com/dbc00perdev/pottracker/actions/workflows/ci.yml)

Tool library + offset registry management system for Lance Industries CNC mills.

External source of truth for tool identity, pot assignments, and FANUC offset registers, with two-way FOCAS sync to the Mighty Viper LG-1000AP (FANUC 0i-MF) and the AG100 (pending FOCAS verification).

---

## Status

**Phase 0 (spec lock) complete. Phase 1 prep landed.** Currently awaiting sign-off on `tasks/spec-focas-calls.md` before `shared/focas/client.py` is implemented.

| Layer | State |
|---|---|
| Architecture / data model / FOCAS integration / API / UI / phases / risks / glossary docs | drafted, decisions closed (D1, D4, D6, D7, D8, D9), D2 ready for sign-off |
| Repo skeleton (`apps/tooling/`, `shared/focas/`, `migrations/`) | scaffolded |
| `shared/focas/models.py` Pydantic models | ✅ |
| `shared/focas/mock.py` labeled mock harness + canonical scenarios | ✅ |
| `shared/focas/client.py` ctypes wrapper for `Fwlib64.dll` | **blocked on Decision-2 sign-off** |
| `shared/focas/poller.py` async polling loop | blocked on `client.py` |
| Alembic env with R1 tracker-isolation guard | ✅ |
| CI (ruff + pytest) | ✅ |
| Pre-commit hooks (ruff + ruff-format pinned to CI version) | ✅ |
| Tests | 47 passing |

See `tasks/todo.md` for the live task list and `tasks/lessons.md` for captured corrections.

## Why

Manual handwritten tool tables drift. Operators forget pots. Offsets get clobbered. T-numbers get reused. Identical tools end up with different H-numbers across machines. Every drift event = potential scrap event.

This system makes the external library authoritative for **identity** (what is this tool, what does it cut, where does it live) and bidirectionally synced with FANUC for **offset values** (length geom, length wear, diameter geom, diameter wear, tool life counters).

## Scope (v1)

- Two machines: Viper LG-1000AP (FANUC 0i-MF, confirmed live at 10.1.10.58:8193), AG100 (FOCAS pending verification — Decision-5)
- 23 physical pot stations + 1 fixed probe pot per machine. Probe locked at T50 / H50 on the Viper (Decision-4).
- 400 offset registers, 98 pot registrations on FANUC
- Random-access ATC modeled correctly (T# bound to identity, pot tracked separately)
- On-machine toolsetter workflow (no offline presetter v1; presetter-ready)
- Two-way FOCAS sync, Python poller, operator-confirmed writes

## Scope (out)

- Offline presetter integration (Zoller/Speroni/Parlec) — hooks reserved, not built
- Full shop-wide rollout beyond Viper + AG100 — design supports it, deployment doesn't
- Tool regrind / sharpening lifecycle tracking — v2
- Inventory / consumables / stocking levels — v2
- Cost accounting per tool — v2

## Documents

| Doc | Purpose |
|---|---|
| `docs/01-architecture.md` | System overview, deployment model, FOCAS layer, tracker integration risk |
| `docs/02-data-model.md` | Entities, relationships, PG schema, FANUC mapping |
| `docs/03-focas-integration.md` | FOCAS protocol use, polling strategy, sync state machine, conflict resolution |
| `docs/04-api.md` | FastAPI surface, endpoint contracts |
| `docs/05-ui-flows.md` | Operator interaction patterns, screen-by-screen |
| `docs/06-phases.md` | Build phases, gate criteria, deferred work |
| `docs/07-risks.md` | Risk register, including tracker coupling risks |
| `docs/08-glossary.md` | FANUC + machinist terms used throughout |
| `CLAUDE.md` | Operating directives for Claude Code CLI on this project |
| `tasks/todo.md` | Active task list |
| `tasks/lessons.md` | Captured corrections |
| `tasks/spec-focas-calls.md` | Verbatim FOCAS function specs from `Fwlib64.h` (Decision-2 output, gates `client.py`) |
| `tasks/spec-focas-calls.generated.md` | Raw extractor output, audit trail for the canonical spec |
| `docs/runbooks/phase-1-smoke.md` | Step-by-step operator guide for running the Phase 1 FOCAS smoke against the Viper |

## Stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, vendored `Fwlib64.dll` via ctypes (Decision-1: `pyfocas` rejected)
- DB: PostgreSQL — `tooling`, `shared` schemas owned by this project; `tracker.*` is read-only and untouched
- Frontend: React + Vite, TypeScript, Tailwind
- Deployment: Docker Compose alongside tracker, single nginx, separate FastAPI worker
- Auth: standalone for v1 (Decision-7: no tracker-auth integration). Tracker keeps its own users; tooling provisions fresh users in `shared.user`.

## Local development

```bash
git clone https://github.com/dbc00perdev/pottracker.git
cd pottracker
python -m venv .venv && source .venv/bin/activate  # or .venv/Scripts/activate on Windows
pip install -e '.[api,dev]'
pre-commit install
cp .env.example .env  # edit values
pytest -q
ruff check .
```

`.env` is git-ignored. Production secrets are deployment-environment-injected, never committed. See `.env.example` for the variable surface.

## Hosting

Deployed on the same host as Lance CNC Tracker, modular separation, schema isolation. See `docs/07-risks.md` for coupling risks and mitigations.

## Critical safety note

This system writes to FANUC offset tables on production CNC machines. A bad write = scrapped parts, broken tools, or a crashed machine. Every write path requires operator confirmation in the UI. No autonomous offset writes in v1. Audit log on every change. The `shared/focas/writer` module does not exist yet and will not until Phase 6.
