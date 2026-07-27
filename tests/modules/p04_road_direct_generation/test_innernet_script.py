from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace


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
    assert "[1/4] Input validation completed." in console.err
    assert "[2/4] Discovered 1 Patch directories: 5417631180197930." in console.err
    assert "[3/4] Starting Segment-first Road generation." in console.err
    assert "[3/4] Segment-first Road generation completed" in console.err
    assert "[4/4] Outputs completed." in console.err
    assert "Run finished with exit_code=0." in console.err


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


def test_innernet_script_reports_heartbeat_during_long_run(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    module = _load_script()
    argv, _ = _arguments(tmp_path)
    monkeypatch.setattr(module, "PROGRESS_HEARTBEAT_SECONDS", 0.01)

    def slow_runner(config):
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
