from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_access_collections import (
    derive_access_collection_label,
)


def _target(
    proposal_id: str,
    road_id: str,
    *final_road_ids: str,
    node_id: str = "node",
) -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "road_id": road_id,
        "target_fraction": 0.0,
        "target_operation": "USE_ENDPOINT",
        "access_business_role": "DIRECT_CARRIER",
        "source_lineage": "ID_EXACT",
        "final_road_ids": list(final_road_ids),
        "final_access_node_ids": [node_id],
    }


def _label(*targets: dict[str, object], task: bool = True) -> dict[str, object]:
    return {
        "case_key": "T10:case",
        "segment_id": "segment",
        "junc_node_id": "junction",
        "fold": 2,
        "truth_decision": "USE_RCSD",
        "label_state": "RESOLVED",
        "access_task_mask": task,
        "access_label_weight": 0.7,
        "acceptable_access_targets": list(targets),
        "manual_review_required": False,
    }


def test_different_final_roads_are_jointly_required() -> None:
    row = derive_access_collection_label(
        _label(
            _target("p1", "r1", "final-1"),
            _target("p2", "r2", "final-2"),
        )
    )
    assert row["collection_task_mask"] is True
    assert row["required_final_road_ids"] == ["final-1", "final-2"]
    assert len(row["acceptable_access_collections"]) == 1
    assert row["acceptable_access_collections"][0]["proposal_ids"] == [
        "p1",
        "p2",
    ]


def test_two_source_explanations_for_one_final_road_are_alternatives() -> None:
    row = derive_access_collection_label(
        _label(
            _target("p1", "r1", "final"),
            _target("p2", "r2", "final"),
        )
    )
    assert [
        value["proposal_ids"]
        for value in row["acceptable_access_collections"]
    ] == [["p1"], ["p2"]]


def test_one_source_slice_may_cover_multiple_final_pieces() -> None:
    row = derive_access_collection_label(
        _label(
            _target("split", "source", "final-1", "final-2"),
            _target("redundant", "other", "final-2"),
        )
    )
    assert len(row["acceptable_access_collections"]) == 1
    assert row["acceptable_access_collections"][0]["proposal_ids"] == [
        "split"
    ]


def test_source_mask_and_weight_are_inherited_without_creating_supervision() -> None:
    row = derive_access_collection_label(
        _label(_target("p1", "r1", "final"), task=False)
    )
    assert row["collection_task_mask"] is False
    assert row["collection_label_weight"] == 0.0
    assert len(row["acceptable_access_collections"]) == 1
    assert row["label_only"] is True
    assert row["inference_input_allowed"] is False
