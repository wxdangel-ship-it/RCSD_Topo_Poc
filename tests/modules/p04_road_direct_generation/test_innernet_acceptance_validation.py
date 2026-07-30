from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


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
