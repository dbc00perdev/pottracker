# 12 — Database Topology (pottracker ⟷ tracker)

**Status**: DECIDED — Decision-10 (dbc00per, 2026-07-10). Supersedes the
"shared PostgreSQL instance, separate schemas" language in `docs/01`, `docs/02`,
`CLAUDE.md`, and reframes **R1** (`docs/07`).
**Audience**: anyone deploying pottracker, writing a migration, planning backups,
or considering a tracker↔tooling data link.
**Related**: `docs/01-architecture.md`, `docs/02-data-model.md`,
`docs/07-risks.md` (R1), `docs/runbooks/backup-restore.md`, `CLAUDE.md`
(Tracker Coupling Rules).

---

## 1. The decision, in one line

pottracker's data and the Lance CNC Tracker's data live in **two physically
separate PostgreSQL databases on one native Postgres server** — never commingled
in the same database. A pottracker migration *cannot* touch tracker data because
vanilla PostgreSQL cannot reference across databases; the isolation is physical,
not merely guarded.

```
Dedicated box (native Postgres, no Docker, specced to run for years)
└── one PostgreSQL server / cluster
    ├── database: tracker_db      ← Lance CNC Tracker (JobBoss-ERP app). Untouched.
    └── database: pottracker_db   ← this project
        ├── schema tooling.*   (tools, assignments, tool types, offset_write_request, …)
        └── schema shared.*    (machine, user, audit_log, focas_* mirrors)
```

## 2. Two separation layers — do not conflate them

There are two "should these be together?" questions with **opposite** answers.

| Boundary | Answer | Why |
|---|---|---|
| `tooling.*` ⟷ `shared.*` (both inside `pottracker_db`) | **Always together, same database** | Real foreign keys cross them: `tooling.assignment → shared.machine`, `tooling.offset_write_request → shared.user`, `tooling.pot_observation → shared.machine`. A DB-level FK cannot span two databases, so these schemas are one indivisible unit. |
| `pottracker_db` ⟷ `tracker_db` | **Separate databases, never commingled** | No FK, no shared table, no cross-DB query. Physical isolation. |

The wall runs **between the two databases**, not inside pottracker. The `shared`
schema is "shared" among *pottracker's own* components (tooling today, other
pottracker modules later) — **not** shared with the tracker.

## 3. Why the old "shared instance" design existed, and why it's superseded

`docs/01`/`docs/02`/`CLAUDE.md` originally described **one database, three
schemas** (`tracker.*` + `tooling.*` + `shared.*`) with `shared.machine` /
`shared.user` as real cross-schema FKs the tracker and tooling would both use.
That model assumed **tight tracker↔tooling integration**: shared machine rows,
shared logins, tooling reading tracker jobs.

That assumption has not held:

- The live tracker **does not use FOCAS** — it is a JobBoss-ERP-sourced FastAPI
  app (memory `tracker-focas-coupling`). There is no shared FOCAS poller.
- **Decision-7** closed cross-app auth for v1 — pottracker provisions its *own*
  users in `shared.user`; the tracker keeps its own user table.
- pottracker owns its own machines and reads **nothing** from the tracker today.

With no live need for shared tables, the shared-database model bought coupling
risk (R1) for a benefit we don't use. Physical separation is the better fit for
what the system actually is. (The dev environment already runs pottracker on its
own Postgres, separate from the tracker — this decision formalizes the target
production shape to match.)

## 4. What this buys

- **R1 collapses from Critical to near-nothing.** The danger R1 tracked — a
  pottracker migration reaching a tracker table — is *impossible* across separate
  databases, not just guarded against. The migration guard, search-path lockdown,
  and GRANT template (`migrations/_guard.py`, `docs/07` R1) remain as **free
  defense-in-depth** and still enforce the internal `tooling`/`shared`-only rule,
  but they are no longer load-bearing for tracker safety.
- **One Postgres to run, patch, and back up.** One native server on the dedicated
  box; two databases inside it. No second server to babysit.
- **Independent lifecycle.** pottracker migrations, restores, and (eventually)
  point-in-time recovery never coordinate with the tracker.

## 5. The one tradeoff — and how to handle it without commingling

Separate databases means **you cannot make a database-level foreign key from a
pottracker row to a tracker row** (e.g. linking a tool assignment to a tracker
job/schedule). Today there is no such requirement.

If pottracker ever needs to **read** tracker data, do **not** merge the databases.
Three clean options, strongest isolation first:

### 5a. PostgreSQL Foreign Data Wrapper (`postgres_fdw`) — the likely path

`postgres_fdw` lets `pottracker_db` query specific tracker tables/views **as if**
they were local, over a normal SQL connection, while the data stays physically in
`tracker_db`. Nothing is copied or commingled; pottracker gets a **read-only
window**, scoped to exactly the objects you expose.

Sketch (run once, by a DBA, in `pottracker_db`):

```sql
-- 1. enable the extension in pottracker_db
CREATE EXTENSION IF NOT EXISTS postgres_fdw;

-- 2. point at the tracker database (same server → host localhost)
CREATE SERVER tracker_srv
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'localhost', port '5432', dbname 'tracker_db');

-- 3. map a LOW-PRIVILEGE, READ-ONLY tracker role to the pottracker DB user
CREATE USER MAPPING FOR pottracker_app
    SERVER tracker_srv
    OPTIONS (user 'tracker_readonly', password '...');  -- secret: .env, never committed

-- 4. import ONLY the specific tracker VIEWS pottracker may read, into a
--    dedicated local schema so they are obviously foreign + read-only
CREATE SCHEMA IF NOT EXISTS tracker_ext;
IMPORT FOREIGN SCHEMA tracker_public
    LIMIT TO (job_schedule_v, work_order_v)   -- named views only, never base tables
    FROM SERVER tracker_srv INTO tracker_ext;

-- now: SELECT * FROM tracker_ext.job_schedule_v WHERE ...  (read-only, live)
```

Rules if/when we do this:
- Expose **named tracker views only**, never base tables — the tracker owns its
  surface, and views are a stable contract (mirrors the original
  "cross-schema reads go through explicit views" rule).
- Use a **dedicated read-only tracker role** for the user mapping; pottracker can
  never write through the FDW.
- Land foreign tables in a distinct schema (`tracker_ext`) so it is obvious in
  every query that the data is remote and read-only.
- The mapping password is a secret — `.env` only, never committed (anti-pattern #6).
- `postgres_fdw` is standard/bundled with PostgreSQL (`contrib`) — no third-party
  dependency, no supply-chain surface.

### 5b. Service / API boundary
pottracker calls a tracker HTTP endpoint for the data it needs. Cleanest
decoupling; adds a network hop and a contract to version. Prefer this if the read
is occasional or needs tracker business logic, not raw rows.

### 5c. Read replica / logical copy
Replicate selected tracker tables into `pottracker_db`. Heavier; only if the read
volume is high and latency-sensitive. Usually unnecessary — FDW covers it.

**Default recommendation:** `postgres_fdw` over named tracker views. It preserves
physical separation, is read-only by construction, needs no new dependency, and is
the least code.

## 6. Backup / DR implications

The dedicated box's existing tracker backup workflow (NAS + USB + GitHub) applies
to pottracker with these pottracker-specific notes:

- **Dump per database, whole-database — never schema-scoped.** A
  `pg_dump --schema=tooling --schema=shared` **omits the `pgcrypto` extension**
  and the restore then fails on the first `shared.gen_random_uuid()` default
  (proven — `tasks/lessons.md`, `docs/runbooks/backup-restore.md`). Dump all of
  `pottracker_db`; it carries its own extensions. `tracker_db` dumps separately —
  the two are independent, which is the point.
- **Know what is precious vs. disposable.** The `shared.focas_*` mirror tables are
  **reconstructable** — they re-converge on the next poll (R15), so losing them
  costs seconds. The irreplaceable data is small: `tooling.tool` (the library),
  `tooling.assignment`, `shared.user`, and above all the append-only
  `shared.audit_log`. Backup cadence should be driven by those.
- **Secrets and dumps stay OFF GitHub.** Code → GitHub. DB dumps and `.env`
  (which will hold `WRITE_APPROVAL_PASSWORD` once the write path exists) → NAS +
  USB only, never a git remote.
- **Once the write path is live (Phase 5/6):** a nightly dump risks up to 24h of
  offset-write audit history in a crash. Consider WAL archiving / point-in-time
  recovery, or more frequent dumps, at that point. For the read-only pilot,
  nightly is sufficient.
- **A backup you have not restored is a rumor.** Keep the tracker's restore-drill
  discipline and extend it to a scratch `pottracker_restore_test` database.

## 7. Cutover checklist (when pottracker moves onto the dedicated box)

- [ ] Create `pottracker_db` on the box's native Postgres (separate database from
      `tracker_db`).
- [ ] `CREATE EXTENSION pgcrypto WITH SCHEMA shared;` before first `alembic
      upgrade head` (schemas pre-created — see `migrations/env.py`).
- [ ] Apply the R1 GRANT template scoped to `pottracker_db` (belt: the app role
      gets DDL on `tooling`/`shared` only). Cross-DB access to `tracker_db` is
      already impossible; grants are internal hygiene now.
- [ ] Update the DSN guard fingerprint: it currently keys on the dev Docker
      `localhost:5433` target. The dedicated box uses native Postgres (likely
      `:5432`, `pottracker_db`) — update the guard's allowed fingerprint or the
      guard refuses to run migrations (`shared/dsn_guard.py`).
- [ ] Point pottracker `DATABASE_URL` at `pottracker_db`; confirm it never names
      `tracker_db`.
- [ ] Backups: add a whole-database `pg_dump` of `pottracker_db` to the existing
      NAS/USB rotation; run a restore drill.

## 8. What this decision does NOT change

- The internal `tooling.*` + `shared.*` FK model is unchanged — same migrations,
  same tables.
- The R1 code guards stay in place (now defense-in-depth, not load-bearing).
- No application code changes are required to adopt two databases — pottracker
  already targets its own database via `DATABASE_URL`; only the cutover config
  (DSN, grants, backup job) differs.
