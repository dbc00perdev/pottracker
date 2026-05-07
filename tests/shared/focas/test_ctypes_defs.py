"""Tests for shared.focas.ctypes_defs.

These tests pin every FOCAS struct's byte size to the value derived from the
verbatim header layout in `tasks/spec-focas-calls.md`. The FOCAS DLL is
intolerant of mis-sized buffers — a struct whose Python ctypes layout drifts
from the C header would silently corrupt every read or write.

If a test in here fails, do NOT change the expected size; fix the struct
definition. The expected values were computed by hand from the verbatim
typedefs in `Fwlib64.h` and assume:
  - `short`  = 2 bytes
  - `long`   = 4 bytes (FANUC C convention; matches MSVC, NOT Linux native)
  - natural alignment, no `#pragma pack`
  - `MAX_CNCPATH = 10` (header default; verify in a future extractor pass)
"""

from __future__ import annotations

import ctypes

import pytest

from shared.focas.ctypes_defs import (
    IODBTD,
    IODBTLMAG,
    IODBTO,
    MAX_CNCPATH,
    ODBALMMSG,
    ODBALMMSG2,
    ODBMDL,
    ODBST,
    ODBST2,
    ODBSYS,
    ODBSYSEX,
    ODBTLIFE1,
    ODBTLIFE2,
    ODBTLIFE5,
    ODBTLINF,
    ODBTOFS,
    ODBUSEGR,
    SIZEOF,
)

EXPECTED_SIZES: dict[type, int] = {
    # Section 2 — system info
    ODBSYS: 18,
    ODBSYSEX: 184,  # depends on MAX_CNCPATH
    # Section 3 — status
    ODBST: 28,  # 2-element dummy[2] + 12 individual shorts = 14 shorts
    ODBST2: 26,
    # Section 4 — modal
    ODBMDL: 204,  # 4 (datano+type) + 200 (raux1[25] of {long+char+char} -> 8)
    # Section 5 — offsets
    ODBTLINF: 4,
    ODBTOFS: 8,
    IODBTO: 188,  # 8 (header+pad) + 180 (largest variant: t_ofs_b[5])
    # Section 6 — magazine
    IODBTLMAG: 6,
    # Section 7 — tool life
    ODBTLIFE2: 8,
    ODBTLIFE1: 8,
    ODBTLIFE5: 12,
    ODBUSEGR: 16,
    IODBTD: 20,
    # Section 8 — alarms
    ODBALMMSG: 44,
    ODBALMMSG2: 76,
}


class TestStructSizes:
    @pytest.mark.parametrize(
        "cls,expected", list(EXPECTED_SIZES.items()), ids=lambda v: getattr(v, "__name__", str(v))
    )
    def test_size(self, cls, expected):
        actual = ctypes.sizeof(cls)
        assert actual == expected, (
            f"{cls.__name__} sizeof = {actual}, expected {expected}. "
            "Layout drifted from the verbatim header in tasks/spec-focas-calls.md."
        )

    def test_sizeof_table_matches_actual(self):
        """`SIZEOF` is exposed for callers that need buffer lengths; ensure
        it stays consistent with the live ctypes sizes."""
        for cls, recorded in SIZEOF.items():
            assert recorded == ctypes.sizeof(cls), (
                f"SIZEOF[{cls.__name__}] = {recorded} but live sizeof = {ctypes.sizeof(cls)}"
            )


class TestLongIs32Bit:
    """The DLL is MSVC-built; its `long` is 32-bit. If we accidentally use
    `c_long` (which is 8 bytes on Linux x86_64), every offset/pot/tool-life
    read corrupts. This test guards against that regression by spot-checking
    structs with FANUC `long` fields."""

    def test_odbtofs_data_is_4_bytes(self):
        # ODBTOFS = short(2) + short(2) + long(4) = 8 bytes total.
        # If `long` were 8 bytes, sizeof would be 16.
        assert ctypes.sizeof(ODBTOFS) == 8

    def test_odbtlife5_three_longs_is_12_bytes(self):
        # ODBTLIFE5 is three `long` fields. With 32-bit longs: 12 bytes.
        # With 64-bit longs: 24 bytes.
        assert ctypes.sizeof(ODBTLIFE5) == 12


class TestFieldNamesPresent:
    """Cheap regression guard against accidental field renames or removals."""

    def test_odbst_has_aut_run_emergency_alarm(self):
        names = {name for name, _ in ODBST._fields_}
        assert {"aut", "run", "emergency", "alarm"} <= names

    def test_iodbtd_has_h_and_d_codes(self):
        names = {name for name, _ in IODBTD._fields_}
        assert {"tool_num", "h_code", "d_code", "tool_inf"} <= names

    def test_iodbtlmag_has_pot_and_tool_index(self):
        names = {name for name, _ in IODBTLMAG._fields_}
        assert {"magazine", "pot", "tool_index"} <= names


class TestIODBTOUnionMembers:
    """`IODBTO`'s union has many variants; we declare every documented one
    so the union is sized to the largest member regardless of which type
    code the Viper reports."""

    def test_m_variants_present(self):
        union_field = next(f for f in IODBTO._fields_ if f[0] == "u")
        union_cls = union_field[1]
        members = {name for name, _ in union_cls._fields_}
        for required in ("m_ofs", "m_ofs_a", "m_ofs_b", "m_ofs_c"):
            assert required in members, f"missing M variant: {required}"

    def test_t_variants_present(self):
        union_field = next(f for f in IODBTO._fields_ if f[0] == "u")
        union_cls = union_field[1]
        members = {name for name, _ in union_cls._fields_}
        for required in ("t_ofs", "t_ofs_a", "t_ofs_b", "t_ofs_2g"):
            assert required in members, f"missing T variant: {required}"


class TestMaxCncPath:
    def test_default_is_documented_fanuc_value(self):
        assert MAX_CNCPATH == 10
