"""SQLAlchemy Core table registry for the `tooling.*` schema.

App-side `Table` objects mirroring migration `0003_tooling_core`. Core (not
ORM) to match the Phase-2 convention in `shared/db.py` — one data-access
paradigm across the repo. Only columns the API reads/writes are declared;
DB-side CHECK/FK constraints and partial unique indexes live in the migration
and are the enforcement point.

DRIFT RISK: these defs and the migration must stay in lockstep. The
reconciliation test (`tests/test_tooling_tables_reconcile.py`) reflects
`alembic upgrade head` and asserts column parity.

Uses its own `MetaData` so `tooling.*` and `shared.*` registries stay
separable; the two are joined at query time by column, not by a shared
MetaData graph.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()

tool_type = sa.Table(
    "tool_type",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
              server_default=sa.text("shared.gen_random_uuid()")),
    sa.Column("code", sa.Text, nullable=False),
    sa.Column("display_name", sa.Text, nullable=False),
    sa.Column("has_corner_radius", sa.Boolean, nullable=False),
    sa.Column("has_thread_pitch", sa.Boolean, nullable=False),
    sa.Column("has_taper_angle", sa.Boolean, nullable=False),
    sa.Column("is_drilling", sa.Boolean, nullable=False),
    sa.Column("notes", sa.Text, nullable=True),
    schema="tooling",
)

tool = sa.Table(
    "tool",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
              server_default=sa.text("shared.gen_random_uuid()")),
    sa.Column("short_id", sa.Text, nullable=False),
    sa.Column("tool_type_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("diameter_mm", sa.Numeric(8, 4), nullable=False),
    sa.Column("diameter_inch", sa.Numeric(8, 5), nullable=True),
    sa.Column("flute_count", sa.Integer, nullable=True),
    sa.Column("corner_radius_mm", sa.Numeric(8, 4), nullable=True),
    sa.Column("flute_length_mm", sa.Numeric(8, 4), nullable=True),
    sa.Column("overall_length_mm", sa.Numeric(8, 4), nullable=True),
    sa.Column("shank_diameter_mm", sa.Numeric(8, 4), nullable=True),
    sa.Column("substrate", sa.Text, nullable=True),
    sa.Column("coating", sa.Text, nullable=True),
    sa.Column("vendor", sa.Text, nullable=True),
    sa.Column("vendor_part_number", sa.Text, nullable=True),
    sa.Column("vendor_url", sa.Text, nullable=True),
    sa.Column("max_doc_mm", sa.Numeric(8, 4), nullable=True),
    sa.Column("max_woc_mm", sa.Numeric(8, 4), nullable=True),
    sa.Column("requires_tsc", sa.Boolean, nullable=False),
    sa.Column("requires_climb", sa.Boolean, nullable=False),
    sa.Column("is_consumable_class", sa.Boolean, nullable=False),
    sa.Column("regrind_count", sa.Integer, nullable=False),
    sa.Column("notes", sa.Text, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    schema="tooling",
)

assignment = sa.Table(
    "assignment",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
              server_default=sa.text("shared.gen_random_uuid()")),
    sa.Column("tool_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("t_number", sa.Integer, nullable=False),
    sa.Column("h_register", sa.Integer, nullable=False),
    sa.Column("d_register", sa.Integer, nullable=True),
    sa.Column("cached_h_geom_mm", sa.Numeric(10, 4), nullable=True),
    sa.Column("cached_h_wear_mm", sa.Numeric(10, 4), nullable=True),
    sa.Column("cached_d_geom_mm", sa.Numeric(10, 4), nullable=True),
    sa.Column("cached_d_wear_mm", sa.Numeric(10, 4), nullable=True),
    sa.Column("pending_review", sa.Boolean, nullable=False),
    sa.Column("pending_reason", sa.Text, nullable=True),
    sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    schema="tooling",
)

pot_observation = sa.Table(
    "pot_observation",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("t_number", sa.Integer, nullable=False),
    sa.Column("pot_number", sa.Integer, nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    schema="tooling",
)

offset_write_request = sa.Table(
    "offset_write_request",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
              server_default=sa.text("shared.gen_random_uuid()")),
    sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("register_number", sa.Integer, nullable=False),
    sa.Column("register_type", sa.Text, nullable=False),
    sa.Column("intended_value_mm", sa.Numeric(10, 4), nullable=False),
    sa.Column("current_value_mm", sa.Numeric(10, 4), nullable=True),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("verified_value_mm", sa.Numeric(10, 4), nullable=True),
    sa.Column("success", sa.Boolean, nullable=True),
    sa.Column("error", sa.Text, nullable=True),
    schema="tooling",
)

__all__ = [
    "assignment",
    "metadata",
    "offset_write_request",
    "pot_observation",
    "tool",
    "tool_type",
]
