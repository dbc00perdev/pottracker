"""Diff a live `MachineSnapshot` against the persisted mirror, then UPSERT the
mirror and append change events to `shared.audit_log`.

Phase 2 read-side deliverable. NO writes to FANUC; NO schema DDL. Consumes the
zero-arg `SnapshotSource` surface (`FocasClient.read_snapshot()` / the mock).

Two layers, split so the interesting logic is DB-free and unit-testable:

  - `diff_*` (pure): given the current mirror state as plain dicts + the
    incoming snapshot tuples, compute the UPSERT params and the audit rows.
    No session, no I/O — the layer the unit tests exercise.

  - `persist` (I/O): SELECT current state, call the diff layer, execute the
    UPSERTs, write audit rows, and COMMIT once. A snapshot lands atomically
    or not at all.

Scope note — ALARMS ARE NOT PERSISTED HERE. Migration 0002 created mirror
tables for offsets / pots / tool_life only; there is no alarm table. Alarm
history needs its own table (a future migration 0003) — deliberately out of
scope rather than silently invented. `snapshot.alarms` is ignored for now.

`last_polled_at` advances every cycle for every observed row; `last_changed_at`
(offsets, pots) advances ONLY when the value actually changed — decided in SQL
via a CASE / IS DISTINCT FROM on conflict, so an unchanged re-read is a cheap
timestamp touch and never fabricates a change event. `focas_tool_life` has no
`last_changed_at` column (per the migration), so it just tracks latest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from shared.audit import record_audit
from shared.db import focas_macro_var, focas_offset_register, focas_pot, focas_tool_life
from shared.focas.models import (
    MachineSnapshot,
    MacroVariable,
    OffsetRegister,
    PotEntry,
    RegisterType,
    ToolLife,
)

# Event-type tags written to shared.audit_log.event_type.
_EVT_OFFSET = "offset_change"
_EVT_POT = "pot_move"
_EVT_TOOL_LIFE = "tool_life_change"
_EVT_MACRO = "macro_change"
_EVT_POT_REINIT = "pot_reinit_suspected"

# Pots simultaneously reverting to their own ordinal in a single poll cycle
# that trips the reset/reinit alarm. Pot cells are sticky — a removed tool KEEPS
# its number, it never reverts to the ordinal in normal operation — so several
# pots snapping to pot N == N at once is the signature of an operator resetting
# the machine mid-tool-change (tools physically ejected, PMC pot table
# reinitialised to N). Conservative: even a handful is abnormal.
_REINIT_MIN_POTS = 4

# The G31 skip system vars the tool presetter latches. A genuine change in any
# of these in the same poll cycle as an H_GEOM offset change attributes that
# write to the presetter (verified) vs a manual keypad edit (R11). Mirrors
# `shared.focas.client._SKIP_MACRO_VARS`; kept local so this pure DB module
# stays free of the ctypes-laden client import.
PRESETTER_SKIP_VARS: frozenset[int] = frozenset({5061, 5062, 5063})

# Attribution tags stored in shared.audit_log.after_value["source"].
_SRC_PRESETTER = "presetter_verified"
_SRC_MANUAL = "manual_edit"


@dataclass(frozen=True)
class _Audit:
    """One pending audit_log row (poller-driven: no user, success=True)."""

    event_type: str
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True)
class DomainDiff:
    """Result of diffing one domain: rows to UPSERT + change events to log."""

    upsert_params: list[dict[str, Any]]
    audits: list[_Audit]


@dataclass(frozen=True)
class PersistResult:
    """Per-snapshot summary. Surfaced by the soak's --persist reporting."""

    offsets_observed: int
    offsets_changed: int
    pots_observed: int
    pots_changed: int
    tool_life_observed: int
    tool_life_changed: int
    macros_observed: int = 0
    macros_changed: int = 0
    pot_reinit_suspected: bool = False

    @property
    def audit_rows(self) -> int:
        return (
            self.offsets_changed
            + self.pots_changed
            + self.tool_life_changed
            + self.macros_changed
            + (1 if self.pot_reinit_suspected else 0)
        )


# ============================================================================
# Pure diff layer — no DB, no session
# ============================================================================


def diff_offsets(
    current: dict[tuple[int, str], Decimal],
    incoming: tuple[OffsetRegister, ...],
    machine_id: UUID,
    polled_at: datetime,
    presetter_active: bool = False,
) -> DomainDiff:
    """`current` maps (register_number, register_type) -> stored value_mm.

    `presetter_active` is True when a G31 skip var changed in this same poll
    cycle (computed in `persist`). It tags the *source* of an H_GEOM change:
    only the tool presetter writes tool length (H_GEOM) offsets, so an H_GEOM
    transition with a fresh skip = presetter-verified; without one = a manual
    keypad edit (the R11 trust signal). Only genuine transitions are tagged
    (a first-observation baseline capture, `old is None`, is not an edit), and
    only H_GEOM (wear / diameter banks are not presetter-written)."""
    params: list[dict[str, Any]] = []
    audits: list[_Audit] = []
    for off in incoming:
        rtype = off.register_type.value
        key = (off.register_number, rtype)
        params.append(
            {
                "machine_id": machine_id,
                "register_number": off.register_number,
                "register_type": rtype,
                "value_mm": off.value_mm,
                "last_polled_at": polled_at,
                "last_changed_at": polled_at,
            }
        )
        old = current.get(key)
        if old is None or old != off.value_mm:
            after: dict[str, Any] = {"value_mm": str(off.value_mm)}
            if off.register_type is RegisterType.H_GEOM and old is not None:
                after["source"] = _SRC_PRESETTER if presetter_active else _SRC_MANUAL
            audits.append(
                _Audit(
                    event_type=_EVT_OFFSET,
                    entity_type="offset",
                    entity_id=f"{off.register_number}/{rtype}",
                    before=None if old is None else {"value_mm": str(old)},
                    after=after,
                )
            )
    return DomainDiff(params, audits)


def diff_pots(
    current: dict[int, int | None],
    incoming: tuple[PotEntry, ...],
    machine_id: UUID,
    polled_at: datetime,
) -> DomainDiff:
    """`current` maps pot_number -> stored t_number (None = empty)."""
    params: list[dict[str, Any]] = []
    audits: list[_Audit] = []
    for pot in incoming:
        params.append(
            {
                "machine_id": machine_id,
                "pot_number": pot.pot_number,
                "t_number": pot.t_number,
                "last_polled_at": polled_at,
                "last_changed_at": polled_at,
            }
        )
        present = pot.pot_number in current
        old = current.get(pot.pot_number)
        if not present or old != pot.t_number:
            audits.append(
                _Audit(
                    event_type=_EVT_POT,
                    entity_type="pot",
                    entity_id=str(pot.pot_number),
                    before=None if not present else {"t_number": old},
                    after={"t_number": pot.t_number},
                )
            )
    return DomainDiff(params, audits)


def detect_pot_reinit(
    current: dict[int, int | None],
    incoming: tuple[PotEntry, ...],
) -> list[int]:
    """Return the pot numbers that reverted to their own ordinal this cycle
    (had a different stored identity, now read pot N == N). A large batch is
    the PMC reinit/reset signature (see `_REINIT_MIN_POTS`)."""
    reverted: list[int] = []
    for pot in incoming:
        old = current.get(pot.pot_number)
        if pot.t_number == pot.pot_number and old is not None and old != pot.pot_number:
            reverted.append(pot.pot_number)
    return sorted(reverted)


def diff_macros(
    current: dict[int, Decimal | None],
    incoming: tuple[MacroVariable, ...],
    machine_id: UUID,
    polled_at: datetime,
) -> DomainDiff:
    """`current` maps macro number -> stored value (None = vacant). Values are
    Decimal; the JSON audit stores them as strings (None stays null)."""
    params: list[dict[str, Any]] = []
    audits: list[_Audit] = []
    for m in incoming:
        params.append(
            {
                "machine_id": machine_id,
                "number": m.number,
                "value": m.value,
                "last_polled_at": polled_at,
                "last_changed_at": polled_at,
            }
        )
        present = m.number in current
        old = current.get(m.number)
        if not present or old != m.value:
            audits.append(
                _Audit(
                    event_type=_EVT_MACRO,
                    entity_type="macro",
                    entity_id=str(m.number),
                    before=None if not present else {"value": None if old is None else str(old)},
                    after={"value": None if m.value is None else str(m.value)},
                )
            )
    return DomainDiff(params, audits)


def diff_tool_life(
    current: dict[int, tuple[int | None, int | None, str | None]],
    incoming: tuple[ToolLife, ...],
    machine_id: UUID,
    polled_at: datetime,
) -> DomainDiff:
    """`current` maps t_number -> (life_count, life_max, status)."""
    params: list[dict[str, Any]] = []
    audits: list[_Audit] = []
    for tl in incoming:
        status = tl.status.value if tl.status is not None else None
        params.append(
            {
                "machine_id": machine_id,
                "t_number": tl.t_number,
                "life_count": tl.life_count,
                "life_max": tl.life_max,
                "status": status,
                "last_polled_at": polled_at,
            }
        )
        old = current.get(tl.t_number)
        new = (tl.life_count, tl.life_max, status)
        # Audit on any change to count/max/status (a count DECREASE is a tool
        # reset/replace — as noteworthy as an increase, so don't filter it out).
        if old is None or old != new:
            audits.append(
                _Audit(
                    event_type=_EVT_TOOL_LIFE,
                    entity_type="tool_life",
                    entity_id=str(tl.t_number),
                    before=None
                    if old is None
                    else {"life_count": old[0], "life_max": old[1], "status": old[2]},
                    after={"life_count": tl.life_count, "life_max": tl.life_max, "status": status},
                )
            )
    return DomainDiff(params, audits)


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

    _upsert_offsets(session, d_off.upsert_params)
    _upsert_pots(session, d_pot.upsert_params)
    _upsert_macros(session, d_macro.upsert_params)
    _upsert_tool_life(session, d_tl.upsert_params)

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
    )


__all__ = [
    "DomainDiff",
    "PersistResult",
    "detect_pot_reinit",
    "diff_macros",
    "diff_offsets",
    "diff_pots",
    "diff_tool_life",
    "persist",
]
