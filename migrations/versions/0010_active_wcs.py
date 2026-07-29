"""active work-coordinate system on the status mirror (lathe v1.2)

Revision ID: 0010_active_wcs
Revises: 0009_work_offset_mirror
Create Date: 2026-07-29

`shared.focas_machine_status.active_wcs` — the modal work-offset G code
currently ACTIVE on the control (e.g. 'G56'), read via `cnc_rdgcode`
(modal G-group 13 on the VT_23, verified live 2026-07-29 with dbc00per's
G56 active at the panel). Selecting an offset is modal state, not a value
change — the work-offset VALUE mirror (0009) can never show it, hence this
column. NULL for machines whose profile doesn't read it (the mills, v1).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_active_wcs"
down_revision: str | None = "0009_work_offset_mirror"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "focas_machine_status",
        sa.Column("active_wcs", sa.Text(), nullable=True),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_column("focas_machine_status", "active_wcs", schema="shared")
