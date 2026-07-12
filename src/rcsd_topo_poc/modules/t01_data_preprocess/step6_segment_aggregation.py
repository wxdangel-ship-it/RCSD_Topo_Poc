from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from shapely.geometry import LineString, MultiLineString

from rcsd_topo_poc.modules.t01_data_preprocess.advance_right_segments import (
    ADVANCE_RIGHT_SEGMENT_TYPE,
    NORMAL_SEGMENT_TYPE,
    AdvanceRightAssignmentSummary,
    assign_advance_right_segments,
    is_advance_right_properties,
)
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    MainnodeGroup,
    NodeFeatureRecord,
    RoadFeatureRecord,
    _build_mainnode_groups,
    _load_nodes_and_roads,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_json, write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    _coerce_int,
    _find_repo_root,
    _mainnodeid_physical_id_alias,
    _sort_key,
)
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    WORKING_NODE_FIELDS,
    WORKING_ROAD_FIELDS,
    get_road_segmentid,
    get_road_sgrade,
    is_allowed_road_kind,
    sanitize_public_node_properties,
)


DEFAULT_RUN_ID_PREFIX = "t01_step6_segment_aggregation_"
STEP6_SEGMENT_GRADE_VALUE = "0-0双"
STEP6_ERROR_TYPE_S_GRADE_CONFLICT = "s_grade_conflict"
STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT = "grade_kind_conflict"
STEP6_ERROR_TYPE_MISSING_ENDPOINT_NODE = "missing_endpoint_node"
STEP6_ONEWAY_SEGMENT_GRADE_VALUES = ("0-0单", "0-1单", "0-2单")
STEP6_S_GRADE_PRIORITY_ORDER = ("0-0双", "0-0单", "0-1双", "0-1单", "0-2双", "0-2单")
DEAD_END_BUILD_SOURCE = "dead_end_leaf"
STEP6_HIGH_GRADE_DEMOTION_BUILD_SOURCE = "step4_high_grade_terminal_demotion"
STEP6_ERROR_LAYER_FILENAMES = {
    STEP6_ERROR_TYPE_S_GRADE_CONFLICT: "segment_error_s_grade_conflict.gpkg",
    STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT: "segment_error_grade_kind_conflict.gpkg",
}


@dataclass(frozen=True)
class Step6Artifacts:
    out_root: Path
    segment_path: Path
    inner_nodes_path: Path
    segment_error_path: Path
    error_layer_paths: dict[str, Path]
    segment_summary_path: Path
    segment_build_table_path: Path
    inner_nodes_summary_path: Path
    summary: dict[str, Any]
    inner_nodes_summary: dict[str, Any]


@dataclass(frozen=True)
class SegmentRecord:
    segment_id: st
    segment_type: str
    pair_nodes: tuple[str, ...]
    road_ids: tuple[str, ...]
    multiline: MultiLineString
    sgrade_old: Optional[str]
    sgrade_new: Optional[str]
    junc_nodes: tuple[str, ...]
    inner_group_ids: tuple[str, ...]
    adjusted: bool
    adjust_reason: Optional[str]
    sgrade_conflict_values: tuple[str, ...]
    dead_end_leaf: bool
    error_type: Optional[str]
    error_desc: Optional[str]
    grade_kind_conflict_waived: bool
    grade_kind_conflict_waived_nodes: tuple[str, ...]
    missing_endpoint_road_ids: tuple[str, ...] = ()
    missing_endpoint_details: tuple[str, ...] = ()


def _build_default_run_id(now: Optional[datetime] = None) -> str:
    current = datetime.now() if now is None else now
    return f"{DEFAULT_RUN_ID_PREFIX}{current.strftime('%Y%m%d_%H%M%S')}"


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or _build_default_run_id()
    if out_root is not None:
        return Path(out_root), resolved_run_id

    start = Path.cwd() if cwd is None else cwd
    repo_root = _find_repo_root(start)
    if repo_root is None:
        raise ValueError("Cannot infer default out_root because repo root was not found; please pass --out-root.")
    return repo_root / "outputs" / "_work" / "t01_step6_segment_aggregation" / resolved_run_id, resolved_run_id


def _current_grade_2(node: NodeFeatureRecord) -> Optional[int]:
    return _coerce_int(node.properties.get("grade_2"))


def _current_kind_2(node: NodeFeatureRecord) -> Optional[int]:
    return _coerce_int(node.properties.get("kind_2"))


def _require_working_layers(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    stage_label: str,
    node_properties_map: Optional[dict[str, dict[str, Any]]] = None,
    road_properties_map: Optional[dict[str, dict[str, Any]]] = None,
) -> None:
    issues: list[str] = []
    for index, node in enumerate(nodes):
        properties = node.properties if node_properties_map is None else node_properties_map.get(node.node_id, node.properties)
        missing = [field for field in WORKING_NODE_FIELDS if field != "working_mainnodeid" and field not in properties]
        if missing:
            issues.append(f"{stage_label} node feature[{index}] missing working fields: {', '.join(missing)}")
    for index, road in enumerate(roads):
        properties = road.properties if road_properties_map is None else road_properties_map.get(road.road_id, road.properties)
        missing = [field for field in WORKING_ROAD_FIELDS if field not in properties]
        if missing:
            issues.append(f"{stage_label} road feature[{index}] missing working fields: {', '.join(missing)}")
    if issues:
        raise ValueError("; ".join(issues))


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _display_optional_value(value: Optional[str]) -> str:
    return "null" if value is None else value


def _segment_sort_key(segment_id: str) -> tuple[tuple[int, Any], ...]:
    return tuple(_sort_key(part) for part in segment_id.split("_"))


def _parse_segment_pair_nodes(segment_id: str) -> tuple[str, str]:
    parts = [part.strip() for part in segment_id.split("_")]
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    if len(parts) == 3 and parts[0] and parts[1] and parts[2].isdigit():
        return parts[0], parts[1]
    raise ValueError(f"Step6 expects segmentid in 'A_B' or 'A_B_N' form, got '{segment_id}'.")


def _mainnode_lookup_aliases(node_id: str) -> tuple[str, ...]:
    aliases = [node_id]
    physical_alias = _mainnodeid_physical_id_alias(node_id)
    if physical_alias is not None and physical_alias not in aliases:
        aliases.append(physical_alias)
    if node_id.isdigit():
        decimal_alias = f"{node_id}.0"
        if decimal_alias not in aliases:
            aliases.append(decimal_alias)
    return tuple(aliases)


def _resolve_mainnode_group(
    node_id: str,
    mainnode_groups: dict[str, MainnodeGroup],
) -> tuple[Optional[str], Optional[MainnodeGroup]]:
    for alias in _mainnode_lookup_aliases(node_id):
        group = mainnode_groups.get(alias)
        if group is not None:
            return alias, group
    return None, None


def _resolve_allowed_road_ids(
    node_id: str,
    group_to_allowed_road_ids: dict[str, set[str]],
) -> set[str]:
    for alias in _mainnode_lookup_aliases(node_id):
        allowed_road_ids = group_to_allowed_road_ids.get(alias)
        if allowed_road_ids is not None:
            return allowed_road_ids
    return set()


def _flatten_lines(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [geom for geom in geometry.geoms if isinstance(geom, LineString)]
    raise ValueError(f"Step6 only supports LineString/MultiLineString road geometry, got '{type(geometry).__name__}'.")


def _join_ids(values: tuple[str, ...]) -> str:
    return ",".join(values)


def _join_optional_values(values: tuple[str, ...]) -> Optional[str]:
    if not values:
        return None
    return ",".join(values)


def _resolve_highest_s_grade(values: tuple[str, ...]) -> Optional[str]:
    if not values:
        return None
    priority_map = {value: index for index, value in enumerate(STEP6_S_GRADE_PRIORITY_ORDER)}
    known_values = [value for value in values if value in priority_map]
    if known_values:
        return min(known_values, key=lambda value: priority_map[value])
    return sorted(values, key=_sort_key)[0]


def _is_oneway_sgrade(value: Optional[str]) -> bool:
    return value in STEP6_ONEWAY_SEGMENT_GRADE_VALUES


def _is_allowed_step6_incident_road(properties: dict[str, Any], road: RoadFeatureRecord) -> bool:
    road_kind = _coerce_int(properties.get("road_kind")) if "road_kind" in properties else road.road_kind
    if is_allowed_road_kind(road_kind):
        return True
    if _normalize_text(properties.get("segment_build_source")) == DEAD_END_BUILD_SOURCE and _normalize_text(
        get_road_segmentid(properties)
    ) is not None:
        return True
    return _is_oneway_sgrade(_normalize_text(get_road_sgrade(properties))) and _normalize_text(
        get_road_segmentid(properties)
    ) is not None


def _build_group_to_allowed_road_ids(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    road_properties_map: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, set[str]]:
    node_by_id = {node.node_id: node for node in nodes}
    group_to_allowed_road_ids: dict[str, set[str]] = defaultdict(set)
    for road in roads:
        current_props = road.properties if road_properties_map is None else road_properties_map.get(road.road_id, road.properties)
        if not _is_allowed_step6_incident_road(current_props, road):
            continue
        for node_id in (road.snodeid, road.enodeid):
            node = node_by_id.get(node_id)
            if node is None:
                continue
            group_to_allowed_road_ids[node.semantic_node_id].add(road.road_id)
    return group_to_allowed_road_ids


def _missing_endpoint_details(
    *,
    road: RoadFeatureRecord,
    node_by_id: dict[str, NodeFeatureRecord],
) -> tuple[str, ...]:
    details: list[str] = []
    if road.snodeid not in node_by_id:
        details.append(f"{road.road_id}:snodeid={road.snodeid}")
    if road.enodeid not in node_by_id:
        details.append(f"{road.road_id}:enodeid={road.enodeid}")
    return tuple(details)


def _collect_segment_records(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    node_properties_map: Optional[dict[str, dict[str, Any]]] = None,
    road_properties_map: Optional[dict[str, dict[str, Any]]] = None,
    mainnode_groups: Optional[dict[str, MainnodeGroup]] = None,
    group_to_allowed_road_ids: Optional[dict[str, set[str]]] = None,
) -> tuple[list[SegmentRecord], list[SegmentRecord], dict[str, list[NodeFeatureRecord]]]:
    node_by_id = {node.node_id: node for node in nodes}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    if mainnode_groups is None:
        mainnode_groups, _ = _build_mainnode_groups(node_by_id, groups)

    roads_by_segment_id: dict[str, list[RoadFeatureRecord]] = defaultdict(list)
    for road in roads:
        current_props = road.properties if road_properties_map is None else road_properties_map.get(road.road_id, road.properties)
        segment_id = _normalize_text(get_road_segmentid(current_props))
        if segment_id is None:
            continue
        roads_by_segment_id[segment_id].append(road)

    if group_to_allowed_road_ids is None:
        group_to_allowed_road_ids = _build_group_to_allowed_road_ids(
            nodes=nodes,
            roads=roads,
            road_properties_map=road_properties_map,
        )
    inner_nodes_by_segment: dict[str, list[NodeFeatureRecord]] = defaultdict(list)
    segment_records: list[SegmentRecord] = []
    skipped_segment_records: list[SegmentRecord] = []

    for segment_id in sorted(roads_by_segment_id, key=_segment_sort_key):
        segment_roads = roads_by_segment_id[segment_id]
        road_ids = tuple(sorted({road.road_id for road in segment_roads}, key=_sort_key))
        segment_road_properties = [
            road.properties if road_properties_map is None else road_properties_map.get(road.road_id, road.properties)
            for road in segment_roads
        ]
        segment_type_values = {
            _normalize_text(properties.get("segment_type")) or NORMAL_SEGMENT_TYPE
            for properties in segment_road_properties
        }
        if len(segment_type_values) != 1:
            raise ValueError(
                f"Step6 segment '{segment_id}' contains mixed segment_type values: "
                + ",".join(sorted(segment_type_values))
            )
        segment_type = next(iter(segment_type_values))
        if segment_type == ADVANCE_RIGHT_SEGMENT_TYPE:
            if not all(is_advance_right_properties(properties) for properties in segment_road_properties):
                raise ValueError(
                    f"Step6 advance-right segment '{segment_id}' contains a road without formway bit 128."
                )
            flattened_lines = [
                line
                for road in segment_roads
                for line in _flatten_lines(road.geometry)
            ]
            sgrade_values = tuple(
                sorted(
                    {
                        value
                        for value in (
                            _normalize_text(get_road_sgrade(properties))
                            for properties in segment_road_properties
                        )
                        if value is not None
                    },
                    key=_sort_key,
                )
            )
            segment_records.append(
                SegmentRecord(
                    segment_id=segment_id,
                    segment_type=ADVANCE_RIGHT_SEGMENT_TYPE,
                    pair_nodes=(),
                    road_ids=road_ids,
                    multiline=MultiLineString(flattened_lines),
                    sgrade_old=_join_optional_values(sgrade_values),
                    sgrade_new=_resolve_highest_s_grade(sgrade_values),
                    junc_nodes=(),
                    inner_group_ids=(),
                    adjusted=False,
                    adjust_reason=None,
                    sgrade_conflict_values=(),
                    dead_end_leaf=False,
                    error_type=None,
                    error_desc=None,
                    grade_kind_conflict_waived=False,
                    grade_kind_conflict_waived_nodes=(),
                )
            )
            continue
        if segment_type != NORMAL_SEGMENT_TYPE:
            raise ValueError(f"Step6 segment '{segment_id}' has unsupported segment_type '{segment_type}'.")

        pair_nodes = _parse_segment_pair_nodes(segment_id)
        dead_end_leaf = any(
            _normalize_text(properties.get("segment_build_source")) == DEAD_END_BUILD_SOURCE
            for properties in segment_road_properties
        )
        high_grade_demotion_source = any(
            _normalize_text(properties.get("segment_build_source")) == STEP6_HIGH_GRADE_DEMOTION_BUILD_SOURCE
            for properties in segment_road_properties
        )

        sgrade_values = {
            _normalize_text(get_road_sgrade(properties))
            for properties in segment_road_properties
        }
        sgrade_conflict_values = tuple(sorted(_display_optional_value(value) for value in sgrade_values))
        contains_oneway_sgrade = any(value in STEP6_ONEWAY_SEGMENT_GRADE_VALUES for value in sgrade_values if value is not None)
        if len(sgrade_values) == 1:
            sgrade_old = next(iter(sgrade_values))
            sgrade_new = sgrade_old
            adjusted = False
            adjust_reason = None
            error_type: Optional[str] = None
            error_desc: Optional[str] = None
        else:
            sgrade_old = _join_optional_values(sgrade_conflict_values)
            sgrade_new = _resolve_highest_s_grade(sgrade_conflict_values)
            adjusted = False
            adjust_reason = None
            error_type = STEP6_ERROR_TYPE_S_GRADE_CONFLICT
            error_desc = (
                "segment contains multiple sgrade values: "
                + ",".join(sgrade_conflict_values)
                + f"; selected highest priority='{_display_optional_value(sgrade_new)}'"
            )

        flattened_lines: list[LineString] = []
        covered_group_ids: set[str] = set()
        missing_endpoint_details: list[str] = []
        for road in segment_roads:
            flattened_lines.extend(_flatten_lines(road.geometry))
            missing_endpoint_details.extend(_missing_endpoint_details(road=road, node_by_id=node_by_id))
            snode = node_by_id.get(road.snodeid)
            enode = node_by_id.get(road.enodeid)
            if snode is None or enode is None:
                continue
            covered_group_ids.add(snode.semantic_node_id)
            covered_group_ids.add(enode.semantic_node_id)
        multiline = MultiLineString(flattened_lines)
        if missing_endpoint_details:
            missing_endpoint_road_ids = tuple(
                sorted({detail.split(":", 1)[0] for detail in missing_endpoint_details}, key=_sort_key)
            )
            missing_endpoint_details_sorted = tuple(sorted(set(missing_endpoint_details), key=_sort_key))
            skipped_segment_records.append(
                SegmentRecord(
                    segment_id=segment_id,
                    segment_type=NORMAL_SEGMENT_TYPE,
                    pair_nodes=pair_nodes,
                    road_ids=road_ids,
                    multiline=multiline,
                    sgrade_old=_join_optional_values(sgrade_conflict_values),
                    sgrade_new=_resolve_highest_s_grade(sgrade_conflict_values),
                    junc_nodes=(),
                    inner_group_ids=(),
                    adjusted=False,
                    adjust_reason=None,
                    sgrade_conflict_values=sgrade_conflict_values,
                    dead_end_leaf=dead_end_leaf,
                    error_type=STEP6_ERROR_TYPE_MISSING_ENDPOINT_NODE,
                    error_desc="segment references endpoint nodes missing from Step6 node input: "
                    + ";".join(missing_endpoint_details_sorted),
                    grade_kind_conflict_waived=False,
                    grade_kind_conflict_waived_nodes=(),
                    missing_endpoint_road_ids=missing_endpoint_road_ids,
                    missing_endpoint_details=missing_endpoint_details_sorted,
                )
            )
            continue

        pair_groups: list[MainnodeGroup] = []
        pair_node_equivalent_ids: set[str] = set()
        for pair_node_id in pair_nodes:
            pair_node_equivalent_ids.update(_mainnode_lookup_aliases(pair_node_id))
            resolved_group_id, group = _resolve_mainnode_group(pair_node_id, mainnode_groups)
            if group is None or resolved_group_id is None:
                raise ValueError(f"Step6 segment '{segment_id}' endpoint '{pair_node_id}' does not exist in node groups.")
            pair_groups.append(group)
            pair_node_equivalent_ids.add(resolved_group_id)
            pair_node_equivalent_ids.add(group.mainnode_id)

        inner_group_ids: list[str] = []
        junc_nodes: list[str] = []
        road_id_set = set(road_ids)
        for semantic_node_id in sorted(covered_group_ids, key=_sort_key):
            if semantic_node_id in pair_node_equivalent_ids:
                continue
            allowed_road_ids = _resolve_allowed_road_ids(semantic_node_id, group_to_allowed_road_ids)
            if allowed_road_ids and allowed_road_ids.issubset(road_id_set):
                inner_group_ids.append(semantic_node_id)
                _, inner_group = _resolve_mainnode_group(semantic_node_id, mainnode_groups)
                if inner_group is None:
                    raise ValueError(f"Step6 segment '{segment_id}' inner node '{semantic_node_id}' does not exist in node groups.")
                member_ids = inner_group.member_node_ids
                for node_id in member_ids:
                    inner_nodes_by_segment[segment_id].append(node_by_id[node_id])
                continue
            junc_nodes.append(semantic_node_id)

        pair_grade_values: list[Optional[int]] = []
        for group in pair_groups:
            representative = node_by_id[group.representative_node_id]
            current_node_props = (
                representative.properties
                if node_properties_map is None
                else node_properties_map.get(representative.node_id, representative.properties)
            )
            pair_grade_values.append(_coerce_int(current_node_props.get("grade_2")))

        if (
            error_type is None
            and pair_grade_values == [1, 1]
            and sgrade_old != STEP6_SEGMENT_GRADE_VALUE
            and not contains_oneway_sgrade
            and not dead_end_leaf
        ):
            adjusted = True
            sgrade_new = STEP6_SEGMENT_GRADE_VALUE
            adjust_reason = "both_pair_nodes_grade_2_eq_1"

        if sgrade_new == STEP6_SEGMENT_GRADE_VALUE:
            conflicting_nodes: list[str] = []
            for semantic_node_id in junc_nodes:
                _, group = _resolve_mainnode_group(semantic_node_id, mainnode_groups)
                if group is None:
                    continue
                representative = node_by_id[group.representative_node_id]
                current_node_props = (
                    representative.properties
                    if node_properties_map is None
                    else node_properties_map.get(representative.node_id, representative.properties)
                )
                if _coerce_int(current_node_props.get("grade_2")) == 1 and _coerce_int(current_node_props.get("kind_2")) == 4:
                    conflicting_nodes.append(semantic_node_id)
            conflicting_node_ids = tuple(sorted(set(conflicting_nodes), key=_sort_key))
            grade_kind_conflict_waived = bool(conflicting_node_ids and high_grade_demotion_source)
            grade_kind_conflict_waived_nodes = conflicting_node_ids if grade_kind_conflict_waived else ()
            if conflicting_node_ids and not grade_kind_conflict_waived:
                error_type = STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT
                error_desc = (
                    "sgrade='0-0双' segment contains junc_nodes with grade_2=1 and kind_2=4: "
                    + ",".join(conflicting_node_ids)
                )
        else:
            grade_kind_conflict_waived = False
            grade_kind_conflict_waived_nodes = ()

        segment_records.append(
            SegmentRecord(
                segment_id=segment_id,
                segment_type=NORMAL_SEGMENT_TYPE,
                pair_nodes=pair_nodes,
                road_ids=road_ids,
                multiline=multiline,
                sgrade_old=sgrade_old,
                sgrade_new=sgrade_new,
                junc_nodes=tuple(sorted(set(junc_nodes), key=_sort_key)),
                inner_group_ids=tuple(sorted(set(inner_group_ids), key=_sort_key)),
                adjusted=adjusted,
                adjust_reason=adjust_reason,
                sgrade_conflict_values=sgrade_conflict_values,
                dead_end_leaf=dead_end_leaf,
                error_type=error_type,
                error_desc=error_desc,
                grade_kind_conflict_waived=grade_kind_conflict_waived,
                grade_kind_conflict_waived_nodes=grade_kind_conflict_waived_nodes,
            )
        )

    return segment_records, skipped_segment_records, inner_nodes_by_segment


def _segment_feature(record: SegmentRecord) -> dict[str, Any]:
    return {
        "properties": {
            "id": record.segment_id,
            "segment_type": record.segment_type,
            "sgrade": record.sgrade_new,
            "pair_nodes": _join_ids(record.pair_nodes),
            "junc_nodes": _join_ids(record.junc_nodes),
            "roads": _join_ids(record.road_ids),
        },
        "geometry": record.multiline,
    }


def _segment_error_feature(record: SegmentRecord) -> dict[str, Any]:
    return {
        "properties": {
            "id": record.segment_id,
            "segment_type": record.segment_type,
            "sgrade": record.sgrade_new,
            "pair_nodes": _join_ids(record.pair_nodes),
            "junc_nodes": _join_ids(record.junc_nodes),
            "roads": _join_ids(record.road_ids),
            "error_type": record.error_type,
            "error_desc": record.error_desc,
            "old_sgrade": record.sgrade_old,
            "new_sgrade": record.sgrade_new,
            "sgrade_conflict_values": _join_ids(record.sgrade_conflict_values),
            "dead_end_leaf": record.dead_end_leaf,
            "flag_s_grade_conflict": record.error_type == STEP6_ERROR_TYPE_S_GRADE_CONFLICT,
            "flag_grade_kind_conflict": record.error_type == STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT,
            "missing_endpoint_road_ids": _join_ids(record.missing_endpoint_road_ids),
            "missing_endpoint_details": ";".join(record.missing_endpoint_details),
        },
        "geometry": record.multiline,
    }


def _write_step6_outputs(
    *,
    segment_records: list[SegmentRecord],
    skipped_segment_records: list[SegmentRecord],
    inner_nodes_by_segment: dict[str, list[NodeFeatureRecord]],
    out_root: Path,
    run_id: str,
    input_node_path: Union[str, Path],
    input_road_path: Union[str, Path],
    debug: bool,
    advance_right_assignment_summary: AdvanceRightAssignmentSummary,
) -> Step6Artifacts:
    resolved_out_root = out_root
    resolved_run_id = run_id

    segment_path = resolved_out_root / "segment.gpkg"
    inner_nodes_path = resolved_out_root / "inner_nodes.gpkg"
    segment_error_path = resolved_out_root / "segment_error.gpkg"
    error_layer_paths = {
        error_type: resolved_out_root / filename
        for error_type, filename in STEP6_ERROR_LAYER_FILENAMES.items()
    }
    segment_summary_path = resolved_out_root / "segment_summary.json"
    segment_build_table_path = resolved_out_root / "segment_build_table.csv"
    inner_nodes_summary_path = resolved_out_root / "inner_nodes_summary.json"

    write_vector(segment_path, (_segment_feature(record) for record in segment_records))

    inner_node_features: list[dict[str, Any]] = []
    inner_group_ids_all: set[str] = set()
    inner_segment_ids: set[str] = set()
    for segment_id, inner_nodes in sorted(inner_nodes_by_segment.items(), key=lambda item: _segment_sort_key(item[0])):
        if not inner_nodes:
            continue
        inner_segment_ids.add(segment_id)
        for node in inner_nodes:
            inner_group_ids_all.add(node.semantic_node_id)
            props = sanitize_public_node_properties(dict(node.properties))
            props["segmentid"] = segment_id
            inner_node_features.append({"properties": props, "geometry": node.geometry})
    write_vector(inner_nodes_path, inner_node_features)

    segment_error_records = [record for record in segment_records if record.error_type is not None]
    segment_error_records.extend(skipped_segment_records)
    write_vector(segment_error_path, (_segment_error_feature(record) for record in segment_error_records))
    for error_type, error_path in error_layer_paths.items():
        matching_records = [record for record in segment_error_records if record.error_type == error_type]
        write_vector(error_path, (_segment_error_feature(record) for record in matching_records))

    segment_summary = {
        "run_id": resolved_run_id,
        "debug": debug,
        "input_node_path": str(Path(input_node_path)),
        "input_road_path": str(Path(input_road_path)),
        "segment_count": len(segment_records),
        "normal_segment_count": sum(
            1 for record in segment_records if record.segment_type == NORMAL_SEGMENT_TYPE
        ),
        "advance_right_segment_count": sum(
            1 for record in segment_records if record.segment_type == ADVANCE_RIGHT_SEGMENT_TYPE
        ),
        "advance_right_road_count": advance_right_assignment_summary.road_count,
        "advance_right_skipped_preassigned_road_count": (
            advance_right_assignment_summary.skipped_preassigned_road_count
        ),
        "skipped_segment_count": len(skipped_segment_records),
        "missing_endpoint_segment_count": len(skipped_segment_records),
        "missing_endpoint_road_count": sum(len(record.missing_endpoint_road_ids) for record in skipped_segment_records),
        "segment_with_junc_count": sum(1 for record in segment_records if record.junc_nodes),
        "segment_with_inner_nodes_count": sum(1 for record in segment_records if record.inner_group_ids),
        "dead_end_segment_count": sum(1 for record in segment_records if record.dead_end_leaf),
        "segment_error_count": len(segment_error_records),
        "sgrade_adjusted_count": sum(1 for record in segment_records if record.adjusted),
        "sgrade_conflict_count": sum(
            1 for record in segment_records if record.error_type == STEP6_ERROR_TYPE_S_GRADE_CONFLICT
        ),
        "grade_kind_conflict_count": sum(
            1 for record in segment_records if record.error_type == STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT
        ),
        "grade_kind_conflict_waived_count": sum(
            1 for record in segment_records if record.grade_kind_conflict_waived
        ),
        "output_files": [
            segment_path.name,
            inner_nodes_path.name,
            segment_error_path.name,
            *[path.name for path in error_layer_paths.values()],
            segment_summary_path.name,
            segment_build_table_path.name,
            inner_nodes_summary_path.name,
        ],
    }
    write_json(segment_summary_path, segment_summary)

    build_records = [*segment_records, *skipped_segment_records]
    build_rows = [
        {
            "segmentid": record.segment_id,
            "segment_type": record.segment_type,
            "road_count": len(record.road_ids),
            "pair_nodes": _join_ids(record.pair_nodes),
            "junc_nodes": _join_ids(record.junc_nodes),
            "road_ids": _join_ids(record.road_ids),
            "sgrade_old": record.sgrade_old,
            "sgrade_new": record.sgrade_new,
            "sgrade_conflict_values": _join_ids(record.sgrade_conflict_values),
            "dead_end_leaf": record.dead_end_leaf,
            "grade_kind_conflict_waived": record.grade_kind_conflict_waived,
            "grade_kind_conflict_waived_nodes": _join_ids(record.grade_kind_conflict_waived_nodes),
            "adjust_reason": record.adjust_reason,
            "error_type": record.error_type,
            "has_error": record.error_type is not None,
        }
        for record in build_records
    ]
    write_csv(
        segment_build_table_path,
        build_rows,
        [
            "segmentid",
            "segment_type",
            "road_count",
            "pair_nodes",
            "junc_nodes",
            "road_ids",
            "sgrade_old",
            "sgrade_new",
            "sgrade_conflict_values",
            "dead_end_leaf",
            "grade_kind_conflict_waived",
            "grade_kind_conflict_waived_nodes",
            "adjust_reason",
            "error_type",
            "has_error",
        ],
    )

    inner_nodes_summary = {
        "run_id": resolved_run_id,
        "inner_segment_count": len(inner_segment_ids),
        "inner_mainnode_count": len(inner_group_ids_all),
        "inner_node_count": len(inner_node_features),
    }
    write_json(inner_nodes_summary_path, inner_nodes_summary)

    return Step6Artifacts(
        out_root=resolved_out_root,
        segment_path=segment_path,
        inner_nodes_path=inner_nodes_path,
        segment_error_path=segment_error_path,
        error_layer_paths=error_layer_paths,
        segment_summary_path=segment_summary_path,
        segment_build_table_path=segment_build_table_path,
        inner_nodes_summary_path=inner_nodes_summary_path,
        summary=segment_summary,
        inner_nodes_summary=inner_nodes_summary,
    )


def run_step6_segment_aggregation_from_records(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    out_root: Union[str, Path],
    node_path: Union[str, Path],
    road_path: Union[str, Path],
    run_id: Optional[str] = None,
    debug: bool = True,
    node_properties_map: Optional[dict[str, dict[str, Any]]] = None,
    road_properties_map: Optional[dict[str, dict[str, Any]]] = None,
    mainnode_groups: Optional[dict[str, MainnodeGroup]] = None,
    group_to_allowed_road_ids: Optional[dict[str, set[str]]] = None,
) -> Step6Artifacts:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)

    effective_road_properties_map = (
        {road.road_id: road.properties for road in roads}
        if road_properties_map is None
        else road_properties_map
    )
    advance_right_assignment_summary = assign_advance_right_segments(
        roads=roads,
        road_properties_map=effective_road_properties_map,
    )

    _require_working_layers(
        nodes=nodes,
        roads=roads,
        stage_label="Step6",
        node_properties_map=node_properties_map,
        road_properties_map=effective_road_properties_map,
    )
    segment_records, skipped_segment_records, inner_nodes_by_segment = _collect_segment_records(
        nodes=nodes,
        roads=roads,
        node_properties_map=node_properties_map,
        road_properties_map=effective_road_properties_map,
        mainnode_groups=mainnode_groups,
        group_to_allowed_road_ids=group_to_allowed_road_ids,
    )
    return _write_step6_outputs(
        segment_records=segment_records,
        skipped_segment_records=skipped_segment_records,
        inner_nodes_by_segment=inner_nodes_by_segment,
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        input_node_path=node_path,
        input_road_path=road_path,
        debug=debug,
        advance_right_assignment_summary=advance_right_assignment_summary,
    )


def run_step6_segment_aggregation(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    out_root: Union[str, Path],
    run_id: Optional[str] = None,
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
    debug: bool = True,
) -> Step6Artifacts:
    (nodes, _, _), (roads, _) = _load_nodes_and_roads(
        node_path=node_path,
        road_path=road_path,
        node_layer=node_layer,
        node_crs=node_crs,
        road_layer=road_layer,
        road_crs=road_crs,
    )
    return run_step6_segment_aggregation_from_records(
        nodes=nodes,
        roads=roads,
        out_root=out_root,
        node_path=node_path,
        road_path=road_path,
        run_id=run_id,
        debug=debug,
    )


def run_step6_segment_aggregation_cli(args: argparse.Namespace) -> int:
    run_step6_segment_aggregation(
        road_path=args.road_path,
        node_path=args.node_path,
        out_root=args.out_root,
        run_id=args.run_id,
        road_layer=args.road_layer,
        road_crs=args.road_crs,
        node_layer=args.node_layer,
        node_crs=args.node_crs,
        debug=args.debug,
    )
    return 0
