"""Single-call cnc_rdmacro sweep over the FANUC system-modal band.

# Why this exists

probe_modal_v3.py used `cnc_rdmacror` (range read) which returned
EW_LENGTH (rc=3) for every chunk in #4000..#4150 — that function is
restricted to user macros on this control. v2 already proved
`cnc_rdmacro` (single read) works on system macros (#4001=1.0,
#4115=1213). This probe completes the sweep one slot at a time.

Background: on a random-ATC machining center the panel "HEAD" tool is
the spindle-loaded tool tracked by the PMC ladder, not an NC modal
value. This sweep is the last cheap check before we move to PMC reads
(`pmc_rdpmcrng`) or magazine-state FOCAS functions
(`cnc_rdcurmgr` / `cnc_rdcurpot`, pending header extraction).

# Usage

    python scripts/probe_modal_v4.py --head 45 --next 83

Prints every non-zero #4000..#4150 macro and flags any decoded value
matching --head or --next.
"""

from __future__ import annotations

import argparse
import ctypes
import os

from shared.focas.client import FocasClient


class _ODBM(ctypes.Structure):
    _fields_ = [
        ("datano", ctypes.c_short),
        ("dummy", ctypes.c_short),
        ("mcr_val", ctypes.c_int32),
        ("dec_val", ctypes.c_short),
    ]


def _decode(mcr_val: int, dec_val: int) -> float:
    if dec_val < 0:
        return 0.0
    return mcr_val * (10.0 ** (-dec_val))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=5)
    p.add_argument("--head", type=int, required=True, help="panel-displayed head/active tool")
    p.add_argument("--next", dest="next_t", type=int, required=True, help="panel next tool to call")
    p.add_argument("--start", type=int, default=4000)
    p.add_argument("--end", type=int, default=4150)
    args = p.parse_args(argv)

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        fn = fc._lib.cnc_rdmacro
        fn.restype = ctypes.c_short
        fn.argtypes = [
            ctypes.c_ushort,
            ctypes.c_short,
            ctypes.c_short,
            ctypes.POINTER(_ODBM),
        ]
        length = ctypes.c_short(ctypes.sizeof(_ODBM))

        print(f"target: {args.ip}:{args.port}")
        print(f"looking for: head={args.head}, next={args.next_t}")
        print(f"sweep: #{args.start}..#{args.end} (single-call cnc_rdmacro)")
        print()

        head_hits: list[int] = []
        next_hits: list[int] = []
        nonzero = 0

        for datano in range(args.start, args.end + 1):
            out = _ODBM()
            rc = fn(fc._handle, ctypes.c_short(datano), length, ctypes.byref(out))
            if rc != 0:
                continue
            raw = int(out.mcr_val)
            dec = int(out.dec_val)
            if raw == 0:
                continue
            decoded = _decode(raw, dec)
            nonzero += 1
            marker = ""
            if abs(decoded - args.head) < 1e-6:
                marker = f"  <== HIT (matches head={args.head})"
                head_hits.append(datano)
            elif abs(decoded - args.next_t) < 1e-6:
                marker = f"  <== HIT (matches next={args.next_t})"
                next_hits.append(datano)
            print(f"  #{datano:<5} raw={raw:>12} dec={dec:>2}  decoded={decoded:>14.6f}{marker}")

        print()
        print("=" * 60)
        print(f"swept {args.end - args.start + 1} slots, {nonzero} non-zero")
        print(f"head={args.head} matches: {head_hits}")
        print(f"next={args.next_t} matches: {next_hits}")
        if head_hits:
            print()
            print(
                f"BIND in client.py: cnc_rdmacro(handle, datano={head_hits[0]}, ...) "
                "for head tool. If multiple slots match, change the panel head tool "
                "and re-run to disambiguate."
            )
            return 0
        print()
        print(
            "NO HEAD MATCH in this band. Head/next is almost certainly PMC data on "
            "this random-ATC. Next: extract magazine/pot-current functions "
            "(cnc_rdcurmgr, cnc_rdcurpot, cnc_rdpotinfo) from Fwlib64.h, then "
            "fall back to pmc_rdpmcrng if none exist."
        )
        return 1
    finally:
        fc.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
