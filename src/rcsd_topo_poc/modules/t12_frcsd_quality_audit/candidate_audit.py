from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

import geopandas as gpd

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import (
    NodeCanonicalizer,
)

from .anchor_portals import (
    AnchorRecord,
    associate_t07_surfaces,
    build_anchor_map,
    raw_portal_candidates,
    validate_t07_truth_anchors,
)
from .carrier_graph import (
    GraphBundle,
    build_graph,
    build_node_context,
    build_raw_node_context,
    directional_swsd_carrier,
    field_name,
    normalize_id,
    parse_ids,
    path_metrics,
    required_swsd_directions,
    shortest_path_between_sets,
)
from .inputs import LoadedInputs
from .models import AuditConfig, EvidenceLayers
from .semantic_carrier import (
    STANDARD_SURFACE_TOLERANCE_M,
    evaluate_portal_constrained_semantic_carrier,
)
from .surface_portal_carrier import (
    ROAD_SURFACE_TOPOLOGY_TOLERANCE_M,
    evaluate_t07_road_surface_carrier,
    not_evaluated_surface_carrier,
)


def audit_frcsd_candidates(
    loaded: LoadedInputs,
    config: AuditConfig,
) -> tuple[list[dict[str, Any]], EvidenceLayers, dict[str, Any]]:
    anchors = build_anchor_map(loaded.t05_anchor_audit)
    swsd_canonicalizer, _, swsd_raw_points = build_node_context(loaded.swsd_nodes)
    frcsd_canonicalizer, _, frcsd_raw_points = build_node_context(
        loaded.frcsd_nodes
    )
    raw_canonicalizer, _, raw_frcsd_points = build_raw_node_context(
        loaded.frcsd_nodes
    )
    truth_audit = validate_t07_truth_anchors(
        anchors,
        loaded.rcsd_intersections,
        loaded.frcsd_nodes,
        tolerance_m=config.portal_radius_m,
    )
    t07_surfaces, t07_surface_audit = associate_t07_surfaces(
        anchors,
        swsd_raw_points,
        loaded.rcsd_intersections,
        tolerance_m=config.portal_radius_m,
    )
    full_graph = build_graph(loaded.frcsd_roads, frcsd_canonicalizer)
    raw_full_graph = build_graph(loaded.frcsd_roads, raw_canonicalizer)
    segment_id_field = field_name(loaded.segments, "id")
    segment_pair_field = field_name(loaded.segments, "pair_nodes")
    segment_roads_field = field_name(loaded.segments, "roads")
    swsd_road_id_field = field_name(loaded.swsd_roads, "id")
    swsd_road_ids = loaded.swsd_roads[swsd_road_id_field].map(normalize_id)
    full_nodes = _all_graph_nodes(full_graph)
    canonical_points = _canonical_points(
        frcsd_canonicalizer,
        frcsd_raw_points,
    )
    drivezone_union = (
        loaded.drivezone.geometry.union_all()
        if loaded.drivezone is not None and not loaded.drivezone.empty
        else None
    )
    candidates: list[dict[str, Any]] = []
    layers = EvidenceLayers()
    counters: Counter[str] = Counter()
    for _, segment in loaded.segments.iterrows():
        counters["segment_total"] += 1
        segment_id = normalize_id(segment[segment_id_field])
        pair_nodes = parse_ids(segment[segment_pair_field])
        if len(pair_nodes) != 2 or pair_nodes[0] == pair_nodes[1]:
            counters["invalid_pair_count"] += 1
            continue
        if any(node_id not in anchors for node_id in pair_nodes):
            counters["missing_anchor_count"] += 1
            continue
        geometry = segment.geometry
        if geometry is None or geometry.is_empty or geometry.length <= 0:
            counters["invalid_segment_geometry_count"] += 1
            continue
        road_ids = set(parse_ids(segment[segment_roads_field]))
        segment_roads = loaded.swsd_roads.loc[swsd_road_ids.isin(road_ids)].copy()
        required_directions = required_swsd_directions(
            segment_roads,
            pair_nodes,
            swsd_canonicalizer,
        )
        if not required_directions:
            counters["invalid_swsd_direction_count"] += 1
            continue
        anchor_pair = [anchors[node_id] for node_id in pair_nodes]
        base_nodes = [
            frcsd_canonicalizer.canonicalize(anchor.base_id)
            for anchor in anchor_pair
        ]
        if any(node_id not in canonical_points for node_id in base_nodes):
            counters["anchor_missing_in_raw_frcsd_count"] += 1
            continue
        counters["audited_both_anchor_segment_count"] += 1
        local_roads = loaded.frcsd_roads.loc[
            loaded.frcsd_roads.geometry.intersects(
                geometry.buffer(config.local_corridor_m)
            )
        ].copy()
        local_graph = build_graph(local_roads, frcsd_canonicalizer)
        coarse_full_missing = _missing_directions(
            required_directions,
            full_graph,
            base_nodes,
        )
        coarse_local_missing = _missing_directions(
            required_directions,
            local_graph,
            base_nodes,
        )
        if not coarse_full_missing and not coarse_local_missing:
            counters["coarse_equivalent_count"] += 1
            continue
        if not _is_fully_inner(geometry, loaded.crop_inner_geometry):
            counters["crop_edge_excluded_count"] += 1
            continue
        raw_local_graph = build_graph(local_roads, raw_canonicalizer)
        candidate = _enrich_candidate(
            segment_id=segment_id,
            segment_geometry=geometry,
            pair_nodes=pair_nodes,
            segment_roads=segment_roads,
            required_directions=required_directions,
            anchors=anchor_pair,
            base_nodes=base_nodes,
            swsd_canonicalizer=swsd_canonicalizer,
            swsd_raw_points=swsd_raw_points,
            frcsd_canonicalizer=frcsd_canonicalizer,
            frcsd_raw_points=raw_frcsd_points,
            frcsd_nodes=loaded.frcsd_nodes,
            full_graph=raw_full_graph,
            local_graph=raw_local_graph,
            semantic_full_graph=full_graph,
            semantic_local_graph=local_graph,
            t07_surfaces=t07_surfaces,
            t07_surface_ids=t07_surface_audit.get("surface_ids", {}),
            t06_cross_evidence=loaded.t06_cross_evidence.get(segment_id, {}),
            config=config,
            layers=layers,
        )
        candidate["coarse_full_missing_directions"] = coarse_full_missing
        candidate["coarse_local_missing_directions"] = coarse_local_missing
        candidate["drivezone_in_road_ratio"] = (
            float(geometry.intersection(drivezone_union).length / geometry.length)
            if drivezone_union is not None
            else None
        )
        candidate["geometry"] = geometry
        candidates.append(candidate)
        layers.candidate_segments.append(
            {
                "candidate_id": segment_id,
                "segment_id": segment_id,
                "candidate_status": "candidate_pending_decision",
                "suggested_issue_type": candidate["suggested_issue_type"],
                "failed_directions": "|".join(candidate["failed_directions"]),
                "raw_failed_directions": "|".join(
                    candidate["raw_failed_directions"]
                ),
                "portal_equivalent": candidate[
                    "automatic_all_directions_equivalent"
                ],
                "equivalence_basis": candidate["automatic_equivalence_basis"],
                "drivezone_in_road_ratio": candidate["drivezone_in_road_ratio"],
                "geometry": geometry,
            }
        )
    candidates.sort(key=lambda row: row["segment_id"])
    counters["candidate_count"] = len(candidates)
    counters["audited_segment_count"] = counters[
        "audited_both_anchor_segment_count"
    ]
    counters["portal_equivalent_candidate_count"] = sum(
        bool(row["automatic_all_directions_equivalent"]) for row in candidates
    )
    counters["raw_equivalent_candidate_count"] = sum(
        row["automatic_equivalence_basis"] == "raw_carrier"
        for row in candidates
    )
    counters["semantic_equivalent_candidate_count"] = sum(
        row["automatic_equivalence_basis"]
        == "portal_constrained_semantic_carrier"
        for row in candidates
    )
    counters["t07_road_surface_equivalent_candidate_count"] = sum(
        row["automatic_equivalence_basis"] == "t07_road_surface_carrier"
        for row in candidates
    )
    return candidates, layers, {
        "counts": dict(counters),
        "t07_truth_audit": truth_audit,
        "t07_surface_audit": t07_surface_audit,
        "candidate_graph_node_count": len(full_nodes),
        "candidate_graph_edge_count": len(full_graph.edges),
        "verdict_graph_node_count": len(_all_graph_nodes(raw_full_graph)),
        "verdict_graph_edge_count": len(raw_full_graph.edges),
        "drivezone_reference_provided": drivezone_union is not None,
        "drivezone_affects_verdict": False,
        "semantic_carrier_policy": {
            "role": "raw_failure_exclusion_only",
            "physical_road_required": True,
            "standard_surface_tolerance_m": STANDARD_SURFACE_TOLERANCE_M,
            "non_t07_endpoint_max_gap_m": config.portal_radius_m,
            "internal_alias_max_gap_m": config.portal_radius_m,
            "path_thresholds": {
                "max_length_ratio": config.path_max_length_ratio,
                "max_additive_m": config.path_max_additive_m,
                "max_corridor_distance_m": config.path_max_corridor_distance_m,
            },
        },
        "t07_road_surface_carrier_policy": {
            "role": "raw_and_node_portal_failure_exclusion_only",
            "required_anchor": "dual_t07_unique_standard_surface",
            "physical_directed_road_required": True,
            "surface_access": [
                "road_surface_intersection",
                "anchor_one_hop_frontier",
            ],
            "frontier_support_surface_tolerance_m": (
                ROAD_SURFACE_TOPOLOGY_TOLERANCE_M
            ),
            "distance_gate_role": "audit_only",
            "hard_path_thresholds": {
                "max_length_ratio": config.path_max_length_ratio,
                "max_additive_m": config.path_max_additive_m,
            },
            "audit_distance_thresholds": {
                "portal_radius_m": config.portal_radius_m,
                "max_corridor_distance_m": config.path_max_corridor_distance_m,
            },
        },
    }


def _enrich_candidate(
    *,
    segment_id: str,
    segment_geometry: Any,
    pair_nodes: list[str],
    segment_roads: gpd.GeoDataFrame,
    required_directions: list[str],
    anchors: list[AnchorRecord],
    base_nodes: list[str],
    swsd_canonicalizer: NodeCanonicalizer,
    swsd_raw_points: Mapping[str, Any],
    frcsd_canonicalizer: NodeCanonicalizer,
    frcsd_raw_points: Mapping[str, Any],
    frcsd_nodes: gpd.GeoDataFrame,
    full_graph: GraphBundle,
    local_graph: GraphBundle,
    semantic_full_graph: GraphBundle,
    semantic_local_graph: GraphBundle,
    t07_surfaces: Mapping[str, Any],
    t07_surface_ids: Mapping[str, str],
    t06_cross_evidence: Mapping[str, Any],
    config: AuditConfig,
    layers: EvidenceLayers,
) -> dict[str, Any]:
    direction_evidence: list[dict[str, Any]] = []
    raw_failed_directions: list[str] = []
    failed_directions: list[str] = []
    semantic_resolved_directions: list[str] = []
    surface_resolved_directions: list[str] = []
    issue_types: set[str] = set()
    for direction in required_directions:
        carrier = directional_swsd_carrier(
            direction,
            pair_nodes,
            segment_roads,
            swsd_canonicalizer,
            swsd_raw_points,
        )
        source_index, target_index = (0, 1) if direction == "pair0_to_pair1" else (1, 0)
        starts = raw_portal_candidates(
            anchor=anchors[source_index],
            portal_point=carrier["source_point"],
            frcsd_nodes=frcsd_nodes,
            raw_node_points=frcsd_raw_points,
            eligible_raw_ids=local_graph.undirected,
            radius_m=config.portal_radius_m,
            direction_role="start",
            truth_surface=t07_surfaces.get(pair_nodes[source_index]),
        )
        ends = raw_portal_candidates(
            anchor=anchors[target_index],
            portal_point=carrier["target_point"],
            frcsd_nodes=frcsd_nodes,
            raw_node_points=frcsd_raw_points,
            eligible_raw_ids=local_graph.undirected,
            radius_m=config.portal_radius_m,
            direction_role="end",
            truth_surface=t07_surfaces.get(pair_nodes[target_index]),
        )
        start_ids = {row["canonical_id"] for row in starts}
        end_ids = {row["canonical_id"] for row in ends}
        paths = {
            "local_directed": shortest_path_between_sets(
                local_graph.directed, start_ids, end_ids
            ),
            "full_directed": shortest_path_between_sets(
                full_graph.directed, start_ids, end_ids
            ),
            "local_undirected": shortest_path_between_sets(
                local_graph.undirected, start_ids, end_ids
            ),
            "full_undirected": shortest_path_between_sets(
                full_graph.undirected, start_ids, end_ids
            ),
        }
        metrics = {
            name: path_metrics(
                path,
                local_graph.edges if name.startswith("local_") else full_graph.edges,
                segment_geometry,
                carrier["length_m"],
                config,
            )
            for name, path in paths.items()
        }
        semantic_start_ids = {
            frcsd_canonicalizer.canonicalize(row["raw_id"]) for row in starts
        }
        semantic_end_ids = {
            frcsd_canonicalizer.canonicalize(row["raw_id"]) for row in ends
        }
        semantic_paths = {
            "semantic_local_directed": shortest_path_between_sets(
                semantic_local_graph.directed,
                semantic_start_ids,
                semantic_end_ids,
            ),
            "semantic_full_directed": shortest_path_between_sets(
                semantic_full_graph.directed,
                semantic_start_ids,
                semantic_end_ids,
            ),
            "semantic_local_undirected": shortest_path_between_sets(
                semantic_local_graph.undirected,
                semantic_start_ids,
                semantic_end_ids,
            ),
            "semantic_full_undirected": shortest_path_between_sets(
                semantic_full_graph.undirected,
                semantic_start_ids,
                semantic_end_ids,
            ),
        }
        semantic_metrics = {
            name: path_metrics(
                path,
                (
                    semantic_local_graph.edges
                    if name.startswith("semantic_local_")
                    else semantic_full_graph.edges
                ),
                segment_geometry,
                carrier["length_m"],
                config,
            )
            for name, path in semantic_paths.items()
        }
        local_ok = bool(metrics["local_directed"]["accepted_equivalent_carrier"])
        semantic_carrier = evaluate_portal_constrained_semantic_carrier(
            path=semantic_paths["semantic_local_directed"],
            metrics=semantic_metrics["semantic_local_directed"],
            graph=semantic_local_graph,
            start_portals=starts,
            end_portals=ends,
            source_anchor=anchors[source_index],
            target_anchor=anchors[target_index],
            source_truth_surface=t07_surfaces.get(pair_nodes[source_index]),
            target_truth_surface=t07_surfaces.get(pair_nodes[target_index]),
            canonicalizer=frcsd_canonicalizer,
            raw_node_points=frcsd_raw_points,
            portal_radius_m=config.portal_radius_m,
        )
        surface_carrier = not_evaluated_surface_carrier(
            "existing_carrier_layer_sufficient"
        )
        if not local_ok and not semantic_carrier["accepted_equivalent_carrier"]:
            surface_carrier = evaluate_t07_road_surface_carrier(
                graph=semantic_local_graph,
                canonicalizer=frcsd_canonicalizer,
                raw_node_points=frcsd_raw_points,
                source_anchor=anchors[source_index],
                target_anchor=anchors[target_index],
                source_surface=t07_surfaces.get(pair_nodes[source_index]),
                target_surface=t07_surfaces.get(pair_nodes[target_index]),
                source_surface_id=str(
                    t07_surface_ids.get(pair_nodes[source_index], "")
                ),
                target_surface_id=str(
                    t07_surface_ids.get(pair_nodes[target_index], "")
                ),
                source_swsd_point=carrier["source_point"],
                target_swsd_point=carrier["target_point"],
                reference_geometry=segment_geometry,
                reference_length_m=carrier["length_m"],
                config=config,
                preferred_source_nodes=semantic_start_ids,
            )
        if not local_ok:
            raw_failed_directions.append(direction)
            if semantic_carrier["accepted_equivalent_carrier"]:
                semantic_resolved_directions.append(direction)
            elif surface_carrier.evidence["accepted_equivalent_carrier"]:
                surface_resolved_directions.append(direction)
            else:
                failed_directions.append(direction)
                if (
                    not semantic_metrics["semantic_local_directed"][
                        "accepted_equivalent_carrier"
                    ]
                    and semantic_metrics["semantic_local_undirected"][
                        "accepted_equivalent_carrier"
                    ]
                ):
                    issue_types.add("directed_carrier_missing")
                else:
                    issue_types.add("required_local_connectivity_missing")
        for portal in starts + ends:
            point = frcsd_raw_points.get(portal["raw_id"])
            layers.anchor_portals.append(
                {
                    "candidate_id": segment_id,
                    "direction": direction,
                    **portal,
                    "geometry": point,
                }
            )
        _append_path_layers(
            layers=layers,
            candidate_id=segment_id,
            direction=direction,
            carrier=carrier,
            segment_roads=segment_roads,
            swsd_road_id_field=field_name(segment_roads, "id"),
            paths={
                **paths,
                **semantic_paths,
                "t07_road_surface_directed": surface_carrier.path,
            },
            metrics={
                **metrics,
                **semantic_metrics,
                "t07_road_surface_directed": surface_carrier.evidence,
            },
            local_graph=local_graph,
            full_graph=full_graph,
            semantic_local_graph=semantic_local_graph,
            semantic_full_graph=semantic_full_graph,
        )
        direction_evidence.append(
            {
                "direction": direction,
                "source_swsd_portal": carrier["source_swsd_portal"],
                "target_swsd_portal": carrier["target_swsd_portal"],
                "swsd_road_ids": carrier["road_ids"],
                "swsd_length_m": carrier["length_m"],
                "start_portal_candidates": starts,
                "end_portal_candidates": ends,
                **metrics,
                **semantic_metrics,
                "portal_constrained_semantic_directed": semantic_carrier,
                "t07_road_surface_directed": surface_carrier.evidence,
                "formal_equivalent_carrier": bool(
                    local_ok
                    or semantic_carrier["accepted_equivalent_carrier"]
                    or surface_carrier.evidence["accepted_equivalent_carrier"]
                ),
                "equivalence_basis": (
                    "raw_carrier"
                    if local_ok
                    else "portal_constrained_semantic_carrier"
                    if semantic_carrier["accepted_equivalent_carrier"]
                    else "t07_road_surface_carrier"
                    if surface_carrier.evidence["accepted_equivalent_carrier"]
                    else ""
                ),
            }
        )
    if "directed_carrier_missing" in issue_types:
        suggested_issue_type = "directed_carrier_missing"
    elif "required_local_connectivity_missing" in issue_types:
        suggested_issue_type = "required_local_connectivity_missing"
    else:
        suggested_issue_type = ""
    return {
        "candidate_id": segment_id,
        "segment_id": segment_id,
        "candidate_status": "candidate_pending_decision",
        "review_status": "",
        "review_reason": "",
        "suggested_issue_type": suggested_issue_type,
        "required_directions": required_directions,
        "raw_failed_directions": raw_failed_directions,
        "failed_directions": failed_directions,
        "anchor_modules": [anchor.source_module for anchor in anchors],
        "base_nodes": base_nodes,
        "anchor_groups": [list(anchor.grouped_node_ids) for anchor in anchors],
        "anchor_confidence": _anchor_confidence(
            pair_nodes,
            anchors,
            t07_surfaces,
        ),
        "t07_surface_statuses": [
            (
                "unique_surface"
                if anchor.source_module == "T07" and pair_nodes[index] in t07_surfaces
                else "missing_or_ambiguous_surface"
                if anchor.source_module == "T07"
                else "not_applicable"
            )
            for index, anchor in enumerate(anchors)
        ],
        "automatic_all_directions_equivalent": not failed_directions,
        "automatic_equivalence_basis": (
            "raw_carrier"
            if not raw_failed_directions
            else "portal_constrained_semantic_carrier"
            if not failed_directions and not surface_resolved_directions
            else "t07_road_surface_carrier"
            if not failed_directions and surface_resolved_directions
            else ""
        ),
        "portal_constrained_semantic_all_raw_failures_equivalent": bool(
            raw_failed_directions
            and not failed_directions
            and not surface_resolved_directions
        ),
        "t07_road_surface_resolved_directions": surface_resolved_directions,
        "semantic_resolved_directions": semantic_resolved_directions,
        "t07_road_surface_all_remaining_failures_equivalent": bool(
            surface_resolved_directions and not failed_directions
        ),
        "directions": direction_evidence,
        "t06_cross_evidence": dict(t06_cross_evidence),
    }


def _anchor_confidence(
    pair_nodes: list[str],
    anchors: list[AnchorRecord],
    t07_surfaces: Mapping[str, Any],
) -> str:
    t07_indexes = [
        index
        for index, anchor in enumerate(anchors)
        if anchor.source_module == "T07"
    ]
    if t07_indexes and all(pair_nodes[index] in t07_surfaces for index in t07_indexes):
        return "t07_standard_surface"
    if [anchor.source_module for anchor in anchors] == ["T03", "T03"]:
        return "t03_pair"
    return "insufficient"


def _append_path_layers(
    *,
    layers: EvidenceLayers,
    candidate_id: str,
    direction: str,
    carrier: Mapping[str, Any],
    segment_roads: gpd.GeoDataFrame,
    swsd_road_id_field: str,
    paths: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, Any]],
    local_graph: GraphBundle,
    full_graph: GraphBundle,
    semantic_local_graph: GraphBundle,
    semantic_full_graph: GraphBundle,
) -> None:
    by_id = {
        normalize_id(row[swsd_road_id_field]): row
        for _, row in segment_roads.iterrows()
    }
    for sequence, road_id in enumerate(carrier["road_ids"], start=1):
        row = by_id[road_id]
        layers.swsd_required_carriers.append(
            {
                "candidate_id": candidate_id,
                "direction": direction,
                "sequence": sequence,
                "road_id": road_id,
                "geometry": row.geometry,
            }
        )
    for path_kind, path in paths.items():
        if path is None:
            continue
        if path_kind.startswith("t07_road_surface_"):
            graph = semantic_local_graph
        elif path_kind.startswith("semantic_local_"):
            graph = semantic_local_graph
        elif path_kind.startswith("semantic_full_"):
            graph = semantic_full_graph
        elif path_kind.startswith("local_"):
            graph = local_graph
        else:
            graph = full_graph
        for sequence, road_id in enumerate(path.road_ids, start=1):
            edge = graph.edges[road_id]
            surface_fields = (
                {
                    "source_surface_id": metrics[path_kind].get(
                        "source_surface_id", ""
                    ),
                    "target_surface_id": metrics[path_kind].get(
                        "target_surface_id", ""
                    ),
                    "source_access_kind": metrics[path_kind].get(
                        "source_access_kind", ""
                    ),
                    "target_access_kind": metrics[path_kind].get(
                        "target_access_kind", ""
                    ),
                    "source_access_frontier_node": metrics[path_kind].get(
                        "source_access_frontier_node", ""
                    ),
                    "target_access_frontier_node": metrics[path_kind].get(
                        "target_access_frontier_node", ""
                    ),
                    "source_access_road_ids": "|".join(
                        metrics[path_kind].get("source_access_road_ids") or []
                    ),
                    "target_access_road_ids": "|".join(
                        metrics[path_kind].get("target_access_road_ids") or []
                    ),
                    "distance_gate_role": metrics[path_kind].get(
                        "distance_gate_role", ""
                    ),
                    "source_road_surface_gap_m": metrics[path_kind].get(
                        "source_road_surface_gap_m"
                    ),
                    "target_road_surface_gap_m": metrics[path_kind].get(
                        "target_road_surface_gap_m"
                    ),
                    "max_internal_alias_gap_m": metrics[path_kind].get(
                        "max_internal_alias_gap_m"
                    ),
                    "distance_risk_flags": "|".join(
                        metrics[path_kind].get("distance_risk_flags") or []
                    ),
                }
                if path_kind.startswith("t07_road_surface_")
                else {}
            )
            layers.frcsd_carrier_paths.append(
                {
                    "candidate_id": candidate_id,
                    "direction": direction,
                    "path_kind": path_kind,
                    "sequence": sequence,
                    "road_id": road_id,
                    "road_direction": edge.direction,
                    "source": edge.source,
                    "accepted_equivalent_carrier": metrics[path_kind][
                        "accepted_equivalent_carrier"
                    ],
                    "path_length_m": metrics[path_kind]["length_m"],
                    "path_length_ratio": metrics[path_kind]["length_ratio"],
                    "max_corridor_distance_m": metrics[path_kind][
                        "max_corridor_distance_m"
                    ],
                    **surface_fields,
                    "geometry": edge.geometry,
                }
            )


def _missing_directions(
    required: list[str],
    graph: GraphBundle,
    base_nodes: list[str],
) -> list[str]:
    paths = {
        "pair0_to_pair1": shortest_path_between_sets(
            graph.directed, [base_nodes[0]], [base_nodes[1]]
        ),
        "pair1_to_pair0": shortest_path_between_sets(
            graph.directed, [base_nodes[1]], [base_nodes[0]]
        ),
    }
    return [direction for direction in required if paths[direction] is None]


def _is_fully_inner(geometry: Any, inner: Any | None) -> bool:
    if inner is None:
        return True
    length = float(geometry.length)
    return length > 0 and float(geometry.intersection(inner).length / length) >= 0.999999


def _canonical_points(
    canonicalizer: NodeCanonicalizer,
    raw_points: Mapping[str, Any],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for raw_id, point in raw_points.items():
        output.setdefault(canonicalizer.canonicalize(raw_id), point)
    return output


def _all_graph_nodes(graph: GraphBundle) -> set[str]:
    nodes = set(graph.directed) | set(graph.incoming)
    for edge in graph.edges.values():
        nodes.update((edge.start, edge.end))
    return nodes
