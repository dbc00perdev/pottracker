"""Integration test: shared.focas.snapshot.persist against a live Postgres.

Proves the diff/UPSERT/audit path end-to-end on a real DB — the thing unit
tests with a fake session can't cover. Requires DATABASE_URL pointing at a
migrated database (the Docker dev Postgres); skips cleanly when unavailable, so
CI without a DB is unaffected.

Isolated by a fixed test machine UUID that is seeded and torn down per test;
touches only `shared.*` rows it owns.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.focas.models import (
    MachineSnapshot,
    MachineStatus,
    OffsetRegister,
    PotEntry,
    RegisterType,
    ToolLife,
    ToolLifeStatus,
)
from shared.focas.snapshot import persist

pytestmark = pytest.mark.integration

_DSN = os.environ.get("DATABASE_URL")
_MID = UUID("11111111-1111-1111-1111-111111111111")
_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def engine():
    if not _DSN:
        pytest.skip("DATABASE_URL not set")
    eng = create_engine(_DSN)
    try:
        with eng.connect() as c:
            c.execute(sa.text("select 1 from shared.machine where false"))
    except Exception as exc:  # schema not migrated / DB unreachable
        eng.dispose()
        pytest.skip(f"migrated dev DB not available: {exc}")

    _cleanup(eng)
    with eng.begin() as c:
        c.execute(
            sa.text(
                "insert into shared.machine "
                "(id, name, control_model, ip_address, pot_count, atc_strategy) "
                "values (:i, 'itest-viper', '0i-MF', '10.1.10.58', 24, 'random_access')"
            ),
            {"i": _MID},
        )
    yield eng
    _cleanup(eng)
    eng.dispose()


def _cleanup(eng) -> None:
    # audit_log FK is ON DELETE SET NULL, so purge audit rows BEFORE the machine
    # (while machine_id still matches); machine delete cascades the focas_* rows.
    with eng.begin() as c:
        c.execute(sa.text("delete from shared.audit_log where machine_id = :i"), {"i": _MID})
        c.execute(sa.text("delete from shared.machine where id = :i"), {"i": _MID})


def _snap(polled_at: datetime, h1_value: str) -> MachineSnapshot:
    return MachineSnapshot(
        machine_id="itest",
        polled_at=polled_at,
        status=MachineStatus(),
        offsets=(
            OffsetRegister(register_number=1, register_type=RegisterType.H_GEOM, value_mm=Decimal(h1_value)),
            OffsetRegister(register_number=2, register_type=RegisterType.H_GEOM, value_mm=Decimal("5.0000")),
        ),
        pots=(PotEntry(pot_number=1, t_number=45),),
        tool_life=(ToolLife(t_number=45, life_count=10, life_max=100, status=ToolLifeStatus.LIVE),),
    )


def _audit_count(eng) -> int:
    with eng.connect() as c:
        return c.execute(
            sa.text("select count(*) from shared.audit_log where machine_id = :i"), {"i": _MID}
        ).scalar_one()


def test_first_persist_creates_mirror_and_audit(engine):
    with Session(engine) as s:
        res = persist(s, _snap(_T0, "7.4050"), _MID)

    # 2 offsets + 1 pot + 1 tool_life, all new -> 4 change events
    assert res.audit_rows == 4
    assert _audit_count(engine) == 4
    with engine.connect() as c:
        offs = c.execute(
            sa.text("select count(*) from shared.focas_offset_register where machine_id = :i"),
            {"i": _MID},
        ).scalar_one()
        pots = c.execute(
            sa.text("select t_number from shared.focas_pot where machine_id = :i and pot_number = 1"),
            {"i": _MID},
        ).scalar_one()
    assert offs == 2
    assert pots == 45


def test_second_persist_audits_only_the_changed_offset(engine):
    with Session(engine) as s:
        persist(s, _snap(_T0, "7.4050"), _MID)  # baseline (4 events)

    t1 = _T0 + timedelta(seconds=60)
    with Session(engine) as s:
        res = persist(s, _snap(t1, "7.4000"), _MID)  # only register 1 changed

    assert res.audit_rows == 1
    assert _audit_count(engine) == 5  # 4 baseline + 1 change

    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                "select register_number, last_polled_at, last_changed_at "
                "from shared.focas_offset_register where machine_id = :i order by register_number"
            ),
            {"i": _MID},
        ).all()
    by_num = {r.register_number: r for r in rows}
    # register 1 changed -> last_changed advanced to t1
    assert by_num[1].last_changed_at == t1
    assert by_num[1].last_polled_at == t1
    # register 2 unchanged -> last_polled advanced, last_changed stays at _T0
    assert by_num[2].last_polled_at == t1
    assert by_num[2].last_changed_at == _T0

    # the single new audit row is the offset change, with before/after
    with engine.connect() as c:
        latest = c.execute(
            sa.text(
                "select event_type, entity_id, before_value, after_value "
                "from shared.audit_log where machine_id = :i "
                "order by occurred_at desc, id desc limit 1"
            ),
            {"i": _MID},
        ).one()
    assert latest.event_type == "offset_change"
    assert latest.entity_id == "1/h_geom"
    assert latest.before_value == {"value_mm": "7.4050"}
    assert latest.after_value == {"value_mm": "7.4000"}
