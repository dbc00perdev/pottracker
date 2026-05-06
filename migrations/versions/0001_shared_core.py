"""shared core: schemas, pgcrypto, machine, user, audit_log

Revision ID: 0001_shared_core
Revises:
Create Date: 2026-05-06

Phase 2.0 migration — first DDL on the database.

Order of operations:
  1. Create `shared` and `tooling` schemas. The Alembic env's
     `SET search_path TO shared, tooling` already runs at connection
     start; setting it before the schemas exist is fine — Postgres
     ignores nonexistent entries at lookup time.
  2. Install `pgcrypto` extension into the `shared` schema. Provides
     `gen_random_uuid()` for UUID column defaults. Installed in
     `shared` rather than `public` because our search_path explicitly
     excludes `public`.
  3. Create the three shared core tables:
       - shared.machine        — control registry (Viper, AG100)
       - shared.user           — auth users (no tracker integration v1)
       - shared.audit_log      — append-only event ledger

R1 mitigation: every op explicitly names `schema='shared'`. The runtime
DDL guard in `migrations/_guard.py` regex-checks each statement; this
file is hand-written, so the autogenerate-time op walker doesn't fire
on it. If a future contributor copies this file as a template and forgets
the `schema=...` arg, the unqualified DDL routes to `tooling` (search_path
first entry), not `public` — still wrong destination but at least within
our allowlist. Code review remains the primary defense for hand-written
migrations.

`shared.user` uses the SQL reserved word `user` as a table name; SQLAlchemy
quotes it automatically. References must spell it `shared."user"` in
hand-written SQL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_shared_core"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Schemas. CREATE SCHEMA IF NOT EXISTS is idempotent against
    # partially-applied migrations during development.
    op.execute("CREATE SCHEMA IF NOT EXISTS shared")
    op.execute("CREATE SCHEMA IF NOT EXISTS tooling")

    # 2. pgcrypto in shared schema for gen_random_uuid().
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA shared")

    # 3. shared.machine
    op.create_table(
        "machine",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("shared.gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("serial_number", sa.Text(), nullable=True),
        sa.Column("control_model", sa.Text(), nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=False),
        sa.Column(
            "focas_port",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("8193"),
        ),
        sa.Column("pot_count", sa.Integer(), nullable=False),
        sa.Column("probe_pot", sa.Integer(), nullable=True),
        sa.Column("probe_t_number", sa.Integer(), nullable=True),
        sa.Column(
            "offset_register_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("400"),
        ),
        sa.Column("atc_strategy", sa.Text(), nullable=False),
        sa.Column(
            "has_tsc",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "has_toolsetter",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "poll_interval_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("name", name="uq_machine_name"),
        sa.CheckConstraint(
            "atc_strategy IN ('random_access', 'sequential')",
            name="ck_machine_atc_strategy",
        ),
        sa.CheckConstraint(
            "poll_interval_seconds >= 10",
            name="ck_machine_poll_interval_floor",
        ),
        sa.CheckConstraint(
            "(probe_pot IS NULL) = (probe_t_number IS NULL)",
            name="ck_machine_probe_pair_consistent",
        ),
        schema="shared",
    )

    # 4. shared.user. SQLAlchemy quotes the reserved word automatically.
    op.create_table(
        "user",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("shared.gen_random_uuid()"),
        ),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("username", name="uq_user_username"),
        sa.CheckConstraint(
            "role IN ('viewer', 'operator', 'setter', 'admin')",
            name="ck_user_role",
        ),
        schema="shared",
    )

    # 5. shared.audit_log — append-only event ledger.
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False, start=1),
            primary_key=True,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("before_value", postgresql.JSONB(), nullable=True),
        sa.Column("after_value", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["shared.user.id"],
            name="fk_audit_log_user_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["shared.machine.id"],
            name="fk_audit_log_machine_id",
            ondelete="SET NULL",
        ),
        schema="shared",
    )
    op.create_index(
        "ix_audit_log_occurred_at",
        "audit_log",
        [sa.text("occurred_at DESC")],
        schema="shared",
    )
    op.create_index(
        "ix_audit_log_machine_occurred",
        "audit_log",
        ["machine_id", sa.text("occurred_at DESC")],
        schema="shared",
    )
    op.create_index(
        "ix_audit_log_entity",
        "audit_log",
        ["entity_type", "entity_id"],
        schema="shared",
    )


def downgrade() -> None:
    # Schemas are NOT dropped — they may host other apps' tables. Only
    # remove what we created.
    op.drop_index("ix_audit_log_entity", table_name="audit_log", schema="shared")
    op.drop_index("ix_audit_log_machine_occurred", table_name="audit_log", schema="shared")
    op.drop_index("ix_audit_log_occurred_at", table_name="audit_log", schema="shared")
    op.drop_table("audit_log", schema="shared")
    op.drop_table("user", schema="shared")
    op.drop_table("machine", schema="shared")
    # pgcrypto is left installed; other migrations / apps may rely on it.
    # Schemas left in place.
