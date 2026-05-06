"""Async polling loop for one FOCAS-attached machine.

Per `docs/03-focas-integration.md`, one `Poller` runs per machine. It:

  - Opens a `SnapshotSource` (typically `FocasClient`) at startup
  - Reads a `MachineSnapshot` on a configurable cadence
  - Emits each successful snapshot via an async iterator
  - Counts consecutive failures and trips a circuit breaker
  - Reconnects on stale-handle errors (FOCAS handle invalidated by control
    reboot, network reset, etc.)
  - Releases the FOCAS handle on shutdown

Phase 1 scope: the loop, the breaker, the reconnect, the iterator, and a
`health` snapshot for monitoring. Phase 2 supplies the persistence /
diff-and-emit consumer that wraps `async for snap in poller.snapshots():`.

# Cadence

Operator-configurable per machine, default 60s. Floor is technically 1 ms
for tests; production code should set 10s minimum (CLAUDE.md polling rule).

# Circuit breaker

After N consecutive failed cycles (default 5), the poller stops calling the
control for `cooldown_seconds` (default 60s). Once the cooldown elapses, it
attempts one cycle; success resumes normal cadence, another failure restarts
the cooldown. This prevents log floods and resource waste against a powered-
down or alarmed control.

# Reconnect

The poller takes a `client_factory: Callable[[], SnapshotSource]` rather than
a pre-built source. On `FocasHandleError` (stale handle) or any error during
the source's own connect path, the poller closes the current source and
calls the factory again. Phase 6 writers use a separate, transactional
connection — they do not share the poller's source.

# Threading

`SnapshotSource.read_snapshot()` is synchronous (FOCAS is blocking ctypes).
The poller dispatches each call to a thread via `asyncio.to_thread` so the
event loop stays responsive — important when the host runs multiple
pollers (one per machine).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, Self

from .errors import FocasHandleError
from .models import MachineSnapshot

_logger = logging.getLogger("shared.focas.poller")


# ============================================================================
# Source protocol + factory type
# ============================================================================


class SnapshotSource(Protocol):
    """What the poller needs from a source. Both `FocasClient` (real) and
    test fakes implement this. The mock harness in `shared.focas.mock` is
    adapted via a small wrapper at the caller side; it isn't directly a
    SnapshotSource because its `poll()` returns a snapshot for any machine."""

    def read_snapshot(self) -> MachineSnapshot:
        """Read every per-cycle data set. Raises on FOCAS or transport error."""
        ...

    def close(self) -> None:
        """Release whatever handle the source holds. Idempotent."""
        ...


SnapshotSourceFactory = Callable[[], SnapshotSource]


# ============================================================================
# State + health
# ============================================================================


class PollerState(StrEnum):
    """Lifecycle states reported via `Poller.health`."""

    INIT = "init"  # constructed, not yet running
    HEALTHY = "healthy"  # at least one recent successful cycle
    DEGRADED = "degraded"  # consecutive failures, breaker not yet tripped
    CIRCUIT_OPEN = "circuit_open"  # breaker tripped, sleeping for cooldown
    SHUTDOWN = "shutdown"  # `stop()` called or run() exited


@dataclass(frozen=True)
class PollerHealth:
    """Snapshot of poller state for monitoring / `/health` endpoints.

    `lag_seconds` is the time since the last successful snapshot. Phase 10
    deployment alerts on `lag_seconds > 300`.
    """

    state: PollerState
    machine_id: str
    last_poll_at: datetime | None
    last_success_at: datetime | None
    consecutive_failures: int
    cycles_completed: int
    cycles_failed: int

    @property
    def lag_seconds(self) -> float | None:
        if self.last_success_at is None:
            return None
        return (datetime.now(UTC) - self.last_success_at).total_seconds()


# ============================================================================
# Poller
# ============================================================================


# Floor on `interval_seconds` — tests want sub-second cadence; production
# should set >= 10s per CLAUDE.md but we don't enforce that here so the
# poller can be exercised in unit tests.
_INTERVAL_FLOOR_SECONDS: float = 0.001


class Poller:
    """One poller per machine. Use as an async context manager:

        async def main():
            poller = Poller("viper", factory, interval_seconds=60)
            async with poller:
                async for snap in poller.snapshots():
                    await persist(snap)

    Or drive `run()` directly.
    """

    def __init__(
        self,
        machine_id: str,
        client_factory: SnapshotSourceFactory,
        interval_seconds: float = 60,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown_seconds: float = 60,
        snapshot_queue_size: int = 4,
    ) -> None:
        if not machine_id:
            raise ValueError("machine_id is required")
        if interval_seconds < _INTERVAL_FLOOR_SECONDS:
            raise ValueError(
                f"interval_seconds={interval_seconds} below floor "
                f"{_INTERVAL_FLOOR_SECONDS}; production should be >= 10"
            )
        if circuit_breaker_threshold < 1:
            raise ValueError("circuit_breaker_threshold must be >= 1")
        if circuit_breaker_cooldown_seconds < 0:
            raise ValueError("circuit_breaker_cooldown_seconds must be >= 0")
        if snapshot_queue_size < 1:
            raise ValueError("snapshot_queue_size must be >= 1")

        self._machine_id = machine_id
        self._factory = client_factory
        self._interval = interval_seconds
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown_seconds

        # Runtime state
        self._source: SnapshotSource | None = None
        self._state: PollerState = PollerState.INIT
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

        # Telemetry
        self._last_poll_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._consecutive_failures: int = 0
        self._cycles_completed: int = 0
        self._cycles_failed: int = 0

        # Snapshot fan-out queue. maxsize bounds memory; on overflow the
        # oldest snapshot is dropped (fresher data wins for a slow consumer).
        self._queue: asyncio.Queue[MachineSnapshot] = asyncio.Queue(maxsize=snapshot_queue_size)

    # --- public properties --------------------------------------------------

    @property
    def machine_id(self) -> str:
        return self._machine_id

    @property
    def state(self) -> PollerState:
        return self._state

    @property
    def health(self) -> PollerHealth:
        return PollerHealth(
            state=self._state,
            machine_id=self._machine_id,
            last_poll_at=self._last_poll_at,
            last_success_at=self._last_success_at,
            consecutive_failures=self._consecutive_failures,
            cycles_completed=self._cycles_completed,
            cycles_failed=self._cycles_failed,
        )

    # --- context manager / lifecycle ----------------------------------------

    async def __aenter__(self) -> Self:
        self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    def start(self) -> asyncio.Task[None]:
        """Schedule `run()` as a background task and return it."""
        if self._task is not None and not self._task.done():
            raise RuntimeError("Poller is already running")
        self._stop.clear()
        self._task = asyncio.create_task(self.run(), name=f"poller-{self._machine_id}")
        return self._task

    async def stop(self) -> None:
        """Signal the loop to exit and wait for it. Idempotent."""
        self._stop.set()
        if self._task is not None:
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    # --- main loop ----------------------------------------------------------

    async def run(self) -> None:
        """Polling loop. Blocks until `stop()` is called or the loop is
        cancelled. Always closes the source and sets state=SHUTDOWN on exit."""
        try:
            self._connect()
            while not self._stop.is_set():
                await self._poll_once()
                if self._stop.is_set():
                    break
                # Sleep for the configured cadence, but wake immediately on
                # stop. CIRCUIT_OPEN uses the cooldown instead of cadence.
                sleep_for = (
                    self._cb_cooldown if self._state is PollerState.CIRCUIT_OPEN else self._interval
                )
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)
        finally:
            self._disconnect()
            self._state = PollerState.SHUTDOWN

    async def _poll_once(self) -> None:
        self._last_poll_at = datetime.now(UTC)
        try:
            snap = await asyncio.to_thread(self._read_via_source)
        except FocasHandleError as exc:
            # Stale handle — reconnect on next attempt rather than counting
            # as a "real" failure, but also bump the failure counter so
            # repeated stale-handle storms eventually trip the breaker.
            _logger.warning(
                "[%s] FOCAS handle stale (%s); reconnecting",
                self._machine_id,
                exc,
            )
            self._on_failure(exc, reconnect=True)
            return
        except Exception as exc:
            self._on_failure(exc, reconnect=False)
            return
        self._on_success(snap)

    def _read_via_source(self) -> MachineSnapshot:
        """Synchronous body of one poll cycle. Runs in a worker thread.

        If the source is None (post-reconnect failure), we re-attempt the
        connection here so the loop body stays single-purpose.
        """
        if self._source is None:
            self._connect()
        assert self._source is not None
        return self._source.read_snapshot()

    # --- success / failure handlers ----------------------------------------

    def _on_success(self, snap: MachineSnapshot) -> None:
        self._cycles_completed += 1
        self._last_success_at = datetime.now(UTC)
        if self._consecutive_failures > 0 or self._state is not PollerState.HEALTHY:
            _logger.info(
                "[%s] recovered after %d failure(s); state -> HEALTHY",
                self._machine_id,
                self._consecutive_failures,
            )
        self._consecutive_failures = 0
        self._state = PollerState.HEALTHY
        # Bounded fan-out: drop oldest if a slow consumer is backed up.
        if self._queue.full():
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        with suppress(asyncio.QueueFull):
            self._queue.put_nowait(snap)

    def _on_failure(self, exc: Exception, *, reconnect: bool) -> None:
        self._cycles_failed += 1
        self._consecutive_failures += 1
        _logger.warning(
            "[%s] poll failed (%d consecutive): %s: %s",
            self._machine_id,
            self._consecutive_failures,
            type(exc).__name__,
            exc,
        )
        if reconnect:
            self._disconnect()  # next _poll_once will reconnect
        if self._consecutive_failures >= self._cb_threshold:
            if self._state is not PollerState.CIRCUIT_OPEN:
                _logger.error(
                    "[%s] circuit breaker tripped after %d failures; " "pausing for %.1fs",
                    self._machine_id,
                    self._consecutive_failures,
                    self._cb_cooldown,
                )
            self._state = PollerState.CIRCUIT_OPEN
        else:
            self._state = PollerState.DEGRADED

    # --- connection management ---------------------------------------------

    def _connect(self) -> None:
        try:
            self._source = self._factory()
        except Exception as exc:
            # Connection failure counts as a failed cycle, but doesn't
            # raise out of run() — the breaker handles persistent failures.
            _logger.warning("[%s] connect failed: %s", self._machine_id, exc)
            self._source = None
            self._on_failure(exc, reconnect=False)

    def _disconnect(self) -> None:
        if self._source is None:
            return
        with suppress(Exception):
            self._source.close()
        self._source = None

    # --- output --------------------------------------------------------------

    async def snapshots(self) -> AsyncIterator[MachineSnapshot]:
        """Yield each successful snapshot. Iteration stops when the poller
        stops; breaks on `stop()` even if the queue is empty."""
        while True:
            getter: asyncio.Task[MachineSnapshot] = asyncio.create_task(self._queue.get())
            stop_waiter: asyncio.Task[bool] = asyncio.create_task(self._stop.wait())
            done, pending = await asyncio.wait(
                {getter, stop_waiter}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
                with suppress(asyncio.CancelledError, BaseException):
                    await t
            if getter in done:
                yield getter.result()
                continue
            # stop fired before a snapshot arrived — drain anything left
            # in the queue, then exit so callers see a clean end.
            while not self._queue.empty():
                yield self._queue.get_nowait()
            return


__all__ = [
    "Poller",
    "PollerHealth",
    "PollerState",
    "SnapshotSource",
    "SnapshotSourceFactory",
]
