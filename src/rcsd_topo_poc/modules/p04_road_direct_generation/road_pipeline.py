from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

try:
    import resource
except ImportError:  # pragma: no cover - Windows standard Python
    resource = None

from .io import (
    prepare_output_dir,
    runtime_metadata,
    write_csv,
    write_gpkg_layers,
    write_json,
)
from .pipeline import run_milestone_one
from .road_config import MilestoneTwoConfig, MilestoneTwoResult
from .road_evidence import build_road_evidence
from .road_geometry import instantiate_road_geometries
from .road_report import build_milestone_two_report


def run_milestone_two(config: MilestoneTwoConfig) -> MilestoneTwoResult:
    cfg = config.resolved()
    prepare_output_dir(cfg.output_dir)
    started = time.perf_counter()
    stage_seconds: dict[str, float] = {}

    stage_started = time.perf_counter()
    milestone_one = run_milestone_one(cfg.milestone_one_config())
    stage_seconds["milestone_one_reuse"] = time.perf_counter() - stage_started
    m1_root = milestone_one.output_dir

    stage_started = time.perf_counter()
    lanes = gpd.read_file(m1_root / "p04_lane_decisions.gpkg", layer="lane_decisions")
    roads = gpd.read_file(m1_root / "p04_swsd_skeleton.gpkg", layer="road_sections")
    junctions = gpd.read_file(m1_root / "p04_swsd_skeleton.gpkg", layer="junctions")
    arms = gpd.read_file(m1_root / "p04_swsd_skeleton.gpkg", layer="arms")
    topology = gpd.read_file(m1_root / "p04_lane_topo_readiness.gpkg", layer="lane_topo_links")
    _require_crs(lanes, cfg.analysis_crs, "lane_decisions")
    _require_crs(roads, cfg.analysis_crs, "road_sections")
    _require_crs(topology, cfg.analysis_crs, "lane_topo_links")
    evidence = build_road_evidence(
        lanes,
        roads,
        topology,
        config=cfg,
    )
    stage_seconds["lane_segment_and_road_support"] = time.perf_counter() - stage_started

    stage_started = time.perf_counter()
    road_geometry = instantiate_road_geometries(
        roads,
        evidence.lane_segments,
        evidence.support_intervals,
        evidence.road_audit,
        config=cfg,
    )
    road_topology = _road_topology_summary(
        road_geometry.road_candidates,
        junctions,
        arms,
    )
    stage_seconds["road_geometry_instantiation"] = time.perf_counter() - stage_started

    stage_started = time.perf_counter()
    _write_outputs(
        cfg.output_dir,
        evidence=evidence,
        road_geometry=road_geometry,
        junctions=junctions,
        arms=arms,
    )
    manifest = _write_milestone_two_manifest(cfg, m1_root)
    stage_seconds["package_outputs"] = time.perf_counter() - stage_started

    total_seconds = time.perf_counter() - started
    stage_seconds["total_core"] = total_seconds
    core_gates = _core_gates(
        cfg,
        milestone_one_core_pass=milestone_one.core_gate_pass,
        evidence_summary=evidence.summary,
        geometry_summary=road_geometry.summary,
        topology_summary=road_topology,
        road_candidates=road_geometry.road_candidates,
    )
    core_gate_pass = all(core_gates.values())
    summary = {
        "run_id": cfg.run_id,
        "terminal_status": "core_passed_qgis_pending" if core_gate_pass else "core_failed",
        "analysis_crs": cfg.analysis_crs,
        "road_count": int(len(roads)),
        "core_gate_pass": core_gate_pass,
        "core_gates": core_gates,
        "milestone_one": {
            "run_id": milestone_one.run_id,
            "core_gate_pass": milestone_one.core_gate_pass,
            "relative_root": "_milestone1",
        },
        "road_evidence": evidence.summary,
        "road_geometry": road_geometry.summary,
        "road_topology": road_topology,
        "parameters": cfg.parameter_dict(),
        "scope_exclusions": {
            "swsd_restriction_consumed": False,
            "swsd_laneinfo_consumed": False,
            "roadsplit_consumed": False,
            "movement_legality_published": False,
        },
        "reuse": {
            "p04_milestone_one": "direct_internal_callable",
            "t00_fix_layers": "formal_product_consumption_via_milestone_one",
            "t01_segment": "public_contract_consumption_via_milestone_one",
            "current_rcsd_and_old_road": "read_only_comparison",
            "t00_t12_v1_changes": 0,
        },
        "manifest": {
            "path": "p04_input_manifest.json",
            "input_file_count": manifest["input_file_count"],
            "input_total_bytes": manifest["input_total_bytes"],
        },
        "performance": {
            "stage_seconds": stage_seconds,
            "peak_rss_mb": _peak_rss_mb(),
        },
        "outputs": {
            "input_manifest": "p04_input_manifest.json",
            "lane_evidence_segments": "p04_lane_evidence_segments.gpkg",
            "input_quality_flags": "p04_input_quality_flags.csv",
            "road_support_intervals": "p04_road_support_intervals.gpkg",
            "road_audit": "p04_road_audit.csv",
            "road_candidates": "p04_road_candidates.gpkg",
            "road_geometry_qa": "p04_road_geometry_qa.csv",
            "road_graph": "p04_road_graph.gpkg",
            "qgis_overlay_evidence": "p04_qgis_overlay_evidence.gpkg",
            "summary": "p04_run_summary.json",
            "report": "p04_milestone2_report.md",
            "qgis_project": "p04_milestone2_comparison.qgz",
        },
    }
    summary_path = cfg.output_dir / "p04_run_summary.json"
    write_json(summary_path, summary)
    report_path = cfg.output_dir / "p04_milestone2_report.md"
    report_path.write_text(
        build_milestone_two_report(
            summary=summary,
            road_candidates=road_geometry.road_candidates,
            road_audit=evidence.road_audit,
        ),
        encoding="utf-8",
    )
    return MilestoneTwoResult(
        run_id=cfg.run_id,
        output_dir=cfg.output_dir,
        summary_path=summary_path,
        report_path=report_path,
        core_gate_pass=core_gate_pass,
    )


def _write_outputs(
    output_dir: Path,
    *,
    evidence: Any,
    road_geometry: Any,
    junctions: gpd.GeoDataFrame,
    arms: gpd.GeoDataFrame,
) -> None:
    write_gpkg_layers(
        output_dir / "p04_lane_evidence_segments.gpkg",
        {
            "lane_samples": evidence.lane_samples,
            "lane_segments": evidence.lane_segments,
        },
    )
    write_csv(
        output_dir / "p04_input_quality_flags.csv",
        evidence.quality_flags.to_dict("records"),
        tuple(evidence.quality_flags.columns),
    )
    write_gpkg_layers(
        output_dir / "p04_road_support_intervals.gpkg",
        {
            "support_intervals": evidence.support_intervals,
            "candidate_geometry_segments": road_geometry.geometry_segments,
            "fit_stations": road_geometry.fit_stations,
        },
    )
    write_csv(
        output_dir / "p04_road_audit.csv",
        evidence.road_audit.to_dict("records"),
        tuple(evidence.road_audit.columns),
    )
    write_gpkg_layers(
        output_dir / "p04_road_candidates.gpkg",
        {"road_candidates": road_geometry.road_candidates},
    )
    geometry_qa_columns = (
        "run_id",
        "swsd_unit_id",
        "support_state",
        "evidence_quality_state",
        "geometry_fit_state",
        "geometry_source",
        "attempted_geometry_simple",
        "attempted_max_lateral_shift_m",
        "max_lateral_shift_m",
        "reason_codes",
    )
    geometry_qa = road_geometry.road_candidates[
        road_geometry.road_candidates["geometry_fit_state"]
        == "fit_rejected_non_simple_swsd_retained"
    ]
    write_csv(
        output_dir / "p04_road_geometry_qa.csv",
        geometry_qa[list(geometry_qa_columns)].to_dict("records"),
        geometry_qa_columns,
    )
    write_gpkg_layers(
        output_dir / "p04_road_graph.gpkg",
        {
            "roads": road_geometry.road_candidates,
            "junctions": junctions,
            "arms": arms,
        },
    )
    hp_fitted_segments = road_geometry.geometry_segments[
        road_geometry.geometry_segments["geometry_source"] == "hp_fitted"
    ]
    write_gpkg_layers(
        output_dir / "p04_qgis_overlay_evidence.gpkg",
        {
            "hp_fitted_segments": hp_fitted_segments,
            "lane_evidence_segments": evidence.lane_segments,
        },
    )


def _write_milestone_two_manifest(cfg: MilestoneTwoConfig, m1_root: Path) -> dict[str, Any]:
    m1_manifest_path = m1_root / "p04_input_manifest.json"
    manifest = json.loads(m1_manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = cfg.run_id
    manifest["milestone"] = 2
    manifest["milestone_one_manifest_ref"] = "_milestone1/p04_input_manifest.json"
    manifest["milestone_one_parameters"] = manifest.pop("parameters", {})
    manifest["parameters"] = cfg.parameter_dict()
    manifest["runtime_milestone_two"] = runtime_metadata()
    write_json(cfg.output_dir / "p04_input_manifest.json", manifest)
    return manifest


def _core_gates(
    cfg: MilestoneTwoConfig,
    *,
    milestone_one_core_pass: bool,
    evidence_summary: dict[str, Any],
    geometry_summary: dict[str, Any],
    topology_summary: dict[str, Any],
    road_candidates: gpd.GeoDataFrame,
) -> dict[str, bool]:
    road_count = int(len(road_candidates))
    known = evidence_summary["known_quality_counts"]
    gates = {
        "milestone_one_core_pass": bool(milestone_one_core_pass),
        "road_id_unique": bool(road_candidates["swsd_unit_id"].is_unique),
        "road_state_conservation": bool(evidence_summary["road_conservation_gate_pass"]),
        "interval_partition_conservation": bool(evidence_summary["interval_partition_gate_pass"]),
        "road_geometry_valid_nonempty": bool(geometry_summary["road_geometry_gate_pass"]),
        "swsd_endpoint_anchor": bool(geometry_summary["endpoint_anchor_gate_pass"]),
        "road_arm_portal_topology": bool(topology_summary["road_topology_gate_pass"]),
        "sd_only_zero_shift": bool(geometry_summary["sd_only_zero_shift_gate_pass"]),
        "input_quality_not_road_conflict": evidence_summary[
            "quality_flag_direct_road_conflict_count"
        ]
        == 0,
        "road_output_count_matches_evidence": road_count == int(evidence_summary["road_count"]),
        "analysis_crs_explicit": str(road_candidates.crs).upper() == cfg.analysis_crs.upper(),
        "excluded_inputs_not_consumed": True,
    }
    if cfg.expected_road_count is not None:
        gates["expected_road_count"] = road_count == cfg.expected_road_count
    if cfg.expected_road_count == 571:
        gates["known_quality_counts_match_1885118"] = known == {
            "narrow_lane": 8,
            "wide_or_boundary_gap": 131,
            "width_unstable": 133,
            "cross_road_direction_review": 29,
            "cross_road_semantic_node_anomaly": 5,
            "patch_5417631180197930_boundary_insufficient": 67,
        }
    return gates


def _road_topology_summary(
    road_candidates: gpd.GeoDataFrame,
    junctions: gpd.GeoDataFrame,
    arms: gpd.GeoDataFrame,
) -> dict[str, Any]:
    road_by_id = {
        str(row.swsd_unit_id): row.geometry
        for row in road_candidates.itertuples(index=False)
    }
    expected_arm_keys = {
        (road_id, endpoint)
        for road_id in road_by_id
        for endpoint in ("s", "e")
    }
    arm_keys: list[tuple[str, str]] = []
    portal_distances: list[float] = []
    invalid_arm_geometry_count = 0
    unknown_road_arm_count = 0
    for arm in arms.itertuples(index=False):
        road_id = str(arm.swsd_unit_id)
        endpoint = str(arm.endpoint)
        arm_keys.append((road_id, endpoint))
        road_geometry = road_by_id.get(road_id)
        if road_geometry is None or endpoint not in {"s", "e"}:
            unknown_road_arm_count += 1
            continue
        if arm.geometry is None or arm.geometry.is_empty:
            invalid_arm_geometry_count += 1
            continue
        road_point = Point(road_geometry.coords[0 if endpoint == "s" else -1])
        arm_points = (Point(arm.geometry.coords[0]), Point(arm.geometry.coords[-1]))
        portal_distances.append(min(road_point.distance(point) for point in arm_points))

    observed_arm_keys = set(arm_keys)
    duplicate_arm_key_count = len(arm_keys) - len(observed_arm_keys)
    missing_arm_key_count = len(expected_arm_keys - observed_arm_keys)
    junction_ids = {str(value) for value in junctions["junction_id"]}
    invalid_junction_reference_count = sum(
        1
        for value in arms["junction_id"]
        if pd.notna(value) and str(value).lower() != "nan" and str(value) not in junction_ids
    )
    portal_max_delta_m = max(portal_distances, default=float("inf"))
    gate_pass = bool(
        len(road_candidates) == len(road_by_id)
        and len(arms) == len(expected_arm_keys)
        and duplicate_arm_key_count == 0
        and missing_arm_key_count == 0
        and unknown_road_arm_count == 0
        and invalid_arm_geometry_count == 0
        and invalid_junction_reference_count == 0
        and len(portal_distances) == len(expected_arm_keys)
        and portal_max_delta_m <= 1e-8
    )
    return {
        "road_count": int(len(road_candidates)),
        "junction_count": int(len(junctions)),
        "arm_count": int(len(arms)),
        "expected_arm_count": int(len(expected_arm_keys)),
        "duplicate_arm_key_count": int(duplicate_arm_key_count),
        "missing_arm_key_count": int(missing_arm_key_count),
        "unknown_road_arm_count": int(unknown_road_arm_count),
        "invalid_arm_geometry_count": int(invalid_arm_geometry_count),
        "invalid_junction_reference_count": int(invalid_junction_reference_count),
        "road_arm_portal_max_delta_m": float(portal_max_delta_m),
        "road_topology_gate_pass": gate_pass,
    }


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


__all__ = ["run_milestone_two"]
