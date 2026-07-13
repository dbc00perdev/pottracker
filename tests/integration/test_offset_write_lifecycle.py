"""Integration test: the offset write-path lifecycle (PR-3) against a live DB.

Proves `offset_write.create_request -> execute_request` drives a real
`tooling.offset_write_request` row through the full gate + mock write + verify,
writes the right `audit_log` rows, and blocks/fails on each guard — all against
the migrated dev Postgres, using ONLY the labeled mock write surface (no FOCAS,
no hardware). Skips cleanly when DATABASE_URL is unset.
"""

from __future__ import annotations

import os
from decimal import Decimal
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.tooling.api.config import Settings
from apps.tooling.api.errors import Conflict, Forbidden, Unprocessable
from apps.tooling.api.services import offset_write
from shared.focas.mock import MockOffsetWriter
from shared.focas.models import MachineMode, MachineStatus, RegisterType

pytestmark = pytest.mark.integration

_DSN = os.environ.get("DATABASE_URL")
_MID = UUID("22222222-2222-2222-2222-222222222222")
_UID = UUID("22222222-2222-2222-2222-2222222222aa")
_PW = "gate-pw-under-test"


def _settings() -> Settings:
    return Settings(database_url="", jwt_secret="x", jwt_access_ttl=900,
                    jwt_refresh_ttl=86400, log_level="INFO", write_approval_password=_PW)


def _safe_status() -> MachineStatus:
    return MachineStatus(mode=MachineMode.MDI, running=False)


@pytest.fixture
def engine():
    if not _DSN:
        pytest.skip("DATABASE_URL not set")
    dsn = _DSN.replace("postgresql://", "postgresql+psycopg://", 1)
    eng = create_engine(dsn)
    try:
        with eng.connect() as c:
            c.execute(sa.text("select 1 from tooling.offset_write_request where false"))
    except Exception as exc:
        eng.dispose()
        pytest.skip(f"migrated dev DB not available: {exc}")
    _cleanup(eng)
    with eng.begin() as c:
        c.execute(
            sa.text(
                "insert into shared.machine "
                "(id, name, control_model, ip_address, pot_count, atc_strategy, "
                " probe_t_number, probe_h_register) "
                "values (:i, 'itest-owr', '0i-MF', '10.1.10.58', 24, 'random_access', 50, 50)"
            ),
            {"i": _MID},
        )
        c.execute(
            sa.text(
                "insert into shared.user (id, username, display_name, role, password_hash) "
                "values (:u, 'itest-owr', 'itest', 'setter', 'x')"
            ),
            {"u": _UID},
        )
    yield eng
    _cleanup(eng)
    eng.dispose()


def _cleanup(eng) -> None:
    with eng.begin() as c:
        c.execute(sa.text("delete from tooling.offset_write_request where machine_id = :i"),
                  {"i": _MID})
        c.execute(sa.text("delete from shared.audit_log where machine_id = :i"), {"i": _MID})
        c.execute(sa.text("delete from shared.machine where id = :i"), {"i": _MID})
        c.execute(sa.text("delete from shared.user where id = :u"), {"u": _UID})


def _create(session, target, *, register=19, value="5.6883", reason="post-preset confirm"):
    return offset_write.create_request(
        session, machine_id=_MID, register_number=register,
        register_type=RegisterType.H_GEOM, intended_value_mm=Decimal(value),
        reason=reason, requested_by=_UID, target=target,
    )


def test_happy_path_writes_verifies_and_audits(engine):
    target = MockOffsetWriter()  # register 19 reads 0.0000
    with Session(engine) as s:
        rid = _create(s, target, value="0.2500")  # < 0.5 mm: a normal no-ack write
        row = offset_write.execute_request(
            s, rid, executing_user=_UID, status=_safe_status(), approved=True,
            password_attempt=_PW, settings=_settings(), target=target,
        )
        s.commit()
        assert row.success is True
        assert Decimal(row.verified_value_mm) == Decimal("0.2500")
        assert row.executed_at is not None
    # target actually got the write, and an offset_write audit row exists
    assert target.read_offset(19, RegisterType.H_GEOM) == Decimal("0.2500")
    with engine.connect() as c:
        ok = c.execute(
            sa.text("select success, after_value from shared.audit_log "
                    "where machine_id = :i and event_type = 'offset_write' "
                    "order by id desc limit 1"),
            {"i": _MID},
        ).one()
        assert ok.success is True
        assert ok.after_value == {"value_mm": "0.2500"}


def test_bad_password_blocks_and_leaves_request_pending(engine):
    target = MockOffsetWriter()
    with Session(engine) as s:
        rid = _create(s, target)
        with pytest.raises(Forbidden):
            offset_write.execute_request(
                s, rid, executing_user=_UID, status=_safe_status(), approved=True,
                password_attempt="wrong", settings=_settings(), target=target,
            )
        s.commit()
        row = offset_write.get(s, rid)
        assert row.executed_at is None       # still pending, retryable
        assert row.success is None
    assert target.writes == []               # nothing was written


def test_running_machine_blocks(engine):
    target = MockOffsetWriter()
    with Session(engine) as s:
        rid = _create(s, target)
        with pytest.raises(Forbidden):
            offset_write.execute_request(
                s, rid, executing_user=_UID,
                status=MachineStatus(mode=MachineMode.AUTO, running=True),
                approved=True, password_attempt=_PW, settings=_settings(), target=target,
            )
        s.commit()
    assert target.writes == []


def test_drift_aborts_and_fails_the_request(engine):
    target = MockOffsetWriter()
    with Session(engine) as s:
        rid = _create(s, target)               # captures current_value 0.0000
        s.commit()
    # someone moves the register out from under the staged request
    target.write_offset(19, RegisterType.H_GEOM, Decimal("1.2345"))
    with Session(engine) as s:
        with pytest.raises(Conflict, match="changed since"):
            offset_write.execute_request(
                s, rid, executing_user=_UID, status=_safe_status(), approved=True,
                password_attempt=_PW, settings=_settings(), target=target,
            )
        s.commit()
        row = offset_write.get(s, rid)
        assert row.success is False
        assert "drift" in row.error


def test_large_diff_requires_acknowledgement(engine):
    target = MockOffsetWriter()  # reg 19 = 0.0000
    with Session(engine) as s:
        rid = _create(s, target, value="0.7500")   # 0.75 mm > 0.5 mm threshold
        with pytest.raises(Unprocessable, match="acknowledgement required"):
            offset_write.execute_request(
                s, rid, executing_user=_UID, status=_safe_status(), approved=True,
                password_attempt=_PW, settings=_settings(), target=target,
            )
        s.rollback()
    # with the ack it goes through
    target2 = MockOffsetWriter()
    with Session(engine) as s:
        rid = _create(s, target2, value="0.7500")
        row = offset_write.execute_request(
            s, rid, executing_user=_UID, status=_safe_status(), approved=True,
            password_attempt=_PW, settings=_settings(), target=target2,
            large_diff_acknowledged=True,
        )
        s.commit()
        assert row.success is True


def test_read_after_write_mismatch_fails(engine):
    target = MockOffsetWriter(corrupt_delta_mm=Decimal("0.0010"))  # stores wrong value
    with Session(engine) as s:
        rid = _create(s, target, value="0.2500")  # no-ack; corrupt makes readback differ
        with pytest.raises(Conflict, match="verification failed"):
            offset_write.execute_request(
                s, rid, executing_user=_UID, status=_safe_status(), approved=True,
                password_attempt=_PW, settings=_settings(), target=target,
            )
        s.commit()
        row = offset_write.get(s, rid)
        assert row.success is False
        assert Decimal(row.verified_value_mm) == Decimal("0.2510")


def test_probe_register_refused_at_request_time(engine):
    target = MockOffsetWriter()
    with Session(engine) as s:
        with pytest.raises(Unprocessable, match="probe H register"):
            _create(s, target, register=50)     # probe_h_register = 50
        s.rollback()


def test_d_wear_refused_at_request_time(engine):
    target = MockOffsetWriter()
    with Session(engine) as s:
        with pytest.raises(Unprocessable, match="panel-only"):
            offset_write.create_request(
                s, machine_id=_MID, register_number=19,
                register_type=RegisterType.D_WEAR, intended_value_mm=Decimal("1.0"),
                reason="x", requested_by=_UID, target=target,
            )
        s.rollback()
