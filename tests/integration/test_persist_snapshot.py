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
    MachineMode,
    MachineSnapshot,
    MachineStatus,
    MacroVariable,
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
    # Use the psycopg v3 driver explicitly (only psycopg[binary] is installed;
    # a bare postgresql:// DSN defaults to psycopg2, which we don't ship). Mirrors
    # the normalization in config.py / migrations/env.py / the seed scripts.
    dsn = _DSN.replace("postgresql://", "postgresql+psycopg://", 1)
    eng = create_engine(dsn)
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


def _snap(polled_at: datetime, h1_value: str, skip_5061: str | None = None) -> MachineSnapshot:
    macros: tuple[MacroVariable, ...] = ()
    if skip_5061 is not None:
        macros = (MacroVariable(number=5061, value=Decimal(skip_5061)),)
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
        macros=macros,
    )


def test_presetter_attribution_via_fresh_skip(engine):
    """End-to-end #2: an H_GEOM offset change in the same poll cycle a G31 skip
    var moved is attributed to the presetter; the skip is mirrored + audited."""
    # Baseline: offset 0, skip #5061 latched at -5.5100.
    with Session(engine) as s:
        persist(s, _snap(_T0, "0.0000", skip_5061="-5.5100"), _MID)

    # Next cycle: presetter fires — offset #1 becomes 5.6883 AND #5061 moves.
    t1 = _T0 + timedelta(seconds=5)
    with Session(engine) as s:
        res = persist(s, _snap(t1, "5.6883", skip_5061="-4.0100"), _MID)
    assert res.macros_changed == 1

    with engine.connect() as c:
        mv = c.execute(
            sa.text(
                "select value from shared.focas_macro_var "
                "where machine_id = :i and number = 5061"
            ),
            {"i": _MID},
        ).scalar_one()
        assert Decimal(mv) == Decimal("-4.0100")

        offset_audit = c.execute(
            sa.text(
                "select after_value from shared.audit_log where machine_id = :i "
                "and entity_type = 'offset' and entity_id = '1/h_geom' "
                "order by occurred_at desc, id desc limit 1"
            ),
            {"i": _MID},
        ).one()
    assert offset_audit.after_value == {"value_mm": "5.6883", "source": "presetter_verified"}


def _pot_snap(polled_at: datetime, pots: tuple[PotEntry, ...]) -> MachineSnapshot:
    return MachineSnapshot(
        machine_id="itest", polled_at=polled_at, status=MachineStatus(), pots=pots
    )


def test_pot_reinit_sweep_raises_alarm(engine):
    """A batch of pots snapping to their ordinals in one cycle = suspected reset
    (tools may have been physically ejected). Raises a pot_reinit_suspected event."""
    # Baseline: pots 1-4 hold real, non-ordinal tools.
    real = tuple(PotEntry(pot_number=n, t_number=t) for n, t in [(1, 55), (2, 90), (3, 33), (4, 12)])
    with Session(engine) as s:
        persist(s, _pot_snap(_T0, real), _MID)

    # Next cycle: all four revert to their ordinal (the reinit signature).
    t1 = _T0 + timedelta(seconds=5)
    ordinals = tuple(PotEntry(pot_number=n, t_number=n) for n in (1, 2, 3, 4))
    with Session(engine) as s:
        res = persist(s, _pot_snap(t1, ordinals), _MID)
    assert res.pot_reinit_suspected is True

    with engine.connect() as c:
        row = c.execute(
            sa.text(
                "select after_value, success from shared.audit_log where machine_id = :i "
                "and event_type = 'pot_reinit_suspected' order by id desc limit 1"
            ),
            {"i": _MID},
        ).one()
    assert row.after_value == {"reverted_pots": [1, 2, 3, 4], "count": 4}
    assert row.success is False


def _status_snap(polled_at: datetime, head: int | None, next_t: int | None) -> MachineSnapshot:
    return MachineSnapshot(
        machine_id="itest",
        polled_at=polled_at,
        status=MachineStatus(
            mode=MachineMode.AUTO, running=True, current_t_number=head, next_t_number=next_t
        ),
    )


def test_status_mirror_upserts_and_last_changed_tracks_head(engine):
    """HEAD/NEXT persist to shared.focas_machine_status; last_changed_at advances
    only when a field moves (not on a bare re-read). Status is not audited."""
    # Baseline: HEAD=85 in the spindle, NEXT=31 on deck.
    with Session(engine) as s:
        res = persist(s, _status_snap(_T0, head=85, next_t=31), _MID)
    assert res.status_changed is True

    with engine.connect() as c:
        row = c.execute(
            sa.text(
                "select head_t_number, next_t_number, mode, running, "
                "last_polled_at, last_changed_at "
                "from shared.focas_machine_status where machine_id = :i"
            ),
            {"i": _MID},
        ).one()
    assert row.head_t_number == 85 and row.next_t_number == 31
    assert row.mode == "auto" and row.running is True
    assert row.last_polled_at == _T0 and row.last_changed_at == _T0

    # Re-read, identical HEAD/NEXT: last_polled advances, last_changed does NOT.
    t1 = _T0 + timedelta(seconds=5)
    with Session(engine) as s:
        res = persist(s, _status_snap(t1, head=85, next_t=31), _MID)
    assert res.status_changed is False
    with engine.connect() as c:
        row = c.execute(
            sa.text(
                "select last_polled_at, last_changed_at "
                "from shared.focas_machine_status where machine_id = :i"
            ),
            {"i": _MID},
        ).one()
    assert row.last_polled_at == t1
    assert row.last_changed_at == _T0  # unchanged

    # Tool change: HEAD 85 -> 31. last_changed advances.
    t2 = _T0 + timedelta(seconds=10)
    with Session(engine) as s:
        res = persist(s, _status_snap(t2, head=31, next_t=50), _MID)
    assert res.status_changed is True
    with engine.connect() as c:
        row = c.execute(
            sa.text(
                "select head_t_number, next_t_number, last_changed_at "
                "from shared.focas_machine_status where machine_id = :i"
            ),
            {"i": _MID},
        ).one()
    assert row.head_t_number == 31 and row.next_t_number == 50
    assert row.last_changed_at == t2

    # Status changes are NOT audited (HEAD/NEXT churn every tool change; R17).
    assert _audit_count(engine) == 0


def test_offset_change_without_skip_is_manual(engine):
    """Contrast: the same offset change with NO fresh skip = manual edit (R11)."""
    with Session(engine) as s:
        persist(s, _snap(_T0, "0.0000", skip_5061="-5.5100"), _MID)
    t1 = _T0 + timedelta(seconds=5)
    with Session(engine) as s:
        persist(s, _snap(t1, "5.6883", skip_5061="-5.5100"), _MID)  # skip unchanged
    with engine.connect() as c:
        offset_audit = c.execute(
            sa.text(
                "select after_value from shared.audit_log where machine_id = :i "
                "and entity_type = 'offset' and entity_id = '1/h_geom' "
                "order by occurred_at desc, id desc limit 1"
            ),
            {"i": _MID},
        ).one()
    assert offset_audit.after_value == {"value_mm": "5.6883", "source": "manual_edit"}


def test_presetter_attribution_straddles_two_cycles(engine):
    """Regression for the live 2026-07-28 mis-tag: the ~35s snapshot sweep is not
    atomic, so a preset can land its G31 skip transition in cycle N while the
    H_GEOM offset it wrote is only swept in cycle N+1. The offset change must
    still be attributed `presetter_verified` via the one-cycle lookback."""
    with Session(engine) as s:
        persist(s, _snap(_T0, "0.0000", skip_5061="-5.5100"), _MID)  # baseline
    t1 = _T0 + timedelta(seconds=60)
    with Session(engine) as s:
        # Cycle N: the skip moves (G31 touch captured) but the offset sweep ran
        # before the macro wrote H1 — offset still 0.
        persist(s, _snap(t1, "0.0000", skip_5061="-6.0673"), _MID)
    t2 = _T0 + timedelta(seconds=120)
    with Session(engine) as s:
        # Cycle N+1: offset lands; skip is unchanged this cycle.
        persist(s, _snap(t2, "4.0818", skip_5061="-6.0673"), _MID)
    with engine.connect() as c:
        offset_audit = c.execute(
            sa.text(
                "select after_value from shared.audit_log where machine_id = :i "
                "and entity_type = 'offset' and entity_id = '1/h_geom' "
                "order by occurred_at desc, id desc limit 1"
            ),
            {"i": _MID},
        ).one()
    assert offset_audit.after_value == {"value_mm": "4.0818", "source": "presetter_verified"}


def test_skip_older_than_one_cycle_is_manual(engine):
    """The lookback is exactly ONE cycle: a skip that changed two cycles before
    the offset change no longer attributes it — that window is closed (R11:
    never claim presetter verification on stale evidence)."""
    with Session(engine) as s:
        persist(s, _snap(_T0, "0.0000", skip_5061="-5.5100"), _MID)  # baseline
    t1 = _T0 + timedelta(seconds=60)
    with Session(engine) as s:
        persist(s, _snap(t1, "0.0000", skip_5061="-6.0673"), _MID)  # skip moves
    t2 = _T0 + timedelta(seconds=120)
    with Session(engine) as s:
        persist(s, _snap(t2, "0.0000", skip_5061="-6.0673"), _MID)  # quiet cycle
    t3 = _T0 + timedelta(seconds=180)
    with Session(engine) as s:
        persist(s, _snap(t3, "4.0818", skip_5061="-6.0673"), _MID)  # offset lands
    with engine.connect() as c:
        offset_audit = c.execute(
            sa.text(
                "select after_value from shared.audit_log where machine_id = :i "
                "and entity_type = 'offset' and entity_id = '1/h_geom' "
                "order by occurred_at desc, id desc limit 1"
            ),
            {"i": _MID},
        ).one()
    assert offset_audit.after_value == {"value_mm": "4.0818", "source": "manual_edit"}


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
    # H_GEOM change with no fresh G31 skip in this snapshot is attributed to a
    # manual keypad edit (presetter attribution, #2).
    assert latest.after_value == {"value_mm": "7.4000", "source": "manual_edit"}
