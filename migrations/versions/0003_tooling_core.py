"""tooling core: tool_type, tool, assignment, pot_observation, offset_write_request
   + shared.machine.probe_h_register

Revision ID: 0003_tooling_core
Revises: 0002_shared_focas_state
Create Date: 2026-07-06

Phase 3.0 migration — the tool library schema. All new tables live in the
`tooling` schema; FKs cross into `shared.*` (machine, user) only, never
`tracker.*` (R1 guard enforces this).

Design notes:

  - `probe_h_register` is ADDED to `shared.machine` (approved shared-schema
    touch, Decision-4 / D-C). The control's probe is locked at T50 **and**
    H50 on the Viper; `probe_t_number` already carries the T-lock, but there
    was no column for the H-lock. Nullable — machines without a reserved probe
    H-register leave it NULL. The API rejects any assignment whose
    `h_register == probe_h_register` (mirrors the existing `probe_t_number`
    rule). R12 mitigation.

  - Assignment uniqueness (D-B) uses **partial unique indexes**
    `WHERE deleted_at IS NULL` rather than the data-model doc's DEFERRABLE
    constraints. Rationale: soft-deleted rows must NOT block reuse of a
    T#/H#/D# after a tool is removed from a machine. Partial unique indexes
    can't be DEFERRABLE, so atomic two-register swaps in a single transaction
    are not supported yet — that's a Phase 5 concern (assignment-move UI),
    revisited then. For Phase 3 (create/retire, no swap) this is correct.

  - `offset_write_request` is created here (schema only, D-D). No write
    endpoints exist until Phase 6; the table lands now to avoid a second
    migration and because Phase 3's scope + tasks/todo.md list it.

  - `gen_random_uuid()` lives in the `shared` schema (pgcrypto, migration
    0001); UUID defaults reference it as `shared.gen_random_uuid()`.

  - Every op names `schema=` explicitly (matches 0001/0002; the R1 runtime
    DDL guard also validates each statement).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_tooling_core"
down_revision: str | Sequence[str] | None = "0002_shared_focas_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("shared.gen_random_uuid()")


def upgrade() -> None:
    # --- shared.machine.probe_h_register (D-C) -------------------------------
    op.add_column(
        "machine",
        sa.Column("probe_h_register", sa.Integer(), nullable=True),
        schema="shared",
    )

    # --- tooling.tool_type ---------------------------------------------------
    op.create_table(
        "tool_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=_UUID_DEFAULT),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("has_corner_radius", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("has_thread_pitch", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("has_taper_angle", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("is_drilling", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("code", name="uq_tool_type_code"),
        schema="tooling",
    )

    # --- tooling.tool --------------------------------------------------------
    op.create_table(
        "tool",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=_UUID_DEFAULT),
        sa.Column("short_id", sa.Text(), nullable=False),
        sa.Column("tool_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        # geometry
        sa.Column("diameter_mm", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("diameter_inch", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("flute_count", sa.Integer(), nullable=True),
        sa.Column("corner_radius_mm", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("flute_length_mm", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("overall_length_mm", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("shank_diameter_mm", sa.Numeric(precision=8, scale=4), nullable=True),
        # material
        sa.Column("substrate", sa.Text(), nullable=True),
        sa.Column("coating", sa.Text(), nullable=True),
        # vendor
        sa.Column("vendor", sa.Text(), nullable=True),
        sa.Column("vendor_part_number", sa.Text(), nullable=True),
        sa.Column("vendor_url", sa.Text(), nullable=True),
        # behavior
        sa.Column("max_doc_mm", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("max_woc_mm", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("requires_tsc", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("requires_climb", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        # lifecycle
        sa.Column("is_consumable_class", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("regrind_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("short_id", name="uq_tool_short_id"),
        sa.ForeignKeyConstraint(["tool_type_id"], ["tooling.tool_type.id"],
                                name="fk_tool_tool_type_id"),
        sa.ForeignKeyConstraint(["created_by"], ["shared.user.id"],
                                name="fk_tool_created_by", ondelete="SET NULL"),
        sa.CheckConstraint("diameter_mm > 0", name="ck_tool_diameter_positive"),
        sa.CheckConstraint("flute_count IS NULL OR flute_count >= 0",
                           name="ck_tool_flute_count_nonneg"),
        schema="tooling",
    )
    op.create_index("ix_tool_type_id", "tool", ["tool_type_id"], schema="tooling")
    op.create_index("ix_tool_diameter", "tool", ["diameter_mm"], schema="tooling")
    op.create_index("ix_tool_short_id", "tool", ["short_id"], schema="tooling")

    # --- tooling.assignment --------------------------------------------------
    op.create_table(
        "assignment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=_UUID_DEFAULT),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("t_number", sa.Integer(), nullable=False),
        sa.Column("h_register", sa.Integer(), nullable=False),
        sa.Column("d_register", sa.Integer(), nullable=True),
        # denormalized cache of last-known FANUC values (authoritative source is
        # shared.focas_offset_register). Never surfaced as "current" without the
        # mirror's poll timestamp (R11).
        sa.Column("cached_h_geom_mm", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("cached_h_wear_mm", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("cached_d_geom_mm", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("cached_d_wear_mm", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("pending_review", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE")),
        sa.Column("pending_reason", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tool_id"], ["tooling.tool.id"],
                                name="fk_assignment_tool_id"),
        sa.ForeignKeyConstraint(["machine_id"], ["shared.machine.id"],
                                name="fk_assignment_machine_id"),
        sa.ForeignKeyConstraint(["assigned_by"], ["shared.user.id"],
                                name="fk_assignment_assigned_by", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_confirmed_by"], ["shared.user.id"],
                                name="fk_assignment_last_confirmed_by", ondelete="SET NULL"),
        sa.CheckConstraint("t_number >= 1", name="ck_assignment_t_number_positive"),
        sa.CheckConstraint("h_register >= 1", name="ck_assignment_h_register_positive"),
        sa.CheckConstraint("d_register IS NULL OR d_register >= 1",
                           name="ck_assignment_d_register_positive"),
        schema="tooling",
    )
    op.create_index("ix_assignment_tool", "assignment", ["tool_id"], schema="tooling")
    op.create_index("ix_assignment_machine", "assignment", ["machine_id"], schema="tooling")
    op.create_index("ix_assignment_pending", "assignment", ["pending_review"],
                    schema="tooling", postgresql_where=sa.text("pending_review = TRUE"))
    # Uniqueness among ACTIVE assignments only (D-B). Soft-deleted rows free the slot.
    op.create_index("uq_assignment_machine_tnum", "assignment",
                    ["machine_id", "t_number"], unique=True, schema="tooling",
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("uq_assignment_machine_hreg", "assignment",
                    ["machine_id", "h_register"], unique=True, schema="tooling",
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("uq_assignment_machine_dreg", "assignment",
                    ["machine_id", "d_register"], unique=True, schema="tooling",
                    postgresql_where=sa.text("deleted_at IS NULL AND d_register IS NOT NULL"))

    # --- tooling.pot_observation ---------------------------------------------
    op.create_table(
        "pot_observation",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False, start=1),
                  primary_key=True),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("t_number", sa.Integer(), nullable=False),
        sa.Column("pot_number", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["machine_id"], ["shared.machine.id"],
                                name="fk_pot_observation_machine_id", ondelete="CASCADE"),
        schema="tooling",
    )
    op.create_index("ix_pot_obs_machine_t", "pot_observation",
                    ["machine_id", "t_number", sa.text("observed_at DESC")],
                    schema="tooling")

    # --- tooling.offset_write_request (D-D, schema only) ---------------------
    op.create_table(
        "offset_write_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=_UUID_DEFAULT),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("register_number", sa.Integer(), nullable=False),
        sa.Column("register_type", sa.Text(), nullable=False),
        sa.Column("intended_value_mm", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("current_value_mm", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_value_mm", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["machine_id"], ["shared.machine.id"],
                                name="fk_owr_machine_id"),
        sa.ForeignKeyConstraint(["requested_by"], ["shared.user.id"],
                                name="fk_owr_requested_by"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["shared.user.id"],
                                name="fk_owr_confirmed_by", ondelete="SET NULL"),
        sa.CheckConstraint(
            "register_type IN ('h_geom', 'h_wear', 'd_geom', 'd_wear')",
            name="ck_owr_register_type"),
        schema="tooling",
    )
    op.create_index("ix_owr_pending", "offset_write_request",
                    ["machine_id", "executed_at"], schema="tooling",
                    postgresql_where=sa.text("executed_at IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_owr_pending", table_name="offset_write_request", schema="tooling")
    op.drop_table("offset_write_request", schema="tooling")

    op.drop_index("ix_pot_obs_machine_t", table_name="pot_observation", schema="tooling")
    op.drop_table("pot_observation", schema="tooling")

    op.drop_index("uq_assignment_machine_dreg", table_name="assignment", schema="tooling")
    op.drop_index("uq_assignment_machine_hreg", table_name="assignment", schema="tooling")
    op.drop_index("uq_assignment_machine_tnum", table_name="assignment", schema="tooling")
    op.drop_index("ix_assignment_pending", table_name="assignment", schema="tooling")
    op.drop_index("ix_assignment_machine", table_name="assignment", schema="tooling")
    op.drop_index("ix_assignment_tool", table_name="assignment", schema="tooling")
    op.drop_table("assignment", schema="tooling")

    op.drop_index("ix_tool_short_id", table_name="tool", schema="tooling")
    op.drop_index("ix_tool_diameter", table_name="tool", schema="tooling")
    op.drop_index("ix_tool_type_id", table_name="tool", schema="tooling")
    op.drop_table("tool", schema="tooling")

    op.drop_table("tool_type", schema="tooling")

    op.drop_column("machine", "probe_h_register", schema="shared")
