from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p5_dataset import (
    build_scope_first_overlay_labels,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p5_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_MODEL_GO,
    DECISION_MODEL_NO_GO,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p5_oof import (
    choose_p5_decision,
    replay_advance_right_gate,
)


def test_overlay_labels_keep_context_out_of_supervision() -> None:
    labels, audit = build_scope_first_overlay_labels(
        [
            _segment_truth("target", eligible=True, anomaly=True),
            _segment_truth("context", eligible=False, anomaly=None),
        ],
        [_node_truth()],
    )

    target = next(row for row in labels if row["object_id"] == "target")
    context = next(row for row in labels if row["object_id"] == "context")
    assert target["label_weight"] == 0.7
    assert target["anomaly_target"] is True
    assert context["label_weight"] == 0.3
    assert context["weight_role"] == "CONTEXT"
    assert context["anomaly_target"] is False
    assert context["safe_materialization_only"] is True
    assert audit["eligible_count"] == 1
    assert audit["context_count"] == 1
    assert audit["eligible_anomaly_count"] == 1
    assert audit["context_supervision_count"] == 0


def test_replay_applies_frozen_access_gate_only_to_invalid_advance_right() -> None:
    invalid = _decision("advance", accepted=True)
    standard = _decision("standard", accepted=True)
    replayed, changes = replay_advance_right_gate(
        [invalid, standard],
        {
            invalid["group_id"]: _segment(
                "advance",
                segment_type="ADVANCE_RIGHT",
                access_valid="False",
            ),
            standard["group_id"]: _segment(
                "standard",
                segment_type="STANDARD",
                access_valid="False",
            ),
        },
    )

    assert replayed[0]["accepted"] is False
    assert replayed[0]["reason"] == "advance_right_access_invalid"
    assert replayed[0]["clue_predicted"] is True
    assert replayed[1] == standard
    assert len(changes) == 1
    assert changes[0]["group_id"] == invalid["group_id"]


def test_stage_decision_separates_audit_and_model_failures() -> None:
    assert choose_p5_decision(False, True) == DECISION_AUDIT_NO_GO
    assert choose_p5_decision(True, False) == DECISION_MODEL_NO_GO
    assert choose_p5_decision(True, True) == DECISION_MODEL_GO


def _segment_truth(
    object_id: str,
    *,
    eligible: bool,
    anomaly: bool | None,
) -> dict[str, object]:
    return {
        "case_key": "T10:case",
        "object_id": object_id,
        "group_id": f"SCHEME_A_P1:SEGMENT:T10:case:{object_id}",
        "fold": 1,
        "label_eligible": eligible,
        "label_weight": 0.7 if eligible else None,
        "effective_truth_candidate_id": f"candidate-{object_id}",
        "effective_carrier_target": (
            "USE_RCSD" if eligible else "KEEP_SWSD"
        ),
        "effective_available": True,
        "effective_anomaly_target": anomaly,
    }


def _node_truth() -> dict[str, object]:
    return {
        "schema_version": "old",
        "case_key": "T10:case",
        "object_type": "NODE",
        "object_id": "node-1",
        "group_id": "P2P1:NODE:T10:case:node-1",
        "junction_key": "T10:case:MAINNODE:node-1",
        "truth_candidate_id": "node-candidate",
        "carrier_target": "T01_NODE",
        "available": True,
        "anomaly_target": False,
        "label_weight": 1.0,
        "weight_role": "TARGET",
        "fold": 1,
        "label_only": True,
    }


def _decision(object_id: str, *, accepted: bool) -> dict[str, object]:
    return {
        "seed": 311,
        "case_key": "T10:case",
        "object_id": object_id,
        "group_id": f"SCHEME_A_P1:SEGMENT:T10:case:{object_id}",
        "accepted": accepted,
        "clue_predicted": False,
        "reason": "hierarchical_carrier_accept",
    }


def _segment(
    object_id: str,
    *,
    segment_type: str,
    access_valid: str,
) -> dict[str, str]:
    return {
        "case_key": "T10:case",
        "segment_id": object_id,
        "segment_type": segment_type,
        "access_valid": access_valid,
    }
