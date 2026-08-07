from __future__ import annotations

from dataclasses import replace

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
    collate_ordinary_plan_batch,
)


def test_ordinary_teacher_forcing_keeps_anchor_locked_and_ar_masked() -> None:
    example = OrdinaryPlanTrainingExample(
        sample_id="case:s1",
        case_key="T10:case",
        segment_id="s1",
        fold=1,
        object_features=(0.0,) * 64,
        required_anchor_ids=("a1", "a2"),
        arm_anchor_ids=("a1", "a2"),
        candidate_ids=("keep", "use"),
        candidate_decisions=("KEEP_SWSD", "USE_RCSD"),
        candidate_road_ids=(("swsd-r",), ("rcsd-r",)),
        candidate_member_ids=((), ()),
        candidate_member_endpoint_ids=((), ()),
        candidate_member_features=((), ()),
        candidate_arm_road_ids=((), ()),
        candidate_arm_node_ids=((), ()),
        candidate_arm_features=((), ()),
        candidate_features=((0.0,) * 64, (1.0,) * 64),
        acceptable_indices=(1,),
        preferred_index=1,
        preferred_decision="USE_RCSD",
        sample_weight=0.7,
        clue_label=0,
        clue_task_mask=False,
        fallback_scope_label=0,
        fallback_scope_task_mask=False,
    )
    batch = collate_ordinary_plan_batch([example])
    assert batch.tensors.teacher_anchor_success.tolist() == [[True]]
    assert batch.tensors.teacher_ordinary_plan_indices.tolist() == [[1]]
    assert batch.targets.ordinary_acceptable.tolist() == [[[False, True]]]
    assert batch.targets.ordinary_task_mask.tolist() == [[True]]
    assert not batch.targets.advance_right_task_mask.any()

    fallback_batch = collate_ordinary_plan_batch(
        [replace(example, carrier_task_mask=False)]
    )
    assert fallback_batch.targets.ordinary_task_mask.tolist() == [[False]]
