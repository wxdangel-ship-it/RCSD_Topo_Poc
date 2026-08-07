from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_scope import (
    select_anchor_examples_for_plan_scope,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    AnchorPretrainExample,
)


def _anchor(case_key: str, anchor_id: str) -> AnchorPretrainExample:
    return AnchorPretrainExample(
        sample_id=f"{case_key}:{anchor_id}",
        case_key=case_key,
        anchor_id=anchor_id,
        fold=0,
        object_features=(0.0,) * 64,
        candidate_ids=("candidate",),
        candidate_features=((0.0,) * 64,),
        status_label=0,
        candidate_acceptable_indices=(),
        preferred_candidate_index=-1,
        candidate_supervised=False,
        sample_weight=1.0,
        input_hashes=(("input", "hash"),),
        label_reason="test",
        dependency_anchor_ids=(anchor_id,),
    )


def test_anchor_scope_uses_label_scope_not_candidate_reachability() -> None:
    examples = [
        _anchor("T03:single", "single"),
        _anchor("T10:case", "a"),
        _anchor("T10:case", "b"),
        _anchor("T10:case", "context"),
    ]
    groups = [
        {
            "case_key": "T10:case",
            "segment_id": "target",
            "segment_type": "STANDARD",
            "required_anchor_ids": ["a", "b"],
        },
        {
            "case_key": "T10:case",
            "segment_id": "context",
            "segment_type": "STANDARD",
            "required_anchor_ids": ["b", "context"],
        },
    ]
    labels = [
        {
            "case_key": "T10:case",
            "segment_id": "target",
            "label_task_mask": True,
            "training_task_mask": False,
        },
        {
            "case_key": "T10:case",
            "segment_id": "context",
            "label_task_mask": False,
            "training_task_mask": True,
        },
    ]

    selected, summary = select_anchor_examples_for_plan_scope(
        examples,
        groups=groups,
        plan_labels=labels,
    )

    assert {
        (row.case_key, row.anchor_id) for row in selected
    } == {
        ("T03:single", "single"),
        ("T10:case", "a"),
        ("T10:case", "b"),
    }
    by_id = {row.anchor_id: row for row in selected}
    assert by_id["a"].dependency_anchor_ids == ("a", "b")
    assert by_id["b"].dependency_anchor_ids == ("a", "b")
    assert summary["target_segment_count"] == 1
    assert summary["target_anchor_count"] == 2
    assert summary["required_anchor_coverage"] == 1.0


def test_labeled_segment_without_required_anchors_is_valid_empty_gate() -> None:
    selected, summary = select_anchor_examples_for_plan_scope(
        [_anchor("T03:single", "single")],
        groups=[
            {
                "case_key": "T10:case",
                "segment_id": "no-required-anchor",
                "segment_type": "STANDARD",
                "required_anchor_ids": [],
            }
        ],
        plan_labels=[
            {
                "case_key": "T10:case",
                "segment_id": "no-required-anchor",
                "label_task_mask": True,
            }
        ],
    )

    assert [(row.case_key, row.anchor_id) for row in selected] == [
        ("T03:single", "single")
    ]
    assert summary["target_segment_count"] == 1
    assert summary["target_anchor_count"] == 0
    assert summary["zero_required_anchor_segment_count"] == 1
