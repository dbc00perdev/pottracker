"""Fleet launcher (docs/10 §8.2): ONE process, one `FocasService` thread per
machine.

Gate: the fwlib multi-handle concurrency check PASSED 2026-08-06 — four
concurrent handles on four threads in one process, ~1,500 read cycles, zero
errors, zero cross-handle bleed (`reports/fwlib-concurrency-check-20260806.json`).

Shape (docs/10 §8.2, frozen 2026-07-10; built now that the fleet is 10):

  - Each machine gets its own `FocasService` on a dedicated thread — the
    service creates, uses, and closes its FOCAS handle entirely on that
    thread (the §8 thread-affinity rule holds by construction).
  - Failure isolation stays per machine: a service's breaker/backoff never
    touches its siblings; an unexpected thread death is logged and the rest
    keep polling (availability posture per dbc00per 2026-08-06: the mirror
    is bonus visibility — operability beats process-level isolation).
  - One shared stop event: SIGTERM/Ctrl-C stops every machine cleanly.
  - Per-machine `SingleInstanceLock`s still guard against a stray legacy
    one-machine poller double-polling; a lock collision SKIPS that machine
    (loudly) instead of killing the fleet.

Pure/portable like `service.py` (no DLLs, no argparse) — unit-tested on CI
with fake services. The registry-driven Windows entrypoint lives in
`scripts/focas_fleet.py`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from .service import AlreadyRunningError, FocasService, SingleInstanceLock

_logger = logging.getLogger("shared.focas.fleet")


@dataclass
class FleetUnit:
    """One machine's service + its instance lock. `thread` is set by start()."""

    machine_id: str
    service: FocasService
    lock: SingleInstanceLock
    thread: threading.Thread | None = field(default=None, init=False)
    skipped: bool = field(default=False, init=False)


class FleetService:
    """Run every unit's `FocasService.run()` on its own thread until `stop`.

    The caller owns the stop event (shared with every FocasService, so one
    signal stops the whole fleet) and decides process exit codes.
    """

    def __init__(self, units: list[FleetUnit], stop: threading.Event) -> None:
        self._units = units
        self._stop = stop

    @property
    def units(self) -> list[FleetUnit]:
        return self._units

    def start(self) -> int:
        """Acquire locks and spawn one thread per machine. Returns the number
        of machines actually started (lock collisions are skipped, not fatal
        — a legacy single-machine poller may still own that machine)."""
        started = 0
        for unit in self._units:
            try:
                unit.lock.acquire()
            except AlreadyRunningError as exc:
                unit.skipped = True
                _logger.warning(
                    "SKIPPING %s: %s (stop the legacy poller, then restart "
                    "the fleet to adopt it)", unit.machine_id, exc,
                )
                continue
            unit.thread = threading.Thread(
                target=self._run_unit, args=(unit,), name=f"focas-{unit.machine_id}",
            )
            unit.thread.start()
            started += 1
        _logger.info(
            "fleet started: %d/%d machines polling%s", started, len(self._units),
            "" if started == len(self._units) else " (see SKIPPING warnings)",
        )
        return started

    def _run_unit(self, unit: FleetUnit) -> None:
        # The FOCAS handle is created inside run() via the unit's client
        # factory — on THIS thread, satisfying handle thread-affinity.
        try:
            unit.service.run()
            _logger.info("%s: service exited cleanly", unit.machine_id)
        except Exception:
            # One machine's crash never takes down its siblings — log with
            # traceback and leave the rest of the fleet polling.
            _logger.exception("%s: service thread DIED; fleet continues", unit.machine_id)
        finally:
            unit.lock.release()

    def wait(self) -> None:
        """Block until every started thread has exited (i.e. after stop is
        set, or every service has died)."""
        for unit in self._units:
            if unit.thread is not None:
                unit.thread.join()

    def alive_count(self) -> int:
        return sum(1 for u in self._units if u.thread is not None and u.thread.is_alive())


__all__ = ["FleetService", "FleetUnit"]
