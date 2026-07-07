"""Read-only pull of FANUC custom-macro variables for presetter mapping.

FOCAS-safe: uses ONLY `cnc_rdmacro` (reads macro variables). No writes, no motion.

The tool presetter runs a G31 skip cycle: when the skip signal fires, the control
latches the axis position into system macro vars (#5061-#5069), and the toolsetter
macro typically stashes measured lengths/diameters in common vars (#500+) before
writing the offset register. This dumps the current values of those ranges so we
can see which vars carry the presetter's verification signal — then confirm by
diffing across an actual presetter cycle (operator-triggered).

    python scripts/probe_presetter.py --ip 10.1.10.58 --output reports/presetter.json
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from typing import Any

from shared.focas.client import FocasClient


class _ODBM(ctypes.Structure):  # noqa: N801  (ctypes struct; RUF012 waived project-wide)
    _fields_ = [
        ("datano", ctypes.c_short),
        ("dummy", ctypes.c_short),
        ("mcr_val", ctypes.c_int32),
        ("dec_val", ctypes.c_short),
    ]


# Ranges worth pulling. Locals (#100-#149) usually vacant outside a macro call;
# commons (#500+) are the toolsetter's persistent scratch/result store; #5021-#5069
# are the position/skip system vars G31 latches.
_RANGES: list[tuple[int, int, str]] = [
    (100, 149, "local #100-149"),
    (500, 599, "common #500-599 (presetter scratch/results?)"),
    (5021, 5028, "machine position at read #5021-5028"),
    (5041, 5048, "absolute position #5041-5048"),
    (5061, 5069, "G31 SKIP position #5061-5069"),
]


def _bind(fc: FocasClient) -> Any:
    fn = fc._lib.cnc_rdmacro
    fn.restype = ctypes.c_short
    fn.argtypes = [ctypes.c_ushort, ctypes.c_short, ctypes.c_short, ctypes.POINTER(_ODBM)]
    return fn


def _read_macro(fn: Any, handle: int, number: int) -> float | None:
    """Return the decoded macro value, or None if vacant/unreadable."""
    out = _ODBM()
    rc = fn(handle, ctypes.c_short(number), ctypes.c_short(10), ctypes.byref(out))
    if rc != 0 or out.dec_val < 0:  # dec_val == -1 => vacant variable
        return None
    return out.mcr_val / (10**out.dec_val)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=5)
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)

    os.environ.setdefault("FOCAS_DLL_DIR", r"C:\Fanuc\FwLib64-runtime")
    report: dict[str, Any] = {"ip": args.ip, "ranges": {}}

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        fn = _bind(fc)
        for lo, hi, label in _RANGES:
            present: dict[str, float] = {}
            for num in range(lo, hi + 1):
                v = _read_macro(fn, fc._handle, num)
                if v is not None:
                    present[f"#{num}"] = v
            report["ranges"][label] = present
            print(f"\n[{label}] non-vacant: {len(present)}")
            for k, v in present.items():
                print(f"   {k} = {v}")
    finally:
        fc.close()

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nreport written to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
