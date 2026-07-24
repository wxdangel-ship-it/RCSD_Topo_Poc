from __future__ import annotations

import time
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - Windows/QGIS runtime
    resource = None

import geopandas as gpd
import pandas as pd

from .assignment import build_lane_assignments
from .business_analysis import build_business_analysis
from .comparison import compare_old_road_groups
from .config import MilestoneOneConfig, MilestoneOneResult
from .geometry import canonical_id, parse_patch_membership
from .io import (
    build_input_manifest,
    discover_patch_dirs,
    prepare_output_dir,
    profile_patch_vectors,
    read_vector,
    write_csv,
    write_gpkg_layers,
    write_json,
)
from .report import build_milestone_report
from .skeleton import build_swsd_skeleton


def run_milestone_one(config: MilestoneOneConfig) -> MilestoneOneResult:
    cfg = config.resolved()
    started = time.perf_counter()
    stage_seconds: dict[str, float] = {}
    prepare_output_dir(cfg.output_dir)
    patch_dirs = discover_patch_dirs(cfg.patch_root)
    patch_ids = {path.name for path in patch_dirs}

    stage_started = time.perf_counter()
    external_inputs = {
        "swsd_roads": cfg.swsd_road_path,
        "swsd_nodes": cfg.swsd_node_path,
        "t01_roads": cfg.t01_road_path,
        "t01_segments": cfg.t01_segment_path,
        "current_rcsd_roads": cfg.current_rcsd_road_path,
    }
    manifest = build_input_manifest(
        run_id=cfg.run_id,
        patch_dirs=patch_dirs,
        external_inputs=external_inputs,
        parameters=cfg.parameter_dict(),
    )
    write_json(cfg.output_dir / "p04_input_manifest.json", manifest)
    profile = profile_patch_vectors(patch_dirs)
    write_json(cfg.output_dir / "p04_patch_vector_profile.json", profile)
    stage_seconds["manifest_and_profile"] = time.perf_counter() - stage_started

    stage_started = time.perf_counter()
    patch_data = _load_patch_data(patch_dirs, cfg.analysis_crs)
    swsd_roads = read_vector(cfg.swsd_road_path, cfg.analysis_crs)
    swsd_nodes = read_vector(cfg.swsd_node_path, cfg.analysis_crs)
    t01_roads = _read_optional(cfg.t01_road_path, cfg.analysis_crs)
    t01_segments = _read_optional(cfg.t01_segment_path, cfg.analysis_crs)
    current_rcsd = _read_optional(cfg.current_rcsd_road_path, cfg.analysis_crs)
    stage_seconds["load_inputs"] = time.perf_counter() - stage_started

    stage_started = time.perf_counter()
    skeleton = build_swsd_skeleton(
        swsd_roads,
        swsd_nodes,
        patch_ids=patch_ids,
        run_id=cfg.run_id,
        t01_roads=t01_roads,
        t01_segments=t01_segments,
    )
    write_gpkg_layers(
        cfg.output_dir / "p04_swsd_skeleton.gpkg",
        {
            "road_sections": skeleton.roads,
            "junctions": skeleton.junctions,
            "arms": skeleton.arms,
            **({"t01_segments": skeleton.segments} if skeleton.segments is not None else {}),
        },
    )
    stage_seconds["swsd_skeleton"] = time.perf_counter() - stage_started

    stage_started = time.perf_counter()
    assignment_roads = skeleton.roads.copy()
    assignment_roads["patch_membership"] = assignment_roads["all_patch_ids"].map(parse_patch_membership)
    assignment = build_lane_assignments(
        patch_data["lanes"],
        patch_data["boundaries"],
        assignment_roads,
        patch_data["drivezone_fix"],
        patch_data["divstripzone_fix"],
        patch_data["lane_next"],
        patch_data["reference_lanes"],
        config=cfg,
    )
    write_gpkg_layers(
        cfg.output_dir / "p04_evidence_assignment.gpkg",
        {
            "lane_owner_candidates": assignment.candidates,
            "lane_boundary_samples": assignment.boundary_samples,
        },
    )
    write_gpkg_layers(
        cfg.output_dir / "p04_lane_decisions.gpkg",
        {"lane_decisions": assignment.decisions},
    )
    stage_seconds["lane_evidence_assignment"] = time.perf_counter() - stage_started

    stage_started = time.perf_counter()
    comparison = compare_old_road_groups(
        assignment.decisions,
        patch_data["old_roads"],
        run_id=cfg.run_id,
    )
    business_analysis = build_business_analysis(
        patch_data["lane_next"],
        assignment.decisions,
        skeleton.roads,
        run_id=cfg.run_id,
    )
    write_gpkg_layers(
        cfg.output_dir / "p04_current_road_comparison.gpkg",
        {"old_patch_roads": comparison.old_roads},
    )
    write_csv(
        cfg.output_dir / "p04_old_road_group_comparison.csv",
        comparison.old_roads.drop(columns="geometry").to_dict("records"),
    )
    write_csv(
        cfg.output_dir / "p04_swsd_fragmentation_comparison.csv",
        comparison.fragmentation.to_dict("records"),
    )
    write_gpkg_layers(
        cfg.output_dir / "p04_lane_topo_readiness.gpkg",
        {"lane_topo_links": business_analysis.topology_links},
    )
    write_csv(
        cfg.output_dir / "p04_lane_topo_readiness.csv",
        business_analysis.topology_links.drop(columns="geometry").to_dict("records"),
    )
    write_csv(
        cfg.output_dir / "p04_patch_assignment_summary.csv",
        business_analysis.patch_summary.to_dict("records"),
    )
    write_csv(
        cfg.output_dir / "p04_reason_code_summary.csv",
        business_analysis.reason_summary.to_dict("records"),
    )
    write_csv(
        cfg.output_dir / "p04_unsegmented_swsd_roads.csv",
        business_analysis.unsegmented_roads.to_dict("records"),
    )
    write_json(
        cfg.output_dir / "p04_business_analysis.json",
        business_analysis.summary,
    )
    conflicts = assignment.decisions[assignment.decisions["decision"] != "accepted"].copy()
    conflict_columns = [
        "run_id",
        "lane_id",
        "source_patch_ids",
        "old_road_id",
        "swsd_unit_id",
        "decision",
        "reason_codes",
        "owner_state",
        "owner_score",
        "owner_score_margin",
        "owner_distance_p90_m",
        "owner_direction_delta_deg",
        "width_state",
        "inferred_lane_width_m",
        "width_sample_coverage",
        "width_variation_m",
        "drivezone_coverage",
        "divstrip_overlap_ratio",
    ]
    write_csv(
        cfg.output_dir / "p04_conflicts.csv",
        conflicts[conflict_columns].to_dict("records"),
        conflict_columns,
    )
    qgis_current_rcsd = _scope_current_rcsd(current_rcsd, patch_data["drivezone_fix"])
    qgis_layers = {
        "raw_lanes": patch_data["lanes"],
        "raw_lane_boundaries": patch_data["boundaries"],
        "drivezone_raw": patch_data["drivezone_raw"],
        "drivezone_fix": patch_data["drivezone_fix"],
        "divstripzone_raw": patch_data["divstripzone_raw"],
        "divstripzone_fix": patch_data["divstripzone_fix"],
        "old_patch_roads": patch_data["old_roads"],
    }
    if qgis_current_rcsd is not None and not qgis_current_rcsd.empty:
        qgis_layers["current_rcsd_roads"] = qgis_current_rcsd
    write_gpkg_layers(cfg.output_dir / "p04_qgis_comparison.gpkg", qgis_layers)
    write_gpkg_layers(
        cfg.output_dir / "p04_road_surface_reference.gpkg",
        {"drivezone_fix": patch_data["drivezone_fix"]},
    )
    stage_seconds["comparison_and_package"] = time.perf_counter() - stage_started

    profile_summary = {
        key: profile[key]
        for key in (
            "patch_count",
            "object_type_count",
            "nonempty_object_type_count",
            "empty_object_type_count",
        )
    }
    core_gates = {
        "patch_count_6": len(patch_dirs) == 6,
        "profile_70_types": profile["object_type_count"] == 70,
        "profile_29_nonempty": profile["nonempty_object_type_count"] == 29,
        "profile_41_empty": profile["empty_object_type_count"] == 41,
        "swsd_road_count_571": skeleton.summary["road_count"] == 571,
        "internal_overlap_24": skeleton.summary["internal_overlap_road_count"] == 24,
        "open_boundary_57": skeleton.summary["open_boundary_road_count"] == 57,
        "lane_count_2188": assignment.summary["lane_count"] == 2188,
        "lane_decision_coverage": assignment.summary["decision_coverage_gate_pass"],
        "accepted_owner_uniqueness": assignment.summary["owner_uniqueness_gate_pass"],
    }
    core_gate_pass = all(core_gates.values())
    total_seconds = time.perf_counter() - started
    stage_seconds["total_core"] = total_seconds
    summary = {
        "run_id": cfg.run_id,
        "terminal_status": "core_passed_qgis_pending" if core_gate_pass else "core_failed",
        "analysis_crs": cfg.analysis_crs,
        "core_gate_pass": core_gate_pass,
        "core_gates": core_gates,
        "manifest": {
            "input_file_count": manifest["input_file_count"],
            "input_total_bytes": manifest["input_total_bytes"],
            "manifest_path": "p04_input_manifest.json",
        },
        "profile": profile_summary,
        "skeleton": skeleton.summary,
        "assignment": assignment.summary,
        "comparison": comparison.summary,
        "business_analysis": business_analysis.summary,
        "parameters": cfg.parameter_dict(),
        "performance": {
            "stage_seconds": stage_seconds,
            "peak_rss_mb": _peak_rss_mb(),
        },
        "outputs": {
            "manifest": "p04_input_manifest.json",
            "profile": "p04_patch_vector_profile.json",
            "skeleton": "p04_swsd_skeleton.gpkg",
            "evidence_assignment": "p04_evidence_assignment.gpkg",
            "lane_decisions": "p04_lane_decisions.gpkg",
            "current_road_comparison": "p04_current_road_comparison.gpkg",
            "business_analysis": "p04_business_analysis.json",
            "lane_topo_readiness": "p04_lane_topo_readiness.gpkg",
            "patch_assignment_summary": "p04_patch_assignment_summary.csv",
            "reason_code_summary": "p04_reason_code_summary.csv",
            "unsegmented_swsd_roads": "p04_unsegmented_swsd_roads.csv",
            "conflicts": "p04_conflicts.csv",
            "qgis_sources": "p04_qgis_comparison.gpkg",
            "road_surface_reference": "p04_road_surface_reference.gpkg",
            "qgis_project": "p04_milestone1_comparison.qgz",
        },
    }
    summary_path = cfg.output_dir / "p04_run_summary.json"
    write_json(summary_path, summary)
    report_path = cfg.output_dir / "p04_milestone1_report.md"
    report_path.write_text(
        build_milestone_report(
            summary=summary,
            decisions=assignment.decisions,
            old_road_comparison=comparison.old_roads,
        ),
        encoding="utf-8",
    )
    return MilestoneOneResult(
        run_id=cfg.run_id,
        output_dir=cfg.output_dir,
        summary_path=summary_path,
        report_path=report_path,
        core_gate_pass=core_gate_pass,
    )


def _load_patch_data(patch_dirs: tuple[Path, ...], analysis_crs: str) -> dict[str, Any]:
    spatial: dict[str, list[gpd.GeoDataFrame]] = {
        "lanes": [],
        "boundaries": [],
        "reference_lanes": [],
        "old_roads": [],
        "drivezone_raw": [],
        "drivezone_fix": [],
        "divstripzone_raw": [],
        "divstripzone_fix": [],
    }
    lane_next: list[pd.DataFrame] = []
    for patch_dir in patch_dirs:
        patch_id = patch_dir.name
        vector = patch_dir / "Vector"
        mapping = {
            "lanes": "Lane.geojson",
            "boundaries": "LaneBoundary.geojson",
            "reference_lanes": "ReferenceLane.geojson",
            "old_roads": "Road.geojson",
            "drivezone_raw": "DriveZone.geojson",
            "drivezone_fix": "DriveZone_fix.geojson",
            "divstripzone_raw": "DivStripZone.geojson",
            "divstripzone_fix": "DivStripZone_fix.geojson",
        }
        for key, filename in mapping.items():
            frame = read_vector(vector / filename, analysis_crs)
            frame["patch_id"] = patch_id
            spatial[key].append(frame)
        relation = gpd.read_file(vector / "LaneNextLane.geojson").drop(columns="geometry")
        relation["patch_id"] = patch_id
        lane_next.append(relation)
    result: dict[str, Any] = {
        key: gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=analysis_crs)
        for key, frames in spatial.items()
    }
    result["lanes"]["lane_id"] = result["lanes"]["Id"].map(canonical_id)
    result["old_roads"]["old_road_id"] = result["old_roads"]["Id"].map(canonical_id)
    result["lane_next"] = pd.concat(lane_next, ignore_index=True)
    return result


def _read_optional(path: Path | None, analysis_crs: str) -> gpd.GeoDataFrame | None:
    if path is None:
        return None
    return read_vector(path, analysis_crs)


def _scope_current_rcsd(
    current_rcsd: gpd.GeoDataFrame | None,
    drivezones: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame | None:
    if current_rcsd is None or current_rcsd.empty:
        return current_rcsd
    scope = drivezones.geometry.union_all().buffer(100.0)
    candidates = current_rcsd.iloc[current_rcsd.sindex.query(scope)].copy()
    candidates = candidates[candidates.geometry.intersects(scope)].copy()
    candidates["comparison_channel"] = "current_rcsd_read_only"
    return candidates


def _peak_rss_mb() -> float | None:
    if resource is None:
        return None
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / 1024.0


__all__ = ["run_milestone_one"]
