"""Persist a live `MachineSnapshot` to the mirror: SELECT current state, diff via
the pure layer, UPSERT, append change events to `shared.audit_log`, COMMIT once.

Phase 2 read-side deliverable. NO writes to FANUC; NO schema DDL. Consumes the
zero-arg `SnapshotSource` surface (`FocasClient.read_snapshot()` / the mock).

The pure diff layer (given the current mirror state + the incoming snapshot,
compute UPSERT params and audit rows — no session, no I/O) lives in
`snapshot_diff.py` and is re-exported here, so `from shared.focas.snapshot import
persist, diff_offsets, ...` keeps resolving. This module is the I/O half:
`_load_*` / `_upsert_*` / `persist`.

Scope note — ALARMS ARE NOT PERSISTED HERE. Migration 0002 created mirror tables
for offsets / pots / tool_life only; there is no alarm table. `snapshot.alarms`
is ignored for now (a future migration would add one).

`last_polled_at` advances every cycle for every observed row; `last_changed_at`
(offsets, pots, macros, status) advances ONLY when the value actually changed —
decided in SQL via a CASE / IS DISTINCT FROM on conflict, so an unchanged re-read
is a cheap timestamp touch and never fabricates a change event. `focas_tool_life`
has no `last_changed_at` column (per the migration), so it just tracks latest.

Machine STATUS (HEAD/NEXT spindle state) is mirrored but NOT audited: HEAD/NEXT
change on every tool call during a running program, so per-change audit rows
would be pure noise (R17). The mirror + `last_changed_at` is the whole record.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from shared.audit import record_audit
from shared.db import (
    focas_machine_status,
    focas_macro_var,
    focas_offset_register,
    focas_pot,
    focas_tool_life,
)
from shared.focas.models import MachineSnapshot
from shared.focas.snapshot_diff import (
    _EVT_POT_REINIT,
    _REINIT_MIN_POTS,
    PRESETTER_SKIP_VARS,
    DomainDiff,
    PersistResult,
    StatusState,
    detect_pot_reinit,
    diff_macros,
    diff_offsets,
    diff_pots,
    diff_status,
    diff_tool_life,
)

# ============================================================================
# I/O layer — SELECT current, UPSERT, write audits, commit
# ============================================================================


def _load_offsets(session: Session, machine_id: UUID) -> dict[tuple[int, str], Decimal]:
    t = focas_offset_register
    rows = session.execute(
        sa.select(t.c.register_number, t.c.register_type, t.c.value_mm).where(
            t.c.machine_id == machine_id
        )
    )
    return {(r.register_number, r.register_type): r.value_mm for r in rows}


def _load_pots(session: Session, machine_id: UUID) -> dict[int, int | None]:
    t = focas_pot
    rows = session.execute(
        sa.select(t.c.pot_number, t.c.t_number).where(t.c.machine_id == machine_id)
    )
    return {r.pot_number: r.t_number for r in rows}


def _load_macros(session: Session, machine_id: UUID) -> dict[int, Decimal | None]:
    t = focas_macro_var
    rows = session.execute(
        sa.select(t.c.number, t.c.value).where(t.c.machine_id == machine_id)
    )
    return {r.number: r.value for r in rows}


def _load_tool_life(
    session: Session, machine_id: UUID
) -> dict[int, tuple[int | None, int | None, str | None]]:
    t = focas_tool_life
    rows = session.execute(
        sa.select(t.c.t_number, t.c.life_count, t.c.life_max, t.c.status).where(
            t.c.machine_id == machine_id
        )
    )
    return {r.t_number: (r.life_count, r.life_max, r.status) for r in rows}


def _load_status(session: Session, machine_id: UUID) -> StatusState | None:
    t = focas_machine_status
    row = session.execute(
        sa.select(
            t.c.head_t_number, t.c.next_t_number, t.c.mode, t.c.running, t.c.emergency_stop
        ).where(t.c.machine_id == machine_id)
    ).one_or_none()
    if row is None:
        return None
    return (row.head_t_number, row.next_t_number, row.mode, row.running, row.emergency_stop)


def _upsert_offsets(session: Session, params: list[dict[str, Any]]) -> None:
    if not params:
        return
    t = focas_offset_register
    stmt = pg_insert(t)
    stmt = stmt.on_conflict_do_update(
        index_elements=[t.c.machine_id, t.c.register_number, t.c.register_type],
        set_={
            "value_mm": stmt.excluded.value_mm,
            "last_polled_at": stmt.excluded.last_polled_at,
            # advance last_changed_at only when the value actually moved
            "last_changed_at": sa.case(
                (t.c.value_mm != stmt.excluded.value_mm, stmt.excluded.last_changed_at),
                else_=t.c.last_changed_at,
            ),
        },
    )
    session.execute(stmt, params)


def _upsert_pots(session: Session, params: list[dict[str, Any]]) -> None:
    if not params:
        return
    t = focas_pot
    stmt = pg_insert(t)
    stmt = stmt.on_conflict_do_update(
        index_elements=[t.c.machine_id, t.c.pot_number],
        set_={
            "t_number": stmt.excluded.t_number,
            "last_polled_at": stmt.excluded.last_polled_at,
            # t_number is nullable — IS DISTINCT FROM so NULL<->value counts
            "last_changed_at": sa.case(
                (
                    t.c.t_number.is_distinct_from(stmt.excluded.t_number),
                    stmt.excluded.last_changed_at,
                ),
                else_=t.c.last_changed_at,
            ),
        },
    )
    session.execute(stmt, params)


def _upsert_macros(session: Session, params: list[dict[str, Any]]) -> None:
    if not params:
        return
    t = focas_macro_var
    stmt = pg_insert(t)
    stmt = stmt.on_conflict_do_update(
        index_elements=[t.c.machine_id, t.c.number],
        set_={
            "value": stmt.excluded.value,
            "last_polled_at": stmt.excluded.last_polled_at,
            # value is nullable (vacant) — IS DISTINCT FROM so NULL<->value counts
            "last_changed_at": sa.case(
                (t.c.value.is_distinct_from(stmt.excluded.value), stmt.excluded.last_changed_at),
                else_=t.c.last_changed_at,
            ),
        },
    )
    session.execute(stmt, params)


def _upsert_tool_life(session: Session, params: list[dict[str, Any]]) -> None:
    if not params:
        return
    t = focas_tool_life
    stmt = pg_insert(t)
    stmt = stmt.on_conflict_do_update(
        index_elements=[t.c.machine_id, t.c.t_number],
        set_={
            "life_count": stmt.excluded.life_count,
            "life_max": stmt.excluded.life_max,
            "status": stmt.excluded.status,
            "last_polled_at": stmt.excluded.last_polled_at,
        },
    )
    session.execute(stmt, params)


def _upsert_status(session: Session, param: dict[str, Any]) -> None:
    t = focas_machine_status
    stmt = pg_insert(t)
    # Any of the observed fields moving counts as a change (all nullable, so
    # IS DISTINCT FROM handles NULL<->value transitions).
    changed = sa.or_(
        t.c.head_t_number.is_distinct_from(stmt.excluded.head_t_number),
        t.c.next_t_number.is_distinct_from(stmt.excluded.next_t_number),
        t.c.mode.is_distinct_from(stmt.excluded.mode),
        t.c.running.is_distinct_from(stmt.excluded.running),
        t.c.emergency_stop.is_distinct_from(stmt.excluded.emergency_stop),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[t.c.machine_id],
        set_={
            "head_t_number": stmt.excluded.head_t_number,
            "next_t_number": stmt.excluded.next_t_number,
            "mode": stmt.excluded.mode,
            "running": stmt.excluded.running,
            "emergency_stop": stmt.excluded.emergency_stop,
            "last_polled_at": stmt.excluded.last_polled_at,
            "last_changed_at": sa.case(
                (changed, stmt.excluded.last_changed_at), else_=t.c.last_changed_at
            ),
        },
    )
    session.execute(stmt, [param])


def persist(session: Session, snapshot: MachineSnapshot, machine_id: UUID) -> PersistResult:
    """Diff `snapshot` against the mirror for `machine_id`, UPSERT, log changes,
    and COMMIT. `machine_id` is the `shared.machine.id` UUID (resolved by the
    caller); `snapshot.machine_id` is the human string identifier, not the PK.
    """
    polled_at = snapshot.polled_at

    # Macros first: a genuine transition (prior value existed and differs) of a
    # skip var means the presetter's G31 touch fired this cycle. That flag tags
    # the source of any H_GEOM offset change below (presetter vs manual, R11).
    cur_macros = _load_macros(session, machine_id)
    presetter_active = any(
        m.number in PRESETTER_SKIP_VARS
        and m.number in cur_macros
        and cur_macros[m.number] != m.value
        for m in snapshot.macros
    )

    d_off = diff_offsets(
        _load_offsets(session, machine_id),
        snapshot.offsets,
        machine_id,
        polled_at,
        presetter_active=presetter_active,
    )
    cur_pots = _load_pots(session, machine_id)
    d_pot = diff_pots(cur_pots, snapshot.pots, machine_id, polled_at)
    reverted_pots = detect_pot_reinit(cur_pots, snapshot.pots)
    d_macro = diff_macros(cur_macros, snapshot.macros, machine_id, polled_at)
    d_tl = diff_tool_life(
        _load_tool_life(session, machine_id), snapshot.tool_life, machine_id, polled_at
    )
    status_param, status_changed = diff_status(
        _load_status(session, machine_id), snapshot.status, machine_id, polled_at
    )

    _upsert_offsets(session, d_off.upsert_params)
    _upsert_pots(session, d_pot.upsert_params)
    _upsert_macros(session, d_macro.upsert_params)
    _upsert_tool_life(session, d_tl.upsert_params)
    _upsert_status(session, status_param)

    for a in (*d_off.audits, *d_pot.audits, *d_macro.audits, *d_tl.audits):
        record_audit(
            session,
            event_type=a.event_type,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            machine_id=machine_id,
            before_value=a.before,
            after_value=a.after,
            occurred_at=polled_at,
        )

    # Reset/reinit alarm: a batch of pots snapping to their ordinals at once is
    # the signature of an operator resetting mid-tool-change — tools may have
    # been physically ejected (R10/R11). Record it as a non-success event so it
    # surfaces distinctly from routine pot moves.
    reinit_suspected = len(reverted_pots) >= _REINIT_MIN_POTS
    if reinit_suspected:
        record_audit(
            session,
            event_type=_EVT_POT_REINIT,
            entity_type="machine",
            entity_id=str(machine_id),
            machine_id=machine_id,
            after_value={"reverted_pots": reverted_pots, "count": len(reverted_pots)},
            success=False,
            occurred_at=polled_at,
        )

    session.commit()

    return PersistResult(
        offsets_observed=len(d_off.upsert_params),
        offsets_changed=len(d_off.audits),
        pots_observed=len(d_pot.upsert_params),
        pots_changed=len(d_pot.audits),
        tool_life_observed=len(d_tl.upsert_params),
        tool_life_changed=len(d_tl.audits),
        macros_observed=len(d_macro.upsert_params),
        macros_changed=len(d_macro.audits),
        pot_reinit_suspected=reinit_suspected,
        status_changed=status_changed,
    )


__all__ = [
    "DomainDiff",
    "PersistResult",
    "detect_pot_reinit",
    "diff_macros",
    "diff_offsets",
    "diff_pots",
    "diff_status",
    "diff_tool_life",
    "persist",
]
