"""Tests for shared.focas.service — the supervised Step-0 poll loop.

CI-safe: no DLLs, no DB, no real sleeps. A `_FakeSource` scripts per-cycle
behavior; persist is a closure that sets the `stop` event after N calls to end
the otherwise-forever loop deterministically; time is injected via `_Clock`.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from shared.focas.errors import FocasConnectError, FocasError, FocasHandleError
from shared.focas.models import MachineMode, MachineSnapshot, MachineStatus
from shared.focas.service import (
    AlreadyRunningError,
    FocasService,
    Heartbeat,
    ServiceConfig,
    ServiceState,
    SingleInstanceLock,
    _pid_alive,
    write_heartbeat_file,
)

# ============================================================================
# Helpers
# ============================================================================


def _snap(head: int | None = 25, next_t: int | None = 18) -> MachineSnapshot:
    return MachineSnapshot(
        machine_id="viper",
        polled_at=datetime.now(UTC),
        status=MachineStatus(
            mode=MachineMode.MEM, current_t_number=head, next_t_number=next_t
        ),
    )


class _FakeSource:
    """Scripted SnapshotSource: each read returns a snapshot or raises.

    Optionally advances `clock` by `read_cost` seconds per read to simulate a
    slow snapshot (the ~36s Viper full sweep)."""

    def __init__(
        self,
        script: Sequence[MachineSnapshot | BaseException],
        clock: _Clock | None = None,
        read_cost: float = 0.0,
    ):
        self.script = deque(script)
        self.read_calls = 0
        self.close_calls = 0
        self._clock = clock
        self._read_cost = read_cost

    def read_snapshot(self) -> MachineSnapshot:
        self.read_calls += 1
        if self._clock is not None and self._read_cost:
            self._clock.t += self._read_cost
        if not self.script:
            return _snap()
        item = self.script.popleft()
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self.close_calls += 1


def _factory(*items: _FakeSource | BaseException):
    """Return (factory, issued). The factory yields each item in order; an
    exception item is raised (a connect failure). Records issued sources."""
    pending = deque(items)
    issued: list[_FakeSource] = []

    def make():
        if not pending:
            raise FocasConnectError(-16, "connect", "no more sources")
        nxt = pending.popleft()
        if isinstance(nxt, BaseException):
            raise nxt
        issued.append(nxt)
        return nxt

    return make, issued


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _cfg(**kw) -> ServiceConfig:
    base = dict(
        machine_id="viper",
        interval_seconds=0.0,
        cooldown_seconds=0.0,
        connect_backoff_seconds=0.0,
        connect_backoff_max_seconds=0.0,
        breaker_threshold=5,
    )
    base.update(kw)
    return ServiceConfig(**base)  # type: ignore[arg-type]


def _persist_stopping(stop: threading.Event, after: int, *, raise_until: int = 0):
    """persist_fn that raises for the first `raise_until` calls, then returns 0;
    sets `stop` once `after` calls have happened."""
    state = {"calls": 0}

    def _p(_snapshot: MachineSnapshot) -> int:
        state["calls"] += 1
        n = state["calls"]
        if n >= after:
            stop.set()
        if n <= raise_until:
            raise RuntimeError(f"db down (call {n})")
        return 0

    _p.state = state  # type: ignore[attr-defined]
    return _p


def _run(service: FocasService, clock: _Clock, stop: threading.Event, hbs: list[Heartbeat]):
    # Safety valve so a logic bug can't hang the suite forever.
    guard = {"n": 0}
    real_sleep = clock.sleep

    def _guarded_sleep(s: float) -> None:
        guard["n"] += 1
        if guard["n"] > 100_000:  # pragma: no cover
            stop.set()
        real_sleep(s)

    clock.sleep = _guarded_sleep  # type: ignore[assignment]
    return service.run()


# ============================================================================
# Tests
# ============================================================================


def test_happy_path_persists_each_cycle() -> None:
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    src = _FakeSource([_snap(), _snap(), _snap()])
    factory, issued = _factory(src)
    persist = _persist_stopping(stop, after=3)

    svc = FocasService(
        _cfg(),
        factory,
        persist,
        stop=stop,
        heartbeat_fn=hbs.append,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    rc = _run(svc, clock, stop, hbs)

    assert rc == 0
    assert persist.state["calls"] == 3  # type: ignore[attr-defined]
    assert src.read_calls == 3
    assert len(issued) == 1  # connected exactly once, no reconnect
    assert hbs[-1].state is ServiceState.STOPPED
    assert hbs[-1].cycles_ok == 3
    assert src.close_calls >= 1  # closed on shutdown


def test_heartbeat_reports_measured_cycle_time() -> None:
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    # Each read "costs" 36s of wall time (the real Viper full-sweep magnitude).
    src = _FakeSource([_snap(), _snap()], clock=clock, read_cost=36.0)
    factory, _ = _factory(src)
    persist = _persist_stopping(stop, after=2)

    svc = FocasService(
        _cfg(interval_seconds=60.0),
        factory, persist, stop=stop,
        heartbeat_fn=hbs.append, sleep=clock.sleep, monotonic=clock.monotonic,
    )
    _run(svc, clock, stop, hbs)

    # The observed cadence is surfaced so ops can set poll_interval_seconds >= it.
    assert hbs[-1].last_cycle_seconds is not None
    assert hbs[-1].last_cycle_seconds >= 36.0


def test_warns_when_cycle_exceeds_interval(caplog) -> None:
    import logging

    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    src = _FakeSource([_snap(), _snap()], clock=clock, read_cost=36.0)
    factory, _ = _factory(src)
    persist = _persist_stopping(stop, after=2)

    svc = FocasService(
        _cfg(interval_seconds=20.0),  # below the 36s cycle → the trap we hit live
        factory, persist, stop=stop,
        heartbeat_fn=hbs.append, sleep=clock.sleep, monotonic=clock.monotonic,
    )
    with caplog.at_level(logging.WARNING, logger="shared.focas.service"):
        _run(svc, clock, stop, hbs)

    warns = [r for r in caplog.records if "exceeds interval" in r.getMessage()]
    assert warns, "expected a slow-cycle warning when interval < cycle time"
    # Warned once, not per cycle (throttled until it recovers).
    assert len(warns) == 1


def test_breaker_trips_then_reconnects_fresh_handle() -> None:
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    # First source fails 5x (== threshold) → breaker opens → reconnect.
    failing = _FakeSource([FocasError(6, "read")] * 5)
    healthy = _FakeSource([_snap()])
    factory, issued = _factory(failing, healthy)
    persist = _persist_stopping(stop, after=1)

    svc = FocasService(
        _cfg(breaker_threshold=5),
        factory,
        persist,
        stop=stop,
        heartbeat_fn=hbs.append,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    rc = _run(svc, clock, stop, hbs)

    assert rc == 0
    assert failing.read_calls == 5
    assert failing.close_calls >= 1  # handle closed when breaker opened
    assert len(issued) == 2  # reconnected with a fresh source
    assert healthy.read_calls == 1
    assert persist.state["calls"] == 1  # type: ignore[attr-defined]
    assert any(hb.state is ServiceState.CIRCUIT_OPEN for hb in hbs)


def test_stale_handle_reconnects_immediately() -> None:
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    s1 = _FakeSource([FocasHandleError(-8, "read")])  # one stale-handle error
    s2 = _FakeSource([_snap()])
    factory, issued = _factory(s1, s2)
    persist = _persist_stopping(stop, after=1)

    svc = FocasService(
        _cfg(breaker_threshold=5),  # well above 1 — proves it's not the breaker
        factory,
        persist,
        stop=stop,
        heartbeat_fn=hbs.append,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    _run(svc, clock, stop, hbs)

    assert s1.close_calls >= 1
    assert len(issued) == 2  # reconnected after a single stale-handle error
    assert s2.read_calls == 1


def test_persist_error_does_not_trip_breaker() -> None:
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    src = _FakeSource([_snap(), _snap(), _snap()])
    factory, issued = _factory(src)
    # DB raises on the first 2 persists, succeeds on the 3rd (which stops).
    persist = _persist_stopping(stop, after=3, raise_until=2)

    svc = FocasService(
        _cfg(breaker_threshold=2),  # low — a read breaker would trip fast
        factory,
        persist,
        stop=stop,
        heartbeat_fn=hbs.append,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    _run(svc, clock, stop, hbs)

    assert src.read_calls == 3  # reads kept succeeding despite DB errors
    assert len(issued) == 1  # never reconnected
    assert not any(hb.state is ServiceState.CIRCUIT_OPEN for hb in hbs)
    assert hbs[-1].cycles_failed == 0  # read failures, not DB failures


def test_connect_failure_backs_off_and_retries() -> None:
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    healthy = _FakeSource([_snap()])
    # Two connect failures, then a good source.
    factory, issued = _factory(
        FocasConnectError(-16, "connect"),
        FocasConnectError(-16, "connect"),
        healthy,
    )
    persist = _persist_stopping(stop, after=1)

    svc = FocasService(
        _cfg(),
        factory,
        persist,
        stop=stop,
        heartbeat_fn=hbs.append,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    rc = _run(svc, clock, stop, hbs)

    assert rc == 0
    assert len(issued) == 1  # only the healthy source was issued
    assert healthy.read_calls == 1
    assert hbs[-1].connect_failures == 0  # reset after a successful connect


def test_stop_before_first_cycle_exits_clean() -> None:
    stop = threading.Event()
    stop.set()  # already asked to stop
    clock = _Clock()
    hbs: list[Heartbeat] = []
    src = _FakeSource([_snap()])
    factory, issued = _factory(src)

    def _never_persist(_s: MachineSnapshot) -> int:  # pragma: no cover
        raise AssertionError("should not poll when stop is pre-set")

    svc = FocasService(
        _cfg(), factory, _never_persist, stop=stop,
        heartbeat_fn=hbs.append, sleep=clock.sleep, monotonic=clock.monotonic,
    )
    rc = svc.run()

    assert rc == 0
    assert issued == []  # never even connected
    assert hbs[-1].state is ServiceState.STOPPED


# -- single-instance lock ----------------------------------------------------


def test_pid_alive_current_process() -> None:
    import os

    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(-1) is False


def test_lock_refuses_second_live_instance(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "svc.lock"
    lock_path.write_text("4242", encoding="utf-8")  # some other pid
    monkeypatch.setattr("shared.focas.service._pid_alive", lambda pid: True)

    with pytest.raises(AlreadyRunningError):
        SingleInstanceLock(lock_path).acquire()


def test_lock_reclaims_stale_pid(tmp_path, monkeypatch) -> None:
    import os

    lock_path = tmp_path / "svc.lock"
    lock_path.write_text("4242", encoding="utf-8")  # dead pid
    monkeypatch.setattr("shared.focas.service._pid_alive", lambda pid: False)

    lock = SingleInstanceLock(lock_path)
    lock.acquire()
    assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())
    lock.release()
    assert not lock_path.exists()


def test_lock_context_manager_roundtrip(tmp_path) -> None:
    lock_path = tmp_path / "svc.lock"
    with SingleInstanceLock(lock_path):
        assert lock_path.exists()
    assert not lock_path.exists()


# -- fast status tier (L3) ---------------------------------------------------


class _FakeFastSource(_FakeSource):
    """_FakeSource that also exposes the light status read (lathe shape)."""

    def __init__(self, *args, fast_script: Sequence[BaseException] = (), **kwargs):
        super().__init__(*args, **kwargs)
        self.fast_calls = 0
        self.fast_script = deque(fast_script)

    def read_status_snapshot(self) -> MachineSnapshot:
        self.fast_calls += 1
        if self.fast_script:
            item = self.fast_script.popleft()
            if isinstance(item, BaseException):
                raise item
        return _snap()


def test_fast_tier_ticks_between_full_cycles() -> None:
    """interval=60 / status=10 -> five status-only ticks fill the window
    between full sweeps, each persisted; the heartbeat counts them apart
    from full cycles."""
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    src = _FakeFastSource([_snap()])
    factory, issued = _factory(src)
    persist = _persist_stopping(stop, after=6)  # 1 full + 5 fast ticks

    svc = FocasService(
        _cfg(interval_seconds=60.0, status_interval_seconds=10.0),
        factory,
        persist,
        stop=stop,
        heartbeat_fn=hbs.append,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    rc = _run(svc, clock, stop, hbs)

    assert rc == 0
    assert src.read_calls == 1  # exactly one full sweep
    assert src.fast_calls == 5  # ticks at t=10..50; the last window just sleeps
    assert persist.state["calls"] == 6  # type: ignore[attr-defined]
    assert hbs[-1].fast_ticks_ok == 5
    assert hbs[-1].cycles_ok == 1  # fast ticks never inflate the cycle count


def test_fast_tier_ignored_without_light_read() -> None:
    """A source with no read_status_snapshot (the mill client) sleeps the
    interval straight through even when the tier is configured."""
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    src = _FakeSource([_snap(), _snap()])
    factory, _ = _factory(src)
    persist = _persist_stopping(stop, after=2)

    svc = FocasService(
        _cfg(interval_seconds=5.0, status_interval_seconds=10.0),
        factory,
        persist,
        stop=stop,
        heartbeat_fn=hbs.append,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    rc = _run(svc, clock, stop, hbs)

    assert rc == 0
    assert src.read_calls == 2
    assert persist.state["calls"] == 2  # type: ignore[attr-defined]
    assert hbs[-1].fast_ticks_ok == 0


def test_fast_tick_error_never_trips_breaker() -> None:
    """A FOCAS error on a fast tick is logged and skipped — the breaker and
    the failure counters belong to full cycles only."""
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    src = _FakeFastSource(
        [_snap()], fast_script=[FocasError(-16, "cnc_statinfo", "blip")]
    )
    factory, issued = _factory(src)
    persist = _persist_stopping(stop, after=5)  # 1 full + 4 fast (tick 1 errors)

    svc = FocasService(
        _cfg(interval_seconds=60.0, status_interval_seconds=10.0, breaker_threshold=1),
        factory,
        persist,
        stop=stop,
        heartbeat_fn=hbs.append,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    rc = _run(svc, clock, stop, hbs)

    assert rc == 0
    assert src.fast_calls == 5  # errored tick still counts as a call...
    assert hbs[-1].fast_ticks_ok == 4  # ...but not as a success
    assert hbs[-1].cycles_failed == 0
    assert hbs[-1].consecutive_failures == 0
    assert len(issued) == 1  # no reconnect: breaker (threshold 1!) never saw it


def test_fast_tick_stale_handle_reconnects() -> None:
    """A stale handle on a fast tick closes the source; the main loop opens a
    fresh one and resumes full cycles — same recovery as the full-cycle path."""
    stop = threading.Event()
    clock = _Clock()
    hbs: list[Heartbeat] = []
    src1 = _FakeFastSource(
        [_snap()], fast_script=[FocasHandleError(-8, "cnc_statinfo", "stale")]
    )
    src2 = _FakeFastSource([_snap()])
    factory, issued = _factory(src1, src2)
    persist = _persist_stopping(stop, after=2)  # full on src1 + full on src2

    svc = FocasService(
        _cfg(interval_seconds=60.0, status_interval_seconds=10.0),
        factory,
        persist,
        stop=stop,
        heartbeat_fn=hbs.append,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    rc = _run(svc, clock, stop, hbs)

    assert rc == 0
    assert len(issued) == 2  # reconnected after the stale fast tick
    assert src1.close_calls >= 1
    assert src2.read_calls == 1


# -- heartbeat file ----------------------------------------------------------


def test_heartbeat_file_written(tmp_path) -> None:
    import json
    import os

    hb_path = tmp_path / "hb.json"
    fn = write_heartbeat_file(hb_path)
    hb = Heartbeat(
        pid=os.getpid(), machine_id="viper",
        state=ServiceState.HEALTHY, started_at="2026-07-10T00:00:00+00:00",
        cycles_ok=7,
    )
    fn(hb)

    data = json.loads(hb_path.read_text(encoding="utf-8"))
    assert data["state"] == "healthy"
    assert data["cycles_ok"] == 7
    assert data["machine_id"] == "viper"
