"""Offset write-path lifecycle (PR-3) — mock-only, no live write.

Drives one `tooling.offset_write_request` row through
`request -> execute (mock) -> verify`, composing every guard the HARD GATE
requires. The register write itself goes through an injected `OffsetWriteTarget`
whose ONLY implementation today is the labeled mock (`shared.focas.mock`); the
real `cnc_wrtofs` binding is PR-4 and lands behind this exact same gate. Nothing
in this module talks to hardware.

Guard order at execute (fail-closed, worst-first):

  1. Double wall + mode-lockout + probe-lock — `write_safety.authorize_write`
     (R6/R12/R24). A block here leaves the request PENDING (fixable) and audits.
  2. Drift abort — re-read the live value; if it no longer matches the value
     captured at request time, the request is dead (R14).
  3. Plausibility — value in-bounds, and a change > 0.5 mm needs an explicit
     acknowledgement, never a silent write (R6).
  4. Write via the target, then mandatory read-after-write verification (R6).

Every execute attempt — permitted, blocked, or failed — writes an `audit_log`
row. The caller owns the transaction boundary (like the rest of the API).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from apps.tooling.api.config import Settings
from apps.tooling.api.errors import Conflict, Forbidden, NotFound, Unprocessable
from apps.tooling.api.services.write_safety import authorize_write
from apps.tooling.api.tables import offset_write_request as owr
from shared.audit import record_audit
from shared.db import machine as machine_t
from shared.focas import offset_math
from shared.focas.models import MachineStatus, RegisterType


class OffsetWriteTarget(Protocol):
    """The write surface the lifecycle drives. Implemented by the labeled mock
    (PR-3) and, later, by the real `cnc_wrtofs`-backed client (PR-4)."""

    def read_offset(self, register_number: int, register_type: RegisterType) -> Decimal: ...

    def write_offset(
        self, register_number: int, register_type: RegisterType, value_mm: Decimal
    ) -> None: ...


def _get_row(session: Session, request_id: UUID):
    row = session.execute(sa.select(owr).where(owr.c.id == request_id)).one_or_none()
    if row is None:
        raise NotFound(f"offset_write_request {request_id} not found")
    return row


def _load_machine(session: Session, machine_id: UUID):
    row = session.execute(
        sa.select(machine_t).where(machine_t.c.id == machine_id)
    ).one_or_none()
    if row is None:
        raise NotFound(f"machine {machine_id} not found")
    return row


def get(session: Session, request_id: UUID):
    return _get_row(session, request_id)


def create_request(
    session: Session,
    *,
    machine_id: UUID,
    register_number: int,
    register_type: RegisterType,
    intended_value_mm: Decimal,
    reason: str,
    requested_by: UUID,
    target: OffsetWriteTarget,
) -> UUID:
    """Stage an intended offset write. Validates writability (D2), the probe
    lock (R12), and value bounds, then captures the current live value so the
    execute step can detect drift. Does NOT write anything."""
    try:
        offset_math.assert_writable(register_type)
    except offset_math.OffsetMathError as exc:
        raise Unprocessable(str(exc), field="register_type") from exc

    if not offset_math.within_bounds(intended_value_mm):
        raise Unprocessable(
            f"intended value {intended_value_mm} mm is outside the offset envelope",
            field="intended_value_mm",
        )

    if not reason or not reason.strip():
        raise Unprocessable("a reason is required for every write (R20)", field="reason")

    machine = _load_machine(session, machine_id)
    if _is_probe_target(machine, register_number):
        raise Unprocessable(
            f"register {register_number} is the probe H register on '{machine.name}' "
            "and is locked (R12)",
            field="register_number",
        )

    current = target.read_offset(register_number, register_type)
    row = session.execute(
        sa.insert(owr)
        .values(
            machine_id=machine_id,
            register_number=register_number,
            register_type=register_type.value,
            intended_value_mm=intended_value_mm,
            current_value_mm=current,
            reason=reason.strip(),
            requested_by=requested_by,
        )
        .returning(owr.c.id)
    ).one()
    return row.id


def _is_probe_target(machine, register_number: int) -> bool:
    return machine.probe_h_register is not None and register_number == machine.probe_h_register


def _audit(session: Session, row, machine_id, user_id, *, success: bool, error: str | None,
           after: Decimal | None) -> None:
    record_audit(
        session,
        event_type="offset_write",
        entity_type="offset",
        entity_id=f"{row.register_number}/{row.register_type}",
        machine_id=machine_id,
        user_id=user_id,
        before_value={"value_mm": str(row.current_value_mm)}
        if row.current_value_mm is not None else None,
        after_value={"value_mm": str(after)} if after is not None else None,
        reason=row.reason,
        success=success,
        error=error,
    )


def _fail(session: Session, request_id: UUID, machine_id, user_id, row, *,
          error: str, verified: Decimal | None, exc_cls, http_detail: str):
    """Mark the request executed-and-failed, audit, and raise. A failed request
    is terminal — the operator re-requests after re-reading."""
    now = datetime.now(UTC)
    session.execute(
        sa.update(owr).where(owr.c.id == request_id).values(
            confirmed_by=user_id, confirmed_at=now, executed_at=now,
            verified_value_mm=verified, success=False, error=error,
        )
    )
    _audit(session, row, machine_id, user_id, success=False, error=error, after=None)
    raise exc_cls(http_detail)


def execute_request(
    session: Session,
    request_id: UUID,
    *,
    executing_user: UUID,
    status: MachineStatus,
    approved: bool,
    password_attempt: str,
    settings: Settings,
    target: OffsetWriteTarget,
    large_diff_acknowledged: bool = False,
):
    """Run the gate and, if it fully passes, perform the mock write + verify.

    A gate block (mode/ask/entry/probe) leaves the request PENDING and raises
    403 — the operator can fix the wall and retry. Drift, a rejected write, or a
    read-after-write mismatch mark the request failed (terminal) and raise."""
    row = _get_row(session, request_id)
    if row.executed_at is not None:
        raise Conflict("offset_write_request already executed")

    machine = _load_machine(session, row.machine_id)
    reg_type = RegisterType(row.register_type)
    intended = Decimal(row.intended_value_mm)

    # 1. Double wall + mode-lockout + probe-lock. Block leaves the row pending.
    auth = authorize_write(
        status=status,
        is_probe_target=_is_probe_target(machine, row.register_number),
        approved=approved,
        password_attempt=password_attempt,
        settings=settings,
    )
    if not auth.permitted:
        _audit(session, row, row.machine_id, executing_user,
               success=False, error=auth.reason, after=None)
        raise Forbidden(auth.reason)

    # 2. Drift abort (R14) — the world moved since the request was staged.
    live = target.read_offset(row.register_number, reg_type)
    if row.current_value_mm is not None and live != Decimal(row.current_value_mm):
        _fail(session, request_id, row.machine_id, executing_user, row,
              error=f"drift: register now {live}, was {row.current_value_mm} at request time",
              verified=live, exc_cls=Conflict,
              http_detail="register changed since the request was staged — write aborted (R14)")

    # 3. Plausibility (R6).
    if not offset_math.within_bounds(intended):
        raise Unprocessable(f"intended value {intended} mm is out of bounds")
    if offset_math.is_large_diff(live, intended) and not large_diff_acknowledged:
        raise Unprocessable(
            f"change of {offset_math.diff_mm(live, intended)} mm exceeds "
            f"{offset_math.LARGE_DIFF_THRESHOLD_MM} mm — explicit acknowledgement required (R6)",
            field="large_diff_acknowledged",
        )

    # 4. Write (mock) + mandatory read-after-write verification (R6).
    try:
        target.write_offset(row.register_number, reg_type, intended)
    except Exception as exc:  # control refused the write
        _fail(session, request_id, row.machine_id, executing_user, row,
              error=f"write rejected: {exc}", verified=None, exc_cls=Conflict,
              http_detail=f"the control rejected the write: {exc}")

    verified = target.read_offset(row.register_number, reg_type)
    if verified != intended:
        _fail(session, request_id, row.machine_id, executing_user, row,
              error=f"read-after-write mismatch: wrote {intended}, read {verified}",
              verified=verified, exc_cls=Conflict,
              http_detail="read-after-write verification failed — value not applied (R6)")

    now = datetime.now(UTC)
    session.execute(
        sa.update(owr).where(owr.c.id == request_id).values(
            confirmed_by=executing_user, confirmed_at=now, executed_at=now,
            verified_value_mm=verified, success=True, error=None,
        )
    )
    _audit(session, row, row.machine_id, executing_user, success=True, error=None, after=verified)
    return _get_row(session, request_id)


def execute_batch(
    session: Session,
    request_ids: list[UUID],
    *,
    executing_user: UUID,
    status: MachineStatus,
    approved: bool,
    password_attempt: str,
    settings: Settings,
    target: OffsetWriteTarget,
    large_diff_acknowledged: bool = False,
) -> list[dict]:
    """D1 batch: one ask + one password entry authorizes multiple registers, but
    each register is executed, drift-checked, and verified independently — a
    failure on one does NOT abort the others. Returns a per-request outcome."""
    results: list[dict] = []
    for rid in request_ids:
        try:
            execute_request(
                session, rid, executing_user=executing_user, status=status,
                approved=approved, password_attempt=password_attempt, settings=settings,
                target=target, large_diff_acknowledged=large_diff_acknowledged,
            )
            results.append({"request_id": str(rid), "success": True, "error": None})
        except (Forbidden, Conflict, Unprocessable) as exc:
            results.append({"request_id": str(rid), "success": False, "error": exc.detail})
    return results
