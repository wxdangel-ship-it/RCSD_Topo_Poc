from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, write_json, write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.shared import (
    NodeRecord,
    T02RunError,
    normalize_id,
    read_vector_layer_strict,
    resolve_junction_group,
)

INTERSECTION_ID_FIELDS = (
    "id",
    "intersection_id",
    "intersectionid",
    "fid",
    "objectid",
    "OBJECTID",
)

REASON_MISSING_REQUIRED_FIELD = "missing_required_field"
REASON_INVALID_CRS_OR_UNPROJECTABLE = "invalid_crs_or_unprojectable"
REASON_REPRESENTATIVE_NODE_MISSING = "representative_node_missing"
REASON_JUNCTION_NODES_NOT_FOUND = "junction_nodes_not_found"

SKIP_SINGLE_GROUP = "single_group_in_intersection"
SKIP_KIND1_FILTER = "single_group_after_kind1_filter"
SKIP_GROUP_RESOLUTION_FAILED = "group_resolution_failed"
SKIP_NOT_ALL_GROUPS_CONNECTED = "not_all_groups_connected"
SKIP_ALREADY_CONSUMED = "group_already_merged_by_previous_intersection"


class FixNodeError2RunError(T02RunError):
    pass


@dataclass(frozen=True)
class CandidateGroup:
    junction_id: str
    representative_output_index: int
    representative_node_id: str
    representative_kind_2: str | None
    representative_grade_2: str | None
    group_nodes: list[NodeRecord]

    @property
    def node_ids(self) -> set[str]:
        return {record.node_id for record in self.group_nodes}


@dataclass(frozen=True)
class ParsedRoad:
    feature_index: int
    road_id: str
    snodeid: str
    enodeid: str
    geometry: Any


@dataclass(frozen=True)
class IntersectionRecord:
    feature_index: int
    intersection_id: str
    geometry: Any


@dataclass(frozen=True)
class ErrorNodeRecord:
    feature_index: int
    node_id: str
    junction_id: str
    geometry: Any


@dataclass(frozen=True)
class FixNodeError2Artifacts:
    success: bool
    nodes_fix_path: Path
    roads_fix_path: Path
    fix_report_path: Path


def _sort_key(value: Any) -> tuple[int, Any]:
    normalized = normalize_id(value)
    if normalized is None:
        return (2, "")
    if normalized.isdigit():
        return (0, int(normalized))
    try:
        return (0, int(float(normalized)))
    except Exception:
        return (1, normalized)


def _intersection_identity(properties: dict[str, Any], feature_index: int) -> str:
    for field in INTERSECTION_ID_FIELDS:
        value = normalize_id(properties.get(field))
        if value is not None:
            return f"{field}:{value}"
    return f"feature_index:{feature_index}"


def _group_id_for_properties(properties: dict[str, Any]) -> str | None:
    return normalize_id(properties.get("mainnodeid")) or normalize_id(properties.get("id"))


def _serialize_feature(feature: Any) -> dict[str, Any]:
    return {
        "properties": dict(feature.properties),
        "geometry": feature.geometry,
    }


def _grade_for_merge(groups: list[CandidateGroup], *, chosen_group: CandidateGroup) -> Any:
    representative_grades = [normalize_id(group.representative_grade_2) for group in groups]
    if "1" in representative_grades:
        return 1
    if "2" in representative_grades:
        return 2
    chosen_value = chosen_group.representative_grade_2
    if chosen_value is None:
        return None
    if str(chosen_value).isdigit():
        return int(str(chosen_value))
    return chosen_value


def _build_node_indexes(nodes_layer_data: Any) -> tuple[
    dict[str, list[NodeRecord]],
    dict[str, list[NodeRecord]],
    dict[str, int],
    dict[str, str],
    dict[str, str | None],
]:
    nodes_by_mainnodeid: dict[str, list[NodeRecord]] = {}
    singleton_nodes_by_id: dict[str, list[NodeRecord]] = {}
    node_output_index_by_id: dict[str, int] = {}
    semantic_group_id_by_node_id: dict[str, str] = {}
    representative_kind_2_by_group_id: dict[str, str | None] = {}

    for output_index, feature in enumerate(nodes_layer_data.features):
        missing_fields: list[str] = []
        for field in ("id", "mainnodeid", "kind_2", "grade_2", "subnodeid"):
            if field not in feature.properties:
                missing_fields.append(field)
        node_id = normalize_id(feature.properties.get("id"))
        mainnodeid = normalize_id(feature.properties.get("mainnodeid"))
        if node_id is None:
            missing_fields.append("id_value")
        if feature.geometry is None or feature.geometry.is_empty:
            missing_fields.append("geometry")
        if missing_fields:
            raise FixNodeError2RunError(
                REASON_MISSING_REQUIRED_FIELD,
                f"nodes feature[{feature.feature_index}] missing/invalid fields: {','.join(sorted(set(missing_fields)))}",
            )
        record = NodeRecord(
            feature_index=feature.feature_index,
            output_index=output_index,
            node_id=node_id,
            mainnodeid=mainnodeid,
            geometry=feature.geometry,
        )
        group_id = mainnodeid or node_id
        node_output_index_by_id[node_id] = output_index
        semantic_group_id_by_node_id[node_id] = group_id
        if node_id == group_id:
            representative_kind_2_by_group_id[group_id] = normalize_id(feature.properties.get("kind_2"))
        if mainnodeid is not None:
            nodes_by_mainnodeid.setdefault(mainnodeid, []).append(record)
        else:
            singleton_nodes_by_id.setdefault(node_id, []).append(record)
    return (
        nodes_by_mainnodeid,
        singleton_nodes_by_id,
        node_output_index_by_id,
        semantic_group_id_by_node_id,
        representative_kind_2_by_group_id,
    )


def _parse_roads(roads_layer_data: Any) -> tuple[list[ParsedRoad], dict[str, set[str]], Counter[str]]:
    roads: list[ParsedRoad] = []
    adjacency: dict[str, set[str]] = defaultdict(set)
    degree_by_node_id: Counter[str] = Counter()
    for feature_index, feature in enumerate(roads_layer_data.features):
        missing_fields: list[str] = []
        for field in ("id", "snodeid", "enodeid"):
            if field not in feature.properties:
                missing_fields.append(field)
        road_id = normalize_id(feature.properties.get("id"))
        snodeid = normalize_id(feature.properties.get("snodeid"))
        enodeid = normalize_id(feature.properties.get("enodeid"))
        if road_id is None:
            missing_fields.append("id_value")
        if snodeid is None:
            missing_fields.append("snodeid_value")
        if enodeid is None:
            missing_fields.append("enodeid_value")
        if feature.geometry is None or feature.geometry.is_empty:
            missing_fields.append("geometry")
        if missing_fields:
            raise FixNodeError2RunError(
                REASON_MISSING_REQUIRED_FIELD,
                f"roads feature[{feature.feature_index}] missing/invalid fields: {','.join(sorted(set(missing_fields)))}",
            )
        roads.append(
            ParsedRoad(
                feature_index=feature_index,
                road_id=road_id,
                snodeid=snodeid,
                enodeid=enodeid,
                geometry=feature.geometry,
            )
        )
        adjacency[snodeid].add(enodeid)
        adjacency[enodeid].add(snodeid)
        degree_by_node_id[snodeid] += 1
        degree_by_node_id[enodeid] += 1
    return roads, adjacency, degree_by_node_id


def _parse_intersections(intersection_layer_data: Any) -> tuple[list[IntersectionRecord], STRtree]:
    intersections: list[IntersectionRecord] = []
    for feature_index, feature in enumerate(intersection_layer_data.features):
        if feature.geometry is None or feature.geometry.is_empty:
            continue
        intersections.append(
            IntersectionRecord(
                feature_index=feature_index,
                intersection_id=_intersection_identity(feature.properties, feature.feature_index),
                geometry=feature.geometry,
            )
        )
    if not intersections:
        raise FixNodeError2RunError(
            REASON_MISSING_REQUIRED_FIELD,
            "RCSDIntersection layer has no non-empty geometry features after projection to EPSG:3857.",
        )
    return intersections, STRtree([record.geometry for record in intersections])


def _parse_error_nodes(node_error2_layer_data: Any) -> tuple[list[ErrorNodeRecord], STRtree]:
    records: list[ErrorNodeRecord] = []
    for feature_index, feature in enumerate(node_error2_layer_data.features):
        node_id = normalize_id(feature.properties.get("id"))
        junction_id = normalize_id(feature.properties.get("junction_id")) or _group_id_for_properties(feature.properties)
        if node_id is None or junction_id is None or feature.geometry is None or feature.geometry.is_empty:
            raise FixNodeError2RunError(
                REASON_MISSING_REQUIRED_FIELD,
                f"node_error_2 feature[{feature.feature_index}] missing required id/junction_id/geometry fields.",
            )
        records.append(
            ErrorNodeRecord(
                feature_index=feature_index,
                node_id=node_id,
                junction_id=junction_id,
                geometry=feature.geometry,
            )
        )
    if not records:
        raise FixNodeError2RunError(REASON_MISSING_REQUIRED_FIELD, "node_error_2 layer is empty.")
    return records, STRtree([record.geometry for record in records])


def _resolve_candidate_groups(
    *,
    junction_ids: list[str],
    nodes_layer_data: Any,
    nodes_by_mainnodeid: dict[str, list[NodeRecord]],
    singleton_nodes_by_id: dict[str, list[NodeRecord]],
) -> tuple[list[CandidateGroup], list[str]]:
    groups: list[CandidateGroup] = []
    failures: list[str] = []
    for junction_id in junction_ids:
        resolved = resolve_junction_group(
            junction_id,
            nodes_by_mainnodeid=nodes_by_mainnodeid,
            singleton_nodes_by_id=singleton_nodes_by_id,
            representative_missing_reason=REASON_REPRESENTATIVE_NODE_MISSING,
            junction_not_found_reason=REASON_JUNCTION_NODES_NOT_FOUND,
        )
        if resolved.reason is not None or resolved.representative is None:
            failures.append(junction_id)
            continue
        representative_properties = nodes_layer_data.features[resolved.representative.output_index].properties
        groups.append(
            CandidateGroup(
                junction_id=junction_id,
                representative_output_index=resolved.representative.output_index,
                representative_node_id=resolved.representative.node_id,
                representative_kind_2=normalize_id(representative_properties.get("kind_2")),
                representative_grade_2=normalize_id(representative_properties.get("grade_2")),
                group_nodes=list(resolved.group_nodes),
            )
        )
    groups.sort(key=lambda item: _sort_key(item.junction_id))
    return groups, failures


def _reachable_group_ids(
    *,
    start_group_id: str,
    candidate_groups_by_id: dict[str, CandidateGroup],
    adjacency: dict[str, set[str]],
    blocked_node_ids: set[str],
    semantic_group_id_by_node_id: dict[str, str],
) -> set[str]:
    start_node_ids = set(candidate_groups_by_id[start_group_id].node_ids)
    visited_node_ids = set(start_node_ids)
    queue: deque[str] = deque(sorted(start_node_ids, key=_sort_key))
    reached_group_ids = {start_group_id}

    while queue:
        current_node_id = queue.popleft()
        for next_node_id in sorted(adjacency.get(current_node_id, ()), key=_sort_key):
            if next_node_id in visited_node_ids:
                continue
            if next_node_id in blocked_node_ids:
                continue
            visited_node_ids.add(next_node_id)
            queue.append(next_node_id)
            next_group_id = semantic_group_id_by_node_id.get(next_node_id)
            if next_group_id in candidate_groups_by_id:
                reached_group_ids.add(next_group_id)
    return reached_group_ids


def _build_deleted_road_ids(
    *,
    roads: list[ParsedRoad],
    merged_node_ids: set[str],
    intersection_geometry: Any,
) -> list[str]:
    deleted = [
        road.road_id
        for road in roads
        if road.snodeid in merged_node_ids and road.enodeid in merged_node_ids and intersection_geometry.covers(road.geometry)
    ]
    return sorted(set(deleted), key=_sort_key)


def run_t02_fix_node_error_2(
    *,
    node_error2_path: Union[str, Path],
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    intersection_path: Union[str, Path],
    nodes_fix_path: Union[str, Path],
    roads_fix_path: Union[str, Path],
    report_path: Union[str, Path, None] = None,
    node_error2_layer: Optional[str] = None,
    nodes_layer: Optional[str] = None,
    roads_layer: Optional[str] = None,
    intersection_layer: Optional[str] = None,
    node_error2_crs: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    roads_crs: Optional[str] = None,
    intersection_crs: Optional[str] = None,
) -> FixNodeError2Artifacts:
    nodes_fix_path = Path(nodes_fix_path)
    roads_fix_path = Path(roads_fix_path)
    fix_report_path = Path(report_path) if report_path is not None else nodes_fix_path.with_name("fix_report.json")

    node_error2_layer_data = read_vector_layer_strict(
        node_error2_path,
        layer_name=node_error2_layer,
        crs_override=node_error2_crs,
        allow_null_geometry=False,
        error_cls=FixNodeError2RunError,
    )
    nodes_layer_data = read_vector_layer_strict(
        nodes_path,
        layer_name=nodes_layer,
        crs_override=nodes_crs,
        allow_null_geometry=False,
        error_cls=FixNodeError2RunError,
    )
    roads_layer_data = read_vector_layer_strict(
        roads_path,
        layer_name=roads_layer,
        crs_override=roads_crs,
        allow_null_geometry=False,
        error_cls=FixNodeError2RunError,
    )
    intersection_layer_data = read_vector_layer_strict(
        intersection_path,
        layer_name=intersection_layer,
        crs_override=intersection_crs,
        allow_null_geometry=False,
        error_cls=FixNodeError2RunError,
    )

    (
        nodes_by_mainnodeid,
        singleton_nodes_by_id,
        node_output_index_by_id,
        semantic_group_id_by_node_id,
        representative_kind_2_by_group_id,
    ) = _build_node_indexes(nodes_layer_data)
    roads, adjacency, degree_by_node_id = _parse_roads(roads_layer_data)
    intersections, _intersection_tree = _parse_intersections(intersection_layer_data)
    error_nodes, error_node_tree = _parse_error_nodes(node_error2_layer_data)

    consumed_group_ids: set[str] = set()
    deleted_road_ids_all: set[str] = set()
    report_rows: list[dict[str, Any]] = []

    for intersection in sorted(intersections, key=lambda item: _sort_key(item.intersection_id)):
        candidate_indexes = error_node_tree.query(intersection.geometry, predicate="intersects")
        candidate_group_ids = sorted(
            {error_nodes[int(index)].junction_id for index in candidate_indexes},
            key=_sort_key,
        )
        row: dict[str, Any] = {
            "intersection_id": intersection.intersection_id,
            "candidate_group_ids": candidate_group_ids,
            "candidate_group_count": len(candidate_group_ids),
            "ignored_kind1_group_ids": [],
            "ignored_kind1_group_count": 0,
            "remaining_group_ids": [],
            "remaining_group_count": 0,
            "merged_group_ids": [],
            "merged_group_count": 0,
            "chosen_mainnodeid": None,
            "merged_node_ids": [],
            "deleted_road_ids": [],
            "status": "skipped",
            "skip_reason": None,
        }

        if len(candidate_group_ids) <= 1:
            row["skip_reason"] = SKIP_SINGLE_GROUP
            report_rows.append(row)
            continue

        if any(group_id in consumed_group_ids for group_id in candidate_group_ids):
            row["skip_reason"] = SKIP_ALREADY_CONSUMED
            report_rows.append(row)
            continue

        candidate_groups, failed_group_ids = _resolve_candidate_groups(
            junction_ids=candidate_group_ids,
            nodes_layer_data=nodes_layer_data,
            nodes_by_mainnodeid=nodes_by_mainnodeid,
            singleton_nodes_by_id=singleton_nodes_by_id,
        )
        if failed_group_ids:
            row["skip_reason"] = SKIP_GROUP_RESOLUTION_FAILED
            row["failed_group_ids"] = failed_group_ids
            report_rows.append(row)
            continue

        if len(candidate_groups) <= 1:
            row["skip_reason"] = SKIP_SINGLE_GROUP
            report_rows.append(row)
            continue

        ignored_kind1_groups = [group for group in candidate_groups if group.representative_kind_2 == "1"]
        remaining_groups = [group for group in candidate_groups if group.representative_kind_2 != "1"]
        row["ignored_kind1_group_ids"] = [group.junction_id for group in ignored_kind1_groups]
        row["ignored_kind1_group_count"] = len(ignored_kind1_groups)
        row["remaining_group_ids"] = [group.junction_id for group in remaining_groups]
        row["remaining_group_count"] = len(remaining_groups)

        if len(remaining_groups) <= 1:
            row["skip_reason"] = SKIP_KIND1_FILTER
            report_rows.append(row)
            continue

        remaining_group_ids = {group.junction_id for group in remaining_groups}
        blocked_node_ids = {
            node_id
            for node_id, semantic_group_id in semantic_group_id_by_node_id.items()
            if semantic_group_id not in remaining_group_ids
            and representative_kind_2_by_group_id.get(semantic_group_id) not in {None, "0"}
            and degree_by_node_id.get(node_id, 0) != 2
        }
        candidate_groups_by_id = {group.junction_id: group for group in remaining_groups}
        seed_group_id = sorted(remaining_group_ids, key=_sort_key)[0]
        reached_group_ids = _reachable_group_ids(
            start_group_id=seed_group_id,
            candidate_groups_by_id=candidate_groups_by_id,
            adjacency=adjacency,
            blocked_node_ids=blocked_node_ids,
            semantic_group_id_by_node_id=semantic_group_id_by_node_id,
        )
        if reached_group_ids != remaining_group_ids:
            row["skip_reason"] = SKIP_NOT_ALL_GROUPS_CONNECTED
            row["reachable_group_ids"] = sorted(reached_group_ids, key=_sort_key)
            report_rows.append(row)
            continue

        chosen_group = sorted(
            remaining_groups,
            key=lambda item: (_sort_key(item.junction_id), _sort_key(item.representative_node_id)),
        )[0]
        chosen_mainnodeid = chosen_group.junction_id
        merged_node_ids = sorted(
            {node_id for group in remaining_groups for node_id in group.node_ids},
            key=_sort_key,
        )
        subnode_ids = [node_id for node_id in merged_node_ids if node_id != chosen_group.representative_node_id]
        new_grade = _grade_for_merge(remaining_groups, chosen_group=chosen_group)

        for group in remaining_groups:
            consumed_group_ids.add(group.junction_id)
        row["status"] = "merged"
        row["skip_reason"] = None
        row["merged_group_ids"] = sorted(remaining_group_ids, key=_sort_key)
        row["merged_group_count"] = len(remaining_group_ids)
        row["chosen_mainnodeid"] = chosen_mainnodeid
        row["merged_node_ids"] = merged_node_ids

        chosen_output_index = node_output_index_by_id[chosen_group.representative_node_id]
        chosen_properties = nodes_layer_data.features[chosen_output_index].properties
        chosen_properties["mainnodeid"] = chosen_mainnodeid
        chosen_properties["kind_2"] = 4
        chosen_properties["grade_2"] = new_grade
        chosen_properties["subnodeid"] = ",".join(subnode_ids) if subnode_ids else None

        for node_id in subnode_ids:
            output_index = node_output_index_by_id[node_id]
            props = nodes_layer_data.features[output_index].properties
            props["mainnodeid"] = chosen_mainnodeid
            props["kind_2"] = 0
            props["grade_2"] = 0
            props["subnodeid"] = None

        deleted_road_ids = _build_deleted_road_ids(
            roads=roads,
            merged_node_ids=set(merged_node_ids),
            intersection_geometry=intersection.geometry,
        )
        row["deleted_road_ids"] = deleted_road_ids
        deleted_road_ids_all.update(deleted_road_ids)
        report_rows.append(row)

    nodes_fix_features = [_serialize_feature(feature) for feature in nodes_layer_data.features]
    roads_fix_features = [
        _serialize_feature(roads_layer_data.features[road.feature_index])
        for road in roads
        if road.road_id not in deleted_road_ids_all
    ]

    write_vector(nodes_fix_path, nodes_fix_features, crs_text=TARGET_CRS.to_string())
    write_vector(roads_fix_path, roads_fix_features, crs_text=TARGET_CRS.to_string())
    write_json(
        fix_report_path,
        {
            "success": True,
            "target_crs": TARGET_CRS.to_string(),
            "inputs": {
                "node_error_2_path": str(node_error2_path),
                "nodes_path": str(nodes_path),
                "roads_path": str(roads_path),
                "intersection_path": str(intersection_path),
            },
            "output_files": {
                "nodes_fix_path": str(nodes_fix_path),
                "roads_fix_path": str(roads_fix_path),
            },
            "counts": {
                "node_error_2_feature_count": len(error_nodes),
                "intersection_feature_count": len(intersections),
                "merged_intersection_count": sum(1 for row in report_rows if row["status"] == "merged"),
                "skipped_intersection_count": sum(1 for row in report_rows if row["status"] != "merged"),
                "deleted_road_count": len(deleted_road_ids_all),
            },
            "rows": report_rows,
        },
    )
    return FixNodeError2Artifacts(
        success=True,
        nodes_fix_path=nodes_fix_path,
        roads_fix_path=roads_fix_path,
        fix_report_path=fix_report_path,
    )


def run_t02_fix_node_error_2_cli(args: argparse.Namespace) -> int:
    try:
        artifacts = run_t02_fix_node_error_2(
            node_error2_path=args.node_error2_path,
            nodes_path=args.nodes_path,
            roads_path=args.roads_path,
            intersection_path=args.intersection_path,
            nodes_fix_path=args.nodes_fix_path,
            roads_fix_path=args.roads_fix_path,
            report_path=args.report_path,
            node_error2_layer=args.node_error2_layer,
            nodes_layer=args.nodes_layer,
            roads_layer=args.roads_layer,
            intersection_layer=args.intersection_layer,
            node_error2_crs=args.node_error2_crs,
            nodes_crs=args.nodes_crs,
            roads_crs=args.roads_crs,
            intersection_crs=args.intersection_crs,
        )
    except FixNodeError2RunError as exc:
        print(f"[T02-FIX-NODE-ERROR-2] {exc.reason}: {exc.detail}")
        return 2

    print(f"nodes_fix written to: {artifacts.nodes_fix_path}")
    print(f"roads_fix written to: {artifacts.roads_fix_path}")
    print(f"fix_report written to: {artifacts.fix_report_path}")
    return 0
