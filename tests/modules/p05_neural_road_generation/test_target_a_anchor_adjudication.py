from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_adjudication import (
    CSV_FIELDS,
    AnchorAdjudicationDecision,
    AnchorManualAdjudication,
    apply_anchor_adjudication_labels,
    read_anchor_adjudication_csv,
    write_anchor_adjudication_overlay,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_label_policy import (
    apply_plan_supervision_policy,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
    write_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)


def test_csv_accepts_exact_bundle_candidate_without_splitting_pipe(
    tmp_path: Path,
) -> None:
    queue = _queue_row(
        candidate_ids=["NODE:1", "ROAD:10|11|12"],
    )
    queue_path, csv_path = _write_queue_and_csv(
        tmp_path,
        [queue],
        decisions={
            ("T10:case", "anchor"): (
                "SUCCESS_UNIQUE",
                "ROAD:10|11|12",
                "visual evidence selects the complete Road bundle",
            )
        },
    )

    adjudications = read_anchor_adjudication_csv(
        csv_path=csv_path,
        queue_path=queue_path,
    )

    assert len(adjudications) == 1
    assert (
        adjudications[0].decision
        is AnchorAdjudicationDecision.SUCCESS_UNIQUE
    )
    assert adjudications[0].selected_candidate_id == "ROAD:10|11|12"


@pytest.mark.parametrize(
    ("decision", "selected", "note", "error"),
    [
        ("", "", "", "incomplete"),
        (
            "SUCCESS_UNIQUE",
            "ROAD:not-frozen",
            "visual evidence",
            "outside the frozen candidate set",
        ),
        (
            "PROVEN_NO_EVIDENCE",
            "NODE:1",
            "formal no-evidence proof",
            "must not select a candidate",
        ),
        (
            "AMBIGUOUS",
            "",
            "",
            "lacks an evidence note",
        ),
    ],
)
def test_csv_rejects_incomplete_or_semantically_invalid_rows(
    tmp_path: Path,
    decision: str,
    selected: str,
    note: str,
    error: str,
) -> None:
    queue_path, csv_path = _write_queue_and_csv(
        tmp_path,
        [_queue_row()],
        decisions={
            ("T10:case", "anchor"): (decision, selected, note),
        },
    )

    with pytest.raises(ValueError, match=error):
        read_anchor_adjudication_csv(
            csv_path=csv_path,
            queue_path=queue_path,
        )


def test_csv_rejects_changes_to_frozen_evidence_columns(
    tmp_path: Path,
) -> None:
    queue_path, csv_path = _write_queue_and_csv(
        tmp_path,
        [_queue_row()],
        decisions={
            ("T10:case", "anchor"): (
                "AMBIGUOUS",
                "",
                "two plausible RCSD objects remain",
            )
        },
        immutable_overrides={"model_candidate_id": "NODE:tampered"},
    )

    with pytest.raises(ValueError, match="changed frozen field"):
        read_anchor_adjudication_csv(
            csv_path=csv_path,
            queue_path=queue_path,
        )


def test_adjudication_labels_preserve_four_business_outcomes() -> None:
    decisions = (
        AnchorAdjudicationDecision.SUCCESS_UNIQUE,
        AnchorAdjudicationDecision.PROVEN_NO_EVIDENCE,
        AnchorAdjudicationDecision.AMBIGUOUS,
        AnchorAdjudicationDecision.CANDIDATE_MISSING,
    )
    examples = [
        _anchor(str(index))
        for index, _ in enumerate(decisions)
    ]
    adjudications = [
        AnchorManualAdjudication(
            case_key="T10:case",
            anchor_id=str(index),
            decision=decision,
            selected_candidate_id=(
                "ROAD:10|11"
                if decision is AnchorAdjudicationDecision.SUCCESS_UNIQUE
                else ""
            ),
            evidence_note=f"evidence {index}",
            affected_segment_ids=(f"segment-{index}",),
            queue_sample_id=f"anchor:{index}",
            source_row_number=index + 2,
        )
        for index, decision in enumerate(decisions)
    ]

    transformed, counts = apply_anchor_adjudication_labels(
        examples,
        adjudications=adjudications,
    )

    success, no_evidence, ambiguous, missing = transformed
    assert success.status_label == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
    assert success.gate_label == 1
    assert success.candidate_supervised
    assert success.candidate_acceptable_indices == (1,)
    assert (
        no_evidence.status_label
        == ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
    )
    assert no_evidence.gate_label == 1
    assert not no_evidence.candidate_supervised
    assert (
        ambiguous.status_label
        == ANCHOR_STATUS_INDEX[AnchorStatus.AMBIGUOUS]
    )
    assert ambiguous.gate_label == 0
    assert missing.status_label == ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
    assert missing.gate_label == 0
    assert all(row.sample_weight == 1.0 for row in transformed)
    assert counts["adjudicated_anchor"] == 4
    assert counts["segment_fallback_gate"] == 2


def test_one_known_failed_anchor_stops_segment_even_if_peer_is_unknown() -> None:
    failed = _anchor("failed")
    failed = AnchorPretrainExample(
        **{
            **failed.__dict__,
            "status_label": ANCHOR_STATUS_INDEX[AnchorStatus.AMBIGUOUS],
            "status_supervised": True,
            "gate_label": 0,
            "gate_supervised": True,
            "label_reason": "user_phase1_anchor:ambiguous:segment_fallback",
        }
    )
    unknown = _anchor("unknown")

    transformed, counts = apply_plan_supervision_policy(
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
                "required_anchor_ids": ["failed", "unknown"],
            }
        ],
        anchor_examples=[failed, unknown],
    )

    row = transformed[0]
    assert row["anchor_supervision_state"] == "FAILED"
    assert row["segment_anchor_gate_label"] == 0
    assert not row["carrier_task_mask"]
    assert row["fallback_scope"] == "SEGMENT"
    assert counts["failed_segment_scope_violation"] == 0


def test_label_overlay_changes_only_labels_and_recomputes_local_gate(
    tmp_path: Path,
) -> None:
    source_anchor = write_anchor_pretraining_stores(
        [_anchor("anchor")],
        output_root=tmp_path,
        run_id="source-anchor",
    )
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    (candidate_root / "manifest.json").write_text("{}\n", encoding="utf-8")
    _write_jsonl(
        candidate_root / "inference_plan_groups.jsonl",
        [
            {
                "case_key": "T10:case",
                "segment_id": "segment",
                "segment_type": "STANDARD",
                "required_anchor_ids": ["anchor"],
            }
        ],
    )
    plan_root = tmp_path / "plan"
    plan_root.mkdir()
    _write_jsonl(
        plan_root / "training_plan_labels.jsonl",
        [
            {
                "case_key": "T10:case",
                "segment_id": "segment",
                "carrier_task_mask": True,
                "preferred_carrier_target": "USE_RCSD",
            }
        ],
    )
    queue_path, csv_path = _write_queue_and_csv(
        tmp_path,
        [_queue_row(impact_segment_ids=["segment"])],
        decisions={
            ("T10:case", "anchor"): (
                "CANDIDATE_MISSING",
                "",
                "correct RCSD object is outside the frozen candidates",
            )
        },
    )

    output = write_anchor_adjudication_overlay(
        anchor_store_root=source_anchor,
        candidate_store_root=candidate_root,
        plan_label_root=plan_root,
        queue_path=queue_path,
        adjudication_csv_path=csv_path,
        output_root=tmp_path,
        run_id="overlay",
    )

    assert sha256_file(
        source_anchor / "inference_feature_store" / "anchor_features.jsonl"
    ) == sha256_file(
        output
        / "anchor_store"
        / "inference_feature_store"
        / "anchor_features.jsonl"
    )
    anchor = read_anchor_pretraining_stores(output / "anchor_store")[0]
    assert anchor.status_label == ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
    assert anchor.status_supervised
    assert anchor.gate_supervised
    assert anchor.gate_label == 0
    plan = json.loads(
        (
            output
            / "plan_label_store"
            / "training_plan_labels.jsonl"
        ).read_text(encoding="utf-8")
    )
    assert plan["anchor_supervision_state"] == "FAILED"
    assert not plan["carrier_task_mask"]
    assert plan["fallback_scope"] == "SEGMENT"
    summary = json.loads(
        (output / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["gate_pass"]
    assert summary["feature_rows_recomputed"] == 0


def _anchor(anchor_id: str) -> AnchorPretrainExample:
    return AnchorPretrainExample(
        sample_id=f"anchor:{anchor_id}",
        case_key="T10:case",
        anchor_id=anchor_id,
        fold=2,
        object_features=(0.0,) * 64,
        candidate_ids=("NODE:1", "ROAD:10|11"),
        candidate_features=((0.0,) * 64, (0.0,) * 64),
        status_label=ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN],
        candidate_acceptable_indices=(),
        preferred_candidate_index=-1,
        candidate_supervised=False,
        sample_weight=0.7,
        input_hashes=(("input", "hash"),),
        label_reason=(
            "t05:relation_record_absent:anchor_truth_unknown:masked"
        ),
        dependency_anchor_ids=(anchor_id,),
        status_supervised=False,
        gate_label=0,
        gate_supervised=False,
    )


def _queue_row(
    *,
    candidate_ids: list[str] | None = None,
    impact_segment_ids: list[str] | None = None,
) -> dict[str, object]:
    candidates = candidate_ids or ["NODE:1", "ROAD:10|11"]
    impacts = impact_segment_ids or ["segment"]
    return {
        "priority": 1,
        "priority_reason": "UNVERIFIED_RELEASE_CANDIDATE",
        "case_key": "T10:case",
        "anchor_id": "anchor",
        "sample_id": "anchor:anchor",
        "fold": 2,
        "current_status": "ABSTAIN",
        "status_supervised": False,
        "candidate_supervised": False,
        "label_reason": (
            "t05:relation_record_absent:anchor_truth_unknown:masked"
        ),
        "candidate_count": len(candidates),
        "candidate_ids": candidates,
        "model_status": "NO_EVIDENCE",
        "model_candidate_id": candidates[0],
        "model_joint_score": 0.7,
        "model_no_evidence_probability": 0.8,
        "model_no_evidence_joint_score": 0.6,
        "model_no_evidence_proof_passed": True,
        "model_success_released": False,
        "impact_segment_count": len(impacts),
        "impact_segment_ids": impacts,
        "impact_unready_segment_count": len(impacts),
        "model_releasable_segment_count": 1,
        "review_auto_segment_count": 0,
        "review_auto_segment_ids": [],
        "unverified_releasable_segment_count": 1,
        "unverified_releasable_segment_ids": impacts,
        "manual_decision": "",
        "manual_selected_candidate_id": "",
        "manual_evidence_note": "",
        "manual_allowed_decisions": [
            "SUCCESS_UNIQUE",
            "PROVEN_NO_EVIDENCE",
            "AMBIGUOUS",
            "CANDIDATE_MISSING",
        ],
    }


def _write_queue_and_csv(
    root: Path,
    rows: list[dict[str, object]],
    *,
    decisions: dict[tuple[str, str], tuple[str, str, str]],
    immutable_overrides: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    queue_path = root / "queue.jsonl"
    _write_jsonl(queue_path, rows)
    csv_path = root / "adjudications.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for source in rows:
            row = {
                field: _csv_value(source[field], field)
                for field in CSV_FIELDS
                if field not in {
                    "manual_decision",
                    "manual_selected_candidate_id",
                    "manual_evidence_note",
                }
            }
            key = (str(source["case_key"]), str(source["anchor_id"]))
            decision, selected, note = decisions[key]
            row["manual_decision"] = decision
            row["manual_selected_candidate_id"] = selected
            row["manual_evidence_note"] = note
            row.update(immutable_overrides or {})
            writer.writerow(row)
    return queue_path, csv_path


def _csv_value(value: object, field: str) -> str:
    if field in {
        "candidate_ids",
        "impact_segment_ids",
        "review_auto_segment_ids",
        "unverified_releasable_segment_ids",
    }:
        return "|".join(str(item) for item in value)
    return str(value)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
