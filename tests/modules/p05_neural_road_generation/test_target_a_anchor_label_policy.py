from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_label_policy import (
    apply_anchor_supervision_policy,
    apply_plan_supervision_policy,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)


def _anchor(
    anchor_id: str,
    *,
    reason: str,
    gate_label: int,
    supervised: bool = True,
    case_key: str = "T10:case",
) -> AnchorPretrainExample:
    return AnchorPretrainExample(
        sample_id=f"anchor:{anchor_id}",
        case_key=case_key,
        anchor_id=anchor_id,
        fold=0,
        object_features=(0.0,) * 64,
        candidate_ids=("NO_RAW_RCSD_CANDIDATE",),
        candidate_features=((0.0,) * 64,),
        status_label=(
            ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
            if gate_label
            else ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
        ),
        candidate_acceptable_indices=(),
        preferred_candidate_index=-1,
        candidate_supervised=False,
        sample_weight=0.7,
        input_hashes=(("input", "hash"),),
        label_reason=reason,
        dependency_anchor_ids=(anchor_id,),
        status_supervised=supervised,
        gate_label=gate_label,
        gate_supervised=supervised,
    )


def test_relation_absent_is_masked_and_explicit_no_evidence_is_positive() -> None:
    examples = [
        _anchor(
            "unknown",
            reason="t05:relation_record_absent:unresolved:abstain",
            gate_label=0,
        ),
        _anchor(
            "no-evidence",
            reason="t05:relation_record_absent:unresolved:abstain",
            gate_label=0,
        ),
    ]

    transformed, counts = apply_anchor_supervision_policy(
        examples,
        confirmed_no_evidence_anchor_keys={
            ("T10:case", "no-evidence"),
        },
    )

    unknown, no_evidence = transformed
    assert not unknown.status_supervised
    assert not unknown.gate_supervised
    assert no_evidence.status_supervised
    assert no_evidence.gate_supervised
    assert no_evidence.gate_label == 1
    assert (
        no_evidence.status_label
        == ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
    )
    assert counts["supervised_relation_record_absent"] == 0


def test_t11_failure_forces_segment_fallback_and_unknown_masks_none_scope() -> None:
    anchors = [
        _anchor(
            "failed",
            reason="t11_manual:no_valid_relation:unresolved:abstain",
            gate_label=0,
        ),
        _anchor(
            "unknown",
            reason="t05:relation_record_absent:anchor_truth_unknown:masked",
            gate_label=0,
            supervised=False,
        ),
    ]
    plans = [
        {
            "case_key": "T10:case",
            "segment_id": "failed-segment",
            "carrier_task_mask": True,
            "fallback_scope": "NONE",
            "fallback_scope_task_mask": True,
        },
        {
            "case_key": "T10:case",
            "segment_id": "unknown-segment",
            "carrier_task_mask": True,
            "fallback_scope": "NONE",
            "fallback_scope_task_mask": True,
        },
    ]
    groups = [
        {
            "case_key": "T10:case",
            "segment_id": "failed-segment",
            "segment_type": "STANDARD",
            "required_anchor_ids": ["failed"],
        },
        {
            "case_key": "T10:case",
            "segment_id": "unknown-segment",
            "segment_type": "STANDARD",
            "required_anchor_ids": ["unknown"],
        },
    ]

    transformed, counts = apply_plan_supervision_policy(
        plans,
        groups=groups,
        anchor_examples=anchors,
    )

    failed, unknown = transformed
    assert not failed["carrier_task_mask"]
    assert failed["carrier_is_conditional_on_anchor"]
    assert failed["fallback_scope"] == "SEGMENT"
    assert failed["segment_anchor_gate_label"] == 0
    assert failed["segment_anchor_gate_task_mask"]
    assert unknown["carrier_task_mask"]
    assert unknown["fallback_scope"] is None
    assert not unknown["fallback_scope_task_mask"]
    assert not unknown["segment_anchor_gate_task_mask"]
    assert counts["failed_segment_scope_violation"] == 0


def test_t11_positive_object_outside_frozen_candidates_is_explicit_fallback() -> None:
    candidate_missing = _anchor(
        "candidate-missing",
        reason="t11_manual:1v1_rcsd_road:object_selection_masked",
        gate_label=1,
    )
    unknown = _anchor(
        "unknown",
        reason="t05:relation_record_absent:anchor_truth_unknown:masked",
        gate_label=0,
        supervised=False,
    )

    transformed_anchors, anchor_counts = apply_anchor_supervision_policy(
        [candidate_missing, unknown]
    )
    missing = transformed_anchors[0]
    assert missing.status_label == ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
    assert missing.status_supervised
    assert missing.gate_supervised
    assert missing.gate_label == 0
    assert not missing.candidate_supervised
    assert missing.label_reason.endswith(
        ":candidate_missing:segment_fallback"
    )
    assert anchor_counts["known_candidate_missing"] == 1
    assert anchor_counts["t11_manual_candidate_missing"] == 1
    assert anchor_counts["known_candidate_missing_supervised_failure"] == 1

    transformed_plans, plan_counts = apply_plan_supervision_policy(
        [
            {
                "case_key": "T10:case",
                "segment_id": "segment",
                "carrier_task_mask": True,
            }
        ],
        groups=[
            {
                "case_key": "T10:case",
                "segment_id": "segment",
                "segment_type": "STANDARD",
                "required_anchor_ids": [
                    "candidate-missing",
                    "unknown",
                ],
            }
        ],
        anchor_examples=transformed_anchors,
    )
    plan = transformed_plans[0]
    assert plan["anchor_supervision_state"] == "FAILED"
    assert not plan["carrier_task_mask"]
    assert plan["fallback_scope"] == "SEGMENT"
    assert plan_counts["failed_segment_scope_violation"] == 0


def test_formal_and_weak_success_outside_candidates_are_not_releasable() -> None:
    reasons = (
        (
            "formal_t03_t04_to_t05:road_only_split:"
            "final_object_unreachable"
        ),
        (
            "t05:road_only_split:t03_b2_road_only_support:"
            "object_selection_masked"
        ),
    )
    examples = [
        _anchor(
            str(index),
            reason=reason,
            gate_label=1,
        )
        for index, reason in enumerate(reasons)
    ]

    transformed, counts = apply_anchor_supervision_policy(examples)

    assert all(
        row.status_label == ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
        and row.status_supervised
        and row.gate_supervised
        and row.gate_label == 0
        and not row.candidate_supervised
        and row.label_reason.endswith(
            ":candidate_missing:segment_fallback"
        )
        for row in transformed
    )
    assert counts["known_candidate_missing"] == 2
    assert counts["formal_t03_t04_candidate_missing"] == 1
    assert counts["t05_weak_candidate_missing"] == 1
    assert counts["known_candidate_missing_supervised_failure"] == 2


def test_member_decodable_truth_is_not_forced_to_fallback() -> None:
    source = _anchor(
        "member-decodable",
        reason=(
            "t05:road_only_split:t03_b2_road_only_support:"
            "object_selection_masked"
        ),
        gate_label=1,
    )
    source = AnchorPretrainExample(
        **{
            **source.__dict__,
            "candidate_ids": ("ROAD:r1",),
            "candidate_features": (
                tuple(
                    1.0 if index == 27 else 0.0
                    for index in range(64)
                ),
            ),
            "structural_member_ids": ("ROAD:r1",),
            "member_arm_features": ((),),
            "member_acceptable_sets": ((0,),),
            "member_supervised": True,
        }
    )

    transformed, counts = apply_anchor_supervision_policy([source])

    assert transformed[0].status_label == ANCHOR_STATUS_INDEX[
        AnchorStatus.SUCCESS
    ]
    assert transformed[0].gate_label == 1
    assert counts["known_candidate_missing"] == 0


def test_confirmed_no_evidence_anchor_produces_positive_keep_state() -> None:
    no_evidence = _anchor(
        "no-evidence",
        reason="user_confirmed:no_rcsd_evidence:positive_keep_swsd_clue_false",
        gate_label=1,
    )
    no_evidence = AnchorPretrainExample(
        **{
            **no_evidence.__dict__,
            "status_label": ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE],
        }
    )

    transformed, counts = apply_plan_supervision_policy(
        [
            {
                "case_key": "T10:case",
                "segment_id": "segment",
                "preferred_carrier_target": "KEEP_SWSD",
            }
        ],
        groups=[
            {
                "case_key": "T10:case",
                "segment_id": "segment",
                "segment_type": "STANDARD",
                "required_anchor_ids": ["no-evidence"],
            }
        ],
        anchor_examples=[no_evidence],
        confirmed_no_evidence_segment_keys={("T10:case", "segment")},
    )

    row = transformed[0]
    assert row["carrier_task_mask"]
    assert row["keep_reason"] == "NO_RCSD_EVIDENCE"
    assert row["fallback_scope"] == "NONE"
    assert row["reality_change_clue"] is False
    assert row["segment_anchor_gate_label"] == 1
    assert counts["positive_keep_proven_no_evidence"] == 1


def test_segment_without_required_anchor_is_resolved_by_empty_gate() -> None:
    transformed, _ = apply_plan_supervision_policy(
        [
            {
                "case_key": "T10:case",
                "segment_id": "segment",
                "preferred_carrier_target": "KEEP_SWSD",
            }
        ],
        groups=[
            {
                "case_key": "T10:case",
                "segment_id": "segment",
                "segment_type": "STANDARD",
                "required_anchor_ids": [],
            }
        ],
        anchor_examples=[],
    )

    row = transformed[0]
    assert row["anchor_supervision_state"] == "RESOLVED"
    assert row["segment_anchor_gate_label"] == 1
    assert row["segment_anchor_gate_task_mask"]
    assert row["carrier_task_mask"]


def test_user_visual_anchor_overrides_strategy_failure_as_gate_only_truth() -> None:
    source = _anchor(
        "621989990",
        reason="t05:t_junction_not_strict_single_surface:unresolved:abstain",
        gate_label=0,
        case_key="T10-Error:501386978_504378551",
    )

    transformed, counts = apply_anchor_supervision_policy([source])

    row = transformed[0]
    assert (
        row.status_label
        == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
    )
    assert row.status_supervised
    assert row.gate_label == 1
    assert row.gate_supervised
    assert not row.candidate_supervised
    assert row.candidate_acceptable_indices == ()
    assert row.preferred_candidate_index == -1
    assert row.sample_weight == 1.0
    assert row.label_reason.endswith("object_unspecified")
    assert counts["user_manual_anchor_adjudication"] == 1
