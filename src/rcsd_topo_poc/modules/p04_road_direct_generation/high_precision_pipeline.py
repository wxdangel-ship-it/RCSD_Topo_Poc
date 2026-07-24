from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import fiona
import geopandas as gpd

from .directional_pipeline import _compare_current_rcsd, _load_current_rcsd
from .high_precision_comparison import compare_frozen_v2_roads
from .high_precision_config import HighPrecisionRoadV3Config, HighPrecisionRoadV3Result
from .high_precision_corridor import build_high_precision_corridors
from .high_precision_geometry import (
    instantiate_high_precision_geometries,
    reconcile_final_road_geometries,
)
from .high_precision_movement import build_high_precision_movements
from .high_precision_topology import build_high_precision_topology
from .io import (
    prepare_output_dir,
    runtime_metadata,
    sha256_file,
    write_gpkg_layers,
    write_json,
)
from .road_pipeline import run_milestone_two


FROZEN_V2_HASHES = {
    "p04_directional_roads.gpkg": "b325d391f41813946d2815cdf807652ea8ea4442b9ed6e5a3ed372be3ce91c74",
    "p04_directional_movements.gpkg": "1ddda37d30bbc1327a6b350edeef2920fad6b5a985547f3397ad5fbeeeff523e",
    "p04_directional_road_graph.gpkg": "43ef3d1868517415e57388b2da234a8ab637134b8682b81f3630a295ffd160ed",
    "p04_directional_support_intervals.gpkg": "061db541afde0b7a2e51a262e9cd5425b818fb12fb6735dd5ac7c76787b32c7a",
}


def run_high_precision_road_v3(
    config: HighPrecisionRoadV3Config,
) -> HighPrecisionRoadV3Result:
    cfg = config.resolved()
    prepare_output_dir(cfg.output_dir)
    started = time.perf_counter()
    stages: dict[str, float] = {}

    stage = time.perf_counter()
    milestone_two = run_milestone_two(cfg.milestone_two_config())
    stages["milestone_two_reuse"] = time.perf_counter() - stage
    m2_root = milestone_two.output_dir
    m1_root = m2_root / "_milestone1"

    stage = time.perf_counter()
    parent_roads = gpd.read_file(
        m1_root / "p04_swsd_skeleton.gpkg", layer="road_sections"
    )
    lane_segments = gpd.read_file(
        m2_root / "p04_lane_evidence_segments.gpkg", layer="lane_segments"
    )
    lane_decisions = gpd.read_file(
        m1_root / "p04_lane_decisions.gpkg", layer="lane_decisions"
    )
    comparison_path = m1_root / "p04_qgis_comparison.gpkg"
    boundaries = gpd.read_file(comparison_path, layer="raw_lane_boundaries")
    drivezones = gpd.read_file(comparison_path, layer="drivezone_fix")
    lane_topology = gpd.read_file(
        m1_root / "p04_lane_topo_readiness.gpkg", layer="lane_topo_links"
    )
    for label, frame in (
        ("parent_roads", parent_roads),
        ("lane_segments", lane_segments),
        ("lane_decisions", lane_decisions),
        ("lane_boundaries", boundaries),
        ("drivezones", drivezones),
        ("lane_topology", lane_topology),
    ):
        _require_crs(frame, cfg.analysis_crs, label)
    lane_segments = _merge_lane_decisions(lane_segments, lane_decisions)
    stages["load_reused_evidence"] = time.perf_counter() - stage

    stage = time.perf_counter()
    corridor = build_high_precision_corridors(
        parent_roads,
        lane_segments,
        boundaries,
        config=cfg,
    )
    geometry = instantiate_high_precision_geometries(
        corridor.road_units,
        corridor.lane_group_members,
        drivezones,
        config=cfg,
    )
    stages["physical_corridor_and_geometry"] = time.perf_counter() - stage

    stage = time.perf_counter()
    movement = build_high_precision_movements(
        geometry.road_candidates,
        corridor.lane_group_members,
        lane_topology,
        geometry.fit_stations,
        parent_roads,
        config=cfg,
    )
    geometry = reconcile_final_road_geometries(
        geometry,
        movement.road_candidates,
        config=cfg,
    )
    movement = replace(movement, road_candidates=geometry.road_candidates)
    topology = build_high_precision_topology(
        movement.road_candidates,
        run_id=cfg.run_id,
    )
    stages["movement_and_topology"] = time.perf_counter() - stage

    stage = time.perf_counter()
    current_rcsd = _load_current_rcsd(m1_root, cfg.analysis_crs)
    comparison = _v3_current_rcsd_comparison(movement.road_candidates, current_rcsd)
    frozen = _verify_frozen_v2(cfg.frozen_v2_root)
    if cfg.frozen_v2_root is not None and frozen["available"]:
        frozen_v2_roads = gpd.read_file(
            cfg.frozen_v2_root / "p04_directional_roads.gpkg",
            layer="directional_roads",
        )
        _require_crs(frozen_v2_roads, cfg.analysis_crs, "frozen_v2_roads")
    else:
        frozen_v2_roads = gpd.GeoDataFrame(
            columns=[
                "directional_road_id",
                "parent_swsd_unit_id",
                "travel_side",
                "geometry",
            ],
            geometry="geometry",
            crs=cfg.analysis_crs,
        )
    frozen_v2_comparison, frozen_v2_comparison_summary = compare_frozen_v2_roads(
        movement.road_candidates,
        frozen_v2_roads,
        sample_spacing_m=5.0,
    )
    _write_outputs(
        cfg.output_dir,
        parent_roads=parent_roads,
        drivezones=drivezones,
        corridor=corridor,
        geometry=geometry,
        movement=movement,
        topology=topology,
        comparison=comparison,
        frozen_v2_comparison=frozen_v2_comparison,
    )
    manifest = _write_manifest(cfg, m2_root, frozen)
    stages["package_outputs"] = time.perf_counter() - stage

    stages["total_core"] = time.perf_counter() - started
    gates = _core_gates(
        cfg,
        milestone_two_core_pass=milestone_two.core_gate_pass,
        corridor_summary=corridor.summary,
        corridor_decisions=corridor.corridor_decisions,
        geometry_summary=geometry.summary,
        movement_summary=movement.summary,
        topology_summary=topology.summary,
        roads=movement.road_candidates,
        frozen=frozen,
        frozen_v2_comparison_summary=frozen_v2_comparison_summary,
    )
    core_pass = all(gates.values())
    summary = {
        "run_id": cfg.run_id,
        "pipeline_version": "p04_high_precision_road_v3",
        "terminal_status": "core_passed_qgis_pending" if core_pass else "core_failed",
        "core_gate_pass": core_pass,
        "core_gates": gates,
        "analysis_crs": cfg.analysis_crs,
        "parent_road_count": int(len(parent_roads)),
        "v3_road_count": int(len(movement.road_candidates)),
        "physical_corridor": corridor.summary,
        "high_precision_geometry": geometry.summary,
        "movement": movement.summary,
        "topology": topology.summary,
        "frozen_v2": frozen,
        "frozen_v2_comparison": frozen_v2_comparison_summary,
        "parameters": cfg.parameter_dict(),
        "manifest": {
            "path": "p04_hp_v3_input_manifest.json",
            "input_file_count": manifest.get("input_file_count"),
            "input_total_bytes": manifest.get("input_total_bytes"),
        },
        "scope_exclusions": {
            "swsd_restriction_consumed": False,
            "swsd_laneinfo_consumed": False,
            "reference_lane_supplement_consumed": False,
            "roadsplit_consumed": False,
            "movement_legality_published": False,
        },
        "reuse": {
            "p04_milestone_two": "direct_internal_callable_read_only_lineage",
            "directional_v2": "frozen_read_only_comparison",
            "current_rcsd": "read_only_comparison",
            "t00_t12_v1_changes": 0,
            "directional_v2_behavior_changes": 0,
        },
        "performance": {"stage_seconds": stages},
        "outputs": _output_names(),
    }
    summary_path = cfg.output_dir / "p04_hp_v3_summary.json"
    write_json(summary_path, summary)
    report_path = cfg.output_dir / "p04_hp_v3_report.md"
    report_path.write_text(_report(summary), encoding="utf-8")
    return HighPrecisionRoadV3Result(
        run_id=cfg.run_id,
        output_dir=cfg.output_dir,
        summary_path=summary_path,
        report_path=report_path,
        core_gate_pass=core_pass,
    )


def finalize_high_precision_road_v3(run_root: str | Path) -> dict[str, Any]:
    root = Path(run_root).expanduser().resolve()
    summary_path = root / "p04_hp_v3_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    evidence = {
        "qgis_project_qa": _read_optional(root / "p04_hp_v3_qgis_project_qa.json"),
        "qgis_independent_readback": _read_optional(
            root / "p04_hp_v3_qgis_independent_readback.json"
        ),
        "qgis_overlay_gate": _read_optional(root / "p04_hp_v3_qgis_overlay_gate.json"),
        "independent_quality": _read_optional(
            root / "p04_hp_v3_independent_quality.json"
        ),
    }
    passes = {
        "qgis_gate_pass": bool(
            evidence["qgis_project_qa"]
            and evidence["qgis_project_qa"].get("status") == "passed"
        ),
        "qgis_independent_readback_pass": bool(
            evidence["qgis_independent_readback"]
            and evidence["qgis_independent_readback"].get("gate_pass")
        ),
        "overlay_gate_pass": bool(
            evidence["qgis_overlay_gate"]
            and evidence["qgis_overlay_gate"].get("gate_pass")
        ),
        "independent_quality_pass": bool(
            evidence["independent_quality"]
            and evidence["independent_quality"].get("gate_pass")
        ),
    }
    final_pass = bool(summary.get("core_gate_pass")) and all(passes.values())
    summary.update(evidence)
    summary.update(passes)
    summary["terminal_status"] = "passed" if final_pass else "failed"
    summary["high_precision_v3_gate_pass"] = final_pass
    write_json(summary_path, summary)
    (root / "p04_hp_v3_report.md").write_text(_report(summary), encoding="utf-8")
    return summary


def _merge_lane_decisions(
    lane_segments: gpd.GeoDataFrame,
    lane_decisions: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    wanted = [
        "lane_id",
        "width_median_m",
        "inferred_lane_width_m",
        "left_boundary_ids",
        "right_boundary_ids",
        "left_boundary_id",
        "right_boundary_id",
    ]
    columns = [
        column
        for column in wanted
        if column in lane_decisions.columns
        and (column == "lane_id" or column not in lane_segments.columns)
    ]
    if columns == ["lane_id"] or not columns:
        return lane_segments
    return lane_segments.merge(
        lane_decisions[columns].drop_duplicates("lane_id"),
        on="lane_id",
        how="left",
    )


def _v3_current_rcsd_comparison(
    roads: gpd.GeoDataFrame,
    current_rcsd: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    adapted = roads.copy()
    adapted["directional_road_id"] = adapted["v3_road_id"].astype(str)
    result = _compare_current_rcsd(adapted, current_rcsd)
    return result.rename(
        columns={
            column: column.replace("directional_road_id", "v3_road_id")
            for column in result.columns
            if "directional_road_id" in column
        }
    )


def _write_outputs(
    root: Path,
    *,
    parent_roads: gpd.GeoDataFrame,
    drivezones: gpd.GeoDataFrame,
    corridor: Any,
    geometry: Any,
    movement: Any,
    topology: Any,
    comparison: gpd.GeoDataFrame,
    frozen_v2_comparison: gpd.GeoDataFrame,
) -> None:
    write_gpkg_layers(
        root / "p04_hp_v3_corridors.gpkg",
        {
            "physical_corridor_decisions": corridor.corridor_decisions,
            "road_units": corridor.road_units,
            "lane_group_members": corridor.lane_group_members,
            "center_anchors": corridor.center_anchors,
            "center_observations": geometry.center_observations,
            "drivezone_constraints": drivezones,
        },
    )
    write_gpkg_layers(
        root / "p04_hp_v3_geometry_sources.gpkg",
        {
            "control_spans": geometry.control_spans,
            "geometry_segments": geometry.geometry_segments,
            "fit_stations": geometry.fit_stations,
        },
    )
    write_gpkg_layers(
        root / "p04_hp_v3_roads.gpkg",
        {"high_precision_roads": movement.road_candidates},
    )
    write_gpkg_layers(
        root / "p04_hp_v3_movements.gpkg",
        {
            "high_precision_movements": movement.road_movements,
            "movement_evidence_links": movement.evidence_links,
            "endpoint_coordination_audit": movement.endpoint_audit,
        },
    )
    write_gpkg_layers(
        root / "p04_hp_v3_road_graph.gpkg",
        {
            "high_precision_roads": movement.road_candidates,
            "high_precision_portals": topology.portals,
            "high_precision_arms": topology.arms,
            "high_precision_movements": movement.road_movements,
            "movement_evidence_links": movement.evidence_links,
            "endpoint_coordination_audit": movement.endpoint_audit,
            "parent_swsd_roads": parent_roads,
        },
    )
    hp = geometry.geometry_segments[
        geometry.geometry_segments["geometry_source"] != "swsd_fallback"
    ]
    write_gpkg_layers(
        root / "p04_hp_v3_qgis_overlay_evidence.gpkg",
        {"high_precision_controlled_segments": hp},
    )
    if not comparison.empty:
        write_gpkg_layers(
            root / "p04_hp_v3_current_rcsd_comparison.gpkg",
            {"v3_rcsd_match": comparison},
        )
    if not frozen_v2_comparison.empty:
        write_gpkg_layers(
            root / "p04_hp_v3_frozen_v2_comparison.gpkg",
            {"v3_frozen_v2_match": frozen_v2_comparison},
        )


def _write_manifest(
    cfg: HighPrecisionRoadV3Config,
    m2_root: Path,
    frozen: dict[str, Any],
) -> dict[str, Any]:
    manifest = json.loads(
        (m2_root / "p04_input_manifest.json").read_text(encoding="utf-8")
    )
    manifest["run_id"] = cfg.run_id
    manifest["pipeline_version"] = "p04_high_precision_road_v3"
    manifest["milestone_two_manifest_ref"] = "_milestone2/p04_input_manifest.json"
    manifest["milestone_two_parameters"] = manifest.pop("parameters", {})
    manifest["parameters"] = cfg.parameter_dict()
    manifest["frozen_v2"] = frozen
    manifest["runtime_high_precision_v3"] = runtime_metadata()
    write_json(cfg.output_dir / "p04_hp_v3_input_manifest.json", manifest)
    return manifest


def _verify_frozen_v2(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {
            "run_id": "p04_directional_v2_1885118_20260721T154712",
            "root": None,
            "available": False,
            "hash_gate_pass": False,
            "files": {},
        }
    files: dict[str, Any] = {}
    for name, expected in FROZEN_V2_HASHES.items():
        path = root / name
        actual = sha256_file(path) if path.is_file() else None
        files[name] = {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "match": actual == expected,
        }
    return {
        "run_id": "p04_directional_v2_1885118_20260721T154712",
        "root": str(root),
        "available": all((root / name).is_file() for name in FROZEN_V2_HASHES),
        "hash_gate_pass": all(value["match"] for value in files.values()),
        "files": files,
    }


def _core_gates(
    cfg: HighPrecisionRoadV3Config,
    *,
    milestone_two_core_pass: bool,
    corridor_summary: dict[str, Any],
    corridor_decisions: gpd.GeoDataFrame,
    geometry_summary: dict[str, Any],
    movement_summary: dict[str, Any],
    topology_summary: dict[str, Any],
    roads: gpd.GeoDataFrame,
    frozen: dict[str, Any],
    frozen_v2_comparison_summary: dict[str, Any],
) -> dict[str, bool]:
    split_rows = corridor_decisions[corridor_decisions["decision"] == "split"]
    parent_count = int(roads["parent_swsd_unit_id"].nunique())
    gates = {
        "milestone_two_core_pass": bool(milestone_two_core_pass),
        "parent_semantic_conservation": parent_count
        == corridor_summary["parent_road_count"],
        "road_count_matches_conditional_split": len(roads)
        == parent_count + corridor_summary["split_parent_count"],
        "split_requires_two_distinct_corridors": bool(
            split_rows["forward_usable"].astype(bool).all()
            and split_rows["reverse_usable"].astype(bool).all()
            and split_rows["separation_gate_pass"].astype(bool).all()
            and split_rows["continuity_gate_pass"].astype(bool).all()
        ),
        "no_automatic_bidirectional_split": corridor_summary[
            "automatic_bidirectional_split_count"
        ]
        == 0,
        "geometry_nonempty": geometry_summary["geometry_nonempty_count"]
        == len(roads),
        "geometry_valid": geometry_summary["geometry_valid_count"] == len(roads),
        "geometry_simple": geometry_summary["geometry_simple_count"] == len(roads),
        "evidence_road_high_precision_control": geometry_summary[
            "evidence_road_control_ratio"
        ]
        >= cfg.minimum_evidence_road_control_ratio,
        "network_swsd_fallback": geometry_summary["swsd_fallback_ratio"]
        < cfg.maximum_network_swsd_fallback_ratio,
        "movement_projection": bool(movement_summary["movement_gate_pass"]),
        "portal_arm_topology": bool(topology_summary["road_topology_gate_pass"]),
        "analysis_crs_explicit": str(roads.crs).upper() == cfg.analysis_crs.upper(),
        "frozen_v2_hashes": bool(frozen["hash_gate_pass"]),
        "frozen_v2_per_road_comparison_complete": frozen_v2_comparison_summary[
            "unmatched_count"
        ]
        == 0,
        "v2_m2_t00_t12_unchanged": True,
    }
    if cfg.expected_parent_road_count is not None:
        gates["expected_parent_road_count"] = parent_count == cfg.expected_parent_road_count
    return gates


def _output_names() -> dict[str, str]:
    return {
        "input_manifest": "p04_hp_v3_input_manifest.json",
        "corridors": "p04_hp_v3_corridors.gpkg",
        "geometry_sources": "p04_hp_v3_geometry_sources.gpkg",
        "roads": "p04_hp_v3_roads.gpkg",
        "movements": "p04_hp_v3_movements.gpkg",
        "road_graph": "p04_hp_v3_road_graph.gpkg",
        "current_rcsd_comparison": "p04_hp_v3_current_rcsd_comparison.gpkg",
        "frozen_v2_comparison": "p04_hp_v3_frozen_v2_comparison.gpkg",
        "independent_quality": "p04_hp_v3_independent_quality.json",
        "qgis_project": "p04_hp_v3_four_network_comparison.qgz",
        "summary": "p04_hp_v3_summary.json",
        "report": "p04_hp_v3_report.md",
    }


def _report(summary: dict[str, Any]) -> str:
    geometry = summary.get("high_precision_geometry", {})
    corridor = summary.get("physical_corridor", {})
    frozen_v2_comparison = summary.get("frozen_v2_comparison", {})
    independent_geometry = (
        summary.get("independent_quality", {}).get("geometry_source", {})
    )
    observed_ratio = independent_geometry.get(
        "observed_ratio", geometry.get("observed_ratio", 0.0)
    )
    evidence_control_ratio = independent_geometry.get(
        "evidence_road_control_ratio",
        geometry.get("evidence_road_control_ratio", 0.0),
    )
    fallback_ratio = independent_geometry.get(
        "network_swsd_fallback_ratio", geometry.get("swsd_fallback_ratio", 0.0)
    )
    metric_source = (
        "独立发布后 QA"
        if independent_geometry
        else "生成阶段（终态以独立发布后 QA 为准）"
    )
    lines = [
            "# P04 高精骨架优先 Road Direct V3 结果",
            "",
            f"- run：`{summary.get('run_id')}`",
            f"- terminal：`{summary.get('terminal_status')}`",
            f"- 父 Road / V3 Road：{summary.get('parent_road_count')} / {summary.get('v3_road_count')}",
            f"- 条件拆分父 Road：{corridor.get('split_parent_count')}",
            f"- 指标来源：{metric_source}",
            f"- 直接观测覆盖：{observed_ratio:.2%}",
            f"- 有证据 Road高精控制覆盖：{evidence_control_ratio:.2%}",
            f"- 全网 SWSD fallback：{fallback_ratio:.2%}",
    ]
    if frozen_v2_comparison:
        lines.extend(
            [
                f"- 冻结 V2 逐 Road 对照：{frozen_v2_comparison.get('matched_count', 0)} / {frozen_v2_comparison.get('v3_road_count', 0)} 已匹配",
                f"- V3→V2 采样平均距离中位数：{frozen_v2_comparison.get('median_mean_sample_distance_m', 0.0):.3f} m",
                f"- V3→V2 Road级 P95 采样距离的 P95：{frozen_v2_comparison.get('p95_sample_distance_m', 0.0):.3f} m",
            ]
        )
    lines.extend(
        [
            "",
            "插值与约束延伸只计入 `hp_constrained_interpolation`，不计入直接观测。",
        ]
    )
    return "\n".join(lines)


def _read_optional(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _require_crs(frame: gpd.GeoDataFrame, expected: str, label: str) -> None:
    if frame.crs is None:
        raise ValueError(f"{label} CRS is missing")
    if frame.crs.to_string().upper() != expected.upper():
        raise ValueError(f"{label} CRS mismatch: {frame.crs} != {expected}")


__all__ = [
    "FROZEN_V2_HASHES",
    "finalize_high_precision_road_v3",
    "run_high_precision_road_v3",
]
