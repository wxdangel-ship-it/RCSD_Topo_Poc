from __future__ import annotations

import json
from pathlib import Path

import rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_progress as progress_module
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_progress import (
    advance_progress,
    begin_progress_stage,
    configure_progress,
    fail_progress,
    finish_progress_stage,
    format_progress_snapshot,
    progress_snapshot,
    reset_progress,
)


def test_progress_reports_actual_monotonic_units_and_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "p04_progress.jsonl"
    configure_progress("run-a", path)
    try:
        begin_progress_stage("segment_carrier", 10, detail="pass")
        advance_progress(
            "segment_carrier",
            completed=4,
            last_unit="segment-4",
            counters={"built": 3},
        )
        advance_progress("segment_carrier", completed=2)
        snapshot = progress_snapshot()

        assert snapshot["completed"] == 4
        assert snapshot["total"] == 10
        assert snapshot["percentage"] == 40.0
        assert snapshot["last_unit"] == "segment-4"
        assert snapshot["counters"] == {"built": 3}
        assert snapshot["overall_estimate"] == {
            "completed": 3,
            "total": 6,
            "phase": "network_stabilization",
            "dynamic_retry_count_unknown": True,
        }
        rendered = format_progress_snapshot(snapshot)
        assert "overall=3/6(network_stabilization)" in rendered
        assert "units=4/10(40.0%)" in rendered
        assert "last=segment-4" in rendered

        finished = finish_progress_stage("segment_carrier")
        assert finished["completed"] == 10
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert events[0]["event_type"] == "run_started"
        assert events[-1]["event_type"] == "stage_completed"
        assert events[-1]["completed"] == 10
    finally:
        reset_progress()


def test_progress_preserves_last_failure_event(tmp_path: Path) -> None:
    path = tmp_path / "p04_progress.jsonl"
    configure_progress("run-b", path)
    try:
        begin_progress_stage("input_patch_layer", 6, detail="Road.geojson")
        fail_progress(ValueError("broken input"))
        final = json.loads(
            path.read_text(encoding="utf-8").splitlines()[-1]
        )
        assert final["event_type"] == "run_failed"
        assert final["counters"]["error_type"] == "ValueError"
        assert final["counters"]["error_message"] == "broken input"
    finally:
        reset_progress()


def test_progress_throttles_fast_percent_events_without_losing_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "p04_progress.jsonl"
    monkeypatch.setattr(progress_module, "_EVENT_INTERVAL_SECONDS", 3600.0)
    monkeypatch.setattr(
        progress_module,
        "_MIN_EVENT_INTERVAL_SECONDS",
        3600.0,
    )
    configure_progress("run-fast", path)
    try:
        begin_progress_stage("segment_carrier", 1000, detail="fast pass")
        for completed in range(1, 1001):
            advance_progress(
                "segment_carrier",
                completed=completed,
                last_unit=f"segment-{completed}",
            )
        snapshot = progress_snapshot()
        finish_progress_stage("segment_carrier")
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

        assert snapshot["completed"] == 1000
        assert snapshot["last_unit"] == "segment-1000"
        assert [event["event_type"] for event in events] == [
            "run_started",
            "stage_started",
            "stage_completed",
        ]
        assert events[-1]["completed"] == 1000
    finally:
        reset_progress()
