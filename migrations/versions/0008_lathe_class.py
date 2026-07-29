"""machine_class column + lathe offset register types (VT_23 v1)

Revision ID: 0008_lathe_class
Revises: 0007_probe_pot_decouple
Create Date: 2026-07-29

First lathe onboarding (VIPER VT_23, FANUC 0i-TF @ 10.1.10.53, docs/11 machine
classes). Two changes, both `shared.*` (pottracker-owned; R1 untouched):

1. `shared.machine.machine_class` — TEXT NOT NULL DEFAULT 'mill', CHECK
   ('mill','lathe'). Routes the poller read profile (mill snapshot vs the
   lathe offsets-only profile in `shared/focas/lathe.py`) and the UI (pot map
   vs turret offsets view — R20: never render a mill pot map for lathe data).

2. `shared.focas_offset_register.register_type` CHECK widened with the lathe
   bank vocabulary, panel-locked on the VT_23 2026-07-29
   (`reports/vt23-bank-mapping-verified-20260729.json`, spec-focas-calls.md):
   x_wear/x_geom (type codes 0/1), z_wear/z_geom (2/3), r_wear/r_geom (4/5),
   tip (6; code 7 is a duplicate view and is not read). Mill banks unchanged.

Downgrade restores the mill-only CHECK and drops the column; it round-trips on
a schema with no lathe-typed rows. (If lathe offset rows exist, delete them
before downgrading — expected consequence of leaving the lathe model, not a
migration bug.)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_lathe_class"
down_revision: str | None = "0007_probe_pot_decouple"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_MILL_TYPES = "('h_geom', 'h_wear', 'd_geom', 'd_wear')"
_ALL_TYPES = (
    "('h_geom', 'h_wear', 'd_geom', 'd_wear', "
    "'x_geom', 'x_wear', 'z_geom', 'z_wear', 'r_geom', 'r_wear', 'tip')"
)


def upgrade() -> None:
    op.add_column(
        "machine",
        sa.Column(
            "machine_class",
            sa.Text(),
            nullable=False,
            server_default="mill",
        ),
        schema="shared",
    )
    op.create_check_constraint(
        "ck_machine_class",
        "machine",
        "machine_class IN ('mill', 'lathe')",
        schema="shared",
    )
    op.drop_constraint(
        "ck_focas_offset_register_type",
        "focas_offset_register",
        schema="shared",
        type_="check",
    )
    op.create_check_constraint(
        "ck_focas_offset_register_type",
        "focas_offset_register",
        f"register_type IN {_ALL_TYPES}",
        schema="shared",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_focas_offset_register_type",
        "focas_offset_register",
        schema="shared",
        type_="check",
    )
    op.create_check_constraint(
        "ck_focas_offset_register_type",
        "focas_offset_register",
        f"register_type IN {_MILL_TYPES}",
        schema="shared",
    )
    op.drop_constraint("ck_machine_class", "machine", schema="shared", type_="check")
    op.drop_column("machine", "machine_class", schema="shared")
