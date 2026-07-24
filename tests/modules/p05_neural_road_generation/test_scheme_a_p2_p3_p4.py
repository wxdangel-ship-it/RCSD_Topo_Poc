from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation import (
    scheme_a_p2_p3_p4_scope as scope_module,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p4_scope import (
    build_label_delta,
    build_scope_first_truth,
    rebaseline_metrics,
)


def test_scope_is_applied_before_junction_truth_closure(monkeypatch) -> None:
    eligible_key = ("T10:case", "target")
    context_key = ("T10:case", "context")
    baseline = {
        eligible_key: _label("target", "USE_RCSD", "use"),
        context_key: _label("context", "USE_RCSD", "use"),
    }
    candidates = {
        eligible_key: _candidates("target"),
        context_key: _candidates("context"),
    }
    calls: list[dict[tuple[str, str], str]] = []

    def fake_build(**kwargs):
        targets = {
            key: str(row["carrier_target"])
            for key, row in kwargs["segment_labels"].items()
        }
        calls.append(targets)
        if targets[eligible_key] == "USE_RCSD":
            return {
                "shared_payload_conflicts": [
                    {"case_key": "T10:case", "node_id": "n1"}
                ],
                "junction_fallback_segment_keys": [eligible_key],
                "missing": [],
                "labels": [],
            }
        return {
            "shared_payload_conflicts": [],
            "junction_fallback_segment_keys": [],
            "missing": [],
            "labels": [{"group_id": "node-1"}],
        }

    monkeypatch.setattr(
        scope_module,
        "build_endpoint_node_carriers",
        fake_build,
    )
    result = build_scope_first_truth(
        baseline_labels=baseline,
        segment_candidates=candidates,
        scope_rows=[
            _scope("target", eligible=True),
            _scope("context", eligible=False),
        ],
        pto_candidate_path=Path("pto.jsonl"),
        p1_lineage_path=Path("lineage.csv"),
        case_folds={"T10:case": 1},
        fallback_positive_segments=set(),
        expected_missing_nodes=(),
        iteration_limit=3,
    )

    assert calls[0][context_key] == "KEEP_SWSD"
    assert calls[0][eligible_key] == "USE_RCSD"
    assert calls[1][eligible_key] == "KEEP_SWSD"
    assert len(result["initial_node_conflicts"]) == 1
    assert result["junction_fallback_closure"][0]["label_eligible"] is True
    context = next(
        row for row in result["segment_labels"] if row["object_id"] == "context"
    )
    assert context["label_truth_contribution"] == 0
    assert context["safe_materialization_only"] is True
    assert context["effective_anomaly_target"] is None


def test_label_delta_keeps_context_out_of_anomaly_truth() -> None:
    corrected = [
        {
            "case_key": "T10:case",
            "object_id": "context",
            "group_id": "g-context",
            "scope_class": "CONTEXT_ONLY_MASKED",
            "label_eligible": False,
            "effective_carrier_target": "KEEP_SWSD",
            "effective_truth_candidate_id": "keep-context",
            "effective_anomaly_target": None,
        },
        {
            "case_key": "T10:case",
            "object_id": "target",
            "group_id": "g-target",
            "scope_class": "TARGET_LINEAGE_LABEL",
            "label_eligible": True,
            "effective_carrier_target": "USE_RCSD",
            "effective_truth_candidate_id": "use-target",
            "effective_anomaly_target": False,
        },
    ]
    old = [
        {
            "object_type": "SEGMENT",
            "group_id": "g-context",
            "carrier_target": "USE_RCSD",
            "truth_candidate_id": "use-context",
            "anomaly_target": True,
        },
        {
            "object_type": "SEGMENT",
            "group_id": "g-target",
            "carrier_target": "KEEP_SWSD",
            "truth_candidate_id": "keep-target",
            "anomaly_target": True,
        },
    ]

    rows = build_label_delta(corrected, old)

    assert len(rows) == 2
    context = next(row for row in rows if row["group_id"] == "g-context")
    assert "anomaly_target" not in context["changed_fields"]
    target = next(row for row in rows if row["group_id"] == "g-target")
    assert target["changed_fields"] == [
        "carrier_target",
        "truth_candidate_id",
        "anomaly_target",
    ]


def test_metric_rebaseline_uses_only_eligible_truth() -> None:
    corrected = [
        _corrected("g-use", "USE_RCSD", "use", anomaly=False, fold=1),
        _corrected(
            "g-review",
            "REVIEW_FALLBACK",
            "keep",
            anomaly=True,
            fold=1,
        ),
        {
            **_corrected(
                "g-context",
                "KEEP_SWSD",
                "keep-context",
                anomaly=False,
                fold=1,
            ),
            "label_eligible": False,
        },
    ]
    decisions = [
        _decision("g-use", clue=False),
        _decision("g-review", clue=True),
    ]
    evaluations = [
        _evaluation("g-use", "use"),
        _evaluation("g-review", "keep"),
    ]
    effective = [
        _effective("g-use", "use", accepted=True),
        _effective("g-review", "keep", accepted=False),
    ]

    result = rebaseline_metrics(
        corrected_rows=corrected,
        decisions=decisions,
        evaluations=evaluations,
        effective_rows=effective,
        model_seeds=(311,),
        minimum_safe_coverage=0.5,
        minimum_use_coverage=0.5,
        minimum_clue_precision=0.8,
        minimum_clue_macro_f1=0.85,
    )

    seed = result["seed_metrics"][0]
    assert seed["group_count"] == 2
    assert seed["carrier_wrong_accepted_count"] == 0
    assert seed["review_auto_publish_count"] == 0
    assert seed["carrier_safety_recall"] == 1.0
    assert result["model_gate_pass"] is True


def _label(object_id: str, target: str, payload: str) -> dict[str, object]:
    return {
        "case_key": "T10:case",
        "object_id": object_id,
        "carrier_target": target,
        "target_kind": "ROAD_IDS",
        "target_payload": [payload],
        "available": True,
        "fold": 1,
        "label_weight": 1.0,
        "weight_role": "TARGET",
    }


def _candidates(object_id: str) -> list[dict[str, object]]:
    group_id = f"SCHEME_A_P1:SEGMENT:T10:case:{object_id}"
    return [
        {
            "case_key": "T10:case",
            "object_id": object_id,
            "group_id": group_id,
            "candidate_id": f"keep-{object_id}",
            "candidate_target": "KEEP_SWSD",
            "target_kind": "ROAD_IDS",
            "target_payload": ["keep"],
        },
        {
            "case_key": "T10:case",
            "object_id": object_id,
            "group_id": group_id,
            "candidate_id": f"use-{object_id}",
            "candidate_target": "USE_RCSD",
            "target_kind": "ROAD_IDS",
            "target_payload": ["use"],
        },
    ]


def _scope(object_id: str, *, eligible: bool) -> dict[str, object]:
    return {
        "case_key": "T10:case",
        "object_id": object_id,
        "group_id": f"SCHEME_A_P1:SEGMENT:T10:case:{object_id}",
        "fold": 1,
        "scope_class": (
            "TARGET_LINEAGE_LABEL" if eligible else "CONTEXT_ONLY_MASKED"
        ),
        "label_eligible": eligible,
        "scorer_metric_eligible": eligible,
        "label_weight": 1.0 if eligible else None,
        "context_input_eligible": True,
        "context_input_weight": None if eligible else 0.3,
    }


def _corrected(
    group_id: str,
    target: str,
    candidate_id: str,
    *,
    anomaly: bool,
    fold: int,
) -> dict[str, object]:
    return {
        "group_id": group_id,
        "label_eligible": True,
        "fold": fold,
        "effective_carrier_target": target,
        "effective_truth_candidate_id": candidate_id,
        "effective_anomaly_target": anomaly,
    }


def _decision(group_id: str, *, clue: bool) -> dict[str, object]:
    return {"seed": 311, "group_id": group_id, "clue_predicted": clue}


def _evaluation(group_id: str, candidate_id: str) -> dict[str, object]:
    return {
        "seed": 311,
        "group_id": group_id,
        "selected_candidate_id": candidate_id,
    }


def _effective(
    group_id: str,
    candidate_id: str,
    *,
    accepted: bool,
) -> dict[str, object]:
    return {
        "seed": 311,
        "group_id": group_id,
        "object_type": "SEGMENT",
        "accepted": accepted,
        "effective_candidate_id": candidate_id,
    }
