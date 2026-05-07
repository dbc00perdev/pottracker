"""Byte-mode PMC sweep for the head/next tool pair.

# Why this exists

probe_modal_v5 (word mode) swept R/D/F cleanly with no hits. Tool IDs
on this machine cap at 99 (single byte), and PMC ladder programmers
typically pack tool numbers as bytes for storage efficiency. A byte
pair `[45, 83]` at an even address reads as word `0x532D = 21293`, not
45 — so word mode misses byte storage by construction.

This probe sweeps R, D, F, K, E areas as bytes (`type_d=0`), one byte
at a time, and flags any byte equal to --head or --next. Adjacent
pairs (within 8 bytes) are the strong signal.

# Usage

    python scripts/probe_modal_v6.py --head 45 --next 83
    python scripts/probe_modal_v6.py --head 45 --next 83 --areas K,E

If still nothing: head/next may be stored as a *packed* short (16-bit
big-endian where the byte pair (45, 83) reads as 0x2D53 = 11603, or
little-endian as 0x532D = 21293) — those are next-step candidates
once we know which areas the OEM populates.
"""

from __future__ import annotations

import argparse
import ctypes
import os

from shared.focas.client import FocasClient

_PMC_AREAS: dict[str, int] = {
    "G": 0,
    "F": 1,
    "Y": 2,
    "X": 3,
    "A": 4,
    "R": 5,
    "T": 6,
    "K": 7,
    "C": 8,
    "D": 9,
    "M": 10,
    "N": 11,
    "E": 12,
    "Z": 13,
}

# Conservative max addresses for 0i-MF Mate — probe stops at the first rc!=0
# anyway, so over-scanning is harmless.
_DEFAULT_MAX: dict[str, int] = {
    "R": 1499,
    "D": 9999,
    "F": 767,
    "K": 99,
    "E": 9999,
    "G": 767,
    "T": 99,
    "C": 79,
    "A": 24,
}

_BYTES_PER_CALL = 5  # IODBPMC.u arrays are sized [5].


class _IODBPMC(ctypes.Structure):
    _fields_ = [
        ("type_a", ctypes.c_short),
        ("type_d", ctypes.c_short),
        ("datano_s", ctypes.c_ushort),
        ("datano_e", ctypes.c_ushort),
        ("u", ctypes.c_ubyte * 40),
    ]


def _sweep_area_bytes(
    fc: FocasClient,
    area: str,
    max_addr: int,
    head: int,
    next_t: int,
) -> list[tuple[str, int, int]]:
    """Sweep area [0..max_addr] as bytes. Returns [(area, addr, value)] for
    every byte equal to head or next. Stops on first rc!=0 chunk (assume
    out of range)."""
    type_a = _PMC_AREAS[area]
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
    length = ctypes.c_ushort(8 + _BYTES_PER_CALL)

    print(f"== sweeping {area}-area (type_a={type_a}) #0..#{max_addr} as bytes ==")
    hits: list[tuple[str, int, int]] = []
    consecutive_errors = 0
    last_ok_addr = -1

    addr = 0
    while addr <= max_addr:
        chunk_end = min(addr + _BYTES_PER_CALL - 1, max_addr)
        out = _IODBPMC()
        rc = fn(
            fc._handle,
            ctypes.c_short(type_a),
            ctypes.c_short(0),  # byte
            ctypes.c_ushort(addr),
            ctypes.c_ushort(chunk_end),
            length,
            ctypes.byref(out),
        )
        if rc != 0:
            consecutive_errors += 1
            # If we've never read this area successfully, the very first
            # chunk failing means the area isn't accessible — bail.
            if last_ok_addr < 0 and consecutive_errors >= 3:
                print(f"  area inaccessible (rc={rc} at start); skipping")
                break
            # If we've been reading fine and suddenly hit errors, we're past
            # the end — stop scanning.
            if consecutive_errors >= 3:
                print(f"  reached end of area at ~{area}{last_ok_addr}")
                break
            addr = chunk_end + 1
            continue

        consecutive_errors = 0
        last_ok_addr = chunk_end
        for i in range(_BYTES_PER_CALL):
            slot_addr = addr + i
            if slot_addr > chunk_end:
                break
            v = int(out.u[i])
            if v == head or v == next_t:
                tag = "head" if v == head else "next"
                print(f"  {area}{slot_addr:<5}: byte={v:>3}  <== matches {tag}")
                hits.append((area, slot_addr, v))
        addr = chunk_end + 1

    print(f"  hits in {area}: {len(hits)}")
    print()
    return hits


def _find_pairs(
    hits: list[tuple[str, int, int]],
    head: int,
    next_t: int,
) -> list[tuple[str, int, int]]:
    """Find (area, head_addr, next_addr) where the two values sit within
    8 bytes of each other in the same area."""
    pairs: list[tuple[str, int, int]] = []
    by_area: dict[str, list[tuple[int, int]]] = {}
    for area, addr, v in hits:
        by_area.setdefault(area, []).append((addr, v))
    for area, items in by_area.items():
        heads = [a for a, v in items if v == head]
        nexts = [a for a, v in items if v == next_t]
        for ha in heads:
            for na in nexts:
                if 0 < abs(na - ha) <= 8:
                    pairs.append((area, ha, na))
    return pairs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=15)
    p.add_argument("--head", type=int, required=True)
    p.add_argument("--next", dest="next_t", type=int, required=True)
    p.add_argument("--areas", default="R,D,F,K,E")
    args = p.parse_args(argv)

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    areas = [a.strip().upper() for a in args.areas.split(",")]
    bad = [a for a in areas if a not in _PMC_AREAS]
    if bad:
        print(f"unknown area names: {bad}")
        return 2

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        print(f"target: {args.ip}:{args.port}")
        print(f"looking for: head={args.head}, next={args.next_t}")
        print(f"areas: {areas}")
        print()

        all_hits: list[tuple[str, int, int]] = []
        for area in areas:
            max_addr = _DEFAULT_MAX.get(area, 999)
            all_hits += _sweep_area_bytes(fc, area, max_addr, args.head, args.next_t)

        pairs = _find_pairs(all_hits, args.head, args.next_t)

        print("=" * 60)
        print(f"total byte hits: {len(all_hits)}")
        print(f"adjacent (head,next) pairs (within 8 bytes): {len(pairs)}")
        for area, ha, na in pairs:
            print(f"  {area}{ha} = {args.head}  +  {area}{na} = {args.next_t}  (delta={na - ha})")

        if pairs:
            print()
            print(
                "STRONG SIGNAL — change the panel's next tool to a different number, "
                "re-run, and confirm the next-addr value tracks the new panel value. "
                "If yes, that's the O1 binding."
            )
            return 0
        if all_hits:
            print()
            print(
                "Hits exist but no adjacent pair. List the hits above and look for "
                "any pair within the same address block. If the head value (45) "
                "appears multiple times, those extras are the pot table — change "
                "the panel head and re-run; only the head variable updates."
            )
            return 0
        print()
        print(
            "NO HITS in byte mode either. Possibilities: head/next stored only "
            "in K (battery-backed) or in a path other than path-1; OR stored "
            "BCD-encoded (e.g. 45 -> 0x45 instead of 0x2D). Next probe: "
            "sweep with --areas K,T,C and try BCD interpretation."
        )
        return 1
    finally:
        fc.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
