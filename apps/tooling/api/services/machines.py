"""Machine queries + FOCAS mirror reads + inferred connection state.

FOCAS "connection" state (D-F): Phase 3 runs no live poller in the API
process. `connected` is inferred from mirror freshness — the most recent
`last_polled_at` across `shared.focas_*` for the machine. A machine is
"connected" when that timestamp is within `health_stale_multiple x
poll_interval_seconds` of now. This is honest: it reports "the mirror is
fresh", never a live socket the API doesn't hold (R11).

`create` runs a plain TCP reachability probe to `ip:port` (D-G) — enough to
prove the FOCAS port is open without the DLLs/thread-affinity machinery.
`skip_probe=True` bypasses it for seeds/tests/offline adds.
"""

from __future__ import annotations

import socket
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.tooling.api.config import get_settings
from apps.tooling.api.errors import Conflict, NotFound, Unprocessable
from apps.tooling.api.schemas.machine import MachineCreate, MachineUpdate
from shared.db import audit_log as audit_t
from shared.db import focas_machine_status as f_status
from shared.db import focas_offset_register as f_off
from shared.db import focas_pot as f_pot
from shared.db import focas_tool_life as f_life
from shared.db import focas_work_offset as f_wo
from shared.db import machine as machine_t


def tcp_probe(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _last_polled(session: Session, machine_id: UUID) -> datetime | None:
    stamps = []
    for tbl in (f_off, f_pot, f_life, f_status):
        stamps.append(session.execute(
            sa.select(sa.func.max(tbl.c.last_polled_at)).where(tbl.c.machine_id == machine_id)
        ).scalar_one())
    present = [s for s in stamps if s is not None]
    return max(present) if present else None


def _status_glance(session: Session, machine_id: UUID) -> dict[str, Any]:
    """Shop-at-a-glance fields from the status mirror (running / mode /
    e-stop / program). All None when the poller has never persisted a row."""
    row = session.execute(
        sa.select(
            f_status.c.running, f_status.c.mode, f_status.c.emergency_stop,
            f_status.c.program_number, f_status.c.program_name,
        ).where(f_status.c.machine_id == machine_id)
    ).one_or_none()
    if row is None:
        return {
            "running": None, "mode": None, "emergency_stop": None,
            "program_number": None, "program_name": None,
        }
    return {
        "running": row.running,
        "mode": row.mode,
        "emergency_stop": row.emergency_stop,
        "program_number": row.program_number,
        "program_name": row.program_name,
    }


def focas_state(session: Session, machine_id: UUID, poll_interval: int) -> dict[str, Any]:
    glance = _status_glance(session, machine_id)
    last = _last_polled(session, machine_id)
    if last is None:
        return {"connected": False, "last_polled_at": None, "lag_seconds": None, **glance}
    lag = (datetime.now(UTC) - last).total_seconds()
    threshold = poll_interval * get_settings().health_stale_multiple
    return {"connected": lag <= threshold, "last_polled_at": last, "lag_seconds": lag, **glance}


def _to_out(session: Session, row: Any) -> dict[str, Any]:
    d = {k: row._mapping[k] for k in machine_t.c.keys()}
    d["ip_address"] = str(d["ip_address"])
    d["focas_state"] = focas_state(session, row.id, row.poll_interval_seconds)
    return d


def get_row(session: Session, machine_id: UUID):
    row = session.execute(sa.select(machine_t).where(machine_t.c.id == machine_id)).one_or_none()
    if row is None:
        raise NotFound(f"machine {machine_id} not found")
    return row


def get(session: Session, machine_id: UUID) -> dict[str, Any]:
    return _to_out(session, get_row(session, machine_id))


def list_machines(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(sa.select(machine_t).order_by(machine_t.c.name)).all()
    return [_to_out(session, r) for r in rows]


def create(session: Session, body: MachineCreate, *, skip_probe: bool) -> dict[str, Any]:
    if not skip_probe and not tcp_probe(body.ip_address, body.focas_port):
        raise Unprocessable(
            f"FOCAS port {body.focas_port} not reachable at {body.ip_address}; "
            "pass skip_probe=true to add anyway",
            field="ip_address",
        )
    values = body.model_dump()
    try:
        row = session.execute(sa.insert(machine_t).values(**values).returning(machine_t)).one()
    except IntegrityError as exc:
        raise Conflict(f"machine name '{body.name}' already exists") from exc
    return _to_out(session, row)


def update(session: Session, machine_id: UUID, body: MachineUpdate) -> dict[str, Any]:
    get_row(session, machine_id)  # 404 if missing
    changes = body.model_dump(exclude_unset=True)
    if changes:
        changes["updated_at"] = datetime.now(UTC)
        try:
            session.execute(
                sa.update(machine_t).where(machine_t.c.id == machine_id).values(**changes)
            )
        except IntegrityError as exc:
            raise Conflict(f"machine name '{changes.get('name')}' already exists") from exc
    return get(session, machine_id)


def work_offsets(session: Session, machine_id: UUID) -> Sequence[Any]:
    """Work coordinate offsets + WORK SHIFT mirror (lathe v1.1)."""
    get_row(session, machine_id)
    return session.execute(
        sa.select(f_wo).where(f_wo.c.machine_id == machine_id)
        .order_by(f_wo.c.slot, f_wo.c.axis)
    ).all()


def offsets(session: Session, machine_id: UUID, register_type: str | None) -> Sequence[Any]:
    get_row(session, machine_id)
    conds: list[Any] = [f_off.c.machine_id == machine_id]
    if register_type:
        conds.append(f_off.c.register_type == register_type)
    return session.execute(
        sa.select(f_off).where(*conds)
        .order_by(f_off.c.register_number, f_off.c.register_type)
    ).all()


def tool_life(session: Session, machine_id: UUID) -> Sequence[Any]:
    get_row(session, machine_id)
    return session.execute(
        sa.select(f_life).where(f_life.c.machine_id == machine_id).order_by(f_life.c.t_number)
    ).all()


def spindle(session: Session, machine_id: UUID) -> dict[str, Any]:
    """Live spindle/load state from the status mirror (HEAD = tool in spindle,
    NEXT = tool on deck). 404 if the machine is unknown; all fields None when no
    status row has been persisted yet (poller hasn't run)."""
    get_row(session, machine_id)  # 404 if missing
    row = session.execute(
        sa.select(f_status).where(f_status.c.machine_id == machine_id)
    ).one_or_none()
    if row is None:
        return {
            "head_t_number": None, "next_t_number": None, "mode": None,
            "running": None, "emergency_stop": None, "active_wcs": None,
            "program_number": None, "program_name": None,
            "last_tool_t_word": None, "last_tool_at": None,
            "last_polled_at": None, "last_changed_at": None,
        }
    return {
        "head_t_number": row.head_t_number,
        "next_t_number": row.next_t_number,
        "mode": row.mode,
        "running": row.running,
        "emergency_stop": row.emergency_stop,
        "active_wcs": row.active_wcs,
        "program_number": row.program_number,
        "program_name": row.program_name,
        "last_tool_t_word": row.last_tool_t_word,
        "last_tool_at": row.last_tool_at,
        "last_polled_at": row.last_polled_at,
        "last_changed_at": row.last_changed_at,
    }


def offset_changes(session: Session, machine_id: UUID) -> list[dict[str, Any]]:
    """Latest `offset_change` audit row per register/bank (hover detail).

    The poller audits every offset transition with entity_id
    "<register>/<type>" and after_value {"value_mm": ..., "source"?: ...}
    (shared/focas/snapshot_diff.diff_offsets). DISTINCT ON keeps only the
    newest row per entity — one round-trip for the whole table."""
    get_row(session, machine_id)  # 404 if missing
    rows = session.execute(
        sa.select(audit_t.c.entity_id, audit_t.c.occurred_at,
                  audit_t.c.before_value, audit_t.c.after_value)
        .where(
            audit_t.c.machine_id == machine_id,
            audit_t.c.event_type == "offset_change",
            audit_t.c.entity_type == "offset",
            audit_t.c.success.is_(True),
        )
        .distinct(audit_t.c.entity_id)
        .order_by(audit_t.c.entity_id, audit_t.c.occurred_at.desc(), audit_t.c.id.desc())
    ).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        register, _, register_type = r.entity_id.partition("/")
        if not register.isdigit() or not register_type:
            continue  # foreign entity_id shape — never guess (R11)
        before = r.before_value or {}
        after = r.after_value or {}
        out.append({
            "register_number": int(register),
            "register_type": register_type,
            "changed_at": r.occurred_at,
            "old_value": before.get("value_mm"),
            "new_value": after.get("value_mm"),
            "source": after.get("source"),
        })
    out.sort(key=lambda c: (c["register_number"], c["register_type"]))
    return out


def health(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        sa.select(machine_t.c.id, machine_t.c.name, machine_t.c.poll_interval_seconds)
        .where(machine_t.c.retired_at.is_(None)).order_by(machine_t.c.name)
    ).all()
    out = []
    for r in rows:
        st = focas_state(session, r.id, r.poll_interval_seconds)
        out.append({
            "id": r.id, "name": r.name, "focas_connected": st["connected"],
            "last_polled_at": st["last_polled_at"], "lag_seconds": st["lag_seconds"],
        })
    return out
