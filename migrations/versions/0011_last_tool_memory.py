"""last-real-offset memory on the status mirror (VT_23 display L2)

Revision ID: 0011_last_tool_memory
Revises: 0010_active_wcs
Create Date: 2026-07-30

`shared.focas_machine_status.last_tool_t_word` + `last_tool_at` — the last
commanded T word that carried REAL offset digits (Tnnww with ww != 00) and
when it was observed. The shop cancels the offset with Tnn00 at the end of
every op (docs/14 convention), which wipes the live word's offset digits;
this memory lets the UI say "canceled · last OFS 08 · Nm ago" instead of a
bare warning. Written by the persist path only when ww != 00 (a cancel
preserves, never erases). NULL on mills — their HEAD ids are raw tool
numbers (< 100), never Tnnww (same per-profile precedent as active_wcs).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_last_tool_memory"
down_revision: str | None = "0010_active_wcs"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "focas_machine_status",
        sa.Column("last_tool_t_word", sa.Integer(), nullable=True),
        schema="shared",
    )
    op.add_column(
        "focas_machine_status",
        sa.Column("last_tool_at", sa.DateTime(timezone=True), nullable=True),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_column("focas_machine_status", "last_tool_at", schema="shared")
    op.drop_column("focas_machine_status", "last_tool_t_word", schema="shared")
