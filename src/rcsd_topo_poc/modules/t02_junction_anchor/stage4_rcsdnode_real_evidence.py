from __future__ import annotations

from typing import Any, Iterable, Mapping

from shapely.geometry import GeometryCollection
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
    RCSDNODE_TRUNK_LATERAL_TOLERANCE_M,
    RC_NODE_SEED_RADIUS_M,
    RC_ROAD_BUFFER_M,
    REASON_RCSDNODE_MAIN_OFF_TRUNK,
    REASON_RCSDNODE_MAIN_OUT_OF_WINDOW,
)
from rcsd_topo_poc.modules.t02_junction_anchor.shared import normalize_id


REAL_EVIDENCE_SOURCE_EXACT_COVER = "selected_rcsdroad_endpoint_exact_cover"
REAL_EVIDENCE_SOURCE_CORRIDOR = "selected_rcsdroad_endpoint_corridor"
INFERRED_LOCAL_RCSDNODE_SEED_MODE = "inferred_local_trunk_window"
WEAK_EVIDENCE_RISK_SIGNALS = frozenset(
    {
        "reverse_tip_used",
        "fallback_to_weak_evidence",
    }
)


def _node_id(value: Any) -> str | None:
    return normalize_id(value)


def _incident_selected_rcsd_roads(*, node_id: str, selected_rcsd_roads: Iterable[Any]) -> list[Any]:
    roads: list[Any] = []
    for road in selected_rcsd_roads:
        endpoint_ids = {
            _node_id(getattr(road, "snodeid", None)),
            _node_id(getattr(road, "enodeid", None)),
        }
        if node_id in endpoint_ids:
            roads.append(road)
    return roads


def apply_selected_rcsdroad_real_evidence_tolerance(
    *,
    polygon_geometry: Any,
    primary_main_rc_node: Any | None,
    primary_rcsdnode_tolerance: Mapping[str, Any],
    selected_rcsd_roads: Iterable[Any],
    drivezone_union: Any | None,
    rcsdnode_seed_mode: str | None,
) -> dict[str, Any]:
    """Treat selected RCSDRoad endpoint coverage as real RCSDNode evidence.

    Stage4 case packages may not carry a direct `mainnodeid -> RCSDNode` relation.
    When Step4 has nevertheless selected RCSDRoads and the inferred primary RCSDNode
    is an endpoint of those roads, the selected RCSDRoad is the auditable reality
    evidence. In that case exact output coverage or a small local RCSDRoad corridor
    patch should override pure SWSD trunk-window drift.
    """
    result = dict(primary_rcsdnode_tolerance)
    if rcsdnode_seed_mode != INFERRED_LOCAL_RCSDNODE_SEED_MODE:
        return result
    if primary_main_rc_node is None:
        return result
    if polygon_geometry is None or polygon_geometry.is_empty:
        return result

    node_id = _node_id(getattr(primary_main_rc_node, "node_id", None))
    if node_id is None:
        return result
    incident_roads = _incident_selected_rcsd_roads(
        node_id=node_id,
        selected_rcsd_roads=selected_rcsd_roads,
    )
    if not incident_roads:
        return result

    node_geometry = primary_main_rc_node.geometry
    clean_polygon = polygon_geometry.buffer(0)
    if clean_polygon.covers(node_geometry):
        result.update(
            {
                "rcsdnode_tolerance_applied": False,
                "rcsdnode_coverage_mode": "exact_cover",
                "reason": None,
                "extended_polygon_geometry": polygon_geometry,
                "covered": True,
                "rcsdnode_real_evidence_source": REAL_EVIDENCE_SOURCE_EXACT_COVER,
            }
        )
        return result

    reason = str(result.get("reason") or "")
    if reason != REASON_RCSDNODE_MAIN_OFF_TRUNK:
        return result

    incident_geometries = [
        road.geometry
        for road in incident_roads
        if getattr(road, "geometry", None) is not None and not road.geometry.is_empty
    ]
    if not incident_geometries:
        return result

    incident_geometry = unary_union(incident_geometries)
    polygon_gap_m = float(clean_polygon.distance(node_geometry))
    corridor_buffer_m = max(
        float(RCSDNODE_TRUNK_LATERAL_TOLERANCE_M),
        float(RC_ROAD_BUFFER_M) * 1.25,
        2.5,
    )
    road_corridor = incident_geometry.buffer(corridor_buffer_m, cap_style=2, join_style=2)
    if drivezone_union is not None and not drivezone_union.is_empty:
        road_corridor = road_corridor.intersection(drivezone_union).buffer(0)
    if road_corridor.is_empty:
        return result

    node_seed = node_geometry.buffer(
        max(float(RC_NODE_SEED_RADIUS_M), polygon_gap_m + 1.5, 3.0),
        join_style=2,
    )
    node_patch = road_corridor.intersection(node_seed).buffer(0)
    if node_patch.is_empty:
        return result

    extended_polygon_geometry = unary_union(
        [clean_polygon, node_patch if not node_patch.is_empty else GeometryCollection()]
    ).buffer(0)
    if not extended_polygon_geometry.covers(node_geometry):
        return result

    result.update(
        {
            "rcsdnode_tolerance_applied": True,
            "rcsdnode_coverage_mode": "selected_road_corridor_tolerated",
            "reason": None,
            "extended_polygon_geometry": extended_polygon_geometry,
            "covered": True,
            "rcsdnode_real_evidence_source": REAL_EVIDENCE_SOURCE_CORRIDOR,
        }
    )
    return result


def suppress_weak_evidence_risks_for_real_rcsdnode_evidence(
    *,
    risk_signals: Iterable[str],
    primary_rcsdnode_tolerance: Mapping[str, Any],
    rcsdnode_seed_mode: str | None,
) -> tuple[str, ...]:
    if rcsdnode_seed_mode != INFERRED_LOCAL_RCSDNODE_SEED_MODE:
        return tuple(risk_signals)
    source = str(primary_rcsdnode_tolerance.get("rcsdnode_real_evidence_source") or "")
    if source not in {REAL_EVIDENCE_SOURCE_EXACT_COVER, REAL_EVIDENCE_SOURCE_CORRIDOR}:
        return tuple(risk_signals)
    if primary_rcsdnode_tolerance.get("reason") not in {None, ""}:
        return tuple(risk_signals)
    if str(primary_rcsdnode_tolerance.get("rcsdnode_coverage_mode") or "") not in {
        "exact_cover",
        "selected_road_corridor_tolerated",
    }:
        return tuple(risk_signals)
    return tuple(signal for signal in risk_signals if signal not in WEAK_EVIDENCE_RISK_SIGNALS)
