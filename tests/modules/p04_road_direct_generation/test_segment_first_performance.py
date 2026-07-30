from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_performance import (
    SegmentFirstPerformanceMonitor,
    active_p04_location,
    format_resource_snapshot,
    merge_performance_into_summary,
)


def test_monitor_records_resources_and_sampled_hotspots() -> None:
    monitor = SegmentFirstPerformanceMonitor()
    monitor.sample(active_location="segment_first_inputs.py:load:10")
    time.sleep(0.001)
    result = monitor.finish(active_location="segment_first_inputs.py:load:10")

    assert result["wall_seconds"] > 0.0
    assert result["process_cpu_seconds"] >= 0.0
    assert result["sample_count"] == 2
    assert result["sampled_hotspots"][0] == {
        "location": "segment_first_inputs.py:load:10",
        "sample_count": 2,
        "sample_ratio": 1.0,
    }
    assert result["resource_timeline"][0]["active_location"] == (
        "segment_first_inputs.py:load:10"
    )
    assert result["resource_timeline"][-1]["wall_seconds"] == result[
        "wall_seconds"
    ]
    assert len(result["resource_timeline"]) == 2
    assert result["budgets"]["wall_target_seconds"] == 21600
    assert result["budgets"]["wall_hard_limit_seconds"] == 28800
    assert result["runtime_resources"]["logical_cpu_count"]
    assert "OPENBLAS_NUM_THREADS" in result["runtime_resources"][
        "native_thread_limits"
    ]
    if sys.platform == "win32":
        assert result["current_rss_bytes"]
        assert result["peak_rss_bytes"]
        assert result["read_bytes"] is not None
        assert result["write_bytes"] is not None


def test_merge_performance_preserves_existing_elapsed_seconds(
    tmp_path: Path,
) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "run_id": "case",
                "performance": {"elapsed_seconds": 12.5},
            }
        ),
        encoding="utf-8",
    )

    assert merge_performance_into_summary(
        summary,
        {"peak_rss_bytes": 123, "wall_seconds": 13.0},
    )
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["performance"] == {
        "elapsed_seconds": 12.5,
        "peak_rss_bytes": 123,
        "wall_seconds": 13.0,
    }
    assert not summary.with_suffix(".json.tmp").exists()


def test_merge_performance_is_optional_for_test_double(
    tmp_path: Path,
) -> None:
    assert not merge_performance_into_summary(
        tmp_path / "missing.json",
        {"wall_seconds": 1.0},
    )


def test_active_location_and_resource_format_are_available() -> None:
    location = active_p04_location(threading.get_ident())
    assert "test_segment_first_performance.py:" in location
    monitor = SegmentFirstPerformanceMonitor()
    rendered = format_resource_snapshot(monitor.snapshot())
    assert "cpu=" in rendered
    assert "rss=" in rendered
    assert "read=" in rendered
