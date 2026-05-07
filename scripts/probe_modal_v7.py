"""Snapshot + diff full PMC state to find the head/next tool registers.

# Why this exists

Probes v1..v6 chased specific tool-ID values across PMC areas and missed
because the machine kept changing tools mid-sweep. A snapshot/diff
strategy is robust to that: dump the full PMC state once, wait for a
tool change, dump again, then diff. Bytes that *changed* are the
candidates — head/next variables, pot table cells the indexer rotated,
plus a small amount of noise (timers, sequence counters).

We then filter the changed-byte list by "new value matches the new
panel head" or "new panel next" — that uniquely identifies the head/
next storage location regardless of byte/word/BCD encoding.

# Workflow

    # 1. Note panel state (head=X1, next=Y1) and dump.
    python scripts/probe_modal_v7.py dump --out before.json

    # 2. Wait for any tool change (or trigger one). Note new state
    #    (head=X2, next=Y2).
    python scripts/probe_modal_v7.py dump --out after.json

    # 3. Diff — pass the NEW head/next values from the panel.
    python scripts/probe_modal_v7.py diff \\
        --before before.json --after after.json \\
        --new-head X2 --new-next Y2

The diff prints every changed byte across R/D/F/K/E and highlights any
whose new value equals --new-head or --new-next, both as a raw byte
AND as a 16-bit word (in case the OEM stores tool IDs as shorts).

A single byte/word that flips exactly to the new head value IS the
head register — we then bind a `read_active_tool()` helper in
client.py that reads that one address.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

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

_DEFAULT_AREAS = ("R", "D", "F", "K", "E")
_DEFAULT_MAX: dict[str, int] = {
    "R": 1499,
    "D": 9999,
    "F": 767,
    "K": 99,
    "E": 9999,
}

_BYTES_PER_CALL = 5


class _IODBPMC(ctypes.Structure):
    _fields_ = [
        ("type_a", ctypes.c_short),
        ("type_d", ctypes.c_short),
        ("datano_s", ctypes.c_ushort),
        ("datano_e", ctypes.c_ushort),
        ("u", ctypes.c_ubyte * 40),
    ]


def _dump_area(fc: FocasClient, area: str, max_addr: int) -> bytes:
    """Read [0..max_addr] as bytes; stop on first sustained error block."""
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

    buf = bytearray()
    addr = 0
    consecutive_errors = 0
    while addr <= max_addr:
        chunk_end = min(addr + _BYTES_PER_CALL - 1, max_addr)
        out = _IODBPMC()
        rc = fn(
            fc._handle,
            ctypes.c_short(type_a),
            ctypes.c_short(0),
            ctypes.c_ushort(addr),
            ctypes.c_ushort(chunk_end),
            length,
            ctypes.byref(out),
        )
        if rc != 0:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            # Skip this chunk but keep position aligned by writing zeros.
            buf.extend(b"\x00" * (chunk_end - addr + 1))
            addr = chunk_end + 1
            continue
        consecutive_errors = 0
        for i in range(chunk_end - addr + 1):
            buf.append(int(out.u[i]))
        addr = chunk_end + 1
    return bytes(buf)


def cmd_dump(args: argparse.Namespace) -> int:
    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    areas = [a.strip().upper() for a in args.areas.split(",")]
    bad = [a for a in areas if a not in _PMC_AREAS]
    if bad:
        print(f"unknown areas: {bad}")
        return 2

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        snapshot = {
            "ts": datetime.now(UTC).isoformat(),
            "ip": args.ip,
            "port": args.port,
            "areas": {},
        }
        print(f"target: {args.ip}:{args.port}")
        print(f"dumping areas: {areas}")
        t0 = time.time()
        for area in areas:
            max_addr = _DEFAULT_MAX.get(area, 999)
            print(f"  {area}: 0..{max_addr} ...", end="", flush=True)
            t1 = time.time()
            data = _dump_area(fc, area, max_addr)
            elapsed = time.time() - t1
            print(f" {len(data)} bytes ({elapsed:.1f}s)")
            snapshot["areas"][area] = {
                "top": 0,
                "last": len(data) - 1,
                "hex": data.hex(),
            }
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        total = time.time() - t0
        total_bytes = sum(len(bytes.fromhex(a["hex"])) for a in snapshot["areas"].values())
        print(f"wrote {out_path} ({total_bytes} bytes total, {total:.1f}s)")
        return 0
    finally:
        fc.close()


def cmd_diff(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))

    print(f"before: {before['ts']}  ({before.get('ip', '?')})")
    print(f"after:  {after['ts']}  ({after.get('ip', '?')})")
    print(f"looking for new head={args.new_head}, new next={args.new_next}")
    print()

    new_head = int(args.new_head)
    new_next = int(args.new_next)

    head_byte_hits: list[tuple[str, int]] = []
    next_byte_hits: list[tuple[str, int]] = []
    head_word_hits: list[tuple[str, int, str]] = []  # (area, addr, "le"|"be")
    next_word_hits: list[tuple[str, int, str]] = []
    total_changes = 0

    for area in sorted(set(before["areas"]) & set(after["areas"])):
        b = bytes.fromhex(before["areas"][area]["hex"])
        a = bytes.fromhex(after["areas"][area]["hex"])
        if b == a:
            continue
        n = min(len(b), len(a))
        changes: list[tuple[int, int, int]] = []
        for i in range(n):
            if b[i] != a[i]:
                changes.append((i, b[i], a[i]))
        if not changes:
            continue
        total_changes += len(changes)
        print(f"== {area}: {len(changes)} byte(s) changed ==")
        for addr, ob, nb in changes:
            marker = ""
            if nb == new_head:
                marker = f"  <== new head ({new_head})"
                head_byte_hits.append((area, addr))
            elif nb == new_next:
                marker = f"  <== new next ({new_next})"
                next_byte_hits.append((area, addr))
            print(f"  {area}{addr:<5}: {ob:>3} -> {nb:>3}{marker}")

        # Word interpretations: at every changed address, also check whether
        # the 2-byte word starting there equals new_head/new_next in either
        # endianness. Catches cases where head is stored as a short.
        for addr, _ob, _nb in changes:
            if addr + 1 >= len(a):
                continue
            le = a[addr] | (a[addr + 1] << 8)
            be = (a[addr] << 8) | a[addr + 1]
            if le == new_head or be == new_head:
                endian = "le" if le == new_head else "be"
                head_word_hits.append((area, addr, endian))
                print(f"  {area}{addr:<5}: word ({endian}) = {new_head}  <== new head as word")
            if le == new_next or be == new_next:
                endian = "le" if le == new_next else "be"
                next_word_hits.append((area, addr, endian))
                print(f"  {area}{addr:<5}: word ({endian}) = {new_next}  <== new next as word")
        print()

    print("=" * 60)
    print(f"total changed bytes: {total_changes}")
    print(f"new-head byte matches: {head_byte_hits}")
    print(f"new-next byte matches: {next_byte_hits}")
    print(f"new-head word matches: {head_word_hits}")
    print(f"new-next word matches: {next_word_hits}")
    print()

    candidates = head_byte_hits + [(a, addr) for a, addr, _ in head_word_hits]
    if len(candidates) == 1:
        area, addr = candidates[0]
        print(
            f"STRONG SIGNAL: {area}{addr} is the head register. "
            "Take a third snapshot after another tool change and re-diff to "
            "confirm — the same address should flip to the newest panel head."
        )
        return 0
    if len(candidates) > 1:
        print(
            "MULTIPLE candidates — change tools again and diff a third "
            "snapshot. The byte that consistently flips to the panel's "
            "current head is the head register; the rest are pot-table "
            "cells where the head value happens to also live."
        )
        return 0
    print(
        "NO new-head match in changed bytes. Possibilities: "
        "(1) head/next stored in an area we didn't sweep — try --areas with "
        "T,C,A,M,N,Z; (2) stored BCD-encoded — head=45 -> 0x45 = byte 69, "
        "so look for 69 in the byte changes; (3) machine state didn't "
        "actually advance between snapshots."
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("dump", help="snapshot full PMC state to JSON")
    pd.add_argument("--ip", default="10.1.10.58")
    pd.add_argument("--port", type=int, default=8193)
    pd.add_argument("--timeout-seconds", type=int, default=15)
    pd.add_argument("--areas", default=",".join(_DEFAULT_AREAS))
    pd.add_argument("--out", required=True, help="output JSON path")
    pd.set_defaults(func=cmd_dump)

    pf = sub.add_parser("diff", help="diff two PMC snapshots, filter by new panel state")
    pf.add_argument("--before", required=True)
    pf.add_argument("--after", required=True)
    pf.add_argument("--new-head", type=int, required=True, help="panel head AFTER the change")
    pf.add_argument("--new-next", type=int, required=True, help="panel next AFTER the change")
    pf.set_defaults(func=cmd_diff)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
