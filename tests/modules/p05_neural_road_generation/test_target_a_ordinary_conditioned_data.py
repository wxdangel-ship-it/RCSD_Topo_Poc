from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_data import (
    AnchorOOFCondition,
    collate_oof_anchor_conditioned_ordinary_batch,
    condition_ordinary_plan_example,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_oof import (
    _balanced_case_weights,
    _conditioned_plan_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    compute_target_a_loss,
)


def _example(*, acceptable_index: int) -> OrdinaryPlanTrainingExample:
    return OrdinaryPlanTrainingExample(
        sample_id="case:s1",
        case_key="T10:case",
        segment_id="s1",
        fold=1,
        object_features=(0.0,) * 64,
        required_anchor_ids=("a1", "a2"),
        arm_anchor_ids=("a1", "a2"),
        candidate_ids=("keep", "use", "abstain"),
        candidate_decisions=("KEEP_SWSD", "USE_RCSD", "ABSTAIN"),
        candidate_road_ids=(("swsd-r",), ("r1", "r2"), ()),
        candidate_member_ids=((), (), ()),
        candidate_member_endpoint_ids=((), (), ()),
        candidate_member_features=((), (), ()),
        candidate_arm_road_ids=((), (), ()),
        candidate_arm_node_ids=((), (), ()),
        candidate_arm_features=((), (), ()),
        candidate_features=(
            (0.0,) * 64,
            (1.0,) * 64,
            (0.5,) * 64,
        ),
        acceptable_indices=(acceptable_index,),
        preferred_index=acceptable_index,
        preferred_decision=(
            "KEEP_SWSD" if acceptable_index == 0 else "USE_RCSD"
        ),
        sample_weight=0.7,
        clue_label=0,
        clue_task_mask=False,
        fallback_scope_label=0,
        fallback_scope_task_mask=False,
    )


def _condition(anchor_id: str, status: str) -> AnchorOOFCondition:
    return AnchorOOFCondition(
        anchor_id=anchor_id,
        selected_candidate_id=(
            f"NODE:{anchor_id}"
            if anchor_id == "a1"
            else "ROAD:r1"
        ),
        predicted_status=status,
        gate_pass_probability=0.9 if status == "SUCCESS" else 0.2,
        selected_candidate_features=(0.25,) * 64,
    )


def test_anchor_failure_blocks_positive_keep_carrier_supervision() -> None:
    conditioned = condition_ordinary_plan_example(
        _example(acceptable_index=0),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "ABSTAIN"),
        },
    )

    assert not conditioned.all_required_anchors_resolved
    assert conditioned.enabled_candidate_mask == (True, False, True)
    assert conditioned.conditioned_acceptable_indices == (0,)
    assert conditioned.conditioned_label_reachable
    assert conditioned.fallback_required

    batch = collate_oof_anchor_conditioned_ordinary_batch(
        [conditioned],
        decision_class_weights={"KEEP_SWSD": 2.0},
    )
    assert batch.tensors.ordinary_plan_mask.tolist() == [
        [[True, False, True]]
    ]
    assert batch.targets.ordinary_acceptable.tolist() == [
        [[True, False, False]]
    ]
    assert batch.targets.ordinary_task_mask.tolist() == [[False]]
    assert batch.tensors.teacher_ordinary_plan_indices.tolist() == [[2]]
    assert batch.targets.ordinary_sample_weights.tolist()[0][0] == (
        pytest.approx(1.4)
    )


def test_anchor_failure_masks_use_rcsd_without_relabeing_it_keep() -> None:
    conditioned = condition_ordinary_plan_example(
        _example(acceptable_index=1),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "AMBIGUOUS"),
        },
    )

    assert conditioned.enabled_candidate_mask == (True, False, True)
    assert conditioned.conditioned_acceptable_indices == ()
    assert conditioned.conditioned_preferred_index == -1
    assert conditioned.fallback_required

    batch = collate_oof_anchor_conditioned_ordinary_batch([conditioned])
    assert batch.targets.ordinary_task_mask.tolist() == [[False]]
    assert not batch.targets.ordinary_acceptable.any()
    assert batch.tensors.teacher_ordinary_plan_indices.tolist() == [[2]]


def test_all_required_anchor_success_enables_use_rcsd() -> None:
    conditioned = condition_ordinary_plan_example(
        _example(acceptable_index=1),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "SUCCESS"),
        },
    )

    assert conditioned.all_required_anchors_resolved
    assert conditioned.all_required_anchors_success
    assert conditioned.enabled_candidate_mask == (True, True, True)
    assert conditioned.conditioned_acceptable_indices == (1,)


def test_no_required_anchor_passes_the_anchor_gate() -> None:
    conditioned = condition_ordinary_plan_example(
        replace(
            _example(acceptable_index=0),
            required_anchor_ids=(),
            arm_anchor_ids=(),
        ),
        {},
    )

    assert conditioned.all_required_anchors_resolved
    assert not conditioned.fallback_required
    assert conditioned.conditioned_acceptable_indices == (0,)


def test_no_evidence_resolves_only_positive_keep_without_anchor_object() -> None:
    conditions = {
        "a1": _condition("a1", "SUCCESS"),
        "a2": _condition("a2", "NO_EVIDENCE"),
    }
    keep = condition_ordinary_plan_example(
        _example(acceptable_index=0),
        conditions,
    )
    use = condition_ordinary_plan_example(
        _example(acceptable_index=1),
        conditions,
    )

    assert keep.all_required_anchors_resolved
    assert not keep.all_required_anchors_success
    assert not keep.fallback_required
    assert keep.conditioned_acceptable_indices == (0,)
    assert use.enabled_candidate_mask == (True, False, True)
    assert use.conditioned_acceptable_indices == ()


def test_anchor_plan_relations_compare_selected_nodes_and_roads() -> None:
    conditioned = condition_ordinary_plan_example(
        _example(acceptable_index=1),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "SUCCESS"),
        },
        include_anchor_plan_relations=True,
        candidate_node_ids=(("swsd-n",), ("a1", "n2", "n3"), ()),
    )

    keep = conditioned.conditioned_candidate_features[0]
    use = conditioned.conditioned_candidate_features[1]
    assert keep[25:33] == (0.0,) * 8
    assert use[23:33] == (
        0.125,
        0.125,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
    )

    batch = collate_oof_anchor_conditioned_ordinary_batch([conditioned])
    assert batch.tensors.ordinary_plan_features[0, 0, 1, 25] == 1.0
    assert batch.tensors.ordinary_plan_features[0, 0, 0, 25] == 0.0


def test_anchor_relations_are_attached_to_each_road_member() -> None:
    base = replace(
        _example(acceptable_index=1),
        candidate_member_ids=((), ("r1", "r2"), ()),
        candidate_member_endpoint_ids=(
            (),
            (("a1", "n2"), ("n2", "n3")),
            (),
        ),
        candidate_member_features=(
            (),
            (
                (0.0,) * ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
                (0.0,) * ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
            ),
            (),
        ),
    )
    conditioned = condition_ordinary_plan_example(
        base,
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "SUCCESS"),
        },
        include_plan_member_relations=True,
    )

    first, second = conditioned.conditioned_member_features[1]
    assert first[-4:] == (1.0, 1.0, 0.0, 1.0)
    assert second[-4:] == (0.0, 0.0, 0.0, 0.0)

    batch = collate_oof_anchor_conditioned_ordinary_batch([conditioned])
    assert batch.tensors.ordinary_plan_member_features is not None
    values = batch.tensors.ordinary_plan_member_features[0, 0, 1]
    assert values[0, -4:].tolist() == [1.0, 1.0, 0.0, 1.0]
    assert values[1, -4:].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_anchor_relations_are_attached_to_the_two_segment_arms() -> None:
    base = replace(
        _example(acceptable_index=1),
        candidate_arm_road_ids=((), ("r1", "r2"), ()),
        candidate_arm_node_ids=((), ("a1", "n3"), ()),
        candidate_arm_features=(
            (),
            (
                (0.0,) * ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
                (0.0,) * ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
            ),
            (),
        ),
    )
    conditioned = condition_ordinary_plan_example(
        base,
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "SUCCESS"),
        },
        include_plan_arm_relations=True,
    )

    first, second = conditioned.conditioned_arm_features[1]
    assert first[13:16] == (1.0, 1.0, 1.0)
    assert first[16:19] == (0.0, 1.0, 1.0)
    assert first[19:22] == (1.0, 0.0, 1.0)
    assert second[13:16] == (0.0, 0.0, 0.0)

    batch = collate_oof_anchor_conditioned_ordinary_batch([conditioned])
    assert batch.tensors.ordinary_plan_arm_features is not None
    values = batch.tensors.ordinary_plan_arm_features[0, 0, 1]
    assert values[0, 16:19].tolist() == [0.0, 1.0, 1.0]
    assert values[0, 19:22].tolist() == [1.0, 0.0, 1.0]
    assert values[1, 13:16].tolist() == [0.0, 0.0, 0.0]


def test_ordinary_candidate_validity_loss_is_optional_and_finite() -> None:
    conditioned = condition_ordinary_plan_example(
        _example(acceptable_index=1),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "SUCCESS"),
        },
    )
    batch = collate_oof_anchor_conditioned_ordinary_batch([conditioned])
    config = TargetAConfig(
        ordinary_oof_anchor_condition_encoder=True,
        ordinary_candidate_validity_loss_weight=0.5,
        separate_ordinary_candidate_validity_head=True,
    )
    outputs = TargetAJointNetwork(config)(batch.tensors)

    total, losses = compute_target_a_loss(outputs, batch, config)

    assert torch.isfinite(total)
    assert losses["ordinary_candidate_validity"] >= 0.0
    assert "ordinary_plan_validity_logits" in outputs


def test_ordinary_decision_validity_loss_is_optional_and_finite() -> None:
    conditioned = condition_ordinary_plan_example(
        _example(acceptable_index=1),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "SUCCESS"),
        },
    )
    batch = collate_oof_anchor_conditioned_ordinary_batch([conditioned])
    config = TargetAConfig(
        hierarchical_ordinary_plan_decoder=True,
        ordinary_decision_validity_loss_weight=1.0,
        separate_ordinary_decision_validity_head=True,
    )
    outputs = TargetAJointNetwork(config)(batch.tensors)

    total, losses = compute_target_a_loss(outputs, batch, config)

    assert torch.isfinite(total)
    assert losses["ordinary_decision_validity"] >= 0.0
    assert "ordinary_decision_validity_logits" in outputs


def test_manual_anchor_fallback_keeps_carrier_head_masked() -> None:
    conditioned = condition_ordinary_plan_example(
        replace(
            _example(acceptable_index=0),
            carrier_task_mask=False,
        ),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "SUCCESS"),
        },
    )
    batch = collate_oof_anchor_conditioned_ordinary_batch([conditioned])

    assert conditioned.conditioned_label_reachable
    assert batch.targets.ordinary_task_mask.tolist() == [[False]]


def test_conditioned_metrics_separate_carrier_and_fallback_supervision() -> None:
    common = {
        "conditioned_label_reachable": True,
        "anchor_gate_fallback_required": False,
        "release_fallback_required": False,
        "release_fallback_scope": "NONE",
        "fallback_safe_success": False,
        "preferred_exact": True,
        "preferred_decision": "KEEP_SWSD",
        "raw_predicted_decision": "KEEP_SWSD",
        "predicted_clue": False,
        "clue_label": False,
        "clue_label_evaluable": True,
    }
    rows = [
        {
            **common,
            "carrier_label_evaluable": True,
            "automatic_decision": True,
            "acceptable_exact": True,
            "fallback_scope_label_evaluable": True,
            "fallback_scope_label": "NONE",
        },
        {
            **common,
            "carrier_label_evaluable": False,
            "automatic_decision": True,
            "acceptable_exact": None,
            "fallback_scope_label_evaluable": True,
            "fallback_scope_label": "SEGMENT",
        },
    ]

    metrics = _conditioned_plan_metrics(rows)

    assert metrics["carrier_label_evaluable_count"] == 1
    assert metrics["automatic_carrier_evaluable_count"] == 1
    assert metrics["automatic_complete_plan_acceptable_exact"] == 1.0
    assert metrics["fallback_scope_exact"] == 0.5
    assert metrics["unsafe_scope_bypass_count"] == 1
    assert metrics["clue_accuracy"] == 1.0


def test_hierarchical_ordinary_loss_supervises_business_decision() -> None:
    conditioned = condition_ordinary_plan_example(
        _example(acceptable_index=1),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "SUCCESS"),
        },
        include_anchor_plan_relations=True,
        candidate_node_ids=(("swsd-n",), ("a1", "n2"), ()),
    )
    batch = collate_oof_anchor_conditioned_ordinary_batch([conditioned])
    config = TargetAConfig(
        ordinary_oof_anchor_condition_encoder=True,
        hierarchical_ordinary_plan_decoder=True,
        ordinary_decision_loss_weight=1.0,
    )
    outputs = TargetAJointNetwork(config)(batch.tensors)

    total, losses = compute_target_a_loss(outputs, batch, config)

    assert torch.isfinite(total)
    assert "ordinary_decision" in losses
    assert losses["ordinary_decision"] >= 0.0


def test_case_balancing_retains_equal_total_mass_per_case() -> None:
    first = condition_ordinary_plan_example(
        _example(acceptable_index=0),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "SUCCESS"),
        },
    )
    second = replace(
        first,
        base=replace(
            first.base,
            sample_id="case:s2",
            segment_id="s2",
        ),
    )
    third = replace(
        first,
        base=replace(
            first.base,
            sample_id="other:s1",
            case_key="T10:other",
        ),
    )

    weights = _balanced_case_weights((first, second, third))

    assert weights["T10:case"] == pytest.approx(0.75)
    assert weights["T10:other"] == pytest.approx(1.5)
    assert 2 * weights["T10:case"] == pytest.approx(
        weights["T10:other"]
    )
