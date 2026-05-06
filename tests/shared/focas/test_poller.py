"""Tests for shared.focas.poller.

Driven by pytest-asyncio. A `_FakeSource` provides programmable per-call
behavior — return canned snapshots, raise typed exceptions, or do both via
a script. Cadences are sub-second so tests run fast; the poller's interval
floor is loose enough to permit this.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from shared.focas.errors import FocasError, FocasHandleError, FocasSocketError
from shared.focas.models import (
    MachineMode,
    MachineSnapshot,
    MachineStatus,
)
from shared.focas.poller import (
    Poller,
    PollerState,
    SnapshotSource,
)

# ============================================================================
# Helpers
# ============================================================================


def _snap(machine_id: str = "viper") -> MachineSnapshot:
    return MachineSnapshot(
        machine_id=machine_id,
        polled_at=datetime.now(UTC),
        status=MachineStatus(mode=MachineMode.MEM),
    )


class _FakeSource:
    """Programmable SnapshotSource. A `script` is a sequence of either
    snapshots (returned) or exceptions (raised). Cycles through the script.

    `factory_calls` records how many times the factory was invoked — used
    to assert reconnect behavior.
    """

    def __init__(self, script: Sequence[MachineSnapshot | BaseException]):
        self.script = deque(script)
        self.read_calls = 0
        self.close_calls = 0

    def read_snapshot(self) -> MachineSnapshot:
        self.read_calls += 1
        if not self.script:
            # Default to a fresh snapshot so the poller doesn't run out.
            return _snap()
        item = self.script.popleft()
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self.close_calls += 1


def _factory(*sources: _FakeSource) -> tuple[Callable[[], SnapshotSource], list[_FakeSource]]:
    """Returns (factory, list-of-issued-sources). Each call to the factory
    pops the next source from the list and records it. After the
    pre-supplied sources are exhausted, the factory raises.
    """
    issued: list[_FakeSource] = []
    queue: deque[_FakeSource] = deque(sources)

    def factory() -> SnapshotSource:
        if not queue:
            raise RuntimeError("factory exhausted")
        s = queue.popleft()
        issued.append(s)
        return s

    return factory, issued


async def _wait_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    """Spin until `predicate()` is True, then return. Test helper that
    avoids fixed sleeps."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"predicate never became true within {timeout}s")


# ============================================================================
# Construction / validation
# ============================================================================


class TestConstruction:
    def test_requires_machine_id(self):
        f, _ = _factory(_FakeSource([]))
        with pytest.raises(ValueError, match="machine_id"):
            Poller("", f)

    def test_floor_on_interval(self):
        f, _ = _factory(_FakeSource([]))
        with pytest.raises(ValueError, match="below floor"):
            Poller("m", f, interval_seconds=0.0)

    def test_threshold_must_be_positive(self):
        f, _ = _factory(_FakeSource([]))
        with pytest.raises(ValueError, match="circuit_breaker_threshold"):
            Poller("m", f, circuit_breaker_threshold=0)

    def test_init_state(self):
        f, _ = _factory(_FakeSource([]))
        p = Poller("m", f)
        assert p.state is PollerState.INIT
        h = p.health
        assert h.state is PollerState.INIT
        assert h.consecutive_failures == 0
        assert h.last_success_at is None


# ============================================================================
# Happy path
# ============================================================================


class TestHappyPath:
    async def test_emits_snapshots_in_order(self):
        a = _snap("m")
        b = _snap("m")
        source = _FakeSource([a, b])
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005)

        received: list[MachineSnapshot] = []
        async with poller:
            async for snap in poller.snapshots():
                received.append(snap)
                if len(received) >= 2:
                    break
        assert received[0] is a
        assert received[1] is b

    async def test_state_becomes_healthy_after_first_success(self):
        source = _FakeSource([_snap()])
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005)
        async with poller:
            await _wait_until(lambda: poller.state is PollerState.HEALTHY)
        assert poller.health.cycles_completed >= 1

    async def test_lag_seconds_drops_to_near_zero_on_success(self):
        source = _FakeSource([_snap()])
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005)
        async with poller:
            await _wait_until(lambda: poller.health.last_success_at is not None)
        lag = poller.health.lag_seconds
        assert lag is not None and lag < 1.0


# ============================================================================
# Failures + circuit breaker
# ============================================================================


class TestFailures:
    async def test_single_failure_marks_degraded_not_open(self):
        # threshold=3 so one failure can't trip the breaker on its own
        source = _FakeSource([FocasSocketError(code=-2, context="x")])
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005, circuit_breaker_threshold=3)
        async with poller:
            await _wait_until(lambda: poller.health.consecutive_failures >= 1)
            assert poller.state is PollerState.DEGRADED

    async def test_breaker_trips_after_threshold_failures(self):
        # 5 socket errors in a row, threshold=3 -> breaker trips after 3rd.
        errs: list[BaseException | MachineSnapshot] = [
            FocasSocketError(code=-2, context="x") for _ in range(5)
        ]
        source = _FakeSource(errs)
        factory, _ = _factory(source)
        poller = Poller(
            "m",
            factory,
            interval_seconds=0.005,
            circuit_breaker_threshold=3,
            circuit_breaker_cooldown_seconds=10,  # long enough we don't recover
        )
        async with poller:
            await _wait_until(lambda: poller.state is PollerState.CIRCUIT_OPEN)
        assert poller.health.consecutive_failures >= 3
        assert poller.health.cycles_failed >= 3
        assert poller.health.cycles_completed == 0

    async def test_breaker_resets_on_recovery(self):
        # 3 failures (threshold=3 -> trip), then the cooldown elapses, then
        # successes resume.
        script: list[BaseException | MachineSnapshot] = [
            FocasSocketError(code=-2, context="x"),
            FocasSocketError(code=-2, context="x"),
            FocasSocketError(code=-2, context="x"),
            _snap(),
            _snap(),
        ]
        source = _FakeSource(script)
        factory, _ = _factory(source)
        poller = Poller(
            "m",
            factory,
            interval_seconds=0.005,
            circuit_breaker_threshold=3,
            circuit_breaker_cooldown_seconds=0.02,
        )
        async with poller:
            await _wait_until(lambda: poller.state is PollerState.HEALTHY, timeout=2.0)
        assert poller.health.consecutive_failures == 0
        assert poller.health.cycles_completed >= 1


# ============================================================================
# Stale-handle reconnect
# ============================================================================


class TestReconnect:
    async def test_handle_error_triggers_reconnect(self):
        # First source raises FocasHandleError once, then would otherwise
        # provide snapshots. The poller closes it and asks the factory for
        # a new one. Second source returns a snapshot.
        s1 = _FakeSource([FocasHandleError(code=-8, context="x")])
        s2 = _FakeSource([_snap()])
        factory, issued = _factory(s1, s2)
        poller = Poller("m", factory, interval_seconds=0.005)
        async with poller:
            await _wait_until(lambda: poller.state is PollerState.HEALTHY, timeout=2.0)
        # First source was closed when the handle went stale.
        assert s1.close_calls >= 1
        # Both sources were issued (initial + reconnect).
        assert len(issued) == 2
        assert issued[1] is s2

    async def test_factory_failure_counts_as_cycle_failure(self):
        # One bad source that returns OK once, then a stale handle. The
        # factory has nothing more to give — it raises. The poller treats
        # this as a normal cycle failure and the breaker eventually trips.
        s1 = _FakeSource([_snap(), FocasHandleError(code=-8, context="x")])
        factory, _ = _factory(s1)  # only one source — reconnect will fail
        poller = Poller(
            "m",
            factory,
            interval_seconds=0.005,
            circuit_breaker_threshold=2,
            circuit_breaker_cooldown_seconds=10,
        )
        async with poller:
            # Wait for the breaker to trip after the reconnect attempts
            # exhaust the factory.
            await _wait_until(lambda: poller.state is PollerState.CIRCUIT_OPEN, timeout=2.0)
        # We did get one good cycle before the trouble.
        assert poller.health.cycles_completed == 1


# ============================================================================
# Stop semantics
# ============================================================================


class TestStop:
    async def test_stop_idempotent(self):
        source = _FakeSource([_snap()])
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005)
        async with poller:
            pass
        await poller.stop()  # already stopped

    async def test_state_shutdown_after_stop(self):
        source = _FakeSource([_snap()])
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005)
        async with poller:
            await _wait_until(lambda: poller.state is PollerState.HEALTHY)
        assert poller.state is PollerState.SHUTDOWN

    async def test_source_closed_on_stop(self):
        source = _FakeSource([_snap()])
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005)
        async with poller:
            await _wait_until(lambda: poller.state is PollerState.HEALTHY)
        assert source.close_calls >= 1

    async def test_cannot_start_twice(self):
        source = _FakeSource([_snap()])
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005)
        poller.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                poller.start()
        finally:
            await poller.stop()


# ============================================================================
# Snapshot iterator semantics
# ============================================================================


class TestSnapshotIterator:
    async def test_drain_remaining_on_stop(self):
        # Three snapshots queued, then stop. Iterator should yield all
        # three before terminating.
        snaps = [_snap(), _snap(), _snap()]
        source = _FakeSource(snaps)
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005, snapshot_queue_size=10)

        received: list[MachineSnapshot] = []

        async def consume() -> None:
            async for snap in poller.snapshots():
                received.append(snap)

        poller.start()
        consumer = asyncio.create_task(consume())
        # Wait for at least 3 successes.
        await _wait_until(lambda: poller.health.cycles_completed >= 3, timeout=2.0)
        await poller.stop()
        await consumer
        assert len(received) >= 3

    async def test_unexpected_exception_counts_as_failure(self):
        # Non-FocasError exception still counts; doesn't crash the loop.
        source = _FakeSource([RuntimeError("boom"), _snap()])
        factory, _ = _factory(source)
        poller = Poller("m", factory, interval_seconds=0.005, circuit_breaker_threshold=10)
        async with poller:
            await _wait_until(lambda: poller.health.cycles_completed >= 1, timeout=2.0)
        assert poller.health.cycles_failed >= 1

    async def test_focaserror_counts_as_failure(self):
        # Need >= threshold failures or _FakeSource falls back to default
        # snapshots and resets the breaker.
        source = _FakeSource(
            [
                FocasError(code=99, context="generic"),
                FocasError(code=99, context="generic"),
            ]
        )
        factory, _ = _factory(source)
        poller = Poller(
            "m",
            factory,
            interval_seconds=0.005,
            circuit_breaker_threshold=2,
            circuit_breaker_cooldown_seconds=10,
        )
        async with poller:
            await _wait_until(lambda: poller.state is PollerState.CIRCUIT_OPEN, timeout=2.0)
        assert poller.health.cycles_failed >= 2
