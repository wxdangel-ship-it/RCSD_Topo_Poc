from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from shapely.geometry import LineString, MultiLineString

from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    MainnodeGroup,
    NodeFeatureRecord,
    RoadFeatureRecord,
    _build_mainnode_groups,
    _load_nodes_and_roads,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_geojson, write_json
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import _coerce_int, _find_repo_root, _sort_key
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    WORKING_NODE_FIELDS,
    WORKING_ROAD_FIELDS,
    is_allowed_road_kind,
)


DEFAULT_RUN_ID_PREFIX = "t01_step6_segment_aggregation_"
STEP6_SEGMENT_GRADE_VALUE = "0-0双"
STEP6_ERROR_TYPE_S_GRADE_CONFLICT = "s_grade_conflict"
STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT = "grade_kind_conflict"
STEP6_S_GRADE_PRIORITY_ORDER = ("0-0双", "0-1双", "0-2双")
STEP6_ERROR_LAYER_FILENAMES = {
    STEP6_ERROR_TYPE_S_GRADE_CONFLICT: "segment_error_s_grade_conflict.geojson",
    STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT: "segment_error_grade_kind_conflict.geojson",
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
    segment_id: str
    pair_nodes: tuple[str, str]
    road_ids: tuple[str, ...]
    multiline: MultiLineString
    s_grade_old: Optional[str]
    s_grade_new: Optional[str]
    junc_nodes: tuple[str, ...]
    inner_group_ids: tuple[str, ...]
    adjusted: bool
    adjust_reason: Optional[str]
    s_grade_conflict_values: tuple[str, ...]
    error_type: Optional[str]
    error_desc: Optional[str]


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
) -> None:
    issues: list[str] = []
    for index, node in enumerate(nodes):
        missing = [field for field in WORKING_NODE_FIELDS if field not in node.properties]
        if missing:
            issues.append(f"{stage_label} node feature[{index}] missing working fields: {', '.join(missing)}")
    for index, road in enumerate(roads):
        missing = [field for field in WORKING_ROAD_FIELDS if field not in road.properties]
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


def _build_group_to_allowed_road_ids(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
) -> dict[str, set[str]]:
    node_by_id = {node.node_id: node for node in nodes}
    group_to_allowed_road_ids: dict[str, set[str]] = defaultdict(set)
    for road in roads:
        if not is_allowed_road_kind(road.road_kind):
            continue
        for node_id in (road.snodeid, road.enodeid):
            node = node_by_id.get(node_id)
            if node is None:
                raise ValueError(f"Road '{road.road_id}' references missing node '{node_id}'.")
            group_to_allowed_road_ids[node.semantic_node_id].add(road.road_id)
    return group_to_allowed_road_ids


def _collect_segment_records(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
) -> tuple[list[SegmentRecord], dict[str, list[NodeFeatureRecord]]]:
    node_by_id = {node.node_id: node for node in nodes}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    mainnode_groups, _ = _build_mainnode_groups(node_by_id, groups)

    roads_by_segment_id: dict[str, list[RoadFeatureRecord]] = defaultdict(list)
    for road in roads:
        segment_id = _normalize_text(road.properties.get("segmentid"))
        if segment_id is None:
            continue
        roads_by_segment_id[segment_id].append(road)

    group_to_allowed_road_ids = _build_group_to_allowed_road_ids(nodes=nodes, roads=roads)
    inner_nodes_by_segment: dict[str, list[NodeFeatureRecord]] = defaultdict(list)
    segment_records: list[SegmentRecord] = []

    for segment_id in sorted(roads_by_segment_id, key=_segment_sort_key):
        segment_roads = roads_by_segment_id[segment_id]
        pair_nodes = _parse_segment_pair_nodes(segment_id)
        road_ids = tuple(sorted({road.road_id for road in segment_roads}, key=_sort_key))

        s_grade_values = {
            _normalize_text(road.properties.get("s_grade"))
            for road in segment_roads
        }
        s_grade_conflict_values = tuple(sorted(_display_optional_value(value) for value in s_grade_values))
        if len(s_grade_values) == 1:
            s_grade_old = next(iter(s_grade_values))
            s_grade_new = s_grade_old
            adjusted = False
            adjust_reason = None
            error_type: Optional[str] = None
            error_desc: Optional[str] = None
        else:
            s_grade_old = _join_optional_values(s_grade_conflict_values)
            s_grade_new = _resolve_highest_s_grade(s_grade_conflict_values)
            adjusted = False
            adjust_reason = None
            error_type = STEP6_ERROR_TYPE_S_GRADE_CONFLICT
            error_desc = (
                "segment contains multiple s_grade values: "
                + ",".join(s_grade_conflict_values)
                + f"; selected highest priority='{_display_optional_value(s_grade_new)}'"
            )

        flattened_lines: list[LineString] = []
        covered_group_ids: set[str] = set()
        for road in segment_roads:
            flattened_lines.extend(_flatten_lines(road.geometry))
            snode = node_by_id.get(road.snodeid)
            enode = node_by_id.get(road.enodeid)
            if snode is None or enode is None:
                raise ValueError(f"Segment road '{road.road_id}' references missing endpoint node.")
            covered_group_ids.add(snode.semantic_node_id)
            covered_group_ids.add(enode.semantic_node_id)
        multiline = MultiLineString(flattened_lines)

        inner_group_ids: list[str] = []
        junc_nodes: list[str] = []
        road_id_set = set(road_ids)
        for semantic_node_id in sorted(covered_group_ids, key=_sort_key):
            if semantic_node_id in pair_nodes:
                continue
            allowed_road_ids = group_to_allowed_road_ids.get(semantic_node_id, set())
            if allowed_road_ids and allowed_road_ids.issubset(road_id_set):
                inner_group_ids.append(semantic_node_id)
                member_ids = mainnode_groups[semantic_node_id].member_node_ids
                for node_id in member_ids:
                    inner_nodes_by_segment[segment_id].append(node_by_id[node_id])
                continue
            junc_nodes.append(semantic_node_id)

        pair_grade_values: list[Optional[int]] = []
        for pair_node_id in pair_nodes:
            group = mainnode_groups.get(pair_node_id)
            if group is None:
                raise ValueError(f"Step6 segment '{segment_id}' endpoint '{pair_node_id}' does not exist in node groups.")
            representative = node_by_id[group.representative_node_id]
            pair_grade_values.append(_current_grade_2(representative))

        if error_type is None and pair_grade_values == [1, 1] and s_grade_old != STEP6_SEGMENT_GRADE_VALUE:
            adjusted = True
            s_grade_new = STEP6_SEGMENT_GRADE_VALUE
            adjust_reason = "both_pair_nodes_grade_2_eq_1"

        if s_grade_new == STEP6_SEGMENT_GRADE_VALUE:
            conflicting_nodes: list[str] = []
            for semantic_node_id in junc_nodes:
                group = mainnode_groups.get(semantic_node_id)
                if group is None:
                    continue
                representative = node_by_id[group.representative_node_id]
                if _current_grade_2(representative) == 1 and _current_kind_2(representative) == 4:
                    conflicting_nodes.append(semantic_node_id)
            if conflicting_nodes:
                error_type = STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT
                error_desc = (
                    "s_grade='0-0双' segment contains junc_nodes with grade_2=1 and kind_2=4: "
                    + ",".join(conflicting_nodes)
                )

        segment_records.append(
            SegmentRecord(
                segment_id=segment_id,
                pair_nodes=pair_nodes,
                road_ids=road_ids,
                multiline=multiline,
                s_grade_old=s_grade_old,
                s_grade_new=s_grade_new,
                junc_nodes=tuple(sorted(set(junc_nodes), key=_sort_key)),
                inner_group_ids=tuple(sorted(set(inner_group_ids), key=_sort_key)),
                adjusted=adjusted,
                adjust_reason=adjust_reason,
                s_grade_conflict_values=s_grade_conflict_values,
                error_type=error_type,
                error_desc=error_desc,
            )
        )

    return segment_records, inner_nodes_by_segment


def _segment_feature(record: SegmentRecord) -> dict[str, Any]:
    return {
        "properties": {
            "id": record.segment_id,
            "s_grade": record.s_grade_new,
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
            "s_grade": record.s_grade_new,
            "pair_nodes": _join_ids(record.pair_nodes),
            "junc_nodes": _join_ids(record.junc_nodes),
            "roads": _join_ids(record.road_ids),
            "error_type": record.error_type,
            "error_desc": record.error_desc,
            "old_s_grade": record.s_grade_old,
            "new_s_grade": record.s_grade_new,
            "s_grade_conflict_values": _join_ids(record.s_grade_conflict_values),
            "flag_s_grade_conflict": record.error_type == STEP6_ERROR_TYPE_S_GRADE_CONFLICT,
            "flag_grade_kind_conflict": record.error_type == STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT,
        },
        "geometry": record.multiline,
    }


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
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)

    (nodes, _, _), (roads, _) = _load_nodes_and_roads(
        node_path=node_path,
        road_path=road_path,
        node_layer=node_layer,
        node_crs=node_crs,
        road_layer=road_layer,
        road_crs=road_crs,
    )
    _require_working_layers(nodes=nodes, roads=roads, stage_label="Step6")

    segment_records, inner_nodes_by_segment = _collect_segment_records(nodes=nodes, roads=roads)

    segment_path = resolved_out_root / "segment.geojson"
    inner_nodes_path = resolved_out_root / "inner_nodes.geojson"
    segment_error_path = resolved_out_root / "segment_error.geojson"
    error_layer_paths = {
        error_type: resolved_out_root / filename
        for error_type, filename in STEP6_ERROR_LAYER_FILENAMES.items()
    }
    segment_summary_path = resolved_out_root / "segment_summary.json"
    segment_build_table_path = resolved_out_root / "segment_build_table.csv"
    inner_nodes_summary_path = resolved_out_root / "inner_nodes_summary.json"

    write_geojson(segment_path, (_segment_feature(record) for record in segment_records))

    inner_node_features: list[dict[str, Any]] = []
    inner_group_ids_all: set[str] = set()
    inner_segment_ids: set[str] = set()
    for segment_id, inner_nodes in sorted(inner_nodes_by_segment.items(), key=lambda item: _segment_sort_key(item[0])):
        if not inner_nodes:
            continue
        inner_segment_ids.add(segment_id)
        for node in inner_nodes:
            inner_group_ids_all.add(node.semantic_node_id)
            props = dict(node.properties)
            props["segmentid"] = segment_id
            inner_node_features.append({"properties": props, "geometry": node.geometry})
    write_geojson(inner_nodes_path, inner_node_features)

    segment_error_records = [record for record in segment_records if record.error_type is not None]
    write_geojson(segment_error_path, (_segment_error_feature(record) for record in segment_error_records))
    for error_type, error_path in error_layer_paths.items():
        matching_records = [record for record in segment_error_records if record.error_type == error_type]
        write_geojson(error_path, (_segment_error_feature(record) for record in matching_records))

    segment_summary = {
        "run_id": resolved_run_id,
        "debug": debug,
        "input_node_path": str(Path(node_path)),
        "input_road_path": str(Path(road_path)),
        "segment_count": len(segment_records),
        "segment_with_junc_count": sum(1 for record in segment_records if record.junc_nodes),
        "segment_with_inner_nodes_count": sum(1 for record in segment_records if record.inner_group_ids),
        "segment_error_count": len(segment_error_records),
        "s_grade_adjusted_count": sum(1 for record in segment_records if record.adjusted),
        "s_grade_conflict_count": sum(
            1 for record in segment_records if record.error_type == STEP6_ERROR_TYPE_S_GRADE_CONFLICT
        ),
        "grade_kind_conflict_count": sum(
            1 for record in segment_records if record.error_type == STEP6_ERROR_TYPE_GRADE_KIND_CONFLICT
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

    build_rows = [
        {
            "segmentid": record.segment_id,
            "road_count": len(record.road_ids),
            "pair_nodes": _join_ids(record.pair_nodes),
            "junc_nodes": _join_ids(record.junc_nodes),
            "road_ids": _join_ids(record.road_ids),
            "s_grade_old": record.s_grade_old,
            "s_grade_new": record.s_grade_new,
            "s_grade_conflict_values": _join_ids(record.s_grade_conflict_values),
            "adjust_reason": record.adjust_reason,
            "error_type": record.error_type,
            "has_error": record.error_type is not None,
        }
        for record in segment_records
    ]
    write_csv(
        segment_build_table_path,
        build_rows,
        [
            "segmentid",
            "road_count",
            "pair_nodes",
            "junc_nodes",
            "road_ids",
            "s_grade_old",
            "s_grade_new",
            "s_grade_conflict_values",
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
