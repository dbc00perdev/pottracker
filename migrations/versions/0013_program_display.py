"""running-program display on the status mirror (spec-program-display)

Revision ID: 0013_program_display
Revises: 0012_status_poll_interval
Create Date: 2026-08-06

`shared.focas_machine_status.program_number` / `program_name` — the program
under execution (`cnc_exeprgname` O number) and the best-effort part name
parsed from its comment line ("3878OR Blank"). Lathe profile v1; NULL on
mills until the mill client gains the read. Not audited — a program change
is per-job churn, same R17 rationale as HEAD/NEXT.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_program_display"
down_revision: str | None = "0012_status_poll_interval"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "focas_machine_status",
        sa.Column("program_number", sa.Integer(), nullable=True),
        schema="shared",
    )
    op.add_column(
        "focas_machine_status",
        sa.Column("program_name", sa.Text(), nullable=True),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_column("focas_machine_status", "program_name", schema="shared")
    op.drop_column("focas_machine_status", "program_number", schema="shared")
