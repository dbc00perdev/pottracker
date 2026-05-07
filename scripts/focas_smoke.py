"""Phase 1 integration smoke test against a real FANUC control.

**Step-by-step operator guide: `docs/runbooks/phase-1-smoke.md`.**

Connects to the named control, runs every Phase-1 FOCAS read once, and
writes a structured JSON report with:
  - connection status + latency
  - sysinfo + R9 identity check
  - offset layout (`cnc_rdtofsinfo.ofs_type` / `use_no`) — resolves O2
  - one full MachineSnapshot dumped for inspection
  - per-call latency p50 / p95 / p99 over N samples
  - open-question verdicts (O1 / O2 / O5 / O7 / O8)

Operational tool, NOT product code: lives in `scripts/`, run by hand on
the Lance dev box when the operator is at the floor with the Viper
reachable. The output JSON is the artifact attached to the Phase 1
gate sign-off.

# Usage

    # Real Viper:
    python scripts/focas_smoke.py \\
        --ip 10.1.10.58 \\
        --machine-id viper-lg-1000ap \\
        --output reports/viper-smoke-20260506-1430.json

    # Local dev (Linux): exercise the script itself against the mock harness.
    # The output report is meaningless for production but verifies the
    # script's plumbing.
    python scripts/focas_smoke.py --mock --output /tmp/mock-smoke.json

# What this is not

  - Not a production poller (use `shared.focas.poller`).
  - Not a write test (`cnc_wrtofs` is Phase 6 only).
  - Not a soak test (60-minute soak is a separate, simpler loop).
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from shared.focas.client import FocasClient
from shared.focas.errors import FocasError
from shared.focas.mock import MockFocasSource, viper_idle
from shared.focas.models import (
    AlarmEntry,
    MachineSnapshot,
    OffsetRegister,
    PotEntry,
    ToolLife,
)

_logger = logging.getLogger("focas_smoke")


# ============================================================================
# Source abstractions — the script speaks to either FocasClient or a
# MockFocasSource adapter, both presenting the same surface.
# ============================================================================


class _MockSourceAdapter:
    """Adapts `MockFocasSource` to look like the subset of FocasClient
    methods this script uses. Lets `--mock` exercise the script's plumbing
    without a Windows DLL."""

    def __init__(self, machine_id: str = "mock"):
        self._machine_id = machine_id
        self._mock = MockFocasSource(scenarios=[viper_idle()])

    def read_sysinfo(self) -> dict[str, str | int]:
        # MockFocasSource doesn't expose sysinfo; synthesize an identity
        # matching the Lance Mighty Viper LG-1000AP as observed in the
        # Phase 1 smoke (cnc_type='0' after whitespace strip, series
        # 'D4F1' for the 0i-MF model variant).
        return {
            "addinfo": 0,
            "max_axis": 3,
            "cnc_type": "0",
            "mt_type": "M",
            "series": "D4F1",
            "version": "15.0",
            "axes": "3",
        }

    def assert_expected_control(
        self,
        expected_cnc_type: str = "0",
        expected_mt_type: str = "M",
        expected_series: str | None = "D4F1",
    ) -> dict[str, str | int]:
        info = self.read_sysinfo()
        if (
            info["cnc_type"] != expected_cnc_type
            or info["mt_type"] != expected_mt_type
            or (expected_series is not None and info["series"] != expected_series)
        ):
            raise FocasError(
                code=0,
                context="assert_expected_control",
                message="mock identity mismatch",
            )
        return info

    def read_offset_layout(self) -> tuple[int, int]:
        # The mock has 24 registers per bank with no real "layout" concept;
        # synthesize a plausible response so the script can record it.
        return (1, 24)

    def read_status(self):
        return self._mock.poll().status

    def read_offsets(self):
        return self._mock.poll().offsets

    def read_pots(self):
        return self._mock.poll().pots

    def read_tool_life(self):
        return self._mock.poll().tool_life

    def read_alarms(self):
        return self._mock.poll().alarms

    def read_snapshot(self, machine_id: str) -> MachineSnapshot:
        snap = self._mock.poll()
        return snap.model_copy(update={"machine_id": machine_id})

    def close(self) -> None:
        pass


# ============================================================================
# Latency timing
# ============================================================================


def _time_call(fn: Callable[[], Any], n: int) -> tuple[Any, dict[str, float]]:
    """Run `fn()` `n` times. Return the last result + latency stats in ms."""
    samples_ms: list[float] = []
    last: Any = None
    for _ in range(n):
        start = time.perf_counter()
        last = fn()
        samples_ms.append((time.perf_counter() - start) * 1000)
    samples_ms.sort()
    return last, {
        "n": n,
        "min_ms": round(samples_ms[0], 2),
        "p50_ms": round(statistics.median(samples_ms), 2),
        "p95_ms": round(samples_ms[max(0, int(0.95 * n) - 1)], 2),
        "p99_ms": round(samples_ms[max(0, int(0.99 * n) - 1)], 2),
        "max_ms": round(samples_ms[-1], 2),
    }


# ============================================================================
# Serialization for the JSON report
# ============================================================================


def _dec(value: Decimal) -> str:
    """Decimal -> string for JSON (preserves precision; floats lose digits)."""
    return str(value)


def _offset_to_dict(o: OffsetRegister) -> dict[str, Any]:
    return {
        "register_number": o.register_number,
        "register_type": o.register_type.value,
        "value_mm": _dec(o.value_mm),
    }


def _pot_to_dict(p: PotEntry) -> dict[str, Any]:
    return {"pot_number": p.pot_number, "t_number": p.t_number}


def _tool_life_to_dict(t: ToolLife) -> dict[str, Any]:
    return {
        "t_number": t.t_number,
        "life_count": t.life_count,
        "life_max": t.life_max,
        "status": t.status.value if t.status else None,
    }


def _alarm_to_dict(a: AlarmEntry) -> dict[str, Any]:
    return {"code": a.code, "axis": a.axis, "message": a.message}


# ============================================================================
# Core flow
# ============================================================================


def _summarize_offsets(
    offsets: tuple[OffsetRegister, ...],
) -> dict[str, Any]:
    """Summarize a large offset list. Show first 5 + last 5 + a count
    breakdown by register type."""
    by_type: dict[str, int] = {}
    for o in offsets:
        by_type[o.register_type.value] = by_type.get(o.register_type.value, 0) + 1
    return {
        "count_total": len(offsets),
        "count_by_type": by_type,
        "first_5": [_offset_to_dict(o) for o in offsets[:5]],
        "last_5": [_offset_to_dict(o) for o in offsets[-5:]],
    }


def _interpret_open_questions(
    snap: MachineSnapshot,
    ofs_type: int,
    use_no: int,
) -> dict[str, Any]:
    """Translate observed values into verdicts on the Phase-1 open
    questions tracked in `tasks/spec-focas-calls.md`."""
    pot_sentinels = sorted({p.t_number for p in snap.pots if p.t_number is None})
    raw_tool_indices = sorted({p.t_number for p in snap.pots if p.t_number is not None})
    return {
        "O1_current_t_via_pmc_r327_r325": {
            "current_t_number": snap.status.current_t_number,
            "next_t_number": snap.status.next_t_number,
            "interpretation": (
                "RESOLVED — head/next live in PMC R-area on this 0i-MF + "
                "Mighty Viper random-ATC. R327=HEAD (tool in spindle), "
                "R325=NEXT (tool to be called). cnc_modal does not expose "
                "T on this control; magazine FOCAS calls (cnc_rdcurmgr "
                "etc.) are absent. None values here mean R327/R325 "
                "currently read 0 (spindle empty or no next pre-selected) "
                "or the PMC read failed — check by running "
                "scripts/probe_modal_v9.py."
            ),
        },
        "O2_offset_table_layout": {
            "ofs_type": ofs_type,
            "use_no": use_no,
            "interpretation": (
                "ofs_type selects the IODBTO union variant. Compare to the "
                "M-* members in tasks/spec-focas-calls.md and update "
                "_OFFSET_TYPE_TO_REGISTER_TYPE / cnc_rdtofsr usage in "
                "shared/focas/client.py with the verified variant name."
            ),
        },
        "O5_empty_pot_sentinel": {
            "empty_pots": len(pot_sentinels),
            "raw_tool_indices_observed": raw_tool_indices[:20],
            "interpretation": (
                "client.py treats tool_index <= 0 as empty. If raw indices "
                "include unexpected sentinels (e.g. -2 or 0xFFFF), update "
                "shared.focas.client.decode_pot."
            ),
        },
        "O7_settimeout_units": {
            "interpretation": (
                "We set 3 (seconds per FOCAS2 docs) at connect. If "
                "connection succeeded and reads are responsive, units are "
                "right. If reads stall for ~3000 seconds on a deliberate "
                "network drop, units are ms — adjust DEFAULT in "
                "FocasClient.connect."
            ),
        },
        "O8_offset_increment": {
            "current_default_mm": "0.001",
            "interpretation": (
                "client.py assumes 0.001 mm/count. To verify, read FANUC "
                "parameter 1013 (currently NOT bound; needs cnc_rdparam "
                "added to client.py). Compare reported offset values "
                "below to operator-known values on the OFFSET screen."
            ),
        },
    }


def _safe(name: str, errors: list[dict[str, str]], fn: Callable[[], Any]) -> Any:
    """Run `fn`. On exception, append a structured error to `errors` and
    return None — keeps the smoke moving so the report captures every
    section that did succeed."""
    try:
        return fn()
    except Exception as exc:
        errors.append({"section": name, "error": f"{type(exc).__name__}: {exc}"})
        _logger.warning("section %s failed: %s: %s", name, type(exc).__name__, exc)
        return None


def run_smoke(
    source: Any,
    machine_id: str,
    *,
    latency_samples: int = 10,
    expected_cnc_type: str = "0",
    expected_mt_type: str = "M",
) -> dict[str, Any]:
    """Run the Phase 1 smoke sequence against `source` and return a
    JSON-serializable report dict. `source` is FocasClient or any object
    with the same read_* surface (see _MockSourceAdapter).

    Resilient by design: each section runs in its own try/except. A
    failure in one read does NOT abort the rest — the report captures
    what succeeded plus a structured `errors` block listing what didn't.
    This is what makes the smoke useful as a diagnostic when a control
    rejects some calls (e.g., EW_NOOPT for unlicensed options) but
    answers others.
    """
    started_at = datetime.now(UTC)
    errors: list[dict[str, str]] = []
    report: dict[str, Any] = {
        "machine_id": machine_id,
        "started_at": started_at.isoformat(),
        "platform": sys.platform,
        "expected_cnc_type": expected_cnc_type,
        "expected_mt_type": expected_mt_type,
    }

    # 1. sysinfo + identity check
    sysinfo, sysinfo_latency = _time_call(
        lambda: _safe("sysinfo", errors, source.read_sysinfo) or {}, n=1
    )
    report["sysinfo"] = sysinfo
    report["sysinfo_latency"] = sysinfo_latency

    try:
        source.assert_expected_control(
            expected_cnc_type=expected_cnc_type, expected_mt_type=expected_mt_type
        )
        report["identity_check"] = {"passed": True, "error": None}
    except FocasError as exc:
        report["identity_check"] = {"passed": False, "error": str(exc)}
    except Exception as exc:
        report["identity_check"] = {
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    # 2. offset layout (resolves O2). This is the single most valuable
    # data point in the whole report — log at INFO so it's visible on
    # stderr without waiting for the file to land.
    layout = _safe("offset_layout", errors, source.read_offset_layout)
    if layout is not None:
        ofs_type, use_no = layout
        report["offset_layout"] = {"ofs_type": ofs_type, "use_no": use_no}
        _logger.info("offset_layout: ofs_type=%d use_no=%d (resolves O2)", ofs_type, use_no)
    else:
        ofs_type, use_no = None, None
        report["offset_layout"] = None

    # 3. snapshot, section by section. Each piece in its own try/except
    # so a single FOCAS-rejected call doesn't lose the rest.
    polled_at = datetime.now(UTC)
    status = _safe("status", errors, source.read_status)
    offsets = _safe("offsets", errors, source.read_offsets) or ()
    pots = _safe("pots", errors, source.read_pots) or ()
    tool_life = _safe("tool_life", errors, source.read_tool_life) or ()
    alarms = _safe("alarms", errors, source.read_alarms) or ()

    report["snapshot"] = {
        "polled_at": polled_at.isoformat(),
        "status": (
            {
                "mode": status.mode.value,
                "running": status.running,
                "emergency_stop": status.emergency_stop,
                "current_t_number": status.current_t_number,
                "next_t_number": status.next_t_number,
            }
            if status is not None
            else None
        ),
        "offsets": _summarize_offsets(offsets),
        "pots": {
            "count": len(pots),
            "entries": [_pot_to_dict(p) for p in pots],
        },
        "tool_life": {
            "count": len(tool_life),
            "first_10": [_tool_life_to_dict(t) for t in tool_life[:10]],
        },
        "alarms": {
            "count": len(alarms),
            "entries": [_alarm_to_dict(a) for a in alarms],
        },
    }

    # 4. per-call latency. Skip a category entirely if its first read
    # already failed — repeating it 10 times to confirm the failure is
    # operator time wasted.
    latency: dict[str, Any] = {}

    def _maybe_sample(name: str, fn: Callable[[], Any], n: int) -> None:
        # Only sample if the section already worked once.
        if any(e["section"] == name for e in errors):
            latency[name] = {"skipped": "section already failed; not re-sampling"}
            return
        try:
            _, lat = _time_call(fn, n=n)
            latency[name] = lat
        except Exception as exc:
            latency[name] = {"error": f"{type(exc).__name__}: {exc}"}

    _maybe_sample("status", source.read_status, latency_samples)
    _maybe_sample("pots", source.read_pots, latency_samples)
    _maybe_sample("alarms", source.read_alarms, latency_samples)
    # Offsets are heavy; cap at 3 even when latency_samples is higher.
    _maybe_sample("offsets", source.read_offsets, min(latency_samples, 3))
    report["latency_per_call_ms"] = latency

    # 5. open-question verdicts. Only meaningful if we have status +
    # offset_layout. Otherwise emit a stub explaining why.
    if status is not None and ofs_type is not None:
        from shared.focas.models import MachineSnapshot

        partial_snap = MachineSnapshot(
            machine_id=machine_id,
            polled_at=polled_at,
            status=status,
            offsets=offsets,
            pots=pots,
            tool_life=tool_life,
            alarms=alarms,
        )
        report["open_questions"] = _interpret_open_questions(partial_snap, ofs_type, use_no)
    else:
        report["open_questions"] = {
            "status": "skipped",
            "reason": (
                "status read or offset_layout failed; cannot interpret "
                "open questions without those data points. See `errors`."
            ),
        }

    # 6. footer
    report["errors"] = errors
    completed_at = datetime.now(UTC)
    report["completed_at"] = completed_at.isoformat()
    report["wall_clock_seconds"] = round((completed_at - started_at).total_seconds(), 2)
    return report


# ============================================================================
# CLI
# ============================================================================


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument(
        "--ip",
        default=None,
        help="control IP address; required unless --mock",
    )
    parser.add_argument("--port", type=int, default=8193)
    parser.add_argument("--machine-id", default="viper")
    parser.add_argument(
        "--dll-dir",
        default=None,
        help="directory containing Fwlib64.dll (default: $FOCAS_DLL_DIR)",
    )
    parser.add_argument("--timeout-seconds", type=int, default=3)
    parser.add_argument("--latency-samples", type=int, default=10)
    parser.add_argument(
        "--expected-cnc-type",
        default="0",
        help=(
            "expected ODBSYS.cnc_type value after whitespace strip "
            "(default '0' for the 0i-family Lance Viper)"
        ),
    )
    parser.add_argument("--expected-mt-type", default="M")
    parser.add_argument("--output", required=True, help="path to write JSON report")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="use shared.focas.mock instead of FocasClient (dev / Linux only)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def _open_source(args: argparse.Namespace) -> Any:
    if args.mock:
        _logger.info("opening MOCK source (--mock); not for production verification")
        return _MockSourceAdapter(machine_id=args.machine_id)
    if args.ip is None:
        raise SystemExit("--ip is required unless --mock is set")
    _logger.info("connecting to %s:%d (timeout=%ss)", args.ip, args.port, args.timeout_seconds)
    return FocasClient.connect(
        ip=args.ip,
        port=args.port,
        timeout_seconds=args.timeout_seconds,
        dll_dir=args.dll_dir,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    source = _open_source(args)
    try:
        report = run_smoke(
            source,
            machine_id=args.machine_id,
            latency_samples=args.latency_samples,
            expected_cnc_type=args.expected_cnc_type,
            expected_mt_type=args.expected_mt_type,
        )
    finally:
        try:
            source.close()
        except Exception as exc:  # pragma: no cover
            _logger.warning("source.close() raised: %s", exc)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    # Exit codes:
    #   0  — every section returned a result and identity matched
    #   1  — at least one section had errors (report still written; review it)
    #   2  — identity check failed (R9 — wrong control)
    if not report["identity_check"]["passed"]:
        _logger.error("identity check failed; see %s", out_path)
        return 2
    if report.get("errors"):
        _logger.warning(
            "smoke report written to %s WITH %d section error(s); review them",
            out_path,
            len(report["errors"]),
        )
        return 1
    _logger.info("smoke report written to %s", out_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "_MockSourceAdapter",
    "main",
    "run_smoke",
]
