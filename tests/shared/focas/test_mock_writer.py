"""Unit tests for the labeled mock write surface (PR-3). No DB, no hardware.

Proves the mock round-trips a write (so read-after-write verification is a real
check), records commanded writes, and can simulate the two failure modes the
lifecycle guards against: a rejected write and a control that stores a corrupted
value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from shared.focas.mock import MockOffsetWriteError, MockOffsetWriter
from shared.focas.models import RegisterType


def test_write_then_read_round_trips():
    w = MockOffsetWriter()
    w.write_offset(19, RegisterType.H_GEOM, Decimal("5.6883"))
    assert w.read_offset(19, RegisterType.H_GEOM) == Decimal("5.6883")
    assert w.writes == [(19, RegisterType.H_GEOM, Decimal("5.6883"))]


def test_unwritten_register_reads_zero():
    assert MockOffsetWriter().read_offset(7, RegisterType.H_GEOM) == Decimal("0.0000")


def test_reject_raises_and_does_not_store():
    w = MockOffsetWriter(reject=True)
    with pytest.raises(MockOffsetWriteError):
        w.write_offset(3, RegisterType.H_GEOM, Decimal("1.0000"))
    # commanded write is still recorded, but nothing was stored
    assert w.writes == [(3, RegisterType.H_GEOM, Decimal("1.0000"))]
    assert w.read_offset(3, RegisterType.H_GEOM) == Decimal("0.0000")


def test_corrupt_delta_makes_readback_mismatch():
    w = MockOffsetWriter(corrupt_delta_mm=Decimal("0.0010"))
    w.write_offset(19, RegisterType.H_GEOM, Decimal("5.0000"))
    assert w.read_offset(19, RegisterType.H_GEOM) == Decimal("5.0010")


def test_from_baseline_seeds_the_viper_table():
    w = MockOffsetWriter.from_baseline()
    # baseline H_GEOM #1 = -100.5000 (see mock._viper_baseline_offsets)
    assert w.read_offset(1, RegisterType.H_GEOM) == Decimal("-100.5000")
