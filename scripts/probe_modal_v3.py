"""Sweep custom-macro bands for the active head/next tool numbers on 0i-MF.

# Why this exists

probe_modal_v2.py confirmed `cnc_rdmacro` works but neither #4120 nor
#4119 carries the active T on this control. Panel shows head=45 /
next=83, but the modal-T slots returned 0 and #4115=1213 was a stale
last-commanded T-code value.

Sweep `cnc_rdmacror` over plausible bands and flag any slot whose
decoded value equals the panel's head or next number. The hit is the
slot to bind in `shared/focas/client.py` (replacing `cnc_modal(-3, 1)`).

# Usage

    python scripts/probe_modal_v3.py --head 45 --next 83

Prints every non-zero macro in the swept bands plus a HIT marker on any
slot whose decoded value matches `--head` or `--next`. Run with the
panel showing the head/next pair you pass in.
"""

from __future__ import annotations

import argparse
import ctypes
import os

from shared.focas.client import FocasClient

_CHUNK = 5  # IODBMR carries 5 (mcr_val, dec_val) entries per call.


class _MacroEntry(ctypes.Structure):
    _fields_ = [
        ("mcr_val", ctypes.c_int32),
        ("dec_val", ctypes.c_short),
    ]


class _IODBMR(ctypes.Structure):
    """Inline IODBMR matching Fwlib64.h verbatim."""

    _fields_ = [
        ("datano_s", ctypes.c_short),
        ("dummy", ctypes.c_short),
        ("datano_e", ctypes.c_short),
        ("data", _MacroEntry * _CHUNK),
    ]


def _decode(mcr_val: int, dec_val: int) -> float:
    """FANUC macro encoding: actual = mcr_val * 10^(-dec_val)."""
    if dec_val < 0:
        return 0.0  # variable not set on this control
    return mcr_val * (10.0 ** (-dec_val))


def _sweep_band(
    fc: FocasClient,
    start: int,
    end: int,
    head: int,
    next_t: int,
) -> list[tuple[int, float, int, int]]:
    """Sweep [start..end] in chunks of 5 via cnc_rdmacror.

    Returns list of (datano, decoded, raw, dec) for every non-zero entry.
    """
    fn = fc._lib.cnc_rdmacror
    fn.restype = ctypes.c_short
    fn.argtypes = [
        ctypes.c_ushort,
        ctypes.c_short,
        ctypes.c_short,
        ctypes.c_short,
        ctypes.POINTER(_IODBMR),
    ]
    length = ctypes.c_short(ctypes.sizeof(_IODBMR))

    print(f"== sweeping #{start}..#{end} via cnc_rdmacror ==")
    nonzero: list[tuple[int, float, int, int]] = []

    s = start
    while s <= end:
        e = min(s + _CHUNK - 1, end)
        out = _IODBMR()
        rc = fn(
            fc._handle,
            ctypes.c_short(s),
            ctypes.c_short(e),
            length,
            ctypes.byref(out),
        )
        if rc != 0:
            # rc=5 (EW_DATA) is normal when block contains unset vars; only
            # bail on truly bad rc.
            if rc not in (0, 5):
                print(f"  #{s:>4}..#{e:<4}: rc={rc} (skip)")
            s = e + 1
            continue

        for i, slot in enumerate(range(s, e + 1)):
            entry = out.data[i]
            raw = int(entry.mcr_val)
            dec = int(entry.dec_val)
            if raw == 0:
                continue
            decoded = _decode(raw, dec)
            marker = ""
            if abs(decoded - head) < 1e-6:
                marker = f"  <== HIT (matches head={head})"
            elif abs(decoded - next_t) < 1e-6:
                marker = f"  <== HIT (matches next={next_t})"
            print(f"  #{slot:<5} raw={raw:>12} dec={dec:>2}  decoded={decoded:>14.6f}{marker}")
            nonzero.append((slot, decoded, raw, dec))
        s = e + 1
    print()
    return nonzero


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=5)
    p.add_argument("--head", type=int, required=True, help="panel-displayed head/active tool")
    p.add_argument("--next", dest="next_t", type=int, required=True, help="panel next tool to call")
    args = p.parse_args(argv)

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        print(f"target: {args.ip}:{args.port}")
        print(f"looking for: head={args.head}, next={args.next_t}")
        print()

        all_hits: list[tuple[int, float, int, int]] = []
        # FANUC-reserved modal/system macros — most likely home for active T.
        all_hits += _sweep_band(fc, 4000, 4150, args.head, args.next_t)
        # User-program macros — random-ATC controls sometimes stash head/next here.
        all_hits += _sweep_band(fc, 500, 999, args.head, args.next_t)

        head_hits = [h for h in all_hits if abs(h[1] - args.head) < 1e-6]
        next_hits = [h for h in all_hits if abs(h[1] - args.next_t) < 1e-6]

        print("=" * 60)
        print(f"head={args.head} matches: {[h[0] for h in head_hits]}")
        print(f"next={args.next_t} matches: {[h[0] for h in next_hits]}")
        if head_hits:
            print()
            print(
                "BIND in client.py: replace cnc_modal(-3, 1) with "
                f"cnc_rdmacro(handle, datano={head_hits[0][0]}, ...) for head tool. "
                "If multiple slots match, the operator can change the panel head "
                "tool and re-run to disambiguate (only the real slot tracks)."
            )
            return 0
        print()
        print(
            "NO HEAD MATCH. Active tool isn't in the swept macro bands on this "
            "control. Next probe: FANUC parameter range via cnc_rdparam (pot "
            "table parameters), or PMC data area read."
        )
        return 1
    finally:
        fc.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
