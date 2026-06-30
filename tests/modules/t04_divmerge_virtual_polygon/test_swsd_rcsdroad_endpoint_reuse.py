from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.final_publish import (
    _first_relation_handoff_rcsd_point,
    _relation_handoff_rcsd_node_ids,
)


def _road(road_id: str, snodeid: str, enodeid: str) -> SimpleNamespace:
    return SimpleNamespace(
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        geometry=LineString([(0, 0), (10, 0)]),
    )


def _node(node_id: str, *, kind: int, incident_ids: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        node_id=node_id,
        mainnodeid="0",
        kind=kind,
        properties={"kind": kind, "node_lid": list(incident_ids)},
        geometry=Point(10, 0) if node_id == "junction" else Point(0, 0),
    )


def _case(
    *,
    fallback_road_id: str,
    roads: tuple[SimpleNamespace, ...],
    nodes: tuple[SimpleNamespace, ...],
    review_reasons: tuple[str, ...] = ("road_surface_fork_binding_used",),
) -> SimpleNamespace:
    event_unit = SimpleNamespace(
        required_rcsd_node=None,
        fallback_rcsdroad_ids=(fallback_road_id,),
        selected_evidence_summary={"review_reasons": list(review_reasons)},
        selected_candidate_summary={},
        positive_rcsd_audit={},
    )
    return SimpleNamespace(
        event_units=(event_unit,),
        case_bundle=SimpleNamespace(rcsd_roads=roads, rcsd_nodes=nodes),
    )


def test_single_fallback_rcsdroad_reuses_unique_semantic_endpoint() -> None:
    case_result = _case(
        fallback_road_id="r1",
        roads=(
            _road("r1", "plain", "junction"),
            _road("r2", "junction", "other_a"),
            _road("r3", "other_b", "junction"),
        ),
        nodes=(
            _node("plain", kind=1, incident_ids=("r1",)),
            _node("junction", kind=8, incident_ids=("r1", "r2", "r3")),
        ),
    )

    assert _relation_handoff_rcsd_node_ids(case_result, swsd_relation_type="offset_fact") == [
        "junction"
    ]
    assert _first_relation_handoff_rcsd_point(case_result, swsd_relation_type="offset_fact") == (
        10.0,
        0.0,
    )


def test_single_fallback_rcsdroad_keeps_road_only_when_endpoint_is_ambiguous() -> None:
    case_result = _case(
        fallback_road_id="r1",
        roads=(
            _road("r1", "junction_a", "junction_b"),
            _road("r2", "junction_a", "other_a"),
            _road("r3", "other_b", "junction_a"),
            _road("r4", "junction_b", "other_c"),
            _road("r5", "other_d", "junction_b"),
        ),
        nodes=(
            _node("junction_a", kind=8, incident_ids=("r1", "r2", "r3")),
            _node("junction_b", kind=8, incident_ids=("r1", "r4", "r5")),
        ),
    )

    assert _relation_handoff_rcsd_node_ids(case_result, swsd_relation_type="offset_fact") == []


def test_single_fallback_rcsdroad_requires_surface_binding_reason() -> None:
    case_result = _case(
        fallback_road_id="r1",
        roads=(
            _road("r1", "plain", "junction"),
            _road("r2", "junction", "other_a"),
            _road("r3", "other_b", "junction"),
        ),
        nodes=(
            _node("plain", kind=1, incident_ids=("r1",)),
            _node("junction", kind=8, incident_ids=("r1", "r2", "r3")),
        ),
        review_reasons=("missing_positive_rcsd", "single_swsd_rcsdroad_alignment"),
    )

    assert _relation_handoff_rcsd_node_ids(case_result, swsd_relation_type="offset_fact") == []
