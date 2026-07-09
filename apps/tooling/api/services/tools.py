"""Tool queries: list/create/get/update/retire/duplicate.

Returns dicts shaped for `ToolOut` (nested tool_type + active assignments) so
routers stay thin. Active assignment = `deleted_at IS NULL`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.tooling.api.errors import Conflict, NotFound
from apps.tooling.api.schemas.tool import ToolCreate, ToolUpdate
from apps.tooling.api.services.tool_label import tool_description
from apps.tooling.api.tables import assignment as asg
from apps.tooling.api.tables import tool as tool_t
from apps.tooling.api.tables import tool_type as tt
from shared.db import machine as machine_t


def _description(d: dict[str, Any], type_code: str, type_display: str) -> str:
    """Canonical generated description from a tool-row mapping + its type."""
    return tool_description(
        type_code=type_code,
        type_display=type_display,
        diameter_mm=d.get("diameter_mm"),
        diameter_inch=d.get("diameter_inch"),
        flute_count=d.get("flute_count"),
        substrate=d.get("substrate"),
        coating=d.get("coating"),
        corner_radius_mm=d.get("corner_radius_mm"),
    )


def _assignments_for(session: Session, tool_ids: list[UUID]) -> dict[UUID, list[dict[str, Any]]]:
    if not tool_ids:
        return {}
    rows = session.execute(
        sa.select(
            asg.c.tool_id, asg.c.machine_id, machine_t.c.name.label("machine_name"),
            asg.c.t_number, asg.c.h_register, asg.c.d_register,
        )
        .select_from(asg.join(machine_t, asg.c.machine_id == machine_t.c.id))
        .where(asg.c.tool_id.in_(tool_ids), asg.c.deleted_at.is_(None))
    ).all()
    out: dict[UUID, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r.tool_id, []).append({
            "machine_id": r.machine_id, "machine_name": r.machine_name,
            "t_number": r.t_number, "h_register": r.h_register, "d_register": r.d_register,
        })
    return out


def _to_out(tool_row: Any, type_row: Any, assignments: list[dict[str, Any]]) -> dict[str, Any]:
    d = dict(tool_row._mapping)
    d["tool_type"] = {"code": type_row.code, "display_name": type_row.display_name}
    d["description"] = _description(d, type_row.code, type_row.display_name)
    d["assignments"] = assignments
    return d


def _get_row(session: Session, tool_id: UUID):
    row = session.execute(sa.select(tool_t).where(tool_t.c.id == tool_id)).one_or_none()
    if row is None:
        raise NotFound(f"tool {tool_id} not found")
    return row


def _type_row(session: Session, type_id: UUID):
    row = session.execute(sa.select(tt).where(tt.c.id == type_id)).one_or_none()
    if row is None:
        raise NotFound(f"tool_type {type_id} not found")
    return row


def get(session: Session, tool_id: UUID) -> dict[str, Any]:
    row = _get_row(session, tool_id)
    type_row = _type_row(session, row.tool_type_id)
    return _to_out(row, type_row, _assignments_for(session, [tool_id]).get(tool_id, []))


def list_tools(session: Session, filters: dict[str, Any], limit: int, offset: int
               ) -> tuple[list[dict[str, Any]], int]:
    j = tool_t.join(tt, tool_t.c.tool_type_id == tt.c.id)
    conds: list[Any] = []
    if not filters.get("include_retired"):
        conds.append(tool_t.c.retired_at.is_(None))
    if (q := filters.get("q")):
        like = f"%{q}%"
        conds.append(sa.or_(
            tool_t.c.short_id.ilike(like),
            tool_t.c.vendor_part_number.ilike(like),
            tool_t.c.manufacturer.ilike(like),
            tool_t.c.edp_number.ilike(like),
            tool_t.c.notes.ilike(like),
        ))
    if (code := filters.get("tool_type")):
        conds.append(tt.c.code == code)
    if (v := filters.get("diameter_mm_min")) is not None:
        conds.append(tool_t.c.diameter_mm >= v)
    if (v := filters.get("diameter_mm_max")) is not None:
        conds.append(tool_t.c.diameter_mm <= v)
    if (v := filters.get("flute_count")) is not None:
        conds.append(tool_t.c.flute_count == v)
    if (v := filters.get("substrate")):
        conds.append(tool_t.c.substrate == v)
    if (v := filters.get("coating")):
        conds.append(tool_t.c.coating == v)
    if (v := filters.get("requires_tsc")) is not None:
        conds.append(tool_t.c.requires_tsc == v)

    # Assignment-based filters via EXISTS on active assignments.
    assigned = filters.get("assigned")
    machine_id = filters.get("assigned_machine_id")
    if assigned is not None or machine_id is not None:
        sub = sa.select(1).select_from(asg).where(
            asg.c.tool_id == tool_t.c.id, asg.c.deleted_at.is_(None)
        )
        if machine_id is not None:
            sub = sub.where(asg.c.machine_id == machine_id)
        exists = sub.exists()
        conds.append(exists if (assigned or machine_id is not None) else ~exists)

    where = sa.and_(*conds) if conds else sa.true()
    total = session.execute(
        sa.select(sa.func.count()).select_from(j).where(where)
    ).scalar_one()
    rows = session.execute(
        sa.select(tool_t, tt.c.code, tt.c.display_name)
        .select_from(j).where(where)
        .order_by(tool_t.c.short_id).limit(limit).offset(offset)
    ).all()
    tool_ids = [r.id for r in rows]
    amap = _assignments_for(session, tool_ids)
    items: list[dict[str, Any]] = []
    for r in rows:
        d = {k: r._mapping[k] for k in tool_t.c.keys()}
        d["tool_type"] = {"code": r.code, "display_name": r.display_name}
        d["description"] = _description(d, r.code, r.display_name)
        d["assignments"] = amap.get(r.id, [])
        items.append(d)
    return items, total


def create(session: Session, body: ToolCreate, created_by: UUID) -> dict[str, Any]:
    _type_row(session, body.tool_type_id)  # 404 if missing
    values = body.model_dump()
    values["created_by"] = created_by
    try:
        row = session.execute(sa.insert(tool_t).values(**values).returning(tool_t)).one()
    except IntegrityError as exc:
        raise Conflict(f"short_id '{body.short_id}' already exists") from exc
    return get(session, row.id)


def update(session: Session, tool_id: UUID, body: ToolUpdate) -> tuple[dict, dict]:
    before = _get_row(session, tool_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return get(session, tool_id), {}
    if "tool_type_id" in changes:
        _type_row(session, changes["tool_type_id"])
    changes["updated_at"] = datetime.now(UTC)
    try:
        session.execute(sa.update(tool_t).where(tool_t.c.id == tool_id).values(**changes))
    except IntegrityError as exc:
        raise Conflict(f"short_id '{changes.get('short_id')}' already exists") from exc
    diff = {k: {"old": _json(before._mapping[k]), "new": _json(v)}
            for k, v in changes.items() if k != "updated_at"}
    return get(session, tool_id), diff


def retire(session: Session, tool_id: UUID, *, force: bool, is_admin: bool) -> dict[str, Any]:
    row = _get_row(session, tool_id)
    if row.retired_at is not None:
        raise Conflict(f"tool {tool_id} already retired")
    active = session.execute(
        sa.select(sa.func.count()).select_from(asg)
        .where(asg.c.tool_id == tool_id, asg.c.deleted_at.is_(None))
    ).scalar_one()
    if active and not (force and is_admin):
        raise Conflict(
            f"tool has {active} active assignment(s); retire requires force=true + admin",
            active_assignments=active,
        )
    session.execute(
        sa.update(tool_t).where(tool_t.c.id == tool_id)
        .values(retired_at=datetime.now(UTC))
    )
    return get(session, tool_id)


def duplicate(session: Session, tool_id: UUID, new_short_id: str, created_by: UUID
              ) -> dict[str, Any]:
    src = _get_row(session, tool_id)
    values = {k: src._mapping[k] for k in tool_t.c.keys()}
    for drop in ("id", "created_at", "updated_at", "retired_at", "created_by"):
        values.pop(drop, None)
    values["short_id"] = new_short_id
    values["created_by"] = created_by
    try:
        row = session.execute(sa.insert(tool_t).values(**values).returning(tool_t)).one()
    except IntegrityError as exc:
        raise Conflict(f"short_id '{new_short_id}' already exists") from exc
    return get(session, row.id)


def _json(v: Any) -> Any:
    """Coerce a value to something JSON-serializable for the audit log."""
    from decimal import Decimal
    if isinstance(v, Decimal | datetime | UUID):
        return str(v)
    return v
