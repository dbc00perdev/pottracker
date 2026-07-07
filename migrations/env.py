"""Alembic environment for lance-tooling.

Wires the tracker-isolation guard into Alembic's hooks. All policy logic
lives in `migrations/_guard.py` so it's unit-testable without bringing up
Alembic. See that module's docstring for the layered-defense explanation.
"""

from __future__ import annotations

import logging
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from migrations._guard import (
    ALLOWED_SCHEMAS,
    SEARCH_PATH_SQL,
    include_object,
    process_revision_directives,
    runtime_ddl_event,
)
from shared.dsn_guard import assert_target_allowed

_logger = logging.getLogger("alembic.env")

config = context.config

# Resolve DSN: DATABASE_URL env var takes precedence over alembic.ini's
# sqlalchemy.url. This is how we point Alembic at the Docker dev DB without
# committing a real connection string. `.env` is loaded by the operator's
# shell (set -a; . ./.env; set +a) before invoking alembic.
_env_url = os.environ.get("DATABASE_URL")
if _env_url:
    # Alembic's pg dialect prefix is `postgresql+psycopg`; the .env's
    # `postgresql://...` form works with psycopg's default driver detection.
    if _env_url.startswith("postgresql://"):
        _env_url = _env_url.replace("postgresql://", "postgresql+psycopg://", 1)
    config.set_main_option("sqlalchemy.url", _env_url)
    _logger.info("alembic DSN sourced from DATABASE_URL env var")

# Empty for v1: hand-written migrations only. When models land in Phase 3,
# replace with the model registry's metadata so autogenerate works; the
# schema-isolation filters in `_guard` keep working unchanged.
target_metadata = None


def run_migrations_offline() -> None:
    """`alembic upgrade --sql` path. No DB connection; SQL is rendered to
    stdout. The runtime DDL guard cannot fire here — review the rendered
    SQL before applying it manually."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        process_revision_directives=process_revision_directives,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """`alembic upgrade` path against a live DB.

    All three guard layers are active:
      1. Runtime DDL guard: SQLAlchemy event listener on the engine
      2. Search-path lockdown: SET search_path on the connection
      3. Autogenerate guard: include_object + process_revision_directives

    Before any of that, the DSN preflight guard refuses a non-dev target unless
    LANCE_ALLOW_PROD=1 is set — a production migration must be an explicit,
    backed-up, confirmed cutover (see tasks/spec-install-safeguards.md).
    """
    assert_target_allowed(
        config.get_main_option("sqlalchemy.url") or "", action="alembic migrate"
    )
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # Layer 1: refuse DDL referencing forbidden schemas before the cursor
    # ever executes it. Listener stays attached for the engine's lifetime.
    event.listen(connectable, "before_cursor_execute", runtime_ddl_event)

    # `begin()` (not `connect()`) so the whole apply commits on success and
    # rolls back atomically on failure. The env sets search_path / creates
    # schemas via exec_driver_sql BEFORE alembic's own `begin_transaction()`,
    # which auto-begins a transaction and makes alembic's inner
    # begin_transaction() a non-committing no-op; without an outer committing
    # scope the migration silently rolls back on connection close (exit 0, no
    # effect). `begin()` owns the commit and closes that gap.
    with connectable.begin() as connection:
        # Layer 2: lock search_path so unqualified DDL routes to `tooling`,
        # never to `public`. exec_driver_sql avoids the SQLAlchemy parser
        # interpreting this as a parameterized statement.
        connection.exec_driver_sql(SEARCH_PATH_SQL)

        # Bootstrap: Alembic creates `alembic_version` BEFORE migration 0001
        # runs, but search_path excludes `public` and the allowed schemas don't
        # exist yet on a fresh DB — so the version table has nowhere to land
        # ("no schema has been selected to create in"). Pre-create the allowed
        # schemas (idempotent; 0001 repeats CREATE SCHEMA IF NOT EXISTS) and
        # pin `alembic_version` to `shared`. Both statements pass the Layer 1
        # guard (they reference only allowed schemas). This also fixes the
        # production first-apply, which would fail identically.
        for _schema in sorted(ALLOWED_SCHEMAS):
            connection.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {_schema}")

        # Layer 3: include_object + process_revision_directives validate
        # autogenerated revisions before they're written.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            process_revision_directives=process_revision_directives,
            include_schemas=True,
            version_table_schema="shared",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    try:
        run_migrations_online()
    except Exception as exc:  # pragma: no cover
        print(f"alembic env failed: {exc}", file=sys.stderr)
        raise
