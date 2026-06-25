# lance-tooling (pottracker)

[![ci](https://github.com/dbc00perdev/pottracker/actions/workflows/ci.yml/badge.svg)](https://github.com/dbc00perdev/pottracker/actions/workflows/ci.yml)

External source of truth for tool identity, pot assignments, and FANUC offset registers — two-way synced with the FOCAS API to the Mighty Viper LG-1000AP (FANUC 0i-MF) and (pending) the AG100.

---

## Status

**Phase 1 (FOCAS read foundation) signed off and validated on live hardware. Phase 2 (persistence + audit) in progress.**

| Phase | State | Artifact |
|---|---|---|
| 0 — Spec lock | ✅ done | `docs/01–08`, `tasks/spec-focas-calls.md` |
| 1 — FOCAS read foundation | ✅ done | `reports/viper-smoke-o1-final.json`, `reports/viper-soak-24h.json` (216/216 clean cycles) |
| 2 — Persistence + audit | 🚧 in progress | `tasks/spec-phase-2.md`, migrations 0001/0002 cherry-picked, Docker dev DB live |
| 3 — Tooling schema + minimal API | queued | — |
| 4 — Frontend foundation | queued | — |
| 5 — Assignment workflow | queued | — |
| 6 — FOCAS write path | queued (high-stakes — first writes to FANUC offset tables) | — |
| 7 — G10 export | queued | — |
| 8 — AG100 onboarding | queued | — |
| 9 — G10 import + bulk operations | queued | — |
| 10 — Production cutover | queued | — |

204+ tests passing. Phase 1 read path is production-quality under sustained polling — verified end-to-end against the live Viper.

---

## Why

Manual handwritten tool tables drift. Operators forget pots. Offsets get clobbered. T-numbers get reused. Identical tools end up with different H-numbers across machines. Every drift event is a potential scrap event.

This system makes the external library authoritative for **identity** (what this tool is, what it cuts, where it lives) and bidirectionally synced with FANUC for **offset values** (length geom, length wear, diameter geom, diameter wear, tool life counters).

---

## Verified on live hardware (Mighty Viper LG-1000AP, FANUC 0i-MF)

Phase 1's integration smoke + soak surfaced many "real machine" findings that the FOCAS docs alone won't tell you. Per-machine reality captured in `tasks/spec-focas-calls.md` and `tasks/lessons.md`. Highlights:

| Finding | Detail |
|---|---|
| Control identity | `cnc_type=' 0'` (space + 0, not `'0i'`), `mt_type=' M'`, `series='D4F1'` — strip both ends for comparison |
| Offset memory model | `ofs_type=2` (Memory B), 400 registers populated, 3 readable banks per register |
| Offset increment | **0.0001 mm/count** — NOT the FANUC-standard 0.001. Cross-verified via panel reading H50 = 7.4050 mm |
| H/D type-code mapping | This control swaps H/D from documented semantics: `type=1→D_GEOM`, `type=2→H_WEAR`, `type=3→H_GEOM`. Confirmed against register 396 panel cross-check. |
| D_WEAR FOCAS-unreadable | Panel stores and displays it, but `cnc_rdtofs(type=4)` returns `EW_ATTRIB` — this license tier doesn't expose D_WEAR. UI must mark "N/A — panel only" |
| Magazine option | `cnc_rdmagazine` returns `EW_NOOPT` (option not present). `read_pots()` gracefully returns `()` rather than raising. |
| Active tool (HEAD) | `cnc_modal` does NOT expose live T on this control. Tracked instead via PMC R-area bytes: **R327 = HEAD** (in spindle), **R325 = NEXT** (to be called). OEM-specific binding to Mighty Viper PMC ladder. |
| Scratch register pitfall | R321 is a fast-mutating scratch register the ladder uses while reading R325/R327; two consecutive spot-reads return different values. Do NOT bind it — bind the stable R325/R327. |
| DLL loading on Windows | FS30i front-end DLL internally `LoadLibrary`s siblings using plain (non-Ex) calls. `os.add_dll_directory` alone is insufficient — also need `PATH` prepend + explicit preload of every sibling DLL by absolute path. |
| FOCAS handle thread affinity | Windows FOCAS handles are thread-affined; an async poller MUST funnel every call through a **dedicated single-worker `ThreadPoolExecutor`**. `asyncio.to_thread` is the wrong primitive (multi-worker default pool). |
| Operational Phase 1 soak | 216 cycles successful, latency p50=34.2s p95=36.0s, zero drift, zero failures across 3.5 hours. Real shop activity captured (tool transitions, MEM→MDI mode flip). |

---

## Scope (v1)

- Two machines: Viper LG-1000AP (FANUC 0i-MF, **confirmed live at 10.1.10.58:8193**), AG100 (FOCAS pending verification — Decision-5)
- 24 physical pot stations per machine (Viper: 23 standard + 1 fixed probe at T50/H50 per Decision-4)
- 400 offset registers
- Random-access ATC modeled correctly (T# bound to identity, pot tracked separately, head/next via PMC binding)
- On-machine toolsetter workflow (no offline presetter v1; presetter-ready)
- Two-way FOCAS sync, sync (and eventually async) polling, operator-confirmed writes (Phase 6)

## Scope (out)

- Offline presetter integration (Zoller/Speroni/Parlec) — hooks reserved, not built
- Full shop-wide rollout beyond Viper + AG100 — design supports it, deployment doesn't yet
- Tool regrind / sharpening lifecycle tracking — v2
- Inventory / consumables / stocking levels — v2
- Cost accounting per tool — v2

---

## Documents

| Doc | Purpose |
|---|---|
| `CLAUDE.md` | Operating directives for Claude Code CLI on this project |
| `docs/01-architecture.md` | System overview, deployment model, FOCAS layer, tracker integration risk |
| `docs/02-data-model.md` | Entities, relationships, PG schema, FANUC mapping |
| `docs/03-focas-integration.md` | FOCAS protocol use, polling strategy, sync state machine, conflict resolution |
| `docs/04-api.md` | FastAPI surface, endpoint contracts |
| `docs/05-ui-flows.md` | Operator interaction patterns, screen-by-screen |
| `docs/06-phases.md` | Build phases, gate criteria, deferred work |
| `docs/07-risks.md` | Risk register, including tracker coupling risks |
| `docs/08-glossary.md` | FANUC + machinist terms used throughout |
| `docs/runbooks/phase-1-smoke.md` | Step-by-step operator guide for the Phase 1 FOCAS smoke |
| `tasks/spec-focas-calls.md` | Verbatim FOCAS function specs from `Fwlib64.h` + verified per-machine bindings (O1–O8 resolution) |
| `tasks/spec-focas-calls.generated.md` | Raw extractor output — audit trail for the canonical spec |
| `tasks/spec-phase-2.md` | Phase 2 implementation plan: Docker DB, role + GRANTs, migrations, snapshot diff, audit writer |
| `tasks/todo.md` | Active task list across phases |
| `tasks/lessons.md` | Captured corrections (22 entries) — the per-machine reality bites |

---

## Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, vendored `Fwlib64.dll` via `ctypes` (Decision-1: `pyfocas` rejected)
- **DB**: PostgreSQL — `tooling`, `shared` schemas owned by this project; `tracker.*` is read-only and untouched
  - Dev: Docker Postgres 16 (port 5433, `docker-compose.dev.yml`)
  - Prod: shared instance with Lance Tracker, with `tooling_app` role + explicit GRANTs (no tracker access)
- **Frontend**: React + Vite, TypeScript, Tailwind (Phase 4+)
- **Deployment**: Docker Compose alongside tracker, single nginx, separate FastAPI worker process
- **Auth**: standalone for v1 (Decision-7: no tracker-auth integration). Tracker keeps its own users; tooling provisions fresh users in `shared.user`.

### Tooling scripts

| Script | Purpose |
|---|---|
| `scripts/focas_smoke.py` | Phase 1 integration smoke — one full snapshot against the Viper |
| `scripts/focas_soak_simple.py` | Sync soak harness — sustained polling validation, used for the 216-cycle Phase 1 artifact |
| `scripts/focas_soak.py` | Async poller-based soak — has a known exit-after-2-3-cycles bug, under investigation in Phase 2 |
| `scripts/debug_poller.py` | Reproduces the async poller bug against the mock harness with DEBUG logging |
| `scripts/focas_diag.py` | One-shot probe of every Phase 1 FOCAS call — used for live triage |
| `scripts/probe_modal_*.py` (v1–v9) | Per-machine binding discovery sequence that resolved O1 (HEAD/NEXT via PMC R327/R325) |
| `scripts/extract_focas_signatures.py` | Read `Fwlib64.h`, emit verbatim function signatures + struct typedefs for the spec doc (R9 mitigation) |

---

## Local development

### Prerequisites

- Python 3.11+ on the dev box (Windows for FOCAS development — DLLs are Windows-only)
- Docker Desktop running (for the dev Postgres)
- Git Bash or equivalent on Windows

### Setup

```bash
git clone https://github.com/dbc00perdev/pottracker.git
cd pottracker

# Virtual environment (mandatory — keeps pottracker's pinned deps from
# leaking to system / user-site Python and breaking other projects)
python -m venv .venv
source .venv/Scripts/activate    # Git Bash on Windows
                                 # (or .venv/bin/activate on Linux/Mac)
pip install -e '.[api,dev]'
pre-commit install

# Environment
cp .env.example .env             # edit values; .env is git-ignored

# Dev database
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps     # confirm (healthy)

# Apply migrations to the dev DB
set -a; . ./.env; set +a
alembic upgrade head

# Tests + lint
pytest -q
ruff check .
ruff format --check .
```

### FOCAS development (Windows only)

```bash
# Confirms the FOCAS link works against the live Viper
python scripts/focas_smoke.py \
    --ip 10.1.10.58 \
    --machine-id viper-lg-1000ap \
    --output reports/local-smoke.json

# Quick PMC head/next spot-read
python scripts/probe_modal_v9.py

# Sustained polling validation (defaults: 60s interval, 60min duration)
python scripts/focas_soak_simple.py \
    --ip 10.1.10.58 \
    --machine-id viper-lg-1000ap \
    --output reports/local-soak.json
```

`Fwlib64.dll` and siblings (`fwlibe64.dll`, `fwlib30i64.dll`) must live in the directory pointed to by `FOCAS_DLL_DIR` (set in `.env`). Mocked development on Linux is supported via `FOCAS_MODE=mock`.

---

## Hosting

Deployed on the same host as Lance CNC Tracker, modular separation, schema isolation. See `docs/07-risks.md` for coupling risks and mitigations.

The R1 layered-defense pattern (runtime DDL inspection + search-path lockdown + autogenerate guard + DB-level GRANT) keeps tooling migrations from touching `tracker.*` schemas even if migration code has bugs.

---

## Operational artifacts

Captured during Phase 1 sign-off, retained as historical baseline for Phase 2:

| File | What |
|---|---|
| `reports/viper-smoke-o1-final.json` | Final smoke run with HEAD/NEXT populated via PMC binding |
| `reports/viper-soak-24h.json` | 216-cycle sustained-polling soak (3.5h, zero failures, latency p50 34.2s) |
| `reports/viper-smoke-20260506-*.json` | Earlier smoke runs during integration debug (pre-O1 binding) |
| `before.json`, `after.json` | PMC snapshot pair that diagnosed the O1 binding via byte-level diff (`probe_modal_v7`) |

---

## Critical safety note

**This system writes to FANUC offset tables on production CNC machines.** A bad write = scrapped parts, broken tools, or a crashed machine. Every write path requires operator confirmation in the UI. **No autonomous offset writes in v1.** Audit log on every change. The write path lives in Phase 6 — and does not exist yet.

When in doubt about a write, the code MUST prompt the operator. Never assume consent.
