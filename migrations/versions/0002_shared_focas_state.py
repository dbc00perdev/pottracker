"""shared focas state mirror tables

Revision ID: 0002_shared_focas_state
Revises: 0001_shared_core
Create Date: 2026-05-06

Phase 2.1 — the FOCAS read mirror. Three tables that hold the most
recent values seen by `shared.focas.poller`:

  - shared.focas_offset_register  — per-(machine, register, type) offset
  - shared.focas_pot              — per-(machine, pot) tool index
  - shared.focas_tool_life        — per-(machine, t_number) life data

These are caches, not sources of truth. The control owns the values; we
mirror them so the UI can paint without poll-blocking and so historical
diff queries are cheap. `Phase 6 reconciliation` is N/A — writes to the
control go through `tooling.offset_write_request` (Phase 3) and confirm
back into this mirror via the next poll cycle.

`value_mm` storage: NUMERIC(10, 4) matches the precision of our Pydantic
`OffsetRegister` model (`Decimal.quantize(0.0001)`). All offsets are
stored in millimeters regardless of the FANUC unit setting; conversion
happens at the FOCAS boundary (`shared.focas.client.decode_offset`),
never in business logic.

`last_polled_at` vs `last_changed_at`: the poller updates `last_polled_at`
every cycle; `last_changed_at` only when the value differs from the prior
snapshot (epsilon = 0.0001 mm). Phase 2.2 (snapshot.py + audit.py) writes
the diff event to `shared.audit_log` when `last_changed_at` advances.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_shared_focas_state"
down_revision: str | Sequence[str] | None = "0001_shared_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # shared.focas_offset_register
    op.create_table(
        "focas_offset_register",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("register_number", sa.Integer(), nullable=False),
        sa.Column("register_type", sa.Text(), nullable=False),
        sa.Column("value_mm", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column(
            "last_polled_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "machine_id",
            "register_number",
            "register_type",
            name="pk_focas_offset_register",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["shared.machine.id"],
            name="fk_focas_offset_register_machine_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "register_type IN ('h_geom', 'h_wear', 'd_geom', 'd_wear')",
            name="ck_focas_offset_register_type",
        ),
        sa.CheckConstraint(
            "register_number BETWEEN 1 AND 999",
            name="ck_focas_offset_register_number_range",
        ),
        schema="shared",
    )
    op.create_index(
        "ix_focas_offset_register_machine_changed",
        "focas_offset_register",
        ["machine_id", sa.text("last_changed_at DESC")],
        schema="shared",
    )

    # shared.focas_pot
    op.create_table(
        "focas_pot",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pot_number", sa.Integer(), nullable=False),
        sa.Column("t_number", sa.Integer(), nullable=True),
        sa.Column(
            "last_polled_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "machine_id",
            "pot_number",
            name="pk_focas_pot",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["shared.machine.id"],
            name="fk_focas_pot_machine_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "pot_number BETWEEN 1 AND 999",
            name="ck_focas_pot_number_range",
        ),
        sa.CheckConstraint(
            "t_number IS NULL OR t_number BETWEEN 1 AND 99999",
            name="ck_focas_pot_t_number_range",
        ),
        schema="shared",
    )
    op.create_index(
        "ix_focas_pot_machine_changed",
        "focas_pot",
        ["machine_id", sa.text("last_changed_at DESC")],
        schema="shared",
    )

    # shared.focas_tool_life
    op.create_table(
        "focas_tool_life",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("t_number", sa.Integer(), nullable=False),
        sa.Column("life_count", sa.Integer(), nullable=True),
        sa.Column("life_max", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column(
            "last_polled_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "machine_id",
            "t_number",
            name="pk_focas_tool_life",
        ),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["shared.machine.id"],
            name="fk_focas_tool_life_machine_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "t_number BETWEEN 1 AND 99999",
            name="ck_focas_tool_life_t_number_range",
        ),
        sa.CheckConstraint(
            "status IS NULL OR status IN ('live', 'expired', 'skipped')",
            name="ck_focas_tool_life_status",
        ),
        sa.CheckConstraint(
            "life_count IS NULL OR life_count >= 0",
            name="ck_focas_tool_life_count_nonneg",
        ),
        sa.CheckConstraint(
            "life_max IS NULL OR life_max >= 0",
            name="ck_focas_tool_life_max_nonneg",
        ),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_table("focas_tool_life", schema="shared")
    op.drop_index(
        "ix_focas_pot_machine_changed",
        table_name="focas_pot",
        schema="shared",
    )
    op.drop_table("focas_pot", schema="shared")
    op.drop_index(
        "ix_focas_offset_register_machine_changed",
        table_name="focas_offset_register",
        schema="shared",
    )
    op.drop_table("focas_offset_register", schema="shared")
