from __future__ import annotations

from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import (
    NodeCanonicalizer,
)

from .anchor_portals import AnchorRecord
from .carrier_graph import GraphBundle, PathResult, normalize_id


STANDARD_SURFACE_TOLERANCE_M = 1.0


def evaluate_portal_constrained_semantic_carrier(
    *,
    path: PathResult | None,
    metrics: Mapping[str, Any],
    graph: GraphBundle,
    start_portals: Sequence[Mapping[str, Any]],
    end_portals: Sequence[Mapping[str, Any]],
    source_anchor: AnchorRecord,
    target_anchor: AnchorRecord,
    source_truth_surface: Any | None,
    target_truth_surface: Any | None,
    canonicalizer: NodeCanonicalizer,
    raw_node_points: Mapping[str, Any],
    portal_radius_m: float,
) -> dict[str, Any]:
    """Validate a semantic path without treating canonical folding as a free edge."""
    semantic_path_accepted = bool(metrics.get("accepted_equivalent_carrier"))
    base = {
        "semantic_path_accepted": semantic_path_accepted,
        "start_endpoint_trusted": False,
        "start_endpoint_reason": "semantic_path_missing",
        "start_endpoint_raw_id": "",
        "start_endpoint_portal_gap_m": None,
        "end_endpoint_trusted": False,
        "end_endpoint_reason": "semantic_path_missing",
        "end_endpoint_raw_id": "",
        "end_endpoint_portal_gap_m": None,
        "internal_aliases_trusted": False,
        "internal_alias_transition_count": 0,
        "max_internal_alias_gap_m": None,
        "accepted_equivalent_carrier": False,
        "rejection_reason": "semantic_path_missing",
    }
    if path is None:
        return base
    if not path.road_ids:
        return {
            **base,
            "start_endpoint_reason": "semantic_path_has_no_physical_road",
            "end_endpoint_reason": "semantic_path_has_no_physical_road",
            "rejection_reason": "semantic_path_has_no_physical_road",
        }

    first = graph.edges[path.road_ids[0]]
    last = graph.edges[path.road_ids[-1]]
    start_raw = _raw_endpoint_for_canonical(
        first,
        path.node_ids[0],
        canonicalizer,
    )
    end_raw = _raw_endpoint_for_canonical(
        last,
        path.node_ids[-1],
        canonicalizer,
    )
    start_ok, start_reason, start_gap = _endpoint_trust(
        raw_id=start_raw,
        canonical_id=path.node_ids[0],
        portals=start_portals,
        anchor=source_anchor,
        truth_surface=source_truth_surface,
        canonicalizer=canonicalizer,
        raw_node_points=raw_node_points,
        portal_radius_m=portal_radius_m,
    )
    end_ok, end_reason, end_gap = _endpoint_trust(
        raw_id=end_raw,
        canonical_id=path.node_ids[-1],
        portals=end_portals,
        anchor=target_anchor,
        truth_surface=target_truth_surface,
        canonicalizer=canonicalizer,
        raw_node_points=raw_node_points,
        portal_radius_m=portal_radius_m,
    )
    transition_rows = _internal_alias_transitions(
        path=path,
        graph=graph,
        canonicalizer=canonicalizer,
        raw_node_points=raw_node_points,
        portal_radius_m=portal_radius_m,
    )
    internal_ok = all(row["trusted"] for row in transition_rows)
    gaps = [
        float(row["gap_m"])
        for row in transition_rows
        if row["gap_m"] is not None
    ]
    accepted = semantic_path_accepted and start_ok and end_ok and internal_ok
    if not semantic_path_accepted:
        rejection_reason = "semantic_path_not_equivalent"
    elif not start_ok:
        rejection_reason = f"start_endpoint_untrusted:{start_reason}"
    elif not end_ok:
        rejection_reason = f"end_endpoint_untrusted:{end_reason}"
    elif not internal_ok:
        rejection_reason = "internal_alias_gap_exceeds_portal_radius"
    else:
        rejection_reason = ""
    return {
        "semantic_path_accepted": semantic_path_accepted,
        "start_endpoint_trusted": start_ok,
        "start_endpoint_reason": start_reason,
        "start_endpoint_raw_id": start_raw,
        "start_endpoint_portal_gap_m": start_gap,
        "end_endpoint_trusted": end_ok,
        "end_endpoint_reason": end_reason,
        "end_endpoint_raw_id": end_raw,
        "end_endpoint_portal_gap_m": end_gap,
        "internal_aliases_trusted": internal_ok,
        "internal_alias_transition_count": len(transition_rows),
        "max_internal_alias_gap_m": max(gaps, default=0.0),
        "accepted_equivalent_carrier": accepted,
        "rejection_reason": rejection_reason,
        "internal_alias_transitions": transition_rows,
    }


def _endpoint_trust(
    *,
    raw_id: str,
    canonical_id: str,
    portals: Sequence[Mapping[str, Any]],
    anchor: AnchorRecord,
    truth_surface: Any | None,
    canonicalizer: NodeCanonicalizer,
    raw_node_points: Mapping[str, Any],
    portal_radius_m: float,
) -> tuple[bool, str, float | None]:
    portal_ids = {
        normalize_id(row.get("raw_id"))
        for row in portals
        if normalize_id(row.get("raw_id"))
    }
    if raw_id and raw_id in portal_ids:
        return True, "exact_raw_portal", 0.0
    point = raw_node_points.get(raw_id)
    comparable = [
        portal_id
        for portal_id in portal_ids
        if canonicalizer.canonicalize(portal_id) == canonical_id
        and raw_node_points.get(portal_id) is not None
    ]
    gaps = [
        float(point.distance(raw_node_points[portal_id]))
        for portal_id in comparable
    ] if point is not None else []
    min_gap = min(gaps, default=None)
    if anchor.source_module == "T07":
        same_surface = (
            truth_surface is not None
            and _on_surface(point, truth_surface)
            and any(
                _on_surface(raw_node_points.get(portal_id), truth_surface)
                for portal_id in comparable
            )
        )
        if same_surface:
            return True, "t07_shared_standard_surface_alias", min_gap
        return False, "t07_alias_outside_standard_surface", min_gap
    if min_gap is not None and min_gap <= portal_radius_m:
        return True, "non_t07_nearby_group_alias", min_gap
    return False, "non_t07_alias_outside_portal_radius", min_gap


def _internal_alias_transitions(
    *,
    path: PathResult,
    graph: GraphBundle,
    canonicalizer: NodeCanonicalizer,
    raw_node_points: Mapping[str, Any],
    portal_radius_m: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (left_id, right_id) in enumerate(
        zip(path.road_ids, path.road_ids[1:]),
        start=1,
    ):
        canonical_id = path.node_ids[index]
        left_raw = _raw_endpoint_for_canonical(
            graph.edges[left_id], canonical_id, canonicalizer
        )
        right_raw = _raw_endpoint_for_canonical(
            graph.edges[right_id], canonical_id, canonicalizer
        )
        left_point = raw_node_points.get(left_raw)
        right_point = raw_node_points.get(right_raw)
        gap = (
            float(left_point.distance(right_point))
            if left_point is not None and right_point is not None
            else None
        )
        trusted = bool(
            left_raw
            and right_raw
            and (
                left_raw == right_raw
                or (gap is not None and gap <= portal_radius_m)
            )
        )
        rows.append(
            {
                "sequence": index,
                "canonical_id": canonical_id,
                "left_road_id": left_id,
                "right_road_id": right_id,
                "left_raw_node_id": left_raw,
                "right_raw_node_id": right_raw,
                "gap_m": gap,
                "trusted": trusted,
            }
        )
    return rows


def _raw_endpoint_for_canonical(
    edge: Any,
    canonical_id: str,
    canonicalizer: NodeCanonicalizer,
) -> str:
    matches = {
        raw_id
        for raw_id in (edge.raw_start, edge.raw_end)
        if canonicalizer.canonicalize(raw_id) == canonical_id
    }
    return next(iter(matches)) if len(matches) == 1 else ""


def _on_surface(point: Any | None, surface: Any) -> bool:
    return bool(
        point is not None
        and not point.is_empty
        and float(surface.distance(point)) <= STANDARD_SURFACE_TOLERANCE_M
    )
