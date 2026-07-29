"""Entrypoint for the supervised FOCAS poll service (Step-0).

Wires the portable supervisor (`shared.focas.service.FocasService`) to the real
`FocasClient` + `persist`, adds a single-instance lock, a heartbeat file, and
signal handlers, and runs forever. Intended to be launched by Windows Task
Scheduler (startup trigger + restart-on-failure) — see
`docs/runbooks/step0-poller-service.md`.

Read-only FOCAS. Writes only to `shared.focas_*` (persist). No FANUC write path.

Usage:

    .venv/Scripts/python scripts/focas_service.py \\
        --ip 10.1.10.58 --machine-id viper-lg-1000ap \\
        --machine-uuid <shared.machine.id> \\
        --dsn postgresql+psycopg://pottracker_dev:...@localhost:5433/pottracker

Stop: Ctrl+C / Ctrl+Break (graceful — releases the lock). A hard Task-Scheduler
"End task" (TerminateProcess) is also safe: the stale lockfile is reclaimed on
the next start because its PID is dead.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Repo root on sys.path even when invoked as `python scripts/focas_service.py`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.dsn_guard import assert_target_allowed  # noqa: E402
from shared.focas.client import FocasClient  # noqa: E402
from shared.focas.lathe import LatheSnapshotSource  # noqa: E402
from shared.focas.models import MachineSnapshot  # noqa: E402
from shared.focas.service import (  # noqa: E402
    AlreadyRunningError,
    FocasService,
    ServiceConfig,
    SingleInstanceLock,
    write_heartbeat_file,
)
from shared.focas.snapshot import persist  # noqa: E402

_logger = logging.getLogger("focas_service")

_DEFAULT_DLL_DIR = r"C:\Fanuc\FwLib64-runtime"


def _resolve_dsn(dsn: str | None) -> str:
    resolved = dsn or os.environ.get("DATABASE_URL")
    if not resolved:
        raise SystemExit("--dsn or the DATABASE_URL env var is required")
    assert_target_allowed(resolved, action="focas service persist")
    return resolved


def _resolve_uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise SystemExit(f"--machine-uuid is not a valid UUID: {raw!r}") from exc


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--ip", default="10.1.10.58")
    p.add_argument("--port", type=int, default=8193)
    p.add_argument("--machine-id", default="viper-lg-1000ap")
    p.add_argument("--machine-uuid", required=True, help="shared.machine.id UUID")
    p.add_argument("--dsn", default=None, help="SQLAlchemy DSN; overrides DATABASE_URL")
    p.add_argument("--interval-seconds", type=float, default=60.0)
    p.add_argument("--timeout-seconds", type=int, default=3)
    p.add_argument("--breaker-threshold", type=int, default=5)
    p.add_argument("--cooldown-seconds", type=float, default=60.0)
    p.add_argument("--lock-path", default=None)
    p.add_argument("--heartbeat-path", default=None)
    p.add_argument(
        "--profile",
        choices=("mill", "lathe"),
        default="mill",
        help=(
            "read profile: 'mill' = full snapshot (offsets+pots+HEAD/NEXT+macros); "
            "'lathe' = offsets-only via the panel-locked 0i-TF banks "
            "(shared/focas/lathe.py) — no PMC reads (R20/R22)"
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Line-buffered stdout + force basicConfig, or Git Bash on Windows hides
    # every log line until ~8KB accrues (soak lesson).
    with suppress(Exception):
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
        force=True,
    )

    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = _DEFAULT_DLL_DIR

    dsn = _resolve_dsn(args.dsn)
    machine_uuid = _resolve_uuid(args.machine_uuid)
    engine = create_engine(dsn)

    reports = _REPO_ROOT / "reports"
    lock_path = Path(args.lock_path) if args.lock_path else reports / f".focas-service-{args.machine_id}.lock"
    hb_path = (
        Path(args.heartbeat_path)
        if args.heartbeat_path
        else reports / f"focas-service-{args.machine_id}.health.json"
    )

    stop = threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        _logger.info("signal %s received; requesting stop", signum)
        stop.set()

    # SIGTERM/SIGBREAK may not exist on every platform; wire whichever do.
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with suppress(ValueError, OSError):
                signal.signal(sig, _handle_signal)

    def _client_factory() -> FocasClient | LatheSnapshotSource:
        client = FocasClient.connect(
            ip=args.ip,
            port=args.port,
            timeout_seconds=args.timeout_seconds,
            machine_id=args.machine_id,
        )
        if args.profile == "lathe":
            return LatheSnapshotSource(client)
        return client

    def _persist_fn(snap: MachineSnapshot) -> int:
        with Session(engine) as session:
            return persist(session, snap, machine_uuid).audit_rows

    config = ServiceConfig(
        machine_id=args.machine_id,
        interval_seconds=args.interval_seconds,
        breaker_threshold=args.breaker_threshold,
        cooldown_seconds=args.cooldown_seconds,
    )
    service = FocasService(
        config,
        _client_factory,
        _persist_fn,
        stop=stop,
        heartbeat_fn=write_heartbeat_file(hb_path),
    )

    try:
        with SingleInstanceLock(lock_path):
            _logger.info(
                "focas-service: machine_id=%s uuid=%s ip=%s lock=%s heartbeat=%s",
                args.machine_id, machine_uuid, args.ip, lock_path, hb_path,
            )
            return service.run()
    except AlreadyRunningError as exc:
        _logger.error("%s", exc)
        return 3
    finally:
        with suppress(Exception):
            engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
