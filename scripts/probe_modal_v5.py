"""Sweep PMC R/D/F areas for the active head/next tool pair.

# Why this exists

probe_modal_v4 confirmed no NC modal slot carries the panel's HEAD tool
on this random-ATC mill; the magazine-state FOCAS calls
(`cnc_rdcurmgr`, `cnc_rdcurpot`, `cnc_rdpotinfo`, `cnc_rdmagsts`,
`cnc_rdspmaint`, `cnc_rdmgrptool`) are all absent from `Fwlib64.h`.

That leaves PMC raw read via `pmc_rdpmcrng`. The Mighty Viper's tool
changer is implemented as PMC ladder logic; head/next are almost
certainly stored in the R-area (internal relay) or D-area (data table)
as 16-bit words at OEM-chosen addresses.

This probe:
  1. Calls `pmc_rdpmcinfo` to enumerate populated PMC areas.
  2. Sweeps R, D, and F areas as 16-bit words.
  3. Reports every word equal to --head or --next.
  4. Flags adjacent pairs (head/next stored 2-4 bytes apart = strong
     signal for "this is the OEM's loaded-tool block").

# Usage

    python scripts/probe_modal_v5.py --head 45 --next 83

If we get a single (area, address) where head and next sit adjacent,
that's our binding. We record it, write a small `read_active_tool()`
helper in `client.py` that reads exactly those two words, and O1 closes.
"""

from __future__ import annotations

import argparse
import ctypes
import os

from shared.focas.client import FocasClient

# PMC address types for `type_a` (Fwlib64.h ABI / FANUC FOCAS docs).
_PMC_AREAS: dict[int, str] = {
    0: "G",
    1: "F",
    2: "Y",
    3: "X",
    4: "A",
    5: "R",
    6: "T",
    7: "K",
    8: "C",
    9: "D",
    10: "M",
    11: "N",
    12: "E",
    13: "Z",
}

_WORDS_PER_CALL = 5  # IODBPMC.u arrays are sized [5].


class _ODBPMCINF_Entry(ctypes.Structure):  # noqa: N801
    _fields_ = [
        ("pmc_adr", ctypes.c_byte),
        ("adr_attr", ctypes.c_byte),
        ("top_num", ctypes.c_ushort),
        ("last_num", ctypes.c_ushort),
    ]


class _ODBPMCINF(ctypes.Structure):
    _fields_ = [
        ("datano", ctypes.c_short),
        ("info", _ODBPMCINF_Entry * 64),
    ]


class _IODBPMC(ctypes.Structure):
    """IODBPMC with the union allocated as a 40-byte buffer (max variant =
    dfdata[5] = 5 * 8 = 40). For word reads we view the first 10 bytes as
    short[5]; for byte reads, the first 5 bytes as char[5]."""

    _fields_ = [
        ("type_a", ctypes.c_short),
        ("type_d", ctypes.c_short),
        ("datano_s", ctypes.c_ushort),
        ("datano_e", ctypes.c_ushort),
        ("u", ctypes.c_ubyte * 40),
    ]


def _enumerate_pmc(fc: FocasClient) -> list[tuple[int, str, int, int]]:
    """Return [(type_a, name, top, last)] for every populated area."""
    fn = fc._lib.pmc_rdpmcinfo
    fn.restype = ctypes.c_short
    fn.argtypes = [ctypes.c_ushort, ctypes.c_short, ctypes.POINTER(_ODBPMCINF)]

    out = _ODBPMCINF()
    rc = fn(fc._handle, ctypes.c_short(0), ctypes.byref(out))
    print(f"== pmc_rdpmcinfo (rc={rc}, datano={int(out.datano)}) ==")
    if rc != 0:
        print("  failed; falling back to assumed defaults")
        return [(5, "R", 0, 7999), (9, "D", 0, 9999), (1, "F", 0, 767)]

    results: list[tuple[int, str, int, int]] = []
    for i in range(64):
        e = out.info[i]
        ta = int(e.pmc_adr)
        top = int(e.top_num)
        last = int(e.last_num)
        if last == 0 and top == 0:
            continue
        name = _PMC_AREAS.get(ta, f"?{ta}")
        print(
            f"  [{i:>2}] type_a={ta:>2} ({name})  top={top:>5}  last={last:>5}  attr={int(e.adr_attr)}"
        )
        results.append((ta, name, top, last))
    print()
    return results


def _sweep_area_words(
    fc: FocasClient,
    type_a: int,
    name: str,
    top: int,
    last: int,
    head: int,
    next_t: int,
) -> list[tuple[int, str, int, int]]:
    """Sweep [top..last] as 16-bit words (type_d=1). Returns [(type_a, name,
    addr, value)] for every word equal to head or next."""
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
    # Length per FANUC convention: 8-byte header + N-byte payload.
    chunk_bytes = _WORDS_PER_CALL * 2  # 5 words = 10 bytes
    length = ctypes.c_ushort(8 + chunk_bytes)

    print(f"== sweeping {name}-area (type_a={type_a}) #{top}..#{last} as words ==")
    hits: list[tuple[int, str, int, int]] = []
    err_count = 0

    addr = top
    while addr <= last:
        chunk_end = min(addr + chunk_bytes - 1, last)
        out = _IODBPMC()
        rc = fn(
            fc._handle,
            ctypes.c_short(type_a),
            ctypes.c_short(1),  # word
            ctypes.c_ushort(addr),
            ctypes.c_ushort(chunk_end),
            length,
            ctypes.byref(out),
        )
        if rc != 0:
            err_count += 1
            if err_count <= 3:
                print(f"  {name}{addr:<5}..{name}{chunk_end:<5}: rc={rc}")
            addr = chunk_end + 1
            continue

        words = (ctypes.c_short * 5).from_buffer(out.u)
        for i in range(_WORDS_PER_CALL):
            slot_addr = addr + i * 2
            if slot_addr > chunk_end:
                break
            v = int(words[i])
            if v == head or v == next_t:
                tag = "head" if v == head else "next"
                print(f"  {name}{slot_addr:<5}: word={v:>6}  <== matches {tag}")
                hits.append((type_a, name, slot_addr, v))
        addr = chunk_end + 1

    if err_count > 3:
        print(f"  ... ({err_count} total error chunks)")
    print(f"  hits in {name}: {len(hits)}")
    print()
    return hits


def _find_pairs(
    hits: list[tuple[int, str, int, int]],
    head: int,
    next_t: int,
) -> list[tuple[str, int, int]]:
    """Find (area, head_addr, next_addr) where the two values sit within
    8 bytes of each other in the same area — strong signal for the OEM's
    head/next pair."""
    pairs: list[tuple[str, int, int]] = []
    by_area: dict[str, list[tuple[int, int]]] = {}
    for _ta, name, addr, v in hits:
        by_area.setdefault(name, []).append((addr, v))
    for name, items in by_area.items():
        heads = [a for a, v in items if v == head]
        nexts = [a for a, v in items if v == next_t]
        for ha in heads:
            for na in nexts:
                if 0 < abs(na - ha) <= 8:
                    pairs.append((name, ha, na))
    return pairs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=10)
    p.add_argument("--head", type=int, required=True)
    p.add_argument("--next", dest="next_t", type=int, required=True)
    p.add_argument(
        "--areas",
        default="R,D,F",
        help="comma-separated PMC area names to sweep (default: R,D,F)",
    )
    args = p.parse_args(argv)

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    wanted_names = [n.strip().upper() for n in args.areas.split(",")]
    name_to_ta = {v: k for k, v in _PMC_AREAS.items()}

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        print(f"target: {args.ip}:{args.port}")
        print(f"looking for: head={args.head}, next={args.next_t}")
        print(f"areas: {wanted_names}")
        print()

        populated = _enumerate_pmc(fc)
        # Dedup and intersect with requested area names.
        sweep_targets: list[tuple[int, str, int, int]] = []
        seen: set[int] = set()
        for ta, name, top, last in populated:
            if name in wanted_names and ta not in seen:
                sweep_targets.append((ta, name, top, last))
                seen.add(ta)
        # Also add any requested area not in populated list (use defaults).
        for n in wanted_names:
            if n not in {name for _, name, _, _ in sweep_targets} and n in name_to_ta:
                ta = name_to_ta[n]
                # Conservative default range.
                sweep_targets.append((ta, n, 0, 1999))

        all_hits: list[tuple[int, str, int, int]] = []
        for ta, name, top, last in sweep_targets:
            all_hits += _sweep_area_words(fc, ta, name, top, last, args.head, args.next_t)

        pairs = _find_pairs(all_hits, args.head, args.next_t)

        print("=" * 60)
        print(f"total hits: {len(all_hits)}")
        print(f"adjacent (head,next) pairs (within 8 bytes): {len(pairs)}")
        for name, ha, na in pairs:
            print(f"  {name}{ha} = {args.head}  +  {name}{na} = {args.next_t}  (delta={na - ha})")

        if pairs:
            print()
            print(
                "STRONG SIGNAL — change the panel head/next, re-run, and confirm "
                "the pair tracks. If yes, that's the O1 binding. We'll add a "
                "read_active_tool() helper in client.py that reads exactly "
                f"{pairs[0][0]}{pairs[0][1]} and {pairs[0][0]}{pairs[0][2]}."
            )
            return 0
        if all_hits:
            print()
            print(
                "Hits exist but no adjacent pair. Either head/next live in "
                "different blocks, or the values 45/83 also appear elsewhere "
                "as coincidence. Change the panel tool and re-run — only the "
                "real slot will track the new value."
            )
            return 0
        print()
        print(
            "NO HITS. Try byte mode (--areas R --bytes), or expand to E,K. "
            "If still nothing, ask the OEM for the Mighty Viper PMC ladder "
            "address map."
        )
        return 1
    finally:
        fc.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
