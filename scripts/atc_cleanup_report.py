"""Read-only ATC cleanup verification report.

Pulls the audit trail + live occupancy for one machine so an operator can confirm
a carousel teardown (empty pots + zeroed tool offsets) landed cleanly in the
mirror BEFORE re-loading tools. Prints three sections:

  1. AUDIT   — recent pot_reinit_suspected / pot_move / offset_change (h_geom→0)
               events in a time window, newest first.
  2. OCCUPANCY — current per-pot state from the occupancy model. A clean empty
               carousel = every non-probe pot `empty`.
  3. VERDICT — non-zero h_geom offsets remaining + non-empty pots remaining. Zero
               of both = clean teardown.

READ-ONLY: SELECTs only. No FANUC contact, no writes, no DDL. Safe to run against
the live mirror any time. Requires `DATABASE_URL` in the environment (same DSN the
poller/API use — `apps.tooling.api.config`).

    $ DATABASE_URL=postgresql://... python -m scripts.atc_cleanup_report \
          --machine 10.1.10.58 --hours 6
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.tooling.api.config import get_settings
from apps.tooling.api.services.occupancy import occupancy
from shared.db import audit_log, focas_machine_status, focas_offset_register
from shared.db import machine as machine_t

_H_GEOM = "h_geom"
# Events that make up a carousel teardown, in the order we care to see them.
_CLEANUP_EVENTS = ("pot_reinit_suspected", "pot_move", "offset_change")


def _resolve_machine(session: Session, needle: str | None) -> tuple[UUID, str]:
    """Resolve a machine by IP or name substring. With no needle, require exactly
    one machine (else list them and bail) so we never report the wrong Viper."""
    rows = session.execute(
        sa.select(machine_t.c.id, machine_t.c.name, machine_t.c.ip_address).order_by(
            machine_t.c.name
        )
    ).all()
    if not rows:
        sys.exit("no machines in shared.machine — is DATABASE_URL pointing at the mirror?")
    if needle:
        n = needle.lower()
        hits = [r for r in rows if n in str(r.ip_address).lower() or n in r.name.lower()]
    else:
        hits = list(rows)
    if len(hits) == 1:
        return hits[0].id, hits[0].name
    label = f"matching {needle!r}" if needle else "known"
    listing = "\n".join(f"  - {r.name} ({r.ip_address})" for r in rows)
    sys.exit(f"expected exactly one machine {label}; found {len(hits)}. Machines:\n{listing}")


def _is_h_geom_offset(row: sa.Row) -> bool:
    """offset_change entity_id is "<register>/<type>"; only the tool-length
    (h_geom) bank is presetter/teardown-relevant here."""
    return row.event_type == "offset_change" and str(row.entity_id).endswith(f"/{_H_GEOM}")


def _fmt_val(v: object) -> str:
    return "∅" if v is None else str(v)


def _print_audit(session: Session, machine_id: UUID, since: datetime) -> None:
    rows = session.execute(
        sa.select(
            audit_log.c.occurred_at,
            audit_log.c.event_type,
            audit_log.c.entity_id,
            audit_log.c.before_value,
            audit_log.c.after_value,
            audit_log.c.success,
        )
        .where(
            audit_log.c.machine_id == machine_id,
            audit_log.c.occurred_at >= since,
            audit_log.c.event_type.in_(_CLEANUP_EVENTS),
        )
        .order_by(audit_log.c.occurred_at.desc(), audit_log.c.id.desc())
    ).all()
    # Keep offset_change rows to the h_geom bank only (wear/dia edits are noise here).
    rows = [r for r in rows if r.event_type != "offset_change" or _is_h_geom_offset(r)]

    print(f"\n=== AUDIT (since {since.isoformat(timespec='seconds')}, newest first) ===")
    if not rows:
        print("  (no pot/offset teardown events in window)")
        return
    for r in rows:
        ts = r.occurred_at.astimezone(UTC).strftime("%m-%d %H:%M:%S")
        flag = "" if r.success else "  ⚠ non-success"
        if r.event_type == "pot_reinit_suspected":
            n = (r.after_value or {}).get("count", "?")
            print(f"  {ts}  POT-REINIT   {n} pots reverted to ordinal{flag}")
        elif r.event_type == "pot_move":
            b = _fmt_val((r.before_value or {}).get("t_number"))
            a = _fmt_val((r.after_value or {}).get("t_number"))
            print(f"  {ts}  pot {r.entity_id:<4} T{b} → T{a}{flag}")
        else:  # offset_change / h_geom
            reg = str(r.entity_id).split("/", 1)[0]
            b = _fmt_val((r.before_value or {}).get("value_mm"))
            a = _fmt_val((r.after_value or {}).get("value_mm"))
            src = (r.after_value or {}).get("source", "")
            print(f"  {ts}  H{reg:<4} {b} → {a} mm  {src}{flag}")
    print(f"  ({len(rows)} events)")


def _print_occupancy(session: Session, machine_id: UUID) -> tuple[int, int]:
    """Print per-pot occupancy; return (non_empty_non_probe, nonzero_h_geom)."""
    occ = occupancy(session, machine_id)
    print("\n=== OCCUPANCY (current mirror) ===")
    dirty_pots = 0
    for p in occ:
        state = p["state"]
        loc = f"  → {p['location']}" if p["location"] else ""
        tnum = f"T{p['t_number']}" if p["t_number"] is not None else "—"
        off = f"  H{p['assigned_h_register']}={p['offset_mm']}mm" if p["offset_mm"] else ""
        mark = "" if state in ("empty", "probe") else "   ← not empty"
        if mark:
            dirty_pots += 1
        print(f"  pot {p['pot_number']:>2}  {state:<10} {tnum:<5}{off}{loc}{mark}")

    nonzero = session.execute(
        sa.select(sa.func.count())
        .select_from(focas_offset_register)
        .where(
            focas_offset_register.c.machine_id == machine_id,
            focas_offset_register.c.register_type == _H_GEOM,
            focas_offset_register.c.value_mm != 0,
        )
    ).scalar_one()
    return dirty_pots, int(nonzero)


def _print_status(session: Session, machine_id: UUID) -> None:
    row = session.execute(
        sa.select(
            focas_machine_status.c.head_t_number,
            focas_machine_status.c.next_t_number,
            focas_machine_status.c.mode,
            focas_machine_status.c.running,
            focas_machine_status.c.last_polled_at,
        ).where(focas_machine_status.c.machine_id == machine_id)
    ).one_or_none()
    print("\n=== STATUS ===")
    if row is None:
        print("  (no status row mirrored yet)")
        return
    polled = row.last_polled_at.astimezone(UTC).strftime("%m-%d %H:%M:%S") if row.last_polled_at else "?"
    print(
        f"  HEAD={_fmt_val(row.head_t_number)}  NEXT={_fmt_val(row.next_t_number)}  "
        f"mode={row.mode}  running={row.running}  (polled {polled})"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only ATC cleanup verification report.")
    ap.add_argument("--machine", help="machine IP or name substring (default: the only machine)")
    ap.add_argument("--hours", type=float, default=6.0, help="audit lookback window (default 6h)")
    args = ap.parse_args()

    engine = create_engine(get_settings().database_url)
    since = datetime.now(UTC) - timedelta(hours=args.hours)
    with Session(engine) as session:
        machine_id, name = _resolve_machine(session, args.machine)
        print(f"ATC cleanup report — {name} ({machine_id})")
        _print_audit(session, machine_id, since)
        dirty_pots, nonzero_off = _print_occupancy(session, machine_id)
        _print_status(session, machine_id)
        print("\n=== VERDICT ===")
        if dirty_pots == 0 and nonzero_off == 0:
            print("  CLEAN — every non-probe pot empty and all h_geom offsets zero. Safe to re-load.")
        else:
            print(
                f"  NOT CLEAN — {dirty_pots} non-empty pot(s), {nonzero_off} non-zero h_geom offset(s) "
                "remain. Re-check the teardown (or wait for the next poll to catch up)."
            )


if __name__ == "__main__":
    main()
