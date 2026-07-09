"""Bulk-import the tool library from a CSV into `tooling.tool`.

The intake pipeline (see `tasks/spec-tool-numbering.md`): document the physical
crib into `docs/templates/tool-intake.csv`, then import it here in one command.

Identity is the non-significant GTID (`tool.short_id`) — the importer **upserts
on it**, so re-running updates catalog fields without creating duplicates and
WITHOUT touching runtime-owned fields (`regrind_count`, `created_at`). tool_type
is resolved by `code` (run `scripts.seed_tool_types` first).

Optional resident-assignment columns (machine_name / t_number / h_register /
d_register) seed `tooling.assignment` when present: H and D default to the
T-number (H=D=T convention), probe T/H are rejected (R12), and a row whose
machine doesn't exist yet is skipped with a note (assignments wait for machines).

Fails closed: any per-row validation error aborts the whole import (nothing is
written), so a bad CSV can't half-load. Dev DB only unless LANCE_ALLOW_PROD.

    python -m scripts.import_tools path/to/tools.csv             # dry-run (default)
    python -m scripts.import_tools path/to/tools.csv --apply     # write
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.tooling.api.services.tool_label import tool_description
from apps.tooling.api.tables import assignment as asg
from apps.tooling.api.tables import tool as tool_t
from apps.tooling.api.tables import tool_type as tt
from shared.db import machine as machine_t
from shared.dsn_guard import assert_target_allowed

# --- CSV column contract (mirrors docs/templates/tool-intake.csv) -------------
_REQUIRED = ("gtid", "tool_type", "diameter_mm")
_STR_COLS = ("substrate", "coating", "manufacturer", "edp_number",
             "vendor", "vendor_part_number", "vendor_url", "notes")
_DEC_COLS = ("diameter_mm", "diameter_inch", "corner_radius_mm", "flute_length_mm",
             "overall_length_mm", "shank_diameter_mm", "max_doc_mm", "max_woc_mm")
_INT_COLS = ("flute_count",)
_BOOL_COLS = ("requires_tsc", "requires_climb", "is_consumable_class")
_ASSIGN_COLS = ("machine_name", "t_number", "h_register", "d_register")
_KNOWN_COLS = {"gtid", "tool_type", *_STR_COLS, *_DEC_COLS, *_INT_COLS, *_BOOL_COLS, *_ASSIGN_COLS}

# Columns written on an UPSERT conflict (identity + runtime-owned fields excluded).
_UPSERT_SET = ("tool_type_id", *_DEC_COLS, *_INT_COLS, *_STR_COLS, *_BOOL_COLS)

_TRUE = {"1", "true", "t", "yes", "y"}
_FALSE = {"0", "false", "f", "no", "n", ""}


@dataclass
class BuiltRow:
    line: int
    gtid: str
    type_code: str
    tool_values: dict[str, Any]
    description: str
    assignment: dict[str, Any] | None  # resolved machine_id + t/h/d, or None


@dataclass
class BuildResult:
    rows: list[BuiltRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)  # non-fatal (e.g. machine absent)
    unknown_columns: list[str] = field(default_factory=list)


def _dec(raw: str, col: str, line: int, errs: list[str]) -> Decimal | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        errs.append(f"line {line}: {col}='{raw}' is not a number")
        return None


def _int(raw: str, col: str, line: int, errs: list[str]) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        errs.append(f"line {line}: {col}='{raw}' is not an integer")
        return None


def _bool(raw: str, col: str, line: int, errs: list[str]) -> bool:
    v = (raw or "").strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    errs.append(f"line {line}: {col}='{raw}' is not a boolean (true/false)")
    return False


def build_rows(
    raw_rows: list[dict[str, str]],
    header: list[str],
    type_code_to_id: dict[str, Any],
    machines: dict[str, dict[str, Any]],
) -> BuildResult:
    """Pure validation/build (no DB). `machines` maps name -> {id, probe_t_number,
    probe_h_register}. Accumulates ALL errors (never aborts on the first)."""
    res = BuildResult()
    res.unknown_columns = [c for c in header if c and c not in _KNOWN_COLS]
    seen_gtid: set[str] = set()

    for i, raw in enumerate(raw_rows, start=2):  # line 1 is the header
        errs = res.errors
        gtid = (raw.get("gtid") or "").strip()
        type_code = (raw.get("tool_type") or "").strip()
        if not gtid:
            errs.append(f"line {i}: gtid (GTID) is required")
            continue
        if gtid in seen_gtid:
            errs.append(f"line {i}: duplicate gtid '{gtid}' in file")
            continue
        seen_gtid.add(gtid)
        if type_code and type_code not in type_code_to_id:
            errs.append(
                f"line {i}: unknown tool_type '{type_code}' "
                f"(valid: {', '.join(sorted(type_code_to_id))})"
            )
        elif not type_code:
            errs.append(f"line {i}: tool_type is required")

        vals: dict[str, Any] = {"short_id": gtid}
        if type_code in type_code_to_id:
            vals["tool_type_id"] = type_code_to_id[type_code]
        for c in _DEC_COLS:
            vals[c] = _dec(raw.get(c, ""), c, i, errs)
        for c in _INT_COLS:
            vals[c] = _int(raw.get(c, ""), c, i, errs)
        for c in _STR_COLS:
            v = (raw.get(c) or "").strip()
            vals[c] = v or None
        for c in _BOOL_COLS:
            vals[c] = _bool(raw.get(c, ""), c, i, errs)
        if vals.get("diameter_mm") is None:
            errs.append(f"line {i}: diameter_mm is required and must be > 0")

        description = tool_description(
            type_code=type_code,
            type_display=type_code,  # display not needed for known codes
            diameter_mm=vals.get("diameter_mm"),
            diameter_inch=vals.get("diameter_inch"),
            flute_count=vals.get("flute_count"),
            substrate=vals.get("substrate"),
            coating=vals.get("coating"),
            corner_radius_mm=vals.get("corner_radius_mm"),
        )

        assignment = _build_assignment(raw, gtid, i, machines, res)
        res.rows.append(BuiltRow(i, gtid, type_code, vals, description, assignment))

    return res


def _build_assignment(
    raw: dict[str, str], gtid: str, line: int,
    machines: dict[str, dict[str, Any]], res: BuildResult,
) -> dict[str, Any] | None:
    machine_name = (raw.get("machine_name") or "").strip()
    t_raw = (raw.get("t_number") or "").strip()
    if not machine_name and not t_raw:
        return None  # catalog-only row
    if not machine_name or not t_raw:
        res.errors.append(f"line {line}: assignment needs both machine_name and t_number")
        return None
    if machine_name not in machines:
        res.skips.append(
            f"line {line}: machine '{machine_name}' not found — assignment skipped "
            "(seed the machine, then re-import)"
        )
        return None
    m = machines[machine_name]
    t_number = _int(t_raw, "t_number", line, res.errors)
    if t_number is None:
        return None
    # H and D default to the T-number (H=D=T convention).
    h_register = _int(raw.get("h_register", ""), "h_register", line, res.errors)
    d_register = _int(raw.get("d_register", ""), "d_register", line, res.errors)
    h_register = h_register if h_register is not None else t_number
    d_register = d_register if d_register is not None else t_number
    # Probe lock (R12): never assign to the reserved probe T / H.
    if m.get("probe_t_number") is not None and t_number == m["probe_t_number"]:
        res.errors.append(f"line {line}: t_number {t_number} is the reserved probe T (R12)")
    if m.get("probe_h_register") is not None and h_register == m["probe_h_register"]:
        res.errors.append(f"line {line}: h_register {h_register} is the reserved probe H (R12)")
    return {
        "gtid": gtid, "machine_id": m["id"], "machine_name": machine_name,
        "t_number": t_number, "h_register": h_register, "d_register": d_register,
    }


def _engine() -> sa.Engine:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url:
        sys.exit("DATABASE_URL not set")
    assert_target_allowed(url, action="import tools")
    eng = sa.create_engine(url, future=True)

    @sa.event.listens_for(eng, "connect")
    def _sp(dbapi_conn, _rec):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET search_path TO tooling, shared")

    return eng


def _load_lookups(conn: sa.Connection) -> tuple[dict[str, Any], dict[str, dict[str, Any]], set[str]]:
    type_code_to_id = {
        r.code: r.id for r in conn.execute(sa.select(tt.c.code, tt.c.id))
    }
    machines = {
        r.name: {"id": r.id, "probe_t_number": r.probe_t_number,
                 "probe_h_register": r.probe_h_register}
        for r in conn.execute(
            sa.select(machine_t.c.name, machine_t.c.id,
                      machine_t.c.probe_t_number, machine_t.c.probe_h_register)
        )
    }
    existing = {r.short_id for r in conn.execute(sa.select(tool_t.c.short_id))}
    return type_code_to_id, machines, existing


def _apply(conn: sa.Connection, res: BuildResult) -> tuple[int, int]:
    tool_params = [dict(r.tool_values) for r in res.rows]
    stmt = pg_insert(tool_t).values(tool_params)
    stmt = stmt.on_conflict_do_update(
        index_elements=[tool_t.c.short_id],
        set_={c: stmt.excluded[c] for c in _UPSERT_SET} | {"updated_at": datetime.now(UTC)},
    )
    rows = conn.execute(stmt.returning(tool_t.c.short_id, tool_t.c.id)).all()
    gtid_to_id = {r.short_id: r.id for r in rows}

    assignments = [r.assignment for r in res.rows if r.assignment is not None]
    made = 0
    for a in assignments:
        tool_id = gtid_to_id[a["gtid"]]
        # Idempotent: skip if an active assignment already occupies this (machine, T).
        exists = conn.execute(
            sa.select(asg.c.id).where(
                asg.c.machine_id == a["machine_id"],
                asg.c.t_number == a["t_number"],
                asg.c.deleted_at.is_(None),
            )
        ).first()
        if exists is not None:
            res.skips.append(
                f"assignment {a['machine_name']} T{a['t_number']} already exists — skipped"
            )
            continue
        conn.execute(sa.insert(asg).values(
            tool_id=tool_id, machine_id=a["machine_id"], t_number=a["t_number"],
            h_register=a["h_register"], d_register=a["d_register"],
            pending_review=False, assigned_at=datetime.now(UTC),
        ))
        made += 1
    return len(tool_params), made


def run(path: str, apply: bool) -> int:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        raw_rows = list(reader)

    eng = _engine()
    with eng.begin() as conn:
        type_code_to_id, machines, existing = _load_lookups(conn)
        res = build_rows(raw_rows, header, type_code_to_id, machines)

        if res.unknown_columns:
            print(f"unknown columns (ignored): {', '.join(res.unknown_columns)}")
        for line in res.rows:
            action = "update" if line.gtid in existing else "new"
            asg_note = ""
            if line.assignment is not None:
                a = line.assignment
                asg_note = f"  [{a['machine_name']} T{a['t_number']} H{a['h_register']} D{a['d_register']}]"
            print(f"  {action:6} {line.gtid:12} {line.description}{asg_note}")
        for s in res.skips:
            print(f"  skip: {s}")

        n_new = sum(1 for r in res.rows if r.gtid not in existing)
        print(f"\n{len(res.rows)} rows: {n_new} new, {len(res.rows) - n_new} update; "
              f"{len(res.errors)} error(s), {len(res.skips)} skip(s)")

        if res.errors:
            for e in res.errors:
                print(f"  ERROR {e}")
            print("aborted — fix the CSV; nothing written.")
            conn.rollback()
            return 1

        if not apply:
            print("dry-run: no changes written (pass --apply to write)")
            conn.rollback()
            return 0

        skips_before = len(res.skips)
        tools_n, asg_n = _apply(conn, res)
        for s in res.skips[skips_before:]:  # apply-time (e.g. assignment already exists)
            print(f"  skip: {s}")
        print(f"applied — {tools_n} tools upserted, {asg_n} assignments created")
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Import the tool library from a CSV")
    p.add_argument("csv_path", help="path to the intake CSV")
    p.add_argument("--apply", action="store_true", help="write to the DB (default: dry-run)")
    args = p.parse_args(argv)
    return run(args.csv_path, args.apply)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
