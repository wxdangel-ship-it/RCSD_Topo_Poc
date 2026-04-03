from __future__ import annotations

import argparse
import json
import math
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
from pyproj import CRS
from shapely.geometry import GeometryCollection, Point
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    TARGET_CRS,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t02_junction_anchor.shared import T02RunError, find_repo_root, normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    DEFAULT_PATCH_SIZE_M,
    DEFAULT_RESOLUTION_M,
    ROAD_BUFFER_M,
    RC_NODE_SEED_RADIUS_M,
    RC_ROAD_BUFFER_M,
    NODE_SEED_RADIUS_M,
    ParsedNode,
    ParsedRoad,
    _binary_close,
    _build_debug_focus_geometry,
    _build_grid,
    _build_road_branches_for_member_nodes,
    _extract_seed_component,
    _load_layer_filtered,
    _mask_to_geometry,
    _parse_nodes,
    _parse_rc_nodes,
    _parse_roads,
    _rasterize_geometries,
    _regularize_virtual_polygon_geometry,
    _resolve_group,
    _select_main_pair,
    _write_debug_rendered_map,
)


REASON_MISSING_REQUIRED_FIELD = "missing_required_field"
REASON_INVALID_CRS_OR_UNPROJECTABLE = "invalid_crs_or_unprojectable"
REASON_MAINNODEID_NOT_FOUND = "mainnodeid_not_found"
REASON_MAINNODEID_OUT_OF_SCOPE = "mainnodeid_out_of_scope"
REASON_MAIN_DIRECTION_UNSTABLE = "main_direction_unstable"
REASON_RCS_OUTSIDE_DRIVEZONE = "rcsd_outside_drivezone"
REASON_COVERAGE_INCOMPLETE = "coverage_incomplete"
STAGE4_KIND_2_VALUES = {8, 16}


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _tracemalloc_stats() -> dict[str, int]:
    if not tracemalloc.is_tracing():
        return {
            "python_tracemalloc_current_bytes": 0,
            "python_tracemalloc_peak_bytes": 0,
        }
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    return {
        "python_tracemalloc_current_bytes": current_bytes,
        "python_tracemalloc_peak_bytes": peak_bytes,
    }


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or build_run_id("t02_stage4_divmerge_virtual_polygon")
    if out_root is not None:
        return Path(out_root) / resolved_run_id, resolved_run_id

    repo_root = find_repo_root(cwd or Path.cwd())
    if repo_root is None:
        raise Stage4RunError(
            REASON_MISSING_REQUIRED_FIELD,
            "Cannot infer default out_root because repo root was not found; please pass --out-root.",
        )
    return repo_root / "outputs" / "_work" / "t02_stage4_divmerge_virtual_polygon" / resolved_run_id, resolved_run_id


def _write_progress_snapshot(
    *,
    out_path: Path,
    run_id: str,
    status: str,
    current_stage: str | None,
    message: str,
    counts: dict[str, Any],
) -> None:
    write_json(
        out_path,
        {
            "run_id": run_id,
            "status": status,
            "updated_at": _now_text(),
            "current_stage": current_stage,
            "message": message,
            "counts": counts,
            **_tracemalloc_stats(),
        },
    )


def _record_perf_marker(
    *,
    out_path: Path,
    run_id: str,
    stage: str,
    elapsed_sec: float,
    counts: dict[str, Any],
    note: str | None = None,
) -> None:
    marker = {
        "event": "stage_marker",
        "run_id": run_id,
        "at": _now_text(),
        "stage": stage,
        "elapsed_sec": round(elapsed_sec, 6),
        "counts": counts,
        **_tracemalloc_stats(),
    }
    if note is not None:
        marker["note"] = note
    _append_jsonl(out_path, marker)


class Stage4RunError(T02RunError):
    pass


@dataclass(frozen=True)
class Stage4Artifacts:
    success: bool
    out_root: Path
    virtual_polygon_path: Path
    node_link_json_path: Path
    rcsdnode_link_json_path: Path
    audit_json_path: Path
    status_path: Path
    log_path: Path
    progress_path: Path
    perf_json_path: Path
    perf_markers_path: Path
    debug_dir: Path | None = None
    status_doc: dict[str, Any] | None = None
    perf_doc: dict[str, Any] | None = None


def _cover_check(geometry, candidates: list[ParsedNode]) -> list[str]:
    cover = geometry.buffer(0)
    return [node.node_id for node in candidates if not cover.covers(node.geometry)]


def _selected_branch_score(branch) -> float:
    return float(branch.road_support_m + branch.drivezone_support_m + branch.rc_support_m)


def _select_stage4_side_branches(road_branches, *, kind_2: int) -> list[Any]:
    selected = [branch for branch in road_branches if not branch.is_main_direction]
    if kind_2 == 8:
        selected = [branch for branch in selected if branch.has_incoming_support or not branch.has_outgoing_support]
    else:
        selected = [branch for branch in selected if branch.has_outgoing_support or not branch.has_incoming_support]
    if not selected:
        selected = [branch for branch in road_branches if not branch.is_main_direction]
    selected.sort(key=_selected_branch_score, reverse=True)
    return selected[:2]


def _load_layer(
    path: Union[str, Path],
    *,
    layer_name: Optional[str],
    crs_override: Optional[str],
    allow_null_geometry: bool,
) -> Any:
    try:
        return _load_layer_filtered(
            path,
            layer_name=layer_name,
            crs_override=crs_override,
            allow_null_geometry=allow_null_geometry,
        )
    except Exception as exc:
        if hasattr(exc, "reason") and hasattr(exc, "detail"):
            raise Stage4RunError(getattr(exc, "reason"), getattr(exc, "detail")) from exc
        raise Stage4RunError(REASON_INVALID_CRS_OR_UNPROJECTABLE, str(exc)) from exc


def _validate_drivezone_containment(
    *,
    drivezone_union,
    features: list[Any],
    label: str,
) -> list[str]:
    outside_ids: list[str] = []
    drivezone_cover = drivezone_union.buffer(0)
    for feature in features:
        feature_id = normalize_id(feature.node_id if hasattr(feature, "node_id") else getattr(feature, "road_id", None))
        if feature.geometry is None or feature.geometry.is_empty:
            continue
        if drivezone_cover.covers(feature.geometry):
            continue
        outside_ids.append(feature_id or "unknown")
    if outside_ids:
        raise Stage4RunError(
            REASON_RCS_OUTSIDE_DRIVEZONE,
            f"{label} features are outside DriveZone: {','.join(sorted(set(outside_ids)))}",
        )
    return outside_ids


def _make_link_doc(
    *,
    mainnodeid: str,
    kind_2: int,
    grade_2: int | None,
    target_node_ids: list[str],
    linked_node_ids: list[str],
    selected_branch_ids: list[str],
    selected_road_ids: list[str],
    coverage_missing_ids: list[str],
) -> dict[str, Any]:
    return {
        "mainnodeid": mainnodeid,
        "kind_2": kind_2,
        "grade_2": grade_2,
        "target_node_ids": target_node_ids,
        "linked_node_ids": linked_node_ids,
        "selected_branch_ids": selected_branch_ids,
        "selected_road_ids": selected_road_ids,
        "coverage_missing_ids": coverage_missing_ids,
    }


def run_t02_stage4_divmerge_virtual_polygon(
    *,
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    drivezone_path: Union[str, Path],
    rcsdroad_path: Union[str, Path],
    rcsdnode_path: Union[str, Path],
    mainnodeid: Union[str, int],
    out_root: Optional[Union[str, Path]] = None,
    run_id: Optional[str] = None,
    nodes_layer: Optional[str] = None,
    roads_layer: Optional[str] = None,
    drivezone_layer: Optional[str] = None,
    rcsdroad_layer: Optional[str] = None,
    rcsdnode_layer: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    roads_crs: Optional[str] = None,
    drivezone_crs: Optional[str] = None,
    rcsdroad_crs: Optional[str] = None,
    rcsdnode_crs: Optional[str] = None,
    debug: bool = False,
    trace_memory: bool = True,
) -> Stage4Artifacts:
    if trace_memory and not tracemalloc.is_tracing():
        tracemalloc.start()

    started_at = time.perf_counter()
    out_root_path, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    out_root_path.mkdir(parents=True, exist_ok=True)

    virtual_polygon_path = out_root_path / "stage4_virtual_polygon.gpkg"
    node_link_json_path = out_root_path / "stage4_node_link.json"
    rcsdnode_link_json_path = out_root_path / "stage4_rcsdnode_link.json"
    audit_json_path = out_root_path / "stage4_audit.json"
    status_path = out_root_path / "stage4_status.json"
    log_path = out_root_path / "stage4_divmerge_virtual_polygon.log"
    progress_path = out_root_path / "stage4_progress.json"
    perf_json_path = out_root_path / "stage4_perf.json"
    perf_markers_path = out_root_path / "stage4_perf_markers.jsonl"
    debug_dir = out_root_path / "stage4_debug" if debug else None
    debug_render_path = debug_dir / f"{normalize_id(mainnodeid) or 'unknown'}.png" if debug_dir is not None else None

    logger = build_logger(log_path, f"t02_stage4_divmerge_virtual_polygon.{resolved_run_id}")
    counts: dict[str, Any] = {
        "mainnodeid": normalize_id(mainnodeid),
        "node_feature_count": 0,
        "road_feature_count": 0,
        "drivezone_feature_count": 0,
        "rcsdroad_feature_count": 0,
        "rcsdnode_feature_count": 0,
        "target_node_count": 0,
        "target_rcsdnode_count": 0,
        "selected_branch_count": 0,
        "selected_road_count": 0,
        "selected_rcsdroad_count": 0,
        "selected_rcsdnode_count": 0,
        "audit_count": 0,
    }
    audit_rows: list[dict[str, Any]] = []
    stage_timings: list[dict[str, Any]] = []

    def _snapshot(status: str, current_stage: str | None, message: str) -> None:
        counts["audit_count"] = len(audit_rows)
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status=status,
            current_stage=current_stage,
            message=message,
            counts=dict(counts),
        )

    def _mark(stage_name: str, started_at_stage: float, note: str | None = None) -> None:
        elapsed_sec = time.perf_counter() - started_at_stage
        stage_timings.append(
            {
                "stage": stage_name,
                "elapsed_sec": round(elapsed_sec, 6),
                **_tracemalloc_stats(),
            }
        )
        _record_perf_marker(
            out_path=perf_markers_path,
            run_id=resolved_run_id,
            stage=stage_name,
            elapsed_sec=elapsed_sec,
            counts=dict(counts),
            note=note,
        )

    def _write_link_json(path: Path, payload: dict[str, Any]) -> None:
        write_json(path, payload)

    try:
        _snapshot("running", "bootstrap", "Stage4 bootstrap started.")
        announce(logger, f"[T02-Stage4] start run_id={resolved_run_id}")

        load_started_at = time.perf_counter()
        nodes_layer_data = _load_layer(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=False,
        )
        roads_layer_data = _load_layer(
            roads_path,
            layer_name=roads_layer,
            crs_override=roads_crs,
            allow_null_geometry=False,
        )
        drivezone_layer_data = _load_layer(
            drivezone_path,
            layer_name=drivezone_layer,
            crs_override=drivezone_crs,
            allow_null_geometry=False,
        )
        rcsdroad_layer_data = _load_layer(
            rcsdroad_path,
            layer_name=rcsdroad_layer,
            crs_override=rcsdroad_crs,
            allow_null_geometry=False,
        )
        rcsdnode_layer_data = _load_layer(
            rcsdnode_path,
            layer_name=rcsdnode_layer,
            crs_override=rcsdnode_crs,
            allow_null_geometry=False,
        )
        counts["node_feature_count"] = len(nodes_layer_data.features)
        counts["road_feature_count"] = len(roads_layer_data.features)
        counts["drivezone_feature_count"] = len(drivezone_layer_data.features)
        counts["rcsdroad_feature_count"] = len(rcsdroad_layer_data.features)
        counts["rcsdnode_feature_count"] = len(rcsdnode_layer_data.features)
        _snapshot("running", "inputs_loaded", "Input layers loaded and projected to EPSG:3857.")
        _mark("inputs_loaded", load_started_at)

        nodes = _parse_nodes(nodes_layer_data, require_anchor_fields=True)
        roads = _parse_roads(roads_layer_data, label="Road")
        rcsd_roads = _parse_roads(rcsdroad_layer_data, label="RCSDRoad")
        rcsd_nodes = _parse_rc_nodes(rcsdnode_layer_data)

        mainnodeid_norm = normalize_id(mainnodeid)
        if mainnodeid_norm is None:
            raise Stage4RunError(REASON_MAINNODEID_NOT_FOUND, "mainnodeid is empty.")

        target_group = _resolve_group(mainnodeid=mainnodeid_norm, nodes=nodes)
        representative_node, group_nodes = target_group
        representative_kind_2 = representative_node.kind_2
        representative_grade_2 = representative_node.grade_2
        if representative_node.has_evd != "yes" or representative_node.is_anchor != "no" or representative_kind_2 not in STAGE4_KIND_2_VALUES:
            raise Stage4RunError(
                REASON_MAINNODEID_OUT_OF_SCOPE,
                (
                    f"mainnodeid='{mainnodeid_norm}' is out of scope: "
                    f"has_evd={representative_node.has_evd}, is_anchor={representative_node.is_anchor}, "
                    f"kind_2={representative_kind_2}."
                ),
            )

        target_rc_nodes = [
            node
            for node in rcsd_nodes
            if node.mainnodeid == mainnodeid_norm or (node.mainnodeid is None and node.node_id == mainnodeid_norm)
        ]
        if not target_rc_nodes:
            raise Stage4RunError(
                REASON_MAINNODEID_NOT_FOUND,
                f"RCSDNode has no seed group for mainnodeid='{mainnodeid_norm}'.",
            )

        drivezone_union = unary_union([feature.geometry for feature in drivezone_layer_data.features if feature.geometry is not None and not feature.geometry.is_empty])
        if drivezone_union.is_empty:
            raise Stage4RunError(REASON_MISSING_REQUIRED_FIELD, "DriveZone layer has no non-empty geometry.")

        _validate_drivezone_containment(drivezone_union=drivezone_union, features=rcsd_roads, label="RCSDRoad")
        _validate_drivezone_containment(drivezone_union=drivezone_union, features=rcsd_nodes, label="RCSDNode")

        seed_geometries = [representative_node.geometry, *[node.geometry for node in group_nodes], *[node.geometry for node in target_rc_nodes]]
        seed_union = unary_union(seed_geometries)
        seed_center = seed_union.centroid if not seed_union.is_empty else representative_node.geometry
        farthest_seed_distance = max((float(Point(seed.x, seed.y).distance(seed_center)) for seed in [representative_node.geometry, *[node.geometry for node in group_nodes], *[node.geometry for node in target_rc_nodes]]), default=0.0)
        patch_size_m = max(DEFAULT_PATCH_SIZE_M, farthest_seed_distance * 2.0 + 60.0)
        grid = _build_grid(seed_center, patch_size_m=patch_size_m, resolution_m=DEFAULT_RESOLUTION_M)
        drivezone_mask = _rasterize_geometries(grid, [drivezone_union])

        local_nodes = [node for node in nodes if node.geometry.intersects(grid.patch_polygon)]
        local_roads = [road for road in roads if road.geometry.intersects(grid.patch_polygon)]
        local_rcsd_roads = [road for road in rcsd_roads if road.geometry.intersects(grid.patch_polygon)]
        local_rcsd_nodes = [node for node in rcsd_nodes if node.geometry.intersects(grid.patch_polygon)]

        member_node_ids = {node.node_id for node in group_nodes}
        _, _, road_branches = _build_road_branches_for_member_nodes(
            local_roads,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
        )
        if len(road_branches) < 2:
            raise Stage4RunError(
                REASON_MAIN_DIRECTION_UNSTABLE,
                "Need at least two incident road branches to identify a stable Stage4 face.",
            )
        main_branch_ids = set(_select_main_pair(road_branches))
        side_branches = _select_stage4_side_branches(road_branches, kind_2=representative_kind_2 or 0)
        selected_branch_ids = sorted(main_branch_ids | {branch.branch_id for branch in side_branches})

        selected_road_ids = sorted({road_id for branch in road_branches if branch.branch_id in selected_branch_ids for road_id in branch.road_ids})
        selected_rcsdroad_ids: set[str] = set()
        _, _, rc_branches = _build_road_branches_for_member_nodes(
            local_rcsd_roads,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
        )
        for rc_branch in rc_branches:
            for road_branch in road_branches:
                if road_branch.branch_id not in selected_branch_ids:
                    continue
                if abs(road_branch.angle_deg - rc_branch.angle_deg) <= 35.0 or min(abs(road_branch.angle_deg - rc_branch.angle_deg), 360.0 - abs(road_branch.angle_deg - rc_branch.angle_deg)) <= 35.0:
                    selected_rcsdroad_ids.update(rc_branch.road_ids)
                    break
        if not selected_rcsdroad_ids:
            selected_rcsdroad_ids = {road.road_id for road in local_rcsd_roads if road.geometry.distance(seed_center) <= max(30.0, patch_size_m / 5.0)}

        selected_roads = [road for road in local_roads if road.road_id in selected_road_ids]
        selected_rcsd_roads = [road for road in local_rcsd_roads if road.road_id in selected_rcsdroad_ids]
        selected_rcsdnode_ids = {
            node.node_id
            for node in local_rcsd_nodes
            if node.mainnodeid == mainnodeid_norm or node.node_id in {road.snodeid for road in selected_rcsd_roads} | {road.enodeid for road in selected_rcsd_roads}
        }
        if not selected_rcsdnode_ids:
            selected_rcsdnode_ids = {node.node_id for node in target_rc_nodes}

        support_geometries = [
            *[road.geometry.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2) for road in selected_roads],
            *[road.geometry.buffer(RC_ROAD_BUFFER_M, cap_style=2, join_style=2) for road in selected_rcsd_roads],
            *[node.geometry.buffer(NODE_SEED_RADIUS_M) for node in group_nodes],
            *[node.geometry.buffer(RC_NODE_SEED_RADIUS_M) for node in target_rc_nodes],
        ]
        support_mask = _rasterize_geometries(grid, support_geometries) & drivezone_mask
        support_mask = _binary_close(support_mask, iterations=1)

        seed_mask = _rasterize_geometries(
            grid,
            [
                *[node.geometry.buffer(NODE_SEED_RADIUS_M) for node in group_nodes],
                *[node.geometry.buffer(RC_NODE_SEED_RADIUS_M) for node in target_rc_nodes],
            ],
        )
        component_mask = _extract_seed_component(support_mask, seed_mask)
        if not component_mask.any():
            raise Stage4RunError(
                REASON_MAIN_DIRECTION_UNSTABLE,
                "Stage4 raster support could not form a seed-connected component.",
            )

        polygon_geometry = _mask_to_geometry(component_mask, grid)
        polygon_geometry = _regularize_virtual_polygon_geometry(
            geometry=polygon_geometry,
            drivezone_union=drivezone_union,
            seed_geometry=seed_union,
        )
        if polygon_geometry.is_empty:
            raise Stage4RunError(
                REASON_MAIN_DIRECTION_UNSTABLE,
                "Stage4 regularized polygon is empty.",
            )

        coverage_missing_ids = _cover_check(polygon_geometry, [*group_nodes, *target_rc_nodes])
        acceptance_class = "accepted" if not coverage_missing_ids else "review_required"
        acceptance_reason = "stable" if not coverage_missing_ids else REASON_COVERAGE_INCOMPLETE
        success = acceptance_class == "accepted"

        counts["target_node_count"] = len(group_nodes)
        counts["target_rcsdnode_count"] = len(target_rc_nodes)
        counts["selected_branch_count"] = len(selected_branch_ids)
        counts["selected_road_count"] = len(selected_roads)
        counts["selected_rcsdroad_count"] = len(selected_rcsd_roads)
        counts["selected_rcsdnode_count"] = len(selected_rcsdnode_ids)

        polygon_feature = {
            "properties": {
                "mainnodeid": mainnodeid_norm,
                "kind_2": representative_kind_2,
                "grade_2": representative_grade_2,
                "status": acceptance_reason,
                "acceptance_class": acceptance_class,
                "acceptance_reason": acceptance_reason,
                "target_node_count": len(group_nodes),
                "target_rcsdnode_count": len(target_rc_nodes),
                "selected_branch_count": len(selected_branch_ids),
                "selected_road_count": len(selected_roads),
                "selected_rcsdroad_count": len(selected_rcsd_roads),
                "selected_rcsdnode_count": len(selected_rcsdnode_ids),
                "coverage_missing_count": len(coverage_missing_ids),
            },
            "geometry": polygon_geometry,
        }
        write_vector(virtual_polygon_path, [polygon_feature], crs_text=TARGET_CRS.to_string())

        node_link_doc = _make_link_doc(
            mainnodeid=mainnodeid_norm,
            kind_2=representative_kind_2 or 0,
            grade_2=representative_grade_2,
            target_node_ids=[node.node_id for node in group_nodes],
            linked_node_ids=[node.node_id for node in group_nodes],
            selected_branch_ids=selected_branch_ids,
            selected_road_ids=selected_road_ids,
            coverage_missing_ids=coverage_missing_ids,
        )
        rcsdnode_link_doc = _make_link_doc(
            mainnodeid=mainnodeid_norm,
            kind_2=representative_kind_2 or 0,
            grade_2=representative_grade_2,
            target_node_ids=[node.node_id for node in target_rc_nodes],
            linked_node_ids=sorted(selected_rcsdnode_ids),
            selected_branch_ids=selected_branch_ids,
            selected_road_ids=sorted(selected_rcsdroad_ids),
            coverage_missing_ids=coverage_missing_ids,
        )
        _write_link_json(node_link_json_path, node_link_doc)
        _write_link_json(rcsdnode_link_json_path, rcsdnode_link_doc)

        if debug and debug_render_path is not None:
            debug_dir = debug_render_path.parent
            debug_dir.mkdir(parents=True, exist_ok=True)
            _write_debug_rendered_map(
                out_path=debug_render_path,
                grid=grid,
                drivezone_mask=drivezone_mask,
                polygon_geometry=polygon_geometry,
                representative_node=representative_node,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
                local_roads=local_roads,
                local_rc_nodes=local_rcsd_nodes,
                local_rc_roads=local_rcsd_roads,
                selected_rc_roads=selected_rcsd_roads,
                selected_rc_node_ids=selected_rcsdnode_ids,
                excluded_rc_road_ids={local_road.road_id for local_road in local_rcsd_roads if local_road.road_id not in selected_rcsdroad_ids},
                excluded_rc_node_ids={node.node_id for node in local_rcsd_nodes if node.node_id not in selected_rcsdnode_ids},
                failure_reason=None if acceptance_class == "accepted" else acceptance_reason,
            )

        status_doc = {
            "run_id": resolved_run_id,
            "success": success,
            "flow_success": True,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "mainnodeid": mainnodeid_norm,
            "kind_2": representative_kind_2,
            "grade_2": representative_grade_2,
            "counts": counts,
            "coverage_missing_ids": coverage_missing_ids,
            "output_files": {
                "stage4_virtual_polygon": str(virtual_polygon_path),
                "stage4_node_link": str(node_link_json_path),
                "stage4_rcsdnode_link": str(rcsdnode_link_json_path),
                "stage4_audit": str(audit_json_path),
                "stage4_debug": str(debug_dir) if debug_dir is not None else None,
            },
        }
        audit_rows.append(
            {
                "scope": "stage4_divmerge_virtual_polygon",
                "status": "warning" if coverage_missing_ids else "info",
                "reason": acceptance_reason,
                "detail": "Coverage incomplete for selected node/RCSDNode seed(s)." if coverage_missing_ids else "Stage4 polygon accepted.",
                "coverage_missing_ids": coverage_missing_ids,
            }
        )
        write_json(audit_json_path, {"run_id": resolved_run_id, "audit_count": len(audit_rows), "rows": audit_rows})
        write_json(status_path, status_doc)
        _snapshot("success" if success else "completed_with_review_required_result", "complete", "Stage4 completed.")

        perf_doc = {
            "run_id": resolved_run_id,
            "success": success,
            "flow_success": True,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "counts": counts,
            "stage_timings": stage_timings,
            "total_wall_time_sec": round(time.perf_counter() - started_at, 6),
            **_tracemalloc_stats(),
        }
        write_json(perf_json_path, perf_doc)
        announce(
            logger,
            (
                "[T02-Stage4] complete "
                f"acceptance_class={acceptance_class} selected_road_count={counts['selected_road_count']} "
                f"selected_rcsdroad_count={counts['selected_rcsdroad_count']} out_root={out_root_path}"
            ),
        )
        return Stage4Artifacts(
            success=success,
            out_root=out_root_path,
            virtual_polygon_path=virtual_polygon_path,
            node_link_json_path=node_link_json_path,
            rcsdnode_link_json_path=rcsdnode_link_json_path,
            audit_json_path=audit_json_path,
            status_path=status_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
            debug_dir=debug_dir,
            status_doc=status_doc,
            perf_doc=perf_doc,
        )
    except Stage4RunError as exc:
        audit_rows.append(
            {
                "scope": "stage4_divmerge_virtual_polygon",
                "status": "failed",
                "reason": exc.reason,
                "detail": exc.detail,
                "mainnodeid": normalize_id(mainnodeid),
            }
        )
        counts["audit_count"] = len(audit_rows)
        _snapshot("failed", "failed", exc.detail)
        write_json(audit_json_path, {"run_id": resolved_run_id, "audit_count": len(audit_rows), "rows": audit_rows})
        status_doc = {
            "run_id": resolved_run_id,
            "success": False,
            "flow_success": False,
            "acceptance_class": "rejected",
            "acceptance_reason": exc.reason,
            "mainnodeid": normalize_id(mainnodeid),
            "status": exc.reason,
            "detail": exc.detail,
            "counts": counts,
            "output_files": {
                "stage4_virtual_polygon": str(virtual_polygon_path),
                "stage4_node_link": str(node_link_json_path),
                "stage4_rcsdnode_link": str(rcsdnode_link_json_path),
                "stage4_audit": str(audit_json_path),
                "stage4_debug": str(debug_dir) if debug_dir is not None else None,
            },
        }
        perf_doc = {
            "run_id": resolved_run_id,
            "success": False,
            "flow_success": False,
            "acceptance_class": "rejected",
            "acceptance_reason": exc.reason,
            "counts": counts,
            "stage_timings": stage_timings,
            "total_wall_time_sec": round(time.perf_counter() - started_at, 6),
            **_tracemalloc_stats(),
        }
        write_json(status_path, status_doc)
        write_json(perf_json_path, perf_doc)
        announce(logger, f"[T02-Stage4] failed reason={exc.reason} detail={exc.detail}")
        return Stage4Artifacts(
            success=False,
            out_root=out_root_path,
            virtual_polygon_path=virtual_polygon_path,
            node_link_json_path=node_link_json_path,
            rcsdnode_link_json_path=rcsdnode_link_json_path,
            audit_json_path=audit_json_path,
            status_path=status_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
            debug_dir=debug_dir,
            status_doc=status_doc,
            perf_doc=perf_doc,
        )
    finally:
        close_logger(logger)
        if trace_memory:
            tracemalloc.stop()


def run_t02_stage4_divmerge_virtual_polygon_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        nodes_path=args.nodes_path,
        roads_path=args.roads_path,
        drivezone_path=args.drivezone_path,
        rcsdroad_path=args.rcsdroad_path,
        rcsdnode_path=args.rcsdnode_path,
        mainnodeid=args.mainnodeid,
        out_root=args.out_root,
        run_id=args.run_id,
        nodes_layer=args.nodes_layer,
        roads_layer=args.roads_layer,
        drivezone_layer=args.drivezone_layer,
        rcsdroad_layer=args.rcsdroad_layer,
        rcsdnode_layer=args.rcsdnode_layer,
        nodes_crs=args.nodes_crs,
        roads_crs=args.roads_crs,
        drivezone_crs=args.drivezone_crs,
        rcsdroad_crs=args.rcsdroad_crs,
        rcsdnode_crs=args.rcsdnode_crs,
        debug=args.debug,
    )
    return 0 if artifacts.success else 2
