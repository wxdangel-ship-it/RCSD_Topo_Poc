from __future__ import annotations

import json
import math
import tempfile
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t02_junction_anchor.fix_node_error_2 import run_t02_fix_node_error_2
from rcsd_topo_poc.modules.t08_preprocess.output_naming import ensure_tool_output_name
from rcsd_topo_poc.modules.t08_preprocess.nodes_type_aggregation import (
    _apply_complex_divmerge_aggregation,
    _elapsed_since,
    _empty_complex_summary,
    _first_non_empty_value,
    _items_per_second,
    _optional_field,
    _should_emit_progress,
)
from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    aggregate_bounds,
    ensure_gpkg_path,
    read_vector,
    resolve_field_name,
    unique_field_names,
    write_gpkg,
    write_json,
)


ProgressCallback = Callable[[str], None]
T_JUNCTION_KIND_2 = "2048"
T_PAIR_HORIZONTAL_ANGLE_DEGREES = 35.0
T_PAIR_OPPOSITE_PARALLEL_ANGLE_DEGREES = 20.0

INTERSECTION_ID_FIELDS = (
    "id",
    "intersection_id",
    "intersectionid",
    "fid",
    "objectid",
    "OBJECTID",
)
NODE_ERROR_2_REASON = "intersection_shared_by_multiple_groups"


@dataclass(frozen=True)
class _GeneratedNodeError2:
    features: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass(frozen=True)
class _SemanticGroup:
    group_id: str
    representative_node_id: str
    representative_output_index: int
    representative_kind_2: str | None
    representative_grade_2: str | None
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class _RoadRecord:
    feature_index: int
    road_id: str
    snodeid: str
    enodeid: str
    direction: int | None
    kind: str | None
    geometry: Any
    snode_outward_vector: tuple[float, float]
    enode_outward_vector: tuple[float, float]


@dataclass(frozen=True)
class _HorizontalCandidate:
    in_road_id: str
    out_road_id: str
    kind: str
    vector: tuple[float, float]
    angle_degrees: float


@dataclass(frozen=True)
class T08ComplexJunctionPreprocessArtifacts:
    nodes_output: Path
    roads_output: Path
    audit_nodes_output: Path
    summary_output: Path


from .complex_junction_pipeline import run_t08_complex_junction_preprocess



def _ensure_type_2_fields(
    *,
    node_features: list[dict[str, Any]],
    kind_field: str,
    grade_field: str,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> int:
    initialized = 0
    for index, feature in enumerate(node_features, start=1):
        props = feature["properties"]
        if "kind_2" not in props:
            props["kind_2"] = props.get(kind_field)
            initialized += 1
        if "grade_2" not in props:
            props["grade_2"] = props.get(grade_field)
            initialized += 1
        if _should_emit_progress(index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool5] prepared {index} node feature(s)")
    return initialized


def _build_node_error2_from_intersections(
    *,
    node_features: list[dict[str, Any]],
    intersection_path: Path,
    node_id_field: str,
    intersection_layer: str | None,
    intersection_crs_text: str | None,
    target_epsg: int,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> _GeneratedNodeError2:
    _emit_progress(progress_callback, f"[T08 Tool5] node_error_2: reading intersections={intersection_path}")
    intersection_result = read_vector(
        intersection_path,
        layer_name=intersection_layer,
        default_crs_text=intersection_crs_text,
        target_epsg=target_epsg,
    )
    if not intersection_result.features:
        return _GeneratedNodeError2(
            features=[],
            summary=_empty_node_error2_detection_summary(
                status="skipped",
                skip_reason="intersection_input_empty",
                intersection_source_crs=None,
                intersection_crs_source=None,
            ),
        )

    groups_by_id = _semantic_groups_for_node_error2(node_features, node_id_field=node_id_field)
    node_tree_records = [
        (feature["geometry"], _semantic_group_id(feature["properties"], node_id_field))
        for feature in node_features
        if feature.get("geometry") is not None
        and not feature["geometry"].is_empty
        and _semantic_group_id(feature["properties"], node_id_field) in groups_by_id
    ]
    if not node_tree_records:
        return _GeneratedNodeError2(
            features=[],
            summary=_empty_node_error2_detection_summary(
                status="skipped",
                skip_reason="no_semantic_nodes",
                intersection_feature_count=len(intersection_result.features),
                intersection_source_crs=intersection_result.source_crs.to_string(),
                intersection_crs_source=intersection_result.crs_source,
            ),
        )

    node_geometries = [record[0] for record in node_tree_records]
    node_group_ids = [str(record[1]) for record in node_tree_records]
    node_tree = STRtree(node_geometries)
    group_to_intersection_ids: dict[str, set[str]] = {}
    rows: list[dict[str, Any]] = []
    _emit_progress(
        progress_callback,
        (
            f"[T08 Tool5] node_error_2: loaded intersections={len(intersection_result.features)} "
            f"semantic_groups={len(groups_by_id)} indexed_nodes={len(node_tree_records)}"
        ),
    )

    for intersection_index, intersection in enumerate(intersection_result.features):
        intersection_id = _intersection_identity(intersection.properties, intersection_index)
        if intersection.geometry is None or intersection.geometry.is_empty:
            rows.append(
                {
                    "intersection_id": intersection_id,
                    "candidate_group_ids": [],
                    "candidate_group_count": 0,
                    "ignored_kind1_group_ids": [],
                    "remaining_group_ids": [],
                    "remaining_group_count": 0,
                    "status": "skipped",
                    "skip_reason": "empty_intersection_geometry",
                }
            )
            continue

        candidate_indexes = node_tree.query(intersection.geometry, predicate="intersects")
        candidate_group_ids = sorted({node_group_ids[int(index)] for index in candidate_indexes}, key=_sort_key)
        groups_with_representative = [
            group_id for group_id in candidate_group_ids if groups_by_id[group_id]["representative_node_id"] is not None
        ]
        unresolved_group_ids = [
            group_id for group_id in candidate_group_ids if groups_by_id[group_id]["representative_node_id"] is None
        ]
        ignored_kind1_group_ids = [
            group_id
            for group_id in groups_with_representative
            if _normalize_id(groups_by_id[group_id]["representative_kind_2"]) == "1"
        ]
        remaining_group_ids = [
            group_id
            for group_id in groups_with_representative
            if _normalize_id(groups_by_id[group_id]["representative_kind_2"]) != "1"
        ]
        row: dict[str, Any] = {
            "intersection_id": intersection_id,
            "candidate_group_ids": candidate_group_ids,
            "candidate_group_count": len(candidate_group_ids),
            "unresolved_group_ids": unresolved_group_ids,
            "ignored_kind1_group_ids": ignored_kind1_group_ids,
            "ignored_kind1_group_count": len(ignored_kind1_group_ids),
            "remaining_group_ids": remaining_group_ids,
            "remaining_group_count": len(remaining_group_ids),
            "status": "skipped",
            "skip_reason": None,
        }
        if len(candidate_group_ids) <= 1:
            row["skip_reason"] = "single_group_in_intersection"
        elif len(remaining_group_ids) <= 1:
            row["skip_reason"] = "single_group_after_kind1_filter"
        else:
            row["status"] = "generated"
            row["skip_reason"] = None
            for group_id in remaining_group_ids:
                group_to_intersection_ids.setdefault(group_id, set()).add(intersection_id)
        rows.append(row)
        if _should_emit_progress(intersection_index + 1, progress_interval):
            _emit_progress(
                progress_callback,
                f"[T08 Tool5] node_error_2: checked {intersection_index + 1} intersection feature(s)",
            )

    generated_features: list[dict[str, Any]] = []
    for group_id in sorted(group_to_intersection_ids, key=_sort_key):
        intersection_ids = sorted(group_to_intersection_ids[group_id], key=_sort_key)
        group = groups_by_id[group_id]
        for feature in group["features"]:
            props = dict(feature["properties"])
            node_id = _normalize_id(props.get(node_id_field))
            if node_id is None:
                continue
            props.update(
                {
                    "id": node_id,
                    "junction_id": group_id,
                    "error_type": "node_error_2",
                    "error_reason": NODE_ERROR_2_REASON,
                    "intersection_ids": ",".join(intersection_ids),
                    "intersection_count": len(intersection_ids),
                }
            )
            generated_features.append({"properties": props, "geometry": feature["geometry"]})

    summary = {
        "status": "generated" if generated_features else "skipped",
        "skip_reason": None if generated_features else "generated_node_error_2_empty",
        "node_error2_source": "generated_from_intersection",
        "target_epsg": target_epsg,
        "input_crs": {
            "intersection": intersection_result.source_crs.to_string(),
            "intersection_crs_source": intersection_result.crs_source,
        },
        "counts": {
            "intersection_feature_count": len(intersection_result.features),
            "candidate_intersection_count": sum(1 for row in rows if row["candidate_group_count"] > 1),
            "generated_intersection_count": sum(1 for row in rows if row["status"] == "generated"),
            "generated_group_count": len(group_to_intersection_ids),
            "generated_feature_count": len(generated_features),
        },
        "rows": rows,
    }
    _emit_progress(
        progress_callback,
        (
            f"[T08 Tool5] node_error_2: generated_groups={len(group_to_intersection_ids)} "
            f"generated_features={len(generated_features)}"
        ),
    )
    return _GeneratedNodeError2(features=generated_features, summary=summary)


def _semantic_groups_for_node_error2(
    node_features: list[dict[str, Any]],
    *,
    node_id_field: str,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for output_index, feature in enumerate(node_features):
        props = feature["properties"]
        node_id = _normalize_id(props.get(node_id_field))
        group_id = _semantic_group_id(props, node_id_field)
        if node_id is None or group_id is None:
            continue
        group = groups.setdefault(
            group_id,
            {
                "features": [],
                "node_ids": [],
                "representative_node_id": None,
                "representative_kind_2": None,
                "representative_output_index": None,
            },
        )
        group["features"].append(feature)
        group["node_ids"].append(node_id)
        if node_id == group_id:
            group["representative_node_id"] = node_id
            group["representative_kind_2"] = _normalize_id(props.get("kind_2"))
            group["representative_output_index"] = output_index
    return groups


def _empty_node_error2_detection_summary(
    *,
    status: str,
    skip_reason: str | None,
    node_error2_source: str = "generated_from_intersection",
    intersection_feature_count: int = 0,
    intersection_source_crs: str | None = None,
    intersection_crs_source: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "skip_reason": skip_reason,
        "node_error2_source": node_error2_source,
        "input_crs": {
            "intersection": intersection_source_crs,
            "intersection_crs_source": intersection_crs_source,
        },
        "counts": {
            "intersection_feature_count": intersection_feature_count,
            "candidate_intersection_count": 0,
            "generated_intersection_count": 0,
            "generated_group_count": 0,
            "generated_feature_count": 0,
        },
        "rows": [],
    }


def _apply_t_pair_one_to_many_fallback(
    *,
    final_node_features: list[dict[str, Any]],
    final_road_features: list[dict[str, Any]],
    one_to_many_summary: dict[str, Any],
    intersection_path: Path,
    intersection_layer: str | None,
    intersection_crs_text: str | None,
    target_epsg: int,
    node_id_field: str,
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    road_direction_field: str | None,
    road_kind_field: str | None,
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    rows = one_to_many_summary.get("rows") or []
    fallback_rows = [
        row
        for row in rows
        if row.get("status") == "skipped" and row.get("skip_reason") == "not_all_groups_connected"
    ]
    summary: dict[str, Any] = {
        "status": "skipped",
        "skip_reason": None,
        "candidate_row_count": len(fallback_rows),
        "merged_intersection_count": 0,
        "deleted_road_count": 0,
        "horizontal_angle_degrees": T_PAIR_HORIZONTAL_ANGLE_DEGREES,
        "opposite_parallel_angle_degrees": T_PAIR_OPPOSITE_PARALLEL_ANGLE_DEGREES,
        "rows": [],
    }
    if not fallback_rows:
        summary["skip_reason"] = "no_not_all_groups_connected_rows"
        return summary
    if road_direction_field is None:
        summary["skip_reason"] = "road_direction_field_missing"
        return summary
    if road_kind_field is None:
        summary["skip_reason"] = "road_kind_field_missing"
        return summary

    _emit_progress(progress_callback, f"[T08 Tool5] one_to_many: t_pair fallback rows={len(fallback_rows)}")
    intersection_geometries = _read_intersection_geometries_by_id(
        intersection_path=intersection_path,
        intersection_layer=intersection_layer,
        intersection_crs_text=intersection_crs_text,
        target_epsg=target_epsg,
    )
    consumed_group_ids = {
        str(group_id)
        for row in rows
        if row.get("status") == "merged"
        for group_id in (row.get("merged_group_ids") or [])
    }

    for row in rows:
        if row.get("status") != "skipped" or row.get("skip_reason") != "not_all_groups_connected":
            continue
        row_audit: dict[str, Any] = {
            "intersection_id": row.get("intersection_id"),
            "remaining_group_ids": list(row.get("remaining_group_ids") or []),
            "status": "skipped",
            "skip_reason": None,
            "virtual_connections": [],
            "reached_group_ids": [],
        }
        remaining_group_ids = [
            group_id
            for group_id in (_normalize_id(value) for value in (row.get("remaining_group_ids") or []))
            if group_id is not None
        ]
        if len(remaining_group_ids) <= 1:
            row_audit["skip_reason"] = "single_remaining_group"
            summary["rows"].append(row_audit)
            continue
        if any(group_id in consumed_group_ids for group_id in remaining_group_ids):
            row_audit["skip_reason"] = "group_already_merged"
            summary["rows"].append(row_audit)
            continue

        groups = _semantic_groups_from_features(final_node_features, node_id_field=node_id_field)
        missing_groups = [group_id for group_id in remaining_group_ids if group_id not in groups]
        if missing_groups:
            row_audit["skip_reason"] = "group_resolution_failed"
            row_audit["missing_group_ids"] = missing_groups
            summary["rows"].append(row_audit)
            continue

        intersection_id = str(row.get("intersection_id") or "")
        intersection_geometry = intersection_geometries.get(intersection_id)
        if intersection_geometry is None:
            row_audit["skip_reason"] = "intersection_geometry_not_found"
            summary["rows"].append(row_audit)
            continue

        node_to_group = _node_to_group_id(final_node_features, node_id_field=node_id_field)
        node_points = _node_points_by_id(final_node_features, node_id_field=node_id_field)
        road_records = _road_records_for_one_to_many(
            final_road_features=final_road_features,
            road_id_field=road_id_field,
            road_snode_field=road_snode_field,
            road_enode_field=road_enode_field,
            road_direction_field=road_direction_field,
            road_kind_field=road_kind_field,
            node_points=node_points,
        )
        connectivity = _evaluate_t_pair_virtual_connectivity(
            remaining_group_ids=remaining_group_ids,
            groups=groups,
            node_to_group=node_to_group,
            road_records=road_records,
        )
        row_audit["virtual_connections"] = connectivity["virtual_connections"]
        row_audit["reached_group_ids"] = connectivity["reached_group_ids"]
        row["tool5_t_pair_virtual_connections"] = connectivity["virtual_connections"]
        row["tool5_t_pair_reached_group_ids"] = connectivity["reached_group_ids"]
        if set(connectivity["reached_group_ids"]) != set(remaining_group_ids):
            row_audit["skip_reason"] = "not_connected_after_t_pair_rule"
            summary["rows"].append(row_audit)
            continue

        deleted_road_ids = _apply_one_to_many_merge_in_place(
            row=row,
            final_node_features=final_node_features,
            final_road_features=final_road_features,
            groups=[groups[group_id] for group_id in remaining_group_ids],
            node_id_field=node_id_field,
            road_id_field=road_id_field,
            road_snode_field=road_snode_field,
            road_enode_field=road_enode_field,
            intersection_geometry=intersection_geometry,
        )
        for group_id in remaining_group_ids:
            consumed_group_ids.add(group_id)
        row["previous_skip_reason"] = "not_all_groups_connected"
        row["repair_rule"] = "tool5_t_pair_virtual_connectivity"
        row["skip_reason"] = None
        row_audit["status"] = "merged"
        row_audit["skip_reason"] = None
        row_audit["deleted_road_ids"] = deleted_road_ids
        summary["merged_intersection_count"] += 1
        summary["deleted_road_count"] += len(deleted_road_ids)
        summary["rows"].append(row_audit)

    _refresh_one_to_many_counts(one_to_many_summary)
    summary["status"] = "applied" if summary["merged_intersection_count"] else "skipped"
    if summary["status"] == "skipped" and summary["skip_reason"] is None:
        summary["skip_reason"] = "no_rows_matched_t_pair_rule"
    return summary


def _read_intersection_geometries_by_id(
    *,
    intersection_path: Path,
    intersection_layer: str | None,
    intersection_crs_text: str | None,
    target_epsg: int,
) -> dict[str, Any]:
    result = read_vector(
        intersection_path,
        layer_name=intersection_layer,
        default_crs_text=intersection_crs_text,
        target_epsg=target_epsg,
    )
    by_id: dict[str, Any] = {}
    for feature_index, feature in enumerate(result.features):
        if feature.geometry is None or feature.geometry.is_empty:
            continue
        identity = _intersection_identity(feature.properties, feature_index)
        by_id[identity] = feature.geometry
    return by_id


def _semantic_groups_from_features(
    final_node_features: list[dict[str, Any]],
    *,
    node_id_field: str,
) -> dict[str, _SemanticGroup]:
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for output_index, feature in enumerate(final_node_features):
        props = feature["properties"]
        node_id = _normalize_id(props.get(node_id_field))
        group_id = _semantic_group_id(props, node_id_field)
        if node_id is None or group_id is None:
            continue
        grouped[group_id].append((output_index, feature))

    groups: dict[str, _SemanticGroup] = {}
    for group_id, indexed_features in grouped.items():
        representative: tuple[int, dict[str, Any]] | None = None
        for output_index, feature in indexed_features:
            if _normalize_id(feature["properties"].get(node_id_field)) == group_id:
                representative = (output_index, feature)
                break
        if representative is None:
            continue
        representative_index, representative_feature = representative
        representative_props = representative_feature["properties"]
        representative_node_id = _normalize_id(representative_props.get(node_id_field))
        if representative_node_id is None:
            continue
        node_ids = tuple(
            sorted(
                (
                    node_id
                    for _, feature in indexed_features
                    if (node_id := _normalize_id(feature["properties"].get(node_id_field))) is not None
                ),
                key=_sort_key,
            )
        )
        groups[group_id] = _SemanticGroup(
            group_id=group_id,
            representative_node_id=representative_node_id,
            representative_output_index=representative_index,
            representative_kind_2=_normalize_id(representative_props.get("kind_2")),
            representative_grade_2=_normalize_id(representative_props.get("grade_2")),
            node_ids=node_ids,
        )
    return groups


def _node_to_group_id(final_node_features: list[dict[str, Any]], *, node_id_field: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for feature in final_node_features:
        props = feature["properties"]
        node_id = _normalize_id(props.get(node_id_field))
        group_id = _semantic_group_id(props, node_id_field)
        if node_id is not None and group_id is not None:
            mapping[node_id] = group_id
    return mapping


def _node_points_by_id(final_node_features: list[dict[str, Any]], *, node_id_field: str) -> dict[str, Any]:
    points: dict[str, Any] = {}
    for feature in final_node_features:
        node_id = _normalize_id(feature["properties"].get(node_id_field))
        geometry = feature.get("geometry")
        if node_id is not None and geometry is not None and not geometry.is_empty:
            points[node_id] = geometry.centroid
    return points


def _road_records_for_one_to_many(
    *,
    final_road_features: list[dict[str, Any]],
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    road_direction_field: str,
    road_kind_field: str,
    node_points: dict[str, Any],
) -> list[_RoadRecord]:
    records: list[_RoadRecord] = []
    for feature_index, feature in enumerate(final_road_features):
        props = feature["properties"]
        road_id = _normalize_id(props.get(road_id_field))
        snodeid = _normalize_id(props.get(road_snode_field))
        enodeid = _normalize_id(props.get(road_enode_field))
        geometry = feature.get("geometry")
        if road_id is None or snodeid is None or enodeid is None or geometry is None or geometry.is_empty:
            continue
        snode_outward, enode_outward = _road_endpoint_outward_vectors(
            geometry,
            snode_point=node_points.get(snodeid),
            enode_point=node_points.get(enodeid),
            distance_m=20.0,
        )
        records.append(
            _RoadRecord(
                feature_index=feature_index,
                road_id=road_id,
                snodeid=snodeid,
                enodeid=enodeid,
                direction=_coerce_optional_int(props.get(road_direction_field)),
                kind=_normalize_kind_value(props.get(road_kind_field)),
                geometry=geometry,
                snode_outward_vector=snode_outward,
                enode_outward_vector=enode_outward,
            )
        )
    return records


def _evaluate_t_pair_virtual_connectivity(
    *,
    remaining_group_ids: list[str],
    groups: dict[str, _SemanticGroup],
    node_to_group: dict[str, str],
    road_records: list[_RoadRecord],
) -> dict[str, Any]:
    remaining_set = set(remaining_group_ids)
    node_adjacency: dict[str, set[str]] = defaultdict(set)
    degree_by_node_id: Counter[str] = Counter()
    for road in road_records:
        node_adjacency[road.snodeid].add(road.enodeid)
        node_adjacency[road.enodeid].add(road.snodeid)
        degree_by_node_id[road.snodeid] += 1
        degree_by_node_id[road.enodeid] += 1

    virtual_adjacency: dict[str, set[str]] = defaultdict(set)
    virtual_connections: list[dict[str, Any]] = []
    for left_index, left_group_id in enumerate(remaining_group_ids):
        for right_group_id in remaining_group_ids[left_index + 1 :]:
            match = _match_t_pair_horizontal_rule(
                left_group=groups[left_group_id],
                right_group=groups[right_group_id],
                node_to_group=node_to_group,
                road_records=road_records,
            )
            if match is None:
                continue
            virtual_adjacency[left_group_id].add(right_group_id)
            virtual_adjacency[right_group_id].add(left_group_id)
            virtual_connections.append(match)

    blocked_node_ids = {
        node_id
        for node_id, group_id in node_to_group.items()
        if group_id not in remaining_set
        and groups.get(group_id) is not None
        and groups[group_id].representative_kind_2 not in {None, "0"}
        and degree_by_node_id.get(node_id, 0) != 2
    }
    seed_group_id = sorted(remaining_group_ids, key=_sort_key)[0]
    reached_group_ids: set[str] = {seed_group_id}
    visited_node_ids: set[str] = set()
    queue: deque[str] = deque()

    def enqueue_group(group_id: str) -> None:
        for node_id in groups[group_id].node_ids:
            if node_id not in visited_node_ids:
                visited_node_ids.add(node_id)
                queue.append(node_id)

    def visit_virtual_neighbors(group_id: str) -> None:
        for neighbor_group_id in sorted(virtual_adjacency.get(group_id, ()), key=_sort_key):
            if neighbor_group_id in reached_group_ids:
                continue
            reached_group_ids.add(neighbor_group_id)
            enqueue_group(neighbor_group_id)

    enqueue_group(seed_group_id)
    visit_virtual_neighbors(seed_group_id)
    while queue:
        current_node_id = queue.popleft()
        current_group_id = node_to_group.get(current_node_id)
        if current_group_id in remaining_set:
            reached_group_ids.add(current_group_id)
            visit_virtual_neighbors(current_group_id)
        for next_node_id in sorted(node_adjacency.get(current_node_id, ()), key=_sort_key):
            if next_node_id in visited_node_ids or next_node_id in blocked_node_ids:
                continue
            visited_node_ids.add(next_node_id)
            queue.append(next_node_id)
            next_group_id = node_to_group.get(next_node_id)
            if next_group_id in remaining_set:
                reached_group_ids.add(next_group_id)
                visit_virtual_neighbors(next_group_id)

    return {
        "reached_group_ids": sorted(reached_group_ids, key=_sort_key),
        "virtual_connections": virtual_connections,
    }


def _match_t_pair_horizontal_rule(
    *,
    left_group: _SemanticGroup,
    right_group: _SemanticGroup,
    node_to_group: dict[str, str],
    road_records: list[_RoadRecord],
) -> dict[str, Any] | None:
    if left_group.representative_kind_2 != T_JUNCTION_KIND_2 or right_group.representative_kind_2 != T_JUNCTION_KIND_2:
        return None
    left_candidates = _t_horizontal_candidates(left_group, node_to_group=node_to_group, road_records=road_records)
    right_candidates = _t_horizontal_candidates(right_group, node_to_group=node_to_group, road_records=road_records)
    matches: list[dict[str, Any]] = []
    for left in left_candidates:
        for right in right_candidates:
            if left.kind != right.kind:
                continue
            opposite_angle = _angle_degrees(left.vector, (-right.vector[0], -right.vector[1]))
            if opposite_angle > T_PAIR_OPPOSITE_PARALLEL_ANGLE_DEGREES:
                continue
            matches.append(
                {
                    "left_group_id": left_group.group_id,
                    "right_group_id": right_group.group_id,
                    "kind": left.kind,
                    "left_horizontal_in_road_id": left.in_road_id,
                    "left_horizontal_out_road_id": left.out_road_id,
                    "right_horizontal_in_road_id": right.in_road_id,
                    "right_horizontal_out_road_id": right.out_road_id,
                    "left_horizontal_angle_degrees": round(float(left.angle_degrees), 3),
                    "right_horizontal_angle_degrees": round(float(right.angle_degrees), 3),
                    "opposite_parallel_angle_degrees": round(float(opposite_angle), 3),
                    "reason": "t_pair_same_kind_opposite_parallel_horizontal_roads",
                }
            )
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda item: (
            item["opposite_parallel_angle_degrees"],
            item["left_horizontal_angle_degrees"],
            item["right_horizontal_angle_degrees"],
            _sort_key(item["left_group_id"]),
            _sort_key(item["right_group_id"]),
        ),
    )[0]


def _t_horizontal_candidates(
    group: _SemanticGroup,
    *,
    node_to_group: dict[str, str],
    road_records: list[_RoadRecord],
) -> list[_HorizontalCandidate]:
    in_legs: list[dict[str, Any]] = []
    out_legs: list[dict[str, Any]] = []
    for road in road_records:
        leg = _incident_leg_for_group(road, group_id=group.group_id, node_to_group=node_to_group)
        if leg is None or leg["kind"] is None:
            continue
        if leg["has_in"] and not leg["has_out"]:
            in_legs.append(leg)
        if leg["has_out"] and not leg["has_in"]:
            out_legs.append(leg)

    candidates: list[_HorizontalCandidate] = []
    for in_leg in in_legs:
        for out_leg in out_legs:
            if in_leg["road_id"] == out_leg["road_id"] or in_leg["kind"] != out_leg["kind"]:
                continue
            angle = _angle_degrees(in_leg["travel_vector"], out_leg["travel_vector"])
            if angle > T_PAIR_HORIZONTAL_ANGLE_DEGREES:
                continue
            vector = _unit_vector(
                (
                    in_leg["travel_vector"][0] + out_leg["travel_vector"][0],
                    in_leg["travel_vector"][1] + out_leg["travel_vector"][1],
                )
            )
            candidates.append(
                _HorizontalCandidate(
                    in_road_id=str(in_leg["road_id"]),
                    out_road_id=str(out_leg["road_id"]),
                    kind=str(in_leg["kind"]),
                    vector=vector,
                    angle_degrees=float(angle),
                )
            )
    return sorted(candidates, key=lambda item: (item.angle_degrees, _sort_key(item.in_road_id), _sort_key(item.out_road_id)))


def _incident_leg_for_group(
    road: _RoadRecord,
    *,
    group_id: str,
    node_to_group: dict[str, str],
) -> dict[str, Any] | None:
    at_snode = node_to_group.get(road.snodeid) == group_id
    at_enode = node_to_group.get(road.enodeid) == group_id
    if at_snode == at_enode:
        return None
    outward_vector = road.snode_outward_vector if at_snode else road.enode_outward_vector
    has_in, has_out = _road_direction_flags_at_endpoint(road.direction, at_snode=at_snode)
    if not has_in and not has_out:
        return None
    if has_in and not has_out:
        travel_vector = (-outward_vector[0], -outward_vector[1])
    else:
        travel_vector = outward_vector
    return {
        "road_id": road.road_id,
        "kind": road.kind,
        "has_in": has_in,
        "has_out": has_out,
        "travel_vector": _unit_vector(travel_vector),
    }


def _road_direction_flags_at_endpoint(direction: int | None, *, at_snode: bool) -> tuple[bool, bool]:
    if direction in {0, 1}:
        return True, True
    if direction == 2:
        return (False, True) if at_snode else (True, False)
    if direction == 3:
        return (True, False) if at_snode else (False, True)
    return False, False


def _apply_one_to_many_merge_in_place(
    *,
    row: dict[str, Any],
    final_node_features: list[dict[str, Any]],
    final_road_features: list[dict[str, Any]],
    groups: list[_SemanticGroup],
    node_id_field: str,
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    intersection_geometry: Any,
) -> list[str]:
    chosen_group = sorted(groups, key=lambda group: (_sort_key(group.group_id), _sort_key(group.representative_node_id)))[0]
    chosen_mainnodeid = chosen_group.group_id
    merged_node_ids = sorted({node_id for group in groups for node_id in group.node_ids}, key=_sort_key)
    subnode_ids = [node_id for node_id in merged_node_ids if node_id != chosen_group.representative_node_id]
    new_grade = _grade_for_t_pair_merge(groups, chosen_group=chosen_group)

    chosen_props = final_node_features[chosen_group.representative_output_index]["properties"]
    chosen_props["mainnodeid"] = chosen_mainnodeid
    chosen_props["kind_2"] = 4
    chosen_props["grade_2"] = new_grade
    chosen_props["subnodeid"] = ",".join(subnode_ids) if subnode_ids else None

    node_output_index_by_id = {
        node_id: output_index
        for output_index, feature in enumerate(final_node_features)
        if (node_id := _normalize_id(feature["properties"].get(node_id_field))) is not None
    }
    for node_id in subnode_ids:
        output_index = node_output_index_by_id[node_id]
        props = final_node_features[output_index]["properties"]
        props["mainnodeid"] = chosen_mainnodeid
        props["kind_2"] = 0
        props["grade_2"] = 0
        props["subnodeid"] = None

    merged_node_id_set = set(merged_node_ids)
    deleted_road_ids: list[str] = []
    kept_road_features: list[dict[str, Any]] = []
    for road_feature in final_road_features:
        props = road_feature["properties"]
        road_id = _normalize_id(props.get(road_id_field))
        snodeid = _normalize_id(props.get(road_snode_field))
        enodeid = _normalize_id(props.get(road_enode_field))
        geometry = road_feature.get("geometry")
        should_delete = (
            road_id is not None
            and snodeid in merged_node_id_set
            and enodeid in merged_node_id_set
            and geometry is not None
            and not geometry.is_empty
            and intersection_geometry.covers(geometry)
        )
        if should_delete:
            deleted_road_ids.append(road_id)
        else:
            kept_road_features.append(road_feature)
    final_road_features[:] = kept_road_features

    row["status"] = "merged"
    row["merged_group_ids"] = sorted((group.group_id for group in groups), key=_sort_key)
    row["merged_group_count"] = len(groups)
    row["chosen_mainnodeid"] = chosen_mainnodeid
    row["merged_node_ids"] = merged_node_ids
    row["deleted_road_ids"] = sorted(set(deleted_road_ids), key=_sort_key)
    return row["deleted_road_ids"]


def _grade_for_t_pair_merge(groups: list[_SemanticGroup], *, chosen_group: _SemanticGroup) -> Any:
    grades = [group.representative_grade_2 for group in groups]
    if "1" in grades:
        return 1
    if "2" in grades:
        return 2
    value = chosen_group.representative_grade_2
    return int(value) if value is not None and value.isdigit() else value


def _refresh_one_to_many_counts(one_to_many_summary: dict[str, Any]) -> None:
    rows = one_to_many_summary.get("rows") or []
    counts = one_to_many_summary.setdefault("counts", {})
    counts["merged_intersection_count"] = sum(1 for row in rows if row.get("status") == "merged")
    counts["skipped_intersection_count"] = sum(1 for row in rows if row.get("status") != "merged")
    deleted_road_ids = {
        str(road_id)
        for row in rows
        for road_id in (row.get("deleted_road_ids") or [])
        if road_id is not None
    }
    counts["deleted_road_count"] = len(deleted_road_ids)


def _intersection_identity(properties: dict[str, Any], feature_index: int) -> str:
    for field in INTERSECTION_ID_FIELDS:
        value = _normalize_id(properties.get(field))
        if value is not None:
            return f"{field}:{value}"
    return f"feature_index:{feature_index}"


def _semantic_group_id(properties: dict[str, Any], node_id_field: str) -> str | None:
    return _normalize_id(properties.get("mainnodeid")) or _normalize_id(properties.get(node_id_field))


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none", "nan"}:
            return None
        return text
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _sort_key(value: Any) -> tuple[int, Any]:
    normalized = _normalize_id(value)
    if normalized is None:
        return (2, "")
    if normalized.isdigit():
        return (0, int(normalized))
    try:
        return (0, int(float(normalized)))
    except Exception:
        return (1, normalized)


def _coerce_optional_int(value: Any) -> int | None:
    normalized = _normalize_id(value)
    if normalized is None:
        return None
    try:
        parsed = float(normalized)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else None


def _normalize_kind_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in {"null", "none", "nan"}:
        return None
    tokens = [token.strip() for token in text.split("|") if token.strip()]
    return "|".join(sorted(set(tokens))) if tokens else None


def _road_endpoint_outward_vectors(
    geometry: Any,
    *,
    snode_point: Any | None,
    enode_point: Any | None,
    distance_m: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    coords = _line_coords(geometry)
    if len(coords) < 2:
        return (1.0, 0.0), (-1.0, 0.0)
    start_outward = _line_endpoint_outward_vector(geometry, at_start=True, distance_m=distance_m)
    end_outward = _line_endpoint_outward_vector(geometry, at_start=False, distance_m=distance_m)
    snode_at_start = _point_closer_to_start(snode_point, coords, default=True)
    enode_at_start = _point_closer_to_start(enode_point, coords, default=False)
    if snode_at_start == enode_at_start:
        snode_at_start = _prefer_snode_at_start(snode_point=snode_point, enode_point=enode_point, coords=coords)
        enode_at_start = not snode_at_start
    return (
        start_outward if snode_at_start else end_outward,
        start_outward if enode_at_start else end_outward,
    )


def _point_closer_to_start(point: Any | None, coords: list[tuple[float, float]], *, default: bool) -> bool:
    if point is None or len(coords) < 2:
        return default
    start = coords[0]
    end = coords[-1]
    start_distance = math.hypot(float(point.x) - float(start[0]), float(point.y) - float(start[1]))
    end_distance = math.hypot(float(point.x) - float(end[0]), float(point.y) - float(end[1]))
    return start_distance <= end_distance


def _prefer_snode_at_start(
    *,
    snode_point: Any | None,
    enode_point: Any | None,
    coords: list[tuple[float, float]],
) -> bool:
    if snode_point is None or enode_point is None or len(coords) < 2:
        return True
    start = coords[0]
    end = coords[-1]
    direct_distance = math.hypot(float(snode_point.x) - float(start[0]), float(snode_point.y) - float(start[1])) + math.hypot(
        float(enode_point.x) - float(end[0]), float(enode_point.y) - float(end[1])
    )
    reverse_distance = math.hypot(float(snode_point.x) - float(end[0]), float(snode_point.y) - float(end[1])) + math.hypot(
        float(enode_point.x) - float(start[0]), float(enode_point.y) - float(start[1])
    )
    return direct_distance <= reverse_distance


def _line_endpoint_outward_vector(geometry: Any, *, at_start: bool, distance_m: float) -> tuple[float, float]:
    coords = _line_coords(geometry)
    if len(coords) < 2:
        return (1.0, 0.0)
    try:
        length = float(geometry.length)
        distance = min(max(float(distance_m), 0.0), length)
        if length > 0.0 and distance > 0.0:
            if at_start:
                origin = coords[0]
                target = geometry.interpolate(distance)
            else:
                origin = coords[-1]
                target = geometry.interpolate(max(length - distance, 0.0))
            return _unit_vector((float(target.x) - float(origin[0]), float(target.y) - float(origin[1])))
    except Exception:
        pass
    if at_start:
        start = coords[0]
        nxt = coords[1]
        return _unit_vector((float(nxt[0]) - float(start[0]), float(nxt[1]) - float(start[1])))
    end = coords[-1]
    prev = coords[-2]
    return _unit_vector((float(prev[0]) - float(end[0]), float(prev[1]) - float(end[1])))


def _line_coords(geometry: Any) -> list[tuple[float, float]]:
    try:
        return [(float(coord[0]), float(coord[1])) for coord in geometry.coords]
    except Exception:
        parts = getattr(geometry, "geoms", None)
        if parts:
            return _line_coords(max(parts, key=lambda part: float(getattr(part, "length", 0.0))))
    return []


def _angle_degrees(a: tuple[float, float], b: tuple[float, float]) -> float:
    au = _unit_vector(a)
    bu = _unit_vector(b)
    dot = max(-1.0, min(1.0, au[0] * bu[0] + au[1] * bu[1]))
    return abs(math.degrees(math.acos(dot)))


def _unit_vector(vector: Iterable[float]) -> tuple[float, float]:
    values = list(vector)
    if len(values) < 2:
        return (1.0, 0.0)
    dx = float(values[0])
    dy = float(values[1])
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return (1.0, 0.0)
    return dx / length, dy / length


def _build_audit_node_features(
    *,
    final_node_features: list[dict[str, Any]],
    node_id_field: str,
    complex_summary: dict[str, Any],
    one_to_many_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    node_by_id = {
        normalized_id: feature
        for feature in final_node_features
        if (normalized_id := _normalize_id(feature["properties"].get(node_id_field))) is not None
    }
    audit_rows: list[dict[str, str | None]] = []
    for row in complex_summary.get("rows", []):
        if row.get("status") != "aggregated":
            continue
        group_id = str(row.get("component_id") or "")
        mainnodeid = str(row.get("mainnodeid") or "")
        for node_id in row.get("node_ids") or []:
            source_node_id = str(node_id)
            audit_rows.append(
                {
                    "process": "complex_divmerge",
                    "group_id": group_id,
                    "source_node_id": source_node_id,
                    "mainnodeid": mainnodeid,
                    "role": "main" if source_node_id == mainnodeid else "member",
                }
            )
    for row in one_to_many_summary.get("rows", []):
        if row.get("status") != "merged":
            continue
        group_id = str(row.get("intersection_id") or "")
        mainnodeid = str(row.get("chosen_mainnodeid") or "")
        for node_id in row.get("merged_node_ids") or []:
            source_node_id = str(node_id)
            audit_rows.append(
                {
                    "process": "one_to_many",
                    "group_id": group_id,
                    "source_node_id": source_node_id,
                    "mainnodeid": mainnodeid,
                    "role": "main" if source_node_id == mainnodeid else "member",
                }
            )

    audit_features: list[dict[str, Any]] = []
    seen_audit_ids: set[str] = set()
    for row in audit_rows:
        source_node_id = _normalize_id(row["source_node_id"]) or str(row["source_node_id"])
        source_feature = node_by_id.get(source_node_id)
        if source_feature is None:
            continue
        audit_id = f"{row['process']}:{row['group_id']}:{source_node_id}"
        if audit_id in seen_audit_ids:
            continue
        seen_audit_ids.add(audit_id)
        properties = dict(source_feature["properties"])
        properties.update(
            {
                "audit_id": audit_id,
                "audit_process": row["process"],
                "audit_group_id": row["group_id"],
                "audit_role": row["role"],
                "audit_mainnodeid": row["mainnodeid"],
                "audit_source_node_id": source_node_id,
            }
        )
        audit_features.append({"properties": properties, "geometry": source_feature["geometry"]})
    return audit_features


def _emit_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _retag_complex_progress(callback: ProgressCallback | None) -> ProgressCallback | None:
    if callback is None:
        return None

    def _wrapped(message: str) -> None:
        if message.startswith("[T08 Tool3] complex_divmerge"):
            message = message.replace("[T08 Tool3]", "[T08 Tool5]", 1)
        callback(message)

    return _wrapped


__all__ = [
    "T08ComplexJunctionPreprocessArtifacts",
    "run_t08_complex_junction_preprocess",
]
