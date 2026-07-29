"""Pure diff layer for the FOCAS snapshot mirror — no DB, no session.

Split out of `snapshot.py` (which kept the I/O half) so the interesting logic
stays DB-free and unit-testable. Given the current mirror state as plain dicts +
the incoming snapshot tuples, each `diff_*` computes the UPSERT params and the
audit rows. `snapshot.py` re-exports everything here, so
`from shared.focas.snapshot import diff_offsets, ...` keeps resolving.

`last_polled_at` advances every cycle for every observed row; `last_changed_at`
(offsets, pots, macros, status) advances ONLY when the value actually changed —
the decision is made in SQL (I/O layer) via a CASE / IS DISTINCT FROM on
conflict, so an unchanged re-read is a cheap timestamp touch and never fabricates
a change event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from shared.focas.models import (
    MachineStatus,
    MacroVariable,
    OffsetRegister,
    PotEntry,
    RegisterType,
    ToolLife,
    WorkOffsetEntry,
)

# Event-type tags written to shared.audit_log.event_type.
_EVT_OFFSET = "offset_change"
_EVT_POT = "pot_move"
_EVT_TOOL_LIFE = "tool_life_change"
_EVT_MACRO = "macro_change"
_EVT_POT_REINIT = "pot_reinit_suspected"
_EVT_WORK_OFFSET = "work_offset_change"

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
# `shared.focas.client._SKIP_MACRO_VARS`; kept local so this pure module stays
# free of the ctypes-laden client import.
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
    status_changed: bool = False
    work_offsets_observed: int = 0
    work_offsets_changed: int = 0

    @property
    def audit_rows(self) -> int:
        return (
            self.offsets_changed
            + self.pots_changed
            + self.tool_life_changed
            + self.macros_changed
            + self.work_offsets_changed
            + (1 if self.pot_reinit_suspected else 0)
        )


# Stored machine-status tuple: (head_t, next_t, mode, running, emergency_stop).
StatusState = tuple[int | None, int | None, str | None, bool | None, bool | None]


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


def diff_work_offsets(
    current: dict[tuple[str, str], Decimal],
    incoming: tuple[WorkOffsetEntry, ...],
    machine_id: UUID,
    polled_at: datetime,
) -> DomainDiff:
    """`current` maps (slot, axis) -> stored value. Work offsets are per-job
    setup state (T1 sets the WORK SHIFT on the VT), so changes ARE audited —
    low churn, high signal. First observation is a baseline capture (before
    None), consistent with the offset domain."""
    params: list[dict[str, Any]] = []
    audits: list[_Audit] = []
    for wo in incoming:
        slot = wo.slot.value
        key = (slot, wo.axis)
        params.append(
            {
                "machine_id": machine_id,
                "slot": slot,
                "axis": wo.axis,
                "value": wo.value,
                "last_polled_at": polled_at,
                "last_changed_at": polled_at,
            }
        )
        old = current.get(key)
        if old is None or old != wo.value:
            audits.append(
                _Audit(
                    event_type=_EVT_WORK_OFFSET,
                    entity_type="work_offset",
                    entity_id=f"{slot}/{wo.axis}",
                    before=None if old is None else {"value": str(old)},
                    after={"value": str(wo.value)},
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


def diff_status(
    current: StatusState | None,
    incoming: MachineStatus,
    machine_id: UUID,
    polled_at: datetime,
) -> tuple[dict[str, Any], bool]:
    """Diff the single machine-status row: returns (upsert_param, changed).

    `current` is the stored (head, next, mode, running, emergency_stop) tuple, or
    None when no row exists yet. HEAD/NEXT churn every tool change, so status is
    NOT audited (R17) — the mirror + `last_changed_at` is the whole record. The
    returned `changed` flag drives `PersistResult.status_changed` reporting; the
    I/O layer decides `last_changed_at` authoritatively in SQL."""
    mode = incoming.mode.value
    param = {
        "machine_id": machine_id,
        "head_t_number": incoming.current_t_number,
        "next_t_number": incoming.next_t_number,
        "mode": mode,
        "running": incoming.running,
        "emergency_stop": incoming.emergency_stop,
        "last_polled_at": polled_at,
        "last_changed_at": polled_at,
    }
    new: StatusState = (
        incoming.current_t_number,
        incoming.next_t_number,
        mode,
        incoming.running,
        incoming.emergency_stop,
    )
    changed = current is None or current != new
    return param, changed


__all__ = [
    "DomainDiff",
    "PersistResult",
    "StatusState",
    "detect_pot_reinit",
    "diff_macros",
    "diff_offsets",
    "diff_pots",
    "diff_status",
    "diff_tool_life",
    "diff_work_offsets",
]
