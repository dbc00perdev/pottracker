"""Unit tests for shared.focas.mock."""

from __future__ import annotations

from decimal import Decimal

from shared.focas.mock import (
    CANONICAL_SCENARIOS,
    MockFocasSource,
    viper_estop,
    viper_idle,
    viper_offset_drifted,
    viper_offset_significantly_drifted,
    viper_pot_swap,
    viper_running_auto,
)
from shared.focas.models import MachineMode, RegisterType


class TestCanonicalScenarios:
    def test_all_scenarios_produce_valid_snapshots(self):
        for sc in CANONICAL_SCENARIOS:
            snap = sc.snapshot()
            assert snap.machine_id == sc.machine_id
            assert len(snap.offsets) > 0
            assert len(snap.pots) > 0

    def test_idle_no_alarms_not_running(self):
        s = viper_idle().snapshot()
        assert s.alarms == ()
        assert s.status.running is False
        assert s.status.mode is MachineMode.MEM

    def test_running_auto_blocks_writes_semantically(self):
        s = viper_running_auto().snapshot()
        assert s.status.running is True
        assert s.status.mode is MachineMode.AUTO

    def test_estop_flagged(self):
        s = viper_estop().snapshot()
        assert s.status.emergency_stop is True


class TestDrift:
    def _h_geom(self, snap, n: int):
        return next(
            o for o in snap.offsets
            if o.register_number == n and o.register_type == RegisterType.H_GEOM
        )

    def test_small_drift_recorded(self):
        baseline = viper_idle().snapshot()
        drifted = viper_offset_drifted(register_number=5, delta_mm="0.0450").snapshot()
        delta = self._h_geom(drifted, 5).value_mm - self._h_geom(baseline, 5).value_mm
        assert delta == Decimal("0.0450")

    def test_significant_drift_above_half_mm(self):
        baseline = viper_idle().snapshot()
        drifted = viper_offset_significantly_drifted(register_number=7).snapshot()
        delta = self._h_geom(drifted, 7).value_mm - self._h_geom(baseline, 7).value_mm
        assert abs(delta) > Decimal("0.5")


class TestPotSwap:
    def test_swap_swaps_t_numbers_at_pots(self):
        baseline = viper_idle().snapshot()
        b_t1 = next(p for p in baseline.pots if p.t_number == 1)
        b_t2 = next(p for p in baseline.pots if p.t_number == 2)

        swapped = viper_pot_swap(t_a=1, t_b=2).snapshot()
        s_at_b_t1_pot = next(p for p in swapped.pots if p.pot_number == b_t1.pot_number)
        s_at_b_t2_pot = next(p for p in swapped.pots if p.pot_number == b_t2.pot_number)

        assert s_at_b_t1_pot.t_number == 2
        assert s_at_b_t2_pot.t_number == 1


class TestMockFocasSource:
    def test_default_yields_idle(self):
        src = MockFocasSource()
        snap = src.poll()
        assert snap.status.mode is MachineMode.MEM

    def test_cycles_scenarios(self):
        src = MockFocasSource([viper_idle(), viper_running_auto()])
        a = src.poll()
        b = src.poll()
        c = src.poll()
        assert a.status.running is False
        assert b.status.running is True
        assert c.status.running is False  # wraps

    def test_clock_advances(self):
        src = MockFocasSource()
        a = src.poll()
        src.advance_clock(60)
        b = src.poll()
        assert (b.polled_at - a.polled_at).total_seconds() == 60

    def test_stream_yields_n(self):
        src = MockFocasSource([viper_idle()])
        out = list(src.stream(5))
        assert len(out) == 5
