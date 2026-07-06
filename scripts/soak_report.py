"""Report model + stats rollups for the sync FOCAS soak.

Split out of `focas_soak_simple.py` to keep that module under the 400-LOC cap
(CLAUDE.md "File Size Discipline") and to isolate the pure, DB-free report
shaping — dataclasses + percentile math — from the run harness. No FOCAS, no
DB, no I/O beyond dataclasses; trivially unit-testable.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class _Cycle:
    cycle: int
    started_at: str
    elapsed_ms: float
    success: bool
    error_type: str | None = None
    error_message: str | None = None
    # --persist bookkeeping (None when persistence is off)
    persist_ms: float | None = None
    persisted: bool = False
    changes: int | None = None
    persist_error: str | None = None


@dataclass
class _SoakReport:
    machine_id: str
    ip: str
    port: int
    interval_seconds: float
    started_at: str
    completed_at: str | None = None
    duration_seconds: float = 0.0
    cycles_attempted: int = 0
    cycles_succeeded: int = 0
    cycles_failed: int = 0
    success_rate: float = 0.0
    latency_ms: dict[str, float] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)
    persist_enabled: bool = False
    persist_summary: dict[str, float] = field(default_factory=dict)
    cycles: list[_Cycle] = field(default_factory=list)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _summarize_latency(cycles: list[_Cycle]) -> dict[str, float]:
    successes = [c.elapsed_ms for c in cycles if c.success]
    if not successes:
        return {"count": 0}
    return {
        "count": len(successes),
        "min": round(min(successes), 1),
        "max": round(max(successes), 1),
        "mean": round(statistics.fmean(successes), 1),
        "p50": round(_percentile(successes, 50), 1),
        "p95": round(_percentile(successes, 95), 1),
        "p99": round(_percentile(successes, 99), 1),
    }


def _summarize_errors(cycles: list[_Cycle]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in cycles:
        if not c.success and c.error_type:
            counts[c.error_type] = counts.get(c.error_type, 0) + 1
    return counts


def _summarize_persist(cycles: list[_Cycle]) -> dict[str, float]:
    """Persist latency percentiles + change/failure totals, reported alongside
    (and separately from) the FOCAS-read latency."""
    times = [c.persist_ms for c in cycles if c.persisted and c.persist_ms is not None]
    summary: dict[str, float] = {
        "persisted_cycles": len(times),
        "changes_total": sum(c.changes or 0 for c in cycles if c.persisted),
        "failures": sum(1 for c in cycles if c.persist_error is not None),
    }
    if times:
        summary.update(
            {
                "min": round(min(times), 1),
                "max": round(max(times), 1),
                "mean": round(statistics.fmean(times), 1),
                "p50": round(_percentile(times, 50), 1),
                "p95": round(_percentile(times, 95), 1),
                "p99": round(_percentile(times, 99), 1),
            }
        )
    return summary
