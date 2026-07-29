"""Unit tests for the lathe (0i-TF) read profile — shared/focas/lathe.py.

Uses the same _FakeLib stub as the client tests. The contract under test:
seven panel-locked banks (t0-t6), NEVER t7 (dup tip view — would collide on
the (register, 'tip') mirror key), NEVER any PMC read (R20/R22: the mill
HEAD/NEXT/pot addresses are foreign bytes on a lathe ladder).
"""

from __future__ import annotations

from decimal import Decimal

from shared.focas.ctypes_defs import ODBST, ODBTLINF, ODBTOFS
from shared.focas.lathe import (
    _IODBZOFS,
    LatheSnapshotSource,
    read_offsets_lathe,
    read_work_offsets_lathe,
)
from shared.focas.models import MachineMode, RegisterType, WorkOffsetSlot
from tests.shared.focas.test_client import _FakeLib, _make_client

_EXPECTED_BANKS = {
    0: RegisterType.X_WEAR,
    1: RegisterType.X_GEOM,
    2: RegisterType.Z_WEAR,
    3: RegisterType.Z_GEOM,
    4: RegisterType.R_WEAR,
    5: RegisterType.R_GEOM,
    6: RegisterType.TIP,
}


def _lathe_lib(use_no: int = 2) -> _FakeLib:
    lib = _FakeLib()
    layout = ODBTLINF()
    layout.ofs_type = 1  # what the VT_23 reports
    layout.use_no = use_no
    lib.responses["cnc_rdtofsinfo"] = layout
    for num in range(1, use_no + 1):
        for code in _EXPECTED_BANKS:
            t = ODBTOFS()
            t.datano = num
            t.data = num * 1000 + code
            lib.responses[f"cnc_rdtofs:{num}:{code}"] = t
    return lib


class TestReadOffsetsLathe:
    def test_reads_seven_banks_per_register(self):
        lib = _lathe_lib(use_no=2)
        offsets = read_offsets_lathe(_make_client(lib))
        assert len(offsets) == 2 * 7
        assert {o.register_type for o in offsets} == set(_EXPECTED_BANKS.values())

    def test_never_asks_for_type7_or_beyond(self):
        # t7 duplicates the tip view; reading it would collide on the
        # (register_number, 'tip') mirror key. t8+ reject on the control.
        lib = _lathe_lib(use_no=1)
        read_offsets_lathe(_make_client(lib))
        asked = {
            int(args[2].value)
            for name, args in lib.calls
            if name == "cnc_rdtofs"
        }
        assert asked == set(range(0, 7)), f"asked type codes {sorted(asked)}"

    def test_values_scaled_by_increment_except_tip(self):
        lib = _lathe_lib(use_no=1)
        offsets = read_offsets_lathe(_make_client(lib))
        x_geom = next(o for o in offsets if o.register_type is RegisterType.X_GEOM)
        # raw 1001 counts at the 0.0001 default increment
        assert x_geom.value_mm == Decimal("0.1001")
        # Tip is an integer CODE, never increment-scaled (raw 1006 stays 1006).
        tip = next(o for o in offsets if o.register_type is RegisterType.TIP)
        assert tip.value_mm == Decimal("1006")

    def test_reject_skips_cell_not_sweep(self):
        lib = _lathe_lib(use_no=2)
        lib.return_codes["cnc_rdtofs"] = 0  # default ok; poison one call path
        # Remove one canned response so datano=0 -> skipped
        del lib.responses["cnc_rdtofs:2:5"]
        offsets = read_offsets_lathe(_make_client(lib))
        assert len(offsets) == 2 * 7 - 1


class TestReadWorkOffsetsLathe:
    def test_reads_zofs_slots_and_workshift(self):
        lib = _lathe_lib(use_no=1)
        g55 = _IODBZOFS()
        g55.datano = 2
        g55.data[0] = 0
        g55.data[1] = 62660  # Z = 6.2660 — the live panel value
        lib.responses["cnc_rdzofs:2"] = g55
        ws = _IODBZOFS()
        ws.data[0] = 158365  # X = 15.8365
        ws.data[1] = 195044  # Z = 19.5044 — the live panel value
        lib.responses["cnc_rdwkcdshft"] = ws

        entries = read_work_offsets_lathe(_make_client(lib))

        by_key = {(e.slot, e.axis): e.value for e in entries}
        assert str(by_key[(WorkOffsetSlot.G55, "z")]) == "6.2660"
        assert str(by_key[(WorkOffsetSlot.WORK_SHIFT, "z")]) == "19.5044"
        assert str(by_key[(WorkOffsetSlot.WORK_SHIFT, "x")]) == "15.8365"
        # 7 zofs slots + work_shift, x+z each
        assert len(entries) == 8 * 2

    def test_full_block_length_always_passed(self):
        # The VT rejects anything short of the full 4+4*32 block (rc=2) —
        # lock the length arg so a "helpful" trim can't regress it.
        lib = _lathe_lib(use_no=1)
        read_work_offsets_lathe(_make_client(lib))
        lengths = {
            int(args[3].value) if hasattr(args[3], "value") else int(args[3])
            for name, args in lib.calls
            if name == "cnc_rdzofs"
        } | {
            int(args[2].value) if hasattr(args[2], "value") else int(args[2])
            for name, args in lib.calls
            if name == "cnc_rdwkcdshft"
        }
        assert lengths == {132}


class TestLatheSnapshotSource:
    def test_snapshot_is_offsets_and_status_only_no_pmc(self):
        lib = _lathe_lib(use_no=1)
        st = ODBST()
        st.aut = 0  # MDI
        lib.responses["cnc_statinfo"] = st
        source = LatheSnapshotSource(_make_client(lib, machine_id="viper-vt-23"))

        snap = source.read_snapshot()

        assert snap.machine_id == "viper-vt-23"
        assert snap.status.mode is MachineMode.MDI
        # No PMC head/next fabrication on a lathe (R22): stays None.
        assert snap.status.current_t_number is None
        assert snap.status.next_t_number is None
        assert len(snap.offsets) == 7
        assert len(snap.work_offsets) == 8 * 2  # zofs slots + work_shift, x+z
        assert snap.pots == ()
        assert snap.macros == ()
        assert snap.tool_life == ()
        # The R20/R22 hard assertion: not a single PMC read was issued.
        assert not any(name == "pmc_rdpmcrng" for name, _ in lib.calls)

    def test_close_delegates(self):
        lib = _lathe_lib(use_no=1)
        source = LatheSnapshotSource(_make_client(lib, machine_id="viper-vt-23"))
        source.close()
        assert any(name == "cnc_freelibhndl" for name, _ in lib.calls)
