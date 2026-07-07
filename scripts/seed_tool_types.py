"""Seed `tooling.tool_type` with the v1 canonical tool-type set.

Idempotent: upserts on the unique `code`, so re-running updates display names /
capability flags without creating duplicates and without disturbing existing
`tooling.tool` rows that reference these types. Runs against `DATABASE_URL`.

    python -m scripts.seed_tool_types            # apply
    python -m scripts.seed_tool_types --dry-run  # print what would change, touch nothing

Capability flags are best-guess defaults keyed to how each type is probed /
measured (see docs/02a-seed-data.md); adjust to shop convention as needed —
re-running the seed reconciles them. Codes are the stable identity; renaming a
code is a data migration, not a seed edit.
"""

from __future__ import annotations

import argparse
import os
import sys

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.tooling.api.tables import tool_type as tt

# code, display_name, has_corner_radius, has_thread_pitch, has_taper_angle, is_drilling
SEED: list[tuple[str, str, bool, bool, bool, bool]] = [
    ("em_square",        "Square Endmill",        False, False, False, False),
    ("em_ball",          "Ball Endmill",          False, False, False, False),
    ("em_corner_radius", "Corner-Radius Endmill", True,  False, False, False),
    ("face_mill",        "Face Mill",             False, False, False, False),
    ("chamfer",          "Chamfer Mill",          False, False, True,  False),
    ("spot_drill",       "Spot Drill",            False, False, False, True),
    ("drill",            "Drill",                 False, False, False, True),
    ("reamer",           "Reamer",                False, False, False, True),
    ("tap",              "Tap",                   False, True,  False, False),
    ("probe",            "Touch Probe",           False, False, False, False),
]


def _engine() -> sa.Engine:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url:
        sys.exit("DATABASE_URL not set")
    eng = sa.create_engine(url, future=True)

    @sa.event.listens_for(eng, "connect")
    def _sp(dbapi_conn, _rec):  # noqa: ANN001, ANN202
        with dbapi_conn.cursor() as cur:
            cur.execute("SET search_path TO tooling, shared")

    return eng


def _rows() -> list[dict]:
    return [
        {"code": c, "display_name": d, "has_corner_radius": cr,
         "has_thread_pitch": tp, "has_taper_angle": ta, "is_drilling": dr}
        for (c, d, cr, tp, ta, dr) in SEED
    ]


def run(dry_run: bool) -> None:
    eng = _engine()
    with eng.begin() as conn:
        existing = {
            r.code: r for r in conn.execute(
                sa.select(tt.c.code, tt.c.display_name, tt.c.has_corner_radius,
                          tt.c.has_thread_pitch, tt.c.has_taper_angle, tt.c.is_drilling)
            ).all()
        }
        inserts = [r for r in _rows() if r["code"] not in existing]
        updates = []
        for r in _rows():
            cur = existing.get(r["code"])
            if cur is not None and (
                cur.display_name != r["display_name"]
                or cur.has_corner_radius != r["has_corner_radius"]
                or cur.has_thread_pitch != r["has_thread_pitch"]
                or cur.has_taper_angle != r["has_taper_angle"]
                or cur.is_drilling != r["is_drilling"]
            ):
                updates.append(r)

        print(f"seed tool_type: {len(inserts)} new, {len(updates)} to update, "
              f"{len(existing)} already present")
        for r in inserts:
            print(f"  + {r['code']:18} {r['display_name']}")
        for r in updates:
            print(f"  ~ {r['code']:18} {r['display_name']}")

        if dry_run:
            print("dry-run: no changes written")
            conn.rollback()
            return

        stmt = pg_insert(tt).values(_rows())
        stmt = stmt.on_conflict_do_update(
            index_elements=[tt.c.code],
            set_={
                "display_name": stmt.excluded.display_name,
                "has_corner_radius": stmt.excluded.has_corner_radius,
                "has_thread_pitch": stmt.excluded.has_thread_pitch,
                "has_taper_angle": stmt.excluded.has_taper_angle,
                "is_drilling": stmt.excluded.is_drilling,
            },
        )
        conn.execute(stmt)
        print(f"applied — {len(SEED)} tool types reconciled")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Seed tooling.tool_type")
    p.add_argument("--dry-run", action="store_true", help="print changes, write nothing")
    args = p.parse_args(argv)
    run(args.dry_run)


if __name__ == "__main__":
    main()
