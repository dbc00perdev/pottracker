"""tool manufacturer + EDP number

Revision ID: 0006_tool_mfr_edp
Revises: 0005_shared_focas_status
Create Date: 2026-07-09

Adds `tooling.tool.manufacturer` + `tooling.tool.edp_number` — the tool's MAKER
(Helical, Harvey, Kennametal, …) and its EDP catalog/reorder number. These are
distinct from the existing `vendor` / `vendor_part_number`, which describe the
DISTRIBUTOR you buy from (who makes it != who you buy it from).

manufacturer + EDP is a valuable secondary cross-reference key: given the pair
you can pull a tool's full published geometry and reorder it, and it's how tool
databases / CAMWorks cross-reference. It rides as an attribute — the permanent
identity stays the non-significant GTID (`short_id`), per the tool-numbering
spec (significant-vs-non-significant: identity must never "lie").

Both nullable Text; no backfill. Downgrade drops them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_tool_mfr_edp"
down_revision: str | Sequence[str] | None = "0005_shared_focas_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column("manufacturer", sa.Text(), nullable=True),
        schema="tooling",
    )
    op.add_column(
        "tool",
        sa.Column("edp_number", sa.Text(), nullable=True),
        schema="tooling",
    )


def downgrade() -> None:
    op.drop_column("tool", "edp_number", schema="tooling")
    op.drop_column("tool", "manufacturer", schema="tooling")
