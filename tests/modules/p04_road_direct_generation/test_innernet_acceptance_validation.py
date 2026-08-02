from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR_PATH = (
    REPO_ROOT
    / "specs"
    / "p04-segment-first-performance-1500-patch-20260730"
    / "validation"
    / "validate_innernet_acceptance.py"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "p04_innernet_acceptance_validation",
        VALIDATOR_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_complete_run(tmp_path: Path, *, patch_workers: int | None) -> Path:
    validator = _load_validator()
    run_root = tmp_path / "run"
    run_root.mkdir()
    for filename in validator.REQUIRED_OUTPUTS:
        (run_root / filename).touch()

    native_limits = {
        name: "1"
        for name in validator.NATIVE_THREAD_LIMITS
    }
    native_limits["CPL_MAX_ERROR_REPORTS"] = "100"
    summary = {
        "analysis_crs": "EPSG:32650",
        "core_gate_pass": True,
        "core_gates": {"complete": True},
        "qgis": {
            "layer_count": 52,
            "readback_pass": True,
            "missing_layers": [],
        },
        "performance": {
            "wall_seconds": 100.0,
            "peak_rss_bytes": 512 * 1024**2,
            "runtime_resources": {
                "logical_cpu_count": 8,
                "patch_io_workers_max": patch_workers,
                "native_thread_limits": native_limits,
            },
            "resource_timeline": [
                {
                    "wall_seconds": 5.0,
                    "rss_bytes": 100,
                    "peak_rss_bytes": 100,
                },
                {
                    "wall_seconds": 35.0,
                    "rss_bytes": 200,
                    "peak_rss_bytes": 200,
                },
                {
                    "wall_seconds": 65.0,
                    "rss_bytes": 210,
                    "peak_rss_bytes": 210,
                },
                {
                    "wall_seconds": 100.0,
                    "rss_bytes": 215,
                    "peak_rss_bytes": 215,
                },
            ],
            "surface_coverage": {
                "unsafe_local_reconstruction_count": 0,
            },
            "surface_coverage_exactness_pass": True,
            "corridor_assembly_cache": {
                "entry_count": 10,
                "entry_count_max": 32768,
                "key_bytes": 1024,
                "key_bytes_max": 64 * 1024**2,
                "eviction_count": 0,
            },
            "target_path_cache": {
                "entry_count": 177,
                "entry_count_max": 32768,
                "key_bytes": 473821,
                "key_bytes_max": 64 * 1024**2,
                "eviction_count": 0,
            },
        },
    }
    quality = {
        "expected_crs": "EPSG:32650",
        "gate_pass": True,
        "counts": {"violation": 0},
        "gates": {"topology": True, "geometry": True},
    }
    manifest_files = [
        {
            "role": "patch_vector",
            "patch_id": patch_id,
            "size_bytes": index + 1,
            "sha256": f"{patch_id}-{index}",
        }
        for patch_id in ("patch_a", "patch_b")
        for index in range(8)
    ]
    manifest = {"files": manifest_files}
    (run_root / "p04_segment_first_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    (run_root / "p04_segment_first_independent_quality.json").write_text(
        json.dumps(quality),
        encoding="utf-8",
    )
    (run_root / "p04_segment_first_input_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    progress_events = []
    progress_stages = (
        "input_patch_layer",
        "segment_carrier",
        "junction_portal",
        "node_materialization",
        "topology_shared_nodes",
        "independent_qa_objects",
        "output_gpkg_layers",
        "qgis_project_layers",
    )
    for sequence, stage in enumerate(progress_stages, start=1):
        progress_events.append(
            {
                "event_type": "stage_completed",
                "stage": stage,
                "stage_sequence": sequence,
                "stage_invocation": 1,
                "completed": 1,
                "total": 1,
            }
        )
    progress_events.append(
        {
            "event_type": "run_completed",
            "stage": progress_stages[-1],
            "stage_sequence": len(progress_stages),
            "stage_invocation": 1,
            "completed": 1,
            "total": 1,
        }
    )
    (run_root / "p04_progress.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in progress_events),
        encoding="utf-8",
    )
    return run_root


def _args(run_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        repo_root=REPO_ROOT,
        run_root=run_root,
        report_path=run_root / "acceptance.json",
        reference_root=None,
        expected_patch_count_min=2,
        expected_patch_count_max=2,
        expected_logical_cpu_count=8,
        expected_analysis_crs="EPSG:32650",
        wall_target_hours=6.0,
        wall_hard_hours=8.0,
        baseline_wall_seconds=45759.2,
        rss_target_gib=8.0,
        rss_hard_gib=16.0,
        over_target_note="",
    )


def test_complete_run_without_reference_is_evidence_ready(tmp_path: Path) -> None:
    validator = _load_validator()
    result = validator.evaluate(
        _args(_write_complete_run(tmp_path, patch_workers=6))
    )

    assert result["status"] == "EVIDENCE_READY"
    assert result["exit_code"] == 0
    assert result["failed_gate_names"] == []
    assert not result["business_reference_evidence"]["provided"]


def test_missing_patch_worker_contract_fails(tmp_path: Path) -> None:
    validator = _load_validator()
    result = validator.evaluate(
        _args(_write_complete_run(tmp_path, patch_workers=None))
    )

    assert result["status"] == "FAILED"
    assert result["exit_code"] == 2
    assert result["failed_gate_names"] == ["patch_io_workers_bounded"]


def test_validator_help_is_renderable(monkeypatch, capsys) -> None:
    validator = _load_validator()
    monkeypatch.setattr(sys, "argv", [str(VALIDATOR_PATH), "--help"])

    with pytest.raises(SystemExit) as error:
        validator.parse_args()

    assert error.value.code == 0
    assert "候选必须不超过其50%。" in capsys.readouterr().out


def test_corridor_cache_must_remain_within_configured_bounds(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    run_root = _write_complete_run(tmp_path, patch_workers=6)
    summary_path = run_root / "p04_segment_first_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["performance"]["corridor_assembly_cache"]["key_bytes"] = (
        64 * 1024**2 + 1
    )
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = validator.evaluate(_args(run_root))

    assert result["status"] == "FAILED"
    assert "corridor_assembly_cache_bounded" in result["failed_gate_names"]


def test_target_path_cache_must_remain_within_configured_bounds(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    run_root = _write_complete_run(tmp_path, patch_workers=6)
    summary_path = run_root / "p04_segment_first_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["performance"]["target_path_cache"]["entry_count"] = 32769
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = validator.evaluate(_args(run_root))

    assert result["status"] == "FAILED"
    assert "target_path_cache_bounded" in result["failed_gate_names"]


def test_movement_selection_cache_must_remain_within_configured_bounds(
    tmp_path: Path,
) -> None:
    validator = _load_validator()
    run_root = _write_complete_run(tmp_path, patch_workers=6)
    progress_path = run_root / "p04_progress.jsonl"
    events = [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
    ]
    events.insert(
        -1,
        {
            "event_type": "stage_completed",
            "stage": "movement_anchor_split",
            "stage_sequence": 9,
            "stage_invocation": 1,
            "completed": 1,
            "total": 1,
            "counters": {
                "carrier_selection_cache_entries": 2,
                "carrier_selection_cache_entries_max": 1,
                "carrier_selection_cache_evictions": 0,
            },
        },
    )
    progress_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    result = validator.evaluate(_args(run_root))

    assert result["status"] == "FAILED"
    assert (
        "movement_carrier_selection_cache_bounded"
        in result["failed_gate_names"]
    )
