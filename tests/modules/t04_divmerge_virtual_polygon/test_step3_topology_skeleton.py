from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import Polygon

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step3_topology_skeleton import (
    _build_stage4_topology_skeleton,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.topology import (
    build_step3_status_doc,
    build_unit_step3_status_doc,
)

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import _parsed_node, _parsed_road


DRIVEZONE = Polygon([(-80, -80), (80, -80), (80, 80), (-80, 80), (-80, -80)])


def _sample_skeleton():
    nodes = [
        _parsed_node("1001", 0, 0, mainnodeid="1001", kind_2=16),
        _parsed_node("2001", -35, 0),
        _parsed_node("3001", 35, 25),
        _parsed_node("4001", 35, -25),
    ]
    roads = [
        _parsed_road("r1", [(-35, 0), (0, 0)], snodeid="2001", enodeid="1001"),
        _parsed_road("r2", [(0, 0), (35, 25)], snodeid="1001", enodeid="3001"),
        _parsed_road("r3", [(0, 0), (35, -25)], snodeid="1001", enodeid="4001"),
    ]
    return _build_stage4_topology_skeleton(
        representative_node=nodes[0],
        group_nodes=[nodes[0]],
        local_nodes=nodes,
        local_roads=roads,
        drivezone_union=DRIVEZONE,
        support_center=nodes[0].geometry,
    )


def _admission():
    return SimpleNamespace(mainnodeid="1001", representative_node_id="1001")


def test_step3_status_doc_keeps_legacy_fields_and_adds_semantic_junction() -> None:
    status_doc = build_step3_status_doc(admission=_admission(), topology_skeleton=_sample_skeleton())

    assert status_doc["scope"] == "t04_step3_topology_skeleton"
    assert status_doc["topology_scope"] == "case_coordination"
    assert status_doc["mainnodeid"] == "1001"
    assert status_doc["representative_node_id"] == "1001"
    assert status_doc["branch_count"] == 3
    assert len(status_doc["branch_ids"]) == status_doc["branch_count"]
    assert "main_branch_ids" in status_doc
    assert status_doc["step3_state"] in {"ready", "review_required"}

    swsd_junction = status_doc["swsd_semantic_junction"]
    assert swsd_junction["junction_id"] == "1001"
    assert swsd_junction["member_node_ids"] == ["1001"]
    assert swsd_junction["intra_junction_road_ids"] == []
    assert {
        road_id
        for arm in swsd_junction["semantic_arms"]
        for road_id in arm["inter_junction_connector_road_ids"]
    } == {"r1", "r2", "r3"}


def test_unit_step3_status_doc_exposes_owned_and_sibling_semantic_arms() -> None:
    skeleton = _sample_skeleton()
    owned_branch_id = skeleton.swsd_semantic_junction.semantic_arms[0].first_branch_id
    unit_doc = build_unit_step3_status_doc(
        admission=_admission(),
        topology_skeleton=skeleton,
        topology_scope="event_unit",
        unit_population_node_ids=("1001",),
        context_augmented_node_ids=(),
        event_branch_ids=(owned_branch_id,),
        boundary_branch_ids=(),
        preferred_axis_branch_id=owned_branch_id,
        degraded_scope_reason=None,
    )

    assert unit_doc["swsd_junction_ref"] == "1001"
    assert unit_doc["unit_owned_arm_ids"] == [skeleton.swsd_semantic_junction.semantic_arms[0].arm_id]
    assert set(unit_doc["sibling_unit_arm_ids"]) == {
        arm.arm_id
        for arm in skeleton.swsd_semantic_junction.semantic_arms[1:]
    }
