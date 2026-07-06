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
from shared.db import focas_offset_register as f_off
from shared.db import focas_pot as f_pot
from shared.db import focas_tool_life as f_life
from shared.db import machine as machine_t


def tcp_probe(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _last_polled(session: Session, machine_id: UUID) -> datetime | None:
    stamps = []
    for tbl in (f_off, f_pot, f_life):
        stamps.append(session.execute(
            sa.select(sa.func.max(tbl.c.last_polled_at)).where(tbl.c.machine_id == machine_id)
        ).scalar_one())
    present = [s for s in stamps if s is not None]
    return max(present) if present else None


def focas_state(session: Session, machine_id: UUID, poll_interval: int) -> dict[str, Any]:
    last = _last_polled(session, machine_id)
    if last is None:
        return {"connected": False, "last_polled_at": None, "lag_seconds": None}
    lag = (datetime.now(UTC) - last).total_seconds()
    threshold = poll_interval * get_settings().health_stale_multiple
    return {"connected": lag <= threshold, "last_polled_at": last, "lag_seconds": lag}


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


def offsets(session: Session, machine_id: UUID, register_type: str | None) -> Sequence[Any]:
    get_row(session, machine_id)
    conds: list[Any] = [f_off.c.machine_id == machine_id]
    if register_type:
        conds.append(f_off.c.register_type == register_type)
    return session.execute(
        sa.select(f_off).where(*conds)
        .order_by(f_off.c.register_number, f_off.c.register_type)
    ).all()


def pots(session: Session, machine_id: UUID) -> Sequence[Any]:
    get_row(session, machine_id)
    return session.execute(
        sa.select(f_pot).where(f_pot.c.machine_id == machine_id).order_by(f_pot.c.pot_number)
    ).all()


def tool_life(session: Session, machine_id: UUID) -> Sequence[Any]:
    get_row(session, machine_id)
    return session.execute(
        sa.select(f_life).where(f_life.c.machine_id == machine_id).order_by(f_life.c.t_number)
    ).all()


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
