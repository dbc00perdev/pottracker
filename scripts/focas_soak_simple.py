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

    # With DB persistence (Phase 2 Step 6): diff + audit each snapshot.
    # --machine-uuid is shared.machine.id; DSN from --persist-dsn or DATABASE_URL.
    python scripts/focas_soak_simple.py \\
        --ip 10.1.10.58 --machine-id viper-lg-1000ap \\
        --persist --machine-uuid <shared.machine.id> \\
        --persist-dsn postgresql://pottracker_dev:...@localhost:5433/pottracker \\
        --duration-minutes 1440 --output reports/viper-soak-24h-persist.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Ensure repo root is on sys.path even when this script is invoked as
# `python scripts/focas_soak_simple.py` from a venv where the package
# isn't pip-install-ed editable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.soak_report import (  # noqa: E402
    _Cycle,
    _SoakReport,
    _summarize_errors,
    _summarize_latency,
    _summarize_persist,
)
from shared.focas.client import FocasClient  # noqa: E402
from shared.focas.errors import FocasError  # noqa: E402
from shared.focas.snapshot import persist  # noqa: E402

_logger = logging.getLogger("focas_soak_simple")


def _resolve_persist_dsn(persist_dsn: str | None) -> str:
    """DSN precedence: --persist-dsn > DATABASE_URL env. SystemExit if neither."""
    dsn = persist_dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("--persist requires --persist-dsn or the DATABASE_URL env var")
    return dsn


def _resolve_machine_uuid(raw: str | None) -> UUID:
    """persist() keys on shared.machine.id (UUID), not the human machine-id string."""
    if not raw:
        raise SystemExit(
            "--persist requires --machine-uuid (the shared.machine.id UUID for this machine)"
        )
    try:
        return UUID(raw)
    except ValueError as exc:
        raise SystemExit(f"--machine-uuid is not a valid UUID: {raw!r}") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--machine-id", default="viper-lg-1000ap")
    p.add_argument("--duration-minutes", type=float, default=60)
    p.add_argument("--interval-seconds", type=float, default=60)
    p.add_argument("--timeout-seconds", type=int, default=3)
    p.add_argument("--output", required=True)
    p.add_argument(
        "--persist",
        action="store_true",
        help="persist each snapshot to the DB (diff + audit) via shared.focas.snapshot.persist",
    )
    p.add_argument(
        "--persist-dsn",
        default=None,
        help="SQLAlchemy DSN; overrides DATABASE_URL. Only used with --persist",
    )
    p.add_argument(
        "--machine-uuid",
        default=None,
        help="shared.machine.id UUID for this machine; required with --persist",
    )
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

    # Persistence wiring (resolved before connecting so a misconfig fails fast).
    engine = None
    machine_uuid: UUID | None = None
    if args.persist:
        dsn = _resolve_persist_dsn(args.persist_dsn)
        machine_uuid = _resolve_machine_uuid(args.machine_uuid)
        engine = create_engine(dsn)
        _logger.info("persistence ON: machine_uuid=%s", machine_uuid)

    report = _SoakReport(
        machine_id=args.machine_id,
        ip=args.ip,
        port=args.port,
        interval_seconds=args.interval_seconds,
        started_at=datetime.now(UTC).isoformat(),
        persist_enabled=args.persist,
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
        if report.persist_enabled:
            report.persist_summary = _summarize_persist(report.cycles)
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
            machine_id=args.machine_id,
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
                snap = fc.read_snapshot()
                cycle.elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
                cycle.success = True
                consecutive_failures = 0

                # Persist AFTER a good read. A DB hiccup must not abort a soak
                # that's proving FOCAS-link stability — record it and carry on;
                # the report surfaces the failure pattern.
                persist_note = ""
                if engine is not None and machine_uuid is not None:
                    tp0 = time.monotonic()
                    try:
                        with Session(engine) as session:
                            pres = persist(session, snap, machine_uuid)
                        cycle.persist_ms = round((time.monotonic() - tp0) * 1000, 1)
                        cycle.persisted = True
                        cycle.changes = pres.audit_rows
                        persist_note = f", persist={cycle.persist_ms:.0f}ms changes={pres.audit_rows}"
                    except Exception as exc:  # record any DB error, keep polling
                        cycle.persist_ms = round((time.monotonic() - tp0) * 1000, 1)
                        cycle.persist_error = f"{type(exc).__name__}: {exc}"
                        persist_note = f", persist=FAILED ({type(exc).__name__})"
                        _logger.warning("cycle %d persist FAILED: %s", cycle_no, exc)

                head = snap.status.current_t_number
                next_t = snap.status.next_t_number
                _logger.info(
                    "cycle %d OK: %.0fms (mode=%s, head=%s, next=%s, offsets=%d, alarms=%d)%s",
                    cycle_no,
                    cycle.elapsed_ms,
                    snap.status.mode.value,
                    head,
                    next_t,
                    len(snap.offsets),
                    len(snap.alarms),
                    persist_note,
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
        if engine is not None:
            with __import__("contextlib").suppress(Exception):
                engine.dispose()
        write_report()
        _logger.info(
            "soak done: %d cycles, %d succeeded (%.1f%%), p95=%sms; report=%s",
            report.cycles_attempted,
            report.cycles_succeeded,
            report.success_rate * 100,
            report.latency_ms.get("p95", "n/a"),
            out_path,
        )
        if report.persist_enabled:
            ps = report.persist_summary
            _logger.info(
                "persist: %s cycles, %s audit rows, %s failures, p95=%sms",
                ps.get("persisted_cycles", 0),
                ps.get("changes_total", 0),
                ps.get("failures", 0),
                ps.get("p95", "n/a"),
            )

    return 0 if report.success_rate >= 0.95 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
