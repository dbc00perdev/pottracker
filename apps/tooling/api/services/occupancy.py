"""Pot occupancy model — correlates pot IDENTITY (the PMC pot table) with tool
PRESENCE (the offset mirror) and the app's assignment records.

The R10/R11 split made concrete (see `tasks/lessons.md`):

  - The PMC pot cell (D105-128) gives IDENTITY only — which T# nominally lives
    in a pot. It is STICKY (retains the last tool, or reinitialises to the pot
    ordinal on a reset), so it never reliably signals presence.
  - The OFFSET is presence truth: a tool only becomes real when the presetter
    measures it and writes its H-geom length offset; decommissioning zeroes it.
    So `h_geom != 0` = a measured tool is really there, `0` = empty.
  - A pot's tool maps to its offset register via the app's ASSIGNMENT record
    (`t_number -> h_register`), never by assuming H == T (docs/09: T != H).

States (per pot):

  probe      — the reserved probe pot (never assignable, R12).
  loaded     — identity present, an active assignment maps it to an H register,
               and that h_geom offset is non-zero. `verified` is True when the
               latest change to that offset was presetter-tagged (#2 attribution).
  empty      — confirmed absent: assignment maps to an h_geom offset that is 0,
               OR the pot reads its own ordinal with no active assignment (the
               reinit/empty sentinel), OR the pot cell carries no identity.
  unverified — identity is known (a non-ordinal T#) but there is no active
               assignment to map it to an offset, so presence cannot be
               confirmed. We show the nominal T# but never claim it present (R11).

This module is API-layer (it joins `tooling.assignment` with the `shared.focas_*`
mirrors); `shared/` stays schema-isolated and knows nothing about `tooling.*`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from apps.tooling.api.errors import NotFound
from apps.tooling.api.tables import assignment as asg
from shared.db import audit_log, focas_machine_status, focas_offset_register, focas_pot
from shared.db import machine as machine_t

_H_GEOM = "h_geom"
_SRC_PRESETTER = "presetter_verified"


class PotState(StrEnum):
    PROBE = "probe"
    LOADED = "loaded"
    EMPTY = "empty"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class PotOccupancy:
    pot_number: int
    t_number: int | None
    state: PotState
    verified: bool
    assigned_h_register: int | None
    offset_mm: Decimal | None


def classify_pot(
    pot_number: int,
    t_number: int | None,
    probe_pot: int | None,
    h_register: int | None,
    offset_mm: Decimal | None,
    presetter_verified: bool,
) -> PotOccupancy:
    """Pure occupancy classification for one pot. `h_register` is the active
    assignment's H register (None = no active assignment for this pot's tool);
    `offset_mm` is that register's mirrored h_geom value (None = not mirrored)."""
    if probe_pot is not None and pot_number == probe_pot:
        return PotOccupancy(pot_number, t_number, PotState.PROBE, False, None, None)
    if t_number is None:
        return PotOccupancy(pot_number, None, PotState.EMPTY, False, None, None)
    if h_register is None:
        # Identity but no assignment: a pot reading its own ordinal is the
        # reinit/empty sentinel; a genuine non-ordinal identity is unverified.
        state = PotState.EMPTY if t_number == pot_number else PotState.UNVERIFIED
        return PotOccupancy(pot_number, t_number, state, False, None, None)
    if offset_mm is None or offset_mm == 0:
        return PotOccupancy(pot_number, t_number, PotState.EMPTY, False, h_register, offset_mm)
    return PotOccupancy(
        pot_number, t_number, PotState.LOADED, presetter_verified, h_register, offset_mm
    )


def _latest_h_geom_source(session: Session, machine_id: UUID) -> dict[int, str | None]:
    """Latest `offset_change` audit `source` per H-geom register — the #2
    presetter attribution. Returns {register_number: source|None}."""
    src = audit_log.c.after_value["source"].astext
    rows = session.execute(
        sa.select(audit_log.c.entity_id, src.label("source"))
        .distinct(audit_log.c.entity_id)
        .where(
            audit_log.c.machine_id == machine_id,
            audit_log.c.event_type == "offset_change",
            audit_log.c.entity_id.like(f"%/{_H_GEOM}"),
        )
        .order_by(audit_log.c.entity_id, audit_log.c.occurred_at.desc(), audit_log.c.id.desc())
    )
    out: dict[int, str | None] = {}
    for r in rows:
        try:
            reg = int(str(r.entity_id).split("/", 1)[0])
        except ValueError:  # pragma: no cover - defensive against malformed ids
            continue
        out[reg] = r.source
    return out


def _load_head_next(session: Session, machine_id: UUID) -> tuple[int | None, int | None]:
    """The current HEAD (spindle) / NEXT (on deck) tool numbers from the status
    mirror, or (None, None) if the machine has no persisted status row yet."""
    row = session.execute(
        sa.select(
            focas_machine_status.c.head_t_number, focas_machine_status.c.next_t_number
        ).where(focas_machine_status.c.machine_id == machine_id)
    ).one_or_none()
    if row is None:
        return None, None
    return row.head_t_number, row.next_t_number


def _pot_location(t_number: int | None, head: int | None, next_t: int | None) -> str | None:
    """Physical location of a pot's nominal tool: "spindle" if it is the HEAD
    tool, "next" if the NEXT tool, else None (it is really in the pot). Spindle
    wins if HEAD == NEXT (shouldn't happen, but be deterministic)."""
    if t_number is None:
        return None
    if head is not None and t_number == head:
        return "spindle"
    if next_t is not None and t_number == next_t:
        return "next"
    return None


def occupancy(session: Session, machine_id: UUID) -> list[dict[str, Any]]:
    """Enriched per-pot occupancy for a machine, ordered by pot number. 404 if
    the machine is unknown. One row per mirrored pot (the UI pads to pot_count)."""
    machine = session.execute(
        sa.select(machine_t.c.probe_pot).where(machine_t.c.id == machine_id)
    ).one_or_none()
    if machine is None:
        raise NotFound(f"machine {machine_id} not found")
    probe_pot = machine.probe_pot

    pots = session.execute(
        sa.select(
            focas_pot.c.pot_number,
            focas_pot.c.t_number,
            focas_pot.c.last_polled_at,
            focas_pot.c.last_changed_at,
        )
        .where(focas_pot.c.machine_id == machine_id)
        .order_by(focas_pot.c.pot_number)
    ).all()

    # Active assignments: t_number -> h_register (deleted_at IS NULL).
    asg_rows = session.execute(
        sa.select(asg.c.t_number, asg.c.h_register).where(
            asg.c.machine_id == machine_id, asg.c.deleted_at.is_(None)
        )
    ).all()
    t_to_h = {r.t_number: r.h_register for r in asg_rows}

    # Mirrored h_geom offsets: register_number -> value_mm.
    off_rows = session.execute(
        sa.select(focas_offset_register.c.register_number, focas_offset_register.c.value_mm).where(
            focas_offset_register.c.machine_id == machine_id,
            focas_offset_register.c.register_type == _H_GEOM,
        )
    ).all()
    h_to_value = {r.register_number: r.value_mm for r in off_rows}

    sources = _latest_h_geom_source(session, machine_id)

    # Live spindle state (#Spindle overlay): a tool physically in the spindle
    # (HEAD) or on deck (NEXT) has left its pot, even though the sticky pot cell
    # still shows its identity there. Tag those pots so the UI draws them vacated
    # instead of double-counting them as loaded residents ("ghosts").
    head, next_t = _load_head_next(session, machine_id)

    out: list[dict[str, Any]] = []
    for p in pots:
        h_register = t_to_h.get(p.t_number) if p.t_number is not None else None
        offset_mm = h_to_value.get(h_register) if h_register is not None else None
        verified = h_register is not None and sources.get(h_register) == _SRC_PRESETTER
        occ = classify_pot(p.pot_number, p.t_number, probe_pot, h_register, offset_mm, verified)
        out.append(
            {
                "pot_number": occ.pot_number,
                "t_number": occ.t_number,
                "state": occ.state.value,
                "verified": occ.verified,
                "assigned_h_register": occ.assigned_h_register,
                "offset_mm": occ.offset_mm,
                "location": _pot_location(p.t_number, head, next_t),
                "last_polled_at": p.last_polled_at,
                "last_changed_at": p.last_changed_at,
            }
        )
    return out


__all__ = ["PotOccupancy", "PotState", "_pot_location", "classify_pot", "occupancy"]
