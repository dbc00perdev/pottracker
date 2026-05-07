"""Probe cnc_modal for the right (datano, type) selectors that return
the active T-code on this 0i-MF.

# Why this exists

Phase 1 smoke against the Lance Viper showed `cnc_modal(datano=-3, type=1)`
returns `aux_data=0` even when the panel's status bar shows T0045 is the
current tool. Either:

  - our (datano, type) constants are wrong for 0i-MF
  - T is exposed via a different mechanism (e.g., `ODBST.mstb` from
    `cnc_statinfo`, or a different FOCAS function entirely)

This script sweeps a documented range of `cnc_modal` selectors and prints
every combination that returns rc=0 with a non-zero `aux_data`. Look for
one that returns the value matching the panel's current T (e.g., 45 if
the panel shows T0045). That's the right pair for `_MODAL_T_DATANO` /
`_MODAL_T_TYPE` in `shared/focas/client.py`.

# Usage

    python scripts/probe_modal.py [--ip 10.1.10.58]

Run while a tool is loaded (panel shows T<n> in status bar). Read-only,
no machine impact, ~5 seconds wall clock.
"""

from __future__ import annotations

import argparse
import ctypes
import os

from shared.focas.client import FocasClient
from shared.focas.ctypes_defs import ODBMDL


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--datano-min", type=int, default=-20, help="lowest datano to scan")
    p.add_argument("--datano-max", type=int, default=20, help="highest datano to scan")
    p.add_argument(
        "--types",
        default="0,1,-1",
        help="comma-separated list of `type` (a.k.a. block) values to scan",
    )
    p.add_argument("--timeout-seconds", type=int, default=3, help="cnc_settimeout value")
    args = p.parse_args(argv)

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    types = [int(x) for x in args.types.split(",")]

    fc = FocasClient.connect(ip=args.ip, port=args.port, timeout_seconds=args.timeout_seconds)
    try:
        print(f"sweeping cnc_modal datano [{args.datano_min}..{args.datano_max}] x types {types}")
        print(f"target machine: {args.ip}:{args.port}")
        print()
        print(
            f"{'datano':>7} {'type':>5} | "
            f"{'rc':>3} | {'aux_data':>9} | "
            f"{'echo.datano':>11} {'echo.type':>9}"
        )
        print("-" * 70)

        hits: list[tuple[int, int, int]] = []
        attempted = 0
        ok_count = 0

        for datano in range(args.datano_min, args.datano_max + 1):
            for type_code in types:
                attempted += 1
                out = ODBMDL()
                rc = fc._lib.cnc_modal(
                    fc._handle,
                    ctypes.c_short(datano),
                    ctypes.c_short(type_code),
                    ctypes.byref(out),
                )
                aux = int(out.modal.aux.aux_data)
                if rc == 0:
                    ok_count += 1
                # Only print hits or the all-zero rows would drown the signal.
                # Print rc=0 with non-zero aux (most interesting), plus rc=0 with
                # echoed datano/type so we can see when the call succeeded but T
                # wasn't loaded there.
                marker = ""
                if rc == 0 and aux != 0:
                    marker = "  <== HIT"
                    hits.append((datano, type_code, aux))
                if rc == 0 or rc == 5:  # 5=EW_DATA, sometimes informative
                    print(
                        f"{datano:>7} {type_code:>5} | "
                        f"{rc:>3} | {aux:>9} | "
                        f"{int(out.datano):>11} {int(out.type):>9}{marker}"
                    )

        print()
        print(
            f"summary: {attempted} probes, {ok_count} returned rc=0, "
            f"{len(hits)} returned non-zero aux_data"
        )
        if hits:
            print()
            print("HITS — rc=0 with non-zero aux_data:")
            for d, t, a in hits:
                note = ""
                if a > 0 and a < 100000:
                    note = "  (plausible T number)"
                print(f"  cnc_modal(datano={d}, type={t}) -> aux_data={a}{note}")
            print()
            print(
                "If one of these matches the panel's current T (e.g., 45 when "
                "panel shows T0045), update _MODAL_T_DATANO / _MODAL_T_TYPE in "
                "shared/focas/client.py with that pair."
            )
        else:
            print()
            print(
                "NO HITS. Either no tool is currently loaded (run M6 T<n> in "
                "MDI first) or T-modal isn't exposed via cnc_modal on this "
                "control. Next probe candidates:"
            )
            print("  1. ODBST.mstb (from cnc_statinfo) — bit flags for M/S/T/B")
            print("  2. cnc_rdcommand or other read-current-block APIs")
            print("  3. Read the FANUC parameter that holds the active T")
        return 0 if hits else 1
    finally:
        fc.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
