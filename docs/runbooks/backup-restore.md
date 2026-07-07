# Runbook — Backup & Restore (tooling + shared schemas)

> Safeguard #4. **Run a backup + a verified restore before any production
> migration or cutover.** Covers `tooling.*` and `shared.*` only — tracker is
> never dumped by tooling (R1). Procedure below was drilled end-to-end against
> the dev container 2026-07-07; the exact output is in this session's notes.

---

## Scope

- Dumps **only** `tooling` and `shared` schemas (schema-scoped `pg_dump -n`).
  Never dumps `tracker` — a tooling backup must not carry tracker data.
- Point-in-time consistent (single `pg_dump` transaction — R15).
- Mirror tables (`shared.focas_*`) re-converge on the next poll if restored
  slightly stale; the authoritative data to protect is `tooling.*` + audit.

---

## ⚠ Critical gotcha (found in the dev drill)

A schema-scoped dump **does NOT include the `pgcrypto` extension**, which lives
in the `shared` schema and provides `shared.gen_random_uuid()` — the default for
every table's `id` PK. Restoring into a fresh database therefore fails on the
first `CREATE TABLE` with:

```
ERROR: function shared.gen_random_uuid() does not exist
```

**The restore target must have `pgcrypto` pre-created in the `shared` schema
BEFORE `pg_restore` runs.** The restore procedure below does this. On the
production DB this is a non-issue for in-place restores (the extension already
exists); it only bites a restore into a *fresh* database — which is exactly what
a DR restore or a pre-migration verification does.

---

## Backup

Dev (docker container):

```bash
docker compose -f docker-compose.dev.yml exec -T postgres \
  pg_dump -U pottracker_dev -d pottracker \
    --schema=tooling --schema=shared -Fc -f /tmp/lance_backup.dump

# copy out of the container, timestamped, into the (gitignored) reports/ dir
docker compose -f docker-compose.dev.yml cp \
  postgres:/tmp/lance_backup.dump "reports/dev-backup-$(date +%Y%m%d-%H%M%S).dump"
```

Production (adjust host/user/db; run from a host with the `postgres:16` client
tools or `docker exec` into the prod PG):

```bash
PGPASSWORD=... pg_dump -h <prod-host> -U lance_tooling -d lance \
  --schema=tooling --schema=shared -Fc -f "lance-prod-$(date +%Y%m%d-%H%M%S).dump"
```

`-Fc` = custom format (compressed, selective `pg_restore`). `*.dump` is
gitignored — never commit a dump.

---

## Restore (into a fresh scratch/DR database)

```bash
DB=pottracker_restore_test          # scratch name; use the real DR name in prod

# 1. fresh database
psql ... -d postgres -c "CREATE DATABASE $DB;"

# 2. PRE-CREATE the pgcrypto dependency in the shared schema (see gotcha above)
psql ... -d "$DB" -c "CREATE SCHEMA shared; CREATE EXTENSION pgcrypto WITH SCHEMA shared;"

# 3. restore. The dump re-issues 'CREATE SCHEMA shared' → one benign
#    'already exists' error, safely ignorable. Any OTHER error is real.
pg_restore -U ... -d "$DB" lance_backup.dump
```

Dev one-liner form used in the drill:

```bash
DC="docker compose -f docker-compose.dev.yml exec -T postgres"
$DC psql -U pottracker_dev -d postgres -c "CREATE DATABASE pottracker_restore_test;"
$DC psql -U pottracker_dev -d pottracker_restore_test \
   -c "CREATE SCHEMA shared; CREATE EXTENSION pgcrypto WITH SCHEMA shared;"
$DC sh -c 'pg_restore -U pottracker_dev -d pottracker_restore_test /tmp/lance_backup.dump'
```

---

## Verify the restore (mandatory — a backup you haven't restored is a rumor)

```bash
# alembic head must match source
psql ... -d "$DB" -At -c "select version_num from shared.alembic_version;"
# → 0003_tooling_core  (as of this writing)

# base-table parity: tooling + shared should be 12 tables
psql ... -d "$DB" -At -c "select count(*) from information_schema.tables
  where table_schema in ('tooling','shared') and table_type='BASE TABLE';"
# → 12

# spot-check row counts against the source's counts captured at dump time
psql ... -d "$DB" -At -c "select count(*) from shared.audit_log;"
```

Drill result (2026-07-07, dev): head `0003_tooling_core`, 12/12 tables,
`audit_log=3`, all other tables 0 — **exact parity with source**.

---

## Cleanup

```bash
psql ... -d postgres -c "DROP DATABASE $DB;"   # drop the scratch/verification DB
```

After the dev drill, confirmed the source dev DB was untouched (head `0003`,
`tracker` schema still absent).

---

## Restore-drill cadence

- **Before every production migration / cutover** (belt for R1 + the migration
  itself). Take a fresh dump, restore it into a scratch DB, verify head + counts,
  *then* proceed with the migration.
- Quarterly DR drill per R15.
