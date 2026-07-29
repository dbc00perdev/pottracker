"""work-offset / WORK SHIFT mirror (lathe v1.1)

Revision ID: 0009_work_offset_mirror
Revises: 0008_lathe_class
Create Date: 2026-07-29

`shared.focas_work_offset` — per-machine mirror of the work coordinate offsets
(EXT + G54..G59 via `cnc_rdzofs`) and the 0i-TF WORK SHIFT screen
(`cnc_rdwkcdshft`), both verified live against the VT_23 panel 2026-07-29
(WORK SHIFT Z=19.5044 / X=15.8365; G55 Z=6.2660 — exact matches;
`reports/vt23-workshift-verified-20260729.json`). Domain fact: T1 sets the
work shift on the VT — these values are per-job setup state, so changes ARE
audited (low churn, high signal — unlike HEAD/NEXT).

One row per (machine, slot, axis). `value` carries the control's native value
(inch on this fleet — the `*_mm`/unit naming debt is tracked in
`tasks/spec-offset-units.md` and deliberately not compounded here).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_work_offset_mirror"
down_revision: str | None = "0008_lathe_class"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "focas_work_offset",
        sa.Column(
            "machine_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shared.machine.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("slot", sa.Text(), primary_key=True),
        sa.Column("axis", sa.Text(), primary_key=True),
        sa.Column("value", sa.Numeric(12, 4), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "slot IN ('work_shift', 'ext', 'g54', 'g55', 'g56', 'g57', 'g58', 'g59')",
            name="ck_focas_work_offset_slot",
        ),
        sa.CheckConstraint(
            "axis IN ('x', 'z')",
            name="ck_focas_work_offset_axis",
        ),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_table("focas_work_offset", schema="shared")
