"""Tests for shared.focas.snapshot.

The diff layer is pure (no DB) and gets the thorough coverage here. The persist
orchestration is exercised with a fake session that stands in for SQLAlchemy —
the real DB round-trip is an integration test (Docker Postgres, Phase 2 Step 7),
deliberately not a unit test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from shared.focas.models import (
    MachineSnapshot,
    MachineStatus,
    OffsetRegister,
    PotEntry,
    RegisterType,
    ToolLife,
    ToolLifeStatus,
)
from shared.focas.snapshot import (
    PersistResult,
    diff_offsets,
    diff_pots,
    diff_tool_life,
    persist,
)

_MID = UUID("00000000-0000-0000-0000-0000000000aa")
_T = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _off(num: int, rtype: RegisterType, value: str) -> OffsetRegister:
    return OffsetRegister(register_number=num, register_type=rtype, value_mm=Decimal(value))


# ============================================================================
# diff_offsets
# ============================================================================


class TestDiffOffsets:
    def test_new_register_upserts_and_audits(self):
        d = diff_offsets({}, (_off(1, RegisterType.H_GEOM, "7.4050"),), _MID, _T)
        assert len(d.upsert_params) == 1
        p = d.upsert_params[0]
        assert p["machine_id"] == _MID
        assert p["register_number"] == 1
        assert p["register_type"] == "h_geom"
        assert p["value_mm"] == Decimal("7.4050")
        assert p["last_polled_at"] == _T
        assert p["last_changed_at"] == _T
        assert len(d.audits) == 1
        a = d.audits[0]
        assert a.event_type == "offset_change"
        assert a.entity_id == "1/h_geom"
        assert a.before is None
        assert a.after == {"value_mm": "7.4050"}

    def test_unchanged_value_upserts_without_audit(self):
        current = {(1, "h_geom"): Decimal("7.4050")}
        d = diff_offsets(current, (_off(1, RegisterType.H_GEOM, "7.4050"),), _MID, _T)
        assert len(d.upsert_params) == 1  # still touch last_polled_at
        assert d.audits == []

    def test_changed_value_audits_before_after(self):
        current = {(1, "h_geom"): Decimal("7.4050")}
        d = diff_offsets(current, (_off(1, RegisterType.H_GEOM, "7.4000"),), _MID, _T)
        assert len(d.audits) == 1
        a = d.audits[0]
        assert a.before == {"value_mm": "7.4050"}
        assert a.after == {"value_mm": "7.4000"}

    def test_before_after_values_are_json_safe_strings(self):
        # value_mm must be str, never Decimal — JSONB can't serialize Decimal.
        d = diff_offsets({}, (_off(5, RegisterType.D_GEOM, "-0.3000"),), _MID, _T)
        assert isinstance(d.audits[0].after["value_mm"], str)


# ============================================================================
# diff_pots
# ============================================================================


class TestDiffPots:
    def test_new_pot_audits_with_null_before(self):
        d = diff_pots({}, (PotEntry(pot_number=3, t_number=45),), _MID, _T)
        assert d.upsert_params[0]["t_number"] == 45
        assert len(d.audits) == 1
        assert d.audits[0].before is None
        assert d.audits[0].after == {"t_number": 45}

    def test_unchanged_pot_no_audit(self):
        d = diff_pots({3: 45}, (PotEntry(pot_number=3, t_number=45),), _MID, _T)
        assert d.audits == []

    def test_empty_to_occupied_is_a_change(self):
        # old NULL -> new value must count (regression guard for NULL compares).
        d = diff_pots({3: None}, (PotEntry(pot_number=3, t_number=45),), _MID, _T)
        assert len(d.audits) == 1
        assert d.audits[0].before == {"t_number": None}
        assert d.audits[0].after == {"t_number": 45}

    def test_occupied_to_empty_is_a_change(self):
        d = diff_pots({3: 45}, (PotEntry(pot_number=3, t_number=None),), _MID, _T)
        assert len(d.audits) == 1
        assert d.audits[0].after == {"t_number": None}


# ============================================================================
# diff_tool_life
# ============================================================================


class TestDiffToolLife:
    def test_new_tool_audits(self):
        tl = ToolLife(t_number=45, life_count=10, life_max=100, status=ToolLifeStatus.LIVE)
        d = diff_tool_life({}, (tl,), _MID, _T)
        assert d.upsert_params[0]["status"] == "live"
        assert "last_changed_at" not in d.upsert_params[0]  # table has no such col
        assert len(d.audits) == 1
        assert d.audits[0].before is None

    def test_unchanged_no_audit(self):
        tl = ToolLife(t_number=45, life_count=10, life_max=100, status=ToolLifeStatus.LIVE)
        d = diff_tool_life({45: (10, 100, "live")}, (tl,), _MID, _T)
        assert d.audits == []

    def test_count_increase_audits(self):
        tl = ToolLife(t_number=45, life_count=11, life_max=100, status=ToolLifeStatus.LIVE)
        d = diff_tool_life({45: (10, 100, "live")}, (tl,), _MID, _T)
        assert len(d.audits) == 1

    def test_count_reset_decrease_audits(self):
        # A decrease = tool replaced; must NOT be filtered out.
        tl = ToolLife(t_number=45, life_count=0, life_max=100, status=ToolLifeStatus.LIVE)
        d = diff_tool_life({45: (99, 100, "live")}, (tl,), _MID, _T)
        assert len(d.audits) == 1
        assert d.audits[0].after == {"life_count": 0, "life_max": 100, "status": "live"}

    def test_status_transition_audits(self):
        tl = ToolLife(t_number=45, life_count=100, life_max=100, status=ToolLifeStatus.EXPIRED)
        d = diff_tool_life({45: (100, 100, "live")}, (tl,), _MID, _T)
        assert len(d.audits) == 1
        assert d.audits[0].after["status"] == "expired"


# ============================================================================
# persist orchestration — fake session, no DB
# ============================================================================


class _FakeSession:
    """Minimal Session stand-in. SELECTs return empty (mirror starts empty ->
    everything is 'new'); UPSERT/INSERT executes are recorded; commit flagged."""

    def __init__(self) -> None:
        self.executes: list[Any] = []
        self.committed = False

    def execute(self, *args: Any) -> list[Any]:
        self.executes.append(args)
        return []  # empty result set for the SELECT loaders

    def commit(self) -> None:
        self.committed = True


def _snapshot() -> MachineSnapshot:
    return MachineSnapshot(
        machine_id="viper-lg-1000ap",
        polled_at=_T,
        status=MachineStatus(),
        offsets=(_off(1, RegisterType.H_GEOM, "7.4050"), _off(1, RegisterType.D_GEOM, "0.2360")),
        pots=(PotEntry(pot_number=1, t_number=45),),
        tool_life=(ToolLife(t_number=45, life_count=10, life_max=100, status=ToolLifeStatus.LIVE),),
    )


class TestPersist:
    def test_empty_mirror_counts_everything_as_change_and_commits(self):
        session = _FakeSession()
        result = persist(session, _snapshot(), _MID)
        assert isinstance(result, PersistResult)
        assert result.offsets_observed == 2
        assert result.offsets_changed == 2
        assert result.pots_observed == 1
        assert result.pots_changed == 1
        assert result.tool_life_observed == 1
        assert result.tool_life_changed == 1
        assert result.audit_rows == 4
        assert session.committed is True

    def test_persist_returns_zero_changes_on_empty_snapshot(self):
        session = _FakeSession()
        empty = MachineSnapshot(machine_id="viper", polled_at=_T, status=MachineStatus())
        result = persist(session, empty, _MID)
        assert result.audit_rows == 0
        assert session.committed is True
