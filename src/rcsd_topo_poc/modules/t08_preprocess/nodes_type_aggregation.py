from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import Point

from rcsd_topo_poc.modules.t08_preprocess.output_naming import ensure_tool_output_name
from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    VectorFeature,
    aggregate_bounds,
    ensure_gpkg_path,
    read_vector,
    resolve_case_insensitive_field_name,
    resolve_field_name,
    unique_field_names,
    write_gpkg,
    write_json,
)


ROUNDABOUT_ROADTYPE_BIT = 3
ROUNDABOUT_KIND_VALUE = 64
COMPLEX_DIVMERGE_KIND_VALUE = 128
COMPLEX_CANDIDATE_KIND_VALUES = frozenset({8, 16})
CONTINUOUS_DIST_MAX_M = 50.0
CONTINUOUS_DIVERGE_THEN_MERGE_DIST_MAX_M = 75.0


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class T08NodesTypeAggregationArtifacts:
    nodes_output: Path
    summary_output: Path


@dataclass(frozen=True)
class RoundaboutGroup:
    group_id: str
    mainnode_id: str
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParsedNode:
    feature_index: int
    properties: dict[str, Any]
    geometry: Point
    node_id: str
    mainnodeid: str | None
    has_evd: str | None
    is_anchor: str | None
    kind: int | None
    grade: int | None
    kind_2: int | None
    grade_2: int | None


@dataclass(frozen=True)
class ParsedRoad:
    feature_index: int
    road_id: str
    snodeid: str
    enodeid: str
    direction: int | None
    length_m: float


@dataclass(frozen=True)
class DirectedEdge:
    src: str
    dst: str
    road_idx: int
    length_m: float


@dataclass(frozen=True)
class ChainEdge:
    src: str
    dst: str
    dist_m: float
    path_road_indices: tuple[int, ...]


@dataclass(frozen=True)
class ChainComponent:
    component_id: str
    node_ids: tuple[str, ...]
    edges: tuple[ChainEdge, ...]
    offsets_m: dict[str, float]
    predecessors: dict[str, tuple[str, ...]]
    diag: dict[str, Any]


def run_t08_nodes_type_aggregation(
    *,
    nodes_gpkg: str | Path,
    roads_gpkg: str | Path,
    nodes_output: str | Path,
    nodes_layer: str | None = None,
    roads_layer: str | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int = 3857,
    nodes_default_crs_text: str | None = None,
    roads_default_crs_text: str | None = None,
    enable_roundabout: bool = True,
    enable_complex_divmerge: bool = False,
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> T08NodesTypeAggregationArtifacts:
    started = time.perf_counter()
    stage_timings: dict[str, float] = {}
    nodes_path = ensure_gpkg_path(nodes_gpkg, label="--nodes-gpkg")
    roads_path = ensure_gpkg_path(roads_gpkg, label="--roads-gpkg")
    output_path = ensure_tool_output_name(
        ensure_gpkg_path(nodes_output, label="--nodes-output"),
        tool_number=3,
        label="--nodes-output",
    )
    if enable_complex_divmerge:
        _emit_progress(progress_callback, "[T08 Tool3] complex_divmerge is disabled; use T08 Tool5 instead")
        enable_complex_divmerge = False
    summary_path = (
        ensure_tool_output_name(summary_output, tool_number=3, label="--summary-output")
        if summary_output
        else output_path.with_name("t08_nodes_type_aggregation_summary_tool3.json")
    )

    _emit_progress(progress_callback, f"[T08 Tool3] start nodes={nodes_path} roads={roads_path}")
    stage_started = time.perf_counter()
    nodes_result = read_vector(
        nodes_path,
        layer_name=nodes_layer,
        default_crs_text=nodes_default_crs_text,
        target_epsg=target_epsg,
    )
    roads_result = read_vector(
        roads_path,
        layer_name=roads_layer,
        default_crs_text=roads_default_crs_text,
        target_epsg=target_epsg,
    )
    if not nodes_result.features:
        raise ValueError("Nodes input contains no features")
    stage_timings["read_inputs_seconds"] = _elapsed_since(stage_started)
    _emit_progress(
        progress_callback,
        f"[T08 Tool3] loaded nodes={len(nodes_result.features)} roads={len(roads_result.features)}",
    )

    stage_started = time.perf_counter()
    node_id_field = resolve_field_name(nodes_result.features, ["id"], "nodes input")
    node_kind_field = resolve_field_name(nodes_result.features, ["kind"], "nodes input")
    node_grade_field = resolve_field_name(nodes_result.features, ["grade"], "nodes input")
    road_id_field = resolve_field_name(roads_result.features, ["id"], "roads input")
    road_snode_field = resolve_field_name(roads_result.features, ["snodeid"], "roads input")
    road_enode_field = resolve_field_name(roads_result.features, ["enodeid"], "roads input")
    road_direction_field = (
        resolve_field_name(roads_result.features, ["direction"], "roads input")
        if enable_complex_divmerge
        else _optional_field(roads_result.features, ["direction"])
    )

    kind_sample = _first_non_empty_value(nodes_result.features, node_kind_field)
    grade_sample = _first_non_empty_value(nodes_result.features, node_grade_field)
    node_features = [
        {"properties": dict(feature.properties), "geometry": feature.geometry}
        for feature in nodes_result.features
    ]
    road_features = [
        {"properties": dict(feature.properties), "geometry": feature.geometry}
        for feature in roads_result.features
    ]
    _initialize_working_type_fields(
        node_features=node_features,
        kind_field=node_kind_field,
        grade_field=node_grade_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    stage_timings["initialize_fields_seconds"] = _elapsed_since(stage_started)

    roundabout_summary: dict[str, Any] = _empty_roundabout_summary()
    if enable_roundabout:
        stage_started = time.perf_counter()
        _emit_progress(progress_callback, "[T08 Tool3] roundabout: start")
        roundabout_summary = _apply_roundabout_aggregation(
            node_features=node_features,
            road_features=road_features,
            node_id_field=node_id_field,
            road_id_field=road_id_field,
            road_snode_field=road_snode_field,
            road_enode_field=road_enode_field,
            kind_sample=kind_sample,
            grade_sample=grade_sample,
            progress_callback=progress_callback,
            progress_interval=progress_interval,
        )
        stage_timings["roundabout_seconds"] = _elapsed_since(stage_started)
        _emit_progress(
            progress_callback,
            (
                f"[T08 Tool3] roundabout: groups={roundabout_summary['roundabout_group_count']} "
                f"updated_nodes={roundabout_summary['roundabout_updated_node_count']} "
                f"elapsed={stage_timings['roundabout_seconds']:.2f}s"
            ),
        )

    complex_summary: dict[str, Any] = _empty_complex_summary()
    if enable_complex_divmerge:
        stage_started = time.perf_counter()
        _emit_progress(progress_callback, "[T08 Tool3] complex_divmerge: start")
        complex_summary = _apply_complex_divmerge_aggregation(
            node_features=node_features,
            road_features=road_features,
            node_id_field=node_id_field,
            node_kind_field=node_kind_field,
            node_grade_field=node_grade_field,
            road_id_field=road_id_field,
            road_snode_field=road_snode_field,
            road_enode_field=road_enode_field,
            road_direction_field=road_direction_field,
            kind_sample=kind_sample,
            grade_sample=grade_sample,
            progress_callback=progress_callback,
            progress_interval=progress_interval,
        )
        stage_timings["complex_divmerge_seconds"] = _elapsed_since(stage_started)
        _emit_progress(
            progress_callback,
            (
                f"[T08 Tool3] complex_divmerge: junctions={complex_summary['complex_junction_count']} "
                f"updated_nodes={complex_summary['updated_node_count']} "
                f"elapsed={stage_timings['complex_divmerge_seconds']:.2f}s"
            ),
        )

    output_fields = unique_field_names(
        nodes_result.field_names,
        extra=("kind_2", "grade_2", "mainnodeid", "subnodeid"),
    )
    stage_started = time.perf_counter()
    _emit_progress(progress_callback, f"[T08 Tool3] writing nodes output={output_path}")
    write_gpkg(output_path, node_features, crs_text=f"EPSG:{target_epsg}", empty_fields=output_fields)
    stage_timings["write_output_seconds"] = _elapsed_since(stage_started)
    elapsed_seconds = _elapsed_since(started)

    summary = {
        "tool": "T08 Tool3",
        "stage": "nodes_type_aggregation",
        "target_epsg": target_epsg,
        "input_paths": {"nodes_gpkg": nodes_path, "roads_gpkg": roads_path},
        "output_paths": {"nodes_output": output_path, "summary_output": summary_path},
        "input_crs": {
            "nodes": nodes_result.source_crs.to_string(),
            "nodes_crs_source": nodes_result.crs_source,
            "roads": roads_result.source_crs.to_string(),
            "roads_crs_source": roads_result.crs_source,
        },
        "params": {
            "nodes_layer": nodes_layer,
            "roads_layer": roads_layer,
            "enable_roundabout": enable_roundabout,
            "enable_complex_divmerge": enable_complex_divmerge,
        },
        "field_audit": {
            "node_id_field": node_id_field,
            "node_kind_field": node_kind_field,
            "node_grade_field": node_grade_field,
            "road_id_field": road_id_field,
            "road_snode_field": road_snode_field,
            "road_enode_field": road_enode_field,
            "road_direction_field": road_direction_field,
        },
        "counts": {
            "node_feature_count": len(node_features),
            "road_feature_count": len(road_features),
            "roundabout_group_count": roundabout_summary["roundabout_group_count"],
            "roundabout_updated_node_count": roundabout_summary["roundabout_updated_node_count"],
            "complex_junction_count": complex_summary["complex_junction_count"],
            "complex_updated_node_count": complex_summary["updated_node_count"],
        },
        "output_bounds": aggregate_bounds(feature["geometry"] for feature in node_features),
        "performance": {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "nodes_per_second": _items_per_second(len(node_features), elapsed_seconds),
            "stage_timings": {key: round(value, 6) for key, value in stage_timings.items()},
        },
        "roundabout": roundabout_summary,
        "complex_divmerge": complex_summary,
    }
    write_json(summary_path, summary)
    _emit_progress(
        progress_callback,
        (
            f"[T08 Tool3] finished nodes={len(node_features)} roads={len(road_features)} "
            f"elapsed={elapsed_seconds:.2f}s summary={summary_path}"
        ),
    )
    return T08NodesTypeAggregationArtifacts(nodes_output=output_path, summary_output=summary_path)


def _initialize_working_type_fields(
    *,
    node_features: list[dict[str, Any]],
    kind_field: str,
    grade_field: str,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> None:
    for index, feature in enumerate(node_features, start=1):
        props = feature["properties"]
        props["kind_2"] = props.get(kind_field)
        props["grade_2"] = props.get(grade_field)
        if _should_emit_progress(index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool3] initialized {index} node feature(s)")


def _apply_roundabout_aggregation(
    *,
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    node_id_field: str,
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    kind_sample: Any,
    grade_sample: Any,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> dict[str, Any]:
    groups, issue_rows, base_summary = _build_roundabout_groups(
        node_features=node_features,
        road_features=road_features,
        node_id_field=node_id_field,
        road_id_field=road_id_field,
        road_snode_field=road_snode_field,
        road_enode_field=road_enode_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    node_index_by_id = {
        _normalize_id(feature["properties"].get(node_id_field)): index
        for index, feature in enumerate(node_features)
    }
    updated_node_ids: set[str] = set()
    for group_index, group in enumerate(groups, start=1):
        for node_id in group.node_ids:
            index = node_index_by_id[node_id]
            props = node_features[index]["properties"]
            props["mainnodeid"] = group.mainnode_id
            if node_id == group.mainnode_id:
                props["grade_2"] = _typed_like(grade_sample, 1)
                props["kind_2"] = _typed_like(kind_sample, ROUNDABOUT_KIND_VALUE)
            else:
                props["grade_2"] = _typed_like(grade_sample, 0)
                props["kind_2"] = _typed_like(kind_sample, 0)
            updated_node_ids.add(node_id)
        if _should_emit_progress(group_index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool3] roundabout: applied {group_index} group(s)")

    return {
        **base_summary,
        "roundabout_updated_node_count": len(updated_node_ids),
        "group_ids": [group.group_id for group in groups],
        "groups": [
            {
                "group_id": group.group_id,
                "mainnode_id": group.mainnode_id,
                "road_ids": list(group.road_ids),
                "node_ids": list(group.node_ids),
            }
            for group in groups
        ],
        "roadtype_issue_rows": issue_rows,
    }


def _build_roundabout_groups(
    *,
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    node_id_field: str,
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> tuple[list[RoundaboutGroup], list[dict[str, Any]], dict[str, Any]]:
    node_ids = {_normalize_id(feature["properties"].get(node_id_field)) for feature in node_features}
    node_ids.discard(None)
    roadtype_field = _optional_field_from_dict_features(road_features, ["roadtype"])

    roundabout_roads: dict[str, dict[str, Any]] = {}
    issue_rows: list[dict[str, Any]] = []
    missing_count = 0
    empty_count = 0
    invalid_count = 0
    if roadtype_field is None:
        missing_count = len(road_features)
    for index, feature in enumerate(road_features, start=1):
        props = feature["properties"]
        road_id = _required_id(props.get(road_id_field), "road id")
        snodeid = _required_id(props.get(road_snode_field), f"road '{road_id}' snodeid")
        enodeid = _required_id(props.get(road_enode_field), f"road '{road_id}' enodeid")
        if snodeid not in node_ids or enodeid not in node_ids:
            raise ValueError(f"Road '{road_id}' references missing node '{snodeid if snodeid not in node_ids else enodeid}'.")
        if roadtype_field is None:
            issue_rows.append({"road_id": road_id, "issue": "missing", "roadtype_raw": None})
            continue
        raw_roadtype = props.get(roadtype_field)
        if _normalize_scalar(raw_roadtype) is None:
            empty_count += 1
            issue_rows.append({"road_id": road_id, "issue": "empty", "roadtype_raw": raw_roadtype})
            continue
        try:
            roadtype = _coerce_int(raw_roadtype)
        except Exception:
            invalid_count += 1
            issue_rows.append({"road_id": road_id, "issue": "invalid", "roadtype_raw": raw_roadtype})
            continue
        if roadtype is None or not _bit_enabled(roadtype, ROUNDABOUT_ROADTYPE_BIT):
            continue
        roundabout_roads[road_id] = {"road_id": road_id, "snodeid": snodeid, "enodeid": enodeid}
        if _should_emit_progress(index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool3] roundabout: scanned {index} road feature(s)")

    node_to_road_ids: dict[str, set[str]] = defaultdict(set)
    for road in roundabout_roads.values():
        node_to_road_ids[road["snodeid"]].add(road["road_id"])
        node_to_road_ids[road["enodeid"]].add(road["road_id"])
    sorted_node_to_road_ids = {
        node_id: tuple(sorted(road_ids, key=_sort_key))
        for node_id, road_ids in node_to_road_ids.items()
    }

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
            component_node_ids.update((road["snodeid"], road["enodeid"]))
            for node_id in (road["snodeid"], road["enodeid"]):
                for next_road_id in sorted_node_to_road_ids.get(node_id, ()):
                    if next_road_id not in visited:
                        queue.append(next_road_id)
        if component_node_ids:
            sorted_nodes = tuple(sorted(component_node_ids, key=_sort_key))
            mainnode_id = sorted_nodes[0]
            groups.append(
                RoundaboutGroup(
                    group_id=f"roundabout_{mainnode_id}",
                    mainnode_id=mainnode_id,
                    road_ids=tuple(sorted(component_road_ids, key=_sort_key)),
                    node_ids=sorted_nodes,
                )
            )

    return groups, issue_rows, {
        "roundabout_roadtype_bit": ROUNDABOUT_ROADTYPE_BIT,
        "roundabout_kind_value": ROUNDABOUT_KIND_VALUE,
        "roundabout_road_count": len(roundabout_roads),
        "roundabout_group_count": len(groups),
        "roundabout_mainnode_count": len(groups),
        "roundabout_member_node_count": sum(max(0, len(group.node_ids) - 1) for group in groups),
        "roadtype_missing_count": missing_count,
        "roadtype_empty_count": empty_count,
        "roadtype_invalid_count": invalid_count,
    }


def _apply_complex_divmerge_aggregation(
    *,
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    node_id_field: str,
    node_kind_field: str,
    node_grade_field: str,
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    road_direction_field: str,
    kind_sample: Any,
    grade_sample: Any,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> dict[str, Any]:
    has_evd_field = _optional_field_from_dict_features(node_features, ["has_evd"])
    is_anchor_field = _optional_field_from_dict_features(node_features, ["is_anchor"])
    parsed_nodes = _parse_nodes(
        node_features=node_features,
        node_id_field=node_id_field,
        node_kind_field=node_kind_field,
        node_grade_field=node_grade_field,
        has_evd_field=has_evd_field,
        is_anchor_field=is_anchor_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    parsed_roads = _parse_roads(
        road_features=road_features,
        road_id_field=road_id_field,
        road_snode_field=road_snode_field,
        road_enode_field=road_enode_field,
        road_direction_field=road_direction_field,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )
    node_by_id = {node.node_id: node for node in parsed_nodes}
    candidate_nodes = [
        node
        for node in parsed_nodes
        if _is_complex_candidate(node, has_evd_gate=has_evd_field is not None, is_anchor_gate=is_anchor_field is not None)
    ]
    candidate_node_ids = {node.node_id for node in candidate_nodes}
    candidate_kind_map = {node.node_id: int(node.kind_2 or 0) for node in candidate_nodes}

    chain_edges, chain_components, chain_diag = _build_continuous_graph(
        starts_set=candidate_node_ids,
        nodes_kind=candidate_kind_map,
        roads=parsed_roads,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )

    rows: list[dict[str, Any]] = []
    updated_node_ids: set[str] = set()
    for component_index, component in enumerate(chain_components, start=1):
        component_nodes = [node_by_id[node_id] for node_id in component.node_ids if node_id in node_by_id]
        if len(component_nodes) < 2:
            continue
        topology_diag = component.diag.get("topology") or {}
        if not bool(topology_diag.get("is_dag", False)):
            rows.append(
                {
                    "component_id": component.component_id,
                    "status": "skipped",
                    "reason": "topology_not_dag",
                    "node_ids": list(component.node_ids),
                    "edge_count": len(component.edges),
                    "topology": topology_diag,
                }
            )
            continue

        chosen_main = sorted(component_nodes, key=_grade_sort_tuple)[0]
        chosen_mainnodeid = chosen_main.node_id
        group_node_ids = tuple(sorted(component.node_ids, key=_sort_key))
        changed_road_indices = sorted({index for edge in component.edges for index in edge.path_road_indices})
        changed_road_ids = sorted({parsed_roads[index].road_id for index in changed_road_indices}, key=_sort_key)

        for node in component_nodes:
            props = node_features[node.feature_index]["properties"]
            props["mainnodeid"] = chosen_mainnodeid
            if node.node_id == chosen_mainnodeid:
                props["kind_2"] = _typed_like(kind_sample, COMPLEX_DIVMERGE_KIND_VALUE)
                if _coerce_int(props.get("grade_2")) is None and _resolved_grade(node) is not None:
                    props["grade_2"] = _typed_like(grade_sample, int(_resolved_grade(node) or 0))
                props["subnodeid"] = ",".join(group_node_ids)
            else:
                props["grade_2"] = _typed_like(grade_sample, 0)
                props["kind_2"] = _typed_like(kind_sample, 0)
                props["subnodeid"] = None
            updated_node_ids.add(node.node_id)

        rows.append(
            {
                "component_id": component.component_id,
                "status": "aggregated",
                "reason": None,
                "node_ids": list(group_node_ids),
                "mainnodeid": chosen_mainnodeid,
                "main_grade": _resolved_grade(chosen_main),
                "edge_count": len(component.edges),
                "road_ids": changed_road_ids,
                "offsets_m": {node_id: round(float(value), 3) for node_id, value in component.offsets_m.items()},
                "predecessors": {node_id: list(items) for node_id, items in component.predecessors.items()},
                "topology": topology_diag,
            }
        )
        if _should_emit_progress(component_index, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool3] complex_divmerge: processed {component_index} chain component(s)")

    complex_mainnodeids = tuple(
        sorted(
            [str(row["mainnodeid"]) for row in rows if row["status"] == "aggregated" and row.get("mainnodeid")],
            key=_sort_key,
        )
    )
    return {
        "complex_kind_value": COMPLEX_DIVMERGE_KIND_VALUE,
        "candidate_kind_values": sorted(COMPLEX_CANDIDATE_KIND_VALUES),
        "has_evd_gate_applied": has_evd_field is not None,
        "is_anchor_gate_applied": is_anchor_field is not None,
        "has_evd_field": has_evd_field,
        "is_anchor_field": is_anchor_field,
        "candidate_node_count": len(candidate_nodes),
        "chain_edge_count": len(chain_edges),
        "chain_component_count": len(chain_components),
        "complex_junction_count": len(complex_mainnodeids),
        "aggregated_component_count": sum(1 for row in rows if row["status"] == "aggregated"),
        "skipped_component_count": sum(1 for row in rows if row["status"] != "aggregated"),
        "updated_node_count": len(updated_node_ids),
        "complex_mainnodeids": list(complex_mainnodeids),
        "diag": chain_diag,
        "rows": rows,
    }


def _parse_nodes(
    *,
    node_features: list[dict[str, Any]],
    node_id_field: str,
    node_kind_field: str,
    node_grade_field: str,
    has_evd_field: str | None,
    is_anchor_field: str | None,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> list[ParsedNode]:
    parsed: list[ParsedNode] = []
    seen_ids: set[str] = set()
    for index, feature in enumerate(node_features):
        props = feature["properties"]
        node_id = _required_id(props.get(node_id_field), "node id")
        if node_id in seen_ids:
            raise ValueError(f"Nodes input has duplicate id '{node_id}'.")
        seen_ids.add(node_id)
        geometry = feature["geometry"]
        centroid = geometry.centroid
        parsed.append(
            ParsedNode(
                feature_index=index,
                properties=props,
                geometry=Point(float(centroid.x), float(centroid.y)),
                node_id=node_id,
                mainnodeid=_valid_mainnodeid(props.get("mainnodeid")),
                has_evd=_normalize_text(props.get(has_evd_field)) if has_evd_field is not None else None,
                is_anchor=_normalize_text(props.get(is_anchor_field)) if is_anchor_field is not None else None,
                kind=_coerce_int(props.get(node_kind_field)),
                grade=_coerce_int(props.get(node_grade_field)),
                kind_2=_coerce_int(props.get("kind_2")),
                grade_2=_coerce_int(props.get("grade_2")),
            )
        )
        if _should_emit_progress(index + 1, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool3] complex_divmerge: parsed {index + 1} node feature(s)")
    return parsed


def _parse_roads(
    *,
    road_features: list[dict[str, Any]],
    road_id_field: str,
    road_snode_field: str,
    road_enode_field: str,
    road_direction_field: str,
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> list[ParsedRoad]:
    parsed: list[ParsedRoad] = []
    seen_ids: set[str] = set()
    for index, feature in enumerate(road_features):
        props = feature["properties"]
        road_id = _required_id(props.get(road_id_field), "road id")
        if road_id in seen_ids:
            raise ValueError(f"Roads input has duplicate id '{road_id}'.")
        seen_ids.add(road_id)
        direction = _coerce_int(props.get(road_direction_field))
        if direction is None:
            raise ValueError(f"Road '{road_id}' is missing required direction for complex divmerge aggregation.")
        parsed.append(
            ParsedRoad(
                feature_index=index,
                road_id=road_id,
                snodeid=_required_id(props.get(road_snode_field), f"road '{road_id}' snodeid"),
                enodeid=_required_id(props.get(road_enode_field), f"road '{road_id}' enodeid"),
                direction=direction,
                length_m=float(feature["geometry"].length),
            )
        )
        if _should_emit_progress(index + 1, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool3] complex_divmerge: parsed {index + 1} road feature(s)")
    return parsed


def _is_complex_candidate(node: ParsedNode, *, has_evd_gate: bool, is_anchor_gate: bool) -> bool:
    group_id = node.mainnodeid or node.node_id
    if node.node_id != group_id:
        return False
    if node.kind_2 not in COMPLEX_CANDIDATE_KIND_VALUES:
        return False
    if has_evd_gate and node.has_evd != "yes":
        return False
    if is_anchor_gate and node.is_anchor != "no":
        return False
    return True


def _build_continuous_graph(
    *,
    starts_set: set[str],
    nodes_kind: dict[str, int],
    roads: list[ParsedRoad],
    progress_callback: ProgressCallback | None,
    progress_interval: int,
) -> tuple[list[ChainEdge], list[ChainComponent], dict[str, Any]]:
    adjacency_out, incident_map, direction_errors = _build_effective_directed_edges(roads)
    search_limit_m = max(CONTINUOUS_DIST_MAX_M, CONTINUOUS_DIVERGE_THEN_MERGE_DIST_MAX_M)
    edges_map: dict[tuple[str, str], ChainEdge] = {}
    visit_queue: deque[str] = deque(sorted(starts_set, key=_sort_key))
    seen_expand: set[str] = set()
    trace_diag: dict[str, list[dict[str, Any]]] = defaultdict(list)

    processed_seed_count = 0
    while visit_queue:
        src = visit_queue.popleft()
        if src in seen_expand:
            continue
        seen_expand.add(src)
        processed_seed_count += 1
        src_kind = nodes_kind.get(src)
        for first_edge in adjacency_out.get(src, []):
            result = _follow_to_next_deg3(
                start_nodeid=src,
                first_edge=first_edge,
                adjacency_out=adjacency_out,
                incident_map=incident_map,
                max_dist_m=float(search_limit_m),
            )
            if result is None:
                continue
            dst, dist_m, path_road_indices, diag = result
            dst_kind = nodes_kind.get(dst)
            distance_limit_m = _edge_dist_limit_m(src_kind=src_kind, dst_kind=dst_kind)
            trace_diag[src].append(
                {
                    "dst": dst,
                    "dist_m": float(dist_m),
                    "dist_limit_m": float(distance_limit_m),
                    "path_road_indices": [int(index) for index in path_road_indices],
                    "diag": dict(diag),
                }
            )
            if dst not in starts_set or float(dist_m) >= float(distance_limit_m):
                continue
            key = (src, dst)
            current = ChainEdge(
                src=src,
                dst=dst,
                dist_m=float(dist_m),
                path_road_indices=tuple(int(index) for index in path_road_indices),
            )
            previous = edges_map.get(key)
            if previous is None or current.dist_m < previous.dist_m:
                edges_map[key] = current
            if dst not in seen_expand:
                visit_queue.append(dst)
        if _should_emit_progress(processed_seed_count, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool3] complex_divmerge: expanded {processed_seed_count} candidate node(s)")

    chain_edges = sorted(edges_map.values(), key=lambda item: (_sort_key(item.src), _sort_key(item.dst), item.dist_m))
    component_nodes = {node_id for edge in chain_edges for node_id in (edge.src, edge.dst)}
    components: list[ChainComponent] = []
    component_sets = _connected_components(component_nodes, chain_edges)
    node_to_component_index: dict[str, int] = {}
    for index, nodes in enumerate(component_sets):
        for node_id in nodes:
            node_to_component_index[node_id] = index
    component_edges_by_index: dict[int, list[ChainEdge]] = defaultdict(list)
    for edge in chain_edges:
        component_index = node_to_component_index.get(edge.src)
        if component_index is not None and node_to_component_index.get(edge.dst) == component_index:
            component_edges_by_index[component_index].append(edge)
    for index, nodes in enumerate(component_sets):
        component_edges = component_edges_by_index.get(index, [])
        offsets_m, predecessors, topology_diag = _topo_offsets(component_nodes=nodes, component_edges=component_edges)
        components.append(
            ChainComponent(
                component_id=f"chain_{index:03d}",
                node_ids=tuple(sorted(nodes, key=_sort_key)),
                edges=tuple(sorted(component_edges, key=lambda item: (_sort_key(item.src), _sort_key(item.dst), item.dist_m))),
                offsets_m={node_id: float(value) for node_id, value in offsets_m.items()},
                predecessors=predecessors,
                diag={"topology": topology_diag},
            )
        )
        if _should_emit_progress(index + 1, progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool3] complex_divmerge: built {index + 1} chain component(s)")

    return chain_edges, components, {
        "direction_errors": direction_errors,
        "trace": {key: value for key, value in trace_diag.items()},
    }


def _build_effective_directed_edges(
    roads: list[ParsedRoad],
) -> tuple[dict[str, list[DirectedEdge]], dict[str, set[int]], list[str]]:
    adjacency_out: dict[str, list[DirectedEdge]] = defaultdict(list)
    incident_map: dict[str, set[int]] = defaultdict(set)
    direction_errors: list[str] = []
    for index, road in enumerate(roads):
        if road.direction not in {2, 3}:
            if road.direction not in {0, 1}:
                direction_errors.append(f"direction_invalid:road_idx={index}:value={road.direction}")
            continue
        incident_map[road.snodeid].add(index)
        incident_map[road.enodeid].add(index)
        if road.direction == 2:
            edge = DirectedEdge(src=road.snodeid, dst=road.enodeid, road_idx=index, length_m=road.length_m)
        else:
            edge = DirectedEdge(src=road.enodeid, dst=road.snodeid, road_idx=index, length_m=road.length_m)
        adjacency_out[edge.src].append(edge)
    return dict(adjacency_out), dict(incident_map), direction_errors


def _follow_to_next_deg3(
    *,
    start_nodeid: str,
    first_edge: DirectedEdge,
    adjacency_out: dict[str, list[DirectedEdge]],
    incident_map: dict[str, set[int]],
    max_dist_m: float,
) -> tuple[str, float, list[int], dict[str, Any]] | None:
    total = float(max(0.0, first_edge.length_m))
    if total > max_dist_m + 1e-9:
        return None
    prev_node = start_nodeid
    curr_node = first_edge.dst
    path_edges = [first_edge.road_idx]
    diag: dict[str, Any] = {"stopped_reason": "none", "deg2_steps": 0, "branch_stop": False}

    for _ in range(256):
        degree = len(incident_map.get(curr_node, set()))
        if degree >= 3:
            return curr_node, float(total), path_edges, diag
        if degree != 2:
            diag["stopped_reason"] = "dead_end_or_isolated"
            return None
        candidates = [edge for edge in adjacency_out.get(curr_node, []) if edge.dst != prev_node]
        if len(candidates) != 1:
            diag["stopped_reason"] = "deg2_out_not_unique"
            diag["branch_stop"] = True
            return None
        nxt = candidates[0]
        total += float(max(0.0, nxt.length_m))
        if total > max_dist_m + 1e-9:
            diag["stopped_reason"] = "distance_exceed"
            return None
        path_edges.append(nxt.road_idx)
        prev_node = curr_node
        curr_node = nxt.dst
        diag["deg2_steps"] = int(diag.get("deg2_steps", 0)) + 1
    diag["stopped_reason"] = "max_hops_reached"
    return None


def _connected_components(nodes: set[str], edges: list[ChainEdge]) -> list[set[str]]:
    undirected: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for edge in edges:
        undirected.setdefault(edge.src, set()).add(edge.dst)
        undirected.setdefault(edge.dst, set()).add(edge.src)
    components: list[set[str]] = []
    seen: set[str] = set()
    for node_id in sorted(nodes, key=_sort_key):
        if node_id in seen:
            continue
        component: set[str] = set()
        queue: deque[str] = deque([node_id])
        seen.add(node_id)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbour in sorted(undirected.get(current, set()), key=_sort_key):
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        components.append(component)
    return components


def _topo_offsets(
    *,
    component_nodes: set[str],
    component_edges: list[ChainEdge],
) -> tuple[dict[str, float], dict[str, tuple[str, ...]], dict[str, Any]]:
    predecessors: dict[str, list[tuple[str, float]]] = {node_id: [] for node_id in component_nodes}
    successors: dict[str, list[tuple[str, float]]] = {node_id: [] for node_id in component_nodes}
    indegree: dict[str, int] = {node_id: 0 for node_id in component_nodes}
    for edge in component_edges:
        predecessors[edge.dst].append((edge.src, float(edge.dist_m)))
        successors[edge.src].append((edge.dst, float(edge.dist_m)))
        indegree[edge.dst] += 1

    sources = [node_id for node_id, value in indegree.items() if value == 0]
    offsets: dict[str, float] = {node_id: 0.0 for node_id in sources}
    queue: deque[str] = deque(sorted(sources, key=_sort_key))
    processed = 0
    while queue:
        current = queue.popleft()
        processed += 1
        current_offset = float(offsets.get(current, 0.0))
        for nxt, dist_m in successors.get(current, []):
            candidate_offset = current_offset + float(dist_m)
            if nxt not in offsets or candidate_offset < float(offsets[nxt]):
                offsets[nxt] = float(candidate_offset)
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    is_dag = bool(processed == len(component_nodes))
    cycle_nodes = sorted([node_id for node_id, value in indegree.items() if value > 0], key=_sort_key)
    for node_id in cycle_nodes:
        offsets.setdefault(node_id, 0.0)
    predecessor_ids = {
        node_id: tuple(sorted((pred for pred, _ in items), key=_sort_key))
        for node_id, items in predecessors.items()
    }
    return offsets, predecessor_ids, {
        "is_dag": is_dag,
        "sources": sorted(sources, key=_sort_key),
        "cycle_nodes": cycle_nodes,
    }


def _edge_dist_limit_m(*, src_kind: int | None, dst_kind: int | None) -> float:
    if int(src_kind or 0) == 16 and int(dst_kind or 0) == 8:
        return CONTINUOUS_DIVERGE_THEN_MERGE_DIST_MAX_M
    return CONTINUOUS_DIST_MAX_M


def _resolved_grade(node: ParsedNode) -> int | None:
    for value in (node.grade, node.grade_2):
        if value is not None and value >= 0:
            return int(value)
    return None


def _grade_sort_tuple(node: ParsedNode) -> tuple[int, int, tuple[int, int | str]]:
    grade = _resolved_grade(node)
    rank = 9999 if grade is None or grade <= 0 else int(grade)
    grade_2_rank = int(node.grade_2) if node.grade_2 is not None and node.grade_2 > 0 else 9999
    return rank, grade_2_rank, _sort_key(node.node_id)


def _empty_roundabout_summary() -> dict[str, Any]:
    return {
        "roundabout_roadtype_bit": ROUNDABOUT_ROADTYPE_BIT,
        "roundabout_kind_value": ROUNDABOUT_KIND_VALUE,
        "roundabout_road_count": 0,
        "roundabout_group_count": 0,
        "roundabout_mainnode_count": 0,
        "roundabout_member_node_count": 0,
        "roundabout_updated_node_count": 0,
        "roadtype_missing_count": 0,
        "roadtype_empty_count": 0,
        "roadtype_invalid_count": 0,
        "group_ids": [],
        "groups": [],
        "roadtype_issue_rows": [],
    }


def _empty_complex_summary() -> dict[str, Any]:
    return {
        "complex_kind_value": COMPLEX_DIVMERGE_KIND_VALUE,
        "candidate_kind_values": sorted(COMPLEX_CANDIDATE_KIND_VALUES),
        "has_evd_gate_applied": False,
        "is_anchor_gate_applied": False,
        "candidate_node_count": 0,
        "chain_edge_count": 0,
        "chain_component_count": 0,
        "complex_junction_count": 0,
        "aggregated_component_count": 0,
        "skipped_component_count": 0,
        "updated_node_count": 0,
        "complex_mainnodeids": [],
        "diag": {},
        "rows": [],
    }


def _optional_field(features: list[VectorFeature], candidates: list[str]) -> str | None:
    for feature in features:
        resolved = resolve_case_insensitive_field_name(feature.properties, candidates)
        if resolved is not None:
            return resolved
    return None


def _optional_field_from_dict_features(features: list[dict[str, Any]], candidates: list[str]) -> str | None:
    for feature in features:
        resolved = resolve_case_insensitive_field_name(feature["properties"], candidates)
        if resolved is not None:
            return resolved
    return None


def _first_non_empty_value(features: list[VectorFeature], field_name: str) -> Any:
    for feature in features:
        value = feature.properties.get(field_name)
        if _normalize_scalar(value) is not None:
            return value
    return None


def _typed_like(sample: Any, value: int) -> Any:
    if isinstance(sample, str):
        return str(value)
    if isinstance(sample, float):
        return float(value)
    return int(value)


def _required_id(value: Any, label: str) -> str:
    normalized = _normalize_id(value)
    if normalized is None:
        raise ValueError(f"Missing required {label}")
    return normalized


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none", "nan"}:
            return None
        return text
    return value


def _normalize_id(value: Any) -> str | None:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    if isinstance(normalized, int):
        return str(normalized)
    if isinstance(normalized, float) and normalized.is_integer():
        return str(int(normalized))
    return str(normalized)


def _valid_mainnodeid(value: Any) -> str | None:
    normalized = _normalize_id(value)
    if normalized in {None, "0", "0.0"}:
        return None
    return normalized


def _normalize_text(value: Any) -> str | None:
    normalized = _normalize_scalar(value)
    return None if normalized is None else str(normalized)


def _coerce_int(value: Any) -> int | None:
    normalized = _normalize_scalar(value)
    if normalized is None or isinstance(normalized, bool):
        return None
    if isinstance(normalized, int):
        return int(normalized)
    if isinstance(normalized, float):
        return int(normalized) if normalized.is_integer() else None
    try:
        return int(str(normalized), 10)
    except ValueError:
        try:
            parsed = float(str(normalized))
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else None


def _bit_enabled(value: int | None, bit_index: int) -> bool:
    return bool(value is not None and (int(value) & (1 << bit_index)))


def _sort_key(value: str) -> tuple[int, int | str]:
    text = str(value)
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def _elapsed_since(started: float) -> float:
    return time.perf_counter() - started


def _should_emit_progress(index: int, progress_interval: int) -> bool:
    return progress_interval > 0 and index % progress_interval == 0


def _items_per_second(item_count: int, elapsed_seconds: float) -> float | None:
    if elapsed_seconds <= 0:
        return None
    return round(float(item_count) / elapsed_seconds, 3)


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


__all__ = [
    "T08NodesTypeAggregationArtifacts",
    "run_t08_nodes_type_aggregation",
]
