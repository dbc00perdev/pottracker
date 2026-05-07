"""One-shot FOCAS call diagnostic — figures out which calls work right now.

# Why this exists

Soak failed with rc=-8 on cnc_statinfo while the smoke 25 minutes
earlier had cnc_statinfo working. Priming with cnc_sysinfo at connect
time did not fix it. We don't know which other calls fail or whether
this is cnc_statinfo-specific. This script connects ONCE and runs
every FOCAS call we use in Phase 1 in sequence, logging rc per call.

# Usage

    python scripts/focas_diag.py --ip 10.1.10.58

Output: one line per call with rc + a short hint. Run while the
soak is failing to capture a coherent snapshot of what works /
doesn't.

# What we're looking for

  - If only cnc_statinfo fails: cnc_statinfo-specific issue (struct
    size, multi-path, mode-gated).
  - If multiple NC reads fail but PMC works: NC daemon in a weird
    state (alarm?, emergency-stop?, no-program-loaded gate).
  - If everything fails: connection itself is broken; reconnect
    might help.
"""

from __future__ import annotations

import argparse
import ctypes
import os

from shared.focas.client import (
    FocasClient,
    decode_offset_layout,
    decode_status,
    decode_sysinfo,
)
from shared.focas.ctypes_defs import (
    IODBPMC,
    ODBALMMSG2,
    ODBMDL,
    ODBST,
    ODBST2,
    ODBSYS,
    ODBSYSEX,
    ODBTLINF,
)


def _label(rc: int) -> str:
    if rc == 0:
        return "OK"
    if rc == -8:
        return "FAIL (-8 = the bug we're chasing)"
    if rc == -15:
        return "FAIL (-15 EW_NODLL)"
    if rc == 4:
        return "FAIL (4 EW_ATTRIB)"
    if rc == 5:
        return "FAIL (5 EW_DATA)"
    if rc == 6:
        return "FAIL (6 EW_NOOPT)"
    return f"FAIL ({rc})"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--timeout-seconds", type=int, default=5)
    args = p.parse_args(argv)

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    print(f"target: {args.ip}:{args.port}")
    print()

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        # 1. cnc_sysinfo (already called by connect prime, repeat to confirm)
        out = ODBSYS()
        rc = fc._lib.cnc_sysinfo(fc._handle, ctypes.byref(out))
        info = decode_sysinfo(out) if rc == 0 else {}
        print(
            f"  cnc_sysinfo                    rc={rc:>4}  {_label(rc)}  "
            f"({info.get('cnc_type', '?')}/{info.get('mt_type', '?')}/{info.get('series', '?')})"
        )

        # 2. cnc_sysinfo_ex
        ex = ODBSYSEX()
        rc = fc._lib.cnc_sysinfo_ex(fc._handle, ctypes.byref(ex))
        print(f"  cnc_sysinfo_ex                 rc={rc:>4}  {_label(rc)}")

        # 3. cnc_statinfo
        st = ODBST()
        rc = fc._lib.cnc_statinfo(fc._handle, ctypes.byref(st))
        if rc == 0:
            status = decode_status(st)
            extra = f"(mode={status.mode.value}, run={'yes' if status.running else 'no'})"
        else:
            extra = ""
        print(f"  cnc_statinfo                   rc={rc:>4}  {_label(rc)} {extra}")

        # 4. cnc_statinfo2 (newer/longer variant)
        st2 = ODBST2()
        rc = fc._lib.cnc_statinfo2(fc._handle, ctypes.byref(st2))
        print(f"  cnc_statinfo2                  rc={rc:>4}  {_label(rc)}")

        # 5. cnc_modal (with our existing -3, 1)
        md = ODBMDL()
        rc = fc._lib.cnc_modal(
            fc._handle,
            ctypes.c_short(-3),
            ctypes.c_short(1),
            ctypes.byref(md),
        )
        print(f"  cnc_modal(-3,1)                rc={rc:>4}  {_label(rc)}")

        # 6. cnc_rdtofsinfo
        ti = ODBTLINF()
        rc = fc._lib.cnc_rdtofsinfo(fc._handle, ctypes.byref(ti))
        if rc == 0:
            ofs_type, use_no = decode_offset_layout(ti)
            extra = f"(ofs_type={ofs_type}, use_no={use_no})"
        else:
            extra = ""
        print(f"  cnc_rdtofsinfo                 rc={rc:>4}  {_label(rc)} {extra}")

        # 7. pmc_rdpmcrng R327 (PMC HEAD read — the one we know works)
        out_pmc = IODBPMC()
        rc = fc._lib.pmc_rdpmcrng(
            fc._handle,
            ctypes.c_short(5),
            ctypes.c_short(0),
            ctypes.c_ushort(327),
            ctypes.c_ushort(327),
            ctypes.c_ushort(8 + 1),
            ctypes.byref(out_pmc),
        )
        if rc == 0:
            extra = f"(R327={int(out_pmc.u.cdata[0])})"
        else:
            extra = ""
        print(f"  pmc_rdpmcrng R327              rc={rc:>4}  {_label(rc)} {extra}")

        # 8. cnc_rdalmmsg2 (alarms — useful to know if control has an active alarm)
        capacity = 8
        ArrayT = ODBALMMSG2 * capacity  # noqa: N806
        arr = ArrayT()
        count = ctypes.c_short(capacity)
        rc = fc._lib.cnc_rdalmmsg2(
            fc._handle,
            ctypes.c_short(-1),  # all alarms
            ctypes.byref(count),
            ctypes.cast(arr, ctypes.POINTER(ODBALMMSG2)),
        )
        n = int(count.value) if rc == 0 else 0
        print(f"  cnc_rdalmmsg2                  rc={rc:>4}  {_label(rc)} ({n} alarms active)")
        if rc == 0 and n > 0:
            for i in range(min(n, 5)):
                msg_bytes = bytes(arr[i].alm_msg)[: int(arr[i].msg_len)]
                msg = msg_bytes.rstrip(b"\x00 ").decode("ascii", errors="replace")
                print(f"    alarm {i}: code={int(arr[i].alm_no)} msg={msg!r}")

        return 0
    finally:
        fc.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
