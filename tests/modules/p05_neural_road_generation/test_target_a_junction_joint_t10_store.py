from __future__ import annotations

from shapely import STRtree
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_t10_store import (
    _CaseIndex,
    _GeometryRecord,
    _dependency_geometry_records,
    _geometry_representation,
    _weak_label_row,
    assign_t10_case_splits,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_RELATION_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_t10_complete_gold import (
    T10CompleteJunctionGold,
)


def test_t10_case_split_keeps_each_case_whole() -> None:
    counts = {"A": 1628, "B": 1225, "C": 597, "D": 538, "E": 181, "F": 114}
    result = assign_t10_case_splits(counts)
    assert set(result) == set(counts)
    assert list(result.values()).count("validation") == 1
    assert list(result.values()).count("test") == 1
    assert list(result.values()).count("train") == 4


def test_relation_record_absent_is_masked_and_object_role_is_partial() -> None:
    feature = {
        "sample_id": "x",
        "structural_member_ids": ["ROAD:1", "NODE:2"],
    }
    label = {
        "status_label": 3,
        "status_supervised": True,
        "label_reason": "t05:relation_record_absent:anchor_truth_unknown:masked",
        "member_supervised": True,
        "member_acceptable_sets": [[0]],
        "candidate_supervised": False,
    }
    audit = {
        "t07_step1_status": "yes",
        "t07_step2_status": "no",
        "t03_available": True,
        "t03_step7_state": "accepted",
        "t03_relation_state": "success_required_rcsd_junction",
        "t05_junctionization_action": "split_rcsdroad_generate_rcsdnode",
    }
    row = _weak_label_row(
        feature,
        label,
        audit,
        split="train",
        available_objects={"ROAD:1", "NODE:2"},
    )
    assert not row["task_masks"]["final_state"]
    assert row["raw_object_target_object_sets"] == [["ROAD:1"]]
    assert row["raw_object_supervision_roles"] == ["ROAD"]
    assert row["task_labels"]["surface_mode"] == "VIRTUAL_SURFACE"
    assert row["sample_weight"] == 0.7


def test_t07_existing_surface_has_independent_surface_object_target() -> None:
    row = _weak_label_row(
        {
            "sample_id": "x",
            "structural_member_ids": ["NODE:2"],
        },
        {
            "status_label": 0,
            "status_supervised": True,
            "label_reason": "t05:direct_existing_rcsd_junction",
            "member_supervised": True,
            "member_acceptable_sets": [[0]],
            "candidate_supervised": True,
            "candidate_acceptable_indices": [0],
        },
        {
            "t07_step1_status": "yes",
            "t07_step2_status": "yes",
            "t05_junctionization_action": "direct_relation",
        },
        split="train",
        available_objects={"NODE:2", "RCSD_INTERSECTION:9"},
        surface_object_ids=("RCSD_INTERSECTION:9",),
    )

    assert row["task_labels"]["surface_mode"] == "EXISTING_RCSD_INTERSECTION"
    assert row["surface_object_target_object_sets"] == [
        ["RCSD_INTERSECTION:9"]
    ]
    assert row["surface_object_supervised"] is True


def test_t11_positive_manual_gold_overrides_older_t05_failure(tmp_path) -> None:
    row = _weak_label_row(
        {
            "sample_id": "x",
            "structural_member_ids": ["NODE:2"],
        },
        {
            "status_label": 0,
            "status_supervised": True,
            "label_reason": "t11_manual:1v1_rcsd_junction:object_reachable",
            "member_supervised": True,
            "member_acceptable_sets": [[0]],
            "candidate_supervised": False,
        },
        {
            "t07_step1_status": "yes",
            "t07_step2_status": "no",
            "t03_available": True,
            "t03_step7_state": "accepted",
            "t03_relation_state": "no_related_rcsd",
            "t05_junctionization_action": "failure_relation",
        },
        split="train",
        available_objects={"NODE:2"},
        complete_gold=T10CompleteJunctionGold(
            target_id="1",
            action="failure_relation",
            status=1,
            relation_object_kind="NONE",
            complete_object_ids=(),
            selected_main_rcsdnode_id="",
            original_rcsdroad_ids=(),
            original_rcsdnode_ids=(),
            new_rcsdnode_ids=(),
            grouped_rcsdnode_ids=(),
            rcsdnode_output_path=tmp_path / "unused.gpkg",
        ),
        anchor_point=Point(0.0, 0.0),
        object_geometries={"NODE:2": Point(1.0, 0.0)},
    )

    assert row["task_labels"]["junctionization_action"] == "direct_relation"
    assert row["task_labels"]["final_state"] == "SUCCESS"
    assert not row["task_masks"]["relation_state"]
    assert row["raw_object_target_object_sets"] == [["NODE:2"]]
    assert row["relation_object_supervision_scope"] == (
        "T11_MANUAL_COMPLETE_RELATION"
    )
    assert row["sample_weight"] == 0.7
    assert not row["topology_geometry_supervised"]


def test_t11_no_valid_manual_gold_overrides_older_t05_success() -> None:
    row = _weak_label_row(
        {"sample_id": "x", "structural_member_ids": ["NODE:2"]},
        {
            "status_label": 3,
            "status_supervised": True,
            "label_reason": "t11_manual:no_valid_relation:unresolved:abstain",
            "member_supervised": False,
            "candidate_supervised": False,
        },
        {
            "t07_step1_status": "yes",
            "t07_step2_status": "no",
            "t03_available": True,
            "t03_step7_state": "accepted",
            "t05_junctionization_action": "direct_relation",
        },
        split="train",
        available_objects={"NODE:2"},
    )

    assert row["task_labels"]["junctionization_action"] == "failure_relation"
    assert row["task_labels"]["final_state"] == "QUALITY_ISSUE"
    assert row["raw_object_target_object_sets"] == []
    assert row["complete_relation_plan_supervised"] is True
    assert row["complete_relation_object_supervised"] is True
    assert row["sample_weight"] == 0.7


def test_dependency_geometry_stops_at_current_semantic_junction() -> None:
    current = _GeometryRecord(
        role="RCSD_ROAD",
        object_id="RCSD_ROAD:current",
        geometry=Point(0.0, 0.0),
        properties={},
    )
    adjacent = _GeometryRecord(
        role="RCSD_ROAD",
        object_id="RCSD_ROAD:adjacent",
        geometry=Point(100.0, 0.0),
        properties={},
    )
    records = (current, adjacent)
    index = _CaseIndex(
        records_by_role={"RCSD_ROAD": records},
        trees_by_role={"RCSD_ROAD": STRtree([row.geometry for row in records])},
        object_lookup={row.object_id: row for row in records},
        anchor_points={"adjacent-anchor": Point(100.0, 0.0)},
        source_hashes=(),
    )

    selected = _dependency_geometry_records(
        index,
        {"dependency_anchor_ids": ["adjacent-anchor"]},
        anchor_point=Point(0.0, 0.0),
        radius_m=5.0,
    )

    assert [row.object_id for row in selected] == ["RCSD_ROAD:current"]


def test_t10_geometry_representation_keeps_raw_node_road_relations() -> None:
    representation = _geometry_representation(
        (
            _GeometryRecord(
                role="RCSD_NODE",
                object_id="NODE:21",
                geometry=Point(0.0, 0.0),
                properties={"id": 21, "mainnodeid": 21},
            ),
            _GeometryRecord(
                role="RCSD_NODE",
                object_id="NODE:22",
                geometry=Point(10.0, 0.0),
                properties={"id": 22, "mainnodeid": 22},
            ),
            _GeometryRecord(
                role="RCSD_ROAD",
                object_id="ROAD:10",
                geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
                properties={"id": 10, "snodeid": 21, "enodeid": 22},
            ),
        ),
        anchor_point=Point(5.0, 0.0),
        radius_m=200.0,
    )

    assert representation["relation_edges"]
    assert all(
        len(edge[2]) == GEOMETRY_RELATION_DIM
        for edge in representation["relation_edges"]
    )
