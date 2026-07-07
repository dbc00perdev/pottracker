"""Assignment queries + the create-time validation gate.

The validation gate is the safety-critical part of Phase 3:

  * Decision-4 / R12 — reject `t_number == machine.probe_t_number` (T50 on the
    Viper) AND `h_register == machine.probe_h_register` (H50). The probe is
    locked; assigning a regular tool onto its registers would break probing.
  * Uniqueness among ACTIVE assignments (partial unique indexes back this at
    the DB; we pre-check for clean 409s).
  * Capability — `requires_tsc` tool onto a non-TSC machine is rejected.

Order matters: existence/enabled first, then probe-lock, then uniqueness, then
capability. All rule violations are 422 (Unprocessable) except uniqueness
collisions (409 Conflict).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from apps.tooling.api.errors import Conflict, NotFound, Unprocessable
from apps.tooling.api.schemas.assignment import AssignmentCreate, AssignmentUpdate
from apps.tooling.api.tables import assignment as asg
from apps.tooling.api.tables import tool as tool_t
from shared.db import machine as machine_t

_OUT_COLS = [
    asg.c.id, asg.c.tool_id, tool_t.c.short_id.label("tool_short_id"),
    asg.c.machine_id, machine_t.c.name.label("machine_name"),
    asg.c.t_number, asg.c.h_register, asg.c.d_register,
    asg.c.cached_h_geom_mm, asg.c.cached_h_wear_mm,
    asg.c.cached_d_geom_mm, asg.c.cached_d_wear_mm,
    asg.c.pending_review, asg.c.pending_reason,
    asg.c.assigned_at, asg.c.last_confirmed_at, asg.c.deleted_at,
]
_OUT_FROM = asg.join(tool_t, asg.c.tool_id == tool_t.c.id).join(
    machine_t, asg.c.machine_id == machine_t.c.id
)


def get(session: Session, assignment_id: UUID):
    row = session.execute(
        sa.select(*_OUT_COLS).select_from(_OUT_FROM).where(asg.c.id == assignment_id)
    ).one_or_none()
    if row is None:
        raise NotFound(f"assignment {assignment_id} not found")
    return row


def list_assignments(session: Session, filters: dict[str, Any], limit: int, offset: int
                     ) -> tuple[Sequence[Any], int]:
    conds: list[Any] = []
    if not filters.get("include_deleted"):
        conds.append(asg.c.deleted_at.is_(None))
    if (mid := filters.get("machine_id")) is not None:
        conds.append(asg.c.machine_id == mid)
    if (tid := filters.get("tool_id")) is not None:
        conds.append(asg.c.tool_id == tid)
    if (pr := filters.get("pending_review")) is not None:
        conds.append(asg.c.pending_review == pr)
    where = sa.and_(*conds) if conds else sa.true()
    total = session.execute(
        sa.select(sa.func.count()).select_from(asg).where(where)
    ).scalar_one()
    rows = session.execute(
        sa.select(*_OUT_COLS).select_from(_OUT_FROM).where(where)
        .order_by(machine_t.c.name, asg.c.t_number).limit(limit).offset(offset)
    ).all()
    return rows, total


def _active_conflict(session: Session, machine_id: UUID, col, value, *, exclude: UUID | None):
    if value is None:
        return False
    conds = [asg.c.machine_id == machine_id, col == value, asg.c.deleted_at.is_(None)]
    if exclude is not None:
        conds.append(asg.c.id != exclude)
    return session.execute(
        sa.select(1).select_from(asg).where(*conds).limit(1)
    ).one_or_none() is not None


def _validate_registers(session: Session, machine, tool, *, t_number, h_register,
                        d_register, exclude: UUID | None) -> None:
    # Probe-lock (Decision-4 / R12).
    if machine.probe_t_number is not None and t_number == machine.probe_t_number:
        raise Unprocessable(
            f"t_number {t_number} is the probe T# on '{machine.name}' and is locked",
            field="t_number",
        )
    if machine.probe_h_register is not None and h_register == machine.probe_h_register:
        raise Unprocessable(
            f"h_register {h_register} is the probe H register on '{machine.name}' and is locked",
            field="h_register",
        )
    # Uniqueness among active assignments.
    if _active_conflict(session, machine.id, asg.c.t_number, t_number, exclude=exclude):
        raise Conflict(f"t_number {t_number} already active on '{machine.name}'")
    if _active_conflict(session, machine.id, asg.c.h_register, h_register, exclude=exclude):
        raise Conflict(f"h_register {h_register} already active on '{machine.name}'")
    if _active_conflict(session, machine.id, asg.c.d_register, d_register, exclude=exclude):
        raise Conflict(f"d_register {d_register} already active on '{machine.name}'")
    # Capability.
    if tool.requires_tsc and not machine.has_tsc:
        raise Unprocessable(
            f"tool requires through-spindle coolant but '{machine.name}' has none",
            field="requires_tsc",
        )


def _load_tool(session: Session, tool_id: UUID):
    row = session.execute(sa.select(tool_t).where(tool_t.c.id == tool_id)).one_or_none()
    if row is None:
        raise NotFound(f"tool {tool_id} not found")
    if row.retired_at is not None:
        raise Unprocessable(f"tool {tool_id} is retired", field="tool_id")
    return row


def _load_machine(session: Session, machine_id: UUID, *, require_enabled: bool):
    row = session.execute(
        sa.select(machine_t).where(machine_t.c.id == machine_id)
    ).one_or_none()
    if row is None:
        raise NotFound(f"machine {machine_id} not found")
    if require_enabled and not row.enabled:
        raise Unprocessable(f"machine '{row.name}' is disabled", field="machine_id")
    return row


def create(session: Session, body: AssignmentCreate, assigned_by: UUID):
    tool = _load_tool(session, body.tool_id)
    machine = _load_machine(session, body.machine_id, require_enabled=True)
    _validate_registers(session, machine, tool, t_number=body.t_number,
                        h_register=body.h_register, d_register=body.d_register, exclude=None)
    row = session.execute(
        sa.insert(asg).values(
            tool_id=body.tool_id, machine_id=body.machine_id,
            t_number=body.t_number, h_register=body.h_register, d_register=body.d_register,
            pending_review=True,
            pending_reason="awaiting operator confirmation of FOCAS values",
            assigned_by=assigned_by,
        ).returning(asg.c.id)
    ).one()
    return get(session, row.id)


def update(session: Session, assignment_id: UUID, body: AssignmentUpdate):
    current = session.execute(
        sa.select(asg).where(asg.c.id == assignment_id)
    ).one_or_none()
    if current is None:
        raise NotFound(f"assignment {assignment_id} not found")
    if current.deleted_at is not None:
        raise Conflict("assignment is deleted")
    changes = body.model_dump(exclude_unset=True)
    t_number = changes.get("t_number", current.t_number)
    h_register = changes.get("h_register", current.h_register)
    d_register = changes.get("d_register", current.d_register)
    machine = _load_machine(session, current.machine_id, require_enabled=False)
    tool = session.execute(sa.select(tool_t).where(tool_t.c.id == current.tool_id)).one()
    _validate_registers(session, machine, tool, t_number=t_number, h_register=h_register,
                        d_register=d_register, exclude=assignment_id)
    # Register move re-opens confirmation.
    changes.update(pending_review=True, pending_reason="register assignment changed")
    session.execute(sa.update(asg).where(asg.c.id == assignment_id).values(**changes))
    return get(session, assignment_id)


def confirm(session: Session, assignment_id: UUID, confirmed_by: UUID):
    current = session.execute(sa.select(asg).where(asg.c.id == assignment_id)).one_or_none()
    if current is None:
        raise NotFound(f"assignment {assignment_id} not found")
    if current.deleted_at is not None:
        raise Conflict("assignment is deleted")
    session.execute(
        sa.update(asg).where(asg.c.id == assignment_id).values(
            pending_review=False, pending_reason=None,
            last_confirmed_at=datetime.now(UTC), last_confirmed_by=confirmed_by,
        )
    )
    return get(session, assignment_id)


def soft_delete(session: Session, assignment_id: UUID):
    current = session.execute(sa.select(asg).where(asg.c.id == assignment_id)).one_or_none()
    if current is None:
        raise NotFound(f"assignment {assignment_id} not found")
    if current.deleted_at is not None:
        raise Conflict("assignment already deleted")
    session.execute(
        sa.update(asg).where(asg.c.id == assignment_id)
        .values(deleted_at=datetime.now(UTC))
    )
