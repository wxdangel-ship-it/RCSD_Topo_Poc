from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_conditioning import (
    _build_segment_gate_rows,
    _segment_gate_summary,
    _t05_anchor_sample_id,
)


def test_anchor_conditioning_requires_every_semantic_anchor() -> None:
    case_key = "T10:case"
    anchor_one = _t05_anchor_sample_id(case_key, "a1")
    anchor_two = _t05_anchor_sample_id(case_key, "a2")
    groups = {
        (case_key, "segment"): {
            "required_anchor_ids": ["a1", "a2"],
        }
    }
    labels = [
        {
            "case_key": case_key,
            "segment_id": "segment",
            "fold": 2,
            "segment_type": "STANDARD",
            "training_task_mask": True,
            "acceptable_plan_ids": ["plan"],
        }
    ]
    anchor_rows = {
        anchor_one: {
            "consensus_safety_accepted": True,
            "consensus_proven_safe_anchor": True,
            "consensus_candidate_index": 3,
        },
        anchor_two: {
            "consensus_safety_accepted": False,
            "consensus_proven_safe_anchor": True,
            "consensus_candidate_index": 1,
        },
    }
    plans = {
        f"{case_key}:segment": {
            "predicted_plan_id": "plan",
            "predicted_decision": "USE_RCSD",
            "acceptable_exact": True,
        }
    }

    rows = _build_segment_gate_rows(
        groups=groups,
        labels=labels,
        anchor_rows=anchor_rows,
        plan_predictions=plans,
    )

    assert len(rows) == 1
    assert rows[0]["anchor_gate_accepted"] is False
    assert rows[0]["chain_safe_auto"] is False


def test_no_required_semantic_anchor_does_not_invent_a_gate() -> None:
    case_key = "T10:case"
    rows = _build_segment_gate_rows(
        groups={(case_key, "segment"): {"required_anchor_ids": []}},
        labels=[
            {
                "case_key": case_key,
                "segment_id": "segment",
                "fold": 0,
                "segment_type": "STANDARD",
                "training_task_mask": True,
                "acceptable_plan_ids": ["keep"],
            }
        ],
        anchor_rows={},
        plan_predictions={
            f"{case_key}:segment": {
                "predicted_plan_id": "keep",
                "predicted_decision": "KEEP_SWSD",
                "acceptable_exact": True,
            }
        },
    )
    summary = _segment_gate_summary(rows)

    assert rows[0]["anchor_gate_accepted"] is True
    assert rows[0]["chain_safe_auto"] is True
    assert summary["safety_gate_pass"] is True
