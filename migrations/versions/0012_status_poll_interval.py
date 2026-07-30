"""per-machine fast status tier interval (VT_23 display L3)

Revision ID: 0012_status_poll_interval
Revises: 0011_last_tool_memory
Create Date: 2026-07-30

`shared.machine.status_poll_interval_seconds` — cadence for the light
status-only poll tier (docs/10 §8.3): between full snapshot sweeps the
poller re-reads just mode/running + the commanded T word + active WCS
(milliseconds of FOCAS traffic) so the UI's active-offset state tracks in
seconds, not at the full-sweep cadence. NULL = no fast tier (the mills,
v1 — their read profile has no light read). 10s floor per the CLAUDE.md
polling rule; seeded 10 on the VT_23 row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_status_poll_interval"
down_revision: str | None = "0011_last_tool_memory"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "machine",
        sa.Column("status_poll_interval_seconds", sa.Integer(), nullable=True),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_column("machine", "status_poll_interval_seconds", schema="shared")
