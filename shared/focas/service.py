"""Supervised, self-healing FOCAS poll service (Step-0).

Productionizes the proven sync soak loop (`scripts/focas_soak_simple.py`) into a
process that reads one machine and persists every cycle **forever**, reconnecting
instead of exiting on FOCAS failure. This is the R2 deploy shape and the fix for
the "Unreachable · polled Nm ago" fossil: the API infers `connected` purely from
mirror freshness (`machines.focas_state`), so a process that keeps `persist()`
alive is the entire fix — no API/UI/schema change.

Design (see `tasks/spec-step0-poller.md`):

  - Sync + single-threaded. FOCAS handles are thread-affined; a plain sync loop
    is inherently one thread, sidestepping the async poller's executor concerns.
  - Never exits on FOCAS failure. Read errors count toward a circuit breaker;
    at the threshold the handle is closed and, after a cooldown, a FRESH handle
    is opened (stale-handle / control-reboot recovery, R19). A stale-handle error
    reconnects immediately. A DB (persist) error is recorded but does NOT trip
    the FOCAS breaker — a DB hiccup is not FOCAS being down.
  - Exits only on `stop` (clean, for Task Scheduler "End task") or an unexpected
    crash (non-zero → Task Scheduler restart-on-failure).

This module is pure/portable (no DLLs, no argparse, no msvcrt) so it is unit-
tested on Linux CI with a fake client + fake persist + injected clock/sleep.
The Windows entrypoint that wires the real `FocasClient` + `persist` +
signal handlers lives in `scripts/focas_service.py`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from .errors import FocasError, FocasHandleError
from .models import MachineSnapshot
from .poller import SnapshotSource

_logger = logging.getLogger("shared.focas.service")

# Defaults mirror the async poller's breaker + the CLAUDE.md polling rule.
DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_BREAKER_THRESHOLD = 5
DEFAULT_COOLDOWN_SECONDS = 60.0
DEFAULT_CONNECT_BACKOFF_SECONDS = 10.0
DEFAULT_CONNECT_BACKOFF_MAX_SECONDS = 60.0
_SLEEP_CHUNK_SECONDS = 1.0  # granularity for interruptible sleep (SIGTERM latency)


class ServiceState(StrEnum):
    """Reported in the heartbeat for ops/watchdog visibility."""

    CONNECTING = "connecting"  # no live handle; (re)connecting with backoff
    HEALTHY = "healthy"  # last cycle read + (attempted) persist OK
    DEGRADED = "degraded"  # read failures accruing, breaker not yet tripped
    CIRCUIT_OPEN = "circuit_open"  # breaker tripped, cooling down before reconnect
    STOPPED = "stopped"  # stop requested, loop exited cleanly


# Injected dependency aliases (kept simple so the supervisor stays DB-agnostic).
ClientFactory = Callable[[], SnapshotSource]
# Persist a snapshot; return the number of audit rows written. Raise on DB error.
PersistFn = Callable[[MachineSnapshot], int]
HeartbeatFn = Callable[["Heartbeat"], None]


@dataclass
class ServiceConfig:
    machine_id: str  # human id; used for logging / lock / heartbeat filenames
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    breaker_threshold: int = DEFAULT_BREAKER_THRESHOLD
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    connect_backoff_seconds: float = DEFAULT_CONNECT_BACKOFF_SECONDS
    connect_backoff_max_seconds: float = DEFAULT_CONNECT_BACKOFF_MAX_SECONDS


@dataclass
class Heartbeat:
    """Written out each cycle/state-change for humans + the optional watchdog.

    The UI's freshness comes from the DB mirror, NOT this file — this is ops
    telemetry only.
    """

    pid: int
    machine_id: str
    state: ServiceState
    started_at: str
    last_cycle_at: str | None = None
    last_success_at: str | None = None
    last_cycle_seconds: float | None = None  # observed read+persist time; sets real cadence
    consecutive_failures: int = 0
    cycles_ok: int = 0
    cycles_failed: int = 0
    connect_failures: int = 0

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


# ============================================================================
# Single-instance lock (PID file + liveness) — portable, importable on Linux CI
# ============================================================================


class AlreadyRunningError(RuntimeError):
    """Another live service already holds the lock for this machine."""


def _pid_alive(pid: int) -> bool:
    """True if a process with `pid` currently exists. Portable across OSes."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # type: ignore[attr-defined]
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


@dataclass
class SingleInstanceLock:
    """PID lockfile guarding one machine's poll loop against a second instance.

    Refuses to start if the lockfile names a LIVE pid; a stale file (dead pid)
    is reclaimed. Removed on clean exit. Not race-free under simultaneous
    starts, but Task Scheduler starts one instance — this catches the real case
    (a manual run overlapping the scheduled one).
    """

    path: Path
    _acquired: bool = field(default=False, init=False)

    def acquire(self) -> None:
        if self.path.exists():
            existing = self._read_pid()
            if existing is not None and existing != os.getpid() and _pid_alive(existing):
                raise AlreadyRunningError(
                    f"service already running for this machine (pid {existing}, "
                    f"lock {self.path}); refusing to start a second instance"
                )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        self._acquired = True

    def release(self) -> None:
        if not self._acquired:
            return
        with suppress(Exception):
            if self._read_pid() == os.getpid():
                self.path.unlink(missing_ok=True)
        self._acquired = False

    def _read_pid(self) -> int | None:
        try:
            return int(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def __enter__(self) -> SingleInstanceLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def write_heartbeat_file(path: Path) -> HeartbeatFn:
    """Return a HeartbeatFn that atomically writes `hb` as JSON to `path`."""

    def _write(hb: Heartbeat) -> None:
        with suppress(Exception):  # heartbeat is best-effort telemetry
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(hb.to_dict(), indent=2), encoding="utf-8")
            tmp.replace(path)

    return _write


# ============================================================================
# The supervisor
# ============================================================================


class FocasService:
    """Forever-running, self-healing poll loop for one machine.

    Time (`sleep`, `monotonic`, `now`) is injected so unit tests drive the loop
    deterministically without real waits.
    """

    def __init__(
        self,
        config: ServiceConfig,
        client_factory: ClientFactory,
        persist_fn: PersistFn,
        *,
        stop: threading.Event,
        heartbeat_fn: HeartbeatFn | None = None,
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        import time

        self._cfg = config
        self._factory = client_factory
        self._persist = persist_fn
        self._stop = stop
        self._heartbeat_fn = heartbeat_fn or (lambda hb: None)
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._now = now or (lambda: datetime.now(UTC))

        self._source: SnapshotSource | None = None
        self._state = ServiceState.CONNECTING
        self._consecutive = 0
        self._connect_failures = 0
        self._slow_cycle_warned = False
        self._hb = Heartbeat(
            pid=os.getpid(),
            machine_id=config.machine_id,
            state=ServiceState.CONNECTING,
            started_at=self._now().isoformat(),
        )

    # -- public ------------------------------------------------------------

    def run(self) -> int:
        """Poll until `stop` is set. Returns 0 on clean shutdown."""
        _logger.info(
            "focas-service starting: machine_id=%s interval=%.0fs breaker=%d cooldown=%.0fs",
            self._cfg.machine_id,
            self._cfg.interval_seconds,
            self._cfg.breaker_threshold,
            self._cfg.cooldown_seconds,
        )
        try:
            while not self._stop.is_set():
                if self._source is None:
                    if not self._connect():
                        continue  # connect failed; backed off, retry
                self._run_cycle()
        finally:
            self._close_source()
            self._set_state(ServiceState.STOPPED)
            self._emit_heartbeat()
            _logger.info(
                "focas-service stopped: %d ok / %d failed cycles",
                self._hb.cycles_ok,
                self._hb.cycles_failed,
            )
        return 0

    # -- internals ---------------------------------------------------------

    def _connect(self) -> bool:
        """Open a fresh source. On failure, back off (interruptibly) and return
        False so the caller retries. Never raises — a powered-off machine is a
        normal state, not a crash."""
        self._set_state(ServiceState.CONNECTING)
        self._emit_heartbeat()
        try:
            self._source = self._factory()
        except Exception as exc:  # connect/DLL/socket — stay alive, retry
            self._connect_failures += 1
            self._hb.connect_failures = self._connect_failures
            backoff = min(
                self._cfg.connect_backoff_max_seconds,
                self._cfg.connect_backoff_seconds * self._connect_failures,
            )
            _logger.warning(
                "connect failed (attempt %d): %s; retrying in %.0fs",
                self._connect_failures,
                exc,
                backoff,
            )
            self._sleep_interruptible(backoff)
            return False
        self._connect_failures = 0
        self._hb.connect_failures = 0
        self._consecutive = 0
        self._set_state(ServiceState.HEALTHY)
        _logger.info("connected; polling machine_id=%s", self._cfg.machine_id)
        return True

    def _run_cycle(self) -> None:
        assert self._source is not None
        cycle_start = self._monotonic()
        try:
            snap = self._source.read_snapshot()
        except FocasHandleError as exc:
            # Stale handle (control reboot / network reset): reconnect at once.
            self._consecutive += 1
            _logger.warning("stale FOCAS handle: %s; reconnecting", exc)
            self._close_source()
            self._on_read_failure()
            return
        except FocasError as exc:
            self._consecutive += 1
            _logger.warning(
                "read failed (consecutive=%d/%d): %s",
                self._consecutive,
                self._cfg.breaker_threshold,
                exc,
            )
            self._on_read_failure()
            if self._consecutive < self._cfg.breaker_threshold:
                self._sleep_remaining(cycle_start)
            return

        # Read OK.
        self._consecutive = 0
        self._hb.cycles_ok += 1
        self._hb.last_success_at = self._now().isoformat()
        changes = self._do_persist(snap)
        cycle_s = self._monotonic() - cycle_start
        self._hb.last_cycle_seconds = round(cycle_s, 1)
        self._hb.last_cycle_at = self._now().isoformat()
        self._set_state(ServiceState.HEALTHY)
        self._emit_heartbeat()
        self._warn_if_slow(cycle_s)
        _logger.info(
            "cycle OK: %.0fms head=%s next=%s offsets=%d%s",
            cycle_s * 1000,
            snap.status.current_t_number,
            snap.status.next_t_number,
            len(snap.offsets),
            "" if changes is None else f" changes={changes}",
        )
        self._sleep_remaining(cycle_start)

    def _warn_if_slow(self, cycle_s: float) -> None:
        """Warn (once, until it recovers) when a cycle takes longer than the
        configured interval: the effective cadence is then the cycle time, and if
        `shared.machine.poll_interval_seconds` (the API freshness basis) is set
        below it, a healthy machine flaps 'Unreachable' between polls. Surfacing
        the real cycle time lets ops set that column correctly (see lessons.md)."""
        if cycle_s > self._cfg.interval_seconds:
            if not self._slow_cycle_warned:
                self._slow_cycle_warned = True
                _logger.warning(
                    "measured cycle %.0fs exceeds interval %.0fs — effective cadence is "
                    "the cycle time; set shared.machine.poll_interval_seconds >= %.0f so "
                    "freshness does not flap 'Unreachable' (lessons.md)",
                    cycle_s, self._cfg.interval_seconds, cycle_s,
                )
        else:
            self._slow_cycle_warned = False

    def _do_persist(self, snap: MachineSnapshot) -> int | None:
        """Persist; a DB error is recorded but does NOT trip the FOCAS breaker."""
        try:
            return self._persist(snap)
        except Exception as exc:  # DB hiccup: keep polling, mirror catches up
            _logger.warning("persist failed (FOCAS link healthy): %s", exc)
            return None

    def _on_read_failure(self) -> None:
        self._hb.cycles_failed += 1
        if self._consecutive >= self._cfg.breaker_threshold:
            self._set_state(ServiceState.CIRCUIT_OPEN)
            self._emit_heartbeat()
            _logger.error(
                "circuit breaker OPEN after %d consecutive failures; "
                "closing handle, cooling down %.0fs then reconnecting",
                self._consecutive,
                self._cfg.cooldown_seconds,
            )
            self._close_source()
            self._sleep_interruptible(self._cfg.cooldown_seconds)
            self._consecutive = 0  # reconnect fresh next loop
        else:
            self._set_state(ServiceState.DEGRADED)
            self._emit_heartbeat()

    def _close_source(self) -> None:
        if self._source is not None:
            with suppress(Exception):
                self._source.close()
            self._source = None

    def _set_state(self, state: ServiceState) -> None:
        self._state = state
        self._hb.state = state
        self._hb.consecutive_failures = self._consecutive

    def _emit_heartbeat(self) -> None:
        self._hb.consecutive_failures = self._consecutive
        # Emit an immutable snapshot — `self._hb` is mutated in place, so a
        # consumer that stores the object (e.g. a state history) must not alias
        # the live one. `write_heartbeat_file` serializes immediately either way.
        with suppress(Exception):
            self._heartbeat_fn(replace(self._hb))

    def _sleep_remaining(self, cycle_start: float) -> None:
        elapsed = self._monotonic() - cycle_start
        self._sleep_interruptible(max(0.0, self._cfg.interval_seconds - elapsed))

    def _sleep_interruptible(self, seconds: float) -> None:
        """Sleep in small chunks so `stop` (SIGTERM) is honored within ~1s."""
        if seconds <= 0:
            return
        deadline = self._monotonic() + seconds
        while not self._stop.is_set():
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return
            self._sleep(min(remaining, _SLEEP_CHUNK_SECONDS))
