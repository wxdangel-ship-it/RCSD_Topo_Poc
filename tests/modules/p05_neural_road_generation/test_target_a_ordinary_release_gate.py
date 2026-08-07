from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_release_gate import (
    _business_output_map,
    _selected_business_truth_result,
    compose_ordinary_anchor_release_gate,
    compose_ordinary_ensemble_release_gate,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _prediction(
    segment_id: str,
    *,
    exact: bool,
    decision: str = "USE_RCSD",
    ownership: str = "OWNER_CURRENT_SEGMENT",
    business_role: str = "MAIN",
    no_evidence_proof: bool = False,
) -> dict[str, object]:
    road_id = f"road-{segment_id}"
    return {
        "case_key": "T10:case",
        "segment_id": segment_id,
        "fold": 2,
        "automatic": True,
        "complete_exact": exact,
        "decision_exact": exact,
        "road_set_exact": exact,
        "road_f1": float(exact),
        "release_eligible": True,
        "predicted_decision": decision,
        "selected_road_ids": [road_id],
        "selected_road_business_roles": [
            {
                "road_id": road_id,
                "ownership": ownership,
                "business_role": business_role,
            }
        ],
        "ownership_exact": exact,
        "business_role_exact": exact,
        "inference_no_evidence_proof_passed": no_evidence_proof,
    }


def test_required_anchor_gate_blocks_unsafe_segment_locally(
    tmp_path: Path,
) -> None:
    ordinary = tmp_path / "ordinary.jsonl"
    features = tmp_path / "features.jsonl"
    anchors = tmp_path / "anchors.jsonl"
    output = tmp_path / "output"
    _write_jsonl(
        ordinary,
        [
            _prediction("safe", exact=True),
            _prediction("unsafe", exact=False, decision="KEEP_SWSD"),
            _prediction(
                "empty-required",
                exact=True,
                decision="KEEP_SWSD",
            ),
            _prediction(
                "proven-no-evidence",
                exact=True,
                decision="KEEP_SWSD",
                no_evidence_proof=True,
            ),
        ],
    )
    _write_jsonl(
        features,
        [
            {
                "case_key": "T10:case",
                "segment_id": "safe",
                "required_anchor_ids": ["a"],
            },
            {
                "case_key": "T10:case",
                "segment_id": "unsafe",
                "required_anchor_ids": ["b"],
            },
            {
                "case_key": "T10:case",
                "segment_id": "empty-required",
                "required_anchor_ids": [],
            },
            {
                "case_key": "T10:case",
                "segment_id": "proven-no-evidence",
                "required_anchor_ids": [],
            },
        ],
    )
    _write_jsonl(
        anchors,
        [
            {
                "case_key": "T10:case",
                "anchor_id": "a",
                "outer_fold": 2,
                "safety_accepted": True,
            },
            {
                "case_key": "T10:case",
                "anchor_id": "b",
                "outer_fold": 2,
                "safety_accepted": False,
            },
        ],
    )
    compose_ordinary_anchor_release_gate(
        ordinary_predictions_path=ordinary,
        ordinary_feature_path=features,
        anchor_gated_predictions_path=anchors,
        output_root=output,
    )
    summary = json.loads((output / "summary.json").read_text())
    assert summary["metrics"]["automatic_count"] == 2
    assert summary["metrics"]["unsafe_automatic_count"] == 0
    rows = [
        json.loads(line)
        for line in (output / "gated_oof_predictions.jsonl")
        .read_text()
        .splitlines()
    ]
    by_segment = {row["segment_id"]: row for row in rows}
    assert by_segment["empty-required"]["effective_decision"] == "ABSTAIN"
    assert by_segment["safe"]["effective_decision"] == "USE_RCSD"
    assert by_segment["unsafe"]["effective_decision"] == "ABSTAIN"
    assert (
        by_segment["proven-no-evidence"]["effective_decision"]
        == "KEEP_SWSD"
    )
    confirmation = tmp_path / "confirmation.jsonl"
    _write_jsonl(
        confirmation,
        [
            _prediction("safe", exact=True),
            _prediction("unsafe", exact=False, decision="KEEP_SWSD"),
            _prediction(
                "empty-required",
                exact=True,
                decision="KEEP_SWSD",
            ),
            _prediction(
                "proven-no-evidence",
                exact=True,
                decision="KEEP_SWSD",
                no_evidence_proof=True,
            ),
        ],
    )
    ensemble_output = tmp_path / "ensemble"
    compose_ordinary_ensemble_release_gate(
        primary_anchor_gated_predictions_path=output
        / "gated_oof_predictions.jsonl",
        confirmation_predictions_path=confirmation,
        output_root=ensemble_output,
    )
    ensemble_summary = json.loads(
        (ensemble_output / "summary.json").read_text()
    )
    assert ensemble_summary["metrics"]["automatic_count"] == 2
    assert ensemble_summary["metrics"]["unsafe_automatic_count"] == 0
    assert ensemble_summary["automatic_USE_RCSD_count"] == 1
    assert ensemble_summary["automatic_KEEP_SWSD_count"] == 1


def test_ensemble_requires_complete_consistent_business_output(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary.jsonl"
    confirmation = tmp_path / "confirmation.jsonl"
    output = tmp_path / "output"
    primary_row = _prediction("segment", exact=True)
    primary_row.update(
        {
            "ordinary_decoder_automatic": True,
            "required_anchor_gate_passed": True,
            "anchor_prerequisite_passed": True,
        }
    )
    confirmation_row = _prediction(
        "segment",
        exact=True,
        business_role="INTERNAL_CONNECTOR",
    )
    _write_jsonl(primary, [primary_row])
    _write_jsonl(confirmation, [confirmation_row])
    compose_ordinary_ensemble_release_gate(
        primary_anchor_gated_predictions_path=primary,
        confirmation_predictions_path=confirmation,
        output_root=output,
    )
    summary = json.loads((output / "summary.json").read_text())
    assert summary["metrics"]["automatic_count"] == 0
    assert summary["ensemble_business_output_disagreement_count"] == 1


def test_selected_business_truth_is_checked_only_when_evaluable() -> None:
    predicted = {
        "road": ("OWNER_CURRENT_SEGMENT", "MAIN"),
    }
    assert _selected_business_truth_result(
        predicted,
        (predicted, True),
    ) == (True, True)
    assert _selected_business_truth_result(
        predicted,
        ({"road": ("OWNER_CURRENT_SEGMENT", "ATTACHED_SWSD")}, True),
    ) == (True, False)
    assert _selected_business_truth_result(
        predicted,
        (predicted, False),
    ) == (False, False)
    assert _business_output_map(
        {
            "selected_road_ids": ["road"],
            "selected_road_business_roles": [],
        }
    ) is None
