import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_clue_scope_adjudication import (
    build_clue_scope_adjudication_bundle,
    compile_clue_scope_adjudications,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, separators=(",", ":")) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def test_adjudication_bundle_keeps_unreviewed_fields_unknown(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    preflight = tmp_path / "preflight"
    ordinary = tmp_path / "ordinary"
    safety = tmp_path / "safety"
    output = tmp_path / "output"
    groups = [
        {
            "case_key": "T10:case",
            "segment_id": "segment-a",
            "segment_type": "STANDARD",
            "required_anchor_ids": ["junction-1"],
            "candidates": [
                {
                    "plan_id": "keep",
                    "decision": "KEEP_SWSD",
                    "road_ids": ["swsd"],
                    "road_roles": [{"road_id": "swsd", "role": "MAIN"}],
                    "generator": "KEEP_T01",
                    "hard_valid": True,
                },
                {
                    "plan_id": "use",
                    "decision": "USE_RCSD",
                    "road_ids": ["rcsd"],
                    "road_roles": [{"road_id": "rcsd", "role": "MAIN"}],
                    "generator": "ANCHOR_PATH",
                    "hard_valid": True,
                },
            ],
        },
        {
            "case_key": "T10:case",
            "segment_id": "segment-b",
            "segment_type": "STANDARD",
            "required_anchor_ids": ["junction-1"],
            "candidates": [],
        },
        {
            "case_key": "T10-Error:directory-segment",
            "segment_id": "context-segment",
            "segment_type": "STANDARD",
            "required_anchor_ids": [],
            "candidates": [
                {
                    "plan_id": "context-keep",
                    "decision": "KEEP_SWSD",
                    "road_ids": ["context-swsd"],
                    "road_roles": [],
                    "generator": "KEEP_T01",
                    "hard_valid": True,
                }
            ],
        },
        {
            "case_key": "T10:case",
            "segment_id": "segment-control",
            "segment_type": "STANDARD",
            "required_anchor_ids": [],
            "candidates": [
                {
                    "plan_id": "control-use",
                    "decision": "USE_RCSD",
                    "road_ids": ["control-rcsd"],
                    "road_roles": [],
                    "generator": "ANCHOR_PATH",
                    "hard_valid": True,
                }
            ],
        },
    ]
    labels = [
        {
            "case_key": "T10:case",
            "segment_id": "segment-a",
            "label_origin": "confirmed_t10_strategy_replay",
            "label_weight": 0.7,
            "preferred_carrier_target": "KEEP_SWSD",
            "preferred_plan_id": "keep",
            "acceptable_plan_ids": ["keep"],
            "clue_task_mask": False,
            "fallback_scope_task_mask": False,
            "training_task_mask": True,
        },
        {
            "case_key": "T10-Error:directory-segment",
            "segment_id": "context-segment",
            "label_origin": "confirmed_t10_strategy_replay",
            "label_weight": 0.7,
            "preferred_carrier_target": "KEEP_SWSD",
            "preferred_plan_id": "context-keep",
            "acceptable_plan_ids": ["context-keep"],
            "clue_task_mask": False,
            "fallback_scope_task_mask": False,
            "training_task_mask": False,
        },
        {
            "case_key": "T10:case",
            "segment_id": "segment-control",
            "label_origin": "confirmed_t10_strategy_replay",
            "label_weight": 0.7,
            "preferred_carrier_target": "USE_RCSD",
            "preferred_plan_id": "control-use",
            "acceptable_plan_ids": ["control-use"],
            "clue_task_mask": False,
            "fallback_scope_task_mask": False,
            "training_task_mask": True,
        },
    ]
    predictions = [
        {
            "sample_id": "T10:case:segment-a",
            "case_key": "T10:case",
            "segment_id": "segment-a",
            "preferred_decision": "KEEP_SWSD",
            "effective_decision": "USE_RCSD",
            "raw_predicted_probability": 0.9,
            "raw_predicted_plan_id": "use",
            "automatic_decision": True,
            "acceptable_exact": False,
            "anchor_gate_fallback_required": False,
        },
        {
            "sample_id": "T10-Error:directory-segment:context-segment",
            "case_key": "T10-Error:directory-segment",
            "segment_id": "context-segment",
            "preferred_decision": "KEEP_SWSD",
            "effective_decision": "USE_RCSD",
            "raw_predicted_probability": 0.8,
            "raw_predicted_plan_id": "context-keep",
            "automatic_decision": True,
            "acceptable_exact": False,
            "anchor_gate_fallback_required": False,
        },
        {
            "sample_id": "T10:case:segment-control",
            "case_key": "T10:case",
            "segment_id": "segment-control",
            "preferred_decision": "USE_RCSD",
            "effective_decision": "USE_RCSD",
            "raw_predicted_probability": 0.8,
            "raw_predicted_plan_id": "control-use",
            "automatic_decision": True,
            "acceptable_exact": True,
            "anchor_gate_fallback_required": False,
        },
    ]
    safety_rows = [
        {
            **predictions[0],
            "use_safety_applied": True,
            "use_safety_accepted": True,
            "use_safety_unsafe_auto": True,
            "use_safety_score": 0.99,
            "use_safety_threshold": 0.95,
        },
        {
            **predictions[1],
            "use_safety_applied": True,
            "use_safety_accepted": True,
            "use_safety_unsafe_auto": True,
            "use_safety_score": 0.99,
            "use_safety_threshold": 0.95,
        },
    ]
    _write_jsonl(candidate / "inference_plan_groups.jsonl", groups)
    _write_jsonl(preflight / "training_plan_labels.jsonl", labels)
    _write_jsonl(ordinary / "oof_predictions.jsonl", predictions)
    (ordinary / "summary.json").write_text("{}", encoding="utf-8")
    _write_jsonl(safety / "safety_predictions.jsonl", safety_rows)

    root = build_clue_scope_adjudication_bundle(
        candidate_store_root=candidate,
        preflight_root=preflight,
        ordinary_oof_root=ordinary,
        safety_run_roots=[safety],
        output_root=output,
        run_id="review",
        controls_per_case_decision=0,
        phase1_control_backfill_sample_ids=[
            "T10:case:segment-control"
        ],
    )
    queue = [
        json.loads(line)
        for line in (root / "adjudication_queue.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))

    assert len(queue) == 2
    assert queue[0]["priority"] == "P0_SAFETY_UNSAFE"
    assert queue[0]["review_tasks"] == [
        "CARRIER_PLAN",
        "KEEP_REASON_CLUE_SCOPE",
    ]
    assert queue[0]["adjudication"]["review_status"] == "PENDING"
    assert queue[0]["adjudication"]["keep_reason"] == "UNKNOWN"
    assert queue[0]["adjudication"]["reality_change_clue"] is None
    assert queue[0]["adjudication"]["fallback_scope"] == "UNKNOWN"
    assert queue[0]["required_anchor_context"][0][
        "direct_related_segment_ids"
    ] == ["segment-a", "segment-b"]
    assert summary["automatic_adjudication_count"] == 0
    assert summary["t06_t11_automatic_mapping_count"] == 0
    assert {
        row["sample_id"] for row in queue
    } == {
        "T10:case:segment-a",
        "T10:case:segment-control",
    }
    assert summary["counts"]["reviewable_label_count"] == 2
    assert summary["counts"]["excluded_context_prediction_count"] == 1
    assert summary["counts"]["phase1_queue_count"] == 2
    assert summary["counts"]["phase1_carrier_plan_count"] == 2
    assert summary["counts"]["phase1_keep_reason_clue_scope_count"] == 1
    assert (
        summary["counts"]["phase1_control_backfill_selected_count"]
        == 1
    )
    assert summary["counts"]["remaining_queue_count"] == 0


def test_compile_adjudications_masks_carrier_when_anchor_unresolved(
    tmp_path: Path,
) -> None:
    preflight = tmp_path / "preflight"
    output = tmp_path / "output"
    labels = [
        {
            "case_key": "T10:case",
            "segment_id": "s-anchor",
            "training_task_mask": True,
            "preferred_carrier_target": "KEEP_SWSD",
            "label_origin": "confirmed_t10_strategy_replay",
            "label_weight": 0.7,
        },
        {
            "case_key": "T10:case",
            "segment_id": "s-positive",
            "training_task_mask": True,
            "preferred_carrier_target": "KEEP_SWSD",
            "label_origin": "confirmed_t10_strategy_replay",
            "label_weight": 0.7,
        },
    ]
    reviews = [
        {
            "sample_id": "T10:case:s-anchor",
            "existing_label": {
                "preferred_carrier_target": "KEEP_SWSD"
            },
            "adjudication": {
                "carrier_verdict": "EXISTING_ACCEPTABLE",
                "keep_reason": "ANCHOR_UNRESOLVED",
                "reality_change_clue": False,
                "fallback_scope": "SEGMENT",
                "review_status": "CONFIRMED",
                "review_note": "anchor unresolved",
            },
        },
        {
            "sample_id": "T10:case:s-positive",
            "existing_label": {
                "preferred_carrier_target": "KEEP_SWSD"
            },
            "adjudication": {
                "carrier_verdict": "EXISTING_ACCEPTABLE",
                "keep_reason": "NO_RCSD_EVIDENCE",
                "reality_change_clue": False,
                "fallback_scope": "NONE",
                "review_status": "CONFIRMED",
                "review_note": "no evidence",
            },
        },
    ]
    _write_jsonl(preflight / "training_plan_labels.jsonl", labels)
    (preflight / "summary.json").write_text(
        json.dumps({"stage": "COMPLETE_PLAN_CANDIDATE_PREFLIGHT"}),
        encoding="utf-8",
    )
    review_path = tmp_path / "reviews.jsonl"
    _write_jsonl(review_path, reviews)

    root = compile_clue_scope_adjudications(
        preflight_root=preflight,
        adjudication_path=review_path,
        output_root=output,
        run_id="compiled",
    )

    compiled = {
        f"{row['case_key']}:{row['segment_id']}": row
        for row in (
            json.loads(line)
            for line in (root / "training_plan_labels.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
    }
    anchor = compiled["T10:case:s-anchor"]
    positive = compiled["T10:case:s-positive"]
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert anchor["carrier_task_mask"] is False
    assert anchor["fallback_scope"] == "SEGMENT"
    assert anchor["clue_task_mask"] is True
    assert positive["carrier_task_mask"] is True
    assert positive["fallback_scope"] == "NONE"
    assert positive["label_weight"] == 1.0
    assert summary["gate_pass"] is True
    assert summary["counts"]["carrier_task_mask:false"] == 1
