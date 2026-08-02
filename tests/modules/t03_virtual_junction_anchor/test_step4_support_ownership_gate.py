from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import NodeRecord, RoadRecord
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_support_ownership import (
    evaluate_class_b_support_ownership,
)


def _node(node_id: str, x: float, y: float) -> NodeRecord:
    return NodeRecord(0, node_id, node_id, None, None, 2048, None, Point(x, y))


def _road(road_id: str, snodeid: str, enodeid: str, coordinates) -> RoadRecord:
    return RoadRecord(0, road_id, snodeid, enodeid, 2, LineString(coordinates))


def _evaluate(targets, roads):
    return evaluate_class_b_support_ownership(
        target_nodes=targets,
        support_roads=roads,
        target_distance_tolerance_m=10.0,
        endpoint_tolerance_m=6.0,
    )


def test_interior_projection_on_one_support_component_is_owned() -> None:
    audit = _evaluate(
        [_node("target", 10, 1)],
        [_road("road", "a", "b", [(0, 0), (20, 0)])],
    )

    assert audit["owned"] is True
    assert audit["issue_codes"] == []


def test_single_far_target_distance_is_audit_only() -> None:
    audit = _evaluate(
        [_node("target", 10, 15)],
        [_road("road", "a", "b", [(0, 0), (20, 0)])],
    )

    assert audit["owned"] is True
    assert audit["target_projection_rows"][0]["within_distance_audit_threshold"] is False


def test_distance_is_audit_only_when_same_component_has_local_target_evidence() -> None:
    audit = _evaluate(
        [_node("near", 10, 1), _node("far", 10, 15)],
        [_road("road", "a", "b", [(0, 0), (20, 0)])],
    )

    assert audit["owned"] is True
    assert audit["target_distance_gate_role"].startswith("audit_only")
    assert audit["target_projection_rows"][1]["within_distance_audit_threshold"] is False


def test_two_parallel_support_components_are_allowed_as_dual_carriageway_evidence() -> None:
    audit = _evaluate(
        [_node("left", 5, 1), _node("right", 25, 1)],
        [
            _road("left_road", "a", "b", [(0, 0), (10, 0)]),
            _road("right_road", "c", "d", [(20, 0), (30, 0)]),
        ],
    )

    assert audit["owned"] is True
    assert audit["support_component_count"] == 2


def test_targets_among_more_than_two_disconnected_support_components_are_not_owned() -> None:
    audit = _evaluate(
        [_node("left", 5, 1), _node("right", 25, 1)],
        [
            _road("left_road", "a", "b", [(0, 0), (10, 0)]),
            _road("right_road", "c", "d", [(20, 0), (30, 0)]),
            _road("foreign_road", "e", "f", [(40, 0), (50, 0)]),
        ],
    )

    assert audit["owned"] is False
    assert "targets_project_to_disconnected_support_components" in audit["issue_codes"]


def test_distributed_canonical_mainnode_evidence_owns_disconnected_local_support() -> None:
    audit = evaluate_class_b_support_ownership(
        target_nodes=[
            _node("left", 5, 1),
            _node("middle", 25, 1),
            _node("right", 45, 1),
        ],
        support_roads=[
            _road("left_road", "a", "b", [(0, 0), (10, 0)]),
            _road("middle_road", "c", "d", [(20, 0), (30, 0)]),
            _road("right_road", "e", "f", [(40, 0), (50, 0)]),
            _road("other_road", "g", "h", [(60, 0), (70, 0)]),
        ],
        target_distance_tolerance_m=10.0,
        endpoint_tolerance_m=6.0,
        distributed_canonical_group_ids=["canonical_main"],
    )

    assert audit["owned"] is True
    assert audit["raw_issue_codes"] == [
        "targets_project_to_disconnected_support_components"
    ]
    assert audit["issue_codes"] == []
    assert audit["ownership_basis"] == (
        "distributed_canonical_mainnode_external_arm_evidence"
    )


def test_single_target_projection_to_terminal_endpoint_is_audit_only() -> None:
    audit = _evaluate(
        [_node("target", 19, 1)],
        [_road("road", "a", "b", [(0, 0), (20, 0)])],
    )

    assert audit["owned"] is True
    assert audit["target_projection_rows"][0]["projection_mode"] == "terminal_endpoint"


def test_multiple_target_aliases_collapsing_to_one_terminal_endpoint_are_not_owned() -> None:
    audit = _evaluate(
        [_node("target_a", 19, 1), _node("target_b", 21, 1)],
        [_road("road", "a", "b", [(0, 0), (20, 0)])],
    )

    assert audit["owned"] is False
    assert "target_projects_to_terminal_support_endpoint" in audit["issue_codes"]


def test_projection_to_shared_endpoint_is_owned() -> None:
    audit = _evaluate(
        [_node("target", 20, 1)],
        [
            _road("first", "a", "shared", [(0, 0), (20, 0)]),
            _road("second", "shared", "b", [(20, 0), (20, 20)]),
        ],
    )

    assert audit["owned"] is True
    assert audit["target_projection_rows"][0]["projection_mode"] == "shared_endpoint"
