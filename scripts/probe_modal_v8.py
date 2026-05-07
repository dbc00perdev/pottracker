"""Verify R321 (and the other 3 changed bytes) against the live panel.

# Why this exists

probe_modal_v7 diff revealed 4 changed bytes between before/after PMC
snapshots: R201, R313, R314, R321. R321 went from 25 (panel-reported
starting head) to 85 — single-byte storage of a tool number, exactly
the shape of a head register. R313/R314 look like status flag bytes
(bit-mask patterns 0xF6 and 0xFF). R201 (0->2) is probably a counter
or phase flag.

This script reads those 4 addresses (plus a small context band around
each) once and prints their current values. The operator cross-checks
R321 against the panel's current head tool. If they match, R321 IS
the head register and O1 closes.

# Usage

    python scripts/probe_modal_v8.py

Prints the current value of R200..R210 and R310..R325. Compare R321
to the panel's HEAD tool number — if they match, we have our binding.

# What's next if confirmed

Add a thin helper to `shared/focas/client.py`:

    def read_active_tool(self) -> int | None:
        # Reads R321 via pmc_rdpmcrng, returns byte value or None on error.

Replace `cnc_modal(-3, 1)` in `read_status()` with this helper.
"""

from __future__ import annotations

import argparse
import ctypes
import os

from shared.focas.client import FocasClient

_PMC_R = 5  # type_a for R-area


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
        ctypes.c_short(_PMC_R),
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
        print(f"target: {args.ip}:{args.port}")
        print()

        # The 4 candidates plus tight context bands.
        targets: list[tuple[int, str]] = []
        for addr in range(195, 215):
            note = ""
            if addr == 201:
                note = "  <-- changed 0->2 in diff"
            targets.append((addr, note))
        targets.append((-1, "---"))
        for addr in range(310, 320):
            note = ""
            if addr == 313:
                note = "  <-- changed 0->246 in diff"
            elif addr == 314:
                note = "  <-- changed 0->255 in diff"
            targets.append((addr, note))
        targets.append((-1, "---"))
        for addr in range(316, 330):
            note = ""
            if addr == 321:
                note = "  <-- changed 25->85 in diff (HEAD CANDIDATE)"
            targets.append((addr, note))

        for addr, note in targets:
            if addr < 0:
                print(note)
                continue
            v = _read_byte(fc, addr)
            if v is None:
                print(f"  R{addr:<4}: read failed")
            else:
                print(f"  R{addr:<4}: {v:>3} (0x{v:02X}){note}")

        print()
        print("=" * 60)
        v321 = _read_byte(fc, 321)
        if v321 is not None:
            print(f"R321 = {v321}")
            print(
                f"If panel currently shows HEAD = {v321}, R321 is the head "
                "register. Reply with the panel's current head tool number "
                "for confirmation."
            )
        else:
            print("R321 read failed unexpectedly.")
        return 0
    finally:
        fc.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
