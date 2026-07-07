"""Tests for scripts/focas_soak_simple.py --persist wiring.

Covers the pure, DB-free helpers: persist-config resolution and the persist
latency/summary rollup. The full read->persist loop is an integration concern
(real FOCAS + Docker Postgres), not a unit test.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from scripts.focas_soak_simple import (
    _resolve_machine_uuid,
    _resolve_persist_dsn,
)
from scripts.soak_report import _Cycle, _summarize_persist


class TestResolvePersistDsn:
    def test_arg_wins_over_env(self, monkeypatch):
        # Precedence-only test with fabricated DSNs — bypass the DSN preflight
        # guard, which would (correctly) refuse these non-dev targets.
        monkeypatch.setenv("LANCE_DSN_GUARD_DISABLE", "1")
        monkeypatch.setenv("DATABASE_URL", "postgresql://env/db")
        assert _resolve_persist_dsn("postgresql://arg/db") == "postgresql://arg/db"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("LANCE_DSN_GUARD_DISABLE", "1")
        monkeypatch.setenv("DATABASE_URL", "postgresql://env/db")
        assert _resolve_persist_dsn(None) == "postgresql://env/db"

    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit, match="DATABASE_URL"):
            _resolve_persist_dsn(None)


class TestResolveMachineUuid:
    def test_valid(self):
        raw = "00000000-0000-0000-0000-0000000000aa"
        assert _resolve_machine_uuid(raw) == UUID(raw)

    def test_invalid_raises(self):
        with pytest.raises(SystemExit, match="not a valid UUID"):
            _resolve_machine_uuid("not-a-uuid")

    def test_missing_raises(self):
        with pytest.raises(SystemExit, match="machine-uuid"):
            _resolve_machine_uuid(None)


def _cycle(**kw) -> _Cycle:
    base = {"cycle": 1, "started_at": "t", "elapsed_ms": 1.0, "success": True}
    base.update(kw)
    return _Cycle(**base)


class TestSummarizePersist:
    def test_counts_times_changes_and_failures(self):
        cycles = [
            _cycle(persisted=True, persist_ms=10.0, changes=3),
            _cycle(persisted=True, persist_ms=20.0, changes=0),
            _cycle(persisted=False, persist_error="OperationalError: boom"),
        ]
        s = _summarize_persist(cycles)
        assert s["persisted_cycles"] == 2
        assert s["changes_total"] == 3
        assert s["failures"] == 1
        assert s["min"] == 10.0
        assert s["max"] == 20.0
        assert "p95" in s

    def test_empty_has_no_percentiles(self):
        s = _summarize_persist([])
        assert s["persisted_cycles"] == 0
        assert s["changes_total"] == 0
        assert s["failures"] == 0
        assert "p95" not in s

    def test_failure_only_reports_failure_no_latency_block(self):
        s = _summarize_persist([_cycle(persisted=False, persist_error="X: y")])
        assert s["failures"] == 1
        assert s["persisted_cycles"] == 0
        assert "mean" not in s
