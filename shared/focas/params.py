"""FANUC NC-parameter reads (`cnc_rdparam`) — unit / increment verification.

Read-only. Binds the one parameter surface the unit gate needs (docs/10 §7
stage 7, `tasks/spec-offset-units.md`):

  * parameter **1013** (per-axis increment-system bits ISA/ISC/ISD/ISE) —
    which IS system each axis runs (all bits 0 = IS-B);
  * setting **0000 bit 2 (INI)** via `cnc_rdset` — inch (1) or metric (0)
    INPUT unit. This is the unit offsets are stored/displayed in — what
    G20/G21 selects;
  * parameter **1001 bit 0 (INM)** — the MACHINE (command) system. Reported
    for the record only: fleet verification 2026-08-05 found all six
    controls are metric-machine (INM=0) while the whole shop runs inch
    input — INM does NOT drive offset units and must never be used for
    them.

INI + 1013 determine the offset increment per count, replacing the assumed
`DEFAULT_OFFSET_INCREMENT` with a value read from the control.
This module only *reads and reports*; wiring a refuse-on-mismatch gate into
`FocasClient.connect()` belongs to spec-offset-units slice 3 (needs the
`shared.machine.offset_unit` column) and is deliberately not done here.

Struct note: `IODBPSD` is declared locally (same idiom as the lathe
profile's work-offset structs) with the REALPRM union arms omitted — byte
parameters never use them, and the 132-byte cdatas/idatas/ldatas union is
ample for every `length` this module passes.

Length note (two prior traps, both in lessons.md): FOCAS `length` args are
documented values, not `ctypes.sizeof`. For `cnc_rdparam` the documented
shape is 4 (datano+type header) + data-size x axis-count: 4+1 for a
no-axis byte parameter, 4+`_MAX_AXIS` when reading a byte parameter for
all axes (axis = -1).
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .errors import raise_for_code

if TYPE_CHECKING:
    from .client import FocasClient

PARAM_INCREMENT_SYSTEM = 1013  # per-axis bits: #0 ISA, #1 ISC, #2 ISD, #3 ISE
PARAM_MACHINE_SYSTEM = 1001  # bit 0 INM: 0 = metric machine, 1 = inch machine
SETTING_INPUT_UNIT = 0  # setting 0000 bit 2 INI: 0 = mm input, 1 = inch input

_ALL_AXES = -1
_MAX_AXIS = 32  # header MAX_AXIS; sizes the union arms and the all-axes read


class _PRMUNION(ctypes.Union):
    _fields_ = [
        ("cdata", ctypes.c_byte),
        ("idata", ctypes.c_short),
        ("ldata", ctypes.c_int32),
        ("cdatas", ctypes.c_byte * _MAX_AXIS),
        ("idatas", ctypes.c_short * _MAX_AXIS),
        ("ldatas", ctypes.c_int32 * _MAX_AXIS),
    ]


class _IODBPSD(ctypes.Structure):
    _fields_ = [
        ("datano", ctypes.c_short),
        ("type", ctypes.c_short),  # header names this field for the axis number
        ("u", _PRMUNION),
    ]


# Offset least-increment per count by IS system, keyed by INPUT unit (INI).
# FANUC IS-B is the fleet norm; the inch column is what the whole shop runs
# (dbc00per 2026-08-05: inch shop-wide, 1013 all-zero).
_INCREMENT: dict[bool, dict[str, Decimal]] = {
    True: {  # inch input
        "IS-A": Decimal("0.001"),
        "IS-B": Decimal("0.0001"),
        "IS-C": Decimal("0.00001"),
        "IS-D": Decimal("0.000001"),
        "IS-E": Decimal("0.0000001"),
    },
    False: {  # metric input
        "IS-A": Decimal("0.01"),
        "IS-B": Decimal("0.001"),
        "IS-C": Decimal("0.0001"),
        "IS-D": Decimal("0.00001"),
        "IS-E": Decimal("0.000001"),
    },
}


def decode_is_system(p1013_byte: int) -> str:
    """Map a parameter-1013 byte to its IS system name. All bits clear is
    IS-B (the FANUC default); ISA/ISC/ISD/ISE bits select the others."""
    if p1013_byte & 0x01:
        return "IS-A"
    if p1013_byte & 0x02:
        return "IS-C"
    if p1013_byte & 0x04:
        return "IS-D"
    if p1013_byte & 0x08:
        return "IS-E"
    return "IS-B"


def increment_for(is_system: str, inch_input: bool) -> Decimal:
    """Offset increment per count for an IS system + INPUT unit (INI)."""
    return _INCREMENT[inch_input][is_system]


@dataclass(frozen=True)
class IncrementSystem:
    """What the control says about its own units — never assumed."""

    inch_input: bool  # setting 0000#2 INI — the unit offsets live in
    inch_machine: bool  # parameter 1001#0 INM — informational only
    p1013_per_axis: tuple[int, ...]  # raw byte per configured axis
    is_system_per_axis: tuple[str, ...]
    increment: Decimal  # offset increment: INI + axis 1's IS system

    @property
    def uniform(self) -> bool:
        """True when every configured axis runs the same IS system."""
        return len(set(self.is_system_per_axis)) <= 1


def read_parameter_byte(client: FocasClient, number: int) -> int:
    """Read a no-axis byte parameter (`cnc_rdparam`, axis=0)."""
    buf = _IODBPSD()
    rc = client._lib.cnc_rdparam(
        client._handle,
        ctypes.c_short(number),
        ctypes.c_short(0),
        ctypes.c_short(4 + 1),
        ctypes.byref(buf),
    )
    raise_for_code(rc, context=f"cnc_rdparam({number})")
    return buf.u.cdata & 0xFF


def read_setting_byte(client: FocasClient, number: int) -> int:
    """Read a no-axis byte SETTING (`cnc_rdset`, axis=0) — settings 0000+
    live in their own datano space, not the parameter space."""
    buf = _IODBPSD()
    rc = client._lib.cnc_rdset(
        client._handle,
        ctypes.c_short(number),
        ctypes.c_short(0),
        ctypes.c_short(4 + 1),
        ctypes.byref(buf),
    )
    raise_for_code(rc, context=f"cnc_rdset({number})")
    return buf.u.cdata & 0xFF


def read_parameter_axis_bytes(client: FocasClient, number: int, axis_count: int) -> tuple[int, ...]:
    """Read a per-axis byte parameter for all axes (`cnc_rdparam`, axis=-1).
    Returns one byte per configured axis."""
    buf = _IODBPSD()
    rc = client._lib.cnc_rdparam(
        client._handle,
        ctypes.c_short(number),
        ctypes.c_short(_ALL_AXES),
        ctypes.c_short(4 + _MAX_AXIS),
        ctypes.byref(buf),
    )
    raise_for_code(rc, context=f"cnc_rdparam({number})")
    return tuple(buf.u.cdatas[i] & 0xFF for i in range(axis_count))


def read_increment_system(client: FocasClient, axis_count: int) -> IncrementSystem:
    """Read INI (setting 0000#2) + 1013 (+ INM for the record) and derive
    the offset increment. INI, not INM, selects the inch/metric column —
    offsets live in the INPUT unit.

    `axis_count` comes from sysinfo's `axes` field (the configured axis
    count) — bytes beyond it in the all-axes read are unconfigured-slot
    garbage and are not decoded.
    """
    inch_input = bool(read_setting_byte(client, SETTING_INPUT_UNIT) & 0x04)  # bit 2 INI
    inch_machine = bool(read_parameter_byte(client, PARAM_MACHINE_SYSTEM) & 0x01)
    p1013 = read_parameter_axis_bytes(client, PARAM_INCREMENT_SYSTEM, axis_count)
    systems = tuple(decode_is_system(b) for b in p1013)
    return IncrementSystem(
        inch_input=inch_input,
        inch_machine=inch_machine,
        p1013_per_axis=p1013,
        is_system_per_axis=systems,
        increment=increment_for(systems[0], inch_input),
    )


__all__ = [
    "PARAM_INCREMENT_SYSTEM",
    "PARAM_MACHINE_SYSTEM",
    "SETTING_INPUT_UNIT",
    "IncrementSystem",
    "decode_is_system",
    "increment_for",
    "read_increment_system",
    "read_parameter_axis_bytes",
    "read_parameter_byte",
    "read_setting_byte",
]
