"""shared focas macro-variable mirror

Revision ID: 0004_shared_focas_macro
Revises: 0003_tooling_core
Create Date: 2026-07-08

Adds `shared.focas_macro_var` — the fourth FOCAS read mirror, symmetric with
`focas_offset_register` / `focas_pot` (migration 0002). Holds the most recent
value of a small set of FANUC custom-macro variables per machine, read via
`cnc_rdmacro`.

Purpose: the tool presetter runs a G31 skip cycle that latches the skip
position into system vars #5061-#5063. Persisting these lets the snapshot
diff detect a *fresh* skip cycle-over-cycle, which — correlated with an
H-geom offset change in the same poll — attributes that offset write to the
presetter (verified) vs a manual keypad edit (R11 trust signal). The
attribution tag rides in `shared.audit_log.after_value` JSONB; no audit
schema change.

`value` is NUMERIC (unconstrained scale) so it can hold any decoded macro
value exactly — skip positions are mm, but the table is general. NULL = the
variable was vacant at read time (FOCAS `dec_val < 0`).

Like the other mirrors this is a cache, not a source of truth: the control
owns the values; a restore re-converges on the next poll (R15).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_shared_focas_macro"
down_revision: str | Sequence[str] | None = "0003_tooling_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "focas_macro_var",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("machine_id", "number", name="pk_focas_macro_var"),
        sa.ForeignKeyConstraint(
            ["machine_id"],
            ["shared.machine.id"],
            name="fk_focas_macro_var_machine_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("number >= 1", name="ck_focas_macro_var_number_positive"),
        schema="shared",
    )
    op.create_index(
        "ix_focas_macro_var_machine_changed",
        "focas_macro_var",
        ["machine_id", sa.text("last_changed_at DESC")],
        schema="shared",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_focas_macro_var_machine_changed",
        table_name="focas_macro_var",
        schema="shared",
    )
    op.drop_table("focas_macro_var", schema="shared")
