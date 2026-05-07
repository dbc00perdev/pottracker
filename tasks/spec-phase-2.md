# tasks/spec-phase-2.md — Persistence + Audit

> Plan for Phase 2 of pottracker. Reviewed at start of Phase 2 work; updated as
> sub-decisions land. Phase 1 sign-off is in `tasks/spec-focas-calls.md` and
> `reports/viper-soak-60min.json`.

## Goal

Wire the live FOCAS snapshot stream into a persistent store. Two outputs:

1. **State mirror** (`shared.focas_offset_register`, `shared.focas_pot`,
   `shared.focas_tool_life`): the latest known value per (machine_id, register)
   with a `last_polled_at` timestamp. Updated on every poll.
2. **Audit log** (`shared.audit_log`): append-only ledger of every
   *change* — offset deltas, pot reassignments, tool-life count
   resets, alarm state transitions. The auditable history we need
   when an operator says "this offset was 0.0050 mm yesterday and
   today it's 0.0040, what happened?"

This is a **read-side only** phase. No writes to FANUC, no UI yet.
Phase 6 adds the write path; Phase 3+ adds the FastAPI surface that
exposes Phase 2's data.

---

## Decisions (locked from this session)

| Decision | Choice | Reason |
|---|---|---|
| Phase 2 branch | Continue on `claude/summarize-build-eWINf` | Operator wants single-branch flow; merge to main when both phases ready |
| DB for development | Docker Postgres via `docker-compose.dev.yml` | Zero risk to Lance Tracker during dev |
| DB for production | Shared Postgres instance with `tooling_app` role + explicit GRANTs | Per CLAUDE.md architecture; R1 + DB GRANT is the safety net |
| Source-of-truth for poller | Sync soak (`focas_soak_simple.py`) for now; async Poller bug deferred to Phase 2 follow-up | 23/23 cycle soak proves sync path |

---

## Step 1 — Docker Postgres (dev)

`docker-compose.dev.yml` at repo root:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: pottracker-dev-pg
    environment:
      POSTGRES_USER: pottracker_dev
      POSTGRES_PASSWORD: dev_only_not_for_prod  # noqa
      POSTGRES_DB: pottracker
    ports: ["5433:5432"]   # 5433 to avoid collision with any host Postgres
    volumes:
      - pottracker-dev-pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pottracker_dev"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pottracker-dev-pg-data:
```

`.env.example` gets `DATABASE_URL=postgresql://pottracker_dev:dev_only_not_for_prod@localhost:5433/pottracker`.

Operator workflow:
- `docker compose -f docker-compose.dev.yml up -d` — start
- `docker compose -f docker-compose.dev.yml down` — stop (data preserved)
- `docker compose -f docker-compose.dev.yml down -v` — wipe (drops volume)

Tests use a separate ephemeral DB via pytest-postgresql or just connect to the dev DB on a random schema (`pg_temp` style). Pick whichever is simpler in tests/conftest.py.

---

## Step 2 — Cherry-pick existing migrations

`origin/claude/phase-2-persistence` has commit `c8aa19d` containing
two well-formed migrations:

- `migrations/versions/0001_shared_core.py` — `shared.machine`, `shared.user`, `shared.audit_log`
- `migrations/versions/0002_shared_focas_state.py` — `shared.focas_offset_register`, `shared.focas_pot`, `shared.focas_tool_life`

Cherry-pick both onto current branch. Audit them against:
- the verified Viper identity (`cnc_type='0'`, not `'0i'` — the `control_model` text field is fine but seed value should match real)
- the offset increment of 0.0001 mm (not the 0.001 default we initially documented)
- the actual offset register count of 400 (Memory B), not whatever was assumed

Run R1 layered defense's runtime DDL inspection during the cherry-pick to confirm
the migrations only target `tooling` and `shared`, never `tracker`.

---

## Step 3 — Production-style DB role (for prod connection string)

```sql
-- run once as superuser before deploying tooling app to production
CREATE ROLE tooling_app LOGIN PASSWORD 'rotate-me';

GRANT USAGE  ON SCHEMA shared, tooling TO tooling_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA shared, tooling TO tooling_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA shared, tooling TO tooling_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA shared, tooling GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tooling_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA shared, tooling GRANT USAGE ON SEQUENCES TO tooling_app;

-- DELIBERATELY no GRANTs on tracker — Postgres rejects DDL/DML there for this role.
```

Migrations for production are run by a separate `tooling_migrator` role with
schema-create privileges on `tooling` + `shared`, also no tracker access.

Document in `docs/runbooks/phase-2-db-setup.md` for the deploy path.

---

## Step 4 — `shared/focas/snapshot.py` (diff + persist)

### Inputs

- A `MachineSnapshot` from the poller's source (sync or async — same Pydantic model either way)
- A SQLAlchemy session (sync, since the poller is sync)
- The `machine_id` (UUID FK)

### Algorithm

For each domain (offsets, pots, tool_life, alarms):

1. Read current state row from `shared.focas_*` for that `machine_id`
2. Compare to incoming snapshot
3. For each delta:
   - UPSERT the state mirror (latest value + `last_polled_at`)
   - INSERT an `audit_log` row capturing `(before, after, delta)`
4. Commit once per snapshot (transactional consistency: a snapshot is atomic or it doesn't land)

### Diff rules per domain

| Domain | What's a "change"? | Audit reason |
|---|---|---|
| Offset register | `value_mm` differs from stored | Operator or program changed offset on the panel |
| Pot table | `t_number` for a given `pot_number` differs | Magazine indexed; tool moved |
| Tool life | `life_count` increased OR `status` transitioned | Cycle counted, or expired/replaced |
| Alarm | New alarm code appeared, or active alarm cleared | Operator visibility |

### What's NOT a change

- `last_polled_at` updates every cycle but doesn't generate audit rows on its own
- Identical re-reads (no value drift) → just update `last_polled_at`
- Status (mode, run, e-stop) flips — Phase 3 concern (event stream); Phase 2 only stores latest

---

## Step 5 — `shared/audit.py`

Thin writer: `record_audit(session, *, kind, machine_id, user_id, before, after, reason)`.

Schema (already in 0001 migration):
```
shared.audit_log:
    id BIGINT IDENTITY PK
    occurred_at TIMESTAMPTZ DEFAULT now()
    kind TEXT NOT NULL  -- 'offset_change' | 'pot_move' | 'tool_life_count' | 'alarm' | (Phase 6) 'offset_write'
    machine_id UUID FK -> shared.machine
    user_id UUID FK -> shared.user (nullable: poller-driven changes have no user)
    before JSONB
    after JSONB
    reason TEXT
```

Phase 2 generates only poller-driven rows (`user_id IS NULL`). Phase 6 will
generate operator-driven rows from the offset writer.

---

## Step 6 — Wire snapshot into the sync soak

Add `--persist` flag to `scripts/focas_soak_simple.py`:
- When set, opens a SQLAlchemy session at startup
- After each successful `read_snapshot()`, calls `snapshot.persist(session, snap, machine_id)`
- Reports persist latency separately from FOCAS read latency
- `--persist-dsn` overrides the env's `DATABASE_URL`

This makes the 24-hour soak the integration test for Phase 2.

---

## Step 7 — Tests

Unit:
- `tests/shared/focas/test_snapshot.py` — diff logic with mock session, no DB
- `tests/shared/test_audit.py` — record_audit shape

Integration (require Docker DB up):
- `tests/integration/test_persist_snapshot.py` — full path: snapshot → DB row → diff against second snapshot → audit row count expected
- Marked `@pytest.mark.integration`; CI skips by default; local + manual gate

Migration:
- `tests/test_alembic_migrations.py` — run `alembic upgrade head` on a clean Docker DB, verify tables exist, verify R1 defense rejected a hand-crafted bad migration

---

## Step 8 — 24-hour Viper soak with persistence

Final operational deliverable:
- Run `focas_soak_simple.py --persist --duration-minutes 1440 --interval-seconds 60` overnight
- Pass criteria: success_rate ≥ 0.99, no DB errors, audit_log row count > 0 (something changed during the day), no memory growth
- Artifact: `reports/viper-soak-24h-with-persistence.json` + `reports/viper-soak-24h-audit-extract.csv` (audit_log dump for the soak window)

---

## Risks & open questions for Phase 2

| ID | Item | Mitigation |
|---|---|---|
| P2-R1 | Audit log explosion if poll interval is too tight + values drift constantly | Floor at 60s polling; threshold "minimum delta to record" if needed |
| P2-R2 | Connection pool starvation if multiple pollers + API share one pool | Set explicit pool size; monitor `pg_stat_activity` |
| P2-R3 | Migration order matters; missing R1 guard could hit tracker | R1 is in place from Phase 1; migration tests assert it |
| P2-O1 | Async Poller exits after 2-3 cycles (deferred from Phase 1) | Investigate during Phase 2; sync soak validates persistence regardless |
| P2-O2 | Backup/restore drill | Document `pg_dump -n shared -n tooling` flow; test on Docker DB |

---

## Out of scope for Phase 2

- FastAPI endpoints (Phase 3)
- Tool / assignment / pot-observation tables in `tooling.*` (Phase 3)
- Offset write path (Phase 6)
- UI (Phase 4+)
- Tracker integration regression test (Phase 10)

---

## Dependencies operator must install

- Docker Desktop on the Windows dev box (one-time): https://www.docker.com/products/docker-desktop/
- `pg_dump` / `pg_restore` (bundled with Docker Postgres image; no host install needed)

Everything else is already in `pyproject.toml` (`alembic`, `sqlalchemy`, `psycopg2-binary` or `psycopg`).
