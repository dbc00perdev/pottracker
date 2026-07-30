"""FOCAS read client: `FocasClient` — high-level read API for one machine.

Phase 1 read coverage. `cnc_wrtofs` is intentionally NOT bound here; Phase 6
will add it via `shared/focas/writer.py` with two-stage UI confirmation, mode
lockout, read-after-write verification, drift abort, and audit logging.

# Layering (split across modules 2026-07-30 for the 400-LOC cap; this module
# re-exports the whole surface so existing imports keep resolving)

  `loader.py`       — loads `Fwlib64.dll` (sibling preload dance), applies
                      `argtypes`/`restype` per `tasks/spec-focas-calls.md`.
  `decoders.py`     — pure decoders (ctypes Structure -> Pydantic model) +
                      every verified binding constant (PMC addresses,
                      offset type maps, increments).
  `client_reads.py` — the bulk domain reads (offsets / pots / tool life /
                      alarms / macros) as functions taking the client
                      (same idiom as `lathe.py`).
  `FocasClient`     — (here) connection lifecycle, identity check (R9),
                      status + PMC primitives, `read_snapshot()`
                      orchestration. One instance per machine; raises
                      typed exceptions from `shared.focas.errors`.

# Mock vs real

`shared.focas.mock.MockFocasSource` is the read-only swap-in for tests
and dev hosts. Selection happens at the caller layer (poller, FastAPI
routes) via the `FOCAS_MODE` env var. This module always talks to a
real DLL — the mock implements the same observable surface (returning
`MachineSnapshot` / Pydantic models) so callers can substitute freely.
"""

from __future__ import annotations

import ctypes
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Self

from . import client_reads
from .ctypes_defs import IODBPMC, ODBST, ODBSYS
from .decoders import (
    _PMC_AREA_R,
    _PMC_DATA_BYTE,
    _PMC_R_HEAD_ADDR,
    _PMC_R_NEXT_ADDR,
    _SKIP_MACRO_VARS,
    DEFAULT_OFFSET_INCREMENT,
    decode_alarm,
    decode_macro,
    decode_offset,
    decode_offset_layout,
    decode_pot,
    decode_pot_bcd,
    decode_status,
    decode_sysinfo,
    decode_tool_life,
)
from .errors import FocasConnectError, FocasError, raise_for_code
from .loader import _resolve_dll_dir, load_focas_library
from .models import (
    AlarmEntry,
    MachineSnapshot,
    MachineStatus,
    MacroVariable,
    OffsetRegister,
    PotEntry,
    ToolLife,
)

_logger = logging.getLogger("shared.focas.client")


class FocasClient:
    """High-level FOCAS read client for one machine.

    Use as a context manager:

        with FocasClient.connect("10.1.10.58", 8193, machine_id="viper") as fc:
            snap = fc.read_snapshot()

    Or manage explicitly via `connect()` / `close()`.

    Not thread-safe; create one instance per FOCAS handle. Reconnect
    semantics, retry policy, circuit breaker — those are concerns for the
    caller (`shared.focas.poller`, Phase 1.5).
    """

    def __init__(
        self,
        lib: Any,
        handle: int,
        ip: str,
        port: int,
        machine_id: str | None = None,
        offset_increment: Decimal = DEFAULT_OFFSET_INCREMENT,
        max_pots: int = 100,
        pot_count: int = 24,
    ) -> None:
        self._lib = lib
        self._handle = ctypes.c_ushort(handle)
        self._ip = ip
        self._port = port
        # Stamped onto every MachineSnapshot this client produces. Set here
        # (or at connect() time) rather than passed per-call to read_snapshot,
        # so FocasClient natively satisfies the zero-arg SnapshotSource
        # protocol the Poller/persist path calls against — no wrapper bridge.
        self._machine_id = machine_id
        self._offset_increment = offset_increment
        self._max_pots = max_pots  # cnc_rdmagazine array capacity (generic path)
        self._pot_count = pot_count  # PMC D-area pot window size (Viper = 24)
        self._closed = False
        # Filled by `read_offset_layout()` on first call. Cached because
        # they only change when the operator reconfigures the offset
        # table on the control — rare event.
        self._offset_use_no: int | None = None
        self._ofs_type: int | None = None

    @classmethod
    def connect(
        cls,
        ip: str,
        port: int = 8193,
        timeout_seconds: int = 3,
        dll_dir: str | os.PathLike[str] | None = None,
        machine_id: str | None = None,
        pot_count: int = 24,
    ) -> Self:
        """Allocate a FOCAS library handle for the named control.

        Pass `machine_id` to stamp every snapshot this client produces and
        to make it a drop-in `SnapshotSource` for the poller. Probe/diag
        callers that never call `read_snapshot()` may omit it. `pot_count`
        sizes the PMC D-area pot read (`shared.machine.pot_count`; Viper = 24).
        """
        lib = load_focas_library(dll_dir)
        handle = ctypes.c_ushort(0)
        ip_bytes = ip.encode("ascii")
        rc = lib.cnc_allclibhndl3(
            ip_bytes,
            ctypes.c_ushort(port),
            ctypes.c_int32(timeout_seconds),
            ctypes.byref(handle),
        )
        if rc != 0:
            raise FocasConnectError(
                code=rc,
                context="cnc_allclibhndl3",
                message=f"connect to {ip}:{port} failed",
            )
        # Set per-call timeout (Open question O7 — verify units; FOCAS2 docs
        # say seconds for cnc_settimeout).
        rc = lib.cnc_settimeout(handle, ctypes.c_int32(timeout_seconds))
        if rc != 0:
            # Best-effort; not fatal. Default DLL timeout still applies.
            _logger.warning("cnc_settimeout returned %d; using DLL default", rc)

        client = cls(lib, handle.value, ip, port, machine_id=machine_id, pot_count=pot_count)

        # Prime the connection. On this 0i-MF (FS30i family DLL), a fresh
        # handle from cnc_allclibhndl3 + cnc_settimeout is NOT immediately
        # usable for cnc_statinfo / cnc_modal — those calls return rc=-8
        # until the DLL has serviced at least one cnc_sysinfo on the
        # handle. The smoke worked because assert_expected_control() does
        # cnc_sysinfo first; the poller's read_snapshot path went straight
        # to cnc_statinfo and hit the failure on every cycle. One sysinfo
        # call (~10ms) per connect closes the gap; reconnects in the
        # circuit-breaker path get primed automatically.
        try:
            client.read_sysinfo()
        except FocasError as exc:
            client.close()
            raise FocasConnectError(
                code=exc.code,
                context="connect_prime",
                message=f"cnc_sysinfo prime call failed: {exc}",
            ) from exc

        return client

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the FOCAS library handle. Idempotent."""
        if self._closed:
            return
        self._closed = True
        try:
            self._lib.cnc_freelibhndl(self._handle)
        except Exception as exc:  # pragma: no cover
            _logger.warning("cnc_freelibhndl raised: %s", exc)

    # --- identity / status ---------------------------------------------------

    def read_sysinfo(self) -> dict[str, str | int]:
        """Read CNC system info. Use at startup for R9 identity check."""
        out = ODBSYS()
        rc = self._lib.cnc_sysinfo(self._handle, ctypes.byref(out))
        raise_for_code(rc, context="cnc_sysinfo")
        return decode_sysinfo(out)

    def assert_expected_control(
        self,
        expected_cnc_type: str = "0",
        expected_mt_type: str = "M",
        expected_series: str | None = "D4F1",
    ) -> dict[str, str | int]:
        """Refuse to proceed unless the connected control identifies as the
        expected family/series. R9 detection: a routing or reconnect
        accident lands us on a different control; we want a hard stop, not
        silent corruption.

        Defaults are calibrated to the Lance Mighty Viper LG-1000AP (0i-MF)
        as observed in the Phase 1 integration smoke:

            cnc_type=' 0'  ->  '0' after strip
            mt_type=' M'   ->  'M' after strip
            series='D4F1'

        FANUC's `cnc_type` is a 2-char field carrying the major series
        number only ('0', '30', '16', etc.); the 'i' suffix is implied by
        `series`. Pass `expected_series=None` to skip the series check
        (e.g., when adding a control of unknown subseries).
        """
        info = self.read_sysinfo()
        actual_cnc = str(info["cnc_type"])
        actual_mt = str(info["mt_type"])
        actual_series = str(info["series"])
        if (
            actual_cnc != expected_cnc_type
            or actual_mt != expected_mt_type
            or (expected_series is not None and actual_series != expected_series)
        ):
            raise FocasError(
                code=0,
                context="assert_expected_control",
                message=(
                    f"control identifies as cnc_type={actual_cnc!r} "
                    f"mt_type={actual_mt!r} series={actual_series!r}; "
                    f"expected {expected_cnc_type!r}/{expected_mt_type!r}/"
                    f"{expected_series!r}. Refusing to proceed (R9)."
                ),
            )
        return info

    def read_status(self) -> MachineStatus:
        """Read machine status (mode, run, e-stop) plus current/next T-number."""
        out = ODBST()
        rc = self._lib.cnc_statinfo(self._handle, ctypes.byref(out))
        raise_for_code(rc, context="cnc_statinfo")
        status = decode_status(out)
        head, next_t = self._read_active_tools()
        return status.model_copy(
            update={"current_t_number": head, "next_t_number": next_t},
        )

    def _read_active_tools(self) -> tuple[int | None, int | None]:
        """Read (HEAD, NEXT) tool numbers from PMC R-area bytes.

        Returns None for either field on PMC error rather than raising —
        a missing PMC read shouldn't fail the whole status path. Zero is
        also returned as None (no tool loaded / no next pre-selected).
        """
        head = self._read_pmc_byte(_PMC_R_HEAD_ADDR)
        next_t = self._read_pmc_byte(_PMC_R_NEXT_ADDR)
        return (
            head if head and head > 0 else None,
            next_t if next_t and next_t > 0 else None,
        )

    def _read_pmc_byte(self, addr: int, area: int = _PMC_AREA_R) -> int | None:
        out = IODBPMC()
        rc = self._lib.pmc_rdpmcrng(
            self._handle,
            ctypes.c_short(area),
            ctypes.c_short(_PMC_DATA_BYTE),
            ctypes.c_ushort(addr),
            ctypes.c_ushort(addr),
            ctypes.c_ushort(8 + 1),  # 8-byte header + 1 data byte
            ctypes.byref(out),
        )
        if rc != 0:
            _logger.debug("pmc_rdpmcrng area=%d addr=%d returned %d; reporting None", area, addr, rc)
            return None
        return int(out.u.cdata[0])

    # --- bulk reads (implementations in client_reads.py) ---------------------

    def read_offset_layout(self) -> tuple[int, int]:
        """Read offset table layout (`ofs_type`, `use_no`). Cached after
        first call until `close()`. See `client_reads.read_offset_layout`."""
        return client_reads.read_offset_layout(self)

    def read_offsets(self) -> tuple[OffsetRegister, ...]:
        """Read every offset register, dispatched by the control's
        `ofs_type`. See `client_reads.read_offsets`."""
        return client_reads.read_offsets(self)

    def read_pots(self) -> tuple[PotEntry, ...]:
        """Read the pot->tool identity table for this control.

        On the Lance Mighty Viper the FANUC magazine option is unlicensed
        (`cnc_rdmagazine` = EW_NOOPT), so the table is read from the PMC
        D-area — see `read_pots_pmc`. The result is IDENTITY only (which T#
        nominally lives in each pot); pot cells are sticky and never reliably
        signal presence. Occupancy truth = the offset table (non-zero geom
        offset = a measured tool is really present), correlated in the app
        layer. Diff/persist/audit downstream consume `PotEntry` unchanged.

        `_read_pots_magazine` retains the generic `cnc_rdmagazine` path for a
        future magazine-licensed control / Phase-8 per-machine dispatch.
        """
        return self.read_pots_pmc()

    def read_pots_pmc(self) -> tuple[PotEntry, ...]:
        """PMC D-area pot read (OEM Mighty Viper binding). See
        `client_reads.read_pots_pmc`."""
        return client_reads.read_pots_pmc(self)

    def _read_pots_magazine(self) -> tuple[PotEntry, ...]:
        """Generic `cnc_rdmagazine` path (EW_NOOPT on the Viper). See
        `client_reads.read_pots_magazine`."""
        return client_reads.read_pots_magazine(self)

    def read_tool_life(self) -> tuple[ToolLife, ...]:
        """Read tool life management data. See `client_reads.read_tool_life`."""
        return client_reads.read_tool_life(self)

    def read_alarms(self) -> tuple[AlarmEntry, ...]:
        """Read active alarms. See `client_reads.read_alarms`."""
        return client_reads.read_alarms(self)

    def read_macro(self, number: int) -> Decimal | None:
        """Read one custom-macro variable (`None` if vacant). See
        `client_reads.read_macro`."""
        return client_reads.read_macro(self, number)

    def read_macros(self, numbers: tuple[int, ...] = _SKIP_MACRO_VARS) -> tuple[MacroVariable, ...]:
        """Read a set of custom-macro variables (default: the G31 skip vars
        #5061-#5063 for presetter attribution). See `client_reads.read_macros`."""
        return client_reads.read_macros(self, numbers)

    # --- snapshot ------------------------------------------------------------

    def read_snapshot(self) -> MachineSnapshot:
        """Read every per-cycle data set in one call. Used by the poller.

        Stamps the snapshot with the `machine_id` supplied at connect/construct
        time. Zero-arg by design so `FocasClient` satisfies the `SnapshotSource`
        protocol directly.
        """
        if self._machine_id is None:
            raise FocasError(
                code=0,
                context="read_snapshot",
                message=(
                    "machine_id not set; pass machine_id to "
                    "FocasClient.connect() (or the constructor) before "
                    "calling read_snapshot()."
                ),
            )
        polled_at = datetime.now(UTC)
        status = self.read_status()
        offsets = self.read_offsets()
        pots = self.read_pots()
        tool_life = self.read_tool_life()
        alarms = self.read_alarms()
        macros = self.read_macros()
        return MachineSnapshot(
            machine_id=self._machine_id,
            polled_at=polled_at,
            status=status,
            offsets=offsets,
            pots=pots,
            tool_life=tool_life,
            alarms=alarms,
            macros=macros,
        )


__all__ = [
    "DEFAULT_OFFSET_INCREMENT",
    "FocasClient",
    "_resolve_dll_dir",
    "decode_alarm",
    "decode_macro",
    "decode_offset",
    "decode_offset_layout",
    "decode_pot",
    "decode_pot_bcd",
    "decode_status",
    "decode_sysinfo",
    "decode_tool_life",
    "load_focas_library",
]
