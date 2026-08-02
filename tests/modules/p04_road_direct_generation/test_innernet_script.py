from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "p04_run_segment_first_innernet.py"
CORE_VECTOR_FILES = (
    "Lane.geojson",
    "LaneBoundary.geojson",
    "LaneNextLane.geojson",
    "Road.geojson",
    "RoadNextRoad.geojson",
    "DriveZone.geojson",
    "DriveZone_fix.geojson",
    "DivStripZone.geojson",
    "DivStripZone_fix.geojson",
    "ReferenceLane.geojson",
)


def _load_script():
    spec = importlib.util.spec_from_file_location("p04_run_segment_first_innernet", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arguments(tmp_path: Path) -> tuple[list[str], dict[str, Path]]:
    patch_root = tmp_path / "patches"
    vector_dir = patch_root / "5417631180197930" / "Vector"
    vector_dir.mkdir(parents=True)
    for filename in CORE_VECTOR_FILES:
        (vector_dir / filename).touch()

    inputs = {}
    for name in (
        "swsd_road",
        "swsd_node",
        "t01_road",
        "t01_node",
        "t01_segment",
        "t07_surface",
        "t03_surface",
        "t04_surface",
        "full_rcsd_road",
        "full_rcsd_node",
        "target_replaceability",
        "target_disposition",
    ):
        path = tmp_path / f"{name}.gpkg"
        path.touch()
        inputs[name] = path

    output_dir = tmp_path.parent / f"{tmp_path.name}_output"
    argv = [
        "--patch-root",
        str(patch_root),
        "--swsd-road",
        str(inputs["swsd_road"]),
        "--swsd-node",
        str(inputs["swsd_node"]),
        "--t01-road",
        str(inputs["t01_road"]),
        "--t01-node",
        str(inputs["t01_node"]),
        "--t01-segment",
        str(inputs["t01_segment"]),
        "--t07-surface",
        str(inputs["t07_surface"]),
        "--t03-surface",
        str(inputs["t03_surface"]),
        "--t04-surface",
        str(inputs["t04_surface"]),
        "--full-rcsd-road",
        str(inputs["full_rcsd_road"]),
        "--full-rcsd-node",
        str(inputs["full_rcsd_node"]),
        "--target-replaceability",
        str(inputs["target_replaceability"]),
        "--target-disposition",
        str(inputs["target_disposition"]),
        "--output-dir",
        str(output_dir),
        "--run-id",
        "p04_innernet_case",
    ]
    return argv, {"patch_root": patch_root, "output_dir": output_dir, **inputs}


def test_innernet_script_maps_all_explicit_inputs_to_segment_first_config(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_script()
    argv, paths = _arguments(tmp_path)
    captured = {}

    def fake_runner(config):
        captured["config"] = config
        return SimpleNamespace(
            run_id=config.run_id,
            output_dir=config.output_dir,
            formal_gpkg=config.output_dir / "p04_segment_first_rcsd.gpkg",
            audit_gpkg=config.output_dir / "p04_segment_first_audit.gpkg",
            relations_gpkg=config.output_dir / "p04_segment_first_relations.gpkg",
            summary_path=config.output_dir / "p04_segment_first_summary.json",
            report_path=config.output_dir / "p04_segment_first_report.md",
            independent_quality_path=config.output_dir / "p04_segment_first_independent_quality.json",
            qgis_project_path=config.output_dir / "p04_segment_first_comparison.qgz",
            terminal_status="failed",
            core_gate_pass=False,
        )

    assert module.main(argv, runner=fake_runner) == 0
    config = captured["config"]
    assert config.patch_root == paths["patch_root"].resolve()
    assert config.swsd_road_path == paths["swsd_road"].resolve()
    assert config.swsd_node_path == paths["swsd_node"].resolve()
    assert config.t01_road_path == paths["t01_road"].resolve()
    assert config.t01_node_path == paths["t01_node"].resolve()
    assert config.t01_segment_path == paths["t01_segment"].resolve()
    assert config.t07_surface_path == paths["t07_surface"].resolve()
    assert config.t03_surface_path == paths["t03_surface"].resolve()
    assert config.t04_surface_path == paths["t04_surface"].resolve()
    assert config.full_rcsd_road_path == paths["full_rcsd_road"].resolve()
    assert config.full_rcsd_node_path == paths["full_rcsd_node"].resolve()
    assert config.target_replaceability_path == paths["target_replaceability"].resolve()
    assert config.target_disposition_path == paths["target_disposition"].resolve()
    assert config.output_dir == paths["output_dir"].resolve()
    assert config.analysis_crs == "EPSG:32650"

    console = capsys.readouterr()
    payload = json.loads(console.out)
    assert payload["process_completed"] is True
    assert payload["terminal_status"] == "failed"
    assert payload["core_gate_pass"] is False
    assert payload["patch_count"] == 1
    progress_path = Path(payload["progress_path"])
    assert progress_path.is_file()
    assert '"event_type": "run_completed"' in progress_path.read_text(
        encoding="utf-8"
    )
    assert "[1/4] Input validation completed." in console.err
    assert "[1/4] Runtime resource contract:" in console.err
    assert "[2/4] Discovered 1 Patch directories: 5417631180197930." in console.err
    assert "[3/4] Starting Segment-first Road generation." in console.err
    assert "[3/4] Segment-first Road generation completed" in console.err
    assert "[4/4] Outputs completed." in console.err
    assert "Run finished with exit_code=0." in console.err


def test_innernet_script_sets_bounded_native_thread_defaults(
    monkeypatch,
) -> None:
    for name in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "NUMEXPR_MAX_THREADS",
        "GDAL_NUM_THREADS",
        "CPL_MAX_ERROR_REPORTS",
    ):
        monkeypatch.delenv(name, raising=False)

    module = _load_script()

    assert {
        name: os.environ[name]
        for name in module.NATIVE_THREAD_DEFAULTS
    } == module.NATIVE_THREAD_DEFAULTS


def test_innernet_script_can_make_core_gate_failure_nonzero(tmp_path: Path) -> None:
    module = _load_script()
    argv, _ = _arguments(tmp_path)
    argv.append("--require-core-pass")

    def fake_runner(config):
        return SimpleNamespace(
            run_id=config.run_id,
            output_dir=config.output_dir,
            formal_gpkg=config.output_dir / "formal.gpkg",
            audit_gpkg=config.output_dir / "audit.gpkg",
            relations_gpkg=config.output_dir / "relations.gpkg",
            summary_path=config.output_dir / "summary.json",
            report_path=config.output_dir / "report.md",
            independent_quality_path=config.output_dir / "quality.json",
            qgis_project_path=None,
            terminal_status="failed",
            core_gate_pass=False,
        )

    assert module.main(argv, runner=fake_runner) == 2


def test_innernet_script_rejects_unsafe_surface_reconstruction(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    module = _load_script()
    argv, _ = _arguments(tmp_path)
    monkeypatch.setattr(
        module,
        "surface_coverage_runtime_stats",
        lambda: {"unsafe_local_reconstruction_count": 1},
    )

    def fake_runner(config):
        return SimpleNamespace(
            run_id=config.run_id,
            output_dir=config.output_dir,
            formal_gpkg=config.output_dir / "formal.gpkg",
            audit_gpkg=config.output_dir / "audit.gpkg",
            relations_gpkg=config.output_dir / "relations.gpkg",
            summary_path=config.output_dir / "summary.json",
            report_path=config.output_dir / "report.md",
            independent_quality_path=config.output_dir / "quality.json",
            qgis_project_path=None,
            terminal_status="passed",
            core_gate_pass=True,
        )

    assert module.main(argv, runner=fake_runner) == 3
    console = capsys.readouterr()
    payload = json.loads(console.out)
    assert payload["performance_gate_pass"] is False
    assert "exact surface coverage" in console.err


def test_innernet_script_reports_heartbeat_during_long_run(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    module = _load_script()
    argv, _ = _arguments(tmp_path)
    monkeypatch.setattr(module, "PROGRESS_HEARTBEAT_SECONDS", 0.01)

    def slow_runner(config):
        from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_progress import (
            advance_progress,
            begin_progress_stage,
        )

        begin_progress_stage("synthetic_units", 4, detail="heartbeat-test")
        advance_progress(
            "synthetic_units",
            completed=1,
            last_unit="segment-1",
        )
        time.sleep(0.035)
        return SimpleNamespace(
            run_id=config.run_id,
            output_dir=config.output_dir,
            formal_gpkg=config.output_dir / "formal.gpkg",
            audit_gpkg=config.output_dir / "audit.gpkg",
            relations_gpkg=config.output_dir / "relations.gpkg",
            summary_path=config.output_dir / "summary.json",
            report_path=config.output_dir / "report.md",
            independent_quality_path=config.output_dir / "quality.json",
            qgis_project_path=None,
            terminal_status="failed",
            core_gate_pass=False,
        )

    assert module.main(argv, runner=slow_runner) == 0
    console = capsys.readouterr()
    json.loads(console.out)
    assert "Segment-first Road generation is still running; elapsed=" in console.err
    assert "stage=synthetic_units#1" in console.err
    assert "units=1/4(25.0%)" in console.err
    assert "coverage=queries=" in console.err
    assert "corridor_cache=queries=" in console.err
    assert "active=test_innernet_script.py:slow_runner:" in console.err


def test_innernet_script_warns_when_actual_unit_stalls(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    module = _load_script()
    argv, _ = _arguments(tmp_path)
    monkeypatch.setattr(module, "PROGRESS_HEARTBEAT_SECONDS", 0.005)
    monkeypatch.setattr(module, "PROGRESS_STALL_WARNING_SECONDS", 0.01)

    def stalled_runner(config):
        from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_progress import (
            begin_progress_stage,
        )

        begin_progress_stage("segment_carrier", 100, detail="stall-test")
        time.sleep(0.04)
        return SimpleNamespace(
            run_id=config.run_id,
            output_dir=config.output_dir,
            formal_gpkg=config.output_dir / "formal.gpkg",
            audit_gpkg=config.output_dir / "audit.gpkg",
            relations_gpkg=config.output_dir / "relations.gpkg",
            summary_path=config.output_dir / "summary.json",
            report_path=config.output_dir / "report.md",
            independent_quality_path=config.output_dir / "quality.json",
            qgis_project_path=None,
            terminal_status="failed",
            core_gate_pass=False,
        )

    assert module.main(argv, runner=stalled_runner) == 0
    console = capsys.readouterr()
    assert "PROGRESS STALL WARNING" in console.err
    assert "stage=segment_carrier#1" in console.err


def test_innernet_script_preserves_failed_progress_event(
    tmp_path: Path,
) -> None:
    module = _load_script()
    argv, paths = _arguments(tmp_path)

    def failing_runner(config):
        from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_progress import (
            begin_progress_stage,
        )

        begin_progress_stage("segment_carrier", 10, detail="failure-test")
        raise RuntimeError("synthetic runner failure")

    with pytest.raises(RuntimeError, match="synthetic runner failure"):
        module.main(argv, runner=failing_runner)

    progress_path = paths["output_dir"] / "p04_progress.jsonl"
    assert progress_path.is_file()
    events = [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event_type"] == "run_failed"
    assert events[-1]["counters"]["error_type"] == "RuntimeError"


def test_innernet_script_help_exposes_only_parameterized_business_paths() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        check=True,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    for option in (
        "--patch-root",
        "--swsd-road",
        "--swsd-node",
        "--t01-road",
        "--t01-node",
        "--t01-segment",
        "--t07-surface",
        "--t03-surface",
        "--t04-surface",
        "--full-rcsd-road",
        "--full-rcsd-node",
        "--target-replaceability",
        "--target-disposition",
        "--output-dir",
        "--run-id",
    ):
        assert option in result.stdout
    assert "E:\\\\" not in result.stdout
    assert "/mnt/" not in result.stdout
