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
    MacroVariable,
    OffsetRegister,
    PotEntry,
    RegisterType,
    ToolLife,
    ToolLifeStatus,
)
from shared.focas.snapshot import (
    PersistResult,
    detect_pot_reinit,
    diff_macros,
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
        # H_GEOM change with no fresh skip is attributed to a manual edit.
        current = {(1, "h_geom"): Decimal("7.4050")}
        d = diff_offsets(current, (_off(1, RegisterType.H_GEOM, "7.4000"),), _MID, _T)
        assert len(d.audits) == 1
        a = d.audits[0]
        assert a.before == {"value_mm": "7.4050"}
        assert a.after == {"value_mm": "7.4000", "source": "manual_edit"}

    def test_h_geom_change_with_fresh_skip_attributed_to_presetter(self):
        current = {(1, "h_geom"): Decimal("0.0000")}
        d = diff_offsets(
            current,
            (_off(1, RegisterType.H_GEOM, "5.6883"),),
            _MID,
            _T,
            presetter_active=True,
        )
        assert d.audits[0].after == {"value_mm": "5.6883", "source": "presetter_verified"}

    def test_first_observation_h_geom_not_attributed(self):
        # A baseline capture (no prior value) is not an edit — no source tag,
        # even if a skip fired this cycle.
        d = diff_offsets({}, (_off(1, RegisterType.H_GEOM, "5.6883"),), _MID, _T, presetter_active=True)
        assert d.audits[0].after == {"value_mm": "5.6883"}

    def test_non_h_geom_change_not_attributed(self):
        # Only H_GEOM is presetter-written; wear/diameter changes carry no tag.
        current = {(1, "h_wear"): Decimal("0.1000")}
        d = diff_offsets(
            current, (_off(1, RegisterType.H_WEAR, "0.2000"),), _MID, _T, presetter_active=True
        )
        assert d.audits[0].after == {"value_mm": "0.2000"}

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
# diff_macros
# ============================================================================


def _macro(number: int, value: str | None) -> MacroVariable:
    return MacroVariable(number=number, value=None if value is None else Decimal(value))


class TestDiffMacros:
    def test_new_macro_audits_with_null_before(self):
        d = diff_macros({}, (_macro(5061, "-5.5100"),), _MID, _T)
        assert d.upsert_params[0]["value"] == Decimal("-5.5100")
        assert len(d.audits) == 1
        assert d.audits[0].entity_type == "macro"
        assert d.audits[0].entity_id == "5061"
        assert d.audits[0].before is None
        assert d.audits[0].after == {"value": "-5.5100"}

    def test_unchanged_macro_no_audit(self):
        d = diff_macros({5061: Decimal("-5.5100")}, (_macro(5061, "-5.5100"),), _MID, _T)
        assert d.upsert_params  # still touches last_polled_at
        assert d.audits == []

    def test_changed_macro_audits_before_after(self):
        # The G31 skip latch moving = the presetter fired.
        d = diff_macros({5061: Decimal("-5.5100")}, (_macro(5061, "-4.0100"),), _MID, _T)
        assert len(d.audits) == 1
        assert d.audits[0].before == {"value": "-5.5100"}
        assert d.audits[0].after == {"value": "-4.0100"}

    def test_vacant_to_value_is_a_change(self):
        d = diff_macros({5061: None}, (_macro(5061, "1.0000"),), _MID, _T)
        assert len(d.audits) == 1
        assert d.audits[0].before == {"value": None}
        assert d.audits[0].after == {"value": "1.0000"}

    def test_json_values_are_strings_or_none(self):
        d = diff_macros({}, (_macro(5062, None),), _MID, _T)
        after = d.audits[0].after
        assert after == {"value": None}


# ============================================================================
# detect_pot_reinit
# ============================================================================


def _pot(n: int, t: int | None) -> PotEntry:
    return PotEntry(pot_number=n, t_number=t)


class TestDetectPotReinit:
    def test_batch_reverting_to_ordinal_is_detected(self):
        # pots 1..4 held real tools; all snap to their ordinal in one cycle.
        current = {1: 55, 2: 90, 3: 33, 4: 12}
        incoming = tuple(_pot(n, n) for n in (1, 2, 3, 4))
        assert detect_pot_reinit(current, incoming) == [1, 2, 3, 4]

    def test_single_pot_at_ordinal_is_not_flagged(self):
        # A legit tool whose number equals its pot (T1 in pot 1) is not a revert.
        current = {1: 1}
        assert detect_pot_reinit(current, (_pot(1, 1),)) == []

    def test_first_observation_is_not_a_revert(self):
        # No prior value -> baseline capture, not a reset.
        assert detect_pot_reinit({}, (_pot(1, 1),)) == []

    def test_nonordinal_change_is_not_a_revert(self):
        current = {1: 55}
        assert detect_pot_reinit(current, (_pot(1, 90),)) == []


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
