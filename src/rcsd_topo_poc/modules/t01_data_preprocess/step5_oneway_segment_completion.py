from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    first_existing_vector_path,
    write_csv,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import (
    RIGHT_TURN_FORMWAY_BIT,
    MainnodeGroup,
    NodeFeatureRecord,
    RoadFeatureRecord,
    _allocate_unique_segmentid,
    _build_mainnode_groups,
    _load_nodes_and_roads,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    _coerce_int,
    _find_repo_root,
    _sort_key,
)
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    canonicalize_road_working_properties,
    get_road_segmentid,
    get_road_sgrade,
    is_allowed_road_kind,
    set_road_segmentid,
    set_road_sgrade,
)


DEFAULT_RUN_ID_PREFIX = "t01_step5_oneway_segment_completion_"
FORMWAY_EXCLUDED_VALUE = 128
FORMWAY_UNSEGMENTED_AUDIT_BITS = (7, 8)
ONEWAY_SEGMENT_OUTPUT_NAME = "oneway_segment_roads.gpkg"
ONEWAY_SEGMENT_BUILD_TABLE_NAME = "oneway_segment_build_table.csv"
ONEWAY_SEGMENT_SUMMARY_NAME = "oneway_segment_summary.json"
UNSEGMENTED_ROADS_PATH_NAME = "unsegmented_roads.gpkg"
UNSEGMENTED_ROADS_CSV_NAME = "unsegmented_roads.csv"
UNSEGMENTED_ROADS_SUMMARY_NAME = "unsegmented_roads_summary.json"
DEAD_END_PHASE_ID = "dead-end-leaf"
DEAD_END_SEGMENT_GRADE = "0-2双"
DEAD_END_BUILD_SOURCE = "dead_end_leaf"
DEAD_END_BIDIRECTIONAL_BUNDLE_TYPE = "bidirectional"
DEAD_END_ONEWAY_PAIR_BUNDLE_TYPE = "reciprocal_oneway"
FINAL_FALLBACK_PHASE_ID = "oneway-single-road-fallback"
FINAL_FALLBACK_SEGMENT_GRADE = "0-2单"
FINAL_FALLBACK_BUILD_SOURCE = "oneway_single_road_fallback"
DEAD_END_ANCHOR_KIND_VALUES = frozenset({4, 64, 128, 2048})
DEAD_END_ANCHOR_GRADE_VALUES = frozenset({1, 2, 3})
DEAD_END_ANCHOR_CLOSED_CON_VALUES = frozenset({2, 3})
STEP5_CONTINUATION_MARKER_NAMES = (
    "step5_summary.json",
    "step5_validated_pairs_merged.csv",
)


@dataclass(frozen=True)
class OnewayPhaseSpec:
    phase_id: str
    sgrade: str
    closed_con_values: frozenset[int]
    kind_values: frozenset[int]
    grade_values: frozenset[int]


@dataclass(frozen=True)
class OnewayTraversalEdge:
    road_id: str
    from_node_id: str
    to_node_id: str
    uses_forward_geometry: bool


@dataclass(frozen=True)
class OnewayBuiltSegment:
    phase_id: str
    sgrade: str
    start_node_id: str
    end_node_id: str
    segmentid: str
    road_ids: tuple[str, ...]
    through_node_ids: tuple[str, ...]
    segment_build_source: Optional[str] = None
    leaf_node_id: Optional[str] = None
    dead_end_bundle_type: Optional[str] = None


@dataclass(frozen=True)
class OnewaySegmentArtifacts:
    out_root: Path
    refreshed_nodes_path: Path
    refreshed_roads_path: Path
    segment_roads_path: Path
    build_table_path: Path
    summary_path: Path
    unsegmented_roads_path: Path
    unsegmented_csv_path: Path
    unsegmented_summary_path: Path
    summary: dict[str, Any]
    step6_nodes: tuple[NodeFeatureRecord, ...]
    step6_roads: tuple[RoadFeatureRecord, ...]
    step6_node_properties_map: dict[str, dict[str, Any]]
    step6_road_properties_map: dict[str, dict[str, Any]]
    step6_mainnode_groups: dict[str, MainnodeGroup]
    step6_group_to_allowed_road_ids: dict[str, set[str]]


@dataclass(frozen=True)
class OnewayStep5InputArtifacts:
    refreshed_nodes_path: Path
    refreshed_roads_path: Path
    step6_nodes: tuple[NodeFeatureRecord, ...]
    step6_roads: tuple[RoadFeatureRecord, ...]
    step6_node_properties_map: dict[str, dict[str, Any]]
    step6_road_properties_map: dict[str, dict[str, Any]]
    step6_mainnode_groups: dict[str, MainnodeGroup]
    step6_group_to_allowed_road_ids: dict[str, set[str]]


@dataclass(frozen=True)
class _TraceResult:
    start_node_id: str
    end_node_id: str
    road_ids: tuple[str, ...]
    through_node_ids: tuple[str, ...]


def _build_default_run_id() -> str:
    from datetime import datetime

    return f"{DEFAULT_RUN_ID_PREFIX}{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or _build_default_run_id()
    if out_root is not None:
        return Path(out_root), resolved_run_id

    repo_root = _find_repo_root(Path.cwd() if cwd is None else cwd)
    if repo_root is None:
        raise ValueError("Cannot infer default out_root because repo root was not found; please pass --out-root.")
    return repo_root / "outputs" / "_work" / "t01_step5_oneway_segment_completion" / resolved_run_id, resolved_run_id


def _build_oneway_phase_specs() -> tuple[OnewayPhaseSpec, ...]:
    return (
        OnewayPhaseSpec(
            phase_id="0-0单",
            sgrade="0-0单",
            closed_con_values=frozenset({1, 3}),
            kind_values=frozenset({8, 16}),
            grade_values=frozenset({1}),
        ),
        OnewayPhaseSpec(
            phase_id="0-1单",
            sgrade="0-1单",
            closed_con_values=frozenset({2, 3}),
            kind_values=frozenset({4, 8, 16, 64, 128, 2048}),
            grade_values=frozenset({1, 2}),
        ),
        OnewayPhaseSpec(
            phase_id="0-2单",
            sgrade="0-2单",
            closed_con_values=frozenset({2, 3}),
            kind_values=frozenset({4, 8, 16, 64, 128, 2048}),
            grade_values=frozenset({1, 2, 3}),
        ),
    )


def build_step5_input_artifacts_from_refreshed_paths(
    *,
    node_path: Union[str, Path],
    road_path: Union[str, Path],
) -> OnewayStep5InputArtifacts:
    resolved_node_path = Path(node_path)
    resolved_road_path = Path(road_path)
    (nodes, node_by_id, groups), (roads, _) = _load_nodes_and_roads(
        node_path=resolved_node_path,
        road_path=resolved_road_path,
    )
    mainnode_groups, _ = _build_mainnode_groups(node_by_id, groups)
    physical_to_semantic = _physical_to_semantic(mainnode_groups)
    road_properties_map = {
        road.road_id: canonicalize_road_working_properties(dict(road.properties))
        for road in roads
    }
    group_to_allowed_road_ids = _build_group_to_allowed_road_ids(
        roads=roads,
        road_properties_map=road_properties_map,
        physical_to_semantic=physical_to_semantic,
    )
    return OnewayStep5InputArtifacts(
        refreshed_nodes_path=resolved_node_path,
        refreshed_roads_path=resolved_road_path,
        step6_nodes=tuple(nodes),
        step6_roads=tuple(roads),
        step6_node_properties_map={node.node_id: dict(node.properties) for node in nodes},
        step6_road_properties_map=road_properties_map,
        step6_mainnode_groups=mainnode_groups,
        step6_group_to_allowed_road_ids=group_to_allowed_road_ids,
    )


def load_step5_input_artifacts_from_dir(input_dir: Union[str, Path]) -> OnewayStep5InputArtifacts:
    resolved_input_dir = Path(input_dir)
    has_step5_marker = any((resolved_input_dir / name).is_file() for name in STEP5_CONTINUATION_MARKER_NAMES)
    node_path = first_existing_vector_path(
        resolved_input_dir,
        "nodes.gpkg",
        "nodes.geojson",
        "nodes_step5_refreshed.gpkg",
        "nodes_step5_refreshed.geojson",
    )
    road_path = first_existing_vector_path(
        resolved_input_dir,
        "roads.gpkg",
        "roads.geojson",
        "roads_step5_refreshed.gpkg",
        "roads_step5_refreshed.geojson",
    )
    if not has_step5_marker:
        raise ValueError(
            "Continuation input directory must be a Step5 refreshed output directory and contain "
            f"at least one Step5 marker file {STEP5_CONTINUATION_MARKER_NAMES} (got '{resolved_input_dir}')."
        )
    if node_path is None or road_path is None:
        raise ValueError(
            "Continuation input directory must contain refreshed Step5 nodes/roads outputs "
            f"(got '{resolved_input_dir}')."
        )
    return build_step5_input_artifacts_from_refreshed_paths(
        node_path=node_path,
        road_path=road_path,
    )


def _current_grade_2(properties: dict[str, Any]) -> Optional[int]:
    return _coerce_int(properties.get("grade_2"))


def _current_kind_2(properties: dict[str, Any]) -> Optional[int]:
    return _coerce_int(properties.get("kind_2"))


def _current_closed_con(properties: dict[str, Any]) -> Optional[int]:
    return _coerce_int(properties.get("closed_con"))


def _coerce_formway(properties: dict[str, Any]) -> Optional[int]:
    return _coerce_int(properties.get("formway"))


def _is_formway_128(properties: dict[str, Any]) -> bool:
    return _coerce_formway(properties) == FORMWAY_EXCLUDED_VALUE


def _bit_enabled(value: Optional[int], bit_index: int) -> bool:
    if value is None:
        return False
    return bool(value & (1 << bit_index))


def _is_right_turn_only_road(properties: dict[str, Any]) -> bool:
    return _bit_enabled(_coerce_formway(properties), RIGHT_TURN_FORMWAY_BIT)


def _has_any_formway_bit(properties: dict[str, Any], bit_indexes: tuple[int, ...]) -> bool:
    formway = _coerce_formway(properties)
    return any(_bit_enabled(formway, bit_index) for bit_index in bit_indexes)


def _has_formway_bit7_or_bit8(properties: dict[str, Any]) -> bool:
    return _has_any_formway_bit(properties, FORMWAY_UNSEGMENTED_AUDIT_BITS)


def _is_oneway_direction(direction: int) -> bool:
    return direction in {2, 3}


def _is_oneway_sgrade(value: Optional[str]) -> bool:
    return value in {"0-0单", "0-1单", "0-2单"}


def _is_allowed_step6_incident_road(properties: dict[str, Any], road: RoadFeatureRecord) -> bool:
    road_kind = _coerce_int(properties.get("road_kind")) if "road_kind" in properties else road.road_kind
    if is_allowed_road_kind(road_kind):
        return True
    if properties.get("segment_build_source") == DEAD_END_BUILD_SOURCE and get_road_segmentid(properties) is not None:
        return True
    return _is_oneway_sgrade(get_road_sgrade(properties)) and get_road_segmentid(properties) is not None


def _build_mainnode_groups_fallback(nodes: list[NodeFeatureRecord]) -> dict[str, MainnodeGroup]:
    node_by_id = {node.node_id: node for node in nodes}
    groups: dict[str, list[str]] = {}
    for node in nodes:
        groups.setdefault(node.semantic_node_id, []).append(node.node_id)
    built_groups, _ = _build_mainnode_groups(node_by_id, groups)
    return built_groups


def _physical_to_semantic(mainnode_groups: dict[str, MainnodeGroup]) -> dict[str, str]:
    return {
        member_node_id: mainnode_id
        for mainnode_id, group in mainnode_groups.items()
        for member_node_id in group.member_node_ids
    }


def _build_group_to_allowed_road_ids(
    *,
    roads: list[RoadFeatureRecord],
    road_properties_map: dict[str, dict[str, Any]],
    physical_to_semantic: dict[str, str],
) -> dict[str, set[str]]:
    group_to_road_ids: dict[str, set[str]] = {}
    for road in roads:
        props = road_properties_map[road.road_id]
        if not _is_allowed_step6_incident_road(props, road):
            continue
        snode_group = physical_to_semantic.get(road.snodeid)
        enode_group = physical_to_semantic.get(road.enodeid)
        if snode_group is not None:
            group_to_road_ids.setdefault(snode_group, set()).add(road.road_id)
        if enode_group is not None:
            group_to_road_ids.setdefault(enode_group, set()).add(road.road_id)
    return group_to_road_ids


def _matches_phase_node(
    *,
    properties: dict[str, Any],
    phase: OnewayPhaseSpec,
) -> bool:
    kind_2 = _current_kind_2(properties)
    grade_2 = _current_grade_2(properties)
    closed_con = _current_closed_con(properties)
    return (
        kind_2 in phase.kind_values
        and grade_2 in phase.grade_values
        and closed_con in phase.closed_con_values
    )


def _matches_dead_end_anchor(properties: dict[str, Any]) -> bool:
    return (
        _current_kind_2(properties) in DEAD_END_ANCHOR_KIND_VALUES
        and _current_grade_2(properties) in DEAD_END_ANCHOR_GRADE_VALUES
        and _current_closed_con(properties) in DEAD_END_ANCHOR_CLOSED_CON_VALUES
    )


def _collect_dead_end_anchor_ids(
    *,
    nodes: list[NodeFeatureRecord],
    node_properties_map: dict[str, dict[str, Any]],
    mainnode_groups: dict[str, MainnodeGroup],
) -> set[str]:
    node_by_id = {node.node_id: node for node in nodes}
    anchor_ids: set[str] = set()
    for mainnode_id, group in mainnode_groups.items():
        representative = node_by_id.get(group.representative_node_id)
        if representative is None:
            continue
        props = node_properties_map.get(representative.node_id, representative.properties)
        if _matches_dead_end_anchor(props):
            anchor_ids.add(mainnode_id)
    return anchor_ids


def _collect_phase_terminate_ids(
    *,
    nodes: list[NodeFeatureRecord],
    node_properties_map: dict[str, dict[str, Any]],
    mainnode_groups: dict[str, MainnodeGroup],
    phase: OnewayPhaseSpec,
) -> set[str]:
    node_by_id = {node.node_id: node for node in nodes}
    terminate_ids: set[str] = set()
    for mainnode_id, group in mainnode_groups.items():
        representative = node_by_id.get(group.representative_node_id)
        if representative is None:
            continue
        props = node_properties_map.get(representative.node_id, representative.properties)
        if _matches_phase_node(properties=props, phase=phase):
            terminate_ids.add(mainnode_id)
    return terminate_ids


def _build_directed_adjacency(
    *,
    roads: list[RoadFeatureRecord],
    candidate_road_ids: set[str],
    physical_to_semantic: dict[str, str],
) -> dict[str, tuple[OnewayTraversalEdge, ...]]:
    adjacency_lists: dict[str, list[OnewayTraversalEdge]] = {}
    for road in roads:
        if road.road_id not in candidate_road_ids:
            continue
        snode_group = physical_to_semantic.get(road.snodeid, road.snodeid)
        enode_group = physical_to_semantic.get(road.enodeid, road.enodeid)
        if snode_group == enode_group:
            continue
        if road.direction in {0, 1, 2}:
            adjacency_lists.setdefault(snode_group, []).append(
                OnewayTraversalEdge(
                    road_id=road.road_id,
                    from_node_id=snode_group,
                    to_node_id=enode_group,
                    uses_forward_geometry=True,
                )
            )
        if road.direction in {0, 1, 3}:
            adjacency_lists.setdefault(enode_group, []).append(
                OnewayTraversalEdge(
                    road_id=road.road_id,
                    from_node_id=enode_group,
                    to_node_id=snode_group,
                    uses_forward_geometry=False,
                )
            )
    return {
        node_id: tuple(
            sorted(
                edges,
                key=lambda edge: (_sort_key(edge.to_node_id), _sort_key(edge.road_id)),
            )
        )
        for node_id, edges in adjacency_lists.items()
    }


def _normalize_line(geometry: BaseGeometry) -> Optional[LineString]:
    if isinstance(geometry, LineString):
        return geometry
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            return merged
        if isinstance(merged, MultiLineString) and merged.geoms:
            return max(merged.geoms, key=lambda geom: geom.length)
    return None


def _oriented_coords(edge: OnewayTraversalEdge, road: RoadFeatureRecord) -> list[tuple[float, float]]:
    line = _normalize_line(road.geometry)
    if line is None:
        return []
    coords = list(line.coords)
    if not edge.uses_forward_geometry:
        coords.reverse()
    return coords


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _departure_bearing(edge: OnewayTraversalEdge, road: RoadFeatureRecord) -> Optional[float]:
    coords = _oriented_coords(edge, road)
    for index in range(len(coords) - 1):
        if coords[index] != coords[index + 1]:
            return _bearing(coords[index], coords[index + 1])
    return None


def _arrival_bearing(edge: OnewayTraversalEdge, road: RoadFeatureRecord) -> Optional[float]:
    coords = _oriented_coords(edge, road)
    for index in range(len(coords) - 1, 0, -1):
        if coords[index - 1] != coords[index]:
            return _bearing(coords[index - 1], coords[index])
    return None


def _turn_angle(prev_bearing: Optional[float], next_bearing: Optional[float]) -> float:
    if prev_bearing is None or next_bearing is None:
        return math.pi
    delta = abs(next_bearing - prev_bearing) % (2.0 * math.pi)
    return min(delta, 2.0 * math.pi - delta)


def _select_min_angle_successor(
    *,
    current_edge: OnewayTraversalEdge,
    candidate_edges: tuple[OnewayTraversalEdge, ...],
    road_by_id: dict[str, RoadFeatureRecord],
) -> OnewayTraversalEdge:
    current_road = road_by_id[current_edge.road_id]
    current_bearing = _arrival_bearing(current_edge, current_road)
    return min(
        candidate_edges,
        key=lambda edge: (
            _turn_angle(current_bearing, _departure_bearing(edge, road_by_id[edge.road_id])),
            _sort_key(edge.to_node_id),
            _sort_key(edge.road_id),
        ),
    )


def _trace_oneway_segment_from_seed(
    *,
    start_node_id: str,
    first_edge: OnewayTraversalEdge,
    outgoing_adjacency: dict[str, tuple[OnewayTraversalEdge, ...]],
    terminate_ids: set[str],
    available_road_ids: set[str],
    road_by_id: dict[str, RoadFeatureRecord],
) -> Optional[_TraceResult]:
    if first_edge.road_id not in available_road_ids:
        return None

    road_ids: list[str] = []
    through_node_ids: list[str] = []
    visited_nodes = {start_node_id}
    visited_road_ids: set[str] = set()
    current_edge = first_edge
    current_node_id = first_edge.to_node_id

    while True:
        if current_edge.road_id not in available_road_ids or current_edge.road_id in visited_road_ids:
            return None
        if current_node_id in visited_nodes:
            return None

        road_ids.append(current_edge.road_id)
        visited_road_ids.add(current_edge.road_id)

        if current_node_id in terminate_ids:
            return _TraceResult(
                start_node_id=start_node_id,
                end_node_id=current_node_id,
                road_ids=tuple(road_ids),
                through_node_ids=tuple(through_node_ids),
            )

        visited_nodes.add(current_node_id)

        candidate_edges = tuple(
            edge
            for edge in outgoing_adjacency.get(current_node_id, ())
            if edge.road_id in available_road_ids
            and edge.road_id not in visited_road_ids
            and edge.to_node_id not in visited_nodes
        )
        if not candidate_edges:
            return None

        through_node_ids.append(current_node_id)
        if len(candidate_edges) == 1:
            current_edge = candidate_edges[0]
        else:
            current_edge = _select_min_angle_successor(
                current_edge=current_edge,
                candidate_edges=candidate_edges,
                road_by_id=road_by_id,
            )
        current_node_id = current_edge.to_node_id


def _collect_phase_candidate_road_ids(
    *,
    roads: list[RoadFeatureRecord],
    road_properties_map: dict[str, dict[str, Any]],
) -> set[str]:
    candidate_road_ids: set[str] = set()
    for road in roads:
        props = road_properties_map[road.road_id]
        if get_road_segmentid(props):
            continue
        if _is_formway_128(props):
            continue
        if _is_right_turn_only_road(props):
            continue
        if not _is_oneway_direction(road.direction):
            continue
        candidate_road_ids.add(road.road_id)
    return candidate_road_ids


def _is_dead_end_effective_road(road: RoadFeatureRecord, properties: dict[str, Any]) -> bool:
    if _is_formway_128(properties) or _is_right_turn_only_road(properties):
        return False
    if road.direction in {0, 1}:
        road_kind = _coerce_int(properties.get("road_kind")) if "road_kind" in properties else road.road_kind
        return is_allowed_road_kind(road_kind)
    return road.direction in {2, 3}


def _is_dead_end_candidate_road(road: RoadFeatureRecord, properties: dict[str, Any]) -> bool:
    return get_road_segmentid(properties) is None and _is_dead_end_effective_road(road, properties)


def _road_semantic_endpoints(
    road: RoadFeatureRecord,
    physical_to_semantic: dict[str, str],
) -> Optional[tuple[str, str]]:
    snode_group = physical_to_semantic.get(road.snodeid)
    enode_group = physical_to_semantic.get(road.enodeid)
    if snode_group is None or enode_group is None or snode_group == enode_group:
        return None
    return snode_group, enode_group


def _dead_end_bundle_key(endpoints: tuple[str, str]) -> tuple[str, str]:
    left_id, right_id = sorted(endpoints, key=_sort_key)
    return left_id, right_id


def _directed_semantic_pairs(
    road: RoadFeatureRecord,
    physical_to_semantic: dict[str, str],
) -> set[tuple[str, str]]:
    endpoints = _road_semantic_endpoints(road, physical_to_semantic)
    if endpoints is None:
        return set()
    snode_group, enode_group = endpoints
    pairs: set[tuple[str, str]] = set()
    if road.direction in {0, 1, 2}:
        pairs.add((snode_group, enode_group))
    if road.direction in {0, 1, 3}:
        pairs.add((enode_group, snode_group))
    return pairs


def _directed_oneway_semantic_endpoints(
    road: RoadFeatureRecord,
    physical_to_semantic: dict[str, str],
) -> Optional[tuple[str, str]]:
    snode_group = physical_to_semantic.get(road.snodeid)
    enode_group = physical_to_semantic.get(road.enodeid)
    if snode_group is None or enode_group is None:
        return None
    if road.direction == 2:
        return snode_group, enode_group
    if road.direction == 3:
        return enode_group, snode_group
    return None


def _resolve_dead_end_bundle_type(
    *,
    endpoint_pair: tuple[str, str],
    road_ids: tuple[str, ...],
    road_by_id: dict[str, RoadFeatureRecord],
    physical_to_semantic: dict[str, str],
) -> Optional[str]:
    if len(road_ids) == 1 and road_by_id[road_ids[0]].direction in {0, 1}:
        return DEAD_END_BIDIRECTIONAL_BUNDLE_TYPE

    if len(road_ids) != 2:
        return None
    if any(road_by_id[road_id].direction not in {2, 3} for road_id in road_ids):
        return None

    left_id, right_id = endpoint_pair
    directed_pairs: set[tuple[str, str]] = set()
    for road_id in road_ids:
        directed_pairs.update(_directed_semantic_pairs(road_by_id[road_id], physical_to_semantic))
    if (left_id, right_id) in directed_pairs and (right_id, left_id) in directed_pairs:
        return DEAD_END_ONEWAY_PAIR_BUNDLE_TYPE
    return None


def _run_dead_end_leaf_completion(
    *,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    node_properties_map: dict[str, dict[str, Any]],
    road_properties_map: dict[str, dict[str, Any]],
    mainnode_groups: dict[str, MainnodeGroup],
    physical_to_semantic: dict[str, str],
    used_segmentids: set[str],
) -> tuple[list[OnewayBuiltSegment], dict[str, Any]]:
    anchor_ids = _collect_dead_end_anchor_ids(
        nodes=nodes,
        node_properties_map=node_properties_map,
        mainnode_groups=mainnode_groups,
    )
    road_by_id = {road.road_id: road for road in roads}
    candidate_bundle_roads: dict[tuple[str, str], list[str]] = {}
    effective_incident_road_ids: dict[str, set[str]] = {}
    for road in roads:
        props = road_properties_map[road.road_id]
        endpoints = _road_semantic_endpoints(road, physical_to_semantic)
        if endpoints is None or not _is_dead_end_effective_road(road, props):
            continue
        for endpoint_id in endpoints:
            effective_incident_road_ids.setdefault(endpoint_id, set()).add(road.road_id)
        if not _is_dead_end_candidate_road(road, props):
            continue
        candidate_bundle_roads.setdefault(_dead_end_bundle_key(endpoints), []).append(road.road_id)

    built_segments: list[OnewayBuiltSegment] = []
    assigned_road_ids: set[str] = set()
    skipped_non_leaf_bundle_count = 0
    skipped_invalid_bundle_count = 0
    for endpoint_pair, bundle_road_ids in sorted(candidate_bundle_roads.items(), key=lambda item: item[0]):
        road_ids = tuple(sorted(bundle_road_ids, key=_sort_key))
        if any(road_id in assigned_road_ids for road_id in road_ids):
            continue

        bundle_type = _resolve_dead_end_bundle_type(
            endpoint_pair=endpoint_pair,
            road_ids=road_ids,
            road_by_id=road_by_id,
            physical_to_semantic=physical_to_semantic,
        )
        if bundle_type is None:
            skipped_invalid_bundle_count += 1
            continue

        endpoint_anchor_flags = {endpoint_id: endpoint_id in anchor_ids for endpoint_id in endpoint_pair}
        if sum(1 for is_anchor in endpoint_anchor_flags.values() if is_anchor) != 1:
            skipped_non_leaf_bundle_count += 1
            continue
        anchor_node_id = next(endpoint_id for endpoint_id, is_anchor in endpoint_anchor_flags.items() if is_anchor)
        leaf_node_id = next(endpoint_id for endpoint_id, is_anchor in endpoint_anchor_flags.items() if not is_anchor)
        if effective_incident_road_ids.get(leaf_node_id, set()) != set(road_ids):
            skipped_non_leaf_bundle_count += 1
            continue

        segmentid = _allocate_unique_segmentid(
            a_node_id=anchor_node_id,
            b_node_id=leaf_node_id,
            used_segmentids=used_segmentids,
            force_suffix=False,
        )
        for road_id in road_ids:
            props = road_properties_map[road_id]
            set_road_segmentid(props, segmentid)
            set_road_sgrade(props, DEAD_END_SEGMENT_GRADE)
            props["segment_build_source"] = DEAD_END_BUILD_SOURCE
            props["leaf_node_id"] = leaf_node_id
            props["dead_end_bundle_type"] = bundle_type
            assigned_road_ids.add(road_id)
        built_segments.append(
            OnewayBuiltSegment(
                phase_id=DEAD_END_PHASE_ID,
                sgrade=DEAD_END_SEGMENT_GRADE,
                start_node_id=anchor_node_id,
                end_node_id=leaf_node_id,
                segmentid=segmentid,
                road_ids=road_ids,
                through_node_ids=(),
                segment_build_source=DEAD_END_BUILD_SOURCE,
                leaf_node_id=leaf_node_id,
                dead_end_bundle_type=bundle_type,
            )
        )

    return built_segments, {
        "phase_id": DEAD_END_PHASE_ID,
        "sgrade": DEAD_END_SEGMENT_GRADE,
        "anchor_node_count": len(anchor_ids),
        "candidate_bundle_count": len(candidate_bundle_roads),
        "built_segment_count": len(built_segments),
        "new_segment_road_count": len(assigned_road_ids),
        "bidirectional_segment_count": sum(
            1 for segment in built_segments if segment.dead_end_bundle_type == DEAD_END_BIDIRECTIONAL_BUNDLE_TYPE
        ),
        "oneway_pair_segment_count": sum(
            1 for segment in built_segments if segment.dead_end_bundle_type == DEAD_END_ONEWAY_PAIR_BUNDLE_TYPE
        ),
        "road_kind_1_built_road_count": sum(
            1
            for road_id in assigned_road_ids
            if _coerce_int(road_properties_map[road_id].get("road_kind")) == 1
        ),
        "skipped_invalid_bundle_count": skipped_invalid_bundle_count,
        "skipped_non_leaf_bundle_count": skipped_non_leaf_bundle_count,
    }


def _run_final_oneway_fallback(
    *,
    roads: list[RoadFeatureRecord],
    road_properties_map: dict[str, dict[str, Any]],
    physical_to_semantic: dict[str, str],
    used_segmentids: set[str],
) -> tuple[list[OnewayBuiltSegment], dict[str, Any]]:
    candidate_road_ids = _collect_phase_candidate_road_ids(
        roads=roads,
        road_properties_map=road_properties_map,
    )
    built_segments: list[OnewayBuiltSegment] = []
    assigned_road_ids: set[str] = set()
    skipped_missing_endpoint_count = 0

    for road in sorted(roads, key=lambda item: _sort_key(item.road_id)):
        if road.road_id not in candidate_road_ids:
            continue
        endpoints = _directed_oneway_semantic_endpoints(road, physical_to_semantic)
        if endpoints is None:
            skipped_missing_endpoint_count += 1
            continue
        start_node_id, end_node_id = endpoints
        segmentid = _allocate_unique_segmentid(
            a_node_id=start_node_id,
            b_node_id=end_node_id,
            used_segmentids=used_segmentids,
            force_suffix=False,
        )
        props = road_properties_map[road.road_id]
        set_road_segmentid(props, segmentid)
        set_road_sgrade(props, FINAL_FALLBACK_SEGMENT_GRADE)
        props["segment_build_source"] = FINAL_FALLBACK_BUILD_SOURCE
        assigned_road_ids.add(road.road_id)
        built_segments.append(
            OnewayBuiltSegment(
                phase_id=FINAL_FALLBACK_PHASE_ID,
                sgrade=FINAL_FALLBACK_SEGMENT_GRADE,
                start_node_id=start_node_id,
                end_node_id=end_node_id,
                segmentid=segmentid,
                road_ids=(road.road_id,),
                through_node_ids=(),
                segment_build_source=FINAL_FALLBACK_BUILD_SOURCE,
            )
        )

    return built_segments, {
        "phase_id": FINAL_FALLBACK_PHASE_ID,
        "sgrade": FINAL_FALLBACK_SEGMENT_GRADE,
        "candidate_road_count": len(candidate_road_ids),
        "built_segment_count": len(built_segments),
        "new_segment_road_count": len(assigned_road_ids),
        "road_kind_1_built_road_count": sum(
            1
            for road_id in assigned_road_ids
            if _coerce_int(road_properties_map[road_id].get("road_kind")) == 1
        ),
        "skipped_missing_endpoint_count": skipped_missing_endpoint_count,
    }


def _run_phase(
    *,
    phase: OnewayPhaseSpec,
    nodes: list[NodeFeatureRecord],
    roads: list[RoadFeatureRecord],
    node_properties_map: dict[str, dict[str, Any]],
    road_properties_map: dict[str, dict[str, Any]],
    mainnode_groups: dict[str, MainnodeGroup],
    physical_to_semantic: dict[str, str],
    used_segmentids: set[str],
) -> tuple[list[OnewayBuiltSegment], dict[str, Any]]:
    terminate_ids = _collect_phase_terminate_ids(
        nodes=nodes,
        node_properties_map=node_properties_map,
        mainnode_groups=mainnode_groups,
        phase=phase,
    )
    candidate_road_ids = _collect_phase_candidate_road_ids(
        roads=roads,
        road_properties_map=road_properties_map,
    )
    outgoing_adjacency = _build_directed_adjacency(
        roads=roads,
        candidate_road_ids=candidate_road_ids,
        physical_to_semantic=physical_to_semantic,
    )
    road_by_id = {road.road_id: road for road in roads}
    road_kind_1_candidate_count = sum(
        1
        for road_id in candidate_road_ids
        if _coerce_int(road_properties_map[road_id].get("road_kind")) == 1
    )
    kind_2_128_terminate_count = sum(
        1
        for node in nodes
        if node.semantic_node_id in terminate_ids
        and _coerce_int(node_properties_map.get(node.node_id, node.properties).get("kind_2")) == 128
    )

    seeds: list[tuple[str, OnewayTraversalEdge]] = []
    for node_id in sorted(terminate_ids, key=_sort_key):
        for edge in outgoing_adjacency.get(node_id, ()):
            seeds.append((node_id, edge))

    assigned_road_ids: set[str] = set()
    built_segments: list[OnewayBuiltSegment] = []
    trace_fail_count = 0
    for start_node_id, first_edge in seeds:
        available_road_ids = candidate_road_ids - assigned_road_ids
        if first_edge.road_id not in available_road_ids:
            continue
        trace = _trace_oneway_segment_from_seed(
            start_node_id=start_node_id,
            first_edge=first_edge,
            outgoing_adjacency=outgoing_adjacency,
            terminate_ids=terminate_ids,
            available_road_ids=available_road_ids,
            road_by_id=road_by_id,
        )
        if trace is None:
            trace_fail_count += 1
            continue

        segmentid = _allocate_unique_segmentid(
            a_node_id=trace.start_node_id,
            b_node_id=trace.end_node_id,
            used_segmentids=used_segmentids,
            force_suffix=False,
        )
        for road_id in trace.road_ids:
            props = road_properties_map[road_id]
            set_road_segmentid(props, segmentid)
            set_road_sgrade(props, phase.sgrade)
            assigned_road_ids.add(road_id)
        built_segments.append(
            OnewayBuiltSegment(
                phase_id=phase.phase_id,
                sgrade=phase.sgrade,
                start_node_id=trace.start_node_id,
                end_node_id=trace.end_node_id,
                segmentid=segmentid,
                road_ids=trace.road_ids,
                through_node_ids=trace.through_node_ids,
            )
        )

    return built_segments, {
        "phase_id": phase.phase_id,
        "sgrade": phase.sgrade,
        "terminate_node_count": len(terminate_ids),
        "candidate_road_count": len(candidate_road_ids),
        "seed_count": len(seeds),
        "built_segment_count": len(built_segments),
        "new_segment_road_count": len(assigned_road_ids),
        "road_kind_1_candidate_count": road_kind_1_candidate_count,
        "road_kind_1_built_road_count": sum(
            1
            for road_id in assigned_road_ids
            if _coerce_int(road_properties_map[road_id].get("road_kind")) == 1
        ),
        "kind_2_128_terminate_count": kind_2_128_terminate_count,
        "trace_fail_count": trace_fail_count,
    }


def _build_segment_road_features(
    *,
    roads: list[RoadFeatureRecord],
    built_segments: list[OnewayBuiltSegment],
) -> list[dict[str, Any]]:
    road_by_id = {road.road_id: road for road in roads}
    features: list[dict[str, Any]] = []
    for segment in built_segments:
        for order, road_id in enumerate(segment.road_ids, start=1):
            road = road_by_id[road_id]
            features.append(
                {
                    "properties": {
                        "segmentid": segment.segmentid,
                        "sgrade": segment.sgrade,
                        "phase_id": segment.phase_id,
                        "start_node_id": segment.start_node_id,
                        "end_node_id": segment.end_node_id,
                        "road_id": road_id,
                        "road_order": order,
                        "road_ids": ",".join(segment.road_ids),
                        "through_node_ids": ",".join(segment.through_node_ids),
                        "segment_build_source": segment.segment_build_source,
                        "leaf_node_id": segment.leaf_node_id,
                        "dead_end_bundle_type": segment.dead_end_bundle_type,
                    },
                    "geometry": road.geometry,
                }
            )
    return features


def _unsegmented_audit_reason(*, road: RoadFeatureRecord, properties: dict[str, Any]) -> str:
    if _has_formway_bit7_or_bit8(properties):
        return "formway_bit7_or_bit8"
    if road.direction not in {0, 1, 2, 3}:
        return "unsupported_direction"
    if road.direction in {2, 3}:
        return "oneway_trace_failed_or_no_terminate"
    road_kind = _coerce_int(properties.get("road_kind")) if "road_kind" in properties else road.road_kind
    if not is_allowed_road_kind(road_kind):
        return "bidirectional_road_kind_1_excluded"
    return "dead_end_leaf_rule_not_met"


def _write_unsegmented_roads_outputs(
    *,
    roads: list[RoadFeatureRecord],
    road_properties_map: dict[str, dict[str, Any]],
    out_root: Path,
    run_id: str,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    unsegmented_roads_path = out_root / UNSEGMENTED_ROADS_PATH_NAME
    unsegmented_csv_path = out_root / UNSEGMENTED_ROADS_CSV_NAME
    unsegmented_summary_path = out_root / UNSEGMENTED_ROADS_SUMMARY_NAME

    rows: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    excluded_formway_128_count = 0
    formway_bit7_or_bit8_count = 0
    non_formway_bit7_or_bit8_reason_counts: dict[str, int] = {}
    for road in roads:
        props = road_properties_map[road.road_id]
        if _is_formway_128(props):
            excluded_formway_128_count += 1
            continue
        if get_road_segmentid(props):
            continue
        formway_has_bit7_or_bit8 = _has_formway_bit7_or_bit8(props)
        audit_reason = _unsegmented_audit_reason(road=road, properties=props)
        if formway_has_bit7_or_bit8:
            formway_bit7_or_bit8_count += 1
        else:
            non_formway_bit7_or_bit8_reason_counts[audit_reason] = (
                non_formway_bit7_or_bit8_reason_counts.get(audit_reason, 0) + 1
            )
        rows.append(
            {
                "road_id": road.road_id,
                "snodeid": road.snodeid,
                "enodeid": road.enodeid,
                "direction": road.direction,
                "road_kind": _coerce_int(props.get("road_kind")) if "road_kind" in props else road.road_kind,
                "formway": _coerce_formway(props),
                "formway_has_bit7_or_bit8": "true" if formway_has_bit7_or_bit8 else "false",
                "segmentid": get_road_segmentid(props),
                "sgrade": get_road_sgrade(props),
                "audit_reason": audit_reason,
            }
        )
        features.append({"properties": dict(props), "geometry": road.geometry})

    write_vector(unsegmented_roads_path, features)
    write_csv(
        unsegmented_csv_path,
        rows,
        [
            "road_id",
            "snodeid",
            "enodeid",
            "direction",
            "road_kind",
            "formway",
            "formway_has_bit7_or_bit8",
            "segmentid",
            "sgrade",
            "audit_reason",
        ],
    )
    summary = {
        "run_id": run_id,
        "unsegmented_road_count": len(rows),
        "excluded_formway_128_count": excluded_formway_128_count,
        "unsegmented_formway_bit7_or_bit8_count": formway_bit7_or_bit8_count,
        "unsegmented_non_formway_bit7_or_bit8_count": len(rows) - formway_bit7_or_bit8_count,
        "unsegmented_non_formway_bit7_or_bit8_reason_counts": dict(
            sorted(non_formway_bit7_or_bit8_reason_counts.items())
        ),
        "output_files": [
            unsegmented_roads_path.name,
            unsegmented_csv_path.name,
            unsegmented_summary_path.name,
        ],
    }
    write_json(unsegmented_summary_path, summary)
    return unsegmented_roads_path, unsegmented_csv_path, unsegmented_summary_path, summary


def run_step5_oneway_segment_completion(
    *,
    step5_artifacts: Any,
    out_root: Union[str, Path],
    run_id: Optional[str] = None,
    debug: bool = True,
) -> OnewaySegmentArtifacts:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    resolved_out_root.mkdir(parents=True, exist_ok=True)

    nodes = list(step5_artifacts.step6_nodes)
    roads = list(step5_artifacts.step6_roads)
    node_properties_map = {
        node_id: dict(props)
        for node_id, props in (getattr(step5_artifacts, "step6_node_properties_map", {}) or {}).items()
    }
    road_properties_map = {
        road_id: canonicalize_road_working_properties(dict(props))
        for road_id, props in (getattr(step5_artifacts, "step6_road_properties_map", {}) or {}).items()
    }
    for node in nodes:
        node_properties_map.setdefault(node.node_id, dict(node.properties))
    for road in roads:
        road_properties_map.setdefault(road.road_id, canonicalize_road_working_properties(dict(road.properties)))

    mainnode_groups = dict(getattr(step5_artifacts, "step6_mainnode_groups", {}) or {})
    if not mainnode_groups:
        mainnode_groups = _build_mainnode_groups_fallback(nodes)
    physical_to_semantic = _physical_to_semantic(mainnode_groups)

    used_segmentids = {
        segmentid
        for road_id in sorted(road_properties_map, key=_sort_key)
        for segmentid in (get_road_segmentid(road_properties_map[road_id]),)
        if segmentid is not None
    }

    all_built_segments: list[OnewayBuiltSegment] = []
    phase_summaries: list[dict[str, Any]] = []
    phase_specs = _build_oneway_phase_specs()
    for phase in phase_specs:
        built_segments, phase_summary = _run_phase(
            phase=phase,
            nodes=nodes,
            roads=roads,
            node_properties_map=node_properties_map,
            road_properties_map=road_properties_map,
            mainnode_groups=mainnode_groups,
            physical_to_semantic=physical_to_semantic,
            used_segmentids=used_segmentids,
        )
        all_built_segments.extend(built_segments)
        phase_summaries.append(phase_summary)

    dead_end_segments, dead_end_summary = _run_dead_end_leaf_completion(
        nodes=nodes,
        roads=roads,
        node_properties_map=node_properties_map,
        road_properties_map=road_properties_map,
        mainnode_groups=mainnode_groups,
        physical_to_semantic=physical_to_semantic,
        used_segmentids=used_segmentids,
    )
    all_built_segments.extend(dead_end_segments)

    final_fallback_segments, final_fallback_summary = _run_final_oneway_fallback(
        roads=roads,
        road_properties_map=road_properties_map,
        physical_to_semantic=physical_to_semantic,
        used_segmentids=used_segmentids,
    )
    all_built_segments.extend(final_fallback_segments)

    group_to_allowed_road_ids = _build_group_to_allowed_road_ids(
        roads=roads,
        road_properties_map=road_properties_map,
        physical_to_semantic=physical_to_semantic,
    )

    kind_2_128_terminate_node_ids = {
        node.semantic_node_id
        for node in nodes
        for props in (node_properties_map.get(node.node_id, node.properties),)
        if _coerce_int(props.get("kind_2")) == 128
        and any(_matches_phase_node(properties=props, phase=phase) for phase in phase_specs)
    }

    refreshed_roads_path = resolved_out_root / "roads.gpkg"
    write_vector(
        refreshed_roads_path,
        (
            {
                "properties": road_properties_map[road.road_id],
                "geometry": road.geometry,
            }
            for road in roads
        ),
    )

    segment_roads_path = resolved_out_root / ONEWAY_SEGMENT_OUTPUT_NAME
    write_vector(
        segment_roads_path,
        _build_segment_road_features(roads=roads, built_segments=all_built_segments),
    )

    build_table_path = resolved_out_root / ONEWAY_SEGMENT_BUILD_TABLE_NAME
    write_csv(
        build_table_path,
        (
            {
                "phase_id": segment.phase_id,
                "segmentid": segment.segmentid,
                "sgrade": segment.sgrade,
                "start_node_id": segment.start_node_id,
                "end_node_id": segment.end_node_id,
                "road_count": len(segment.road_ids),
                "road_ids": ",".join(segment.road_ids),
                "through_node_ids": ",".join(segment.through_node_ids),
                "segment_build_source": segment.segment_build_source,
                "leaf_node_id": segment.leaf_node_id,
                "dead_end_bundle_type": segment.dead_end_bundle_type,
            }
            for segment in all_built_segments
        ),
        [
            "phase_id",
            "segmentid",
            "sgrade",
            "start_node_id",
            "end_node_id",
            "road_count",
            "road_ids",
            "through_node_ids",
            "segment_build_source",
            "leaf_node_id",
            "dead_end_bundle_type",
        ],
    )

    unsegmented_roads_path, unsegmented_csv_path, unsegmented_summary_path, unsegmented_summary = (
        _write_unsegmented_roads_outputs(
            roads=roads,
            road_properties_map=road_properties_map,
            out_root=resolved_out_root,
            run_id=resolved_run_id,
        )
    )

    summary = {
        "run_id": resolved_run_id,
        "debug": debug,
        "input_node_path": str(Path(step5_artifacts.refreshed_nodes_path).resolve()),
        "input_road_path": str(Path(step5_artifacts.refreshed_roads_path).resolve()),
        "phase_summaries": phase_summaries,
        "dead_end_summary": dead_end_summary,
        "final_fallback_summary": final_fallback_summary,
        "built_segment_count": len(all_built_segments),
        "built_segment_road_count": sum(len(segment.road_ids) for segment in all_built_segments),
        "road_kind_1_built_road_count": sum(
            phase_summary["road_kind_1_built_road_count"] for phase_summary in phase_summaries
        )
        + dead_end_summary["road_kind_1_built_road_count"]
        + final_fallback_summary["road_kind_1_built_road_count"],
        "kind_2_128_terminate_count": len(kind_2_128_terminate_node_ids),
        "dead_end_segment_count": dead_end_summary["built_segment_count"],
        "dead_end_road_count": dead_end_summary["new_segment_road_count"],
        "dead_end_bidirectional_segment_count": dead_end_summary["bidirectional_segment_count"],
        "dead_end_oneway_pair_segment_count": dead_end_summary["oneway_pair_segment_count"],
        "final_fallback_segment_count": final_fallback_summary["built_segment_count"],
        "final_fallback_road_count": final_fallback_summary["new_segment_road_count"],
        "unsegmented_road_count": unsegmented_summary["unsegmented_road_count"],
        "unsegmented_excluded_formway_128_count": unsegmented_summary["excluded_formway_128_count"],
        "unsegmented_formway_bit7_or_bit8_count": unsegmented_summary[
            "unsegmented_formway_bit7_or_bit8_count"
        ],
        "unsegmented_non_formway_bit7_or_bit8_count": unsegmented_summary[
            "unsegmented_non_formway_bit7_or_bit8_count"
        ],
        "unsegmented_non_formway_bit7_or_bit8_reason_counts": unsegmented_summary[
            "unsegmented_non_formway_bit7_or_bit8_reason_counts"
        ],
        "output_files": [
            refreshed_roads_path.name,
            segment_roads_path.name,
            build_table_path.name,
            ONEWAY_SEGMENT_SUMMARY_NAME,
            unsegmented_roads_path.name,
            unsegmented_csv_path.name,
            unsegmented_summary_path.name,
        ],
    }
    summary_path = resolved_out_root / ONEWAY_SEGMENT_SUMMARY_NAME
    write_json(summary_path, summary)

    return OnewaySegmentArtifacts(
        out_root=resolved_out_root,
        refreshed_nodes_path=Path(step5_artifacts.refreshed_nodes_path),
        refreshed_roads_path=refreshed_roads_path,
        segment_roads_path=segment_roads_path,
        build_table_path=build_table_path,
        summary_path=summary_path,
        unsegmented_roads_path=unsegmented_roads_path,
        unsegmented_csv_path=unsegmented_csv_path,
        unsegmented_summary_path=unsegmented_summary_path,
        summary=summary,
        step6_nodes=tuple(nodes),
        step6_roads=tuple(roads),
        step6_node_properties_map=node_properties_map,
        step6_road_properties_map=road_properties_map,
        step6_mainnode_groups=mainnode_groups,
        step6_group_to_allowed_road_ids=group_to_allowed_road_ids,
    )
