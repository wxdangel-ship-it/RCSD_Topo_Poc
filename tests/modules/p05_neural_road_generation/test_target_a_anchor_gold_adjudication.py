from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_gold_adjudication import (
    CSV_FIELDS,
    QUEUE_SCHEMA_VERSION,
    AnchorGoldAdjudication,
    AnchorGoldDecision,
    apply_anchor_gold_labels,
    queue_row_sha256,
    read_anchor_gold_csv,
    write_anchor_gold_overlay,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
    read_anchor_pretraining_stores,
    write_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)


def test_csv_preserves_multiple_acceptable_complete_candidates(tmp_path: Path) -> None:
    queue = _queue_row()
    queue_path, csv_path = _write_queue_and_csv(
        tmp_path,
        queue,
        decision="SUCCESS_CONFIRMED",
        acceptable="NODE:1;ROAD:10|11",
        preferred="ROAD:10|11",
        note="both encodings are business-correct; Road is preferred",
    )

    rows = read_anchor_gold_csv(csv_path=csv_path, queue_path=queue_path)

    assert rows[0].acceptable_candidate_ids == ("NODE:1", "ROAD:10|11")
    assert rows[0].preferred_candidate_id == "ROAD:10|11"


@pytest.mark.parametrize(
    ("decision", "acceptable", "preferred", "note", "error"),
    [
        ("", "", "", "", "incomplete"),
        (
            "SUCCESS_CONFIRMED",
            "ROAD:not-frozen",
            "ROAD:not-frozen",
            "visual evidence",
            "outside the frozen candidate set",
        ),
        (
            "SUCCESS_CONFIRMED",
            "NODE:1",
            "ROAD:10|11",
            "visual evidence",
            "preferred candidate must belong",
        ),
        (
            "AMBIGUOUS",
            "NODE:1",
            "NODE:1",
            "two plausible objects",
            "must not select candidates",
        ),
        ("CANDIDATE_MISSING", "", "", "", "lacks an evidence note"),
    ],
)
def test_csv_rejects_invalid_gold_semantics(
    tmp_path: Path,
    decision: str,
    acceptable: str,
    preferred: str,
    note: str,
    error: str,
) -> None:
    queue_path, csv_path = _write_queue_and_csv(
        tmp_path,
        _queue_row(),
        decision=decision,
        acceptable=acceptable,
        preferred=preferred,
        note=note,
    )

    with pytest.raises(ValueError, match=error):
        read_anchor_gold_csv(csv_path=csv_path, queue_path=queue_path)


def test_csv_rejects_frozen_candidate_or_hash_change(tmp_path: Path) -> None:
    queue_path, csv_path = _write_queue_and_csv(
        tmp_path,
        _queue_row(),
        decision="AMBIGUOUS",
        acceptable="",
        preferred="",
        note="evidence is insufficient",
        immutable_override={"candidate_ids_json": '["NODE:tampered"]'},
    )

    with pytest.raises(ValueError, match="changed frozen field"):
        read_anchor_gold_csv(csv_path=csv_path, queue_path=queue_path)


def test_apply_gold_promotes_silver_and_preserves_multi_solution() -> None:
    source = _anchor()
    adjudication = AnchorGoldAdjudication(
        case_key=source.case_key,
        anchor_id=source.anchor_id,
        decision=AnchorGoldDecision.SUCCESS_CONFIRMED,
        acceptable_candidate_ids=("NODE:1", "ROAD:10|11"),
        preferred_candidate_id="ROAD:10|11",
        evidence_note="both are acceptable; Road preferred",
        affected_segment_ids=("segment",),
        queue_sample_id=source.sample_id,
        source_row_number=2,
    )

    rows, counts = apply_anchor_gold_labels([source], adjudications=[adjudication])

    result = rows[0]
    assert result.sample_weight == 1.0
    assert result.status_label == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
    assert result.candidate_acceptable_indices == (0, 1)
    assert result.preferred_candidate_index == 1
    assert counts["multi_solution"] == 1


def test_apply_gold_refuses_to_overwrite_existing_gold() -> None:
    source = _anchor(sample_weight=1.0)
    adjudication = AnchorGoldAdjudication(
        case_key=source.case_key,
        anchor_id=source.anchor_id,
        decision=AnchorGoldDecision.AMBIGUOUS,
        acceptable_candidate_ids=(),
        preferred_candidate_id="",
        evidence_note="evidence is ambiguous",
        affected_segment_ids=("segment",),
        queue_sample_id=source.sample_id,
        source_row_number=2,
    )

    with pytest.raises(ValueError, match="must not overwrite existing Gold"):
        apply_anchor_gold_labels([source], adjudications=[adjudication])


def test_write_gold_overlay_changes_only_labels(tmp_path: Path) -> None:
    queue_path, csv_path = _write_queue_and_csv(
        tmp_path,
        _queue_row(),
        decision="SUCCESS_CONFIRMED",
        acceptable="ROAD:10|11",
        preferred="ROAD:10|11",
        note="Road pair is the complete anchor",
    )
    source_store = write_anchor_pretraining_stores(
        [_anchor()],
        output_root=tmp_path / "source",
        run_id="anchor_store",
    )

    overlay = write_anchor_gold_overlay(
        anchor_store_root=source_store,
        queue_path=queue_path,
        adjudication_csv_path=csv_path,
        output_root=tmp_path / "output",
        run_id="gold_overlay",
        expected_adjudication_count=1,
    )

    output_store = overlay / "anchor_store"
    assert sha256_file(
        source_store / "inference_feature_store" / "anchor_features.jsonl"
    ) == sha256_file(
        output_store / "inference_feature_store" / "anchor_features.jsonl"
    )
    result = read_anchor_pretraining_stores(output_store)[0]
    assert result.sample_weight == 1.0
    assert result.preferred_candidate_index == 1
    summary = json.loads((overlay / "summary.json").read_text(encoding="utf-8"))
    assert summary["feature_store_byte_identical"] is True
    assert summary["gate_pass"] is True


def _queue_row() -> dict[str, object]:
    row: dict[str, object] = {
        "queue_schema_version": QUEUE_SCHEMA_VERSION,
        "priority": 1,
        "case_key": "T10:case",
        "fold": 2,
        "anchor_id": "anchor",
        "sample_id": "anchor:sample",
        "candidate_count": 2,
        "candidate_ids": ["NODE:1", "ROAD:10|11"],
        "impact_segment_count": 1,
        "impact_segment_ids": ["segment"],
    }
    row["queue_row_sha256"] = queue_row_sha256(row)
    return row


def _write_queue_and_csv(
    root: Path,
    queue: dict[str, object],
    *,
    decision: str,
    acceptable: str,
    preferred: str,
    note: str,
    immutable_override: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    queue_path = root / "queue.jsonl"
    queue_path.write_text(json.dumps(queue) + "\n", encoding="utf-8")
    row = {
        "priority": str(queue["priority"]),
        "case_key": str(queue["case_key"]),
        "fold": str(queue["fold"]),
        "anchor_id": str(queue["anchor_id"]),
        "sample_id": str(queue["sample_id"]),
        "candidate_count": str(queue["candidate_count"]),
        "candidate_ids_json": json.dumps(
            queue["candidate_ids"], separators=(",", ":")
        ),
        "impact_segment_count": str(queue["impact_segment_count"]),
        "impact_segment_ids": ";".join(queue["impact_segment_ids"]),
        "queue_row_sha256": str(queue["queue_row_sha256"]),
        "manual_decision": decision,
        "manual_acceptable_candidate_ids": acceptable,
        "manual_preferred_candidate_id": preferred,
        "manual_evidence_note": note,
    }
    row.update(immutable_override or {})
    csv_path = root / "gold.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    return queue_path, csv_path


def _anchor(*, sample_weight: float = 0.7) -> AnchorPretrainExample:
    return AnchorPretrainExample(
        sample_id="anchor:sample",
        case_key="T10:case",
        anchor_id="anchor",
        fold=2,
        object_features=(0.0,) * 64,
        candidate_ids=("NODE:1", "ROAD:10|11"),
        candidate_features=((0.0,) * 64, (0.0,) * 64),
        status_label=ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS],
        candidate_acceptable_indices=(0,),
        preferred_candidate_index=0,
        candidate_supervised=True,
        sample_weight=sample_weight,
        input_hashes=(("input", "hash"),),
        label_reason="t05:silver:object_reachable",
        dependency_anchor_ids=("anchor",),
        status_supervised=True,
        gate_label=1,
        gate_supervised=True,
    )
