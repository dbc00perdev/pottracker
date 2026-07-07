-- prod_grant_lockdown.sql — DB-level belt for R1 (docs/07-risks.md).
--
-- The ULTIMATE tracker-isolation defense: even if every code-level guard
-- regressed, the tooling DB role physically cannot touch tracker tables.
-- The `lance_tooling` role gets DDL only on tooling + shared, and SELECT only
-- on explicitly named tracker VIEWS — never on tracker tables directly.
--
-- Idempotent. Run as a DB admin (superuser / owner) during the production
-- deploy / cutover. Verified against the dev DB via a rolled-back drill
-- (see safeguard #6 in tasks/spec-install-safeguards.md).
--
-- Usage:
--   psql -h <host> -U <admin> -d <dbname> \
--        -v role=lance_tooling -v dbname=lance \
--        -f scripts/sql/prod_grant_lockdown.sql
--
-- Then add one GRANT SELECT line per tracker view the app actually needs
-- (see the marked section) and re-run — it stays idempotent.

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- 1. Revoke everything on tracker (tables, sequences, and DB-level CREATE).
--    Guard against the tracker schema not existing yet in a given environment.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'tracker') THEN
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA tracker FROM %I', :'role');
    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA tracker FROM %I', :'role');
    EXECUTE format('REVOKE ALL ON SCHEMA tracker FROM %I', :'role');
  END IF;
END $$;

REVOKE CREATE ON DATABASE :"dbname" FROM :"role";

-- ---------------------------------------------------------------------------
-- 2. Grant DDL on tooling + shared (existing objects AND future defaults).
-- ---------------------------------------------------------------------------
GRANT USAGE, CREATE ON SCHEMA tooling TO :"role";
GRANT USAGE, CREATE ON SCHEMA shared  TO :"role";

GRANT ALL ON ALL TABLES    IN SCHEMA tooling TO :"role";
GRANT ALL ON ALL SEQUENCES IN SCHEMA tooling TO :"role";
GRANT ALL ON ALL TABLES    IN SCHEMA shared  TO :"role";
GRANT ALL ON ALL SEQUENCES IN SCHEMA shared  TO :"role";

ALTER DEFAULT PRIVILEGES IN SCHEMA tooling GRANT ALL ON TABLES    TO :"role";
ALTER DEFAULT PRIVILEGES IN SCHEMA tooling GRANT ALL ON SEQUENCES TO :"role";
ALTER DEFAULT PRIVILEGES IN SCHEMA shared  GRANT ALL ON TABLES    TO :"role";
ALTER DEFAULT PRIVILEGES IN SCHEMA shared  GRANT ALL ON SEQUENCES TO :"role";

-- ---------------------------------------------------------------------------
-- 3. Read-only access to specific tracker VIEWS only — never tracker tables.
--    USAGE lets the role traverse into the schema; SELECT is per-view.
--    Add one line per view the app needs. Kept empty by default (deny-all).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'tracker') THEN
    EXECUTE format('GRANT USAGE ON SCHEMA tracker TO %I', :'role');
  END IF;
END $$;

--   GRANT SELECT ON tracker.<view_name> TO :"role";
--   (uncomment + name each view; re-run — idempotent)

-- ---------------------------------------------------------------------------
-- Verify after applying:
--   \dn+                 -- schema-level privileges
--   \dp tracker.*        -- per-relation privileges (role must have none on tables)
-- ---------------------------------------------------------------------------
