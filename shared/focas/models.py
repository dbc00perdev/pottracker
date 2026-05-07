"""Pydantic models for FOCAS responses.

Protocol-agnostic. These types describe the *shape* of data we read from FANUC
controls, independent of whether the underlying transport is `pyfocas`, a
ctypes wrapper around `Fwlib32.dll`, or the mock harness in `mock.py`.

All lengths are millimeters. The FOCAS boundary (in `client.py`, future) is the
only place unit conversion happens. See CLAUDE.md "Offset math" rules.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterType(StrEnum):
    """FANUC mill offset register categories (30i-M layout)."""

    H_GEOM = "h_geom"
    H_WEAR = "h_wear"
    D_GEOM = "d_geom"
    D_WEAR = "d_wear"


class MachineMode(StrEnum):
    """Coarse machine mode reported by `cnc_statinfo`. Exact mapping verified
    against 30i-B SDK in `tasks/spec-focas-calls.md` before client.py uses it."""

    MDI = "mdi"
    MEM = "mem"
    EDIT = "edit"
    HND = "hnd"
    JOG = "jog"
    REF = "ref"
    AUTO = "auto"
    UNKNOWN = "unknown"


class ToolLifeStatus(StrEnum):
    LIVE = "live"
    EXPIRED = "expired"
    SKIPPED = "skipped"


# Plausibility bounds. Wide on purpose — narrow per-register-type validation
# is a Phase 6 writer concern, not a Phase 1 read concern. We just want to
# catch obviously corrupt values from a misdecoded FOCAS response.
_OFFSET_MIN_MM = Decimal("-9999.9999")
_OFFSET_MAX_MM = Decimal("9999.9999")

OffsetValueMM = Annotated[Decimal, Field(ge=_OFFSET_MIN_MM, le=_OFFSET_MAX_MM)]


class OffsetRegister(BaseModel):
    """One row of the FANUC offset table."""

    model_config = ConfigDict(frozen=True)

    register_number: int = Field(ge=1, le=999)
    register_type: RegisterType
    value_mm: OffsetValueMM

    @field_validator("value_mm")
    @classmethod
    def _quantize(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.0001"))


class PotEntry(BaseModel):
    """One slot in the magazine pot table.

    `t_number=None` means the pot is empty. Pot is observed state; on a
    random-access ATC the pot↔T mapping drifts during operation (see R10).
    """

    model_config = ConfigDict(frozen=True)

    pot_number: int = Field(ge=1, le=999)
    t_number: int | None = Field(default=None, ge=1, le=99999)


class ToolLife(BaseModel):
    """Tool life counter row from FANUC tool life management."""

    model_config = ConfigDict(frozen=True)

    t_number: int = Field(ge=1, le=99999)
    life_count: int | None = Field(default=None, ge=0)
    life_max: int | None = Field(default=None, ge=0)
    status: ToolLifeStatus | None = None


class AlarmEntry(BaseModel):
    """Single FANUC alarm row."""

    model_config = ConfigDict(frozen=True)

    code: int
    axis: int | None = None
    message: str = ""


class MachineStatus(BaseModel):
    """Decoded `cnc_statinfo` output relevant to write-safety gates.

    `mode == AUTO` + `running == True` means writes are forbidden (R6
    mitigation: mode lockout)."""

    model_config = ConfigDict(frozen=True)

    mode: MachineMode = MachineMode.UNKNOWN
    running: bool = False
    emergency_stop: bool = False
    current_t_number: int | None = Field(default=None, ge=0, le=99999)


class MachineSnapshot(BaseModel):
    """Full per-poll snapshot for one machine. Emitted by `poller`, consumed
    by `snapshot.py` (Phase 2) for diff-and-persist."""

    model_config = ConfigDict(frozen=True)

    machine_id: str
    polled_at: datetime
    status: MachineStatus
    offsets: tuple[OffsetRegister, ...] = ()
    pots: tuple[PotEntry, ...] = ()
    tool_life: tuple[ToolLife, ...] = ()
    alarms: tuple[AlarmEntry, ...] = ()

    @field_validator("offsets")
    @classmethod
    def _unique_offset_keys(cls, v: tuple[OffsetRegister, ...]) -> tuple[OffsetRegister, ...]:
        keys = [(o.register_number, o.register_type) for o in v]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate (register_number, register_type) in offsets")
        return v

    @field_validator("pots")
    @classmethod
    def _unique_pot_numbers(cls, v: tuple[PotEntry, ...]) -> tuple[PotEntry, ...]:
        nums = [p.pot_number for p in v]
        if len(nums) != len(set(nums)):
            raise ValueError("duplicate pot_number in pots")
        return v
