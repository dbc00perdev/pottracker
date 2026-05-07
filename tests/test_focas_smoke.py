"""Tests for scripts/focas_smoke.py.

Driven entirely off the `--mock` source adapter — a real Viper run isn't
something CI can do, but we can verify the script's report-building logic,
CLI parsing, and JSON output shape against the mock harness from
shared.focas.mock. Operator runs the same script with `--ip` on Windows;
the report shape is identical.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.focas_smoke import (
    _MockSourceAdapter,
    main,
    run_smoke,
)

# ============================================================================
# run_smoke — exercises the report-building flow end-to-end
# ============================================================================


class TestRunSmoke:
    def test_returns_json_serializable_report(self):
        source = _MockSourceAdapter(machine_id="m")
        report = run_smoke(source, machine_id="m", latency_samples=2)
        # JSON-roundtrips without errors.
        json.dumps(report, default=str)

    def test_top_level_keys(self):
        source = _MockSourceAdapter(machine_id="m")
        report = run_smoke(source, machine_id="m", latency_samples=2)
        for k in (
            "machine_id",
            "started_at",
            "completed_at",
            "platform",
            "sysinfo",
            "identity_check",
            "offset_layout",
            "snapshot",
            "latency_per_call_ms",
            "open_questions",
            "wall_clock_seconds",
        ):
            assert k in report

    def test_identity_check_passes_with_default_expected(self):
        source = _MockSourceAdapter()
        report = run_smoke(source, machine_id="m", latency_samples=2)
        assert report["identity_check"]["passed"] is True
        assert report["identity_check"]["error"] is None

    def test_identity_check_fails_on_mismatch(self):
        source = _MockSourceAdapter()
        report = run_smoke(
            source,
            machine_id="m",
            latency_samples=2,
            expected_cnc_type="30",  # mock identifies as "0i"
        )
        assert report["identity_check"]["passed"] is False
        assert "mock identity mismatch" in (report["identity_check"]["error"] or "")

    def test_offset_layout_recorded(self):
        source = _MockSourceAdapter()
        report = run_smoke(source, machine_id="m", latency_samples=2)
        layout = report["offset_layout"]
        assert "ofs_type" in layout
        assert "use_no" in layout
        assert layout["use_no"] >= 0

    def test_snapshot_includes_status_pots_alarms(self):
        source = _MockSourceAdapter()
        report = run_smoke(source, machine_id="m", latency_samples=2)
        snap = report["snapshot"]
        assert "status" in snap
        assert "pots" in snap
        assert "alarms" in snap
        assert "offsets" in snap
        # status fields
        for key in ("mode", "running", "emergency_stop", "current_t_number"):
            assert key in snap["status"]
        # pots emit count + entries
        assert snap["pots"]["count"] == len(snap["pots"]["entries"])

    def test_offsets_summary_has_first_and_last(self):
        source = _MockSourceAdapter()
        report = run_smoke(source, machine_id="m", latency_samples=2)
        offs = report["snapshot"]["offsets"]
        assert "count_total" in offs
        assert "count_by_type" in offs
        assert "first_5" in offs
        assert "last_5" in offs
        assert len(offs["first_5"]) <= 5
        assert len(offs["last_5"]) <= 5

    def test_offsets_value_mm_serialized_as_string(self):
        # Decimal -> string preserves precision; floats lose it.
        source = _MockSourceAdapter()
        report = run_smoke(source, machine_id="m", latency_samples=2)
        for o in report["snapshot"]["offsets"]["first_5"]:
            assert isinstance(o["value_mm"], str)

    def test_latency_block_has_all_call_categories(self):
        source = _MockSourceAdapter()
        report = run_smoke(source, machine_id="m", latency_samples=3)
        lat = report["latency_per_call_ms"]
        for call in ("status", "pots", "alarms", "offsets"):
            assert call in lat
            for stat in ("n", "min_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms"):
                assert stat in lat[call]

    def test_errors_block_present(self):
        source = _MockSourceAdapter()
        report = run_smoke(source, machine_id="m", latency_samples=2)
        assert "errors" in report
        assert isinstance(report["errors"], list)
        # Mock source never errors — list should be empty.
        assert report["errors"] == []

    def test_open_questions_block_addresses_each_id(self):
        source = _MockSourceAdapter()
        report = run_smoke(source, machine_id="m", latency_samples=2)
        oq = report["open_questions"]
        for qid in (
            "O1_current_t_via_cnc_modal",
            "O2_offset_table_layout",
            "O5_empty_pot_sentinel",
            "O7_settimeout_units",
            "O8_offset_increment",
        ):
            assert qid in oq
            assert "interpretation" in oq[qid]


# ============================================================================
# CLI / main()
# ============================================================================


class TestMain:
    def test_writes_output_file(self, tmp_path: Path):
        out = tmp_path / "report.json"
        rc = main(["--mock", "--output", str(out), "--latency-samples", "2"])
        assert rc == 0
        assert out.exists()
        loaded = json.loads(out.read_text())
        assert loaded["machine_id"] == "viper"  # default machine-id
        assert loaded["identity_check"]["passed"] is True

    def test_creates_parent_directories(self, tmp_path: Path):
        out = tmp_path / "subdir" / "report.json"
        rc = main(["--mock", "--output", str(out), "--latency-samples", "2"])
        assert rc == 0
        assert out.exists()

    def test_machine_id_propagates(self, tmp_path: Path):
        out = tmp_path / "report.json"
        rc = main(
            [
                "--mock",
                "--output",
                str(out),
                "--machine-id",
                "viper-lg-1000ap",
                "--latency-samples",
                "2",
            ]
        )
        assert rc == 0
        loaded = json.loads(out.read_text())
        assert loaded["machine_id"] == "viper-lg-1000ap"
        assert loaded["snapshot"]["status"] is not None

    def test_identity_mismatch_exits_2(self, tmp_path: Path):
        out = tmp_path / "report.json"
        rc = main(
            [
                "--mock",
                "--output",
                str(out),
                "--expected-cnc-type",
                "30",
                "--latency-samples",
                "2",
            ]
        )
        assert rc == 2
        loaded = json.loads(out.read_text())
        assert loaded["identity_check"]["passed"] is False

    def test_missing_ip_without_mock_exits(self, tmp_path: Path):
        out = tmp_path / "report.json"
        with pytest.raises(SystemExit, match="--ip"):
            main(["--output", str(out)])
