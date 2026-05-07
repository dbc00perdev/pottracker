"""Simple sync soak — bypasses the async Poller.

# Why this exists

The async Poller (shared.focas.poller) interacts badly with our
single-threaded executor in some way I can't root-cause without
more debug time: cleanly exits run() after 2-3 cycles for no
visible reason, leaving the soak script's async-for-snapshot loop
hung. Filed as a Phase 2 task. For Phase 1 sign-off we need an
operational deliverable today, so this script does the soak the
boring sync way: one connection, one thread, a for-loop over
snapshots with sleep.

This validates the same things the async soak would (FOCAS link
stability over an hour, no memory leaks, no handle exhaustion, no
latency drift) without the asyncio plumbing.

# What it does

  1. Connects via FocasClient (which also primes with cnc_sysinfo).
  2. Loops until --duration-minutes elapses:
       a. read_snapshot()
       b. log latency + cycle number
       c. sleep --interval-seconds
  3. On any FocasError per cycle: log + record + continue (don't
     bail — we want the report to capture the failure pattern,
     not stop on first error). On 5 consecutive failures: bail
     with non-zero exit (matches Poller's circuit-breaker
     threshold).
  4. Writes a JSON report on every successful cycle (intermediate)
     so a crash mid-run doesn't lose data.
  5. Ctrl-C is honored cleanly — final report includes whatever
     ran up to the interrupt.

# Usage

    python scripts/focas_soak_simple.py \\
        --ip 10.1.10.58 \\
        --machine-id viper-lg-1000ap \\
        --output reports/viper-soak-60min.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from shared.focas.client import FocasClient
from shared.focas.errors import FocasError

_logger = logging.getLogger("focas_soak_simple")


@dataclass
class _Cycle:
    cycle: int
    started_at: str
    elapsed_ms: float
    success: bool
    error_type: str | None = None
    error_message: str | None = None


@dataclass
class _SoakReport:
    machine_id: str
    ip: str
    port: int
    interval_seconds: float
    started_at: str
    completed_at: str | None = None
    duration_seconds: float = 0.0
    cycles_attempted: int = 0
    cycles_succeeded: int = 0
    cycles_failed: int = 0
    success_rate: float = 0.0
    latency_ms: dict[str, float] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)
    cycles: list[_Cycle] = field(default_factory=list)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _summarize_latency(cycles: list[_Cycle]) -> dict[str, float]:
    successes = [c.elapsed_ms for c in cycles if c.success]
    if not successes:
        return {"count": 0}
    return {
        "count": len(successes),
        "min": round(min(successes), 1),
        "max": round(max(successes), 1),
        "mean": round(statistics.fmean(successes), 1),
        "p50": round(_percentile(successes, 50), 1),
        "p95": round(_percentile(successes, 95), 1),
        "p99": round(_percentile(successes, 99), 1),
    }


def _summarize_errors(cycles: list[_Cycle]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in cycles:
        if not c.success and c.error_type:
            counts[c.error_type] = counts.get(c.error_type, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--machine-id", default="viper-lg-1000ap")
    p.add_argument("--duration-minutes", type=float, default=60)
    p.add_argument("--interval-seconds", type=float, default=60)
    p.add_argument("--timeout-seconds", type=int, default=3)
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)

    # Force unbuffered stdout so progress lines show up live in Git Bash.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
        force=True,  # override any existing handlers
    )

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = r"C:\Fanuc\FwLib64-runtime"

    duration_seconds = args.duration_minutes * 60.0
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report = _SoakReport(
        machine_id=args.machine_id,
        ip=args.ip,
        port=args.port,
        interval_seconds=args.interval_seconds,
        started_at=datetime.now(UTC).isoformat(),
    )

    soak_start = time.monotonic()

    def write_report() -> None:
        report.completed_at = datetime.now(UTC).isoformat()
        report.duration_seconds = round(time.monotonic() - soak_start, 1)
        report.cycles_attempted = len(report.cycles)
        report.cycles_succeeded = sum(1 for c in report.cycles if c.success)
        report.cycles_failed = report.cycles_attempted - report.cycles_succeeded
        report.success_rate = (
            round(report.cycles_succeeded / report.cycles_attempted, 4)
            if report.cycles_attempted
            else 0.0
        )
        report.latency_ms = _summarize_latency(report.cycles)
        report.error_counts = _summarize_errors(report.cycles)
        out_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    _logger.info(
        "starting soak: ip=%s machine_id=%s duration=%.0fmin interval=%.0fs output=%s",
        args.ip,
        args.machine_id,
        args.duration_minutes,
        args.interval_seconds,
        out_path,
    )

    fc: FocasClient | None = None
    consecutive_failures = 0
    cycle_no = 0
    try:
        fc = FocasClient.connect(
            ip=args.ip,
            port=args.port,
            timeout_seconds=args.timeout_seconds,
        )
        _logger.info("connected; entering soak loop")

        while time.monotonic() - soak_start < duration_seconds:
            cycle_no += 1
            t0 = time.monotonic()
            cycle = _Cycle(
                cycle=cycle_no,
                started_at=datetime.now(UTC).isoformat(),
                elapsed_ms=0.0,
                success=False,
            )
            try:
                snap = fc.read_snapshot(args.machine_id)
                cycle.elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
                cycle.success = True
                consecutive_failures = 0
                head = snap.status.current_t_number
                next_t = snap.status.next_t_number
                _logger.info(
                    "cycle %d OK: %.0fms (mode=%s, head=%s, next=%s, offsets=%d, alarms=%d)",
                    cycle_no,
                    cycle.elapsed_ms,
                    snap.status.mode.value,
                    head,
                    next_t,
                    len(snap.offsets),
                    len(snap.alarms),
                )
            except FocasError as exc:
                cycle.elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
                cycle.error_type = type(exc).__name__
                cycle.error_message = str(exc)
                consecutive_failures += 1
                _logger.warning(
                    "cycle %d FAIL (consecutive=%d): %s",
                    cycle_no,
                    consecutive_failures,
                    exc,
                )
                if consecutive_failures >= 5:
                    _logger.error("5 consecutive failures; aborting soak. See report for details.")
                    report.cycles.append(cycle)
                    write_report()
                    return 2
            except Exception as exc:
                cycle.elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
                cycle.error_type = type(exc).__name__
                cycle.error_message = str(exc)
                consecutive_failures += 1
                _logger.exception("cycle %d crashed: %s", cycle_no, exc)
                if consecutive_failures >= 5:
                    report.cycles.append(cycle)
                    write_report()
                    return 2

            report.cycles.append(cycle)
            write_report()  # intermediate write every cycle

            # Sleep until next cycle, but stay responsive to Ctrl-C.
            sleep_for = max(0.0, args.interval_seconds - (time.monotonic() - t0))
            if sleep_for > 0:
                time.sleep(sleep_for)

    except KeyboardInterrupt:
        _logger.info("interrupted; writing partial report")
    finally:
        if fc is not None:
            with __import__("contextlib").suppress(Exception):
                fc.close()
        write_report()
        _logger.info(
            "soak done: %d cycles, %d succeeded (%.1f%%), p95=%sms; report=%s",
            report.cycles_attempted,
            report.cycles_succeeded,
            report.success_rate * 100,
            report.latency_ms.get("p95", "n/a"),
            out_path,
        )

    return 0 if report.success_rate >= 0.95 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
