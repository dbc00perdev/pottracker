"""Unit tests for shared.focas.models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from shared.focas.models import (
    AlarmEntry,
    MachineMode,
    MachineSnapshot,
    MachineStatus,
    OffsetRegister,
    PotEntry,
    RegisterType,
    ToolLife,
    ToolLifeStatus,
)


class TestOffsetRegister:
    def test_quantizes_to_four_decimals(self):
        r = OffsetRegister(
            register_number=1,
            register_type=RegisterType.H_GEOM,
            value_mm=Decimal("1.23456789"),
        )
        assert r.value_mm == Decimal("1.2346")

    def test_rejects_register_number_zero(self):
        with pytest.raises(ValidationError):
            OffsetRegister(
                register_number=0,
                register_type=RegisterType.H_GEOM,
                value_mm=Decimal("0"),
            )

    def test_rejects_implausible_offset(self):
        with pytest.raises(ValidationError):
            OffsetRegister(
                register_number=1,
                register_type=RegisterType.H_GEOM,
                value_mm=Decimal("99999.0"),
            )

    def test_frozen(self):
        r = OffsetRegister(
            register_number=1,
            register_type=RegisterType.H_GEOM,
            value_mm=Decimal("1.0"),
        )
        with pytest.raises(ValidationError):
            r.value_mm = Decimal("2.0")  # type: ignore[misc]


class TestPotEntry:
    def test_empty_pot(self):
        p = PotEntry(pot_number=5, t_number=None)
        assert p.t_number is None

    def test_t_number_in_range(self):
        with pytest.raises(ValidationError):
            PotEntry(pot_number=1, t_number=0)


class TestToolLife:
    def test_negative_life_count_rejected(self):
        with pytest.raises(ValidationError):
            ToolLife(t_number=1, life_count=-1, life_max=100, status=ToolLifeStatus.LIVE)


class TestMachineSnapshot:
    def _empty(self):
        return MachineSnapshot(
            machine_id="m",
            polled_at=datetime.now(UTC),
            status=MachineStatus(mode=MachineMode.MEM),
        )

    def test_empty_snapshot_valid(self):
        s = self._empty()
        assert s.offsets == ()
        assert s.pots == ()

    def test_duplicate_offset_keys_rejected(self):
        dup = (
            OffsetRegister(
                register_number=1, register_type=RegisterType.H_GEOM, value_mm=Decimal("1")
            ),
            OffsetRegister(
                register_number=1, register_type=RegisterType.H_GEOM, value_mm=Decimal("2")
            ),
        )
        with pytest.raises(ValidationError):
            MachineSnapshot(
                machine_id="m",
                polled_at=datetime.now(UTC),
                status=MachineStatus(mode=MachineMode.MEM),
                offsets=dup,
            )

    def test_same_register_different_type_allowed(self):
        ok = (
            OffsetRegister(
                register_number=1, register_type=RegisterType.H_GEOM, value_mm=Decimal("1")
            ),
            OffsetRegister(
                register_number=1, register_type=RegisterType.H_WEAR, value_mm=Decimal("0")
            ),
        )
        s = MachineSnapshot(
            machine_id="m",
            polled_at=datetime.now(UTC),
            status=MachineStatus(mode=MachineMode.MEM),
            offsets=ok,
        )
        assert len(s.offsets) == 2

    def test_duplicate_pot_numbers_rejected(self):
        dup = (
            PotEntry(pot_number=1, t_number=1),
            PotEntry(pot_number=1, t_number=2),
        )
        with pytest.raises(ValidationError):
            MachineSnapshot(
                machine_id="m",
                polled_at=datetime.now(UTC),
                status=MachineStatus(mode=MachineMode.MEM),
                pots=dup,
            )


class TestMachineStatus:
    def test_default_unknown(self):
        s = MachineStatus()
        assert s.mode is MachineMode.UNKNOWN
        assert s.running is False
        assert s.emergency_stop is False


class TestAlarmEntry:
    def test_minimal(self):
        a = AlarmEntry(code=506)
        assert a.message == ""
        assert a.axis is None
