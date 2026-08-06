"""Fleet entrypoint: poll EVERY enabled machine from ONE process.

Registry-driven (docs/10 §8.2): reads `shared.machine` and spawns one
`FocasService` thread per machine — no per-machine command lines, no script
edits to add a machine. Adding machine #11 = insert its row and flip
`enabled=true` (after its docs/10 §7 gates).

Read-only FOCAS. Writes only to `shared.focas_*` (persist). No FANUC write path.

Usage:

    # Everything enabled in the registry:
    .venv/Scripts/python -m scripts.focas_fleet --dsn postgresql+psycopg://...

    # Same, plus specific not-yet-enabled machines (e.g. a gate-8 soak):
    .venv/Scripts/python -m scripts.focas_fleet --also <uuid> --also <uuid>

Per-machine config comes from the row: ip/port, machine_class -> profile
(lathe -> LatheSnapshotSource), poll_interval_seconds, and
status_poll_interval_seconds (fast tier, lathe only). Locks/heartbeats land
in run/ per machine (run/<slug>.lock, run/hb-<slug>.json) plus a fleet-level
lock (run/fleet.lock). A per-machine lock collision (legacy single-machine
poller still running) skips that machine loudly; it never kills the fleet.

Stop: Ctrl+C / SIGTERM stops every machine cleanly. Intended for a single
Task Scheduler entry on the future dedicated poller PC.
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
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.focas_service import _DEFAULT_DLL_DIR, _resolve_dsn  # noqa: E402
from shared.db import machine as machine_t  # noqa: E402
from shared.focas.client import FocasClient  # noqa: E402
from shared.focas.fleet import FleetService, FleetUnit  # noqa: E402
from shared.focas.lathe import LatheSnapshotSource  # noqa: E402
from shared.focas.models import MachineSnapshot  # noqa: E402
from shared.focas.poller import SnapshotSource  # noqa: E402
from shared.focas.service import (  # noqa: E402
    FocasService,
    ServiceConfig,
    SingleInstanceLock,
    write_heartbeat_file,
)
from shared.focas.snapshot import persist  # noqa: E402

_logger = logging.getLogger("focas_fleet")


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("_", "-")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    p.add_argument("--dsn", default=None, help="DB DSN (default: $DATABASE_URL)")
    p.add_argument(
        "--also",
        action="append",
        default=[],
        metavar="UUID",
        help="poll this machine even though enabled=false (repeatable; gate-8 soaks)",
    )
    p.add_argument("--timeout-seconds", type=int, default=3)
    p.add_argument("--run-dir", default=str(_REPO_ROOT / "run"))
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    return p.parse_args(argv)


def _load_fleet_rows(session: Session, also: list[UUID]) -> list[Any]:
    cond = machine_t.c.enabled.is_(True)
    if also:
        cond = sa.or_(cond, machine_t.c.id.in_(also))
    return list(
        session.execute(
            sa.select(
                machine_t.c.id, machine_t.c.name, machine_t.c.ip_address,
                machine_t.c.focas_port, machine_t.c.machine_class,
                machine_t.c.poll_interval_seconds,
                machine_t.c.status_poll_interval_seconds,
            )
            .where(cond, machine_t.c.retired_at.is_(None))
            .order_by(machine_t.c.name)
        )
    )


def _build_unit(row: Any, engine: Any, run_dir: Path, stop: threading.Event,
                timeout_seconds: int) -> FleetUnit:
    slug = _slug(row.name)
    ip = str(row.ip_address)
    port = int(row.focas_port)
    is_lathe = row.machine_class == "lathe"
    machine_uuid = row.id

    def client_factory(
        _ip: str = ip, _port: int = port, _slug: str = slug, _lathe: bool = is_lathe
    ) -> SnapshotSource:
        client = FocasClient.connect(
            ip=_ip, port=_port, timeout_seconds=timeout_seconds, machine_id=_slug
        )
        return LatheSnapshotSource(client) if _lathe else client

    def persist_fn(snap: MachineSnapshot, _uuid: UUID = machine_uuid) -> int:
        with Session(engine) as session:
            return persist(session, snap, _uuid).audit_rows

    config = ServiceConfig(
        machine_id=slug,
        interval_seconds=float(row.poll_interval_seconds),
        status_interval_seconds=(
            float(row.status_poll_interval_seconds)
            if is_lathe and row.status_poll_interval_seconds
            else None
        ),
    )
    service = FocasService(
        config,
        client_factory,
        persist_fn,
        stop=stop,
        heartbeat_fn=write_heartbeat_file(run_dir / f"hb-{slug}.json"),
    )
    return FleetUnit(
        machine_id=slug, service=service, lock=SingleInstanceLock(run_dir / f"{slug}.lock")
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    with suppress(Exception):
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
        force=True,
    )
    if "FOCAS_DLL_DIR" not in os.environ:
        os.environ["FOCAS_DLL_DIR"] = _DEFAULT_DLL_DIR

    dsn = _resolve_dsn(args.dsn)
    engine = create_engine(dsn)
    run_dir = Path(args.run_dir)
    also = [UUID(u) for u in args.also]

    with Session(engine) as session:
        rows = _load_fleet_rows(session, also)
    if not rows:
        _logger.error("no machines to poll (none enabled, no --also); exiting")
        return 2
    for row in rows:
        _logger.info(
            "fleet member: %-24s %s:%s class=%s interval=%ss status_tier=%s",
            row.name, row.ip_address, row.focas_port, row.machine_class,
            row.poll_interval_seconds, row.status_poll_interval_seconds or "-",
        )

    stop = threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        _logger.info("signal %s received; stopping fleet", signum)
        stop.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with suppress(ValueError, OSError):
                signal.signal(sig, _handle_signal)

    fleet_lock = SingleInstanceLock(run_dir / "fleet.lock")
    fleet_lock.acquire()  # raises AlreadyRunningError if a fleet is up
    try:
        units = [
            _build_unit(row, engine, run_dir, stop, args.timeout_seconds) for row in rows
        ]
        fleet = FleetService(units, stop)
        started = fleet.start()
        if started == 0:
            _logger.error("every machine was lock-skipped; nothing to do")
            return 2
        fleet.wait()
    finally:
        fleet_lock.release()
    _logger.info("fleet stopped cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
