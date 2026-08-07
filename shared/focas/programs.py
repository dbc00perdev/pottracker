"""NC program upload — `cnc_upstart3`/`cnc_upload3`/`cnc_upend3` (READ-ONLY).

Uploads program text FROM the control TO this process. The write counterparts
(`cnc_download*`) are NOT bound anywhere in this repo (spec-offset-export §0).

Live-probed 2026-08-06 (`scripts/probe_upload3.py`, spec-focas-calls.md
"Program upload"): type 0 = NC program on every generation probed (0i-TD/TF/
TF Plus/MF); both TF generations served their foreground-executing program
while cutting in AUTO. `EW_BUFFER` on `cnc_upload3` is rc **+10** and means
"no data ready yet, retry" — NOT an error and NOT -1/EW_BUSY.

Thread-affinity: callers must run connect → read → close on ONE thread (the
FocasClient rule); this module adds no threading of its own.
"""

from __future__ import annotations

import ctypes
import time
from typing import TYPE_CHECKING

from shared.focas.errors import raise_for_code

if TYPE_CHECKING:
    from shared.focas.client import FocasClient

_NC_PROGRAM_TYPE = 0  # cnc_upstart3 data type: NC program (probe-verified)
_EW_BUFFER = 10  # "no data ready, retry" (probe-verified; +10, not -1)
_CHUNK_BYTES = 1440
_MAX_BYTES = 2_000_000  # runaway cap; no sane single program exceeds this
_MAX_CALLS = 5_000
_MAX_EMPTY_STREAK = 250  # ~5s of consecutive EW_BUFFER before giving up
_EMPTY_BACKOFF_SECONDS = 0.02

_bound_libs: set[int] = set()


def _bind(lib: ctypes.WinDLL) -> None:
    if id(lib) in _bound_libs:
        return
    lib.cnc_upstart3.restype = ctypes.c_short
    lib.cnc_upstart3.argtypes = [ctypes.c_ushort, ctypes.c_short,
                                 ctypes.c_long, ctypes.c_long]
    lib.cnc_upload3.restype = ctypes.c_short
    lib.cnc_upload3.argtypes = [ctypes.c_ushort, ctypes.POINTER(ctypes.c_long),
                                ctypes.c_char_p]
    lib.cnc_upend3.restype = ctypes.c_short
    lib.cnc_upend3.argtypes = [ctypes.c_ushort]
    _bound_libs.add(id(lib))


def read_program_text(client: FocasClient, o_number: int) -> bytes:
    """Full text of program O<o_number>, byte-faithful (leading/trailing `%`,
    the control's own spacing). Raises FocasError on any reject; always calls
    `cnc_upend3` so the handle never sticks in upload mode."""
    if o_number <= 0:
        raise ValueError(f"o_number must be positive, got {o_number}")
    lib = client._lib
    _bind(lib)
    rc = lib.cnc_upstart3(client._handle, _NC_PROGRAM_TYPE, o_number, o_number)
    raise_for_code(rc, context="cnc_upstart3")

    chunks: list[bytes] = []
    total = 0
    empty_streak = 0
    buf = ctypes.create_string_buffer(_CHUNK_BYTES)
    try:
        for _ in range(_MAX_CALLS):
            length = ctypes.c_long(_CHUNK_BYTES)
            rc = lib.cnc_upload3(client._handle, ctypes.byref(length), buf)
            if rc == _EW_BUFFER:
                empty_streak += 1
                if empty_streak > _MAX_EMPTY_STREAK:
                    raise TimeoutError(
                        f"cnc_upload3 returned EW_BUFFER {empty_streak} times "
                        f"in a row for O{o_number} — control never yielded data"
                    )
                time.sleep(_EMPTY_BACKOFF_SECONDS)
                continue
            empty_streak = 0
            raise_for_code(rc, context="cnc_upload3")
            got = buf.raw[: int(length.value)]
            chunks.append(got)
            total += len(got)
            if total > _MAX_BYTES:
                raise ValueError(
                    f"program O{o_number} exceeded {_MAX_BYTES} bytes — aborting"
                )
            if total > 1 and got.rstrip().endswith(b"%"):
                break
        else:
            raise TimeoutError(
                f"cnc_upload3 hit the {_MAX_CALLS}-call cap for O{o_number} "
                "without an end-of-data '%'"
            )
    finally:
        # Never raise from cleanup — the primary error is the story; a failed
        # upend surfaces on the next call against this handle anyway.
        lib.cnc_upend3(client._handle)

    return b"".join(chunks)
