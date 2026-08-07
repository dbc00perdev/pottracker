"""Probe `cnc_upstart3`/`cnc_upload3`/`cnc_upend3` — READ-ONLY program upload.

# Why this exists

spec-offset-export.md §3 (running-program export) has a live-behavior gate:
many FANUC controls refuse to upload the foreground-executing program. This
probe observes the actual rc per control, read-only, so the export feature
can handle "busy" honestly instead of guessing. Upload moves program text
FROM the control TO this PC — nothing is sent to the machine; the write
counterpart (`cnc_download*`) is not bound anywhere in this repo.

# What it does

1. Connect, read identity (`cnc_sysinfo`) + status (`cnc_statinfo` only — no
   PMC, safe on any control class per R22).
2. Read the running program O number (`cnc_exeprgname`).
3. Attempt upload of that program (or `--onum N` override):
   `cnc_upstart3(handle, type, onum, onum)` -> loop `cnc_upload3` -> `cnc_upend3`.
   Type code 0 (NC program) is tried first; on a start reject the sweep tries
   a few candidates and records every rc (an EW_ code proves that code is
   invalid, never more — lessons.md).
4. Write `reports/upload3-probe-<ts>.json` ALWAYS (resilient-smoke rule:
   every section try/except'd, failures are data, the report survives).
   Captured program text (if any) goes to `reports/O<num>-<ip>-<ts>.nc`.

# Usage

    python scripts/probe_upload3.py --ip 10.1.10.53          # running program
    python scripts/probe_upload3.py --ip 10.1.10.53 --onum 21  # specific one
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from shared.focas.client import FocasClient, decode_status
from shared.focas.client_reads import read_program_info
from shared.focas.ctypes_defs import ODBST
from shared.focas.errors import raise_for_code

_UPLOAD_CHUNK = 1440  # bytes per cnc_upload3 call (FOCAS-typical buffer)
_MAX_BYTES = 2_000_000  # runaway cap — no sane single program exceeds this
_MAX_CALLS = 5_000
_MAX_EMPTY_RETRIES = 250  # ~5s of consecutive EW_BUFFER before giving up
_START_TYPE_CANDIDATES = (0, 1, 4)  # 0 = NC program (documented); rest = sweep


def _bind(lib: ctypes.WinDLL) -> None:
    lib.cnc_upstart3.restype = ctypes.c_short
    lib.cnc_upstart3.argtypes = [
        ctypes.c_ushort,
        ctypes.c_short,
        ctypes.c_long,
        ctypes.c_long,
    ]
    lib.cnc_upload3.restype = ctypes.c_short
    lib.cnc_upload3.argtypes = [
        ctypes.c_ushort,
        ctypes.POINTER(ctypes.c_long),
        ctypes.c_char_p,
    ]
    lib.cnc_upend3.restype = ctypes.c_short
    lib.cnc_upend3.argtypes = [ctypes.c_ushort]


def _try_upload(
    fc: FocasClient, onum: int, start_type: int, report: dict
) -> bytes | None:
    """One full upstart3 -> upload3 loop -> upend3 attempt. Returns program
    bytes on success, None otherwise; every rc lands in the report."""
    attempt: dict = {"start_type": start_type, "onum": onum}
    report["attempts"].append(attempt)
    lib = fc._lib
    rc = lib.cnc_upstart3(fc._handle, start_type, onum, onum)
    attempt["upstart3_rc"] = int(rc)
    if rc != 0:
        return None

    chunks: list[bytes] = []
    total = 0
    calls = 0
    empty_streak = 0
    buf = ctypes.create_string_buffer(_UPLOAD_CHUNK)
    try:
        while calls < _MAX_CALLS and total < _MAX_BYTES:
            calls += 1
            length = ctypes.c_long(_UPLOAD_CHUNK)
            rc = lib.cnc_upload3(fc._handle, ctypes.byref(length), buf)
            if rc == 10:  # EW_BUFFER — no data ready yet, retry (observed
                # live on VT-23B first run; -1/EW_BUSY was the wrong constant)
                empty_streak += 1
                if empty_streak > _MAX_EMPTY_RETRIES:
                    attempt["upload3_rc"] = int(rc)
                    attempt["gave_up"] = f"EW_BUFFER x{empty_streak} consecutive"
                    break
                time.sleep(0.02)
                continue
            empty_streak = 0
            if rc != 0:
                attempt["upload3_rc"] = int(rc)
                break
            got = buf.raw[: int(length.value)]
            chunks.append(got)
            total += len(got)
            if got.rstrip().endswith(b"%") and total > 1:
                attempt["upload3_rc"] = 0
                break
    finally:
        end_rc = lib.cnc_upend3(fc._handle)
        attempt["upend3_rc"] = int(end_rc)
        attempt["calls"] = calls
        attempt["bytes"] = total

    data = b"".join(chunks)
    if data.rstrip().endswith(b"%"):
        return data
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="READ-ONLY cnc_upload3 behavior probe")
    p.add_argument("--ip", required=True)
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=10)
    p.add_argument("--onum", type=int, default=None, help="program to fetch; default = the running one")
    args = p.parse_args(argv)

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report: dict = {
        "probe": "upload3",
        "ip": args.ip,
        "timestamp_utc": ts,
        "errors": [],
        "attempts": [],
    }
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"upload3-probe-{args.ip.replace('.', '-')}-{ts}.json"

    exit_code = 0
    fc: FocasClient | None = None
    try:
        try:
            fc = FocasClient.connect(
                ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds
            )
            _bind(fc._lib)
            report["identity"] = fc.read_sysinfo()
        except Exception as exc:
            report["errors"].append(f"connect: {exc!r}")
            return 2

        try:
            st = ODBST()
            rc = fc._lib.cnc_statinfo(fc._handle, ctypes.byref(st))
            raise_for_code(rc, context="cnc_statinfo")
            status = decode_status(st)
            report["status"] = {"mode": str(status.mode), "running": status.running}
        except Exception as exc:
            report["errors"].append(f"statinfo: {exc!r}")
            exit_code = 1

        onum = args.onum
        try:
            running_onum, running_name = read_program_info(fc)
            report["running_program"] = {"o_num": running_onum, "name": running_name}
            if onum is None:
                onum = running_onum
        except Exception as exc:
            report["errors"].append(f"program_info: {exc!r}")
            exit_code = 1

        if onum is None:
            report["errors"].append("no O number available (nothing running, no --onum)")
            return 1

        data: bytes | None = None
        for start_type in _START_TYPE_CANDIDATES:
            try:
                data = _try_upload(fc, onum, start_type, report)
            except Exception as exc:
                report["errors"].append(f"upload(type={start_type}): {exc!r}")
            if data is not None:
                break
            # keep sweeping only while upstart itself rejects; a mid-stream
            # failure after a successful start is a real answer, stop there
            if report["attempts"] and report["attempts"][-1].get("upstart3_rc") == 0:
                break

        if data is not None:
            nc_path = reports_dir / f"O{onum}-{args.ip.replace('.', '-')}-{ts}.nc"
            nc_path.write_bytes(data)
            report["captured"] = {"path": str(nc_path), "bytes": len(data)}
            print(f"CAPTURED O{onum}: {len(data)} bytes -> {nc_path}")
        else:
            report["captured"] = None
            print(f"NOT CAPTURED (see attempts): {report['attempts']}")
    finally:
        if fc is not None:
            try:
                fc.close()
            except Exception as exc:
                report["errors"].append(f"close: {exc!r}")
        report_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"report -> {report_path}")

    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    raise SystemExit(main())
