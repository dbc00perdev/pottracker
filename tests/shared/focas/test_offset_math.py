"""Unit tests for the pure offset math (PR-3). No DB, no FOCAS.

Locks the Viper-verified constants (increment, type-code map, writability,
0.5 mm flag) so a regression can't silently reintroduce the 10x or H/D-swap
hazards these encode. See tasks/lessons.md + spec-phase5-write-path §4.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from shared.focas import offset_math as om
from shared.focas.models import RegisterType


def test_increment_is_ten_thousandths_not_thousandths():
    # The 10x hazard: a value of 0.001 here would corrupt every write.
    assert om.OFFSET_INCREMENT_MM == Decimal("0.0001")


@pytest.mark.parametrize(
    ("mm", "counts"),
    [
        ("7.4050", 74050),   # panel H50 cross-check
        ("0.0000", 0),
        ("-100.5000", -1005000),
        ("0.00005", 1),      # half-up rounds to the nearest count
        ("0.00004", 0),
    ],
)
def test_counts_from_mm_round_half_up(mm, counts):
    assert om.counts_from_mm(Decimal(mm)) == counts


def test_mm_counts_round_trip():
    for raw in ("-100.0000", "0.0000", "5.6883", "9999.9999"):
        v = Decimal(raw)
        assert om.mm_from_counts(om.counts_from_mm(v)) == v


def test_type_code_map_has_h_and_d_swapped_vs_docs():
    # This 0i-MF: type=3 -> H_GEOM, type=1 -> D_GEOM (opposite of the FANUC docs).
    assert om.REGISTER_TYPE_TO_CODE == {
        RegisterType.D_GEOM: 1,
        RegisterType.H_WEAR: 2,
        RegisterType.H_GEOM: 3,
        RegisterType.D_WEAR: 4,
    }
    assert om.register_type_code(RegisterType.H_GEOM) == 3
    assert om.CODE_TO_REGISTER_TYPE[3] is RegisterType.H_GEOM


def test_only_h_geom_is_writable_in_v1():
    assert om.is_writable(RegisterType.H_GEOM)
    for t in (RegisterType.H_WEAR, RegisterType.D_GEOM, RegisterType.D_WEAR):
        assert not om.is_writable(t)


def test_assert_writable_refuses_d_wear_unconditionally():
    with pytest.raises(om.OffsetMathError, match="panel-only"):
        om.assert_writable(RegisterType.D_WEAR)


def test_assert_writable_refuses_not_yet_enabled_types():
    with pytest.raises(om.OffsetMathError, match="not writable in v1"):
        om.assert_writable(RegisterType.D_GEOM)


def test_assert_writable_allows_h_geom():
    om.assert_writable(RegisterType.H_GEOM)  # no raise


def test_large_diff_threshold_half_mm():
    assert om.is_large_diff(Decimal("1.0000"), Decimal("1.6000"))       # 0.6 > 0.5
    assert not om.is_large_diff(Decimal("1.0000"), Decimal("1.5000"))   # exactly 0.5 not "large"
    assert not om.is_large_diff(Decimal("1.0000"), Decimal("1.4000"))


def test_within_bounds_guard():
    assert om.within_bounds(Decimal("9999.9999"))
    assert om.within_bounds(Decimal("-9999.9999"))
    assert not om.within_bounds(Decimal("10000.0000"))


def test_verify_increment_refuses_disagreement():
    om.verify_increment(Decimal("0.0001"))  # no raise
    with pytest.raises(om.OffsetMathError, match="10x scaling hazard"):
        om.verify_increment(Decimal("0.001"))
