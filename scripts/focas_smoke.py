"""Phase 1 integration smoke test against a real FANUC control.

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
        # MockFocasSource doesn't expose sysinfo; synthesize a 0i-MF identity
        # so the R9 identity check passes.
        return {
            "addinfo": 0,
            "max_axis": 3,
            "cnc_type": "0i",
            "mt_type": "M",
            "series": "D4F1",
            "version": "15.0",
            "axes": "3",
        }

    def assert_expected_control(
        self, expected_cnc_type: str = "0i", expected_mt_type: str = "M"
    ) -> dict[str, str | int]:
        info = self.read_sysinfo()
        if info["cnc_type"] != expected_cnc_type or info["mt_type"] != expected_mt_type:
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
        "O1_current_t_via_cnc_modal": {
            "current_t_number": snap.status.current_t_number,
            "interpretation": (
                "non-None means cnc_modal(datano=-3, type=1) returned a "
                "valid T-aux modal value; verify it tracks reality by "
                "doing M6 T<n> on the control and re-running"
                if snap.status.current_t_number is not None
                else "None — either no T currently selected, or the "
                "(datano, type) constants are wrong; consult FOCAS2 manual"
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


def run_smoke(
    source: Any,
    machine_id: str,
    *,
    latency_samples: int = 10,
    expected_cnc_type: str = "0i",
    expected_mt_type: str = "M",
) -> dict[str, Any]:
    """Run the Phase 1 smoke sequence against `source` and return a
    JSON-serializable report dict. `source` is FocasClient or any object
    with the same read_* surface (see _MockSourceAdapter)."""
    started_at = datetime.now(UTC)
    report: dict[str, Any] = {
        "machine_id": machine_id,
        "started_at": started_at.isoformat(),
        "platform": sys.platform,
        "expected_cnc_type": expected_cnc_type,
        "expected_mt_type": expected_mt_type,
    }

    # 1. sysinfo + identity check
    sysinfo, sysinfo_latency = _time_call(source.read_sysinfo, n=1)
    report["sysinfo"] = sysinfo
    report["sysinfo_latency"] = sysinfo_latency
    try:
        source.assert_expected_control(
            expected_cnc_type=expected_cnc_type, expected_mt_type=expected_mt_type
        )
        identity_ok = True
        identity_error = None
    except FocasError as exc:
        identity_ok = False
        identity_error = str(exc)
    report["identity_check"] = {"passed": identity_ok, "error": identity_error}

    # 2. offset layout (resolves O2)
    (ofs_type, use_no), layout_latency = _time_call(source.read_offset_layout, n=1)
    report["offset_layout"] = {"ofs_type": ofs_type, "use_no": use_no}
    report["offset_layout_latency"] = layout_latency

    # 3. one full snapshot
    snap = source.read_snapshot(machine_id)
    report["snapshot"] = {
        "polled_at": snap.polled_at.isoformat(),
        "status": {
            "mode": snap.status.mode.value,
            "running": snap.status.running,
            "emergency_stop": snap.status.emergency_stop,
            "current_t_number": snap.status.current_t_number,
        },
        "offsets": _summarize_offsets(snap.offsets),
        "pots": {
            "count": len(snap.pots),
            "entries": [_pot_to_dict(p) for p in snap.pots],
        },
        "tool_life": {
            "count": len(snap.tool_life),
            "first_10": [_tool_life_to_dict(t) for t in snap.tool_life[:10]],
        },
        "alarms": {
            "count": len(snap.alarms),
            "entries": [_alarm_to_dict(a) for a in snap.alarms],
        },
    }

    # 4. per-call latency
    _, status_latency = _time_call(source.read_status, n=latency_samples)
    _, pots_latency = _time_call(source.read_pots, n=latency_samples)
    _, alarms_latency = _time_call(source.read_alarms, n=latency_samples)
    # Offsets are heavy (1600 calls per cycle until cnc_rdtofsr ships).
    # Sample fewer to keep runtime bounded on a real machine.
    offsets_samples = min(latency_samples, 3)
    _, offsets_latency = _time_call(source.read_offsets, n=offsets_samples)
    report["latency_per_call_ms"] = {
        "read_status": status_latency,
        "read_pots": pots_latency,
        "read_alarms": alarms_latency,
        "read_offsets": offsets_latency,
    }

    # 5. open-question verdicts
    report["open_questions"] = _interpret_open_questions(snap, ofs_type, use_no)

    # 6. timing footer
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
    parser.add_argument("--expected-cnc-type", default="0i")
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

    # Exit code reflects identity check; remaining issues live in the report.
    if not report["identity_check"]["passed"]:
        _logger.error("identity check failed; see %s", out_path)
        return 2
    _logger.info("smoke report written to %s", out_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "_MockSourceAdapter",
    "main",
    "run_smoke",
]
