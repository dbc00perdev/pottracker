"""Tests for shared.focas.client.

Two layers of tests:

  - Decoder tests: hand-build ctypes Structure instances with known field
    values, run the pure decoder function, assert the resulting Pydantic
    model. No DLL, no machine.

  - FocasClient orchestration tests: use a fake `lib` object exposing the
    same `cnc_*` callables the real DLL would; verify FocasClient calls
    them in the right order with the right ctypes arg shapes, and that it
    raises typed exceptions on nonzero return codes.

The DLL loader is exercised only on its error paths (Linux fallback,
missing dir, missing file). Loading a real Fwlib64.dll is a Windows-only
integration concern, not a unit-test concern.
"""

from __future__ import annotations

import ctypes
import sys
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from shared.focas.client import (
    DEFAULT_OFFSET_INCREMENT,
    FocasClient,
    _resolve_dll_dir,
    decode_alarm,
    decode_current_t,
    decode_offset,
    decode_offset_layout,
    decode_pot,
    decode_status,
    decode_sysinfo,
)
from shared.focas.ctypes_defs import (
    IODBTD,
    IODBTLMAG,
    ODBALMMSG2,
    ODBMDL,
    ODBST,
    ODBSYS,
    ODBTLIFE1,
    ODBTLIFE2,
    ODBTLINF,
    ODBTOFS,
    ODBUSEGR,
)
from shared.focas.errors import FocasConnectError, FocasError, FocasNoDllError
from shared.focas.models import (
    MachineMode,
    RegisterType,
)

# ============================================================================
# Decoder tests — synthetic ctypes structs in, Pydantic models out
# ============================================================================


class TestDecodeSysinfo:
    def test_basic_fields(self):
        s = ODBSYS()
        s.addinfo = 1
        s.max_axis = 3
        s.cnc_type = b"0i"
        s.mt_type = b"M\x00"
        s.series = b"D4F1"
        s.version = b"15.0"
        s.axes = b"3\x00"
        out = decode_sysinfo(s)
        assert out["cnc_type"] == "0i"
        assert out["mt_type"] == "M"
        assert out["series"] == "D4F1"
        assert out["version"] == "15.0"
        assert out["max_axis"] == 3
        assert out["axes"] == "3"


class TestDecodeStatus:
    def _odbst(self, *, aut: int = 1, run: int = 0, emergency: int = 0) -> ODBST:
        s = ODBST()
        s.aut = aut
        s.run = run
        s.emergency = emergency
        return s

    def test_mem_idle_is_mem(self):
        out = decode_status(self._odbst(aut=1, run=0))
        assert out.mode is MachineMode.MEM
        assert out.running is False
        assert out.emergency_stop is False

    def test_mem_running_is_auto(self):
        # MEM mode with run >= 2 (STaRT) is the AUTO-running synth state
        # the writer (Phase 6) will check for mode lockout (R6).
        out = decode_status(self._odbst(aut=1, run=2))
        assert out.mode is MachineMode.AUTO
        assert out.running is True

    def test_mem_hold_is_mem_with_running_false(self):
        # HOLD (run=1) — program loaded but not executing instructions.
        # We treat run < 2 as not "actively running" for write-lockout.
        out = decode_status(self._odbst(aut=1, run=1))
        assert out.mode is MachineMode.MEM
        assert out.running is False

    def test_mdi_mode(self):
        out = decode_status(self._odbst(aut=0))
        assert out.mode is MachineMode.MDI

    def test_emergency_stop_flagged(self):
        out = decode_status(self._odbst(aut=1, run=0, emergency=1))
        assert out.emergency_stop is True

    def test_unmapped_aut_falls_to_unknown(self):
        # 99 isn't a documented `aut` value; defensive fallback.
        out = decode_status(self._odbst(aut=99))
        assert out.mode is MachineMode.UNKNOWN

    def test_current_t_is_none_until_caller_sets_it(self):
        out = decode_status(self._odbst())
        assert out.current_t_number is None


class TestDecodeCurrentT:
    def test_positive_aux_data_returned(self):
        m = ODBMDL()
        m.modal.aux.aux_data = 42
        assert decode_current_t(m) == 42

    def test_zero_aux_data_is_none(self):
        m = ODBMDL()
        m.modal.aux.aux_data = 0
        assert decode_current_t(m) is None

    def test_negative_aux_data_is_none(self):
        # Defensive; FANUC shouldn't send negative T but don't propagate.
        m = ODBMDL()
        m.modal.aux.aux_data = -1
        assert decode_current_t(m) is None


class TestDecodeOffsetLayout:
    def test_returns_ofs_type_and_use_no(self):
        o = ODBTLINF()
        o.ofs_type = 5
        o.use_no = 200
        assert decode_offset_layout(o) == (5, 200)


class TestDecodeOffset:
    def test_default_increment_001mm(self):
        o = ODBTOFS()
        o.datano = 25
        o.data = 12345  # raw long, increment 0.001 mm
        out = decode_offset(o, RegisterType.H_GEOM)
        assert out.register_number == 25
        assert out.register_type is RegisterType.H_GEOM
        assert out.value_mm == Decimal("12.3450")

    def test_negative_offset(self):
        o = ODBTOFS()
        o.datano = 1
        o.data = -100250  # -100.250 mm at 0.001 mm increment
        out = decode_offset(o, RegisterType.H_GEOM)
        assert out.value_mm == Decimal("-100.2500")

    def test_alternate_increment_0001mm(self):
        o = ODBTOFS()
        o.datano = 1
        o.data = 12345  # 1.2345 mm at 0.0001 mm increment
        out = decode_offset(o, RegisterType.D_GEOM, increment=Decimal("0.0001"))
        assert out.value_mm == Decimal("1.2345")

    def test_default_increment_value_is_001(self):
        # Guard against silent regression of the default conversion factor.
        assert DEFAULT_OFFSET_INCREMENT == Decimal("0.001")


class TestDecodePot:
    def test_occupied_pot(self):
        m = IODBTLMAG()
        m.magazine = 1
        m.pot = 5
        m.tool_index = 7
        out = decode_pot(m)
        assert out.pot_number == 5
        assert out.t_number == 7

    def test_empty_pot_with_zero_tool_index(self):
        m = IODBTLMAG()
        m.magazine = 1
        m.pot = 5
        m.tool_index = 0
        out = decode_pot(m)
        assert out.t_number is None

    def test_empty_pot_with_negative_sentinel(self):
        # Some FANUC variants encode empty as -1; we treat <=0 as empty.
        m = IODBTLMAG()
        m.magazine = 1
        m.pot = 5
        m.tool_index = -1
        out = decode_pot(m)
        assert out.t_number is None


class TestDecodeAlarm:
    def test_basic(self):
        a = ODBALMMSG2()
        a.alm_no = 506
        a.axis = 1
        a.msg_len = 12
        a.alm_msg = b"Overtravel +"
        out = decode_alarm(a)
        assert out.code == 506
        assert out.axis == 1
        assert out.message == "Overtravel +"

    def test_zero_axis_becomes_none(self):
        a = ODBALMMSG2()
        a.alm_no = 100
        a.axis = 0
        a.msg_len = 4
        a.alm_msg = b"Hard"
        out = decode_alarm(a)
        assert out.axis is None

    def test_strips_padding(self):
        a = ODBALMMSG2()
        a.alm_no = 1
        a.axis = 0
        a.msg_len = 5
        a.alm_msg = b"Hello\x00\x00\x00"
        out = decode_alarm(a)
        assert out.message == "Hello"


# ============================================================================
# DLL loader error-path tests (Linux fallback)
# ============================================================================


class TestResolveDllDir:
    def test_explicit_arg_wins(self, tmp_path):
        out = _resolve_dll_dir(tmp_path)
        assert out == tmp_path

    def test_env_var_used_when_no_arg(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOCAS_DLL_DIR", str(tmp_path))
        out = _resolve_dll_dir(None)
        assert out == tmp_path

    def test_neither_set_raises(self, monkeypatch):
        monkeypatch.delenv("FOCAS_DLL_DIR", raising=False)
        with pytest.raises(FocasNoDllError, match="FOCAS_DLL_DIR"):
            _resolve_dll_dir(None)

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(FocasNoDllError, match="not a directory"):
            _resolve_dll_dir(tmp_path / "does_not_exist")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Linux-fallback message is only meaningful off Windows.",
)
class TestLoadFocasLibraryNonWindows:
    def test_raises_on_linux(self, tmp_path):
        # _resolve_dll_dir succeeds on tmp_path; _load_fwlib refuses on Linux.
        from shared.focas.client import load_focas_library

        with pytest.raises(FocasNoDllError, match="Windows-only"):
            load_focas_library(tmp_path)


# ============================================================================
# FocasClient orchestration tests with a fake `lib`
# ============================================================================


def _struct_from_template(template: ctypes.Structure, dst_p: Any) -> None:
    """Copy `template` into the buffer pointed to by `dst_p` (a ctypes
    pointer-like). Used by fake-lib stubs to emit canned responses."""
    ctypes.memmove(
        dst_p,
        ctypes.addressof(template),
        ctypes.sizeof(type(template)),
    )


def _as_int(arg: Any) -> int:
    """Coerce a ctypes simple-int wrapper to a Python int.

    Direct `int(c_short(1))` fails on Python 3.11+ ctypes — it dispatches
    through bytes conversion. Reach into `.value` if present.
    """
    return arg.value if hasattr(arg, "value") else int(arg)


class _FakeLib:
    """In-memory FOCAS library stub. Records every call; emits canned
    responses configured per cnc_* function."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.return_codes: dict[str, int] = {}
        self.responses: dict[str, ctypes.Structure] = {}

    def _record(self, name: str, args: tuple[Any, ...]) -> int:
        self.calls.append((name, args))
        return self.return_codes.get(name, 0)

    # --- minimal cnc_* surface --------------------------------------------

    def cnc_freelibhndl(self, handle):
        return self._record("cnc_freelibhndl", (handle,))

    def cnc_settimeout(self, handle, timeout):
        return self._record("cnc_settimeout", (handle, timeout))

    def cnc_sysinfo(self, handle, out_p):
        rc = self._record("cnc_sysinfo", (handle,))
        if "cnc_sysinfo" in self.responses:
            _struct_from_template(self.responses["cnc_sysinfo"], out_p)
        return rc

    def cnc_statinfo(self, handle, out_p):
        rc = self._record("cnc_statinfo", (handle,))
        if "cnc_statinfo" in self.responses:
            _struct_from_template(self.responses["cnc_statinfo"], out_p)
        return rc

    def cnc_modal(self, handle, datano, type_, out_p):
        rc = self._record("cnc_modal", (handle, datano, type_))
        if "cnc_modal" in self.responses:
            _struct_from_template(self.responses["cnc_modal"], out_p)
        return rc

    def cnc_rdtofsinfo(self, handle, out_p):
        rc = self._record("cnc_rdtofsinfo", (handle,))
        if "cnc_rdtofsinfo" in self.responses:
            _struct_from_template(self.responses["cnc_rdtofsinfo"], out_p)
        return rc

    def cnc_rdtofs(self, handle, num, type_, length, out_p):
        rc = self._record("cnc_rdtofs", (handle, num, type_, length))
        # Per-call response keyed by (num, type_). Cast ctypes args to plain
        # ints so test setup keys (`cnc_rdtofs:1:2`) match real call args.
        key = f"cnc_rdtofs:{_as_int(num)}:{_as_int(type_)}"
        if key in self.responses:
            _struct_from_template(self.responses[key], out_p)
        return rc

    def cnc_rdmagazine(self, handle, count_p, arr_p):
        rc = self._record("cnc_rdmagazine", (handle,))
        if "cnc_rdmagazine" in self.responses:
            template = self.responses["cnc_rdmagazine"]
            count_p._obj.value = template["count"]  # type: ignore[attr-defined]
            for i, pot in enumerate(template["pots"]):  # type: ignore[index]
                ctypes.memmove(
                    ctypes.addressof(arr_p.contents) + i * ctypes.sizeof(IODBTLMAG),
                    ctypes.addressof(pot),
                    ctypes.sizeof(IODBTLMAG),
                )
        return rc

    def cnc_rdngrp(self, handle, out_p):
        rc = self._record("cnc_rdngrp", (handle,))
        if "cnc_rdngrp" in self.responses:
            _struct_from_template(self.responses["cnc_rdngrp"], out_p)
        return rc

    def cnc_rdgrpid(self, handle, group_idx, out_p):
        rc = self._record("cnc_rdgrpid", (handle, group_idx))
        key = f"cnc_rdgrpid:{_as_int(group_idx)}"
        if key in self.responses:
            _struct_from_template(self.responses[key], out_p)
        return rc

    def cnc_rdusegrpid(self, handle, out_p):
        rc = self._record("cnc_rdusegrpid", (handle,))
        if "cnc_rdusegrpid" in self.responses:
            _struct_from_template(self.responses["cnc_rdusegrpid"], out_p)
        return rc

    def cnc_rd1tlifedata(self, handle, group_id, slot, out_p):
        rc = self._record("cnc_rd1tlifedata", (handle, group_id, slot))
        key = f"cnc_rd1tlifedata:{_as_int(group_id)}:{_as_int(slot)}"
        if key in self.responses:
            _struct_from_template(self.responses[key], out_p)
        return rc

    def cnc_rdalmmsg2(self, handle, type_, count_p, arr_p):
        rc = self._record("cnc_rdalmmsg2", (handle, type_))
        if "cnc_rdalmmsg2" in self.responses:
            template = self.responses["cnc_rdalmmsg2"]
            count_p._obj.value = template["count"]  # type: ignore[attr-defined]
            for i, alm in enumerate(template["alarms"]):  # type: ignore[index]
                ctypes.memmove(
                    ctypes.addressof(arr_p.contents) + i * ctypes.sizeof(ODBALMMSG2),
                    ctypes.addressof(alm),
                    ctypes.sizeof(ODBALMMSG2),
                )
        return rc


def _make_client(lib: _FakeLib, **kwargs: Any) -> FocasClient:
    return FocasClient(lib=lib, handle=42, ip="10.0.0.1", port=8193, **kwargs)


class TestFocasClientLifecycle:
    def test_close_calls_freelibhndl(self):
        lib = _FakeLib()
        c = _make_client(lib)
        c.close()
        assert any(name == "cnc_freelibhndl" for name, _ in lib.calls)

    def test_close_is_idempotent(self):
        lib = _FakeLib()
        c = _make_client(lib)
        c.close()
        c.close()
        free_calls = [n for n, _ in lib.calls if n == "cnc_freelibhndl"]
        assert len(free_calls) == 1

    def test_context_manager_closes(self):
        lib = _FakeLib()
        with _make_client(lib):
            pass
        assert any(name == "cnc_freelibhndl" for name, _ in lib.calls)


class TestFocasClientReadSysinfo:
    def test_returns_decoded_dict(self):
        lib = _FakeLib()
        canned = ODBSYS()
        canned.cnc_type = b"0i"
        canned.mt_type = b"M\x00"
        canned.series = b"D4F1"
        canned.version = b"15.0"
        canned.max_axis = 3
        lib.responses["cnc_sysinfo"] = canned
        info = _make_client(lib).read_sysinfo()
        assert info["cnc_type"] == "0i"
        assert info["series"] == "D4F1"

    def test_raises_on_focas_error(self):
        lib = _FakeLib()
        lib.return_codes["cnc_sysinfo"] = 5
        with pytest.raises(FocasError, match="cnc_sysinfo"):
            _make_client(lib).read_sysinfo()


class TestFocasClientAssertExpectedControl:
    def test_passes_on_expected_control(self):
        lib = _FakeLib()
        canned = ODBSYS()
        canned.cnc_type = b"0i"
        canned.mt_type = b"M\x00"
        canned.series = b"D4F1"
        canned.version = b"15.0"
        lib.responses["cnc_sysinfo"] = canned
        info = _make_client(lib).assert_expected_control()
        assert info["cnc_type"] == "0i"

    def test_raises_on_wrong_control(self):
        lib = _FakeLib()
        canned = ODBSYS()
        canned.cnc_type = b"30"  # not 0i — wrong machine
        canned.mt_type = b"M\x00"
        lib.responses["cnc_sysinfo"] = canned
        with pytest.raises(FocasError, match="R9"):
            _make_client(lib).assert_expected_control()


class TestFocasClientReadStatus:
    def test_combines_statinfo_and_modal(self):
        lib = _FakeLib()
        st = ODBST()
        st.aut = 1
        st.run = 0
        st.emergency = 0
        lib.responses["cnc_statinfo"] = st
        modal = ODBMDL()
        modal.modal.aux.aux_data = 25
        lib.responses["cnc_modal"] = modal

        status = _make_client(lib).read_status()
        assert status.mode is MachineMode.MEM
        assert status.current_t_number == 25

    def test_modal_failure_does_not_fail_status(self):
        lib = _FakeLib()
        st = ODBST()
        st.aut = 1
        lib.responses["cnc_statinfo"] = st
        lib.return_codes["cnc_modal"] = 13  # simulate reject

        status = _make_client(lib).read_status()
        assert status.current_t_number is None
        assert status.mode is MachineMode.MEM


class TestFocasClientReadOffsets:
    def test_iterates_use_no_times_four_types(self):
        lib = _FakeLib()
        layout = ODBTLINF()
        layout.ofs_type = 1
        layout.use_no = 2
        lib.responses["cnc_rdtofsinfo"] = layout

        # Provide a canned response for each (num, type) so all reads
        # succeed and we can count them.
        for num in (1, 2):
            for type_code in (1, 2, 3, 4):
                t = ODBTOFS()
                t.datano = num
                t.data = num * 1000 + type_code
                lib.responses[f"cnc_rdtofs:{num}:{type_code}"] = t

        client = _make_client(lib)
        offsets = client.read_offsets()
        assert len(offsets) == 2 * 4  # 2 registers x 4 banks

        rdtofs_calls = [c for c in lib.calls if c[0] == "cnc_rdtofs"]
        assert len(rdtofs_calls) == 8

    def test_skips_zero_datano_responses(self):
        # When FOCAS returns rc=0 but no real data (datano=0), the client
        # treats it as an unconfigured slot and skips. Guards against the
        # decoder being asked to build an OffsetRegister with register=0
        # which would fail Pydantic validation (R6-adjacent: don't ship
        # bogus offsets to the audit log).
        lib = _FakeLib()
        layout = ODBTLINF()
        layout.ofs_type = 1
        layout.use_no = 1
        lib.responses["cnc_rdtofsinfo"] = layout
        # Only the H_geom (type=1) read returns valid data; the other
        # three types return rc=0 with a zero-init buffer (datano=0).
        ok = ODBTOFS()
        ok.datano = 1
        ok.data = 1234
        lib.responses["cnc_rdtofs:1:1"] = ok

        offsets = _make_client(lib).read_offsets()
        assert len(offsets) == 1
        assert offsets[0].register_number == 1
        assert offsets[0].register_type is RegisterType.H_GEOM


class TestFocasClientReadAlarms:
    def test_decodes_count_alarms(self):
        lib = _FakeLib()
        a1 = ODBALMMSG2()
        a1.alm_no = 506
        a1.axis = 1
        a1.msg_len = 9
        a1.alm_msg = b"Overtravel"
        a2 = ODBALMMSG2()
        a2.alm_no = 100
        a2.msg_len = 4
        a2.alm_msg = b"Test"
        lib.responses["cnc_rdalmmsg2"] = {"count": 2, "alarms": [a1, a2]}

        alarms = _make_client(lib).read_alarms()
        assert len(alarms) == 2
        assert alarms[0].code == 506
        assert alarms[1].code == 100


class TestFocasClientReadPots:
    def test_decodes_pot_table(self):
        lib = _FakeLib()
        p1 = IODBTLMAG()
        p1.magazine = 1
        p1.pot = 1
        p1.tool_index = 5
        p2 = IODBTLMAG()
        p2.magazine = 1
        p2.pot = 2
        p2.tool_index = 0  # empty
        lib.responses["cnc_rdmagazine"] = {"count": 2, "pots": [p1, p2]}

        pots = _make_client(lib, max_pots=8).read_pots()
        assert len(pots) == 2
        assert pots[0].t_number == 5
        assert pots[1].t_number is None


class TestFocasClientReadToolLife:
    def test_empty_when_no_groups(self):
        lib = _FakeLib()
        ngrp = ODBTLIFE2()
        ngrp.data = 0
        lib.responses["cnc_rdngrp"] = ngrp
        assert _make_client(lib).read_tool_life() == ()

    def test_walks_groups_and_slots(self):
        lib = _FakeLib()
        ngrp = ODBTLIFE2()
        ngrp.data = 1  # one group
        lib.responses["cnc_rdngrp"] = ngrp

        usegrp = ODBUSEGR()
        usegrp.use = 1
        lib.responses["cnc_rdusegrpid"] = usegrp

        gid = ODBTLIFE1()
        gid.data = 100  # group ID = 100
        lib.responses["cnc_rdgrpid:1"] = gid

        # Two tools in the group, then end-of-list (slot 3 returns rc!=0).
        td1 = IODBTD()
        td1.tool_num = 5
        td1.h_code = 5
        td1.d_code = 5
        td2 = IODBTD()
        td2.tool_num = 7
        td2.h_code = 7
        td2.d_code = 7
        lib.responses["cnc_rd1tlifedata:100:1"] = td1
        lib.responses["cnc_rd1tlifedata:100:2"] = td2
        lib.return_codes["cnc_rd1tlifedata"] = 0
        # Slot 3 has no response; default rc=0 leaves tool_num=0 which the
        # client treats as end-of-list.

        out = _make_client(lib).read_tool_life()
        assert len(out) == 2
        assert {t.t_number for t in out} == {5, 7}


# ============================================================================
# FocasClient.connect — DLL-mocked path
# ============================================================================


class TestFocasClientConnect:
    def test_connect_calls_allclibhndl3_and_settimeout(self):
        fake_lib = _FakeLib()

        # cnc_allclibhndl3 isn't on _FakeLib because in real usage the lib
        # is constructed by load_focas_library; we patch that to return
        # our fake plus add the missing surface.
        def fake_allclibhndl3(ip, port, timeout, handle_p):
            handle_p._obj.value = 99
            fake_lib.calls.append(("cnc_allclibhndl3", (ip, port, timeout)))
            return 0

        fake_lib.cnc_allclibhndl3 = fake_allclibhndl3  # type: ignore[attr-defined]

        with patch("shared.focas.client.load_focas_library", return_value=fake_lib):
            client = FocasClient.connect("10.1.10.58", port=8193, timeout_seconds=3)

        assert any(name == "cnc_allclibhndl3" for name, _ in fake_lib.calls)
        assert any(name == "cnc_settimeout" for name, _ in fake_lib.calls)
        client.close()

    def test_connect_raises_on_focas_error(self):
        fake_lib = _FakeLib()

        def fake_allclibhndl3(ip, port, timeout, handle_p):
            return -8  # invalid handle / connection failure

        fake_lib.cnc_allclibhndl3 = fake_allclibhndl3  # type: ignore[attr-defined]

        with patch("shared.focas.client.load_focas_library", return_value=fake_lib):
            with pytest.raises(FocasConnectError, match="cnc_allclibhndl3"):
                FocasClient.connect("10.1.10.58")
