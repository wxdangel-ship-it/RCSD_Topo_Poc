from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, write_json

from .full_input_observability import now_text
from .full_input_shared_layers import T04SharedFullInputLayers


REQUIRED_INPUT_KEYS = (
    "nodes_path",
    "roads_path",
    "drivezone_path",
    "divstripzone_path",
    "rcsdroad_path",
    "rcsdnode_path",
)


def validate_full_input_paths(*, input_paths: dict[str, Path], out_root: Path, run_root: Path) -> dict[str, Any]:
    input_checks = []
    missing = []
    for key in REQUIRED_INPUT_KEYS:
        path = Path(input_paths[key])
        exists = path.is_file()
        input_checks.append({"key": key, "path": str(path), "exists": exists})
        if not exists:
            missing.append(key)
    out_root.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)
    probe_path = run_root / ".t04_preflight_write_probe"
    probe_path.write_text("ok\n", encoding="utf-8")
    probe_path.unlink(missing_ok=True)
    if missing:
        raise ValueError(f"missing required full-input layer paths: {','.join(missing)}")
    return {
        "input_checks": input_checks,
        "out_root": str(out_root),
        "run_root": str(run_root),
        "out_root_writable": True,
    }


def build_preflight_doc(
    *,
    input_paths: dict[str, Path],
    out_root: Path,
    run_root: Path,
    visual_check_dir: Path,
    path_check_doc: dict[str, Any],
    shared_layers: T04SharedFullInputLayers,
    discovered_case_ids: list[str],
    selected_case_ids: list[str],
    max_cases: int | None,
    workers: int,
    resume_requested: bool,
    retry_failed_requested: bool,
) -> dict[str, Any]:
    return {
        "generated_at": now_text(),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "target_crs": str(TARGET_CRS),
        "crs_policy": "all input layers are transformed to EPSG:3857 during shared bootstrap",
        "input_paths": {key: str(value) for key, value in input_paths.items()},
        "out_root": str(out_root),
        "run_root": str(run_root),
        "visual_check_dir": str(visual_check_dir),
        "path_checks": path_check_doc,
        "layer_crs": {
            name: {
                "source_crs": str(layer.source_crs),
                "crs_source": layer.crs_source,
                "target_crs": str(TARGET_CRS),
            }
            for name, layer in {
                "nodes": shared_layers.node_layer,
                "roads": shared_layers.road_layer,
                "drivezone": shared_layers.drivezone_layer,
                "divstripzone": shared_layers.divstripzone_layer,
                "rcsdroad": shared_layers.rcsdroad_layer,
                "rcsdnode": shared_layers.rcsdnode_layer,
            }.items()
        },
        "candidate_discovery_rule": {
            "representative_node": True,
            "has_evd": "yes",
            "is_anchor": "no",
            "kind_2_in": [8, 16, 128],
            "or_kind": 128,
        },
        "raw_case_count": len(discovered_case_ids),
        "raw_case_ids": list(discovered_case_ids),
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids": list(selected_case_ids),
        "effective_case_count": len(selected_case_ids),
        "effective_case_ids": list(selected_case_ids),
        "max_cases": max_cases,
        "workers": workers,
        "resume_requested": resume_requested,
        "retry_failed_requested": retry_failed_requested,
        "execution_mode": "t04_internal_full_input_direct_shared_layers",
    }


def write_candidate_artifacts(
    *,
    run_root: Path,
    discovered_case_ids: list[str],
    selected_case_ids: list[str],
) -> dict[str, str]:
    candidate_list_path = run_root / "candidate_mainnodeids.txt"
    candidate_list_path.write_text(
        "".join(f"{case_id}\n" for case_id in selected_case_ids),
        encoding="utf-8",
    )
    candidate_manifest_path = run_root / "candidate_manifest.json"
    write_json(
        candidate_manifest_path,
        {
            "generated_at": now_text(),
            "candidate_discovery_rule": "representative node, has_evd=yes, is_anchor=no, kind_2 in {8,16,128} or kind=128",
            "discovered_case_count": len(discovered_case_ids),
            "discovered_case_ids": list(discovered_case_ids),
            "selected_case_count": len(selected_case_ids),
            "selected_case_ids": list(selected_case_ids),
            "candidate_mainnodeids_path": str(candidate_list_path),
        },
    )
    return {
        "candidate_mainnodeids_path": str(candidate_list_path),
        "candidate_manifest_path": str(candidate_manifest_path),
    }


def write_bootstrap_artifacts(
    *,
    run_root: Path,
    shared_layers: T04SharedFullInputLayers,
    bootstrap_seconds: float,
) -> dict[str, str]:
    shared_manifest_path = run_root / "shared_layers_manifest.json"
    bootstrap_stats_path = run_root / "bootstrap_stats.json"
    write_json(shared_manifest_path, shared_layers.layer_manifest())
    write_json(
        bootstrap_stats_path,
        {
            "generated_at": now_text(),
            "bootstrap_seconds": round(max(float(bootstrap_seconds), 0.0), 6),
            "shared_layer_manifest_path": str(shared_manifest_path),
            "optimization_flags": {
                "candidate_discovery_once": True,
                "shared_readonly_layers_loaded_once": True,
                "spatial_indexes_built_once": True,
            },
        },
    )
    return {
        "shared_layers_manifest_path": str(shared_manifest_path),
        "bootstrap_stats_path": str(bootstrap_stats_path),
    }


__all__ = [
    "build_preflight_doc",
    "validate_full_input_paths",
    "write_bootstrap_artifacts",
    "write_candidate_artifacts",
]
