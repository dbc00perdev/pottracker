"""FOCAS read client: ctypes wrapper around `Fwlib64.dll` for the FS30i family.

Phase 1 read coverage. `cnc_wrtofs` is intentionally NOT bound here; Phase 6
will add it via `shared/focas/writer.py` with two-stage UI confirmation, mode
lockout, read-after-write verification, drift abort, and audit logging.

# Layering

  `_FocasLibrary` — loads `Fwlib64.dll`, applies `argtypes`/`restype` per
                    the verbatim spec in `tasks/spec-focas-calls.md`. Pure
                    ctypes; no decoding, no Pydantic.

  Decoder functions (module-level, pure) — turn ctypes Structure outputs
                    into Pydantic models from `shared.focas.models`. Tested
                    with hand-built structs; no DLL or machine required.

  `FocasClient`   — high-level API. One instance per machine. Owns the
                    library handle, runs decoders, raises typed exceptions
                    from `shared.focas.errors` on FOCAS error codes.

# Open questions

Several decoders carry conservative assumptions because the integer codes
returned by FOCAS aren't in the header — they're in the FOCAS2 developer
manual and partly empirical. Each is marked `O<n>` matching the open
questions in `tasks/spec-focas-calls.md`. Resolve on first integration
test against the Viper.

  O1 — RESOLVED: head/next tool live in PMC R-area (R327=head, R325=next)
       on this 0i-MF / Mighty Viper stack. cnc_modal does NOT expose them.
  O2 — `cnc_rdtofsinfo.ofs_type` value selecting the IODBTO union variant
  O5 — `IODBTLMAG.tool_index` empty-pot sentinel value
  O6 — `IODBTD.tool_inf` bit layout
  O7 — `cnc_settimeout` units (currently treated as seconds)
  O8 — offset increment parameter for raw long → mm conversion

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
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from .ctypes_defs import (
    IODBPMC,
    IODBTD,
    IODBTLMAG,
    IODBTO,
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
)
from .errors import FocasConnectError, FocasError, FocasNoDllError, raise_for_code
from .models import (
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

_logger = logging.getLogger("shared.focas.client")


# ============================================================================
# Constants
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
_PMC_R_HEAD_ADDR: int = 327  # R-area byte: tool currently in spindle (HEAD)
_PMC_R_NEXT_ADDR: int = 325  # R-area byte: tool to be called next (NEXT)
_PMC_AREA_R: int = 5  # `type_a` value for R-area
_PMC_DATA_BYTE: int = 0  # `type_d` value for byte read

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
# WEAR D) but the FOCAS type-code semantics are H/D-swapped from the
# docs, AND the diameter-wear bank is not readable via FOCAS at all:
#
#   register 396 panel       FOCAS read
#   --------------------     ----------------------------
#   GEOM (H) = 3.0000 mm     type=3 raw=30000   ✓
#   WEAR (H) = 1.7500 mm     type=2 raw=17500   ✓
#   GEOM (D) = -0.3000 mm    type=1 raw=-3000   ✓
#   WEAR (D) = 2.0000 mm     type=4 rejected (EW_ATTRIB)
#
# Verified mapping for this control:
#   type=1  ->  D_GEOM   (NOT H_GEOM as the FANUC docs imply)
#   type=2  ->  H_WEAR
#   type=3  ->  H_GEOM   (NOT D_GEOM as the FANUC docs imply)
#   type=4  ->  D_WEAR   — NOT READABLE via FOCAS on this 0i-MF.
#                          The panel stores and displays D_WEAR; the
#                          FOCAS option configuration on this Lance
#                          Viper does not expose it. Audit log will
#                          have no D_WEAR rows for this machine.
_OFFSET_TYPE_MAP_MEMORY_B: dict[int, RegisterType] = {
    1: RegisterType.D_GEOM,  # CONFIRMED: matches panel "GEOM (D)"
    2: RegisterType.H_WEAR,  # CONFIRMED: matches panel "WEAR (H)"
    3: RegisterType.H_GEOM,  # CONFIRMED: matches panel "GEOM (H)"
    # type=4 omitted: D_WEAR is on the panel but rejects via FOCAS on
    # this control. cnc_rdtofs(type=4) returns EW_ATTRIB regardless of
    # the stored value. UI must display "N/A" for D_WEAR on machines
    # whose ofs_type=2 — there is no FOCAS path to it.
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
# DLL loader
# ============================================================================


def _resolve_dll_dir(dll_dir: str | os.PathLike[str] | None) -> Path:
    """Locate the `Fwlib64.dll` directory.

    Precedence: explicit arg > `FOCAS_DLL_DIR` env > raise.
    """
    if dll_dir is None:
        env = os.environ.get("FOCAS_DLL_DIR")
        if not env:
            raise FocasNoDllError(
                code=0,
                context="dll_load",
                message=(
                    "FOCAS DLL location not set. Pass dll_dir=... or set the "
                    "FOCAS_DLL_DIR environment variable to the directory "
                    "containing Fwlib64.dll."
                ),
            )
        dll_dir = env
    p = Path(dll_dir)
    if not p.is_dir():
        raise FocasNoDllError(
            code=0,
            context="dll_load",
            message=f"FOCAS_DLL_DIR is not a directory: {p}",
        )
    return p


def _load_fwlib(dll_dir: Path) -> Any:
    """Load `Fwlib64.dll` from `dll_dir`. Windows-only; on other platforms
    callers must use the mock harness (`shared.focas.mock`)."""
    if sys.platform != "win32":
        raise FocasNoDllError(
            code=0,
            context="dll_load",
            message=(
                f"FOCAS DLLs are Windows-only (platform={sys.platform!r}). "
                "Use FOCAS_MODE=mock for non-Windows development."
            ),
        )
    dll_path = dll_dir / "Fwlib64.dll"
    if not dll_path.is_file():
        raise FocasNoDllError(
            code=0,
            context="dll_load",
            message=f"Fwlib64.dll not found at {dll_path}",
        )
    # Fwlib64.dll dynamically loads two siblings at the moment of
    # `cnc_allclibhndl3`: `fwlibe64.dll` (TCP transport) and
    # `fwlib30i64.dll` (FS30i family processing). Those internal
    # LoadLibrary calls use Windows's Standard Search Order, which:
    #   - DOES include directories on PATH
    #   - DOES include the loaded-module table (DLLs already in memory
    #     by absolute path are found by short name from cache)
    #   - DOES NOT include directories added via `os.add_dll_directory`
    #     unless the caller uses LoadLibraryEx with the right flag —
    #     and Fwlib64.dll's internal load is plain LoadLibrary
    #
    # First fix attempted only `os.add_dll_directory`; the user's smoke
    # still failed with EW_NODLL (-15). Now we belt-and-suspenders:
    #   1. prepend dll_dir to PATH
    #   2. call os.add_dll_directory (covers ctypes' own LoadLibraryEx)
    #   3. preload each sibling by absolute path so they sit in the
    #      loaded-module table; the front-end DLL's later short-name
    #      LoadLibrary calls find them from cache without filesystem
    #      lookup
    # If a sibling refuses to load, the OSError it raises tells us
    # exactly why (missing MSVC runtime, wrong bitness, etc.) — much
    # better than the cryptic EW_NODLL we get from cnc_allclibhndl3.

    # 1. PATH prepend, idempotent
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if str(dll_dir) not in path_entries:
        os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")

    # 2. add_dll_directory — covers ctypes' own LoadLibraryEx calls.
    os.add_dll_directory(str(dll_dir))

    # 3. Preload siblings by absolute path. Each preload may fail with
    # a distinct OSError that names the actual missing dependency.
    for sibling_name in ("fwlibe64.dll", "fwlib30i64.dll"):
        sibling_path = dll_dir / sibling_name
        if not sibling_path.is_file():
            raise FocasNoDllError(
                code=0,
                context="dll_load",
                message=f"{sibling_name} not found at {sibling_path}",
            )
        try:
            ctypes.WinDLL(str(sibling_path))  # type: ignore[attr-defined]
        except OSError as exc:
            raise FocasNoDllError(
                code=0,
                context="dll_load",
                message=(
                    f"Preload of {sibling_name} from {sibling_path} failed: "
                    f"{exc}. Common causes: (a) missing Microsoft Visual "
                    "C++ Redistributable — install vc_redist.x64.exe from "
                    "Microsoft; (b) 32/64-bit mismatch between Python and "
                    "the DLL — verify with: python -c 'import sys; "
                    "print(sys.maxsize > 2**32)' (must print True)."
                ),
            ) from exc
        _logger.debug("preloaded %s", sibling_name)

    # 4. Front-end DLL last.
    try:
        return ctypes.WinDLL(str(dll_path))  # type: ignore[attr-defined]
    except OSError as exc:
        raise FocasNoDllError(
            code=0,
            context="dll_load",
            message=f"Failed to load {dll_path}: {exc}",
        ) from exc


def _configure_signatures(lib: Any) -> None:
    """Apply argtypes/restype to every FOCAS function we use.

    Without these, ctypes assumes int return and may corrupt 64-bit pointer
    args silently — a silent corruption of every read is worse than a
    visible crash. This routine is non-optional.

    Signatures match the verbatim header in `tasks/spec-focas-calls.md`.
    """
    c_short = ctypes.c_short
    c_ushort = ctypes.c_ushort
    c_int32 = ctypes.c_int32
    c_char_p = ctypes.c_char_p
    p = ctypes.POINTER  # local alias to keep argtypes lines short

    # Connection lifecycle
    lib.cnc_allclibhndl3.argtypes = [c_char_p, c_ushort, c_int32, p(c_ushort)]
    lib.cnc_allclibhndl3.restype = c_short

    lib.cnc_freelibhndl.argtypes = [c_ushort]
    lib.cnc_freelibhndl.restype = c_short

    lib.cnc_settimeout.argtypes = [c_ushort, c_int32]
    lib.cnc_settimeout.restype = c_short

    # System info
    lib.cnc_sysinfo.argtypes = [c_ushort, p(ODBSYS)]
    lib.cnc_sysinfo.restype = c_short

    lib.cnc_sysinfo_ex.argtypes = [c_ushort, p(ODBSYSEX)]
    lib.cnc_sysinfo_ex.restype = c_short

    # Status
    lib.cnc_statinfo.argtypes = [c_ushort, p(ODBST)]
    lib.cnc_statinfo.restype = c_short

    lib.cnc_statinfo2.argtypes = [c_ushort, p(ODBST2)]
    lib.cnc_statinfo2.restype = c_short

    # Modal
    lib.cnc_modal.argtypes = [c_ushort, c_short, c_short, p(ODBMDL)]
    lib.cnc_modal.restype = c_short

    # Offsets
    lib.cnc_rdtofs.argtypes = [c_ushort, c_short, c_short, c_short, p(ODBTOFS)]
    lib.cnc_rdtofs.restype = c_short

    lib.cnc_rdtofsr.argtypes = [c_ushort, c_short, c_short, c_short, c_short, p(IODBTO)]
    lib.cnc_rdtofsr.restype = c_short

    lib.cnc_rdtofsinfo.argtypes = [c_ushort, p(ODBTLINF)]
    lib.cnc_rdtofsinfo.restype = c_short

    # Magazine
    lib.cnc_rdmagazine.argtypes = [c_ushort, p(c_short), p(IODBTLMAG)]
    lib.cnc_rdmagazine.restype = c_short

    # Tool life
    lib.cnc_rdngrp.argtypes = [c_ushort, p(ODBTLIFE2)]
    lib.cnc_rdngrp.restype = c_short

    lib.cnc_rdgrpid.argtypes = [c_ushort, c_short, p(ODBTLIFE1)]
    lib.cnc_rdgrpid.restype = c_short

    lib.cnc_rdgrpid2.argtypes = [c_ushort, c_int32, p(ODBTLIFE5)]
    lib.cnc_rdgrpid2.restype = c_short

    lib.cnc_rdusegrpid.argtypes = [c_ushort, p(ODBUSEGR)]
    lib.cnc_rdusegrpid.restype = c_short

    lib.cnc_rd1tlifedata.argtypes = [c_ushort, c_short, c_short, p(IODBTD)]
    lib.cnc_rd1tlifedata.restype = c_short

    # Alarms
    lib.cnc_rdalmmsg.argtypes = [c_ushort, c_short, p(c_short), p(ODBALMMSG)]
    lib.cnc_rdalmmsg.restype = c_short

    lib.cnc_rdalmmsg2.argtypes = [c_ushort, c_short, p(c_short), p(ODBALMMSG2)]
    lib.cnc_rdalmmsg2.restype = c_short

    # PMC raw read — used to extract the panel HEAD/NEXT tool numbers from
    # R-area bytes on random-ATC controls (O1 resolution).
    lib.pmc_rdpmcrng.argtypes = [
        c_ushort,  # FlibHndl
        c_short,  # type_a (PMC area: 5 = R)
        c_short,  # type_d (data type: 0 = byte)
        c_ushort,  # datano_s
        c_ushort,  # datano_e
        c_ushort,  # length (8-byte header + payload)
        p(IODBPMC),
    ]
    lib.pmc_rdpmcrng.restype = c_short


def load_focas_library(dll_dir: str | os.PathLike[str] | None = None) -> Any:
    """Load and configure `Fwlib64.dll`. Returns the ctypes WinDLL handle
    with all FOCAS function signatures applied."""
    d = _resolve_dll_dir(dll_dir)
    lib = _load_fwlib(d)
    _configure_signatures(lib)
    return lib


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
    program-execution state (0=STOP, 1=HOLD, 2=STaRT, ...). When MEM mode
    is selected and the program is actually running (run >= 2), we expose
    the synthesized `MachineMode.AUTO` — that's the write-lockout signal
    the writer (Phase 6) checks (R6).
    """
    aut = int(odbst.aut)
    run = int(odbst.run)
    mode = _AUT_TO_MODE.get(aut, MachineMode.UNKNOWN)
    is_program_running = run >= 2  # STaRT or higher
    if mode is MachineMode.MEM and is_program_running:
        mode = MachineMode.AUTO
    if mode is MachineMode.UNKNOWN:
        _logger.warning("decode_status: unmapped ODBST.aut=%d run=%d", aut, run)
    return MachineStatus(
        mode=mode,
        running=is_program_running,
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


# ============================================================================
# FocasClient
# ============================================================================


class FocasClient:
    """High-level FOCAS read client for one machine.

    Use as a context manager:

        with FocasClient.connect("10.1.10.58", 8193) as fc:
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
        offset_increment: Decimal = DEFAULT_OFFSET_INCREMENT,
        max_pots: int = 100,
    ) -> None:
        self._lib = lib
        self._handle = ctypes.c_ushort(handle)
        self._ip = ip
        self._port = port
        self._offset_increment = offset_increment
        self._max_pots = max_pots
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
    ) -> Self:
        """Allocate a FOCAS library handle for the named control."""
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
        return cls(lib, handle.value, ip, port)

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

    # --- reads ---------------------------------------------------------------

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

    def _read_pmc_byte(self, addr: int) -> int | None:
        out = IODBPMC()
        rc = self._lib.pmc_rdpmcrng(
            self._handle,
            ctypes.c_short(_PMC_AREA_R),
            ctypes.c_short(_PMC_DATA_BYTE),
            ctypes.c_ushort(addr),
            ctypes.c_ushort(addr),
            ctypes.c_ushort(8 + 1),  # 8-byte header + 1 data byte
            ctypes.byref(out),
        )
        if rc != 0:
            _logger.debug("pmc_rdpmcrng R%d returned %d; reporting None", addr, rc)
            return None
        return int(out.u.cdata[0])

    def read_offset_layout(self) -> tuple[int, int]:
        """Read offset table layout (`ofs_type`, `use_no`). Cached after
        first call until `close()`. The cached `ofs_type` drives the
        type-code dispatch in `read_offsets`."""
        out = ODBTLINF()
        rc = self._lib.cnc_rdtofsinfo(self._handle, ctypes.byref(out))
        raise_for_code(rc, context="cnc_rdtofsinfo")
        ofs_type, use_no = decode_offset_layout(out)
        self._offset_use_no = use_no
        self._ofs_type = ofs_type
        return ofs_type, use_no

    def read_offsets(self) -> tuple[OffsetRegister, ...]:
        """Read every offset register, dispatched by the control's
        `ofs_type` (Memory A / B / C).

        Memory A: 1 type per register, 1 call per register.
        Memory B: 2 types per register (length + diameter), 2 calls each.
                  This is what the Lance Viper reports; 800 calls per cycle.
        Memory C: 4 types per register (length geom/wear, dia geom/wear),
                  1600 calls per cycle.

        Phase 2 poller may switch to `cnc_rdtofsr` (range read) for a
        ~10x speedup once the IODBTO union variant is verified per
        ofs_type — see Open question O3 in `tasks/spec-focas-calls.md`.
        """
        if self._offset_use_no is None or self._ofs_type is None:
            self.read_offset_layout()
        assert self._offset_use_no is not None
        assert self._ofs_type is not None

        type_map = _OFS_TYPE_DISPATCH.get(self._ofs_type)
        if type_map is None:
            _logger.warning(
                "unsupported ofs_type=%d; cannot decode offsets. "
                "Add a mapping to _OFS_TYPE_DISPATCH in shared/focas/client.py.",
                self._ofs_type,
            )
            return ()

        out: list[OffsetRegister] = []
        length = ctypes.sizeof(ODBTOFS)
        for num in range(1, self._offset_use_no + 1):
            for type_code, register_type in type_map.items():
                buf = ODBTOFS()
                rc = self._lib.cnc_rdtofs(
                    self._handle,
                    ctypes.c_short(num),
                    ctypes.c_short(type_code),
                    ctypes.c_short(length),
                    ctypes.byref(buf),
                )
                if rc != 0:
                    _logger.debug("cnc_rdtofs(num=%d, type=%d) returned %d", num, type_code, rc)
                    continue
                if int(buf.datano) <= 0:
                    # rc==0 but the response carries no register number —
                    # treat as an unconfigured / unused slot rather than
                    # synthesizing a row with a bogus datano.
                    continue
                out.append(decode_offset(buf, register_type, self._offset_increment))
        return tuple(out)

    def read_pots(self) -> tuple[PotEntry, ...]:
        """Read magazine / pot table.

        `cnc_rdmagazine` is a FANUC OPTION, not a baseline FOCAS function.
        Controls without the magazine option licensed return rc=6
        (EW_NOOPT). On the Lance Mighty Viper LG-1000AP this is the case;
        we return an empty tuple and log a warning rather than raising,
        so the rest of the snapshot proceeds. Pot tracking on this
        control will need a different mechanism (parameter reads via
        cnc_rdparam, or operator-driven manual assignment).
        """
        ArrayT = IODBTLMAG * self._max_pots  # noqa: N806
        arr = ArrayT()
        count = ctypes.c_short(self._max_pots)
        rc = self._lib.cnc_rdmagazine(
            self._handle, ctypes.byref(count), ctypes.cast(arr, ctypes.POINTER(IODBTLMAG))
        )
        if rc == 6:  # EW_NOOPT
            _logger.warning(
                "cnc_rdmagazine returned EW_NOOPT (option not licensed on "
                "this control); pot tracking via FOCAS unavailable."
            )
            return ()
        raise_for_code(rc, context="cnc_rdmagazine")
        n = int(count.value)
        return tuple(decode_pot(arr[i]) for i in range(n))

    def read_tool_life(self) -> tuple[ToolLife, ...]:
        """Read tool life management data.

        Sequence per the spec doc:
          1. `cnc_rdngrp` — total group count
          2. For each group: `cnc_rdgrpid` -> group ID
          3. `cnc_rdusegrpid` -> currently-active groups (logged for visibility)
          4. For each group + each tool slot: `cnc_rd1tlifedata`

        Empty / disabled tool life management returns ().
        """
        ngrp = ODBTLIFE2()
        rc = self._lib.cnc_rdngrp(self._handle, ctypes.byref(ngrp))
        if rc != 0:
            _logger.debug("cnc_rdngrp returned %d; treating as no tool life", rc)
            return ()
        group_count = int(ngrp.data)
        if group_count <= _NO_TOOL_LIFE:
            return ()

        # Active group info — informational, not gated.
        usegrp = ODBUSEGR()
        rc = self._lib.cnc_rdusegrpid(self._handle, ctypes.byref(usegrp))
        if rc == 0:
            _logger.debug(
                "tool life groups: in_use=%d, next=%d, selecting=%d",
                usegrp.use,
                usegrp.next,
                usegrp.slct,
            )

        out: list[ToolLife] = []
        for group_idx in range(1, group_count + 1):
            group_id_buf = ODBTLIFE1()
            rc = self._lib.cnc_rdgrpid(
                self._handle, ctypes.c_short(group_idx), ctypes.byref(group_id_buf)
            )
            if rc != 0:
                _logger.debug("cnc_rdgrpid(%d) returned %d", group_idx, rc)
                continue
            group_id = int(group_id_buf.data)

            # Read each tool slot in the group. FANUC tool life management
            # supports configurable max tools per group; iterate up to a
            # bounded ceiling and stop on first error per slot.
            for slot in range(1, 64 + 1):
                td = IODBTD()
                rc = self._lib.cnc_rd1tlifedata(
                    self._handle,
                    ctypes.c_short(group_id),
                    ctypes.c_short(slot),
                    ctypes.byref(td),
                )
                if rc != 0:
                    break
                if int(td.tool_num) <= 0:
                    break
                out.append(decode_tool_life(td))
        return tuple(out)

    def read_alarms(self) -> tuple[AlarmEntry, ...]:
        """Read active alarms. Prefers `cnc_rdalmmsg2` (64-char message)."""
        # Allocate an array of 32 alarm records. Most controls report < 10
        # active at any time; 32 is a generous bound.
        capacity = 32
        ArrayT = ODBALMMSG2 * capacity  # noqa: N806
        arr = ArrayT()
        count = ctypes.c_short(capacity)
        rc = self._lib.cnc_rdalmmsg2(
            self._handle,
            ctypes.c_short(_ALARM_TYPE_ALL),
            ctypes.byref(count),
            ctypes.cast(arr, ctypes.POINTER(ODBALMMSG2)),
        )
        raise_for_code(rc, context="cnc_rdalmmsg2")
        n = int(count.value)
        return tuple(decode_alarm(arr[i]) for i in range(n))

    def read_snapshot(self, machine_id: str) -> MachineSnapshot:
        """Read every per-cycle data set in one call. Used by the poller."""
        polled_at = datetime.now(UTC)
        status = self.read_status()
        offsets = self.read_offsets()
        pots = self.read_pots()
        tool_life = self.read_tool_life()
        alarms = self.read_alarms()
        return MachineSnapshot(
            machine_id=machine_id,
            polled_at=polled_at,
            status=status,
            offsets=offsets,
            pots=pots,
            tool_life=tool_life,
            alarms=alarms,
        )


__all__ = [
    "DEFAULT_OFFSET_INCREMENT",
    "FocasClient",
    "decode_alarm",
    "decode_offset",
    "decode_offset_layout",
    "decode_pot",
    "decode_status",
    "decode_sysinfo",
    "decode_tool_life",
    "load_focas_library",
]
