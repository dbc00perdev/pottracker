"""LABELED mock harness for FOCAS responses.

Per CLAUDE.md anti-pattern #3: do NOT mock FOCAS inline in tests or service
code. Use this module. Every consumer that imports from here is making an
explicit "I am not talking to a real machine" decision.

Scenarios are canned, deterministic, and parametric. The `MockFocasSource`
class is a drop-in replacement for the (still-unwritten) real `FocasClient`
read surface. It is not a transport — it just returns `MachineSnapshot`
instances on demand.

Used by:
  - Phase 1 unit tests
  - Phase 1 poller smoke tests (no real machine required)
  - Phase 2 snapshot/diff tests
  - UI dev environments where a real Viper isn't reachable

Never used in production. `client.py` (real transport) lives separately and
is selected via dependency injection at runtime.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .models import (
    AlarmEntry,
    MachineMode,
    MachineSnapshot,
    MachineStatus,
    OffsetRegister,
    PotEntry,
    RegisterType,
    ToolLife,
    ToolLifeStatus,
)


def _viper_baseline_offsets() -> tuple[OffsetRegister, ...]:
    """Plausible starting offset table for a Viper-shaped machine.

    Not real Viper data — synthesized values within physical ranges. H_geom
    typically negative (tool length below gauge line); H_wear small; D_geom
    positive (tool radius); D_wear small.
    """
    rows: list[OffsetRegister] = []
    for n in range(1, 25):
        rows.append(OffsetRegister(
            register_number=n,
            register_type=RegisterType.H_GEOM,
            value_mm=Decimal("-100.0000") - Decimal(n) * Decimal("0.5"),
        ))
        rows.append(OffsetRegister(
            register_number=n,
            register_type=RegisterType.H_WEAR,
            value_mm=Decimal("0.0000"),
        ))
        rows.append(OffsetRegister(
            register_number=n,
            register_type=RegisterType.D_GEOM,
            value_mm=Decimal("3.0000") + Decimal(n) * Decimal("0.1"),
        ))
        rows.append(OffsetRegister(
            register_number=n,
            register_type=RegisterType.D_WEAR,
            value_mm=Decimal("0.0000"),
        ))
    return tuple(rows)


def _viper_baseline_pots(probe_t: int = 99) -> tuple[PotEntry, ...]:
    """24-pot magazine, T1..T23 mapped 1:1 to pots, probe in pot 24."""
    rows = [PotEntry(pot_number=p, t_number=p) for p in range(1, 24)]
    rows.append(PotEntry(pot_number=24, t_number=probe_t))
    return tuple(rows)


def _viper_baseline_tool_life() -> tuple[ToolLife, ...]:
    return tuple(
        ToolLife(t_number=t, life_count=0, life_max=1000, status=ToolLifeStatus.LIVE)
        for t in range(1, 24)
    )


@dataclass
class MockScenario:
    """Named, parameterizable canned scenario.

    Attributes:
        name: human label, surfaced in test failure messages.
        machine_id: opaque string, matches `shared.machine.id` in real life.
        status: machine mode + running state.
        offsets / pots / tool_life / alarms: snapshot contents.
    """

    name: str
    machine_id: str = "viper-mock"
    status: MachineStatus = field(default_factory=lambda: MachineStatus(
        mode=MachineMode.MEM, running=False, emergency_stop=False, current_t_number=None
    ))
    offsets: tuple[OffsetRegister, ...] = field(default_factory=_viper_baseline_offsets)
    pots: tuple[PotEntry, ...] = field(default_factory=_viper_baseline_pots)
    tool_life: tuple[ToolLife, ...] = field(default_factory=_viper_baseline_tool_life)
    alarms: tuple[AlarmEntry, ...] = ()

    def snapshot(self, polled_at: datetime | None = None) -> MachineSnapshot:
        return MachineSnapshot(
            machine_id=self.machine_id,
            polled_at=polled_at or datetime.now(UTC),
            status=self.status,
            offsets=self.offsets,
            pots=self.pots,
            tool_life=self.tool_life,
            alarms=self.alarms,
        )


# --- canonical scenarios -----------------------------------------------------

def viper_idle() -> MockScenario:
    """Viper sitting in MEM mode, no program running, no alarms."""
    return MockScenario(name="viper_idle")


def viper_running_auto() -> MockScenario:
    """Viper running a program. WRITES MUST BE BLOCKED in this state (R6)."""
    return MockScenario(
        name="viper_running_auto",
        status=MachineStatus(
            mode=MachineMode.AUTO, running=True, emergency_stop=False, current_t_number=5
        ),
    )


def viper_estop() -> MockScenario:
    """E-stop pressed. All FOCAS writes must be refused."""
    return MockScenario(
        name="viper_estop",
        status=MachineStatus(
            mode=MachineMode.MEM, running=False, emergency_stop=True, current_t_number=None
        ),
    )


def viper_alarm() -> MockScenario:
    """Viper with an active alarm — surfaced to UI, doesn't change read shape."""
    return MockScenario(
        name="viper_alarm",
        alarms=(
            AlarmEntry(code=506, axis=1, message="Overtravel + X"),
        ),
    )


def viper_offset_drifted(register_number: int = 5, delta_mm: str = "0.0450") -> MockScenario:
    """Same as idle, but H_geom on `register_number` has shifted by `delta_mm`.

    Used by diff-detection tests. 0.045mm is above the 0.5mm flagging
    threshold check inversely — a *small* drift below the prompt threshold,
    used to verify we still record it without prompting. For the >0.5mm
    case use `viper_offset_significantly_drifted`.
    """
    base = list(_viper_baseline_offsets())
    target_idx = next(
        i for i, o in enumerate(base)
        if o.register_number == register_number and o.register_type == RegisterType.H_GEOM
    )
    base[target_idx] = OffsetRegister(
        register_number=register_number,
        register_type=RegisterType.H_GEOM,
        value_mm=base[target_idx].value_mm + Decimal(delta_mm),
    )
    return MockScenario(name=f"viper_offset_drifted_h{register_number}", offsets=tuple(base))


def viper_offset_significantly_drifted(register_number: int = 5) -> MockScenario:
    """H_geom shifted >0.5mm — must trigger operator confirmation prompt."""
    return viper_offset_drifted(register_number=register_number, delta_mm="0.7500")


def viper_pot_swap(t_a: int = 1, t_b: int = 2) -> MockScenario:
    """Random-access ATC swapped two tools' pot positions (R10)."""
    base = list(_viper_baseline_pots())
    pot_a = next(i for i, p in enumerate(base) if p.t_number == t_a)
    pot_b = next(i for i, p in enumerate(base) if p.t_number == t_b)
    base[pot_a], base[pot_b] = (
        PotEntry(pot_number=base[pot_a].pot_number, t_number=t_b),
        PotEntry(pot_number=base[pot_b].pot_number, t_number=t_a),
    )
    return MockScenario(name=f"viper_pot_swap_t{t_a}_t{t_b}", pots=tuple(base))


CANONICAL_SCENARIOS: tuple[MockScenario, ...] = (
    viper_idle(),
    viper_running_auto(),
    viper_estop(),
    viper_alarm(),
    viper_offset_drifted(),
    viper_offset_significantly_drifted(),
    viper_pot_swap(),
)


# --- mock source -------------------------------------------------------------


class MockFocasSource:
    """In-memory replacement for the real (unwritten) FocasClient read surface.

    Construct with one or more scenarios; iteration cycles through them so
    callers can simulate poll-over-time changes deterministically.

    NOT a transport. NOT thread-safe. NOT for production use.
    """

    def __init__(self, scenarios: list[MockScenario] | tuple[MockScenario, ...] | None = None):
        if not scenarios:
            scenarios = [viper_idle()]
        self._scenarios: tuple[MockScenario, ...] = tuple(scenarios)
        self._cursor: int = 0
        self._clock: datetime = datetime.now(UTC)

    def advance_clock(self, seconds: int) -> None:
        self._clock = self._clock + timedelta(seconds=seconds)

    def poll(self) -> MachineSnapshot:
        scenario = self._scenarios[self._cursor % len(self._scenarios)]
        self._cursor += 1
        return scenario.snapshot(polled_at=self._clock)

    def stream(self, n: int) -> Iterator[MachineSnapshot]:
        for _ in range(n):
            yield self.poll()
