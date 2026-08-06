"""FOCAS decoders + verified control bindings: pure functions and constants.

Split out of `shared/focas/client.py` (LOC cap) along the seam the module
always documented: this layer turns ctypes Structure outputs into Pydantic
models from `shared.focas.models` and owns every empirically-verified
constant (PMC addresses, offset type maps, increments). No DLL, no machine,
no I/O — tested with hand-built structs.

Everything here is re-exported by `shared.focas.client` so existing imports
keep resolving.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from .ctypes_defs import (
    IODBTD,
    IODBTLMAG,
    ODBALMMSG,
    ODBALMMSG2,
    ODBM,
    ODBST,
    ODBSYS,
    ODBTLINF,
    ODBTOFS,
)
from .models import (
    AlarmEntry,
    MachineMode,
    MachineStatus,
    OffsetRegister,
    PotEntry,
    RegisterType,
    ToolLife,
    ToolLifeStatus,
)

_logger = logging.getLogger("shared.focas.decoders")


# ============================================================================
# Constants — verified per-control bindings; see tasks/spec-focas-calls.md
# ============================================================================

# PMC R-area byte addresses for active-tool / next-tool on this 0i-MF +
# Mighty Viper random-ATC stack. Resolution path for O1: cnc_modal(-3, 1)
# returned 0 even with a tool loaded; cnc_rdtdiseltool returned EW_NOOPT;
# no FANUC system macro (#4xxx, #5xxx) carries the panel's HEAD value;
# the documented magazine-state functions (cnc_rdcurmgr / cnc_rdcurpot /
# cnc_rdpotinfo / cnc_rdmagsts / cnc_rdspmaint / cnc_rdmgrptool) are all
# absent from this DLL's exports. Random-ATC head/next is PMC-ladder
# data, not NC modal. probe_modal_v7 (snapshot/diff across a tool change)
# isolated 4 changed bytes; v8/v9 confirmed R327=panel HEAD and R325=
# panel NEXT against the live operator panel. R321 is a fast-mutating
# scratch register the ladder uses while reading these — DO NOT bind it.
# ENCODING: these R-area bytes are RAW BINARY, NOT packed-BCD like the D-area
# pot table below. Panel-verified across tool numbers 25, 85 and 31 (v7 diff
# 25->85, v8 R327=85, v8/v9 R325=31) — all >9, so the raw read equalling the
# panel value refutes BCD (BCD would read 0x85=133, 0x31=49, 0x25=37). Read the
# byte verbatim; do NOT apply decode_pot_bcd here. The two PMC areas genuinely
# use different encodings on this ladder.
_PMC_R_HEAD_ADDR: int = 327  # R-area byte: tool currently in spindle (HEAD)
_PMC_R_NEXT_ADDR: int = 325  # R-area byte: tool to be called next (NEXT)
_PMC_AREA_R: int = 5  # `type_a` value for R-area
_PMC_DATA_BYTE: int = 0  # `type_d` value for byte read

# PMC D-area pot->tool table on this 0i-MF + Mighty Viper random-ATC stack.
# `cnc_rdmagazine` is EW_NOOPT here (option unlicensed), so the pot table is
# read from the PMC D-area, one byte per pot, BCD-encoded (tool T90 stored as
# byte 0x90=144, T33 as 0x33=51 — NOT raw). D104 = tool currently in the
# spindle; D105 = pot 1 ... D128 = pot 24 (pot N at D(104+N)). Discovered by
# the probe_pot_table snapshot/diff workflow and confirmed against the operator
# panel (pot1=T1, pot2=T90, pot3=T33; D104 flipped 0x30->0x50 on a T30->T50
# change). Like the R327/R325 head/next binding above, this is OEM-SPECIFIC to
# the Mighty Viper ladder, not a FANUC standard — v1 is Viper-only (Decision-4,
# Decision-5 defers AG100 to Phase 8). Phase-8 backlog: make the pot source
# (area / base addr / encoding) per-machine config when a second OEM onboards.
_PMC_AREA_D: int = 9  # `type_a` value for D-area (data table)
_PMC_D_POT_BASE: int = 105  # D-area byte for pot 1; pot N at D(104+N)
# (D104 = spindle tool; read in the occupancy model, todo item #3, not here.)

# FANUC custom-macro system variables the G31 skip cycle latches. The tool
# presetter runs a G31 touch; when the skip signal fires, the control latches
# the skip position into #5061 (X), #5062 (Y), #5063 (Z). A fresh change in
# these correlated with an H-geom offset change = presetter-verified write; an
# offset change with no skip = manual keypad edit (R11 trust signal). Read via
# cnc_rdmacro. NB: G31 is also the spindle probe's mechanism, so the skip alone
# only says "a G31 touch happened" — attribution scopes the rule to H_GEOM
# offset changes, which only the presetter writes (the probe writes work
# offsets / macro vars, never tool length registers). Verified live 2026-07-08:
# presetting offset #21 (0 -> 5.6883) coincided with #5061 -5.51->-4.01 and
# #5063 3.93->4.35. See tasks/lessons.md.
_SKIP_MACRO_VARS: tuple[int, ...] = (5061, 5062, 5063)
# `cnc_rdmacro` documented data-length arg (bytes). NOT sizeof(ODBM)=12 — the
# struct pads for c_int32 alignment; FANUC expects the unpadded 10.
_MACRO_DATA_LEN: int = 10
# `cnc_rdmacro` returns dec_val < 0 for a vacant (unset) macro variable.
_MACRO_VACANT: int = -1

# FOCAS offset type codes for `cnc_rdtofs` — dispatched per offset memory
# model reported by `cnc_rdtofsinfo.ofs_type`. The Phase 1 integration
# smoke against the Lance Viper resolved Open Question O2: the Viper
# reports ofs_type=2 (Memory Type B). Calling cnc_rdtofs with type=3 or
# type=4 on Memory B returns EW_ATTRIB (rc=4) for every register.

# Memory Type A — single offset value per register (length only, no
# diameter, no wear separation). Smallest control footprint.
_OFFSET_TYPE_MAP_MEMORY_A: dict[int, RegisterType] = {
    1: RegisterType.H_GEOM,  # tool length offset (only value)
}

# Memory Type B — `cnc_rdtofsinfo` reports `ofs_type=2` on the Lance
# Viper. Standard FANUC docs document this as "length geom + length wear"
# with type=1=H_GEOM, type=2=H_WEAR and no diameter banks.
#
# Phase 1 panel cross-check on the actual Viper REVEALED a different
# layout. The control presents 4 panel columns (GEOM H, WEAR H, GEOM D,
# WEAR D) and the FOCAS type-code semantics are a NON-STANDARD
# PERMUTATION of the documented codes — including D_WEAR living at
# type=0, which no doc mentions and early probes (sweeping 1..4 only)
# missed entirely; type=4 legitimately rejects (EW_ATTRIB):
#
#   register 396 panel       FOCAS read
#   --------------------     ----------------------------
#   GEOM (H) = 3.0000 mm     type=3 raw=30000   ✓
#   WEAR (H) = 1.7500 mm     type=2 raw=17500   ✓
#   GEOM (D) = -0.3000 mm    type=1 raw=-3000   ✓
#   WEAR (D) = 2.0000 mm     type=0 raw=20000   ✓ (2026-07-15 sweep;
#                            type=4 rejects EW_ATTRIB — wrong code, not
#                            a missing bank. See lessons.md RETRACTION.)
#
# Verified mapping for this control (full 400x4 read: ZERO rejects,
# reports/viper-lg1000ap-4bank-20260715.json):
#   type=0  ->  D_WEAR   (undocumented code; register 396 matched the
#                         original panel cross-check value exactly)
#   type=1  ->  D_GEOM   (NOT H_GEOM as the FANUC docs imply)
#   type=2  ->  H_WEAR
#   type=3  ->  H_GEOM   (NOT D_GEOM as the FANUC docs imply)
_OFFSET_TYPE_MAP_MEMORY_B: dict[int, RegisterType] = {
    0: RegisterType.D_WEAR,  # CONFIRMED: panel "WEAR (D)" — brother 07-15
    #                          (regs 10/20), dbc00per 07-28 (regs 40/396)
    1: RegisterType.D_GEOM,  # CONFIRMED: matches panel "GEOM (D)"
    2: RegisterType.H_WEAR,  # CONFIRMED: matches panel "WEAR (H)"
    3: RegisterType.H_GEOM,  # CONFIRMED: matches panel "GEOM (H)"
}

# Memory Type C — full four-bank layout (length geom + length wear +
# diameter geom + diameter wear). Largest, most flexible. Not in use on
# the Lance Viper but supported here for future controls.
_OFFSET_TYPE_MAP_MEMORY_C: dict[int, RegisterType] = {
    1: RegisterType.H_GEOM,
    2: RegisterType.H_WEAR,
    3: RegisterType.D_GEOM,
    4: RegisterType.D_WEAR,
}

_OFS_TYPE_DISPATCH: dict[int, dict[int, RegisterType]] = {
    1: _OFFSET_TYPE_MAP_MEMORY_A,
    2: _OFFSET_TYPE_MAP_MEMORY_B,
    3: _OFFSET_TYPE_MAP_MEMORY_C,
}

# FANUC offset increment for raw long → mm conversion. Open question O8
# RESOLVED via Phase 1 smoke + panel cross-check on the Lance Viper:
#   panel  H50 = 7.4050 mm
#   panel  D50 = 0.2360 mm
#   FOCAS  type=3 raw = 74050  -> matches H50 at 0.0001 mm/count
#   FOCAS  type=1 raw = 2360   -> matches D50 at 0.0001 mm/count
# NOT the FANUC standard 0.001 mm we initially assumed. A 10x scaling
# error would have corrupted every offset read in the audit log.
#
# Phase 2 hardening: read FANUC parameter 1013 at startup via
# `cnc_rdparam` (not yet bound) to verify this empirical increment
# matches the control's runtime configuration; refuse to start the
# poller if they disagree.
DEFAULT_OFFSET_INCREMENT: Decimal = Decimal("0.0001")

# `cnc_rdalmmsg2` "all alarms" type selector per FOCAS docs.
_ALARM_TYPE_ALL: int = -1

# `cnc_rdngrp` returns 0 if tool life management is disabled or empty.
_NO_TOOL_LIFE: int = 0


# ============================================================================
# Decoders — pure functions, ctypes Structure -> Pydantic model
# ============================================================================


def _decode_ascii_field(buf: bytes) -> str:
    """Decode a fixed-size FANUC char[] field, stripping NUL/space padding
    on BOTH ends.

    FANUC right-justifies single-digit-major-version values: e.g., a 0i-MF
    control reports `cnc_type` as ` 0` (space + '0') in a `char[2]` field,
    not `0i`. Both leading and trailing whitespace must be stripped before
    comparing to expected identity values.
    """
    return buf.strip(b"\x00 ").decode("ascii", errors="replace")


def decode_sysinfo(odbsys: ODBSYS) -> dict[str, str | int]:
    """Decode `cnc_sysinfo` response. Used at startup for R9 detection —
    refuse to start the poller if cnc_type / mt_type / series don't match
    the expected 0i-MF Viper identity.
    """
    return {
        "addinfo": int(odbsys.addinfo),
        "max_axis": int(odbsys.max_axis),
        "cnc_type": _decode_ascii_field(bytes(odbsys.cnc_type)),
        "mt_type": _decode_ascii_field(bytes(odbsys.mt_type)),
        "series": _decode_ascii_field(bytes(odbsys.series)),
        "version": _decode_ascii_field(bytes(odbsys.version)),
        "axes": _decode_ascii_field(bytes(odbsys.axes)),
    }


# `ODBST.aut` -> selected automatic-side mode. Provisional mapping per the
# FOCAS2 developer manual conventions for FS30i-family controls. Verify on
# first Viper integration test; adjust here if any value differs. Unmapped
# values fall through to `MachineMode.UNKNOWN` so we never silently lie
# about state.
_AUT_TO_MODE: dict[int, MachineMode] = {
    0: MachineMode.MDI,
    1: MachineMode.MEM,
    # 2 = "***" (no-mode)
    3: MachineMode.EDIT,
    4: MachineMode.HND,
    5: MachineMode.JOG,
    # 6 = Teach in JOG
    # 7 = Teach in HND
    # 8 = INC
    9: MachineMode.REF,
    # 10 = RMT (remote / DNC)
}


def decode_status(odbst: ODBST) -> MachineStatus:
    """Decode `cnc_statinfo` response into our `MachineStatus` model.

    `aut` selects the mode (MDI/MEM/EDIT/HND/JOG/REF/...). `run` is the
    program-execution state: **0=****(reset/stopped), 1=STOP, 2=HOLD,
    3=STRT** — live-verified 2026-08-06 on a cutting JAKE_2100LY (run=3)
    after the ODBST layout fix (see the struct's docstring; the old code
    was reading the motion flag here). `running` is True for HOLD as well
    as STRT: a held program can resume at any moment, so for both the UI
    badge and the future write-lockout (R6) HOLD counts as running — the
    safe direction. When MEM mode is selected and the program is running,
    we expose the synthesized `MachineMode.AUTO` (the R6 signal).
    """
    aut = int(odbst.aut)
    run = int(odbst.run)
    mode = _AUT_TO_MODE.get(aut, MachineMode.UNKNOWN)
    is_program_running = run >= 2  # HOLD or STRT (see docstring)
    if mode is MachineMode.MEM and is_program_running:
        mode = MachineMode.AUTO
    if mode is MachineMode.UNKNOWN:
        _logger.warning("decode_status: unmapped ODBST.aut=%d run=%d", aut, run)
    return MachineStatus(
        mode=mode,
        running=is_program_running,
        # Header documents 0=not emergency / 1=emergency. No e-stop has been
        # observed through the FIXED layout yet — first chance a machine is
        # legitimately e-stopped, panel-verify this reads 1 (lessons.md).
        emergency_stop=bool(odbst.emergency),
        current_t_number=None,  # populated by caller from PMC R327
        next_t_number=None,  # populated by caller from PMC R325
    )


def decode_offset_layout(odbtlinf: ODBTLINF) -> tuple[int, int]:
    """Decode `cnc_rdtofsinfo`. Returns `(ofs_type, use_no)`.

    Used once at startup to determine which IODBTO union variant the
    control uses (Open question O2) and how many offset registers are
    actually populated.
    """
    return int(odbtlinf.ofs_type), int(odbtlinf.use_no)


def decode_offset(
    odbtofs: ODBTOFS,
    register_type: RegisterType,
    increment: Decimal = DEFAULT_OFFSET_INCREMENT,
) -> OffsetRegister:
    """Decode a single `cnc_rdtofs` response into an `OffsetRegister`.

    `data` is a raw FANUC long counted in units of `increment` (default
    0.001 mm). Conversion to mm happens here at the FOCAS boundary, never
    in business logic — per CLAUDE.md offset-math rule.
    """
    raw = int(odbtofs.data)
    value_mm = (Decimal(raw) * increment).quantize(Decimal("0.0001"))
    return OffsetRegister(
        register_number=int(odbtofs.datano),
        register_type=register_type,
        value_mm=value_mm,
    )


def decode_pot(iodbtlmag: IODBTLMAG) -> PotEntry:
    """Decode one `cnc_rdmagazine` record. `tool_index <= 0` is treated as
    an empty pot (Open question O5 — confirm sentinel value on first read)."""
    pot_number = int(iodbtlmag.pot)
    tool_index = int(iodbtlmag.tool_index)
    return PotEntry(
        pot_number=pot_number,
        t_number=tool_index if tool_index > 0 else None,
    )


def decode_pot_bcd(raw: int) -> int | None:
    """Decode one packed-BCD pot byte from the Viper's PMC D-area into a
    tool number.

    The Mighty Viper ladder stores pot tool numbers as packed BCD: byte
    `0x90` = T90, `0x33` = T33 (each nibble is a decimal digit, 0..99 in one
    byte). Returns the tool number, or `None` for an empty/no-identity pot.

      - `0x00` -> None (no tool identity in the cell).
      - a byte whose high or low nibble exceeds 9 is not valid packed BCD
        (`0xAB`, etc.) -> None; the caller logs it distinctly from a real 0x00.

    This yields IDENTITY only (which T# nominally lives in the pot). Pot cells
    are sticky — a normally-unloaded pot retains its last tool number, and a
    reset reinitialises every pot to its ordinal (pot N -> BCD N). PRESENCE is
    the offset table's job (non-zero geom offset = a measured tool is really
    there), correlated in the app layer — see `tasks/lessons.md` and todo #3.
    """
    hi, lo = (raw >> 4) & 0x0F, raw & 0x0F
    if hi > 9 or lo > 9:
        return None  # not valid packed BCD
    tool = hi * 10 + lo
    return tool if tool > 0 else None


def decode_macro(odbm: ODBM) -> Decimal | None:
    """Decode one `cnc_rdmacro` response into a real value, or `None` if the
    variable is vacant.

    FANUC encodes a macro value as an integer mantissa `mcr_val` and a decimal
    exponent `dec_val`: `value = mcr_val / 10**dec_val`. `dec_val < 0` signals a
    vacant variable (no value set) — returned as `None` so callers never mistake
    "unset" for a real 0. Exact `Decimal` math (no float) to preserve the offset
    domain's 0.0001 mm precision."""
    dec_val = int(odbm.dec_val)
    if dec_val < 0:
        return None
    return Decimal(int(odbm.mcr_val)) / (Decimal(10) ** dec_val)


def decode_tool_life(iodbtd: IODBTD) -> ToolLife:
    """Decode one `cnc_rd1tlifedata` response. Status interpretation depends
    on `tool_inf` bits (Open question O6); for now we expose status=None
    until the bit layout is verified against the FOCAS2 manual."""
    return ToolLife(
        t_number=int(iodbtd.tool_num),
        life_count=None,  # IODBTD doesn't expose count directly; needs cnc_rdcount
        life_max=None,
        status=ToolLifeStatus.LIVE,  # provisional until O6 resolved
    )


def decode_alarm(odbalm: ODBALMMSG2 | ODBALMMSG) -> AlarmEntry:
    """Decode one `cnc_rdalmmsg` / `cnc_rdalmmsg2` record.

    Accepts either the 32-char or 64-char message variant — the field
    names match across both structs.
    """
    msg_bytes = bytes(odbalm.alm_msg)
    msg_len = int(odbalm.msg_len)
    msg = msg_bytes[:msg_len].rstrip(b"\x00 ").decode("ascii", errors="replace")
    return AlarmEntry(
        code=int(odbalm.alm_no),
        axis=int(odbalm.axis) if odbalm.axis > 0 else None,
        message=msg,
    )


__all__ = [
    "DEFAULT_OFFSET_INCREMENT",
    "decode_alarm",
    "decode_macro",
    "decode_offset",
    "decode_offset_layout",
    "decode_pot",
    "decode_pot_bcd",
    "decode_status",
    "decode_sysinfo",
    "decode_tool_life",
]
