"""Tests for scripts.import_tools.

`build_rows` is pure (no DB) and gets thorough validation coverage that always
runs. The upsert / idempotency / assignment path is exercised against the live
dev DB in an `integration`-marked block that skips without DATABASE_URL.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine

from scripts.import_tools import _apply, build_rows

_EM = uuid.UUID("aaaa0000-0000-0000-0000-000000000001")
_DR = uuid.UUID("aaaa0000-0000-0000-0000-000000000002")
_MID = uuid.UUID("aaaa0000-0000-0000-0000-0000000000m1".replace("m", "b"))
_TYPES = {"em_square": _EM, "drill": _DR}
_MACHINES = {"Viper": {"id": _MID, "probe_t_number": 50, "probe_h_register": 50}}

_HEADER = [
    "gtid", "tool_type", "diameter_mm", "diameter_inch", "flute_count", "substrate",
    "coating", "manufacturer", "edp_number", "machine_name", "t_number", "h_register",
    "d_register",
]


def _row(**kw: str) -> dict[str, str]:
    base = {c: "" for c in _HEADER}
    base.update(kw)
    return base


# --- pure build_rows validation ---------------------------------------------


def test_happy_catalog_plus_assignment():
    r = _row(gtid="100001", tool_type="em_square", diameter_mm="12.7", diameter_inch="0.5",
             flute_count="4", substrate="carbide", coating="tialn", manufacturer="Helical",
             edp_number="59424", machine_name="Viper", t_number="7")
    res = build_rows([r], _HEADER, _TYPES, _MACHINES)
    assert res.errors == []
    assert len(res.rows) == 1
    row = res.rows[0]
    assert row.gtid == "100001"
    assert row.tool_values["tool_type_id"] == _EM
    assert row.tool_values["manufacturer"] == "Helical"
    assert row.tool_values["edp_number"] == "59424"
    assert row.description == "0.5in 4FL SQ EM CARBIDE TIALN"
    # H=D=T default
    assert row.assignment == {
        "gtid": "100001", "machine_id": _MID, "machine_name": "Viper",
        "t_number": 7, "h_register": 7, "d_register": 7,
    }


def test_unknown_tool_type_is_error():
    res = build_rows([_row(gtid="1", tool_type="nope", diameter_mm="6")], _HEADER, _TYPES, _MACHINES)
    assert any("unknown tool_type 'nope'" in e for e in res.errors)


def test_bad_diameter_is_error():
    res = build_rows([_row(gtid="1", tool_type="drill", diameter_mm="abc")], _HEADER, _TYPES, _MACHINES)
    assert any("diameter_mm='abc' is not a number" in e for e in res.errors)


def test_missing_required_fields_are_errors():
    res = build_rows([_row(gtid="", tool_type="drill", diameter_mm="6")], _HEADER, _TYPES, _MACHINES)
    assert any("gtid (GTID) is required" in e for e in res.errors)
    res2 = build_rows([_row(gtid="1", tool_type="drill", diameter_mm="")], _HEADER, _TYPES, _MACHINES)
    assert any("diameter_mm is required" in e for e in res2.errors)


def test_duplicate_gtid_in_file_is_error():
    rows = [_row(gtid="7", tool_type="drill", diameter_mm="6"),
            _row(gtid="7", tool_type="drill", diameter_mm="6")]
    res = build_rows(rows, _HEADER, _TYPES, _MACHINES)
    assert any("duplicate gtid '7'" in e for e in res.errors)


def test_unknown_columns_flagged():
    header = [*_HEADER, "favourite_colour"]
    res = build_rows([_row(gtid="1", tool_type="drill", diameter_mm="6")], header, _TYPES, _MACHINES)
    assert "favourite_colour" in res.unknown_columns


def test_absent_machine_skips_assignment_not_error():
    r = _row(gtid="1", tool_type="drill", diameter_mm="6", machine_name="Ghost", t_number="7")
    res = build_rows([r], _HEADER, _TYPES, _MACHINES)
    assert res.errors == []
    assert res.rows[0].assignment is None
    assert any("machine 'Ghost' not found" in s for s in res.skips)


def test_probe_t_and_h_rejected_r12():
    r = _row(gtid="1", tool_type="drill", diameter_mm="6", machine_name="Viper", t_number="50")
    res = build_rows([r], _HEADER, _TYPES, _MACHINES)
    assert any("reserved probe T (R12)" in e for e in res.errors)
    r2 = _row(gtid="2", tool_type="drill", diameter_mm="6", machine_name="Viper",
              t_number="7", h_register="50")
    res2 = build_rows([r2], _HEADER, _TYPES, _MACHINES)
    assert any("reserved probe H (R12)" in e for e in res2.errors)


def test_assignment_needs_both_machine_and_t():
    r = _row(gtid="1", tool_type="drill", diameter_mm="6", machine_name="Viper")
    res = build_rows([r], _HEADER, _TYPES, _MACHINES)
    assert any("needs both machine_name and t_number" in e for e in res.errors)


# --- integration: upsert / idempotency / assignment against the dev DB -------

_DSN = os.environ.get("DATABASE_URL")
_IT_MID = uuid.UUID("cccc0000-0000-0000-0000-0000000000c1")


@pytest.fixture
def engine():
    if not _DSN:
        pytest.skip("DATABASE_URL not set")
    dsn = _DSN.replace("postgresql://", "postgresql+psycopg://", 1)
    eng = create_engine(dsn)

    @sa.event.listens_for(eng, "connect")
    def _sp(dbapi_conn, _rec):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET search_path TO tooling, shared")

    try:
        with eng.connect() as c:
            c.execute(sa.text("select 1 from tooling.tool where false"))
    except Exception as exc:  # pragma: no cover
        eng.dispose()
        pytest.skip(f"migrated dev DB not available: {exc}")

    _cleanup(eng)
    with eng.begin() as c:
        c.execute(sa.text(
            "insert into tooling.tool_type (id, code, display_name, has_corner_radius, "
            "has_thread_pitch, has_taper_angle, is_drilling) values "
            "(gen_random_uuid(), 'it_em', 'IT Endmill', false, false, false, false)"
        ))
        c.execute(sa.text(
            "insert into shared.machine (id, name, control_model, ip_address, pot_count, "
            "atc_strategy, probe_t_number, probe_h_register, probe_pot) values "
            "(:i, 'IT-Viper', '0i-MF', '10.1.10.58', 24, 'random_access', 50, 50, 24)"
        ), {"i": _IT_MID})
    yield eng
    _cleanup(eng)
    eng.dispose()


def _cleanup(eng) -> None:
    with eng.begin() as c:
        c.execute(sa.text("delete from tooling.assignment where machine_id = :i"), {"i": _IT_MID})
        c.execute(sa.text("delete from tooling.tool where short_id like 'IT-%'"))
        c.execute(sa.text("delete from shared.machine where id = :i"), {"i": _IT_MID})
        c.execute(sa.text("delete from tooling.tool_type where code = 'it_em'"))


def _lookups(conn):
    types = {r.code: r.id for r in conn.execute(sa.text("select code, id from tooling.tool_type"))}
    machines = {
        r.name: {"id": r.id, "probe_t_number": r.probe_t_number, "probe_h_register": r.probe_h_register}
        for r in conn.execute(sa.text(
            "select name, id, probe_t_number, probe_h_register from shared.machine"))
    }
    return types, machines


@pytest.mark.integration
def test_upsert_idempotent_preserves_regrind_and_creates_assignment(engine):
    header = ["gtid", "tool_type", "diameter_mm", "manufacturer", "machine_name", "t_number"]
    row = {"gtid": "IT-100", "tool_type": "it_em", "diameter_mm": "6.0",
           "manufacturer": "Helical", "machine_name": "IT-Viper", "t_number": "7"}

    with engine.begin() as conn:
        types, machines = _lookups(conn)
        res = build_rows([row], header, types, machines)
        assert res.errors == []
        tools_n, asg_n = _apply(conn, res)
    assert tools_n == 1 and asg_n == 1

    # Simulate a runtime regrind, then re-import with a changed field.
    with engine.begin() as conn:
        conn.execute(sa.text("update tooling.tool set regrind_count = 3 where short_id = 'IT-100'"))
    row2 = dict(row, manufacturer="Harvey Tool")
    with engine.begin() as conn:
        types, machines = _lookups(conn)
        res = build_rows([row2], header, types, machines)
        _apply(conn, res)

    with engine.connect() as conn:
        r = conn.execute(sa.text(
            "select manufacturer, regrind_count from tooling.tool where short_id = 'IT-100'"
        )).one()
        n_tool = conn.execute(sa.text(
            "select count(*) from tooling.tool where short_id = 'IT-100'")).scalar_one()
        n_asg = conn.execute(sa.text(
            "select count(*) from tooling.assignment where machine_id = :i"), {"i": _IT_MID}
        ).scalar_one()
    assert r.manufacturer == "Harvey Tool"   # catalog field updated
    assert r.regrind_count == 3              # runtime field preserved
    assert n_tool == 1                       # upsert, no duplicate
    assert n_asg == 1                        # assignment not re-created
