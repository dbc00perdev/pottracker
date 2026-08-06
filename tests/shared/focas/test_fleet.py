"""FleetService: one thread per machine, lock-skip, crash isolation, clean stop."""

from __future__ import annotations

import threading
import time

from shared.focas.fleet import FleetService, FleetUnit
from shared.focas.service import SingleInstanceLock


class _FakeService:
    """Stands in for FocasService: runs until the shared stop event fires."""

    def __init__(self, stop: threading.Event, crash: bool = False):
        self._stop = stop
        self._crash = crash
        self.ran = threading.Event()

    def run(self) -> None:
        self.ran.set()
        if self._crash:
            raise RuntimeError("boom")
        self._stop.wait(timeout=5)


def _unit(tmp_path, name: str, stop: threading.Event, crash: bool = False) -> FleetUnit:
    return FleetUnit(
        machine_id=name,
        service=_FakeService(stop, crash=crash),  # type: ignore[arg-type]
        lock=SingleInstanceLock(tmp_path / f"{name}.lock"),
    )


class TestFleetService:
    def test_starts_one_thread_per_unit_and_stops_cleanly(self, tmp_path):
        stop = threading.Event()
        units = [_unit(tmp_path, f"m{i}", stop) for i in range(3)]
        fleet = FleetService(units, stop)
        assert fleet.start() == 3
        for u in units:
            assert u.service.ran.wait(timeout=2)  # type: ignore[attr-defined]
        assert fleet.alive_count() == 3
        stop.set()
        fleet.wait()
        assert fleet.alive_count() == 0
        # Locks released on exit.
        for i in range(3):
            assert not (tmp_path / f"m{i}.lock").exists()

    def test_lock_collision_skips_that_machine_only(self, tmp_path):
        import subprocess
        import sys

        stop = threading.Event()
        # A "legacy poller" — a DIFFERENT live pid owning m1's lock (the lock
        # deliberately ignores our own pid, so a real foreign process is
        # needed to exercise the collision path).
        legacy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        (tmp_path / "m1.lock").write_text(str(legacy.pid), encoding="utf-8")
        try:
            units = [_unit(tmp_path, n, stop) for n in ("m0", "m1", "m2")]
            fleet = FleetService(units, stop)
            assert fleet.start() == 2
            assert units[1].skipped is True
            assert units[1].thread is None
            stop.set()
            fleet.wait()
        finally:
            legacy.kill()

    def test_one_crash_never_touches_siblings(self, tmp_path):
        stop = threading.Event()
        units = [
            _unit(tmp_path, "healthy-a", stop),
            _unit(tmp_path, "crasher", stop, crash=True),
            _unit(tmp_path, "healthy-b", stop),
        ]
        fleet = FleetService(units, stop)
        fleet.start()
        # Give the crasher time to die.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and fleet.alive_count() != 2:
            time.sleep(0.02)
        assert fleet.alive_count() == 2  # both healthy units still polling
        # Crasher's lock was released by the finally.
        assert not (tmp_path / "crasher.lock").exists()
        stop.set()
        fleet.wait()
