"""Pure-logic tests for the parameter-1013/1001 increment decode
(`shared/focas/params.py`). The live `cnc_rdparam` binding is exercised by
the fleet unit-verify harness (reports/fleet-unit-verify-*.json), same
division of labor as the smoke vs. decoder tests.
"""

import ctypes
from decimal import Decimal

import pytest

from shared.focas.params import (
    _IODBPSD,
    IncrementSystem,
    decode_is_system,
    increment_for,
)


class TestDecodeIsSystem:
    def test_all_bits_clear_is_b(self):
        assert decode_is_system(0x00) == "IS-B"

    @pytest.mark.parametrize(
        ("byte", "expected"),
        [
            (0x01, "IS-A"),
            (0x02, "IS-C"),
            (0x04, "IS-D"),
            (0x08, "IS-E"),
        ],
    )
    def test_selector_bits(self, byte, expected):
        assert decode_is_system(byte) == expected

    def test_unrelated_high_bits_do_not_change_is_b(self):
        # 1013 carries other per-axis bits above the IS selectors; they must
        # not perturb the decode.
        assert decode_is_system(0xF0) == "IS-B"


class TestIncrementFor:
    def test_inch_is_b_is_the_fleet_value(self):
        # The shop-wide confirmed configuration (dbc00per 2026-08-05):
        # inch INPUT + 1013 all zeros -> 0.0001 inch/count, which must
        # equal DEFAULT_OFFSET_INCREMENT.
        from shared.focas.decoders import DEFAULT_OFFSET_INCREMENT

        assert increment_for("IS-B", inch_input=True) == DEFAULT_OFFSET_INCREMENT

    @pytest.mark.parametrize(
        ("is_system", "inch", "expected"),
        [
            ("IS-A", True, Decimal("0.001")),
            ("IS-C", True, Decimal("0.00001")),
            ("IS-A", False, Decimal("0.01")),
            ("IS-B", False, Decimal("0.001")),
            ("IS-C", False, Decimal("0.0001")),
        ],
    )
    def test_matrix(self, is_system, inch, expected):
        assert increment_for(is_system, inch_input=inch) == expected

    def test_metric_is_b_is_the_25x4_trap(self):
        # The 2026-07-15 incident: metric IS-B (0.001 mm) vs inch IS-B
        # (0.0001 inch) — same digits family, 25.4x apart in meaning. The
        # two must be distinct values so a unit mix-up cannot be silent.
        assert increment_for("IS-B", False) != increment_for("IS-B", True)


class TestIncrementSystem:
    def test_uniform_true_when_all_axes_agree(self):
        s = IncrementSystem(
            inch_input=True,
            inch_machine=False,
            p1013_per_axis=(0, 0, 0),
            is_system_per_axis=("IS-B", "IS-B", "IS-B"),
            increment=Decimal("0.0001"),
        )
        assert s.uniform

    def test_uniform_false_on_mixed_axes(self):
        s = IncrementSystem(
            inch_input=True,
            inch_machine=False,
            p1013_per_axis=(0, 2),
            is_system_per_axis=("IS-B", "IS-C"),
            increment=Decimal("0.0001"),
        )
        assert not s.uniform


class TestStructShape:
    def test_iodbpsd_header_is_two_shorts(self):
        # datano + type = 4-byte header before the union — the "4 +" in
        # every documented cnc_rdparam length.
        assert _IODBPSD.u.offset == 4

    def test_union_holds_max_axis_int32s(self):
        # Largest arm bound in this module: ldatas[32] = 128 bytes.
        assert ctypes.sizeof(_IODBPSD) == 4 + 128
