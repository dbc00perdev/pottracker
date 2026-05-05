# lance-tooling

Tool library + offset registry management system for Lance Industries CNC mills.

External source of truth for tool identity, pot assignments, and FANUC offset registers, with two-way FOCAS sync to the Viper LG-1000AP and AG100 controls.

---

## Status

**Spec phase.** No code yet. This repo currently holds architecture, data model, and phase planning documents only.

## Why

Manual handwritten tool tables drift. Operators forget pots. Offsets get clobbered. T-numbers get reused. Identical tools end up with different H-numbers across machines. Every drift event = potential scrap event.

This system makes the external library authoritative for **identity** (what is this tool, what does it cut, where does it live) and bidirectionally synced with FANUC for **offset values** (length geom, length wear, diameter geom, diameter wear, tool life counters).

## Scope (v1)

- Two machines: Viper LG-1000AP, AG100 (assumed FOCAS-live, AG100 unverified)
- 23 physical pot stations + 1 fixed probe pot per machine
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
| `tasks/lessons.md` | Captured corrections (empty at start) |

## Stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy, Alembic, `pyfocas` (or vendored Fanuc DLL wrapper)
- DB: PostgreSQL (shared instance with Lance CNC Tracker, separate `tooling` schema)
- Frontend: React + Vite, TypeScript, Tailwind
- Deployment: Docker Compose alongside tracker, single nginx, separate FastAPI worker
- Auth: shared with tracker

## Hosting

Deployed on the same host as Lance CNC Tracker, modular separation, schema isolation. See `docs/07-risks.md` for coupling risks and mitigations.

## Critical safety note

This system writes to FANUC offset tables. A bad write = scrapped parts, broken tools, or a crashed machine. Every write path requires operator confirmation in the UI. No autonomous offset writes in v1. Audit log on every change.
