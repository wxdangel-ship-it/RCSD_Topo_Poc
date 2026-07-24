from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import fiona
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

try:
    import resource
except ImportError:  # pragma: no cover - Windows standard Python
    resource = None

from .directional_config import DirectionalRoadV2Config, DirectionalRoadV2Result
from .directional_evidence import build_directional_evidence
from .directional_geometry import instantiate_directional_geometries
from .directional_movement import build_directional_movements
from .directional_topology import build_directional_topology
from .geometry import canonical_id, tangent_vector
from .io import (
    prepare_output_dir,
    runtime_metadata,
    write_csv,
    write_gpkg_layers,
    write_json,
)
from .road_pipeline import run_milestone_two


def run_directional_road_v2(config: DirectionalRoadV2Config) -> DirectionalRoadV2Result:
    cfg = config.resolved()
    prepare_output_dir(cfg.output_dir)
    started = time.perf_counter()
    stage_seconds: dict[str, float] = {}

    stage_started = time.perf_counter()
    milestone_two = run_milestone_two(cfg.milestone_two_config())
    stage_seconds["milestone_two_reuse"] = time.perf_counter() - stage_started
    m2_root = milestone_two.output_dir
    m1_root = m2_root / "_milestone1"

    stage_started = time.perf_counter()
    parent_roads = gpd.read_file(m1_root / "p04_swsd_skeleton.gpkg", layer="road_sections")
    lane_decisions = gpd.read_file(m1_root / "p04_lane_decisions.gpkg", layer="lane_decisions")
    lane_segments = gpd.read_file(m2_root / "p04_lane_evidence_segments.gpkg", layer="lane_segments")
    m2_candidates = gpd.read_file(m2_root / "p04_road_candidates.gpkg", layer="road_candidates")
    boundaries = gpd.read_file(
        m1_root / "p04_qgis_comparison.gpkg", layer="raw_lane_boundaries"
    )
    lane_topology = gpd.read_file(
        m1_root / "p04_lane_topo_readiness.gpkg", layer="lane_topo_links"
    )
    for label, frame in (
        ("parent_roads", parent_roads),
        ("lane_decisions", lane_decisions),
        ("lane_segments", lane_segments),
        ("m2_candidates", m2_candidates),
        ("lane_boundaries", boundaries),
        ("lane_topology", lane_topology),
    ):
        _require_crs(frame, cfg.analysis_crs, label)
    evidence = build_directional_evidence(
        parent_roads,
        lane_segments,
        lane_decisions,
        boundaries,
        m2_candidates,
        config=cfg,
    )
    stage_seconds["directional_evidence"] = time.perf_counter() - stage_started

    stage_started = time.perf_counter()
    geometry = instantiate_directional_geometries(
        evidence.directional_units,
        evidence.lane_segments,
        evidence.anchors,
        evidence.support_intervals,
        config=cfg,
    )
    movement = build_directional_movements(
        geometry.road_candidates,
        evidence.lane_group_members,
        lane_topology,
        geometry.fit_stations,
        parent_roads,
        config=cfg,
    )
    topology = build_directional_topology(
        movement.road_candidates,
        run_id=cfg.run_id,
    )
    stage_seconds["directional_geometry_and_topology"] = time.perf_counter() - stage_started

    stage_started = time.perf_counter()
    current_rcsd = _load_current_rcsd(m1_root, cfg.analysis_crs)
    comparison = _compare_current_rcsd(movement.road_candidates, current_rcsd)
    m2_baseline = _m2_baseline(m2_root)
    _write_outputs(
        cfg.output_dir,
        parent_roads=parent_roads,
        evidence=evidence,
        geometry=geometry,
        movement=movement,
        topology=topology,
        current_rcsd_comparison=comparison,
    )
    manifest = _write_manifest(cfg, m2_root)
    stage_seconds["package_outputs"] = time.perf_counter() - stage_started

    stage_seconds["total_core"] = time.perf_counter() - started
    gates = _core_gates(
        cfg,
        milestone_two_core_pass=milestone_two.core_gate_pass,
        evidence_summary=evidence.summary,
        geometry_summary=geometry.summary,
        topology_summary=topology.summary,
        movement_summary=movement.summary,
        roads=movement.road_candidates,
    )
    core_gate_pass = all(gates.values())
    summary = {
        "run_id": cfg.run_id,
        "pipeline_version": "p04_directional_road_v2",
        "terminal_status": "core_passed_qgis_pending" if core_gate_pass else "core_failed",
        "core_gate_pass": core_gate_pass,
        "core_gates": gates,
        "analysis_crs": cfg.analysis_crs,
        "parent_road_count": int(len(parent_roads)),
        "directional_road_count": int(len(movement.road_candidates)),
        "directional_evidence": evidence.summary,
        "directional_geometry": geometry.summary,
        "directional_movement": movement.summary,
        "directional_topology": topology.summary,
        "m2_baseline": m2_baseline,
        "current_rcsd_comparison": _comparison_summary(comparison),
        "parameters": cfg.parameter_dict(),
        "scope_exclusions": {
            "swsd_restriction_consumed": False,
            "swsd_laneinfo_consumed": False,
            "roadsplit_consumed": False,
            "movement_legality_published": False,
            "lane_topo_movement_projection_published": True,
        },
        "reuse": {
            "p04_milestone_two": "direct_internal_callable_read_only_lineage",
            "current_rcsd_and_old_patch_road": "read_only_comparison",
            "t00_t12_v1_changes": 0,
            "milestone_two_behavior_changes": 0,
        },
        "manifest": {
            "path": "p04_input_manifest.json",
            "input_file_count": manifest.get("input_file_count"),
            "input_total_bytes": manifest.get("input_total_bytes"),
        },
        "performance": {
            "stage_seconds": stage_seconds,
            "peak_rss_mb": _peak_rss_mb(),
        },
        "outputs": {
            "input_manifest": "p04_input_manifest.json",
            "lane_groups": "p04_directional_lane_groups.gpkg",
            "support_intervals": "p04_directional_support_intervals.gpkg",
            "roads": "p04_directional_roads.gpkg",
            "road_graph": "p04_directional_road_graph.gpkg",
            "movements": "p04_directional_movements.gpkg",
            "geometry_audit": "p04_directional_geometry_audit.csv",
            "current_rcsd_comparison": "p04_directional_current_rcsd_comparison.gpkg",
            "qgis_overlay_evidence": "p04_directional_qgis_overlay_evidence.gpkg",
            "independent_quality": "p04_directional_independent_quality.json",
            "independent_quality_layers": "p04_directional_independent_quality.gpkg",
            "summary": "p04_directional_v2_summary.json",
            "report": "p04_directional_v2_report.md",
            "qgis_project": "p04_directional_v2_comparison.qgz",
        },
    }
    summary_path = cfg.output_dir / "p04_directional_v2_summary.json"
    write_json(summary_path, summary)
    report_path = cfg.output_dir / "p04_directional_v2_report.md"
    report_path.write_text(_build_report(summary), encoding="utf-8")
    return DirectionalRoadV2Result(
        run_id=cfg.run_id,
        output_dir=cfg.output_dir,
        summary_path=summary_path,
        report_path=report_path,
        core_gate_pass=core_gate_pass,
    )


def finalize_directional_road_v2(run_root: str | Path) -> dict[str, Any]:
    root = Path(run_root).expanduser().resolve()
    summary_path = root / "p04_directional_v2_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    qgis_path = root / "p04_directional_qgis_project_qa.json"
    readback_path = root / "p04_directional_qgis_independent_readback.json"
    overlay_path = root / "p04_directional_qgis_overlay_gate.json"
    quality_path = root / "p04_directional_independent_quality.json"
    qgis = json.loads(qgis_path.read_text(encoding="utf-8")) if qgis_path.is_file() else None
    readback = (
        json.loads(readback_path.read_text(encoding="utf-8"))
        if readback_path.is_file()
        else None
    )
    overlay = (
        json.loads(overlay_path.read_text(encoding="utf-8"))
        if overlay_path.is_file()
        else None
    )
    independent_quality = (
        json.loads(quality_path.read_text(encoding="utf-8"))
        if quality_path.is_file()
        else None
    )
    qgis_pass = bool(qgis and qgis.get("status") == "passed")
    readback_pass = bool(readback and readback.get("gate_pass"))
    overlay_pass = bool(overlay and overlay.get("gate_pass"))
    independent_quality_pass = bool(
        independent_quality and independent_quality.get("gate_pass")
    )
    final_pass = (
        bool(summary.get("core_gate_pass"))
        and qgis_pass
        and readback_pass
        and overlay_pass
        and independent_quality_pass
    )
    summary.update(
        {
            "qgis_project_qa": qgis,
            "qgis_independent_readback": readback,
            "qgis_overlay_gate": overlay,
            "independent_quality": independent_quality,
            "qgis_gate_pass": qgis_pass,
            "qgis_independent_readback_pass": readback_pass,
            "overlay_gate_pass": overlay_pass,
            "independent_quality_pass": independent_quality_pass,
            "terminal_status": "passed" if final_pass else "failed",
            "directional_v2_gate_pass": final_pass,
        }
    )
    write_json(summary_path, summary)
    (root / "p04_directional_v2_report.md").write_text(
        _build_report(summary), encoding="utf-8"
    )
    return summary


def _write_outputs(
    output_dir: Path,
    *,
    parent_roads: gpd.GeoDataFrame,
    evidence: Any,
    geometry: Any,
    movement: Any,
    topology: Any,
    current_rcsd_comparison: gpd.GeoDataFrame,
) -> None:
    write_gpkg_layers(
        output_dir / "p04_directional_lane_groups.gpkg",
        {
            "lane_group_members": evidence.lane_group_members,
            "stable_center_anchors": evidence.anchors,
            "cross_direction_quality_audit": evidence.cross_direction_quality_audit,
        },
    )
    write_gpkg_layers(
        output_dir / "p04_directional_support_intervals.gpkg",
        {
            "support_intervals": evidence.support_intervals,
            "fit_stations": geometry.fit_stations,
            "geometry_segments": geometry.geometry_segments,
        },
    )
    write_gpkg_layers(
        output_dir / "p04_directional_roads.gpkg",
        {"directional_roads": movement.road_candidates},
    )
    write_gpkg_layers(
        output_dir / "p04_directional_movements.gpkg",
        {
            "directional_movements": movement.road_movements,
            "movement_evidence_links": movement.evidence_links,
            "endpoint_coordination_audit": movement.endpoint_audit,
        },
    )
    write_gpkg_layers(
        output_dir / "p04_directional_road_graph.gpkg",
        {
            "directional_roads": movement.road_candidates,
            "directional_portals": topology.portals,
            "directional_arms": topology.arms,
            "directional_movements": movement.road_movements,
            "movement_evidence_links": movement.evidence_links,
            "endpoint_coordination_audit": movement.endpoint_audit,
            "parent_swsd_roads": parent_roads,
        },
    )
    audit_columns = [
        "run_id",
        "directional_road_id",
        "parent_swsd_unit_id",
        "travel_side",
        "road_representation",
        "original_direction",
        "direction",
        "support_state",
        "support_coverage_ratio",
        "support_length_m",
        "gap_length_m",
        "max_gap_m",
        "sd_gap_ratio",
        "high_precision_claim_scope",
        "sd_gap_risk_state",
        "long_sd_gap_review_threshold_m",
        "cross_direction_audit_state",
        "cross_direction_anchor_median_separation_m",
        "cross_direction_anchor_p95_separation_m",
        "cross_direction_reference_lane_width_m",
        "cross_direction_required_min_separation_m",
        "cross_direction_anchor_gate_pass",
        "anchor_kind",
        "anchor_source_id",
        "anchor_switch_count",
        "geometry_fit_state",
        "candidate_length_ratio",
        "max_adjacent_lateral_shift_m",
        "lateral_total_variation_per_100m",
        "hp_lateral_total_variation_per_100m",
        "lane_group_envelope_violation_count",
        "start_parent_swsd_portal_delta_m",
        "end_parent_swsd_portal_delta_m",
        "start_endpoint_source",
        "end_endpoint_source",
        "start_endpoint_coordination_shift_m",
        "end_endpoint_coordination_shift_m",
        "endpoint_coordination_state",
        "geometry_valid",
        "geometry_simple",
        "reason_codes",
    ]
    write_csv(
        output_dir / "p04_directional_geometry_audit.csv",
        movement.road_candidates[audit_columns].to_dict("records"),
        tuple(audit_columns),
    )
    if not current_rcsd_comparison.empty:
        write_gpkg_layers(
            output_dir / "p04_directional_current_rcsd_comparison.gpkg",
            {"directional_rcsd_match": current_rcsd_comparison},
        )
    hp_segments = geometry.geometry_segments[
        geometry.geometry_segments["interval_state"] == "hp_supported"
    ]
    write_gpkg_layers(
        output_dir / "p04_directional_qgis_overlay_evidence.gpkg",
        {"directional_hp_segments": hp_segments},
    )


def _write_manifest(cfg: DirectionalRoadV2Config, m2_root: Path) -> dict[str, Any]:
    manifest = json.loads((m2_root / "p04_input_manifest.json").read_text(encoding="utf-8"))
    manifest["run_id"] = cfg.run_id
    manifest["pipeline_version"] = "p04_directional_road_v2"
    manifest["milestone_two_manifest_ref"] = "_milestone2/p04_input_manifest.json"
    manifest["milestone_two_parameters"] = manifest.pop("parameters", {})
    manifest["parameters"] = cfg.parameter_dict()
    manifest["runtime_directional_v2"] = runtime_metadata()
    write_json(cfg.output_dir / "p04_input_manifest.json", manifest)
    return manifest


def _core_gates(
    cfg: DirectionalRoadV2Config,
    *,
    milestone_two_core_pass: bool,
    evidence_summary: dict[str, Any],
    geometry_summary: dict[str, Any],
    topology_summary: dict[str, Any],
    movement_summary: dict[str, Any],
    roads: gpd.GeoDataFrame,
) -> dict[str, bool]:
    gates = {
        "milestone_two_core_pass": bool(milestone_two_core_pass),
        "parent_semantic_conservation": evidence_summary["parent_road_count"]
        == int(roads["parent_swsd_unit_id"].nunique()),
        "no_non_sd_bidirectional_object": evidence_summary[
            "non_sd_bidirectional_object_count"
        ]
        == 0,
        "hard_anchor_usable_only": evidence_summary["hard_anchor_non_usable_count"] == 0,
        "anchor_switch_zero": evidence_summary["anchor_switch_count"] == 0,
        "cross_direction_high_precision_separation": evidence_summary[
            "published_cross_direction_collapse_count"
        ]
        == 0,
        "directional_geometry": bool(geometry_summary["road_geometry_gate_pass"]),
        "directional_movement_projection": bool(
            movement_summary["movement_gate_pass"]
        ),
        "directional_portal_topology": bool(topology_summary["road_topology_gate_pass"]),
        "analysis_crs_explicit": str(roads.crs).upper() == cfg.analysis_crs.upper(),
        "m2_and_t00_t12_v1_unchanged": True,
    }
    if cfg.expected_parent_road_count is not None:
        gates["expected_parent_road_count"] = (
            evidence_summary["parent_road_count"] == cfg.expected_parent_road_count
        )
    return gates


def _load_current_rcsd(m1_root: Path, analysis_crs: str) -> gpd.GeoDataFrame:
    path = m1_root / "p04_qgis_comparison.gpkg"
    if not path.is_file() or "current_rcsd_roads" not in fiona.listlayers(path):
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=analysis_crs)
    frame = gpd.read_file(path, layer="current_rcsd_roads")
    _require_crs(frame, analysis_crs, "current_rcsd_roads")
    return frame


def _compare_current_rcsd(
    roads: gpd.GeoDataFrame,
    current_rcsd: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    columns = [
        "directional_road_id",
        "parent_swsd_unit_id",
        "travel_side",
        "matched_rcsd_road_id",
        "matched_rcsd_road_ids_json",
        "matched_rcsd_candidate_count",
        "orientation_delta_deg",
        "midpoint_distance_m",
        "hausdorff_distance_m",
        "corridor_sample_count",
        "corridor_distance_median_m",
        "corridor_distance_p95_m",
        "corridor_distance_max_m",
        "corridor_coverage_within_2m_ratio",
        "corridor_coverage_within_5m_ratio",
        "comparison_state",
        "geometry",
    ]
    if current_rcsd.empty:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=roads.crs)
    id_column = next(
        (column for column in ("id", "Id", "roadid", "RoadId") if column in current_rcsd.columns),
        None,
    )
    rows = []
    for road in roads.itertuples(index=False):
        if str(road.travel_side) == "sd_parent":
            continue
        query = box(*road.geometry.buffer(40.0).bounds)
        candidates = current_rcsd.iloc[list(current_rcsd.sindex.query(query))]
        best = None
        corridor_candidates: list[Any] = []
        candidate_ids: list[str] = []
        for candidate in candidates.itertuples(index=False):
            if candidate.geometry is None or candidate.geometry.is_empty:
                continue
            delta = _orientation_delta(road.geometry, candidate.geometry)
            if delta > 60.0 or road.geometry.distance(candidate.geometry) > 30.0:
                continue
            corridor_candidates.append(candidate.geometry)
            if id_column:
                candidate_ids.append(canonical_id(getattr(candidate, id_column)))
            midpoint_distance = road.geometry.interpolate(0.5, normalized=True).distance(
                candidate.geometry.interpolate(0.5, normalized=True)
            )
            hausdorff = road.geometry.hausdorff_distance(candidate.geometry)
            score = midpoint_distance + 0.1 * hausdorff + 0.05 * delta
            if best is None or score < best[0]:
                best = (score, candidate, delta, midpoint_distance, hausdorff)
        if best is None or not corridor_candidates:
            rows.append(
                {
                    "directional_road_id": str(road.directional_road_id),
                    "parent_swsd_unit_id": str(road.parent_swsd_unit_id),
                    "travel_side": str(road.travel_side),
                    "matched_rcsd_road_id": "",
                    "matched_rcsd_road_ids_json": "[]",
                    "matched_rcsd_candidate_count": 0,
                    "orientation_delta_deg": None,
                    "midpoint_distance_m": None,
                    "hausdorff_distance_m": None,
                    "corridor_sample_count": 0,
                    "corridor_distance_median_m": None,
                    "corridor_distance_p95_m": None,
                    "corridor_distance_max_m": None,
                    "corridor_coverage_within_2m_ratio": None,
                    "corridor_coverage_within_5m_ratio": None,
                    "comparison_state": "no_spatial_direction_match",
                    "geometry": road.geometry,
                }
            )
            continue
        _, candidate, delta, midpoint_distance, hausdorff = best
        corridor = unary_union(corridor_candidates)
        sample_count = max(2, int(math.ceil(float(road.geometry.length) / 5.0)) + 1)
        distances = np.asarray(
            [
                road.geometry.interpolate(float(fraction), normalized=True).distance(corridor)
                for fraction in np.linspace(0.0, 1.0, sample_count)
            ],
            dtype=float,
        )
        rows.append(
            {
                "directional_road_id": str(road.directional_road_id),
                "parent_swsd_unit_id": str(road.parent_swsd_unit_id),
                "travel_side": str(road.travel_side),
                "matched_rcsd_road_id": canonical_id(getattr(candidate, id_column))
                if id_column
                else "",
                "matched_rcsd_road_ids_json": json.dumps(
                    sorted(set(candidate_ids)), ensure_ascii=False
                ),
                "matched_rcsd_candidate_count": int(len(corridor_candidates)),
                "orientation_delta_deg": float(delta),
                "midpoint_distance_m": float(midpoint_distance),
                "hausdorff_distance_m": float(hausdorff),
                "corridor_sample_count": sample_count,
                "corridor_distance_median_m": float(np.median(distances)),
                "corridor_distance_p95_m": float(np.quantile(distances, 0.95)),
                "corridor_distance_max_m": float(distances.max(initial=0.0)),
                "corridor_coverage_within_2m_ratio": float((distances <= 2.0).mean()),
                "corridor_coverage_within_5m_ratio": float((distances <= 5.0).mean()),
                "comparison_state": "corridor_matched_for_shape_audit",
                "geometry": road.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=roads.crs)


def _m2_baseline(m2_root: Path) -> dict[str, Any]:
    roads = gpd.read_file(m2_root / "p04_road_candidates.gpkg", layer="road_candidates")
    stations = gpd.read_file(m2_root / "p04_road_support_intervals.gpkg", layer="fit_stations")
    ratios = roads["candidate_length_m"] / roads["swsd_reference_length_m"].replace(0, np.nan)
    jump_count = 0
    tv_count = 0
    max_jump = 0.0
    for _, frame in stations.sort_values(["swsd_unit_id", "station_index"]).groupby("swsd_unit_id"):
        shifts = frame["applied_lateral_shift_m"].astype(float).to_numpy()
        jumps = np.abs(np.diff(shifts))
        road_length = float(frame["station_offset_m"].max())
        max_jump = max(max_jump, float(jumps.max(initial=0.0)))
        jump_count += int(jumps.max(initial=0.0) > 2.0)
        tv = float(jumps.sum()) / max(road_length, 1e-8) * 100.0
        tv_count += int(tv > 15.0)
    return {
        "road_count": int(len(roads)),
        "direction_counts": {
            str(key): int(value) for key, value in roads["direction"].value_counts().items()
        },
        "non_sd_direction_1_count": int(
            ((roads["support_state"] != "sd_only") & roads["direction"].isin([0, 1])).sum()
        ),
        "candidate_length_ratio_max": float(ratios.max()),
        "candidate_length_ratio_gt_1_03_count": int((ratios > 1.03).sum()),
        "adjacent_lateral_jump_max_m": max_jump,
        "adjacent_lateral_jump_gt_2m_road_count": jump_count,
        "lateral_total_variation_gt_15m_per_100m_road_count": tv_count,
    }


def _comparison_summary(frame: gpd.GeoDataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"available": False, "road_count": 0}
    matched = frame[
        frame["comparison_state"] == "corridor_matched_for_shape_audit"
    ]
    total_samples = int(matched["corridor_sample_count"].sum()) if not matched.empty else 0
    within_2m = (
        float(
            (
                matched["corridor_coverage_within_2m_ratio"]
                * matched["corridor_sample_count"]
            ).sum()
        )
        if total_samples
        else 0.0
    )
    within_5m = (
        float(
            (
                matched["corridor_coverage_within_5m_ratio"]
                * matched["corridor_sample_count"]
            ).sum()
        )
        if total_samples
        else 0.0
    )
    return {
        "available": True,
        "road_count": int(len(frame)),
        "matched_count": int(len(matched)),
        "unmatched_count": int(len(frame) - len(matched)),
        "corridor_sample_count": total_samples,
        "corridor_coverage_within_2m_ratio": within_2m / total_samples
        if total_samples
        else None,
        "corridor_coverage_within_5m_ratio": within_5m / total_samples
        if total_samples
        else None,
        "median_corridor_distance_m": None
        if matched.empty
        else float(matched["corridor_distance_median_m"].median()),
        "p95_corridor_distance_m": None
        if matched.empty
        else float(matched["corridor_distance_p95_m"].quantile(0.95)),
        "median_midpoint_distance_m": None
        if matched.empty
        else float(matched["midpoint_distance_m"].median()),
        "p95_midpoint_distance_m": None
        if matched.empty
        else float(matched["midpoint_distance_m"].quantile(0.95)),
    }


def _orientation_delta(first: Any, second: Any) -> float:
    a = tangent_vector(first, float(first.length) / 2.0)
    b = tangent_vector(second, float(second.length) / 2.0)
    norm = math.hypot(*a) * math.hypot(*b)
    if norm <= 1e-12:
        return 180.0
    cosine = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / norm))
    return math.degrees(math.acos(cosine))


def _build_report(summary: dict[str, Any]) -> str:
    evidence = summary["directional_evidence"]
    geometry = summary["directional_geometry"]
    movement = summary["directional_movement"]
    topology = summary["directional_topology"]
    baseline = summary["m2_baseline"]
    comparison = summary["current_rcsd_comparison"]
    lines = [
        "# P04 Directional Road V2 报告",
        "",
        "## 1. 终态",
        "",
        f"- terminal status：`{summary['terminal_status']}`。",
        f"- 父 SWSD Road：{summary['parent_road_count']}；发布 Road：{summary['directional_road_count']}。",
        f"- 展开双向父 Road：{evidence['expanded_bidirectional_parent_count']}；纯 `sd_only` 父表达：{evidence['pure_sd_parent_count']}。",
        f"- 非 `sd_only` 双向单对象：{geometry['non_sd_bidirectional_object_count']}。",
        "",
        "## 2. 中心锚点与证据隔离",
        "",
        f"- 硬几何 LaneEvidenceSegment：{evidence['hard_lane_segment_count']}；软复核片段：{evidence['soft_lane_segment_count']}。",
        f"- 中心锚点：{evidence['anchor_count']}，类型 {evidence['anchor_kind_counts']}。",
        f"- 非 usable 硬锚点：{evidence['hard_anchor_non_usable_count']}；未解释锚点切换：{evidence['anchor_switch_count']}。",
        f"- 双向锚点审计父 Road：{evidence['cross_direction_audited_parent_count']}；塌缩候选：{evidence['cross_direction_collapse_parent_count']}；已降级 LaneEvidenceSegment：{evidence['cross_direction_downgraded_lane_segment_count']}；仍错误发布的塌缩方向子 Road：{evidence['published_cross_direction_collapse_count']}。",
        f"- 长 SD gap（≥ {summary['parameters']['long_sd_gap_review_m']} m）复核 Road：{evidence['long_sd_gap_review_count']}；该项只限制高精声明范围，不删除语义 Road。",
        "",
        "## 3. 几何 A/B",
        "",
        f"- V2 最大相邻横移：{geometry['max_adjacent_lateral_shift_m']:.3f} m；M2：{baseline['adjacent_lateral_jump_max_m']:.3f} m。",
        f"- V2 最大长度比：{geometry['max_candidate_length_ratio']:.6f}；M2：{baseline['candidate_length_ratio_max']:.6f}。",
        f"- V2 高精片段最大横向振荡：{geometry['max_hp_lateral_oscillation_per_100m']:.3f} m/100m；全 Road 横移总变差 {geometry['max_lateral_total_variation_per_100m']:.3f} m/100m 仅作 SD↔高精过渡诊断。",
        f"- LaneGroup 包络越界站点：{geometry['lane_group_envelope_violation_count']}。",
        f"- 无证据站点：{geometry['unsupported_station_count']}，发生高精外推：{geometry['unsupported_station_shift_count']}；无证据端点：{geometry['unsupported_endpoint_count']}，发生高精外推：{geometry['unsupported_endpoint_shift_count']}。",
        f"- 站点来源：{geometry['station_geometry_source_counts']}。",
        "",
        "## 4. LaneTopo movement 与方向 Portal",
        "",
        f"- 跨 Road LaneTopo：确认 {movement['confirmed_lane_topo_link_count']}，保留复核 {movement['review_lane_topo_link_count']}。",
        f"- Directional Road movement：{movement['road_movement_count']}，其中物理节点 {movement['physical_node_movement_count']}、复杂语义路口 {movement['semantic_junction_movement_count']}。",
        f"- 确认物理 movement 最大 Road 端点间距：{movement['confirmed_physical_movement_max_gap_m']:.9f} m；movement 到 Road Portal 最大偏差：{movement['movement_portal_max_delta_m']:.9f} m。",
        f"- 全量物理 Node 最大端点间距：{movement.get('all_physical_node_max_gap_m', float('nan')):.9f} m；movement 最大接头角：{movement.get('movement_join_angle_max_deg', float('nan')):.3f}°。",
        f"- 参与协调的 Road 端点：{movement['coordinated_endpoint_count']}；最大协调位移：{movement['max_endpoint_coordination_shift_m']:.3f} m。",
        f"- Road/Portal 最大偏差：{topology['road_portal_max_delta_m']:.9f} m。",
        f"- Road/Arm 最大偏差：{topology['road_arm_max_delta_m']:.9f} m。",
        f"- reverse Road 单方向编码：{topology['reverse_single_direction_encoding_count']} / {topology['reverse_road_count']}。",
        "",
        "## 5. 当前 RCSD 对照",
        "",
        f"- 同向走廊匹配 Road：{comparison.get('matched_count', 0)}；未匹配：{comparison.get('unmatched_count', 0)}。",
        f"- 走廊采样点：{comparison.get('corridor_sample_count', 0)}；2 m 覆盖率：{comparison.get('corridor_coverage_within_2m_ratio')}；5 m 覆盖率：{comparison.get('corridor_coverage_within_5m_ratio')}。",
        f"- Road 级中位走廊距离中位数：{comparison.get('median_corridor_distance_m')} m；Road 级 P95 走廊距离的 P95：{comparison.get('p95_corridor_distance_m')} m。",
        "- 输入 RCSD、旧 Patch Road和 M2 只作方向/形态对照，不作为目标几何真值。",
        "",
        "## 6. 门禁",
        "",
    ]
    for name, passed in summary["core_gates"].items():
        lines.append(f"- `{name}`：`{passed}`")
    if "qgis_gate_pass" in summary:
        lines.extend(
            [
                f"- `qgis_project`：`{summary['qgis_gate_pass']}`",
                f"- `qgis_independent_readback`：`{summary['qgis_independent_readback_pass']}`",
                f"- `drivezone_overlay`：`{summary['overlay_gate_pass']}`",
                f"- `independent_geometry_topology_quality`：`{summary['independent_quality_pass']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## 7. 范围边界",
            "",
            "- 本轮已发布 LaneTopo movement 投影，但不接入 restriction/Laneinfo、RoadSplit，也不声明 restriction 意义上的 movement 合法性。",
            "- 平滑、长度比和高精片段横向振荡阈值是 1885118 POC 参数，仍需多 Case 与人工真值确认。",
            "- 缺证据方向的 `sd_only` 中心线只保证语义完整，不声明高精几何。",
            "",
        ]
    )
    return "\n".join(lines)


def _require_crs(frame: gpd.GeoDataFrame, expected: str, label: str) -> None:
    if frame.crs is None:
        raise ValueError(f"missing CRS: {label}")
    expected_crs = gpd.GeoSeries([], crs=expected).crs
    if frame.crs != expected_crs:
        raise ValueError(f"unexpected CRS for {label}: {frame.crs}; expected {expected}")


def _peak_rss_mb() -> float | None:
    if resource is None:
        return None
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


__all__ = ["finalize_directional_road_v2", "run_directional_road_v2"]
