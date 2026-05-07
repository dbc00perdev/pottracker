# ruff: noqa: N801, RUF012
#
# N801: struct class names mirror the C typedefs in `Fwlib64.h` verbatim
#       (ODBSYS / IODBTLMAG / etc.) so a reader can grep header -> Python.
#       Renaming to PascalCase would lose that traceability.
# RUF012: ctypes requires `_fields_` to be a plain class attribute. Wrapping
#       in `ClassVar[...]` breaks ctypes' attribute-installation machinery.
"""ctypes Structure / Union definitions for FOCAS responses.

Mirrors the typedefs in `tasks/spec-focas-calls.md` (verbatim from
`C:\\Fanuc\\FwLib64-runtime\\Fwlib64.h`). Layouts use natural alignment to
match the FANUC C compiler.

Conventions:
- FANUC `short` = 16-bit signed -> `ctypes.c_short`
- FANUC `long` = 32-bit signed -> `ctypes.c_int32`. Crucial: do NOT use
  `ctypes.c_long` — that maps to the platform's native long, which is 8
  bytes on Linux x86_64 vs 4 bytes on Windows. The DLL is MSVC-built and
  uses 32-bit `long`; a mismatch corrupts every offset, pot, and tool-life
  read on non-Windows dev hosts.
- FANUC `char` = 8-bit -> `ctypes.c_char` (kept as bytes; decode to str at
  the boundary in `client.py`)

Sizes are pinned by the tests in `tests/shared/focas/test_ctypes_defs.py`.
If any layout drifts, the tests fail loudly — the FOCAS DLL is untolerant
of mis-sized buffers and a silent layout change would corrupt reads.

This module is platform-agnostic: it defines memory shapes only and does
not load any DLL. DLL loading lives in `client.py`.
"""

from __future__ import annotations

import ctypes
from ctypes import (
    Structure,
    Union,
    c_byte,
    c_char,
    c_double,
    c_int32,
    c_short,
    c_ubyte,
    c_ushort,
)

# Header-defined max paths for the system info extended call. The 0i-MF on
# the Lance Viper is single-path (max_path == 1 in observed responses), but
# the C `path[]` array in ODBSYSEX is sized statically by the header. 10 is
# the documented FANUC default and is what the SDK builds expect; an oversized
# buffer is harmless because FOCAS only writes the populated entries.
# TODO: confirm `MAX_CNCPATH` value from `Fwlib64.h` via a future extractor
# pass over `#define` lines.
MAX_CNCPATH: int = 10


# ============================================================================
# Section 2: System info
# ============================================================================


class ODBSYS(Structure):
    """`cnc_sysinfo` response. Per-control identity check at startup."""

    _fields_ = [
        ("addinfo", c_short),
        ("max_axis", c_short),
        ("cnc_type", c_char * 2),
        ("mt_type", c_char * 2),
        ("series", c_char * 4),
        ("version", c_char * 4),
        ("axes", c_char * 2),
    ]


class _ODBSYSEX_PATH(Structure):
    _fields_ = [
        ("system", c_short),
        ("group", c_short),
        ("attrib", c_short),
        ("ctrl_axis", c_short),
        ("ctrl_srvo", c_short),
        ("ctrl_spdl", c_short),
        ("mchn_no", c_short),
        ("reserved", c_short),
    ]


class ODBSYSEX(Structure):
    """`cnc_sysinfo_ex` response. Optional supplemental sysinfo."""

    _fields_ = [
        ("max_axis", c_short),
        ("max_spdl", c_short),
        ("max_path", c_short),
        ("max_mchn", c_short),
        ("ctrl_axis", c_short),
        ("ctrl_srvo", c_short),
        ("ctrl_spdl", c_short),
        ("ctrl_path", c_short),
        ("ctrl_mchn", c_short),
        ("addinfo", c_short),
        ("reserved", c_short * 2),
        ("path", _ODBSYSEX_PATH * MAX_CNCPATH),
    ]


# ============================================================================
# Section 3: Machine status
# ============================================================================


class ODBST(Structure):
    """`cnc_statinfo` response. Canonical machine status read every cycle.

    `aut`, `run`, `emergency`, `alarm` map to our `MachineStatus` Pydantic
    model in `client.py`. Mode lockout (R6) reads this struct.
    """

    _fields_ = [
        ("dummy", c_short * 2),
        ("aut", c_short),
        ("manual", c_short),
        ("run", c_short),
        ("edit", c_short),
        ("motion", c_short),
        ("mstb", c_short),
        ("emergency", c_short),
        ("write", c_short),
        ("labelskip", c_short),
        ("alarm", c_short),
        ("warning", c_short),
        ("battery", c_short),
    ]


class ODBST2(Structure):
    """`cnc_statinfo2` response. Reserved for future TT/multi-mode controls."""

    _fields_ = [
        ("hdck", c_short),
        ("tmmode", c_short),
        ("aut", c_short),
        ("run", c_short),
        ("motion", c_short),
        ("mstb", c_short),
        ("emergency", c_short),
        ("alarm", c_short),
        ("edit", c_short),
        ("warning", c_short),
        ("o3dchk", c_short),
        ("ext_opt", c_short),
        ("restart", c_short),
    ]


# ============================================================================
# Section 4: Modal info (current T)
# ============================================================================


class _ODBMDL_AUX(Structure):
    """The `aux` and `raux1` member type inside the `cnc_modal` union."""

    _fields_ = [
        ("aux_data", c_int32),
        ("flag1", c_char),
        ("flag2", c_char),
    ]


class _ODBMDL_MODAL(Union):
    _fields_ = [
        ("g_data", c_char),
        ("g_rdata", c_char * 12),
        ("g_1shot", c_char),
        ("aux", _ODBMDL_AUX),
        ("raux1", _ODBMDL_AUX * 25),
    ]


class ODBMDL(Structure):
    """`cnc_modal` response. Current T number lives in `modal.aux.aux_data`."""

    _fields_ = [
        ("datano", c_short),
        ("type", c_short),
        ("modal", _ODBMDL_MODAL),
    ]


# ============================================================================
# Section 5: Tool offsets
# ============================================================================


class ODBTLINF(Structure):
    """`cnc_rdtofsinfo` response. `ofs_type` selects the IODBTO union variant.

    Decision-3 resolved at runtime by reading this struct once at startup.
    """

    _fields_ = [
        ("ofs_type", c_short),
        ("use_no", c_short),
    ]


class ODBTOFS(Structure):
    """`cnc_rdtofs` single-register response. `data` is raw integer at the
    control's offset increment (typically 0.001 mm); divide at the boundary."""

    _fields_ = [
        ("datano", c_short),
        ("type", c_short),
        ("data", c_int32),
    ]


# IODBTO union variants — every documented member is declared so the union
# is sized correctly regardless of which `ofs_type` the Viper reports at
# runtime. Unused members carry no runtime cost.


class _IODBTO_AT(Structure):
    """`m_ofs_at` element: M-A All with tip — short tip + long data[1]."""

    _fields_ = [("tip", c_short), ("data", c_int32 * 1)]


class _IODBTO_BT(Structure):
    """`m_ofs_bt` element: short tip + long data[2]."""

    _fields_ = [("tip", c_short), ("data", c_int32 * 2)]


class _IODBTO_CT(Structure):
    """`m_ofs_ct` element: short tip + long data[4]."""

    _fields_ = [("tip", c_short), ("data", c_int32 * 4)]


class _IODBTO_T_A(Structure):
    """`t_ofs_a` element: short tip + long data[4]."""

    _fields_ = [("tip", c_short), ("data", c_int32 * 4)]


class _IODBTO_T_B(Structure):
    """`t_ofs_b` element: short tip + long data[8] — largest variant."""

    _fields_ = [("tip", c_short), ("data", c_int32 * 8)]


class _IODBTO_T_EX(Structure):
    """`t_ofs_ex` element: long data[2]."""

    _fields_ = [("data", c_int32 * 2)]


class _IODBTO_UNION(Union):
    _fields_ = [
        ("m_ofs", c_int32 * 5),
        ("m_ofs_a", c_int32 * 5),
        ("m_ofs_b", c_int32 * 10),
        ("m_ofs_c", c_int32 * 20),
        ("m_ofs_at", _IODBTO_AT * 5),
        ("m_ofs_bt", _IODBTO_BT * 5),
        ("m_ofs_ct", _IODBTO_CT * 5),
        ("t_tip", c_short * 5),
        ("t_ofs", c_int32 * 5),
        ("t_ofs_a", _IODBTO_T_A * 5),
        ("t_ofs_b", _IODBTO_T_B * 5),
        ("t_ofs_2g", c_int32 * 15),
        ("m_ofs_cnr", c_int32 * 10),
        ("t_ofs_ex", _IODBTO_T_EX * 5),
    ]


class IODBTO(Structure):
    """`cnc_rdtofsr` range-read response. The active union member is
    determined by the `type` arg passed to the call and the control's
    `ofs_type` from `cnc_rdtofsinfo`."""

    _fields_ = [
        ("datano_s", c_short),
        ("type", c_short),
        ("datano_e", c_short),
        ("u", _IODBTO_UNION),
    ]


# ============================================================================
# Section 6: Magazine / pot table
# ============================================================================


class IODBTLMAG(Structure):
    """`cnc_rdmagazine` element. One per pot record."""

    _fields_ = [
        ("magazine", c_short),
        ("pot", c_short),
        ("tool_index", c_short),
    ]


# ============================================================================
# Section 7: Tool life management
# ============================================================================


class ODBTLIFE2(Structure):
    """`cnc_rdngrp` response. `data` = number of tool life groups defined."""

    _fields_ = [
        ("dummy", c_short * 2),
        ("data", c_int32),
    ]


class ODBTLIFE1(Structure):
    """`cnc_rdgrpid` response. `data` = group ID at requested index."""

    _fields_ = [
        ("dummy", c_short),
        ("type", c_short),
        ("data", c_int32),
    ]


class ODBTLIFE5(Structure):
    """`cnc_rdgrpid2` response. `long`-indexed variant of ODBTLIFE1."""

    _fields_ = [
        ("dummy", c_int32),
        ("type", c_int32),
        ("data", c_int32),
    ]


class ODBUSEGR(Structure):
    """`cnc_rdusegrpid` response. `next` / `use` / `slct` group numbers."""

    _fields_ = [
        ("datano", c_short),
        ("type", c_short),
        ("next", c_int32),
        ("use", c_int32),
        ("slct", c_int32),
    ]


class IODBTD(Structure):
    """`cnc_rd1tlifedata` response. `tool_num` = T#, `h_code`/`d_code` =
    register numbers (NOT values). Wires our `tooling.assignment` model."""

    _fields_ = [
        ("datano", c_short),
        ("type", c_short),
        ("tool_num", c_int32),
        ("h_code", c_int32),
        ("d_code", c_int32),
        ("tool_inf", c_int32),
    ]


# ============================================================================
# Section 8: Alarms
# ============================================================================


class ODBALMMSG(Structure):
    """`cnc_rdalmmsg` response. 32-char message — fallback only.

    Prefer ODBALMMSG2 (64 chars) when supported.
    """

    _fields_ = [
        ("alm_no", c_int32),
        ("type", c_short),
        ("axis", c_short),
        ("dummy", c_short),
        ("msg_len", c_short),
        ("alm_msg", c_char * 32),
    ]


class ODBALMMSG2(Structure):
    """`cnc_rdalmmsg2` response. 64-char message — preferred."""

    _fields_ = [
        ("alm_no", c_int32),
        ("type", c_short),
        ("axis", c_short),
        ("dummy", c_short),
        ("msg_len", c_short),
        ("alm_msg", c_char * 64),
    ]


class _IODBPMC_UNION(Union):
    # Match Fwlib64.h variant set including `dfdata` so the union sizes to
    # 40 bytes (5 * sizeof(double)). Omitting the double variant would
    # under-size the struct and the DLL would reject the buffer.
    # `cdata` declared as `c_ubyte` (vs the header's plain `char`): PMC
    # bytes carry small unsigned integers (tool IDs 0..99, status bit
    # patterns) and we don't want signedness ambiguity at read time.
    _fields_ = [
        ("cdata", c_ubyte * 5),
        ("idata", c_short * 5),
        ("ldata", c_int32 * 5),
        ("dfdata", c_double * 5),
    ]


class IODBPMC(Structure):
    """`pmc_rdpmcrng` request/response. Reads up to 5 elements from a PMC
    address range; element type selected by the `type_d` arg to
    `pmc_rdpmcrng` (0=byte, 1=word, 2=long-word). Total size 48 bytes
    (8-byte header + 40-byte union)."""

    _fields_ = [
        ("type_a", c_short),
        ("type_d", c_short),
        ("datano_s", c_ushort),
        ("datano_e", c_ushort),
        ("u", _IODBPMC_UNION),
    ]


# ============================================================================
# Public size table (also asserted by tests).
#
# Used by `client.py` to compute the `length` argument for FOCAS calls that
# require a buffer length — FANUC functions size-check the caller's buffer
# against an internal expected size for the given `type`/`ofs_type`.
# ============================================================================

SIZEOF: dict[type, int] = {
    ODBSYS: ctypes.sizeof(ODBSYS),
    ODBSYSEX: ctypes.sizeof(ODBSYSEX),
    ODBST: ctypes.sizeof(ODBST),
    ODBST2: ctypes.sizeof(ODBST2),
    ODBMDL: ctypes.sizeof(ODBMDL),
    ODBTLINF: ctypes.sizeof(ODBTLINF),
    ODBTOFS: ctypes.sizeof(ODBTOFS),
    IODBTO: ctypes.sizeof(IODBTO),
    IODBTLMAG: ctypes.sizeof(IODBTLMAG),
    ODBTLIFE2: ctypes.sizeof(ODBTLIFE2),
    ODBTLIFE1: ctypes.sizeof(ODBTLIFE1),
    ODBTLIFE5: ctypes.sizeof(ODBTLIFE5),
    ODBUSEGR: ctypes.sizeof(ODBUSEGR),
    IODBTD: ctypes.sizeof(IODBTD),
    ODBALMMSG: ctypes.sizeof(ODBALMMSG),
    ODBALMMSG2: ctypes.sizeof(ODBALMMSG2),
    IODBPMC: ctypes.sizeof(IODBPMC),
}


__all__ = [
    "IODBPMC",
    "IODBTD",
    "IODBTLMAG",
    "IODBTO",
    "MAX_CNCPATH",
    "ODBALMMSG",
    "ODBALMMSG2",
    "ODBMDL",
    "ODBST",
    "ODBST2",
    "ODBSYS",
    "ODBSYSEX",
    "ODBTLIFE1",
    "ODBTLIFE2",
    "ODBTLIFE5",
    "ODBTLINF",
    "ODBTOFS",
    "ODBUSEGR",
    "SIZEOF",
    # Re-exports for convenience — needed because c_byte is referenced
    # by callers that allocate raw buffers around these structs.
    "c_byte",
]
