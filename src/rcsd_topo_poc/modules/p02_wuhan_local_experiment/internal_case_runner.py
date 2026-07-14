from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from rcsd_topo_poc.modules.p02_wuhan_local_experiment.endpoint_overrides import (
    apply_confirmed_endpoint_overrides,
)
from rcsd_topo_poc.modules.p02_wuhan_local_experiment.manual_overrides import (
    apply_wuhan_t_junction_override,
)
from rcsd_topo_poc.modules.p02_wuhan_local_experiment.manual_relations import (
    transform_manual_relations,
)
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_runner import (
    run_t05_phase2_rcsd_junctionization_and_relation,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import (
    run_t06_segment_fusion_precheck,
    run_t06_step3_segment_replacement,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.io import (
    suppress_feature_json_outputs,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.rcsd_unreplaced_attribution import (
    run_t06_rcsd_unreplaced_attribution,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_output_slimming import (
    compact_step3_outputs,
)
from rcsd_topo_poc.modules.t08_preprocess.vector_io import read_vector, write_gpkg


RAW_FILENAMES = ("node.geojson", "road.geojson", "RCSDNode.geojson", "RCSDRoad.geojson")
EXPECTED_RAW_COUNTS = {
    "node.geojson": 143,
    "road.geojson": 163,
    "RCSDNode.geojson": 655,
    "RCSDRoad.geojson": 469,
}
TARGET_SEGMENT_STATUS = {
    "3086610_609284657": "replaced",
    "521458225_600688320": "retained_swsd",
    "521458225_612028267": "replaced",
    "609020493_61493884": "replaced",
}
EXPECTED_USED_OWNER_COUNTS = {
    "3086610_609284657": 38,
    "521458225_612028267": 6,
    "609020493_61493884": 5,
}
EXPECTED_ROAD_OWNERS = {
    "5855295910117380": "609020493_61493884",
    "5855295910117399": "3086610_609284657",
    "5855295910117467": "3086610_609020493",
    "5855295910117477": "3086610_609284657",
    "5855295910117496": "3086610_609284657",
    "5855296278768589": "3086610_609284657",
}


def run_wuhan_internal_case(
    *,
    input_dir: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    qgis_mode: str = "required",
    qgis_python: str | None = None,
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[4]
    input_root = Path(input_dir).expanduser().resolve()
    output_parent = Path(out_root).expanduser().resolve()
    resolved_run_id = run_id or f"p02_wuhan_internal_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", resolved_run_id):
        raise ValueError(f"run_id contains unsupported characters: {resolved_run_id}")
    if qgis_mode not in {"required", "skip"}:
        raise ValueError(f"unsupported qgis_mode: {qgis_mode}")
    raw_inputs = _require_raw_inputs(input_root)
    run_root = output_parent / resolved_run_id
    if run_root.exists():
        raise FileExistsError(f"run root already exists; refuse overwrite: {run_root}")
    run_root.mkdir(parents=True)
    manifest_path = run_root / "p02_run_manifest.json"
    manifest: dict[str, Any] = {
        "schema": "p02_wuhan_internal_case_manifest_v1",
        "run_id": resolved_run_id,
        "region": "Wuhan",
        "status": "running",
        "started_at": _utc_now(),
        "repo": _repo_state(repo_root),
        "environment": {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "qgis_mode": qgis_mode,
            "qgis_python_requested": qgis_python,
        },
        "input_policy": "full raw input; no clip; copy-on-write only",
        "input_directory": str(input_root),
        "inputs": {
            name: {
                "source_path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for name, path in raw_inputs.items()
        },
        "manual_sources": {
            "relations": "modules/p02_wuhan_local_experiment/relations/p02_manual_relations_v1.csv",
            "endpoint_overrides": "modules/p02_wuhan_local_experiment/endpoint_overrides/p02_confirmed_endpoint_overrides.csv",
            "t_junction_override": "609020493 grade/grade_2=2 after Tool6 before Tool4",
        },
        "unavailable_stages": {
            "T07": "missing_road_surface_divstrip_and_rcsdintersection",
            "T03": "missing_road_surface_divstrip_and_rcsdintersection",
            "T04": "missing_road_surface_divstrip_and_rcsdintersection",
        },
        "stages": [],
    }
    _write_json(manifest_path, manifest)

    paths = _stage_paths(run_root, resolved_run_id)
    relation_source = repo_root / "modules" / "p02_wuhan_local_experiment" / "relations" / "p02_manual_relations_v1.csv"
    override_source = repo_root / "modules" / "p02_wuhan_local_experiment" / "endpoint_overrides" / "p02_confirmed_endpoint_overrides.csv"
    try:
        _execute_stage(
            manifest,
            manifest_path,
            "copy_raw_inputs",
            lambda: _copy_raw_inputs(raw_inputs, paths["tool1"]),
        )
        tool1_command = [
            sys.executable,
            str(repo_root / "scripts" / "t08_tool1_vector_convert.py"),
        ]
        for name in RAW_FILENAMES:
            tool1_command.extend(("--input-geojson", str(paths["tool1"] / name)))
        tool1_command.extend(
            (
                "--default-crs",
                "EPSG:4326",
                "--summary-output",
                str(paths["tool1"] / "p02_summary_tool1.json"),
            )
        )
        _execute_command_stage(
            manifest,
            manifest_path,
            "t08_tool1",
            tool1_command,
            paths["tool1"] / "t08_tool1.log",
            repo_root,
        )
        endpoint_artifacts = _execute_stage(
            manifest,
            manifest_path,
            "p02_confirmed_endpoint_overrides",
            lambda: apply_confirmed_endpoint_overrides(
                roads_path=paths["tool1"] / "RCSDRoad.gpkg",
                nodes_path=paths["tool1"] / "RCSDNode.gpkg",
                override_list_path=override_source,
                out_dir=paths["endpoint"],
                expected_override_count=9,
            ),
        )
        _execute_command_stage(
            manifest,
            manifest_path,
            "t08_tool3",
            [
                sys.executable,
                str(repo_root / "scripts" / "t08_tool3_nodes_type_aggregation.py"),
                "--nodes-gpkg",
                str(paths["tool1"] / "node.gpkg"),
                "--roads-gpkg",
                str(paths["tool1"] / "road.gpkg"),
                "--nodes-output",
                str(paths["tool3"] / "p02_nodes_tool3.gpkg"),
                "--summary-output",
                str(paths["tool3"] / "p02_summary_tool3.json"),
            ],
            paths["tool3"] / "t08_tool3.log",
            repo_root,
        )
        _execute_command_stage(
            manifest,
            manifest_path,
            "t08_tool6",
            [
                sys.executable,
                str(repo_root / "scripts" / "t08_tool6_nodes_type_qc.py"),
                "--nodes-gpkg",
                str(paths["tool3"] / "p02_nodes_tool3.gpkg"),
                "--roads-gpkg",
                str(paths["tool1"] / "road.gpkg"),
                "--csv-output",
                str(paths["tool6"] / "p02_node_error_tool6.csv"),
                "--error-nodes-output",
                str(paths["tool6"] / "p02_node_error_tool6.gpkg"),
                "--summary-output",
                str(paths["tool6"] / "p02_node_error_summary_tool6.json"),
            ],
            paths["tool6"] / "t08_tool6.log",
            repo_root,
        )
        manual_artifacts = _execute_stage(
            manifest,
            manifest_path,
            "p02_manual_t_junction_override",
            lambda: apply_wuhan_t_junction_override(
                nodes_path=paths["tool3"] / "p02_nodes_tool3.gpkg",
                roads_path=paths["tool1"] / "road.gpkg",
                tool6_csv_path=paths["tool6"] / "p02_node_error_tool6.csv",
                out_dir=paths["manual_override"],
            ),
        )
        _execute_command_stage(
            manifest,
            manifest_path,
            "t08_tool4",
            [
                sys.executable,
                str(repo_root / "scripts" / "t08_tool4_junction_type_repair.py"),
                "--nodes-gpkg",
                str(manual_artifacts.nodes),
                "--roads-gpkg",
                str(paths["tool1"] / "road.gpkg"),
                "--nodes-output",
                str(paths["tool4"] / "p02_nodes_tool4.gpkg"),
                "--roads-output",
                str(paths["tool4"] / "p02_roads_tool4.gpkg"),
                "--audit-nodes-output",
                str(paths["tool4"] / "p02_audit_nodes_tool4.gpkg"),
                "--tool6-node-error-csv",
                str(manual_artifacts.tool6_csv),
                "--summary-output",
                str(paths["tool4"] / "p02_summary_tool4.json"),
            ],
            paths["tool4"] / "t08_tool4.log",
            repo_root,
        )
        _execute_command_stage(
            manifest,
            manifest_path,
            "t08_tool5",
            [
                sys.executable,
                str(repo_root / "scripts" / "t08_tool5_complex_junction_preprocess.py"),
                "--nodes-gpkg",
                str(paths["tool4"] / "p02_nodes_tool4.gpkg"),
                "--roads-gpkg",
                str(paths["tool4"] / "p02_roads_tool4.gpkg"),
                "--nodes-output",
                str(paths["tool5"] / "p02_nodes_tool5.gpkg"),
                "--roads-output",
                str(paths["tool5"] / "p02_roads_tool5.gpkg"),
                "--audit-nodes-output",
                str(paths["tool5"] / "p02_audit_nodes_tool5.gpkg"),
                "--summary-output",
                str(paths["tool5"] / "p02_summary_tool5.json"),
            ],
            paths["tool5"] / "t08_tool5.log",
            repo_root,
        )
        relation_artifacts = _execute_stage(
            manifest,
            manifest_path,
            "p02_manual_relation_transform",
            lambda: transform_manual_relations(
                raw_relation_path=relation_source,
                final_swsd_nodes_path=paths["tool5"] / "p02_nodes_tool5.gpkg",
                rcsdnode_path=paths["tool1"] / "RCSDNode.gpkg",
                rcsdroad_path=endpoint_artifacts.corrected_roads,
                out_dir=paths["relations"],
            ),
        )
        _execute_command_stage(
            manifest,
            manifest_path,
            "t01_segment_build",
            [
                sys.executable,
                "-m",
                "rcsd_topo_poc",
                "t01-run-skill-v1",
                "--road-path",
                str(paths["tool5"] / "p02_roads_tool5.gpkg"),
                "--node-path",
                str(paths["tool5"] / "p02_nodes_tool5.gpkg"),
                "--strategy-config",
                str(repo_root / "configs" / "t01_data_preprocess" / "step1_pair_s2.json"),
                "--formway-mode",
                "strict",
                "--left-turn-formway-bit",
                "8",
                "--out-root",
                str(paths["t01"]),
                "--no-debug",
            ],
            paths["t01"] / "t01.log",
            repo_root,
        )
        compat = _execute_stage(
            manifest,
            manifest_path,
            "p02_t05_unavailable_compatibility",
            lambda: _create_t05_compatibility(paths["t05_compat"]),
        )
        t05_artifacts = _execute_stage(
            manifest,
            manifest_path,
            "t05_phase2",
            lambda: run_t05_phase2_rcsd_junctionization_and_relation(
                junction_surface_path=compat["surface"],
                fusion_audit_path=compat["fusion_audit"],
                nodes_path=paths["t01"] / "nodes.gpkg",
                rcsdroad_path=endpoint_artifacts.corrected_roads,
                rcsdnode_path=paths["tool1"] / "RCSDNode.gpkg",
                t02_relation_evidence_path=compat["t02_evidence"],
                t03_relation_evidence_path=compat["t03_evidence"],
                t04_relation_evidence_path=compat["t04_evidence"],
                t07_relation_evidence_path=None,
                t04_surface_path=None,
                t04_summary_path=None,
                t04_audit_path=None,
                t04_case_root=None,
                t10_side_group_endpoint_candidate_path=None,
                t10_pair_anchor_endpoint_cluster_path=None,
                t11_manual_relation_path=relation_artifacts.converted_relations,
                out_root=paths["t05_parent"],
                run_id=paths["t05_run_id"],
                progress=True,
                progress_interval=1000,
                readonly_workers=1,
            ),
        )
        t06_artifacts = _execute_stage(
            manifest,
            manifest_path,
            "t06_step1_step2",
            lambda: run_t06_segment_fusion_precheck(
                swsd_segment_path=paths["t01"] / "segment.gpkg",
                swsd_roads_path=paths["t01"] / "roads.gpkg",
                swsd_nodes_path=paths["t01"] / "nodes.gpkg",
                intersection_match_path=t05_artifacts.relation_geojson_path,
                rcsdroad_path=t05_artifacts.rcsdroad_out_path,
                rcsdnode_path=t05_artifacts.rcsdnode_out_path,
                out_root=paths["t06_parent"],
                run_id=paths["t06_run_id"],
                progress=True,
                write_json_outputs=False,
            ),
        )

        def _run_step3() -> Any:
            with suppress_feature_json_outputs():
                step3 = run_t06_step3_segment_replacement(
                    step2_replaceable_path=t06_artifacts.step2.replaceable_gpkg_path,
                    step2_special_junction_group_audit_path=None,
                    step2_group_replacement_audit_path=None,
                    swsd_segment_path=paths["t01"] / "segment.gpkg",
                    swsd_roads_path=paths["t01"] / "roads.gpkg",
                    swsd_nodes_path=paths["t01"] / "nodes.gpkg",
                    rcsdroad_path=t05_artifacts.rcsdroad_out_path,
                    rcsdnode_path=t05_artifacts.rcsdnode_out_path,
                    out_root=paths["t06_parent"],
                    run_id=paths["t06_run_id"],
                    progress=True,
                )
            run_t06_rcsd_unreplaced_attribution(
                t06_run_root=t06_artifacts.run_root,
                step_output_root=step3.run_root,
                swsd_segment_path=paths["t01"] / "segment.gpkg",
                rcsdroad_path=t05_artifacts.rcsdroad_out_path,
            )
            compact_step3_outputs(step3.step_root)
            return step3

        step3_artifacts = _execute_stage(
            manifest,
            manifest_path,
            "t06_step3",
            _run_step3,
        )
        validation = _execute_stage(
            manifest,
            manifest_path,
            "p02_current_result_validation",
            lambda: _validate_current_result(
                paths=paths,
                endpoint_audit=endpoint_artifacts.audit,
                relation_summary=relation_artifacts.summary,
                t05_summary=t05_artifacts.summary_path,
                t06_step3_root=step3_artifacts.step_root,
            ),
        )
        qgis_package = _execute_stage(
            manifest,
            manifest_path,
            "qgis_package",
            lambda: _package_qgis_inputs(paths, validation),
        )
        if qgis_mode == "required":
            _execute_stage(
                manifest,
                manifest_path,
                "qgis_project",
                lambda: _build_qgis_project(
                    repo_root=repo_root,
                    package_root=paths["qgis"],
                    qgis_python=qgis_python,
                ),
            )
        else:
            manifest["stages"].append(
                {
                    "name": "qgis_project",
                    "status": "skipped_developer_diagnostic",
                    "reason": "--qgis-mode skip",
                }
            )
            _write_json(manifest_path, manifest)

        manifest["status"] = (
            "passed" if qgis_mode == "required" else "passed_without_qgis_developer_diagnostic"
        )
        manifest["finished_at"] = _utc_now()
        manifest["outputs"] = {
            "run_root": str(run_root),
            "validation": str(validation["report_path"]),
            "t01_segment": str(paths["t01"] / "segment.gpkg"),
            "t05_phase2_root": str(t05_artifacts.run_root),
            "t06_run_root": str(t06_artifacts.run_root),
            "frcsd_road": str(step3_artifacts.frcsd_road_gpkg_path),
            "frcsd_node": str(step3_artifacts.frcsd_node_gpkg_path),
            "qgis_package_manifest": str(qgis_package),
            "qgis_project": str(paths["qgis"] / "p02_wuhan_local_analysis.qgz") if qgis_mode == "required" else None,
            "qgis_project_qa": str(paths["qgis"] / "p02_qgis_project_qa.json") if qgis_mode == "required" else None,
        }
        _write_json(manifest_path, manifest)
        return manifest
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["finished_at"] = _utc_now()
        manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
        _write_json(manifest_path, manifest)
        raise


def _stage_paths(run_root: Path, run_id: str) -> dict[str, Any]:
    paths: dict[str, Any] = {
        "run_root": run_root,
        "tool1": run_root / "02_tool1",
        "endpoint": run_root / "02a_rcsd_endpoint_override",
        "tool3": run_root / "04_tool3",
        "tool6": run_root / "05_tool6",
        "manual_override": run_root / "05a_manual_override",
        "tool4": run_root / "06_tool4",
        "tool5": run_root / "07_tool5",
        "relations": run_root / "08_relations",
        "t01": run_root / "09_t01",
        "t05_compat": run_root / "10_t05_compat",
        "t05_parent": run_root / "11_t05",
        "t06_parent": run_root / "12_t06",
        "qa": run_root / "13_qa",
        "qgis": run_root / "14_qgis",
        "t05_run_id": f"{run_id}_t05_phase2",
        "t06_run_id": f"{run_id}_t06",
    }
    for key, path in paths.items():
        if isinstance(path, Path) and key != "run_root":
            path.mkdir(parents=True, exist_ok=True)
    return paths


def _require_raw_inputs(input_root: Path) -> dict[str, Path]:
    if not input_root.is_dir():
        raise NotADirectoryError(input_root)
    result = {name: input_root / name for name in RAW_FILENAMES}
    missing = [name for name, path in result.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"input directory is missing required GeoJSON files: {missing}")
    return result


def _copy_raw_inputs(inputs: dict[str, Path], output_root: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    for name, source in inputs.items():
        destination = output_root / name
        shutil.copy2(source, destination)
        if _sha256(source) != _sha256(destination):
            raise RuntimeError(f"raw input copy hash mismatch: {source}")
        copied[name] = str(destination)
    return copied


def _create_t05_compatibility(output_root: Path) -> dict[str, Path]:
    surface = output_root / "junction_anchor_surface_unavailable.gpkg"
    write_gpkg(
        surface,
        [],
        crs_text="EPSG:3857",
        empty_fields=("surface_id", "mainnodeid", "junction_type", "kind_2", "patch_id"),
        geometry_type="Polygon",
    )
    fusion_audit = output_root / "fusion_audit_unavailable.csv"
    _write_empty_csv(fusion_audit, ("surface_id", "mainnodeid"))
    evidence: dict[str, Path] = {}
    for module in ("t02", "t03", "t04"):
        path = output_root / f"{module}_relation_evidence_unavailable.csv"
        _write_empty_csv(path, ("target_id", "status_suggested", "base_id_candidate"))
        evidence[f"{module}_evidence"] = path
    manifest = {
        "status": "unavailable_empty_compat",
        "reason": "missing_road_surface_divstrip_and_rcsdintersection",
        "surface": str(surface),
        "fusion_audit": str(fusion_audit),
        **{key: str(value) for key, value in evidence.items()},
    }
    _write_json(output_root / "compatibility_manifest.json", manifest)
    return {"surface": surface, "fusion_audit": fusion_audit, **evidence}


def _validate_current_result(
    *,
    paths: dict[str, Any],
    endpoint_audit: Path,
    relation_summary: Path,
    t05_summary: Path,
    t06_step3_root: Path,
) -> dict[str, Any]:
    qa_root: Path = paths["qa"]
    report_path = qa_root / "p02_current_result_validation.json"
    target_audit_path = qa_root / "p02_target_segment_audit.csv"
    checks: list[dict[str, Any]] = []

    def check(name: str, actual: Any, expected: Any) -> None:
        checks.append(
            {
                "name": name,
                "actual": actual,
                "expected": expected,
                "passed": actual == expected,
            }
        )

    raw_counts = {
        name: len(read_vector(paths["tool1"] / name, target_epsg=None).features)
        for name in RAW_FILENAMES
    }
    for name, expected in EXPECTED_RAW_COUNTS.items():
        check(f"raw_count:{name}", raw_counts[name], expected)
    endpoint = _read_json(endpoint_audit)
    check("endpoint_override_count", endpoint["checks"]["confirmed_override_count"], 9)
    check("endpoint_missing_after", endpoint["checks"]["missing_endpoint_count_after"], 0)
    check("endpoint_geometry_unchanged", endpoint["checks"]["geometry_unchanged"], True)
    check("endpoint_only_confirmed_fields_changed", endpoint["checks"]["only_confirmed_fields_changed"], True)
    check("endpoint_crosslid_unused", endpoint["checks"]["crosslid_used"], False)
    check("endpoint_nodelid_unused", endpoint["checks"]["nodelid_used"], False)

    relations = _read_json(relation_summary)
    check("manual_relation_transform_passed", relations["passed"], True)
    check("manual_relation_raw_count", relations["raw_relation_count"], 16)
    check("manual_relation_converted_count", relations["converted_relation_count"], 12)
    check("manual_relation_blocking_count", relations["blocking_row_count"], 0)
    check("t01_segment_count", len(read_vector(paths["t01"] / "segment.gpkg", target_epsg=None).features), 109)

    t05 = _read_json(t05_summary)
    check("t05_passed", t05["passed"], True)
    check("t05_relation_count", t05["intersection_match_all_feature_count"], 12)
    check("t05_relation_failure_count", t05["status_1_count"], 0)
    check("t05_rcsdroad_count", t05["rcsdroad_out_count"], 474)
    check("t05_rcsdnode_count", t05["rcsdnode_out_count"], 660)

    step3_summary = _read_json(t06_step3_root / "t06_step3_summary.json")
    check("t06_replacement_success_count", step3_summary["replacement_unit_success_count"], 7)
    check("t06_frcsd_road_count", step3_summary["frcsd_road_count"], 206)
    check("t06_frcsd_node_count", step3_summary["frcsd_node_count"], 243)
    check("t06_final_topology_fail_count", step3_summary["final_frcsd_topology_fail_count"], 0)

    relation_rows = _read_csv(t06_step3_root / "t06_step3_swsd_frcsd_segment_relation.csv")
    relation_by_segment = {row["swsd_segment_id"]: row for row in relation_rows}
    ownership_rows = _read_csv(t06_step3_root / "t06_rcsd_road_ownership.csv")
    if len({row["rcsd_road_id"] for row in ownership_rows}) != len(ownership_rows):
        checks.append(
            {
                "name": "ownership_road_id_unique",
                "actual": False,
                "expected": True,
                "passed": False,
            }
        )
    else:
        check("ownership_road_id_unique", True, True)
    check("ownership_ledger_count", len(ownership_rows), 474)
    used_rows = [row for row in ownership_rows if row["replacement_status"] == "used"]
    check("ownership_used_road_count", len(used_rows), 62)
    check("ownership_used_single_segment_count", sum(row["owner_type"] == "single_segment" for row in used_rows), 58)
    check("ownership_used_special_internal_unowned_count", sum(row["owner_type"] == "special_junction_internal" for row in used_rows), 3)
    check("ownership_used_connectivity_unowned_count", sum(row["owner_type"] == "multi_segment_connectivity" for row in used_rows), 1)
    check("ownership_used_multi_owner_count", sum("|" in row["owner_segment_id"] for row in used_rows), 0)

    ownership_by_road = {row["rcsd_road_id"]: row for row in ownership_rows}
    for road_id, expected_owner in EXPECTED_ROAD_OWNERS.items():
        check(
            f"road_owner:{road_id}",
            ownership_by_road.get(road_id, {}).get("owner_segment_id"),
            expected_owner,
        )
    check(
        "road_owner_type:5855296278768511",
        ownership_by_road.get("5855296278768511", {}).get("owner_type"),
        "multi_segment_connectivity",
    )
    check(
        "road_owner:5855296278768511",
        ownership_by_road.get("5855296278768511", {}).get("owner_segment_id"),
        "",
    )

    target_rows: list[dict[str, Any]] = []
    for segment_id, expected_status in TARGET_SEGMENT_STATUS.items():
        actual_status = relation_by_segment.get(segment_id, {}).get("relation_status", "missing")
        owner_count = sum(
            row["replacement_status"] == "used" and row["owner_segment_id"] == segment_id
            for row in ownership_rows
        )
        check(f"segment_status:{segment_id}", actual_status, expected_status)
        if segment_id in EXPECTED_USED_OWNER_COUNTS:
            check(
                f"segment_used_owner_count:{segment_id}",
                owner_count,
                EXPECTED_USED_OWNER_COUNTS[segment_id],
            )
        target_rows.append(
            {
                "segment_id": segment_id,
                "expected_status": expected_status,
                "actual_status": actual_status,
                "ordinary_used_owner_count": owner_count,
                "passed": actual_status == expected_status,
            }
        )
    _write_csv(target_audit_path, target_rows, tuple(target_rows[0]))

    gis_layers = [
        paths["tool1"] / "node.geojson",
        paths["tool1"] / "road.geojson",
        paths["tool1"] / "RCSDNode.geojson",
        paths["tool1"] / "RCSDRoad.geojson",
        paths["tool5"] / "p02_nodes_tool5.gpkg",
        paths["tool5"] / "p02_roads_tool5.gpkg",
        paths["t01"] / "segment.gpkg",
        paths["t05_parent"] / paths["t05_run_id"] / "rcsdnode_out.gpkg",
        paths["t05_parent"] / paths["t05_run_id"] / "rcsdroad_out.gpkg",
        t06_step3_root / "t06_frcsd_node.gpkg",
        t06_step3_root / "t06_frcsd_road.gpkg",
    ]
    gis_audit: list[dict[str, Any]] = []
    for path in gis_layers:
        vector = read_vector(path, target_epsg=None)
        invalid = sum(
            feature.geometry is None
            or feature.geometry.is_empty
            or not feature.geometry.is_valid
            for feature in vector.features
        )
        gis_audit.append(
            {
                "path": str(path),
                "feature_count": len(vector.features),
                "crs": vector.output_crs.to_string(),
                "invalid_or_empty_geometry_count": invalid,
            }
        )
    check("gis_invalid_or_empty_geometry_count", sum(row["invalid_or_empty_geometry_count"] for row in gis_audit), 0)
    check("gis_raw_crs", sorted({row["crs"] for row in gis_audit[:4]}), ["EPSG:4326"])
    check("gis_processed_crs", sorted({row["crs"] for row in gis_audit[4:]}), ["EPSG:3857"])

    failures = [item for item in checks if not item["passed"]]
    report = {
        "schema": "p02_wuhan_current_result_validation_v1",
        "status": "passed" if not failures else "failed",
        "checked_at": _utc_now(),
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures,
        "gis": {
            "checked_layer_count": len(gis_audit),
            "layers": gis_audit,
            "silent_fix_performed": False,
        },
        "known_unavailable": {
            "T07": "missing road surface/diversion belt/RCSDIntersection",
            "T03": "missing road surface/diversion belt/RCSDIntersection",
            "T04": "missing road surface/diversion belt/RCSDIntersection",
        },
        "report_path": str(report_path),
        "target_segment_audit": str(target_audit_path),
    }
    _write_json(report_path, report)
    if failures:
        raise RuntimeError(f"P02 current Wuhan result validation failed; see {report_path}")
    return report


def _package_qgis_inputs(paths: dict[str, Any], validation: dict[str, Any]) -> Path:
    qgis_root: Path = paths["qgis"]
    t05_root = paths["t05_parent"] / paths["t05_run_id"]
    t06_root = paths["t06_parent"] / paths["t06_run_id"]
    step1_root = t06_root / "step1_identify_fusion_units"
    step2_root = t06_root / "step2_extract_rcsd_segments"
    step3_root = t06_root / "step3_segment_replacement"
    copies = {
        "data/01_raw/road.geojson": paths["tool1"] / "road.geojson",
        "data/01_raw/node.geojson": paths["tool1"] / "node.geojson",
        "data/01_raw/RCSDRoad.geojson": paths["tool1"] / "RCSDRoad.geojson",
        "data/01_raw/RCSDNode.geojson": paths["tool1"] / "RCSDNode.geojson",
        "data/02a_rcsd_endpoint_override/RCSDRoad_endpoint_override.gpkg": paths["endpoint"] / "RCSDRoad_endpoint_override.gpkg",
        "data/02_t08/p02_nodes_tool3.gpkg": paths["tool3"] / "p02_nodes_tool3.gpkg",
        "data/02_t08/p02_node_error_tool6.gpkg": paths["tool6"] / "p02_node_error_tool6.gpkg",
        "data/02_t08/p02_nodes_tool3_manual_override.gpkg": paths["manual_override"] / "p02_nodes_tool3_manual_override.gpkg",
        "data/02_t08/p02_manual_tool6_override_row.csv": paths["manual_override"] / "p02_manual_tool6_override_row.csv",
        "data/02_t08/p02_roads_tool4.gpkg": paths["tool4"] / "p02_roads_tool4.gpkg",
        "data/02_t08/p02_nodes_tool4.gpkg": paths["tool4"] / "p02_nodes_tool4.gpkg",
        "data/02_t08/p02_audit_nodes_tool4.gpkg": paths["tool4"] / "p02_audit_nodes_tool4.gpkg",
        "data/02_t08/p02_roads_tool5.gpkg": paths["tool5"] / "p02_roads_tool5.gpkg",
        "data/02_t08/p02_nodes_tool5.gpkg": paths["tool5"] / "p02_nodes_tool5.gpkg",
        "data/02_t08/p02_audit_nodes_tool5.gpkg": paths["tool5"] / "p02_audit_nodes_tool5.gpkg",
        "data/03_relations/p02_manual_relations_raw.csv": paths["relations"] / "p02_manual_relations_raw.csv",
        "data/03_relations/p02_manual_relations_converted.csv": paths["relations"] / "p02_manual_relations_converted.csv",
        "data/03_relations/p02_manual_relation_transform_audit.csv": paths["relations"] / "p02_manual_relation_transform_audit.csv",
        "data/04_t01/roads.gpkg": paths["t01"] / "roads.gpkg",
        "data/04_t01/nodes.gpkg": paths["t01"] / "nodes.gpkg",
        "data/04_t01/segment.gpkg": paths["t01"] / "segment.gpkg",
        "data/04_t01/unsegmented_roads.gpkg": paths["t01"] / "unsegmented_roads.gpkg",
        "data/05_t05/intersection_match_all.geojson": t05_root / "intersection_match_all.geojson",
        "data/05_t05/rcsdroad_out.gpkg": t05_root / "rcsdroad_out.gpkg",
        "data/05_t05/rcsdnode_out.gpkg": t05_root / "rcsdnode_out.gpkg",
        "data/05_t05/rcsdroad_split.gpkg": t05_root / "rcsdroad_split.gpkg",
        "data/05_t05/rcsdnode_generated.gpkg": t05_root / "rcsdnode_generated.gpkg",
        "data/05_t05/rcsdnode_grouped.gpkg": t05_root / "rcsdnode_grouped.gpkg",
        "data/05_t05/relation_graph_consumability_audit.csv": t05_root / "relation_graph_consumability_audit.csv",
        "data/06_t06_step1/t06_swsd_segment_final_fusion_units.gpkg": step1_root / "t06_swsd_segment_final_fusion_units.gpkg",
        "data/06_t06_step1/t06_swsd_segment_rejected.gpkg": step1_root / "t06_swsd_segment_rejected.gpkg",
        "data/07_t06_step2/t06_rcsd_segment_replaceable.gpkg": step2_root / "t06_rcsd_segment_replaceable.gpkg",
        "data/07_t06_step2/t06_rcsd_segment_rejected.gpkg": step2_root / "t06_rcsd_segment_rejected.gpkg",
        "data/07_t06_step2/t06_segment_replacement_plan.gpkg": step2_root / "t06_segment_replacement_plan.gpkg",
        "data/07_t06_step2/t06_rcsd_segment_failure_business_audit.gpkg": step2_root / "t06_rcsd_segment_failure_business_audit.gpkg",
        "data/07_t06_step2/t06_segment_replacement_problem_registry.gpkg": step2_root / "t06_segment_replacement_problem_registry.gpkg",
        "data/08_t06_step3/t06_frcsd_road.gpkg": step3_root / "t06_frcsd_road.gpkg",
        "data/08_t06_step3/t06_frcsd_node.gpkg": step3_root / "t06_frcsd_node.gpkg",
        "data/08_t06_step3/t06_step3_replacement_units.gpkg": step3_root / "t06_step3_replacement_units.gpkg",
        "data/08_t06_step3/t06_step3_topology_connectivity_audit.gpkg": step3_root / "t06_step3_topology_connectivity_audit.gpkg",
        "data/08_t06_step3/t06_step3_unreplaced_rcsd_attribution.gpkg": step3_root / "t06_step3_unreplaced_rcsd_attribution.gpkg",
        "data/08_t06_step3/t06_rcsd_road_ownership.gpkg": step3_root / "t06_rcsd_road_ownership.gpkg",
        "data/08_t06_step3/t06_step3_swsd_frcsd_segment_relation.gpkg": step3_root / "t06_step3_swsd_frcsd_segment_relation.gpkg",
        "data/08_t06_step3/t06_step3_added_rcsd_roads.gpkg": step3_root / "t06_step3_added_rcsd_roads.gpkg",
        "data/08_t06_step3/t06_step3_removed_swsd_roads.gpkg": step3_root / "t06_step3_removed_swsd_roads.gpkg",
        "data/09_qa/p02_target_segment_audit.csv": Path(validation["target_segment_audit"]),
    }
    manifest_rows: list[dict[str, Any]] = []
    for relative_path, source in copies.items():
        if not source.is_file():
            raise FileNotFoundError(f"QGIS package source is missing: {source}")
        destination = qgis_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest_rows.append(
            {
                "relative_path": relative_path,
                "source_path": str(source),
                "size_bytes": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )
    package_manifest = qgis_root / "p02_qgis_package_manifest.json"
    _write_json(
        package_manifest,
        {
            "schema": "p02_wuhan_qgis_package_v1",
            "run_id": paths["run_root"].name,
            "status": "packaged",
            "file_path_policy": "project relative paths under 14_qgis/data",
            "file_count": len(manifest_rows),
            "files": manifest_rows,
        },
    )
    return package_manifest


def _build_qgis_project(*, repo_root: Path, package_root: Path, qgis_python: str | None) -> dict[str, Any]:
    executable = _resolve_qgis_python(qgis_python)
    src_root = str(repo_root / "src")
    command = [
        executable,
        "-c",
        (
            f"import sys; sys.path.insert(0, {src_root!r}); "
            "from rcsd_topo_poc.modules.p02_wuhan_local_experiment.qgis_project "
            "import cli; raise SystemExit(cli())"
        ),
        "--package-root",
        str(package_root),
    ]
    log_path = package_root / "p02_qgis_project.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = src_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    _run_command(command, log_path=log_path, cwd=repo_root, env=env)
    qa_path = package_root / "p02_qgis_project_qa.json"
    qa = _read_json(qa_path)
    if qa.get("status") == "failed":
        raise RuntimeError(f"QGIS project QA failed; see {qa_path}")
    return qa


def _resolve_qgis_python(explicit: str | None) -> str:
    requested = explicit or os.environ.get("QGIS_PYTHON_BIN")
    if requested:
        path = Path(requested).expanduser()
        if path.is_file():
            return str(path.resolve())
        resolved = shutil.which(requested)
        if resolved:
            return resolved
        raise FileNotFoundError(f"configured QGIS Python executable not found: {requested}")
    for name in ("python-qgis-ltr", "python-qgis"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidates = sorted(program_files.glob("QGIS */bin/python-qgis-ltr.bat"), reverse=True)
        if candidates:
            return str(candidates[0])
    raise FileNotFoundError(
        "QGIS Python executable not found. Install QGIS LTR or pass --qgis-python /path/to/python-qgis-ltr."
    )


def _execute_stage(
    manifest: dict[str, Any],
    manifest_path: Path,
    name: str,
    action: Callable[[], Any],
) -> Any:
    started = time.perf_counter()
    stage = {"name": name, "status": "running", "started_at": _utc_now()}
    manifest["stages"].append(stage)
    _write_json(manifest_path, manifest)
    try:
        result = action()
    except Exception as exc:
        stage.update(
            {
                "status": "failed",
                "finished_at": _utc_now(),
                "elapsed_seconds": round(time.perf_counter() - started, 6),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        _write_json(manifest_path, manifest)
        raise
    stage.update(
        {
            "status": "passed",
            "finished_at": _utc_now(),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
        }
    )
    _write_json(manifest_path, manifest)
    return result


def _execute_command_stage(
    manifest: dict[str, Any],
    manifest_path: Path,
    name: str,
    command: list[str],
    log_path: Path,
    cwd: Path,
) -> None:
    def action() -> None:
        _run_command(command, log_path=log_path, cwd=cwd)

    before = len(manifest["stages"])
    _execute_stage(manifest, manifest_path, name, action)
    manifest["stages"][before]["command"] = command
    manifest["stages"][before]["log_path"] = str(log_path)
    _write_json(manifest_path, manifest)


def _run_command(
    command: list[str],
    *,
    log_path: Path,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}; see {log_path}"
        )


def _repo_state(repo_root: Path) -> dict[str, str | None]:
    def git(*args: str) -> str | None:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else None

    return {
        "root": str(repo_root),
        "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
    }


def _write_empty_csv(path: Path, fields: tuple[str, ...]) -> None:
    _write_csv(path, [], fields)


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["run_wuhan_internal_case"]
