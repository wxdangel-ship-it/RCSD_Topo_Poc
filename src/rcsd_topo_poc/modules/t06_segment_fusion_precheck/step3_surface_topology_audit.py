from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.ops import linemerge, substring

from .io import read_features, write_feature_triplet, write_json
from .parsing import normalize_id, unique_preserve_order
from .schemas import (
    STEP2_FAILURE_BUSINESS_AUDIT_STEM,
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP3_FRCSD_NODE_STEM,
    STEP3_FRCSD_ROAD_STEM,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
)
from .step3_relation_node_map import sync_retained_swsd_carrier_mainnodes
from .step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
    build_topology_connectivity_audit_rows,
    summarize_topology_connectivity_audit,
)


SURFACE_TOPOLOGY_AUDIT_STEM = "t06_step3_surface_topology_audit"
SURFACE_TOPOLOGY_SUMMARY = "t06_step3_surface_topology_summary.json"
MAX_EXISTING_CROSS_SOURCE_1V1_DISTANCE_M = 20.0
MAX_T04_PATCH_1V1_DISTANCE_M = 20.0
MAX_RELATION_MAPPED_BOUNDARY_1V1_DISTANCE_M = 20.0
MAX_SURFACE_NEAREST_MULTI_CANDIDATE_DISTANCE_M = 5.0
MIN_SURFACE_NEAREST_MULTI_CANDIDATE_SEPARATION_M = 10.0
SURFACE_NEAREST_MULTI_CANDIDATE_LAYERS = {"t03", "t05"}
MAX_SELECTED_REPLACEMENT_ENDPOINT_DISTANCE_M = 5.0
MAX_SELECTED_REPLACEMENT_ENDPOINT_AMBIGUITY_M = 10.0
MAX_SELECTED_REPLACEMENT_MIDROAD_DISTANCE_M = 5.0
MIN_SELECTED_REPLACEMENT_MIDROAD_ENDPOINT_DISTANCE_M = 1.0
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_CANDIDATES = 2
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_GAP_SPREAD_M = 1.0
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_PROJECTED_DISTANCE_M = 10.0
SELECTED_REPLACEMENT_MIDROAD_SPLIT_REASON = "surface_topology_selected_replacement_midroad"
SURFACE_TOPOLOGY_AUDIT_FIELDS = [
    "audit_layer",
    "audit_status",
    "audit_reason",
    "action",
    "swsd_node_id",
    "swsd_segment_ids",
    "frcsd_node_ids",
    "swsd_patch_ids",
    "surface_patch_ids",
    "surface_layers",
    "surface_candidate_node_ids",
    "t04_reject_reasons",
    "source1_node_count",
    "source2_node_count",
    "max_pairwise_distance_m",
    "closure_mainnodeid",
]


from .step3_surface_topology_support import (
    _load_surfaces,
    _load_t04_rejects,
    _load_step2_optional_junc_mappings,
    _load_step2_dropped_junc_nodes,
    _iter_step2_junc_rows,
    _step2_junc_roots,
    _read_step2_junc_rows,
    _road_features_by_id,
    _road_features_by_id_from_features,
    _relation_props_by_segment,
    _swsd_patch_ids_by_node,
    _node_info,
    _surface_hits,
    _surface_candidate_node_ids,
    _closure_mainnodeid,
    _has_effective_mainnode,
    _can_resolve_closure_mainnode,
    _source2_default_mainnodeid,
    _fieldnames_from_gpkg,
    _feature_id,
    _parse_id_list,
    _patch_ids,
    _safe_id,
    _float_or_none,
    _int_or_none,
    _bool_or_none,
    _distance_within,
    _points_geometry,
)

from .step3_surface_topology_relation import (
    _apply_step2_plan_relation_node_map_updates,
    _set_relation_node_map_entry,
    _apply_relation_node_map_updates,
    _replace_relation_road_ids,
    _selected_midroad_node_ids,
    _upsert_relation_node_map,
    _node_map_entries,
    _rebuild_topology_connectivity_audit,
    _write_topology_connectivity_audit_rows,
    _is_surface_action_row,
    _unique_surface_audit_rows,
    _surface_summary,
    _merge_step3_summary,
)

from .step3_surface_topology_selection import (
    _failed_junction_rows,
    _classify_surface_junction,
    _surface_1v1_fallback_node,
    _source_node_by_mainnode,
    _step2_optional_junc_fallback_node,
    _surface_nearest_multi_candidate_node,
    _selected_replacement_endpoint_fallback_node,
    _selected_replacement_midroad_projection,
    _select_midroad_projection_candidates,
    _new_midroad_node,
    _split_midroad_projection_road,
    _road_endpoint_ids,
    _feature_line,
    _next_split_road_ids,
    _next_generated_id,
    _next_numeric_id,
    _relation_mapped_boundary_fallback_node,
    _has_swsd_surface_hit,
    _is_t07_accepted_1v1_hit,
    _has_t04_patch_1v1_evidence,
    _t04_reject_node_1v1_fallback_node,
    _is_t04_reject_node_1v1_allowed,
)

from .step3_surface_topology_rows import (
    _build_surface_audit_rows,
)
from .step3_surface_runtime import Step3SurfaceRuntimeState

def run_surface_topology_postprocess(
    *,
    step_root: str | Path,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    t07_surface_path: str | Path | None = None,
    t03_surface_path: str | Path | None = None,
    t04_surface_path: str | Path | None = None,
    t04_audit_path: str | Path | None = None,
    t05_surface_path: str | Path | None = None,
    source_field_name: str = "source",
    swsd_source_value: int = 2,
    rcsd_source_value: int = 1,
    apply_closure: bool = True,
    topology_coverage_cache: dict[Any, Any] | None = None,
    runtime_state: Step3SurfaceRuntimeState | None = None,
) -> dict[str, Any]:
    resolved_step_root = Path(step_root)
    node_path = resolved_step_root / f"{STEP3_FRCSD_NODE_STEM}.gpkg"
    topology_path = resolved_step_root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    if runtime_state is None and not node_path.is_file():
        return {"surface_topology_status": "skipped", "surface_topology_reason": "missing_step3_outputs"}

    node_features = runtime_state.frcsd_nodes if runtime_state is not None else read_features(node_path)
    node_fields = (
        _runtime_fieldnames(node_features)
        if runtime_state is not None and not node_path.is_file()
        else _fieldnames_from_gpkg(node_path)
    )
    node_by_id = {_feature_id(feature): feature for feature in node_features}
    road_path = resolved_step_root / f"{STEP3_FRCSD_ROAD_STEM}.gpkg"
    road_features = runtime_state.frcsd_roads if runtime_state is not None else read_features(road_path)
    road_fields = (
        _runtime_fieldnames(road_features)
        if runtime_state is not None and not road_path.is_file()
        else _fieldnames_from_gpkg(road_path)
    )
    road_by_id = _road_features_by_id_from_features(road_features)
    swsd_roads = runtime_state.swsd_roads if runtime_state is not None else read_features(swsd_roads_path)
    node_patch_ids = _swsd_patch_ids_by_node(swsd_roads)
    surfaces = _load_surfaces(
        t07_surface_path=t07_surface_path,
        t03_surface_path=t03_surface_path,
        t04_surface_path=t04_surface_path,
        t05_surface_path=t05_surface_path,
    )
    t04_rejects = _load_t04_rejects(t04_audit_path)
    step2_junc_mappings = _load_step2_optional_junc_mappings(resolved_step_root)
    step2_dropped_junc_nodes = _load_step2_dropped_junc_nodes(resolved_step_root)
    topology_coverage_cache = topology_coverage_cache if topology_coverage_cache is not None else {}
    topology_audit_rows: list[dict[str, Any]] | None = None
    retained_sync_totals: dict[str, int] = {}

    audit_rows: list[dict[str, Any]] = []
    action_audit_rows: list[dict[str, Any]] = []
    closure_updates: list[str] = []
    relation_update_count = _apply_step2_plan_relation_node_map_updates(
        step_root=resolved_step_root,
        step2_junc_mappings=step2_junc_mappings,
        step2_dropped_junc_nodes=step2_dropped_junc_nodes,
        relation_rows=runtime_state.segment_relation_rows if runtime_state is not None else None,
    )
    if relation_update_count or not topology_path.is_file():
        topology_audit_rows, retained_sync_stats = _rebuild_topology_connectivity_audit(
            step_root=resolved_step_root,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
            coverage_cache=topology_coverage_cache,
            write_outputs=False,
            runtime_state=runtime_state,
            junction_only=True,
        )
        _add_retained_sync_stats(retained_sync_totals, retained_sync_stats)
    materialized_updates: list[str] = []
    surface_paths: dict[str, Path] = {}
    for _iteration in range(3):
        if runtime_state is not None:
            relation_by_segment = {
                _safe_id((row.get("properties") or {}).get("swsd_segment_id")): dict(row.get("properties") or {})
                for row in runtime_state.segment_relation_rows
                if _safe_id((row.get("properties") or {}).get("swsd_segment_id"))
            }
        else:
            relation_by_segment = _relation_props_by_segment(
                resolved_step_root / f"{STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM}.gpkg"
            )
        topology_audit = topology_audit_rows if topology_audit_rows is not None else gpd.read_file(topology_path)
        road_by_id = _road_features_by_id_from_features(road_features)
        pass_rows, pass_closure_updates, pass_relation_updates, pass_materialized_updates = _build_surface_audit_rows(
            topology_audit=topology_audit,
            node_by_id=node_by_id,
            node_features=node_features,
            road_features=road_features,
            node_patch_ids=node_patch_ids,
            surfaces=surfaces,
            t04_rejects=t04_rejects,
            step2_junc_mappings=step2_junc_mappings,
            road_by_id=road_by_id,
            relation_by_segment=relation_by_segment,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
            apply_closure=apply_closure,
        )
        action_audit_rows = _unique_surface_audit_rows(
            [
                *action_audit_rows,
                *[pass_row for pass_row in pass_rows if _is_surface_action_row(pass_row)],
            ]
        )
        audit_rows = [
            *action_audit_rows,
            *[pass_row for pass_row in pass_rows if not _is_surface_action_row(pass_row)],
        ]
        surface_paths = write_feature_triplet(
            step_root=resolved_step_root,
            stem=SURFACE_TOPOLOGY_AUDIT_STEM,
            features=audit_rows,
            fieldnames=SURFACE_TOPOLOGY_AUDIT_FIELDS,
        )
        pass_relation_update_count = 0
        if pass_relation_updates:
            pass_relation_update_count = _apply_relation_node_map_updates(
                step_root=resolved_step_root,
                updates=pass_relation_updates,
                relation_rows=runtime_state.segment_relation_rows if runtime_state is not None else None,
            )
        if not pass_closure_updates and not pass_relation_update_count and not pass_materialized_updates:
            break
        closure_updates = unique_preserve_order([*closure_updates, *pass_closure_updates])
        relation_update_count += pass_relation_update_count
        materialized_updates = unique_preserve_order([*materialized_updates, *pass_materialized_updates])
        write_feature_triplet(
            step_root=resolved_step_root,
            stem=STEP3_FRCSD_NODE_STEM,
            features=node_features,
            fieldnames=node_fields,
        )
        if pass_materialized_updates:
            write_feature_triplet(
                step_root=resolved_step_root,
                stem=STEP3_FRCSD_ROAD_STEM,
                features=road_features,
                fieldnames=road_fields,
            )
        topology_audit_rows, retained_sync_stats = _rebuild_topology_connectivity_audit(
            step_root=resolved_step_root,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
            coverage_cache=topology_coverage_cache,
            write_outputs=False,
            runtime_state=runtime_state,
        )
        _add_retained_sync_stats(retained_sync_totals, retained_sync_stats)
        if not pass_materialized_updates:
            break

    if topology_audit_rows is not None:
        _write_topology_connectivity_audit_rows(
            resolved_step_root,
            topology_audit_rows,
            retained_sync_totals,
        )

    summary = _surface_summary(audit_rows)
    summary.update(
        {
            "surface_topology_status": "passed" if summary["surface_topology_fail_count"] == 0 else "failed",
            "surface_topology_closure_updated_node_count": len(closure_updates),
            "surface_topology_closure_updated_nodes": closure_updates,
            "surface_topology_relation_node_map_update_count": relation_update_count,
            "surface_topology_selected_replacement_midroad_materialized_count": len(materialized_updates),
            "surface_topology_selected_replacement_midroad_materialized_nodes": materialized_updates,
            "surface_topology_audit_outputs": {key: str(path) for key, path in surface_paths.items()},
        }
    )
    summary_path = resolved_step_root / SURFACE_TOPOLOGY_SUMMARY
    write_json(summary_path, summary)
    _merge_step3_summary(resolved_step_root, summary, summary_path)
    return summary


def _runtime_fieldnames(features: list[dict[str, Any]]) -> list[str]:
    fieldnames: list[str] = []
    for feature_row in features:
        for field_name in (feature_row.get("properties") or {}):
            if field_name not in fieldnames:
                fieldnames.append(str(field_name))
    return fieldnames


def _add_retained_sync_stats(target: dict[str, int], stats: dict[str, Any]) -> None:
    for key, value in stats.items():
        target[key] = int(target.get(key, 0) or 0) + int(value or 0)
