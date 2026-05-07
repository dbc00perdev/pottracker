"""Quick spot-read of R321, R325, R327 — verify R327 tracks panel HEAD.

# Why this exists

probe_modal_v8 found R327 = 85 = panel-reported active tool, and R325
= 31 (likely next-tool). R321 is a fast-mutating scratch register that
flips between R325 and R327 between reads — not stable storage.

This script reads R321/R325/R327 once and prints them. Run it
whenever the panel's HEAD changes to confirm R327 tracks. After two
consecutive runs where R327 matches the panel's HEAD, we bind it as
the head register in `shared/focas/client.py` and O1 closes.

# Usage

    python scripts/probe_modal_v9.py

Output is one line per address. Compare R327 to the panel's current
HEAD; compare R325 to the panel's NEXT (tool to be called).
"""

from __future__ import annotations

import argparse
import ctypes
import os

from shared.focas.client import FocasClient


class _IODBPMC(ctypes.Structure):
    _fields_ = [
        ("type_a", ctypes.c_short),
        ("type_d", ctypes.c_short),
        ("datano_s", ctypes.c_ushort),
        ("datano_e", ctypes.c_ushort),
        ("u", ctypes.c_ubyte * 40),
    ]


def _read_byte(fc: FocasClient, addr: int) -> int | None:
    fn = fc._lib.pmc_rdpmcrng
    fn.restype = ctypes.c_short
    fn.argtypes = [
        ctypes.c_ushort,
        ctypes.c_short,
        ctypes.c_short,
        ctypes.c_ushort,
        ctypes.c_ushort,
        ctypes.c_ushort,
        ctypes.POINTER(_IODBPMC),
    ]
    out = _IODBPMC()
    rc = fn(
        fc._handle,
        ctypes.c_short(5),  # R-area
        ctypes.c_short(0),  # byte
        ctypes.c_ushort(addr),
        ctypes.c_ushort(addr),
        ctypes.c_ushort(8 + 1),
        ctypes.byref(out),
    )
    if rc != 0:
        return None
    return int(out.u[0])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=5)
    args = p.parse_args(argv)

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        r321 = _read_byte(fc, 321)
        r325 = _read_byte(fc, 325)
        r327 = _read_byte(fc, 327)
        print(f"R321 = {r321}  (transient scratch — expected to flip)")
        print(f"R325 = {r325}  (candidate: NEXT tool to call)")
        print(f"R327 = {r327}  (candidate: HEAD / active tool)")
        print()
        print(f"=> Compare R327={r327} against the panel's current HEAD.")
        print(f"=> Compare R325={r325} against the panel's NEXT.")
        return 0
    finally:
        fc.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
