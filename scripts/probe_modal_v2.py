"""Probe alternative FOCAS functions for the active T-code on 0i-MF.

# Why this exists

Phase 1 smoke + `probe_modal.py` confirmed `cnc_modal` does not return
the live T on this control. Header extraction (commit 1c1bdcc) found
two real candidates in `Fwlib64.h`:

  - `cnc_rdtdiseltool(handle, long type, long *out1, long *out2)` —
    "read selected tool information"; sweep type=0,1,2 (next/displayed/
    selected) and report both output longs.

  - `cnc_rdmacro(handle, short datano, short length, ODBM *)` —
    read one custom-macro variable. FANUC convention: `#4120` carries
    the modal T number on machining centers; `#4119` carries the
    previous T. We read those plus a small probe band.

# Usage

    python scripts/probe_modal_v2.py [--ip 10.1.10.58]

Run while a tool is loaded (panel shows T<n>). Read-only.

If `cnc_rdtdiseltool` returns the panel T, that's our O1 fix — bind it
in `shared/focas/client.py` and replace the `cnc_modal(-3, 1)` path.
If `#4120` returns the panel T but `cnc_rdtdiseltool` doesn't, fall
back to `cnc_rdmacro`. Either result resolves O1.
"""

from __future__ import annotations

import argparse
import ctypes
import os

from shared.focas.client import FocasClient


class _ODBM(ctypes.Structure):
    """Inline ODBM matching Fwlib64.h verbatim — kept local to the probe so
    we don't add it to ctypes_defs until the function is actually bound."""

    _fields_ = [
        ("datano", ctypes.c_short),
        ("dummy", ctypes.c_short),
        ("mcr_val", ctypes.c_int32),
        ("dec_val", ctypes.c_short),
    ]


# Common macro variables that carry tool-related state on FANUC machining
# centers. #4120 is the one we expect; the rest are belt-and-suspenders
# in case the operator's program uses a non-standard slot.
_MACRO_CANDIDATES: tuple[tuple[int, str], ...] = (
    (4120, "modal T number (FANUC standard for machining centers)"),
    (4119, "previous T (modal)"),
    (4115, "active T (alt convention)"),
    (4001, "modal G group 1"),
    (100, "user macro #100"),
    (149, "user macro #149"),
    (500, "user macro #500"),
)


def _probe_rdtdiseltool(fc: FocasClient) -> int:
    """Sweep type=0,1,2; return number of hits where rc=0 with non-zero data."""
    fn = fc._lib.cnc_rdtdiseltool
    fn.restype = ctypes.c_short
    fn.argtypes = [
        ctypes.c_ushort,
        ctypes.c_long,
        ctypes.POINTER(ctypes.c_long),
        ctypes.POINTER(ctypes.c_long),
    ]

    print("== cnc_rdtdiseltool ==")
    print("  signature: cnc_rdtdiseltool(handle, long type, long *out1, long *out2)")
    print(f"  {'type':>4} | {'rc':>3} | {'out1':>10} | {'out2':>10}")
    print("  " + "-" * 42)

    hits = 0
    for type_code in (0, 1, 2):
        out1 = ctypes.c_long(0)
        out2 = ctypes.c_long(0)
        rc = fn(fc._handle, ctypes.c_long(type_code), ctypes.byref(out1), ctypes.byref(out2))
        marker = ""
        if rc == 0 and (out1.value != 0 or out2.value != 0):
            marker = "  <== HIT"
            hits += 1
        print(f"  {type_code:>4} | {rc:>3} | {out1.value:>10} | {out2.value:>10}{marker}")
    print()
    return hits


def _probe_rdmacro(fc: FocasClient) -> int:
    """Read each candidate macro variable; flag rc=0 with non-zero mcr_val."""
    fn = fc._lib.cnc_rdmacro
    fn.restype = ctypes.c_short
    fn.argtypes = [
        ctypes.c_ushort,
        ctypes.c_short,
        ctypes.c_short,
        ctypes.POINTER(_ODBM),
    ]
    length = ctypes.c_short(ctypes.sizeof(_ODBM))

    print("== cnc_rdmacro ==")
    print("  signature: cnc_rdmacro(handle, short datano, short length, ODBM *)")
    print(f"  {'#var':>5} | {'rc':>3} | {'mcr_val':>10} | {'dec':>3} | note")
    print("  " + "-" * 60)

    hits = 0
    for datano, note in _MACRO_CANDIDATES:
        out = _ODBM()
        rc = fn(fc._handle, ctypes.c_short(datano), length, ctypes.byref(out))
        marker = ""
        if rc == 0 and out.mcr_val != 0:
            marker = "  <== HIT"
            hits += 1
        print(
            f"  #{datano:<4} | {rc:>3} | {int(out.mcr_val):>10} | "
            f"{int(out.dec_val):>3} | {note}{marker}"
        )
    print()
    return hits


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=3)
    args = p.parse_args(argv)

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        print(f"target: {args.ip}:{args.port}")
        print("Run with a tool loaded (panel shows T<n>) — looking for the panel T value.")
        print()

        d_hits = _probe_rdtdiseltool(fc)
        m_hits = _probe_rdmacro(fc)

        print("=" * 60)
        if d_hits or m_hits:
            print(
                f"HITS: cnc_rdtdiseltool={d_hits}, cnc_rdmacro={m_hits}. "
                "Cross-check the highlighted value against the panel's current T. "
                "If one matches, that's the O1 fix — paste the output back so we "
                "can bind it in shared/focas/client.py."
            )
            return 0
        print(
            "NO HITS. Both candidates returned rc=0 with all zeros, or non-zero "
            "rc on every call. Next probe candidates: cnc_rdmacror over a wider "
            "range (#4000..#4200), or read FANUC parameter holding active T."
        )
        return 1
    finally:
        fc.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
