"""`shared.focas.programs.read_program_text` loop logic against a LABELED
fake library (CLAUDE.md anti-pattern #3: the real call behavior was verified
live by `scripts/probe_upload3.py` on four control generations 2026-08-06 —
these tests pin the retry/termination/cleanup logic, not FOCAS itself)."""

from __future__ import annotations

import pytest

import shared.focas.programs as programs
from shared.focas.errors import FocasError


class FakeUploadLib:
    """Scripted cnc_upstart3/upload3/upend3. `upload_script` is a list of
    (rc, payload) consumed per call; EW_BUFFER entries carry no payload."""

    def __init__(self, upstart_rc: int = 0, upload_script: list | None = None):
        self.upstart_rc = upstart_rc
        self.upload_script = list(upload_script or [])
        self.upend_calls = 0

        def cnc_upstart3(handle, dtype, start, end):
            self.upstart_args = (dtype, start, end)
            return self.upstart_rc

        def cnc_upload3(handle, length_ref, buf):
            rc, payload = self.upload_script.pop(0)
            if payload is not None:
                buf.value = payload  # writes into the caller's string buffer
                length_ref._obj.value = len(payload)
            return rc

        def cnc_upend3(handle):
            self.upend_calls += 1
            return 0

        self.cnc_upstart3 = cnc_upstart3
        self.cnc_upload3 = cnc_upload3
        self.cnc_upend3 = cnc_upend3


class FakeClient:
    def __init__(self, lib):
        self._lib = lib
        self._handle = 1


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(programs, "_EMPTY_BACKOFF_SECONDS", 0)
    # fresh bind per fake lib id — the cache set survives across tests
    programs._bound_libs.clear()


def test_happy_path_with_buffer_retries():
    lib = FakeUploadLib(upload_script=[
        (programs._EW_BUFFER, None),
        (0, b"%\nO0080\nG20"),
        (programs._EW_BUFFER, None),
        (0, b"\nM30\n%\n"),
    ])
    out = programs.read_program_text(FakeClient(lib), 80)
    assert out == b"%\nO0080\nG20\nM30\n%\n"
    assert lib.upstart_args == (programs._NC_PROGRAM_TYPE, 80, 80)
    assert lib.upend_calls == 1


def test_upstart_reject_raises_without_upend():
    lib = FakeUploadLib(upstart_rc=13)  # EW_REJECT
    with pytest.raises(FocasError):
        programs.read_program_text(FakeClient(lib), 80)
    assert lib.upend_calls == 0  # upload mode never started


def test_midstream_error_still_upends():
    lib = FakeUploadLib(upload_script=[(0, b"%\nO0080"), (5, None)])  # EW_DATA
    with pytest.raises(FocasError):
        programs.read_program_text(FakeClient(lib), 80)
    assert lib.upend_calls == 1


def test_buffer_starvation_times_out(monkeypatch):
    monkeypatch.setattr(programs, "_MAX_EMPTY_STREAK", 3)
    lib = FakeUploadLib(upload_script=[(programs._EW_BUFFER, None)] * 5)
    with pytest.raises(TimeoutError, match="never yielded data"):
        programs.read_program_text(FakeClient(lib), 80)
    assert lib.upend_calls == 1


def test_rejects_nonpositive_o_number():
    with pytest.raises(ValueError):
        programs.read_program_text(FakeClient(FakeUploadLib()), 0)
