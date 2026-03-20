from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    read_vector_layers_parallel,
    write_csv,
    write_geojson,
    write_json,
)


WORKING_NODE_FIELDS = ("grade_2", "kind_2")
WORKING_ROAD_FIELDS = ("s_grade", "segmentid")
ACTIVE_CLOSED_CON_VALUES = frozenset({2, 3})
EXCLUDED_ROAD_KIND_VALUE = 1
MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0
MAX_SIDE_ACCESS_DISTANCE_M = 50.0
ROUNDABOUT_ROADTYPE_BIT = 3
ROUNDABOUT_KIND_VALUE = 64
FULL_THROUGH_KIND_VALUES = frozenset({4, ROUNDABOUT_KIND_VALUE})
FULL_THROUGH_OR_T_KIND_VALUES = frozenset({4, ROUNDABOUT_KIND_VALUE, 2048})
WorkingLayerProgressCallback = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class WorkingLayerArtifacts:
    out_root: Path
    nodes_path: Path
    roads_path: Path
    summary_path: Path
    roundabout_summary_path: Path
    summary: dict[str, Any]


@dataclass(frozen=True)
class RoundaboutGroup:
    group_id: str
    mainnode_id: str
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return None if stripped == "" else stripped
    return value


def _coerce_int(value: Any) -> Optional[int]:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    if isinstance(normalized, bool):
        return int(normalized)
    if isinstance(normalized, int):
        return normalized
    if isinstance(normalized, float):
        return int(normalized)
    return int(str(normalized), 10)


def _normalize_id(value: Any) -> Optional[str]:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    if isinstance(normalized, int):
        return str(normalized)
    if isinstance(normalized, float) and normalized.is_integer():
        return str(int(normalized))
    return str(normalized)


def _normalize_nullable_text(value: Any) -> Optional[str]:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    return str(normalized)


def _sort_key(value: str) -> tuple[int, Union[int, str]]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _bit_enabled(value: Optional[int], bit_index: int) -> bool:
    if value is None:
        return False
    return bool(value & (1 << bit_index))


def is_roundabout_mainnode_kind(kind_2: Optional[int]) -> bool:
    return kind_2 == ROUNDABOUT_KIND_VALUE


def is_active_closed_con(closed_con: Optional[int]) -> bool:
    return closed_con in ACTIVE_CLOSED_CON_VALUES


def is_allowed_road_kind(road_kind: Optional[int]) -> bool:
    return road_kind != EXCLUDED_ROAD_KIND_VALUE


def is_full_through_kind(kind_2: Optional[int]) -> bool:
    return kind_2 in FULL_THROUGH_KIND_VALUES


def is_full_through_or_t_kind(kind_2: Optional[int]) -> bool:
    return kind_2 in FULL_THROUGH_OR_T_KIND_VALUES


def _emit_progress(
    progress_callback: Optional[WorkingLayerProgressCallback],
    event: str,
    **payload: Any,
) -> None:
    if progress_callback is None:
        return
    progress_callback(event, payload)


def _initialize_node_properties(props: dict[str, Any]) -> dict[str, Any]:
    initialized = dict(props)
    existing_grade_2 = _coerce_int(initialized.get("grade_2"))
    existing_kind_2 = _coerce_int(initialized.get("kind_2"))
    initialized["grade_2"] = existing_grade_2 if existing_grade_2 is not None else _coerce_int(initialized.get("grade"))
    initialized["kind_2"] = existing_kind_2 if existing_kind_2 is not None else _coerce_int(initialized.get("kind"))
    return initialized


def _initialize_road_properties(props: dict[str, Any]) -> dict[str, Any]:
    initialized = dict(props)
    initialized["s_grade"] = _normalize_nullable_text(initialized.get("s_grade"))
    initialized["segmentid"] = _normalize_nullable_text(initialized.get("segmentid"))
    return initialized


def _empty_roundabout_summary(*, out_root: Path) -> dict[str, Any]:
    return {
        "out_root": str(out_root.resolve()),
        "roundabout_roadtype_bit": ROUNDABOUT_ROADTYPE_BIT,
        "roundabout_kind_value": ROUNDABOUT_KIND_VALUE,
        "roundabout_road_count": 0,
        "roundabout_group_count": 0,
        "roundabout_mainnode_count": 0,
        "roundabout_member_node_count": 0,
        "roundabout_kind64_count": 0,
        "roundabout_member_zeroed_count": 0,
        "roadtype_missing_count": 0,
        "roadtype_empty_count": 0,
        "roadtype_invalid_count": 0,
    }


def _build_roundabout_groups(
    *,
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
) -> tuple[list[RoundaboutGroup], list[dict[str, Any]], dict[str, Any]]:
    node_index_by_id: dict[str, int] = {}
    for index, feature in enumerate(node_features):
        node_id = _normalize_id(feature["properties"].get("id"))
        if node_id is None:
            raise ValueError("Working node feature is missing required field 'id'.")
        node_index_by_id[node_id] = index

    roundabout_roads: dict[str, dict[str, Any]] = {}
    roadtype_issue_rows: list[dict[str, Any]] = []
    roadtype_missing_count = 0
    roadtype_empty_count = 0
    roadtype_invalid_count = 0

    for feature in road_features:
        props = feature["properties"]
        road_id = _normalize_id(props.get("id"))
        if road_id is None:
            raise ValueError("Working road feature is missing required field 'id'.")

        snodeid = _normalize_id(props.get("snodeid"))
        enodeid = _normalize_id(props.get("enodeid"))
        if snodeid is None or enodeid is None:
            raise ValueError(f"Working road '{road_id}' is missing snodeid or enodeid.")

        if "roadtype" not in props:
            roadtype_missing_count += 1
            roadtype_issue_rows.append({"road_id": road_id, "issue": "missing", "roadtype_raw": None})
            continue

        normalized_roadtype = _normalize_scalar(props.get("roadtype"))
        if normalized_roadtype is None:
            roadtype_empty_count += 1
            roadtype_issue_rows.append({"road_id": road_id, "issue": "empty", "roadtype_raw": props.get("roadtype")})
            continue

        try:
            roadtype = _coerce_int(normalized_roadtype)
        except Exception:
            roadtype_invalid_count += 1
            roadtype_issue_rows.append({"road_id": road_id, "issue": "invalid", "roadtype_raw": props.get("roadtype")})
            continue

        if not _bit_enabled(roadtype, ROUNDABOUT_ROADTYPE_BIT):
            continue

        for node_id in (snodeid, enodeid):
            if node_id not in node_index_by_id:
                raise ValueError(f"Roundabout road '{road_id}' references missing node '{node_id}'.")

        roundabout_roads[road_id] = {
            "road_id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "roadtype": roadtype,
            "feature": feature,
        }

    node_to_roundabout_road_ids: dict[str, set[str]] = defaultdict(set)
    for road in roundabout_roads.values():
        node_to_roundabout_road_ids[road["snodeid"]].add(road["road_id"])
        node_to_roundabout_road_ids[road["enodeid"]].add(road["road_id"])

    groups: list[RoundaboutGroup] = []
    visited: set[str] = set()
    for seed_road_id in sorted(roundabout_roads, key=_sort_key):
        if seed_road_id in visited:
            continue
        queue: deque[str] = deque([seed_road_id])
        component_road_ids: set[str] = set()
        component_node_ids: set[str] = set()

        while queue:
            road_id = queue.popleft()
            if road_id in visited:
                continue
            visited.add(road_id)
            road = roundabout_roads[road_id]
            component_road_ids.add(road_id)
            component_node_ids.add(road["snodeid"])
            component_node_ids.add(road["enodeid"])
            for node_id in (road["snodeid"], road["enodeid"]):
                for neighbor_road_id in sorted(node_to_roundabout_road_ids[node_id], key=_sort_key):
                    if neighbor_road_id not in visited:
                        queue.append(neighbor_road_id)

        if not component_node_ids:
            continue
        sorted_node_ids = tuple(sorted(component_node_ids, key=_sort_key))
        mainnode_id = sorted_node_ids[0]
        groups.append(
            RoundaboutGroup(
                group_id=f"roundabout_{mainnode_id}",
                mainnode_id=mainnode_id,
                road_ids=tuple(sorted(component_road_ids, key=_sort_key)),
                node_ids=sorted_node_ids,
            )
        )

    summary = {
        "roundabout_roadtype_bit": ROUNDABOUT_ROADTYPE_BIT,
        "roundabout_kind_value": ROUNDABOUT_KIND_VALUE,
        "roundabout_road_count": len(roundabout_roads),
        "roundabout_group_count": len(groups),
        "roundabout_mainnode_count": len(groups),
        "roundabout_member_node_count": sum(max(0, len(group.node_ids) - 1) for group in groups),
        "roundabout_kind64_count": len(groups),
        "roundabout_member_zeroed_count": sum(max(0, len(group.node_ids) - 1) for group in groups),
        "roadtype_missing_count": roadtype_missing_count,
        "roadtype_empty_count": roadtype_empty_count,
        "roadtype_invalid_count": roadtype_invalid_count,
    }
    return groups, roadtype_issue_rows, summary


def _write_roundabout_audits(
    *,
    out_root: Path,
    groups: list[RoundaboutGroup],
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    roadtype_issue_rows: list[dict[str, Any]],
    summary: dict[str, Any],
    debug: bool,
) -> Path:
    summary_path = out_root / "roundabout_summary.json"
    write_json(summary_path, summary)

    if not debug:
        return summary_path

    node_feature_by_id = {
        _normalize_id(feature["properties"].get("id")): feature
        for feature in node_features
    }
    road_feature_by_id = {
        _normalize_id(feature["properties"].get("id")): feature
        for feature in road_features
    }

    group_road_features: list[dict[str, Any]] = []
    group_node_features: list[dict[str, Any]] = []
    mainnode_features: list[dict[str, Any]] = []
    group_table_rows: list[dict[str, Any]] = []

    for group in groups:
        for road_id in group.road_ids:
            feature = road_feature_by_id[road_id]
            props = dict(feature["properties"])
            props["group_id"] = group.group_id
            props["mainnode_id"] = group.mainnode_id
            group_road_features.append({"properties": props, "geometry": feature["geometry"]})

        for node_id in group.node_ids:
            feature = node_feature_by_id[node_id]
            props = dict(feature["properties"])
            props["group_id"] = group.group_id
            props["mainnode_id"] = group.mainnode_id
            props["is_mainnode"] = node_id == group.mainnode_id
            group_node_features.append({"properties": props, "geometry": feature["geometry"]})
            if node_id == group.mainnode_id:
                mainnode_features.append({"properties": props, "geometry": feature["geometry"]})

        group_table_rows.append(
            {
                "group_id": group.group_id,
                "mainnode_id": group.mainnode_id,
                "road_count": len(group.road_ids),
                "node_count": len(group.node_ids),
                "member_node_ids": ",".join(group.node_ids),
            }
        )

    write_geojson(out_root / "roundabout_group_roads.geojson", group_road_features)
    write_geojson(out_root / "roundabout_group_nodes.geojson", group_node_features)
    write_geojson(out_root / "roundabout_mainnodes.geojson", mainnode_features)
    write_csv(
        out_root / "roundabout_group_table.csv",
        group_table_rows,
        ["group_id", "mainnode_id", "road_count", "node_count", "member_node_ids"],
    )
    write_csv(
        out_root / "roundabout_roadtype_issues.csv",
        roadtype_issue_rows,
        ["road_id", "issue", "roadtype_raw"],
    )
    return summary_path


def _apply_roundabout_preprocess(
    *,
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    out_root: Path,
    debug: bool,
    progress_callback: Optional[WorkingLayerProgressCallback],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Path, dict[str, Any]]:
    _emit_progress(progress_callback, "roundabout_preprocess_started")
    groups, roadtype_issue_rows, roundabout_summary = _build_roundabout_groups(
        node_features=node_features,
        road_features=road_features,
    )
    roundabout_summary = {
        **_empty_roundabout_summary(out_root=out_root),
        **roundabout_summary,
        "group_ids": [group.group_id for group in groups],
    }

    if groups:
        node_index_by_id = {
            _normalize_id(feature["properties"].get("id")): index
            for index, feature in enumerate(node_features)
        }
        for group in groups:
            for node_id in group.node_ids:
                index = node_index_by_id[node_id]
                current_feature = node_features[index]
                props = dict(current_feature["properties"])
                props["mainnodeid"] = group.mainnode_id
                if node_id == group.mainnode_id:
                    props["grade_2"] = 1
                    props["kind_2"] = ROUNDABOUT_KIND_VALUE
                else:
                    props["grade_2"] = 0
                    props["kind_2"] = 0
                node_features[index] = {"properties": props, "geometry": current_feature["geometry"]}

    summary_path = _write_roundabout_audits(
        out_root=out_root,
        groups=groups,
        node_features=node_features,
        road_features=road_features,
        roadtype_issue_rows=roadtype_issue_rows,
        summary=roundabout_summary,
        debug=debug,
    )
    _emit_progress(
        progress_callback,
        "roundabout_preprocess_completed",
        roundabout_group_count=roundabout_summary["roundabout_group_count"],
        roundabout_mainnode_count=roundabout_summary["roundabout_mainnode_count"],
        roundabout_road_count=roundabout_summary["roundabout_road_count"],
    )
    return node_features, road_features, summary_path, roundabout_summary


def _apply_intersection_preprocess_hook(
    *,
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    out_root: Path,
    debug: bool,
    progress_callback: Optional[WorkingLayerProgressCallback],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Path, dict[str, Any]]:
    return _apply_roundabout_preprocess(
        node_features=node_features,
        road_features=road_features,
        out_root=out_root,
        debug=debug,
        progress_callback=progress_callback,
    )


def initialize_working_layers(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    out_root: Union[str, Path],
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
    node_output_name: str = "nodes.geojson",
    road_output_name: str = "roads.geojson",
    summary_name: str = "working_layers_summary.json",
    debug: bool = True,
    progress_callback: Optional[WorkingLayerProgressCallback] = None,
) -> WorkingLayerArtifacts:
    resolved_out_root = Path(out_root)
    resolved_out_root.mkdir(parents=True, exist_ok=True)
    _emit_progress(progress_callback, "working_layers_read_started")
    road_layer_result, node_layer_result = read_vector_layers_parallel(
        first_path=road_path,
        second_path=node_path,
        first_layer=road_layer,
        second_layer=node_layer,
        first_crs=road_crs,
        second_crs=node_crs,
    )
    _emit_progress(
        progress_callback,
        "working_layers_read_completed",
        road_feature_count=len(road_layer_result.features),
        node_feature_count=len(node_layer_result.features),
    )

    initialized_nodes = [
        {
            "properties": _initialize_node_properties(feature.properties),
            "geometry": feature.geometry,
        }
        for feature in node_layer_result.features
    ]
    initialized_roads = [
        {
            "properties": _initialize_road_properties(feature.properties),
            "geometry": feature.geometry,
        }
        for feature in road_layer_result.features
    ]

    initialized_nodes, initialized_roads, roundabout_summary_path, roundabout_summary = _apply_intersection_preprocess_hook(
        node_features=initialized_nodes,
        road_features=initialized_roads,
        out_root=resolved_out_root,
        debug=debug,
        progress_callback=progress_callback,
    )
    _emit_progress(
        progress_callback,
        "working_layers_initialized",
        road_feature_count=len(initialized_roads),
        node_feature_count=len(initialized_nodes),
    )

    nodes_path = resolved_out_root / node_output_name
    roads_path = resolved_out_root / road_output_name
    summary_path = resolved_out_root / summary_name

    write_geojson(nodes_path, initialized_nodes)
    write_geojson(roads_path, initialized_roads)

    summary = {
        "out_root": str(resolved_out_root.resolve()),
        "input_node_path": str(Path(node_path).resolve()),
        "input_road_path": str(Path(road_path).resolve()),
        "node_feature_count": len(initialized_nodes),
        "road_feature_count": len(initialized_roads),
        "working_node_fields": list(WORKING_NODE_FIELDS),
        "working_road_fields": list(WORKING_ROAD_FIELDS),
        "node_initialization_rule": {"grade_2": "grade", "kind_2": "kind"},
        "road_initialization_rule": {"s_grade": None, "segmentid": None},
        "intersection_preprocess_hook": "roundabout_preprocess_v1",
        "roundabout_summary_path": str(roundabout_summary_path.resolve()),
        "roundabout_summary": roundabout_summary,
        "nodes_path": str(nodes_path.resolve()),
        "roads_path": str(roads_path.resolve()),
        "debug": debug,
    }
    write_json(summary_path, summary)
    _emit_progress(
        progress_callback,
        "working_layers_written",
        road_feature_count=len(initialized_roads),
        node_feature_count=len(initialized_nodes),
        nodes_path=str(nodes_path),
        roads_path=str(roads_path),
    )
    return WorkingLayerArtifacts(
        out_root=resolved_out_root,
        nodes_path=nodes_path,
        roads_path=roads_path,
        summary_path=summary_path,
        roundabout_summary_path=roundabout_summary_path,
        summary=summary,
    )


def require_initialized_working_features(
    *,
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    stage_label: str,
) -> None:
    issues: list[str] = []
    for index, feature in enumerate(node_features):
        properties = feature["properties"]
        missing = [field for field in WORKING_NODE_FIELDS if field not in properties]
        if missing:
            issues.append(f"{stage_label} node feature[{index}] missing working fields: {', '.join(missing)}")

    for index, feature in enumerate(road_features):
        properties = feature["properties"]
        missing = [field for field in WORKING_ROAD_FIELDS if field not in properties]
        if missing:
            issues.append(f"{stage_label} road feature[{index}] missing working fields: {', '.join(missing)}")

    if issues:
        raise ValueError("; ".join(issues))


def require_initialized_working_geojson(
    *,
    node_path: Union[str, Path],
    road_path: Union[str, Path],
    stage_label: str,
) -> None:
    def _load(path: Path) -> list[dict[str, Any]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("features") or [])

    require_initialized_working_features(
        node_features=_load(Path(node_path)),
        road_features=_load(Path(road_path)),
        stage_label=stage_label,
    )
