"""FOCAS DLL loader: locate, load and signature-configure `Fwlib64.dll`.

Split out of `shared/focas/client.py` (LOC cap) along the seam the module
always documented: this layer loads the vendor DLL and applies
`argtypes`/`restype` per the verbatim spec in `tasks/spec-focas-calls.md`.
Pure ctypes plumbing; no decoding, no Pydantic, no machine I/O beyond the
OS-level LoadLibrary dance.

Everything here is re-exported by `shared.focas.client` so existing imports
keep resolving.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path
from typing import Any

from .ctypes_defs import (
    IODBPMC,
    IODBTD,
    IODBTLMAG,
    IODBTO,
    ODBALMMSG,
    ODBALMMSG2,
    ODBM,
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
from .errors import FocasNoDllError

_logger = logging.getLogger("shared.focas.loader")


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

    # Custom-macro variable read (G31 skip vars for presetter attribution)
    lib.cnc_rdmacro.argtypes = [c_ushort, c_short, c_short, p(ODBM)]
    lib.cnc_rdmacro.restype = c_short

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

    # NC parameter read — unit/increment verification (params 1013 + 1001#0,
    # `shared/focas/params.py`). Header line 12215: cnc_rdparam(unsigned short,
    # short, short, short, IODBPSD*). The IODBPSD pointer is declared as
    # c_void_p here because the struct lives module-local in params.py (lathe
    # idiom); ctypes passes byref(struct) through void* without conversion.
    lib.cnc_rdparam.argtypes = [c_ushort, c_short, c_short, c_short, ctypes.c_void_p]
    lib.cnc_rdparam.restype = c_short

    # Setting-data read (header line 12260, same IODBPSD shape) — needed for
    # setting 0000 bit 2 (INI, inch/metric INPUT unit). Offsets follow the
    # input unit, NOT parameter 1001#0 INM (the machine/command system):
    # fleet-verified 2026-08-05 that all six controls are metric-machine
    # (INM=0) while the shop runs inch input everywhere.
    lib.cnc_rdset.argtypes = [c_ushort, c_short, c_short, c_short, ctypes.c_void_p]
    lib.cnc_rdset.restype = c_short

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


__all__ = [
    "load_focas_library",
]
