"""Reproduce the async Poller exit-after-2-3-cycles bug against the mock.

# Why this exists

`Poller.run()` exits cleanly after a handful of successful cycles in the
real-Viper async soak. Symptom: consumer's `async for snap in
poller.snapshots():` hangs forever waiting for snapshots that never come;
`Poller.health.state` reads `SHUTDOWN`. No exception logged, no `_stop`
event set by user code.

This script drives the same code path against `MockFocasSource` (no
Viper, no DB, no FOCAS DLL) at fast cadence so the bug should reproduce
in ~30 seconds rather than 3 minutes. Combined with the new DEBUG-level
instrumentation in `shared/focas/poller.py:run()`, the log shows exactly
where `run()` exits and what raised.

# Usage

    python scripts/debug_poller.py

Captures DEBUG logs from `shared.focas.poller` to stdout. Run for 20
cycles or until the bug fires. If the bug doesn't reproduce on this
Python version, the script exits 0 and we know the bug is environment-
specific (Python 3.13 or asyncio internal change). If it does
reproduce, the log immediately before the SHUTDOWN line is the smoking
gun.

# What we're looking for

A line like:
  poller-test run() cycle=2 sleep BASE-EXCEPTION CancelledError: ...
followed by:
  poller-test run() outer BASE-EXCEPTION ...
followed by:
  poller-test run() FINALLY entered

That sequence pinpoints the asyncio.wait_for cancellation propagation
hypothesis.

If we see:
  poller-test run() loop exited normally (stop=False, state=...)
... then the loop is exiting without _stop being set, which means
`not self._stop.is_set()` became False some OTHER way (impossible
unless _stop was set externally). That points at a different bug class.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure repo root is on sys.path even when invoked as
# `python scripts/debug_poller.py` from a venv where the package isn't
# pip-install-ed editable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.focas.mock import MockFocasSource, viper_idle  # noqa: E402
from shared.focas.models import MachineSnapshot  # noqa: E402
from shared.focas.poller import Poller, PollerState  # noqa: E402


class _MockAdapter:
    """Wrap MockFocasSource to match the SnapshotSource Protocol."""

    def __init__(self, machine_id: str) -> None:
        self._machine_id = machine_id
        self._mock = MockFocasSource([viper_idle()])

    def read_snapshot(self) -> MachineSnapshot:
        # Tiny sleep so the executor thread does some work, mirroring the
        # ~30s real-Viper poll. We use 50ms here so 20 cycles fit in a
        # bounded test window.
        import time

        time.sleep(0.05)
        snap = self._mock.poll()
        # MockFocasSource.poll() returns a snapshot but its machine_id may
        # not match what we want — patch it.
        return snap.model_copy(update={"machine_id": self._machine_id})

    def close(self) -> None:
        pass


async def _drive() -> int:
    machine_id = "poller-test"
    poller = Poller(
        machine_id=machine_id,
        client_factory=lambda: _MockAdapter(machine_id),
        interval_seconds=1.0,  # fast cadence to surface the bug quickly
        circuit_breaker_threshold=5,
        circuit_breaker_cooldown_seconds=2.0,
    )

    consumed: list[int] = []
    max_cycles = 20
    max_seconds = 30

    async def consume() -> None:
        async for _snap in poller.snapshots():
            consumed.append(len(consumed) + 1)
            print(
                f"  CONSUMED snapshot #{len(consumed)} "
                f"(state={poller.health.state.value}, "
                f"succ={poller.health.cycles_completed})"
            )
            if len(consumed) >= max_cycles:
                print(f"  reached {max_cycles} cycles; exiting consumer")
                return

    async with poller:
        consumer_task = asyncio.create_task(consume(), name="consumer")
        # Wait for either the consumer to finish or the timeout
        try:
            await asyncio.wait_for(consumer_task, timeout=max_seconds)
        except TimeoutError:
            print(
                f"  TIMEOUT after {max_seconds}s. "
                f"consumed={len(consumed)}, "
                f"poller.state={poller.health.state.value}, "
                f"succ={poller.health.cycles_completed}, "
                f"fail={poller.health.cycles_failed}"
            )
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

    print()
    print("=" * 60)
    print(f"final: consumed={len(consumed)} snapshots")
    print(f"poller succ={poller.health.cycles_completed}, fail={poller.health.cycles_failed}")
    print(f"poller final state: {poller.health.state.value}")
    print()

    if len(consumed) < max_cycles and poller.health.state is PollerState.SHUTDOWN:
        print("BUG REPRODUCED — Poller.run() exited prematurely")
        print("Look at the DEBUG log above for the cycle where run() exited.")
        return 1
    if len(consumed) >= max_cycles:
        print("Bug did NOT reproduce; poller delivered all snapshots cleanly.")
        return 0
    print("Inconclusive — neither full delivery nor SHUTDOWN-without-stop.")
    return 2


def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    # Force line buffering so output shows up live on Windows + Git Bash.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    print("=" * 60)
    print("Reproducing the async Poller exit-after-cycles bug")
    print("Python:", sys.version)
    print("=" * 60)
    print()

    return asyncio.run(_drive())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
