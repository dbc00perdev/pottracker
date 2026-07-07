"""Read-only PMC probe to locate the pot->tool table on the Lance Viper.

FOCAS-safe: uses ONLY `pmc_rdpmcrng` (reads PMC memory). No writes, no motion —
the machine's own program causes tool changes; we just observe.

Two methods, combined:

  A. STATIC dump of the R-area, then slide a `pot_count`-wide window looking for
     a contiguous block of plausible tool numbers (0..99) that contains the tool
     currently in the spindle (head). Each such block is a candidate pot table.

  B. WATCH for a tool change (head byte R327 changes), then diff the full R-area
     before/after. The bytes that move are unambiguously ATC state; the pot cells
     that change should fall INSIDE a Method-A candidate block -> that confirms
     which block is the real pot table (and rules out coincidental look-alikes).

Known binding on this control (from O1 discovery): R327=HEAD, R325=NEXT.

    python scripts/probe_pot_table.py --ip 10.1.10.58 --watch-seconds 120 \
        --output reports/pot-probe.json
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import time
from typing import Any

from shared.focas.client import FocasClient

_PMC_DATA_BYTE = 0
_R_HEAD = 327
_R_NEXT = 325
# pmc_rdpmcrng area codes: 5 = R (internal relay), 9 = D (data table). The ATC
# head/next live in R; OEM pot tables commonly live in D — scan both.
_AREAS: list[tuple[int, str]] = [(5, "R"), (9, "D")]


class _IODBPMC(ctypes.Structure):  # noqa: N801  (ctypes struct; RUF012 waived project-wide)
    _fields_ = [
        ("type_a", ctypes.c_short),
        ("type_d", ctypes.c_short),
        ("datano_s", ctypes.c_ushort),
        ("datano_e", ctypes.c_ushort),
        ("u", ctypes.c_ubyte * 64),
    ]


def _bind(fc: FocasClient) -> Any:
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
    return fn


def _read_range(
    fn: Any, handle: int, area: int, start: int, end: int, chunk: int = 40
) -> dict[int, int | None]:
    """Read bytes [start, end] of PMC `area` into {addr: value|None}."""
    vals: dict[int, int | None] = {}
    addr = start
    while addr <= end:
        n = min(chunk, end - addr + 1)
        out = _IODBPMC()
        rc = fn(
            handle,
            ctypes.c_short(area),
            ctypes.c_short(_PMC_DATA_BYTE),
            ctypes.c_ushort(addr),
            ctypes.c_ushort(addr + n - 1),
            ctypes.c_ushort(8 + n),
            ctypes.byref(out),
        )
        for i in range(n):
            vals[addr + i] = int(out.u[i]) if rc == 0 else None
        addr += n
    return vals


def _find_candidates(
    vals: dict[int, int | None], pot_count: int, known: set[int]
) -> list[dict[str, Any]]:
    """Sliding window of `pot_count` bytes, all in 0..99, ranked by distinct
    non-zero tools and whether the window contains a known loaded tool."""
    readable = sorted(a for a, v in vals.items() if v is not None)
    if not readable:
        return []
    lo, hi = readable[0], readable[-1]
    out: list[dict[str, Any]] = []
    for start in range(lo, hi - pot_count + 2):
        window = [vals.get(start + i) for i in range(pot_count)]
        if any(v is None for v in window):
            continue
        if not all(0 <= v <= 99 for v in window):  # type: ignore[operator]
            continue
        present = {v for v in window if v}  # type: ignore[misc]
        out.append(
            {
                "start_addr": start,
                "distinct_tools": len(present),
                "contains_known": bool(present & known),
                "window": window,
            }
        )
    out.sort(key=lambda c: (c["contains_known"], c["distinct_tools"]), reverse=True)
    return out[:8]


def _stable_baseline(
    fn: Any, handle: int, area: int, start: int, end: int
) -> tuple[dict[int, int | None], list[int]]:
    """Read the range twice back-to-back; flag bytes that differ as 'scratch'
    (the ladder's transient pointers, e.g. R321) so they don't fool the diff."""
    first = _read_range(fn, handle, area, start, end)
    second = _read_range(fn, handle, area, start, end)
    scratch = [a for a in first if first[a] != second.get(a)]
    return second, scratch


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=5)
    p.add_argument("--pot-count", type=int, default=24)
    p.add_argument("--r-start", type=int, default=0)
    p.add_argument("--r-end", type=int, default=1400)
    p.add_argument("--watch-seconds", type=int, default=120)
    p.add_argument("--poll-seconds", type=float, default=2.0)
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)

    os.environ.setdefault("FOCAS_DLL_DIR", r"C:\Fanuc\FwLib64-runtime")
    report: dict[str, Any] = {"ip": args.ip, "areas": [lbl for _, lbl in _AREAS]}

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        fn = _bind(fc)

        # --- Method A: static dump of each area + candidate windows ----------
        # {label: {addr: val}} baselines and their scratch bytes.
        base: dict[str, dict[int, int | None]] = {}
        scratch: dict[str, list[int]] = {}
        cands: dict[str, list[dict[str, Any]]] = {}
        for code, lbl in _AREAS:
            b, sc = _stable_baseline(fn, fc._handle, code, args.r_start, args.r_end)
            base[lbl], scratch[lbl] = b, sc

        head = base["R"].get(_R_HEAD)
        nxt = base["R"].get(_R_NEXT)
        known = {v for v in (head, nxt) if v}
        for _, lbl in _AREAS:
            cands[lbl] = _find_candidates(base[lbl], args.pot_count, known)

        report["head_R327"], report["next_R325"] = head, nxt
        report["scratch_bytes"] = scratch
        report["candidates"] = cands

        print(f"HEAD (R327) = {head}   NEXT (R325) = {nxt}")
        print(f"\nMethod A — top candidates per area (window of {args.pot_count} bytes in 0..99):")
        for _, lbl in _AREAS:
            print(f"  [{lbl}-area] scratch={scratch[lbl]}")
            for c in cands[lbl][:4]:
                mark = " <== contains loaded tool" if c["contains_known"] else ""
                print(f"    {lbl}{c['start_addr']}..{lbl}{c['start_addr'] + args.pot_count - 1}: "
                      f"{c['distinct_tools']} distinct tools{mark}  {c['window']}")

        # --- Method B: watch head for a tool change, then diff BOTH areas ----
        print(f"\nMethod B — watching R327 for a tool change (up to {args.watch_seconds}s)…")
        print("  >>> DO ONE TOOL CHANGE NOW <<<")
        deadline = time.time() + args.watch_seconds
        changed: dict[str, dict[int, list[int | None]]] = {lbl: {} for _, lbl in _AREAS}
        caught = False
        while time.time() < deadline:
            cur_head = _read_range(fn, fc._handle, 5, _R_HEAD, _R_HEAD).get(_R_HEAD)
            if cur_head is not None and cur_head != head:
                for code, lbl in _AREAS:
                    after = _read_range(fn, fc._handle, code, args.r_start, args.r_end)
                    changed[lbl] = {
                        a: [base[lbl][a], after.get(a)]
                        for a in base[lbl]
                        if a not in scratch[lbl] and base[lbl][a] != after.get(a)
                    }
                caught = True
                print(f"  tool change: HEAD {head} -> {cur_head}")
                for _, lbl in _AREAS:
                    print(f"  [{lbl}] changed: { {f'{lbl}{a}': v for a, v in changed[lbl].items()} }")
                break
            time.sleep(args.poll_seconds)
        if not caught:
            print("  no tool change observed in the window.")

        report["change_caught"] = caught
        report["changed_bytes"] = {
            lbl: {str(a): v for a, v in changed[lbl].items()} for _, lbl in _AREAS
        }

        # Which candidate block do the changed cells land in? (per area)
        confirmed: list[dict[str, Any]] = []
        for _, lbl in _AREAS:
            for c in cands[lbl]:
                block = range(c["start_addr"], c["start_addr"] + args.pot_count)
                hits = [a for a in changed[lbl] if a in block]
                if hits:
                    confirmed.append({"area": lbl, "start_addr": c["start_addr"], "hits": hits})
        report["confirmed_blocks"] = confirmed
        if confirmed:
            best = confirmed[0]
            lbl, start = best["area"], best["start_addr"]
            mapping = {f"pot_{i + 1}": base[lbl].get(start + i) for i in range(args.pot_count)}
            report["pot_mapping_candidate"] = {"area": lbl, "start_addr": start, "map": mapping}
            print(f"\n=> CONFIRMED pot block: {lbl}{start} (changed cells: {best['hits']})")
            print(f"   Candidate pot->tool map (VERIFY against the machine):\n   {mapping}")
        elif caught:
            print("\n=> Tool change caught, but no dense candidate block moved. "
                  "Changed addresses above are the lead — may need a wider/other area.")
    finally:
        fc.close()

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nreport written to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
