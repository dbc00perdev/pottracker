"""SQLAlchemy Core table registry for the `shared.*` schema.

App-side `Table` objects that MIRROR the hand-written Alembic migrations
(`migrations/versions/0001_shared_core.py`, `0002_shared_focas_state.py`).
Core (not ORM) because the Phase 2 persist path is UPSERT-heavy and wants
`postgresql.insert(...).on_conflict_do_update(...)`.

Only the columns needed for DML are declared — DB-side CHECK/FK constraints
and indexes live in the migrations and are the enforcement point; duplicating
them here would add drift surface for no gain.

DRIFT RISK: these defs and the migrations must stay in lockstep. A follow-up
Phase 2 task adds a reconciliation test (`alembic upgrade head` on a Docker DB,
reflect, assert column parity). Until then, code review is the guard.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()

# --- shared.focas_offset_register --------------------------------------------
# PK (machine_id, register_number, register_type). value_mm NUMERIC(10,4) in mm.
# last_polled_at advances every cycle; last_changed_at only on value change.
focas_offset_register = sa.Table(
    "focas_offset_register",
    metadata,
    sa.Column("machine_id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("register_number", sa.Integer, primary_key=True),
    sa.Column("register_type", sa.Text, primary_key=True),
    sa.Column("value_mm", sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
    schema="shared",
)

# --- shared.focas_pot --------------------------------------------------------
# PK (machine_id, pot_number). t_number NULL = empty pot. Observed state (R10).
focas_pot = sa.Table(
    "focas_pot",
    metadata,
    sa.Column("machine_id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("pot_number", sa.Integer, primary_key=True),
    sa.Column("t_number", sa.Integer, nullable=True),
    sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
    schema="shared",
)

# --- shared.focas_tool_life --------------------------------------------------
# PK (machine_id, t_number). No last_changed_at column (migration 0002).
focas_tool_life = sa.Table(
    "focas_tool_life",
    metadata,
    sa.Column("machine_id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("t_number", sa.Integer, primary_key=True),
    sa.Column("life_count", sa.Integer, nullable=True),
    sa.Column("life_max", sa.Integer, nullable=True),
    sa.Column("status", sa.Text, nullable=True),
    sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=False),
    schema="shared",
)

# --- shared.audit_log --------------------------------------------------------
# Append-only ledger. id is IDENTITY (omit on insert). occurred_at defaults to
# now() server-side. Poller-driven rows have user_id NULL and success TRUE.
audit_log = sa.Table(
    "audit_log",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column(
        "occurred_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    ),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("event_type", sa.Text, nullable=False),
    sa.Column("entity_type", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text, nullable=False),
    sa.Column("before_value", postgresql.JSONB, nullable=True),
    sa.Column("after_value", postgresql.JSONB, nullable=True),
    sa.Column("reason", sa.Text, nullable=True),
    sa.Column("success", sa.Boolean, nullable=False),
    sa.Column("error", sa.Text, nullable=True),
    schema="shared",
)

__all__ = [
    "audit_log",
    "focas_offset_register",
    "focas_pot",
    "focas_tool_life",
    "metadata",
]
