"""Offset-table export: G10 (runnable program) + CSV (crib report).

Reads the DB mirror ONLY (`shared.focas_offset_register`) — zero FOCAS calls,
zero machine contact. The G10 text becomes a write only if an operator loads
and runs it at a panel; until dbc00per panel-verifies the form per machine
class, files carry a DO-NOT-RUN header (`_FORM_VERIFIED_CLASSES`).

Unit: the mirror stores the control's NATIVE values (`value_mm` column name is
the grandfathered pre-07-15 misnomer). INI=1 (inch) is fleet-verified on all
10 machines (2026-08-05, reports/fleet-unit-verify-*, spec-focas-calls.md);
until `shared.machine.offset_unit` lands (spec-offset-units follow-up), unit
resolution funnels through `machine_offset_unit()` — the single place to swap
to the column read.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from apps.tooling.api.services import tool_label
from apps.tooling.api.services.g10 import G10Meta, Rows, build_g10, comment_text
from apps.tooling.api.services.machines import get_row
from apps.tooling.api.tables import assignment as asg_t
from apps.tooling.api.tables import tool as tool_t
from apps.tooling.api.tables import tool_type as type_t
from shared.db import focas_offset_register as f_off
from shared.focas.models import RegisterType

# Machine classes whose G10 form dbc00per has panel-run against scratch
# registers (spec-offset-export §1.4 final gate). Empty until that happens.
_FORM_VERIFIED_CLASSES: frozenset[str] = frozenset()

_MILL_COLUMNS = [RegisterType.H_GEOM, RegisterType.H_WEAR,
                 RegisterType.D_GEOM, RegisterType.D_WEAR]
_LATHE_COLUMNS = [RegisterType.X_GEOM, RegisterType.X_WEAR,
                  RegisterType.Z_GEOM, RegisterType.Z_WEAR,
                  RegisterType.R_GEOM, RegisterType.R_WEAR, RegisterType.TIP]


def machine_offset_unit(machine_row: Any) -> str:
    """Single funnel for unit resolution (see module docstring)."""
    return "inch"


def _mirror_rows(session: Session, machine_id: UUID) -> tuple[Rows, dict[int, datetime], datetime | None]:
    """(register -> {type: value}, register -> latest change, mirror freshness)."""
    rows: Rows = {}
    changed: dict[int, datetime] = {}
    freshest: datetime | None = None
    result = session.execute(
        sa.select(
            f_off.c.register_number, f_off.c.register_type,
            f_off.c.value_mm, f_off.c.last_changed_at, f_off.c.last_polled_at,
        ).where(f_off.c.machine_id == machine_id)
    )
    for r in result:
        rows.setdefault(r.register_number, {})[r.register_type] = r.value_mm
        prior = changed.get(r.register_number)
        if prior is None or r.last_changed_at > prior:
            changed[r.register_number] = r.last_changed_at
        if freshest is None or r.last_polled_at > freshest:
            freshest = r.last_polled_at
    return rows, changed, freshest


def _identity_by_register(session: Session, machine_id: UUID) -> dict[int, tuple[str, str]]:
    """h_register -> (GTID, generated description) for active assignments."""
    result = session.execute(
        sa.select(
            asg_t.c.h_register, tool_t.c.short_id, type_t.c.code, type_t.c.display_name,
            tool_t.c.diameter_mm, tool_t.c.diameter_inch, tool_t.c.flute_count,
            tool_t.c.substrate, tool_t.c.coating, tool_t.c.corner_radius_mm,
        )
        .join(tool_t, tool_t.c.id == asg_t.c.tool_id)
        .join(type_t, type_t.c.id == tool_t.c.tool_type_id)
        .where(asg_t.c.machine_id == machine_id, asg_t.c.deleted_at.is_(None))
    )
    out: dict[int, tuple[str, str]] = {}
    for r in result:
        description = tool_label.tool_description(
            type_code=r.code, type_display=r.display_name,
            diameter_mm=r.diameter_mm, diameter_inch=r.diameter_inch,
            flute_count=r.flute_count, substrate=r.substrate,
            coating=r.coating, corner_radius_mm=r.corner_radius_mm,
        )
        out[r.h_register] = (r.short_id, description)
    return out


def _mirror_note(freshest: datetime | None, now: datetime) -> str:
    if freshest is None:
        return "MIRROR EMPTY - NO POLL DATA"
    age = int((now - freshest).total_seconds())
    return f"MIRROR POLLED {age} SEC BEFORE EXPORT"


def _stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H%M UTC")


def file_stamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M")


def safe_name(name: str) -> str:
    return comment_text(name).replace(" ", "_").replace("/", "-")


def export_g10(session: Session, machine_id: UUID, *, sparse: bool) -> tuple[str, str]:
    """(filename, text). Sparse default; full writes every register incl zeros."""
    machine = get_row(session, machine_id)
    rows, _, freshest = _mirror_rows(session, machine_id)
    now = datetime.now(UTC)
    meta = G10Meta(
        machine_name=machine.name,
        machine_class=machine.machine_class,
        unit=machine_offset_unit(machine),
        register_count=machine.offset_register_count,
        sparse=sparse,
        generated_at=_stamp(now),
        mirror_note=_mirror_note(freshest, now),
        form_verified=machine.machine_class in _FORM_VERIFIED_CLASSES,
    )
    mode = "sparse" if sparse else "full"
    filename = f"{safe_name(machine.name)}-offsets-{mode}-{file_stamp(now)}.nc"
    return filename, build_g10(rows, meta)


def export_csv(session: Session, machine_id: UUID, *, sparse: bool) -> tuple[str, str]:
    """Crib-facing CSV: one row per register, native values, identity join."""
    machine = get_row(session, machine_id)
    rows, changed, freshest = _mirror_rows(session, machine_id)
    identity = _identity_by_register(session, machine_id)
    unit = machine_offset_unit(machine)
    now = datetime.now(UTC)
    columns = _LATHE_COLUMNS if machine.machine_class == "lathe" else _MILL_COLUMNS

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    buf.write(f"# {machine.name} offset export {_stamp(now)} — "
              f"{_mirror_note(freshest, now)} — values in {unit} (control-native)\n")
    header = ["machine", "register"]
    header += [rt.value if rt is RegisterType.TIP else f"{rt.value}_{unit}" for rt in columns]
    header += ["last_changed_at", "gtid", "description"]
    writer.writerow(header)

    numbers = sorted(rows) if sparse else range(1, machine.offset_register_count + 1)
    for n in numbers:
        banks = rows.get(n, {})
        if sparse and all(v == 0 for v in banks.values()):
            continue
        gtid, description = identity.get(n, ("", ""))
        last_changed = changed.get(n)
        writer.writerow(
            [machine.name, n]
            + [banks.get(rt, "") for rt in columns]
            + [last_changed.isoformat() if last_changed else "", gtid, description]
        )

    mode = "sparse" if sparse else "full"
    filename = f"{safe_name(machine.name)}-offsets-{mode}-{file_stamp(now)}.csv"
    return filename, buf.getvalue()
