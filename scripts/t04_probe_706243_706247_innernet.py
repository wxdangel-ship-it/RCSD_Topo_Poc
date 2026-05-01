#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CASE_IDS = ("706243", "706247")
CASE_ROOT_CANDIDATES = (
    Path("/mnt/d/TestData/POC_Data/T02/Anchor_2"),
    Path("/mnt/e/TestData/POC_Data/T02/Anchor_2"),
    Path("/mnt/c/TestData/POC_Data/T02/Anchor_2"),
)
FULL_INPUT_PATH_CANDIDATES = {
    "nodes_path": (
        Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg"),
        Path("/mnt/e/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg"),
        Path("/mnt/c/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg"),
    ),
    "roads_path": (
        Path("/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg"),
        Path("/mnt/e/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg"),
        Path("/mnt/c/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg"),
    ),
    "drivezone_path": (
        Path("/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg"),
        Path("/mnt/e/TestData/POC_Data/patch_all/DriveZone.gpkg"),
        Path("/mnt/c/TestData/POC_Data/patch_all/DriveZone.gpkg"),
    ),
    "divstripzone_path": (
        Path("/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg"),
        Path("/mnt/e/TestData/POC_Data/patch_all/DivStripZone.gpkg"),
        Path("/mnt/c/TestData/POC_Data/patch_all/DivStripZone.gpkg"),
    ),
    "rcsdroad_path": (
        Path("/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg"),
        Path("/mnt/e/TestData/POC_Data/RC4/RCSDRoad.gpkg"),
        Path("/mnt/c/TestData/POC_Data/RC4/RCSDRoad.gpkg"),
    ),
    "rcsdnode_path": (
        Path("/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg"),
        Path("/mnt/e/TestData/POC_Data/RC4/RCSDNode.gpkg"),
        Path("/mnt/c/TestData/POC_Data/RC4/RCSDNode.gpkg"),
    ),
}
DEFAULT_FULL_INPUT_BUFFERS = (360.0, 600.0, 900.0, 1200.0, 1600.0, 2400.0)


def _run_cmd(args: list[str], cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
        return {
            "cmd": args,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as exc:
        return {"cmd": args, "error": repr(exc)}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_json_load_error": repr(exc), "_path": str(path)}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _geo_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "path": str(path)}
    try:
        import geopandas as gpd

        gdf = gpd.read_file(path)
        return {
            "exists": True,
            "path": str(path),
            "crs": str(gdf.crs),
            "rows": int(len(gdf)),
            "geom_types": sorted({str(item) for item in gdf.geometry.geom_type}),
            "valid_all": bool(gdf.geometry.is_valid.all()) if len(gdf) else True,
            "area_sum": float(gdf.geometry.area.sum()) if len(gdf) else 0.0,
            "bounds": [float(item) for item in gdf.total_bounds] if len(gdf) else [],
        }
    except Exception as exc:
        return {"exists": True, "path": str(path), "error": repr(exc)}


def _first_unit(doc: dict[str, Any], key: str) -> dict[str, Any]:
    values = doc.get(key) or []
    if values and isinstance(values[0], dict):
        return values[0]
    return {}


def _candidate_summary(row: dict[str, Any]) -> dict[str, Any]:
    summary = row.get("candidate_summary") or row
    return {
        "candidate_id": row.get("candidate_id") or summary.get("candidate_id"),
        "selection_status": row.get("selection_status") or summary.get("selection_status"),
        "decision_reason": row.get("decision_reason") or summary.get("decision_reason"),
        "candidate_scope": summary.get("candidate_scope"),
        "upper_evidence_kind": summary.get("upper_evidence_kind"),
        "source_mode": summary.get("source_mode"),
        "layer": summary.get("layer"),
        "layer_label": summary.get("layer_label"),
        "axis_signature": summary.get("axis_signature"),
        "axis_position_m": summary.get("axis_position_m"),
        "reference_distance_to_origin_m": summary.get("reference_distance_to_origin_m"),
        "point_signature": summary.get("point_signature"),
        "primary_eligible": summary.get("primary_eligible"),
        "node_fallback_only": summary.get("node_fallback_only"),
        "positive_rcsd_present": summary.get("positive_rcsd_present"),
        "positive_rcsd_present_reason": summary.get("positive_rcsd_present_reason"),
        "positive_rcsd_support_level": summary.get("positive_rcsd_support_level"),
        "positive_rcsd_consistency_level": summary.get("positive_rcsd_consistency_level"),
        "required_rcsd_node": summary.get("required_rcsd_node"),
        "rcsd_selection_mode": summary.get("rcsd_selection_mode"),
    }


def _candidate_report(path: Path) -> dict[str, Any]:
    doc = _load_json(path)
    if not doc:
        return {"exists": False, "path": str(path)}
    rows = doc.get("candidate_audit_entries") or doc.get("candidates") or doc.get("rows") or []
    return {
        "exists": True,
        "path": str(path),
        "candidate_count": len(rows),
        "top_candidates": [_candidate_summary(row) for row in rows[:30] if isinstance(row, dict)],
    }


def _compact_positive_rcsd(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "operational_event_type": audit.get("operational_event_type"),
        "rcsd_decision_reason": audit.get("rcsd_decision_reason"),
        "published_rcsd_selection_mode": audit.get("published_rcsd_selection_mode"),
        "published_rcsdroad_ids": audit.get("published_rcsdroad_ids"),
        "published_rcsdnode_ids": audit.get("published_rcsdnode_ids"),
        "first_hit_rcsdroad_ids": audit.get("first_hit_rcsdroad_ids"),
        "selected_unit_role_assignments": audit.get("selected_unit_role_assignments"),
        "local_rcsd_units": audit.get("local_rcsd_units"),
        "aggregated_rcsd_units": audit.get("aggregated_rcsd_units"),
    }


def _case_report(run_root: Path, case_id: str) -> dict[str, Any]:
    case_dir = run_root / "cases" / case_id
    unit_dir = case_dir / "event_units" / "event_unit_01"
    step3 = _load_json(case_dir / "step3_status.json")
    step4 = _load_json(case_dir / "step4_event_interpretation.json")
    step4_audit = _load_json(case_dir / "step4_audit.json")
    step5 = _load_json(case_dir / "step5_status.json")
    step6 = _load_json(case_dir / "step6_status.json")
    step7 = _load_json(case_dir / "step7_status.json")
    unit4 = _first_unit(step4, "event_units")
    unit5 = _first_unit(step5, "unit_results")
    audit_unit = _first_unit(step4_audit, "event_units")
    selected = unit4.get("selected_evidence") or {}
    positive_audit = unit4.get("positive_rcsd_audit") or {}
    audit_positive = audit_unit.get("positive_rcsd_audit") or {}
    return {
        "case_id": case_id,
        "case_dir_exists": case_dir.is_dir(),
        "step3": step3,
        "step4_core": {
            "review_state": unit4.get("review_state"),
            "review_reasons": unit4.get("review_reasons"),
            "evidence_source": unit4.get("evidence_source"),
            "position_source": unit4.get("position_source"),
            "main_evidence_type": unit4.get("main_evidence_type"),
            "surface_scenario_type": unit4.get("surface_scenario_type"),
            "section_reference_source": unit4.get("section_reference_source"),
            "surface_generation_mode": unit4.get("surface_generation_mode"),
            "reference_point_present": unit4.get("reference_point_present"),
            "reference_point_source": unit4.get("reference_point_source"),
            "no_reference_point_reason": unit4.get("no_reference_point_reason"),
            "required_rcsd_node": unit4.get("required_rcsd_node"),
            "rcsd_match_type": unit4.get("rcsd_match_type"),
            "rcsd_selection_mode": unit4.get("rcsd_selection_mode"),
            "positive_rcsd_present": unit4.get("positive_rcsd_present"),
            "positive_rcsd_present_reason": unit4.get("positive_rcsd_present_reason"),
            "positive_rcsd_support_level": unit4.get("positive_rcsd_support_level"),
            "positive_rcsd_consistency_level": unit4.get("positive_rcsd_consistency_level"),
            "first_hit_rcsdroad_ids": unit4.get("first_hit_rcsdroad_ids"),
            "selected_rcsdroad_ids": unit4.get("selected_rcsdroad_ids"),
            "selected_rcsdnode_ids": unit4.get("selected_rcsdnode_ids"),
        },
        "selected_evidence": {
            "candidate_id": selected.get("candidate_id"),
            "candidate_scope": selected.get("candidate_scope"),
            "upper_evidence_kind": selected.get("upper_evidence_kind"),
            "source_mode": selected.get("source_mode"),
            "layer": selected.get("layer"),
            "layer_label": selected.get("layer_label"),
            "axis_signature": selected.get("axis_signature"),
            "axis_position_m": selected.get("axis_position_m"),
            "reference_distance_to_origin_m": selected.get("reference_distance_to_origin_m"),
            "point_signature": selected.get("point_signature"),
            "primary_eligible": selected.get("primary_eligible"),
            "node_fallback_only": selected.get("node_fallback_only"),
            "road_surface_fork_binding": selected.get("road_surface_fork_binding"),
        },
        "positive_rcsd_audit_from_step4": _compact_positive_rcsd(positive_audit),
        "positive_rcsd_audit_from_step4_audit": _compact_positive_rcsd(audit_positive),
        "step4_candidates": _candidate_report(unit_dir / "step4_candidates.json"),
        "step4_evidence_audit_keys": sorted((_load_json(unit_dir / "step4_evidence_audit.json") or {}).keys()),
        "step5": {
            "surface_scenario_type": unit5.get("surface_scenario_type"),
            "section_reference_source": unit5.get("section_reference_source"),
            "surface_generation_mode": unit5.get("surface_generation_mode"),
            "surface_fill_mode": unit5.get("surface_fill_mode"),
            "must_cover_components": unit5.get("must_cover_components"),
            "unit_must_cover_domain": unit5.get("unit_must_cover_domain"),
            "unit_allowed_growth_domain": unit5.get("unit_allowed_growth_domain"),
            "fallback_rcsdroad_localized": unit5.get("fallback_rcsdroad_localized"),
            "no_virtual_reference_point_guard": unit5.get("no_virtual_reference_point_guard"),
            "support_domain_from_reference_kind": unit5.get("support_domain_from_reference_kind"),
        },
        "step6": {
            "assembly_state": step6.get("assembly_state"),
            "review_reasons": step6.get("review_reasons"),
            "final_case_polygon_component_count": step6.get("final_case_polygon_component_count"),
            "single_connected_case_surface_ok": step6.get("single_connected_case_surface_ok"),
            "b_node_gate_applicable": step6.get("b_node_gate_applicable"),
            "b_node_gate_skip_reason": step6.get("b_node_gate_skip_reason"),
            "b_node_target_covered": step6.get("b_node_target_covered"),
            "post_cleanup_allowed_growth_ok": step6.get("post_cleanup_allowed_growth_ok"),
            "post_cleanup_forbidden_ok": step6.get("post_cleanup_forbidden_ok"),
            "post_cleanup_terminal_cut_ok": step6.get("post_cleanup_terminal_cut_ok"),
            "post_cleanup_lateral_limit_ok": step6.get("post_cleanup_lateral_limit_ok"),
            "final_case_polygon": step6.get("final_case_polygon"),
        },
        "step7": {
            "final_state": step7.get("final_state"),
            "reject_reason": step7.get("reject_reason"),
            "reject_reason_detail": step7.get("reject_reason_detail"),
            "publish_target": step7.get("publish_target"),
        },
        "output_geometries": {
            "final_case_polygon": _geo_summary(case_dir / "final_case_polygon.gpkg"),
            "step5_domains": _geo_summary(case_dir / "step5_domains.gpkg"),
            "step4_event_evidence": _geo_summary(case_dir / "step4_event_evidence.gpkg"),
        },
        "artifact_paths": {
            "case_dir": str(case_dir),
            "final_review_png": str(case_dir / "final_review.png"),
            "step4_review_png": str(unit_dir / "step4_review.png"),
            "step4_positive_rcsd_review_png": str(unit_dir / "step4_positive_rcsd_review.png"),
        },
    }


def _top_level_report(run_root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name in (
        "summary.json",
        "divmerge_virtual_anchor_surface_summary.json",
        "step7_consistency_report.json",
        "nodes_anchor_update_audit.json",
        "step4_road_surface_fork_binding.json",
    ):
        doc = _load_json(run_root / name)
        report[name] = {
            key: doc.get(key)
            for key in (
                "failed_case_ids",
                "row_count",
                "accepted_count",
                "rejected_count",
                "step7_accepted_count",
                "step7_rejected_count",
                "passed",
                "nodes_consistency_passed",
                "updated_to_yes_count",
                "updated_to_fail4_count",
                "nodes_updated_to_yes_count",
                "nodes_updated_to_fail4_count",
                "no_surface_reference_accepted_case_ids",
                "step6_guard_field_missing_case_ids",
                "nodes_mismatch_case_ids",
            )
            if key in doc
        } if doc else {"missing": True, "path": str(run_root / name)}
    return report


def _resolve_case_root(value: str | None) -> Path | None:
    if value:
        path = Path(value).resolve()
        return path if path.is_dir() else None
    return next((path for path in CASE_ROOT_CANDIDATES if path.is_dir()), None)


def _resolve_full_input_path(value: str, key: str) -> Path | None:
    if value:
        return Path(value).resolve()
    return next((path for path in FULL_INPUT_PATH_CANDIDATES[key] if path.is_file()), None)


def _parse_buffers(value: str) -> list[float]:
    if not value.strip():
        return list(DEFAULT_FULL_INPUT_BUFFERS)
    buffers = []
    for item in value.split(","):
        text = item.strip()
        if not text:
            continue
        buffers.append(float(text))
    return buffers or list(DEFAULT_FULL_INPUT_BUFFERS)


def _bounds(geometry: Any) -> list[float]:
    if geometry is None or getattr(geometry, "is_empty", True):
        return []
    return [round(float(item), 6) for item in geometry.bounds]


def _safe_distance(seed: Any, geometry: Any) -> float | None:
    if seed is None or geometry is None or getattr(seed, "is_empty", True) or getattr(geometry, "is_empty", True):
        return None
    try:
        return round(float(seed.distance(geometry)), 6)
    except Exception:
        return None


def _compact_properties(properties: dict[str, Any]) -> dict[str, Any]:
    preferred = (
        "id",
        "ID",
        "road_id",
        "node_id",
        "mainnodeid",
        "snodeid",
        "enodeid",
        "kind",
        "kind_2",
        "has_evd",
        "is_anchor",
        "layer",
        "Layer",
        "type",
        "name",
    )
    compact: dict[str, Any] = {}
    for key in preferred:
        if key in properties:
            compact[key] = properties.get(key)
    if compact:
        return compact
    return {str(key): properties.get(key) for key in list(properties)[:12]}


def _item_identity(item: Any) -> str:
    for attr in ("node_id", "road_id"):
        value = getattr(item, attr, None)
        if value is not None:
            return str(value)
    properties = getattr(item, "properties", {}) or {}
    for key in ("id", "ID", "road_id", "node_id"):
        value = properties.get(key)
        if value is not None:
            return str(value)
    return str(getattr(item, "feature_index", ""))


def _compact_spatial_item(item: Any, *, seed: Any) -> dict[str, Any]:
    geometry = getattr(item, "geometry", None)
    return {
        "id": _item_identity(item),
        "feature_index": getattr(item, "feature_index", None),
        "geometry_type": getattr(geometry, "geom_type", None),
        "distance_to_seed_m": _safe_distance(seed, geometry),
        "bounds": _bounds(geometry),
        "properties": _compact_properties(dict(getattr(item, "properties", {}) or {})),
    }


def _nearest_items(index: Any, *, seed: Any, buffers: list[float], limit: int = 8) -> dict[str, Any]:
    from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.full_input_shared_layers import query_spatial_index

    for buffer_m in buffers:
        window = seed.buffer(float(buffer_m), join_style=2)
        hits = list(query_spatial_index(index, window))
        if not hits:
            continue
        ordered = sorted(
            hits,
            key=lambda item: (
                float("inf")
                if _safe_distance(seed, getattr(item, "geometry", None)) is None
                else float(_safe_distance(seed, getattr(item, "geometry", None)))
            ),
        )
        return {
            "first_non_empty_buffer_m": float(buffer_m),
            "hit_count": len(hits),
            "top_hits": [_compact_spatial_item(item, seed=seed) for item in ordered[:limit]],
        }
    return {"first_non_empty_buffer_m": None, "hit_count": 0, "top_hits": []}


def _validity_summary(items: tuple[Any, ...] | list[Any]) -> dict[str, Any]:
    geometries = [
        getattr(item, "geometry", None)
        for item in items
        if getattr(item, "geometry", None) is not None and not getattr(item, "geometry", None).is_empty
    ]
    return {
        "geometry_count": len(geometries),
        "valid_all": all(bool(geometry.is_valid) for geometry in geometries),
    }


def _package_input_summaries(case_root: Path | None, case_ids: list[str]) -> dict[str, Any]:
    if case_root is None:
        return {"case_root": None, "available": False}
    return {
        "case_root": str(case_root),
        "available": True,
        "cases": {
            case_id: {
                "drivezone": _geo_summary(case_root / case_id / "drivezone.gpkg"),
                "roads": _geo_summary(case_root / case_id / "roads.gpkg"),
                "divstripzone": _geo_summary(case_root / case_id / "divstripzone.gpkg"),
                "rcsdroad": _geo_summary(case_root / case_id / "rcsdroad.gpkg"),
                "rcsdnode": _geo_summary(case_root / case_id / "rcsdnode.gpkg"),
                "nodes": _geo_summary(case_root / case_id / "nodes.gpkg"),
            }
            for case_id in case_ids
        },
    }


def _full_input_debug_report(args: argparse.Namespace, case_ids: list[str], case_root: Path | None) -> dict[str, Any]:
    from shapely.geometry import GeometryCollection
    from shapely.ops import unary_union

    from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import _resolve_group
    from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.full_input_shared_layers import (
        collect_case_features,
        load_shared_full_input_layers,
        query_spatial_index,
    )

    input_paths = {
        "nodes_path": _resolve_full_input_path(args.nodes_path, "nodes_path"),
        "roads_path": _resolve_full_input_path(args.roads_path, "roads_path"),
        "drivezone_path": _resolve_full_input_path(args.drivezone_path, "drivezone_path"),
        "divstripzone_path": _resolve_full_input_path(args.divstripzone_path, "divstripzone_path"),
        "rcsdroad_path": _resolve_full_input_path(args.rcsdroad_path, "rcsdroad_path"),
        "rcsdnode_path": _resolve_full_input_path(args.rcsdnode_path, "rcsdnode_path"),
    }
    missing = [key for key, path in input_paths.items() if path is None or not path.is_file()]
    if missing:
        return {
            "available": False,
            "missing_input_keys": missing,
            "resolved_paths": {key: str(path) if path is not None else None for key, path in input_paths.items()},
        }

    buffers = _parse_buffers(args.local_query_buffers)
    shared_layers = load_shared_full_input_layers(**{key: value for key, value in input_paths.items() if value is not None})
    cases: dict[str, Any] = {}
    for case_id in case_ids:
        representative, group_nodes = _resolve_group(mainnodeid=str(case_id), nodes=list(shared_layers.nodes))
        member_ids = {node.node_id for node in group_nodes}
        seed_roads = tuple(
            road
            for node_id in member_ids
            for road in shared_layers.node_id_to_roads.get(node_id, ())
        )
        seed_geometries = [node.geometry for node in group_nodes]
        seed_geometries.extend(
            road.geometry for road in seed_roads if road.geometry is not None and not road.geometry.is_empty
        )
        seed = unary_union(seed_geometries) if seed_geometries else representative.geometry
        if seed is None or seed.is_empty:
            seed = GeometryCollection()

        buffer_rows = []
        for buffer_m in buffers:
            selected = collect_case_features(
                layers=shared_layers,
                case_id=case_id,
                local_query_buffer_m=float(buffer_m),
            )
            selection_window = selected["selection_window"]
            polygon_clip_window = selected["polygon_clip_window"]
            raw_selection_counts = {
                "nodes": len(query_spatial_index(shared_layers.node_index, selection_window)),
                "roads": len(query_spatial_index(shared_layers.road_index, selection_window)),
                "drivezone": len(query_spatial_index(shared_layers.drivezone_index, selection_window)),
                "divstripzone": len(query_spatial_index(shared_layers.divstrip_index, selection_window)),
                "rcsdroad": len(query_spatial_index(shared_layers.rcsdroad_index, selection_window)),
                "rcsdnode": len(query_spatial_index(shared_layers.rcsdnode_index, selection_window)),
            }
            polygon_clip_counts = {
                "drivezone": len(query_spatial_index(shared_layers.drivezone_index, polygon_clip_window)),
                "divstripzone": len(query_spatial_index(shared_layers.divstrip_index, polygon_clip_window)),
            }
            selected_validity = {
                "nodes": _validity_summary(tuple(selected["nodes"])),
                "roads": _validity_summary(tuple(selected["roads"])),
                "drivezone": _validity_summary(tuple(selected["drivezone_features"])),
                "divstripzone": _validity_summary(tuple(selected["divstrip_features"])),
                "rcsdroad": _validity_summary(tuple(selected["rcsd_roads"])),
                "rcsdnode": _validity_summary(tuple(selected["rcsd_nodes"])),
            }
            buffer_rows.append(
                {
                    "buffer_m": float(buffer_m),
                    "selection_window_bounds": _bounds(selection_window),
                    "polygon_clip_window_bounds": _bounds(polygon_clip_window),
                    "raw_selection_counts": raw_selection_counts,
                    "polygon_clip_counts": polygon_clip_counts,
                    "selected_counts_after_clip": dict(selected["selected_counts"]),
                    "selected_validity": selected_validity,
                }
            )

        cases[str(case_id)] = {
            "representative": _compact_spatial_item(representative, seed=seed),
            "group_node_ids": [str(node.node_id) for node in group_nodes],
            "seed_road_ids": [str(road.road_id) for road in seed_roads],
            "seed_bounds": _bounds(seed),
            "buffer_scan": buffer_rows,
            "nearest_by_layer": {
                "divstripzone": _nearest_items(shared_layers.divstrip_index, seed=seed, buffers=buffers),
                "rcsdroad": _nearest_items(shared_layers.rcsdroad_index, seed=seed, buffers=buffers),
                "rcsdnode": _nearest_items(shared_layers.rcsdnode_index, seed=seed, buffers=buffers),
                "roads": _nearest_items(shared_layers.road_index, seed=seed, buffers=buffers),
            },
        }

    return {
        "available": True,
        "mode": "shared_full_input_feature_window_debug",
        "buffers_m": buffers,
        "input_paths": {key: str(value) for key, value in input_paths.items()},
        "shared_layer_manifest": shared_layers.layer_manifest(),
        "package_input_compare": _package_input_summaries(case_root, case_ids),
        "cases": cases,
    }


def _print_json(title: str, value: Any) -> None:
    print("\n" + "=" * 100)
    print(title)
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run or inspect T04 706243/706247 innernet diagnostics."
    )
    parser.add_argument("--case-root", default="", help="Anchor_2 case root. Auto-detects /mnt/d,/mnt/e,/mnt/c if omitted.")
    parser.add_argument("--run-root", default="", help="Existing T04 run root to inspect without rerun.")
    parser.add_argument("--case-ids", nargs="*", default=list(DEFAULT_CASE_IDS), help="Case ids to inspect.")
    parser.add_argument("--out-root", default="", help="Output root for a fresh rerun.")
    parser.add_argument(
        "--full-input-debug",
        action="store_true",
        help="Load global full-input layers and scan the shared-layer local feature windows for the cases.",
    )
    parser.add_argument(
        "--local-query-buffers",
        default=",".join(str(int(item)) for item in DEFAULT_FULL_INPUT_BUFFERS),
        help="Comma-separated buffer sizes in meters for --full-input-debug.",
    )
    parser.add_argument("--nodes-path", default="", help="Full-input nodes.gpkg path.")
    parser.add_argument("--roads-path", default="", help="Full-input roads.gpkg path.")
    parser.add_argument("--drivezone-path", default="", help="Full-input DriveZone.gpkg path.")
    parser.add_argument("--divstripzone-path", default="", help="Full-input DivStripZone.gpkg path.")
    parser.add_argument("--rcsdroad-path", default="", help="Full-input RCSDRoad.gpkg path.")
    parser.add_argument("--rcsdnode-path", default="", help="Full-input RCSDNode.gpkg path.")
    args = parser.parse_args()

    repo = Path.cwd().resolve()
    case_ids = [str(item) for item in args.case_ids]
    preflight = {
        "repo": str(repo),
        "python": sys.version,
        "platform": platform.platform(),
        "git_branch": _run_cmd(["git", "branch", "--show-current"], repo),
        "git_head": _run_cmd(["git", "log", "-1", "--oneline", "--decorate"], repo),
        "git_status": _run_cmd(["git", "status", "--short"], repo),
        "case_root_candidates": [{"path": str(path), "exists": path.is_dir()} for path in CASE_ROOT_CANDIDATES],
        "key_file_sha256": {
            "step4_road_surface_fork_binding.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding.py"),
            "event_interpretation_selection.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/event_interpretation_selection.py"),
            "support_domain.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain.py"),
            "polygon_assembly.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py"),
            "final_publish.py": _sha256(repo / "src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish.py"),
        },
    }
    _print_json("PREFLIGHT", preflight)

    if args.run_root:
        run_root = Path(args.run_root).resolve()
        if not run_root.is_dir():
            raise SystemExit(f"run root does not exist: {run_root}")
        out_root = run_root / "_probe_706243_706247"
        out_root.mkdir(parents=True, exist_ok=True)
        run_info = {"mode": "inspect_existing_run", "run_root": str(run_root), "out_root": str(out_root)}
    else:
        case_root = _resolve_case_root(args.case_root or None)
        if case_root is None:
            raise SystemExit("case root not found; pass --case-root explicitly")
        missing = [case_id for case_id in case_ids if not (case_root / case_id).is_dir()]
        if missing:
            raise SystemExit(f"missing case directories under {case_root}: {missing}")
        _print_json(
            "INPUT_GPKG",
            {
                case_id: {
                    "drivezone": _geo_summary(case_root / case_id / "drivezone.gpkg"),
                    "roads": _geo_summary(case_root / case_id / "roads.gpkg"),
                    "divstripzone": _geo_summary(case_root / case_id / "divstripzone.gpkg"),
                    "rcsdroad": _geo_summary(case_root / case_id / "rcsdroad.gpkg"),
                    "rcsdnode": _geo_summary(case_root / case_id / "rcsdnode.gpkg"),
                    "nodes": _geo_summary(case_root / case_id / "nodes.gpkg"),
                }
                for case_id in case_ids
            },
        )
        from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch

        started = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_root = Path(args.out_root).resolve() if args.out_root else repo / "outputs/_work" / f"t04_probe_706243_706247_deep_{timestamp}"
        try:
            run_root = run_t04_step14_batch(
                case_root=case_root,
                case_ids=case_ids,
                out_root=out_root,
                run_id=f"t04_probe_706243_706247_deep_{timestamp}",
            )
            run_error = None
        except Exception:
            run_root = out_root
            run_error = traceback.format_exc()
        run_info = {
            "mode": "fresh_rerun",
            "case_root": str(case_root),
            "case_ids": case_ids,
            "run_root": str(run_root),
            "out_root": str(out_root),
            "elapsed_s": round(time.time() - started, 3),
            "run_error": run_error,
        }
        if run_error:
            _print_json("RUN_FAILED", run_info)
            return 4

    _print_json("RUN", run_info)
    case_root_for_compare = _resolve_case_root(args.case_root or None)
    full_input_debug = (
        _full_input_debug_report(args, case_ids, case_root_for_compare)
        if args.full_input_debug
        else {"enabled": False}
    )
    if args.full_input_debug:
        _print_json("FULL_INPUT_DEBUG", full_input_debug)
    report = {
        "preflight": preflight,
        "run": run_info,
        "top_level": _top_level_report(run_root),
        "full_input_debug": full_input_debug,
        "cases": {case_id: _case_report(run_root, case_id) for case_id in case_ids},
    }
    for case_id, case_report in report["cases"].items():
        _print_json(f"CASE_REPORT_{case_id}", case_report)

    report_path = out_root / "analysis_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _print_json("DONE", {"run_root": str(run_root), "report": str(report_path)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
