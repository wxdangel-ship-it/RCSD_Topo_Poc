from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

from shapely.geometry import Point
from shapely.ops import unary_union

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _parse_access,
    _roads_near_segments,
    _segment_geometry,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_models import (
    RoadRecord,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_models import (
    P12RR1Config,
)


def build_truth_free_case_candidates(
    *,
    case_key: str,
    skeleton: Mapping[str, Any],
    t01_roads: Sequence[RoadRecord],
    raw_rcsd_roads: Sequence[RoadRecord],
    config: P12RR1Config,
) -> dict[str, list[dict[str, Any]]]:
    segments = list(skeleton.get("segments") or [])
    advance_right = [
        row
        for row in segments
        if str(row.get("segment_type")) == "ADVANCE_RIGHT"
    ]
    standard = {
        str(row["segment_id"]): row
        for row in segments
        if str(row.get("segment_type")) != "ADVANCE_RIGHT"
    }
    t01_by_id = {road.road_id: road for road in t01_roads}
    raw_advance = [
        road for road in raw_rcsd_roads if road.is_advance_right
    ]
    raw_by_id = {road.road_id: road for road in raw_advance}
    incident_non_advance = _incident_non_advance(raw_rcsd_roads)
    bundles = _build_bundles(raw_advance, config)

    ar_geometries = {
        str(segment["segment_id"]): _segment_geometry(
            segment,
            t01_by_id,
        )
        for segment in advance_right
    }
    local = _roads_near_segments(
        ar_geometries,
        raw_advance,
        max_distance_m=config.local_distance_m,
    )

    candidate_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    object_rows: list[dict[str, Any]] = []
    for segment in sorted(
        advance_right,
        key=lambda row: str(row["segment_id"]),
    ):
        object_id = str(segment["segment_id"])
        source_owner, source_node = _parse_access(
            segment.get("source_segment_access")
        )
        target_owner, target_node = _parse_access(
            segment.get("target_segment_access")
        )
        owner_valid = (
            bool(segment.get("access_valid"))
            and source_owner in standard
            and target_owner in standard
            and bool(source_node)
            and bool(target_node)
        )
        control_ids = {
            item["road"].road_id
            for item in local.get(object_id, [])
        }
        selected_by_endpoint: set[str] = set()
        bundle_evidence: dict[str, dict[str, Any]] = {}
        if owner_valid:
            source_geometry = _owner_geometry(
                standard[source_owner],
                t01_by_id,
            )
            target_geometry = _owner_geometry(
                standard[target_owner],
                t01_by_id,
            )
            for bundle in bundles:
                evidence = _bundle_owner_evidence(
                    bundle=bundle,
                    source_owner=source_owner,
                    target_owner=target_owner,
                    source_geometry=source_geometry,
                    target_geometry=target_geometry,
                    incident_non_advance=incident_non_advance,
                    config=config,
                )
                bundle_evidence[str(bundle["bundle_id"])] = evidence
                if evidence["endpoint_candidate_selected"]:
                    selected_by_endpoint.update(bundle["road_ids"])
                if (
                    evidence["endpoint_candidate_selected"]
                    or evidence["orientation"] == "AMBIGUOUS"
                    or control_ids.intersection(bundle["road_ids"])
                ):
                    evidence_rows.append(
                        {
                            **evidence,
                            "case_key": case_key,
                            "control_road_ids_in_bundle": sorted(
                                control_ids.intersection(
                                    bundle["road_ids"]
                                )
                            ),
                            "object_id": object_id,
                            "schema_version": (
                                "p05-scheme-a-p2-p3-p12r-r1-v1"
                            ),
                        }
                    )

        treatment_ids = control_ids.union(selected_by_endpoint)
        for road_id in sorted(treatment_ids):
            road = raw_by_id[road_id]
            bundle = next(
                value
                for value in bundles
                if road_id in value["road_ids"]
            )
            evidence = bundle_evidence.get(str(bundle["bundle_id"]))
            sources = []
            if road_id in control_ids:
                sources.append("LOCAL_5M")
            if road_id in selected_by_endpoint:
                sources.append("ENDPOINT_JUNCTION")
            candidate_rows.append(
                {
                    "bundle_id": bundle["bundle_id"],
                    "candidate_road_id": road_id,
                    "candidate_sources": sorted(sources),
                    "case_key": case_key,
                    "endpoint_evidence_complete": bool(
                        evidence
                        and evidence["endpoint_candidate_selected"]
                    ),
                    "object_id": object_id,
                    "orientation": (
                        None
                        if evidence is None
                        else evidence["orientation"]
                    ),
                    "raw_enodeid": road.enodeid,
                    "raw_snodeid": road.snodeid,
                    "schema_version": (
                        "p05-scheme-a-p2-p3-p12r-r1-v1"
                    ),
                }
            )

        object_rows.append(
            {
                "access_valid_for_candidate": owner_valid,
                "case_key": case_key,
                "control_candidate_road_ids": sorted(control_ids),
                "object_id": object_id,
                "schema_version": "p05-scheme-a-p2-p3-p12r-r1-v1",
                "source_access_node_id": source_node,
                "source_owner_segment_id": source_owner,
                "target_access_node_id": target_node,
                "target_owner_segment_id": target_owner,
                "treatment_candidate_road_ids": sorted(treatment_ids),
            }
        )
    return {
        "candidates": candidate_rows,
        "evidence": evidence_rows,
        "objects": object_rows,
    }


def _build_bundles(
    roads: Sequence[RoadRecord],
    config: P12RR1Config,
) -> list[dict[str, Any]]:
    parent = list(range(len(roads)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    node_owner: dict[str, int] = {}
    for index, road in enumerate(roads):
        for node_id in road.endpoint_ids:
            if node_id in node_owner:
                union(index, node_owner[node_id])
            else:
                node_owner[node_id] = index

    starts = [_start_point(road) for road in roads]
    ends = [_end_point(road) for road in roads]
    geometric_edges: list[tuple[str, str, str]] = []
    for left in range(len(roads)):
        for right in range(left + 1, len(roads)):
            sequential_gap = min(
                float(ends[left].distance(starts[right])),
                float(ends[right].distance(starts[left])),
            )
            parallel_source_gap = float(
                starts[left].distance(starts[right])
            )
            parallel_target_gap = float(
                ends[left].distance(ends[right])
            )
            relation = ""
            if sequential_gap <= config.sequential_gap_m:
                relation = "SEQUENTIAL_GAP"
            elif (
                parallel_source_gap
                <= config.parallel_endpoint_gap_m
                and parallel_target_gap
                <= config.parallel_endpoint_gap_m
            ):
                relation = "PARALLEL_ENDPOINTS"
            if relation:
                union(left, right)
                geometric_edges.append(
                    (roads[left].road_id, roads[right].road_id, relation)
                )

    grouped: dict[int, list[RoadRecord]] = defaultdict(list)
    for index, road in enumerate(roads):
        grouped[find(index)].append(road)

    bundles = []
    for values in grouped.values():
        values.sort(key=lambda road: road.road_id)
        road_ids = [road.road_id for road in values]
        edge_rows = [
            {
                "left_road_id": left,
                "relation": relation,
                "right_road_id": right,
            }
            for left, right, relation in geometric_edges
            if left in road_ids and right in road_ids
        ]
        bundles.append(
            {
                "bundle_id": hashlib.sha256(
                    "\n".join(road_ids).encode("utf-8")
                ).hexdigest()[:16],
                "geometric_edges": edge_rows,
                "road_ids": road_ids,
                "roads": values,
            }
        )
    bundles.sort(key=lambda row: str(row["bundle_id"]))
    return bundles


def _bundle_owner_evidence(
    *,
    bundle: Mapping[str, Any],
    source_owner: str,
    target_owner: str,
    source_geometry: Any,
    target_geometry: Any,
    incident_non_advance: Mapping[str, Sequence[RoadRecord]],
    config: P12RR1Config,
) -> dict[str, Any]:
    source_nodes, target_nodes = _directed_boundary_nodes(bundle["roads"])
    source_incident = _incident_roads(source_nodes, incident_non_advance)
    target_incident = _incident_roads(target_nodes, incident_non_advance)
    forward_source = _minimum_distance(source_incident, source_geometry)
    forward_target = _minimum_distance(target_incident, target_geometry)
    reverse_source = _minimum_distance(source_incident, target_geometry)
    reverse_target = _minimum_distance(target_incident, source_geometry)
    forward_max = _finite_max(forward_source, forward_target)
    reverse_max = _finite_max(reverse_source, reverse_target)
    best = _finite_min(forward_max, reverse_max)

    if best is None or best > config.owner_carrier_distance_m:
        orientation = "UNRESOLVED"
        selected = False
    elif source_owner == target_owner:
        orientation = "SAME_OWNER"
        selected = True
    elif (
        forward_max is not None
        and reverse_max is not None
        and abs(forward_max - reverse_max)
        <= config.orientation_tie_epsilon_m
    ):
        orientation = "AMBIGUOUS"
        selected = False
    elif reverse_max is None or (
        forward_max is not None and forward_max < reverse_max
    ):
        orientation = "FORWARD"
        selected = True
    else:
        orientation = "REVERSE"
        selected = True

    return {
        "best_owner_carrier_distance_m": best,
        "bundle_id": bundle["bundle_id"],
        "bundle_road_ids": list(bundle["road_ids"]),
        "endpoint_candidate_selected": selected,
        "forward_source_distance_m": forward_source,
        "forward_target_distance_m": forward_target,
        "geometric_edges": list(bundle["geometric_edges"]),
        "orientation": orientation,
        "reverse_source_distance_m": reverse_source,
        "reverse_target_distance_m": reverse_target,
        "source_boundary_node_ids": source_nodes,
        "source_incident_carrier_road_ids": [
            road.road_id for road in source_incident
        ],
        "source_owner_segment_id": source_owner,
        "target_boundary_node_ids": target_nodes,
        "target_incident_carrier_road_ids": [
            road.road_id for road in target_incident
        ],
        "target_owner_segment_id": target_owner,
    }


def _incident_non_advance(
    roads: Sequence[RoadRecord],
) -> dict[str, list[RoadRecord]]:
    result: dict[str, list[RoadRecord]] = defaultdict(list)
    for road in roads:
        if road.is_advance_right:
            continue
        for node_id in road.endpoint_ids:
            result[node_id].append(road)
    for values in result.values():
        values.sort(key=lambda road: road.road_id)
    return dict(result)


def _directed_boundary_nodes(
    roads: Sequence[RoadRecord],
) -> tuple[list[str], list[str]]:
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    for road in roads:
        if road.snodeid:
            outgoing[road.snodeid] += 1
        if road.enodeid:
            incoming[road.enodeid] += 1
    nodes = set(incoming).union(outgoing)
    source = sorted(
        node for node in nodes if outgoing[node] and not incoming[node]
    )
    target = sorted(
        node for node in nodes if incoming[node] and not outgoing[node]
    )
    return source, target


def _incident_roads(
    node_ids: Sequence[str],
    index: Mapping[str, Sequence[RoadRecord]],
) -> list[RoadRecord]:
    values = {
        road.road_id: road
        for node_id in node_ids
        for road in index.get(node_id, [])
    }
    return [values[road_id] for road_id in sorted(values)]


def _owner_geometry(
    segment: Mapping[str, Any],
    t01_by_id: Mapping[str, RoadRecord],
) -> Any:
    road_ids = [
        str(value) for value in segment.get("swsd_road_ids") or []
    ]
    values = [
        t01_by_id[road_id].geometry
        for road_id in road_ids
        if road_id in t01_by_id
    ]
    if not values or len(values) != len(road_ids):
        raise ValueError(
            f"ordinary Segment Road lineage is incomplete: "
            f"{segment.get('segment_id')}"
        )
    return unary_union(values)


def _minimum_distance(
    roads: Sequence[RoadRecord],
    geometry: Any,
) -> float | None:
    if not roads:
        return None
    value = min(float(road.geometry.distance(geometry)) for road in roads)
    return value if math.isfinite(value) else None


def _finite_max(*values: float | None) -> float | None:
    if any(value is None for value in values):
        return None
    return max(float(value) for value in values if value is not None)


def _finite_min(*values: float | None) -> float | None:
    finite = [float(value) for value in values if value is not None]
    return min(finite) if finite else None


def _start_point(road: RoadRecord) -> Point:
    return Point(road.geometry.coords[0])


def _end_point(road: RoadRecord) -> Point:
    return Point(road.geometry.coords[-1])
