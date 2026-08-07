from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_teacher_student import (
    apply_oof_upstream_truth,
    labeled_conditioned_example,
    weighted_training_views,
)


def _side(source: str, road_id: str) -> dict[str, object]:
    return {
        "owner_segment_id": f"{source}-owner",
        "t01_access_node_id": f"{source}-access",
        "object_feature_values": [0.0] * 64,
        "road_candidates": [
            {
                "road_id": road_id,
                "source": source,
                "start_node_id": f"{source}-start",
                "end_node_id": f"{source}-end",
                "feature_values": [0.0] * 40,
            }
        ],
        "access_candidates": [],
    }


def _condition(source: str, road_id: str) -> dict[str, object]:
    return {
        "selected_road_ids": [road_id],
        "selected_decision": (
            "USE_RCSD" if source == "RCSD" else "KEEP_SWSD"
        ),
        "access_source": source,
        "access_source_resolved": True,
        "access_road_ids": [],
        "access_road_resolved": False,
        "carrier_probability": 1.0,
        "ordinary_release_ready": True,
        "access_release_ready": False,
        "complete_release_ready": False,
        "resolution": "ACCESS_UNKNOWN",
        "condition_uses_truth": True,
    }


def test_teacher_source_can_train_carrier_without_claiming_complete_safety() -> None:
    feature = {
        "schema_version": "test",
        "case_key": "case",
        "object_id": "ar",
        "fold": 0,
        "fixed_swsd_road_ids": ["fixed"],
        "access_valid": True,
        "source_side": _side("RCSD", "left"),
        "target_side": _side("SWSD", "right"),
        "candidate_rows": [
            {
                "bundle_id": "bundle",
                "candidate_road_id": "candidate",
                "local_feature_values": [0.0] * 50,
                "raw_snodeid": "RCSD-start",
                "raw_enodeid": "SWSD-end",
            }
        ],
    }
    condition = {
        "source_condition": _condition("RCSD", "left"),
        "target_condition": _condition("SWSD", "right"),
        "both_access_source_resolved": True,
        "both_access_road_resolved": False,
        "condition_kind": "TEACHER_ORDINARY_FINAL_STATE",
    }
    label = {
        "truth_plan_type": "MIXED_SPLICE",
        "plan_task_mask": True,
        "acceptable_rcsd_candidate_ids_by_truth_road": {
            "truth": ["candidate"]
        },
        "label_weight": 0.7,
    }
    example = labeled_conditioned_example(feature, condition, label)
    assert example["truth_plan_type"] == "MIXED_SPLICE"
    assert example["candidate_supervised"]
    assert example["carrier_safety_target"]
    assert not example["complete_safety_target"]
    assert not example["safety_target"]
    assert example["label_weight"] == 0.7


def test_oof_unique_access_is_not_safe_until_it_matches_teacher() -> None:
    teacher = {
        "case_key": "case",
        "object_id": "ar",
        "candidate_supervised": True,
        "source_context": {
            "data_source": "RCSD",
            "road_members": [{"road_id": "left"}],
            "access_rows": [{"road_id": "left-access"}],
        },
        "target_context": {
            "data_source": "RCSD",
            "road_members": [{"road_id": "right"}],
            "access_rows": [{"road_id": "right-access"}],
        },
    }
    oof = {
        **teacher,
        "source_context": {
            "data_source": "RCSD",
            "road_members": [{"road_id": "left"}],
            "access_rows": [{"road_id": "wrong-left-access"}],
        },
        "safety_target": True,
    }
    result = apply_oof_upstream_truth(
        oof,
        teacher_by_key={("case", "ar"): teacher},
    )
    assert result["upstream_ordinary_road_set_exact"]
    assert not result["upstream_ordinary_access_exact"]
    assert not result["upstream_ordinary_complete_exact"]
    assert not result["safety_target"]


def test_same_road_with_wrong_attachment_proposal_is_not_access_exact() -> None:
    teacher = {
        "case_key": "case",
        "object_id": "ar",
        "candidate_supervised": True,
        "source_context": {
            "data_source": "RCSD",
            "road_members": [{"road_id": "left"}],
            "access_rows": [
                {"road_id": "left-access", "proposal_id": "left-truth"}
            ],
        },
        "target_context": {
            "data_source": "RCSD",
            "road_members": [{"road_id": "right"}],
            "access_rows": [
                {"road_id": "right-access", "proposal_id": "right-truth"}
            ],
        },
    }
    oof = {
        **teacher,
        "source_context": {
            "data_source": "RCSD",
            "road_members": [{"road_id": "left"}],
            "access_rows": [
                {"road_id": "left-access", "proposal_id": "left-wrong"}
            ],
        },
        "safety_target": True,
    }
    result = apply_oof_upstream_truth(
        oof,
        teacher_by_key={("case", "ar"): teacher},
    )
    assert result["upstream_ordinary_road_set_exact"]
    assert result["upstream_ordinary_source_exact"]
    assert result["upstream_ordinary_access_proposal_truth_known"]
    assert not result["upstream_ordinary_access_proposal_exact"]
    assert not result["upstream_ordinary_access_exact"]
    assert not result["upstream_ordinary_complete_exact"]
    assert not result["safety_target"]


def test_swsd_access_is_exact_when_frozen_source_and_road_set_match() -> None:
    teacher = {
        "case_key": "case",
        "object_id": "ar",
        "candidate_supervised": True,
        "source_context": {
            "data_source": "SWSD",
            "road_members": [{"road_id": "left"}],
            "access_rows": [],
        },
        "target_context": {
            "data_source": "SWSD",
            "road_members": [{"road_id": "right"}],
            "access_rows": [],
        },
    }
    oof = {
        **teacher,
        "safety_target": False,
    }
    result = apply_oof_upstream_truth(
        oof,
        teacher_by_key={("case", "ar"): teacher},
    )
    assert result["upstream_ordinary_source_exact"]
    assert result["upstream_ordinary_access_truth_known"]
    assert result["upstream_ordinary_access_exact"]
    assert result["upstream_ordinary_complete_exact"]
    assert result["safety_target"]


def test_locked_fallback_state_is_safe_without_claiming_teacher_exact() -> None:
    teacher = {
        "case_key": "case",
        "object_id": "ar",
        "candidate_supervised": True,
        "source_context": {
            "data_source": "RCSD",
            "road_members": [{"road_id": "left-rcsd"}],
            "access_rows": [{"road_id": "left-rcsd"}],
        },
        "target_context": {
            "data_source": "RCSD",
            "road_members": [{"road_id": "right-rcsd"}],
            "access_rows": [{"road_id": "right-rcsd"}],
        },
    }
    fallback_context = {
        "data_source": "SWSD",
        "selected_decision": "ABSTAIN",
        "road_members": [{"road_id": "frozen-swsd"}],
        "access_rows": [],
        "resolved": True,
        "required_access_resolved": True,
    }
    oof = {
        **teacher,
        "source_context": dict(fallback_context),
        "target_context": dict(fallback_context),
    }
    result = apply_oof_upstream_truth(
        oof,
        teacher_by_key={("case", "ar"): teacher},
        trust_locked_final_state=True,
    )
    assert not result["upstream_ordinary_source_exact"]
    assert not result["upstream_ordinary_complete_exact"]
    assert result["upstream_locked_final_state_valid"]
    assert result["safety_basis"] == "LOCKED_FINAL_STATE"
    assert result["safety_target"]


def test_locked_rcsd_state_without_access_is_not_safe() -> None:
    context = {
        "data_source": "RCSD",
        "selected_decision": "USE_RCSD",
        "road_members": [{"road_id": "rcsd"}],
        "access_rows": [],
        "resolved": True,
        "required_access_resolved": False,
    }
    teacher = {
        "case_key": "case",
        "object_id": "ar",
        "candidate_supervised": True,
        "source_context": dict(context),
        "target_context": dict(context),
    }
    result = apply_oof_upstream_truth(
        teacher,
        teacher_by_key={("case", "ar"): teacher},
        trust_locked_final_state=True,
    )
    assert not result["upstream_locked_final_state_valid"]
    assert not result["safety_target"]


def test_dual_training_views_apply_independent_loss_weights() -> None:
    teacher = [{"case_key": "case", "object_id": "ar", "label_weight": 0.8}]
    oof = [{"case_key": "case", "object_id": "ar", "label_weight": 0.8}]
    combined = weighted_training_views(
        teacher,
        oof,
        teacher_weight=0.25,
        oof_weight=1.0,
    )
    assert [row["training_condition"] for row in combined] == [
        "TEACHER_ORDINARY",
        "STRICT_OOF_ORDINARY",
    ]
    assert [row["label_weight"] for row in combined] == [0.2, 0.8]
    assert "training_condition" not in teacher[0]
    assert "training_condition" not in oof[0]
