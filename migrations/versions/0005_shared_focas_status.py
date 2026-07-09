"""shared focas machine-status mirror

Revision ID: 0005_shared_focas_status
Revises: 0004_shared_focas_macro
Create Date: 2026-07-09

Adds `shared.focas_machine_status` — the fifth FOCAS read mirror, holding the
per-machine spindle/load state decoded from `cnc_statinfo` + the Viper's OEM
PMC head/next registers (R327 = HEAD in spindle, R325 = NEXT on deck).

Purpose: the pot map shows tool IDENTITY (the sticky PMC pot cell) and PRESENCE
(offset != 0), but not LOCATION. A measured tool physically in the spindle (or
on deck) still shows its identity in its home pot, so occupancy renders it a
"ghost" (loaded in a pot it has physically left). HEAD (`current_t_number`) and
NEXT (`next_t_number`) are already read every snapshot; persisting them lets the
API overlay the spindle/next slots on the pot map and mark the vacated pot.

One row per machine (PK = machine_id). Unlike the multi-row mirrors this needs
no secondary index. `last_polled_at` advances every cycle; `last_changed_at`
advances only when a field actually moves (decided in SQL by the persist path).

HEAD/NEXT change constantly during a running program, so — unlike offsets / pots
/ tool-life — status changes are NOT written to `shared.audit_log` (R17). This
mirror is the whole record of live spindle state.

Like the other mirrors this is a cache, not a source of truth: the control owns
the values; a restore re-converges on the next poll (R15).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_shared_focas_status"
down_revision: str | Sequence[str] | None = "0004_shared_focas_macro"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "focas_machine_status",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("head_t_number", sa.Integer(), nullable=True),
        sa.Column("next_t_number", sa.Integer(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=True),
        sa.Column("running", sa.Boolean(), nullable=True),
        sa.Column("emergency_stop", sa.Boolean(), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("machine_id", name="pk_focas_machine_status"),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["shared.machine.id"],
            name="fk_focas_machine_status_machine_id",
            ondelete="CASCADE",
        ),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_table("focas_machine_status", schema="shared")
