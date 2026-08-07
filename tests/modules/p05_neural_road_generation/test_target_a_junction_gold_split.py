from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_gold_split import (
    build_junction_gold_split,
)


def test_split_groups_versions_and_excludes_conflicting_truth(tmp_path: Path) -> None:
    labels = []
    for case_index in range(10):
        case_id = str(100 + case_index)
        labels.append(_label(case_id, 0, "a" * 63 + str(case_index), "sig-a"))
    labels.append(_label("100", 1, "b" * 64, "sig-a"))
    labels.extend(
        (
            _label("999", 2, "c" * 64, "sig-c"),
            _label("999", 3, "d" * 64, "sig-d"),
        )
    )
    labels_path = tmp_path / "labels.jsonl"
    _write_rows(labels_path, labels)
    reviews_path = tmp_path / "reviews.jsonl"
    _write_rows(
        reviews_path,
        [
            {
                "case_id": "100",
                "status": "SAME_TERMINAL_BUSINESS",
            },
            {
                "case_id": "999",
                "status": "TERMINAL_BUSINESS_CONFLICT",
            },
        ],
    )

    groups, samples, exclusions, summary = build_junction_gold_split(
        labels_path=labels_path,
        version_reviews_path=reviews_path,
        seed=7,
    )

    assert len(groups) == 10
    assert len(samples) == 11
    assert summary["split_group_counts"] == {
        "test": 2,
        "train": 7,
        "validation": 1,
    }
    case_100 = [row for row in samples if row.case_id == "100"]
    assert len({row.split for row in case_100}) == 1
    assert sum(row.effective_label_weight for row in case_100) == 1.0
    assert exclusions[0].case_id == "999"
    assert summary["case_group_leakage_count"] == 0
    assert summary["train_missing_stratum_count"] == 0


def test_split_is_deterministic(tmp_path: Path) -> None:
    labels_path = tmp_path / "labels.jsonl"
    _write_rows(
        labels_path,
        [_label(str(index), index, f"{index:064x}", "sig") for index in range(30)],
    )
    reviews_path = tmp_path / "reviews.jsonl"
    reviews_path.write_text("", encoding="utf-8")

    first = build_junction_gold_split(
        labels_path=labels_path,
        version_reviews_path=reviews_path,
        seed=11,
    )
    second = build_junction_gold_split(
        labels_path=labels_path,
        version_reviews_path=reviews_path,
        seed=11,
    )

    assert first == second


def test_every_observed_stratum_has_training_example(tmp_path: Path) -> None:
    common = [_label(str(index), index, f"{index:064x}", "sig") for index in range(20)]
    rare = _label("rare", 100, "f" * 64, "rare-sig")
    rare["surface_state"] = "runtime_failed"
    rare["anchor_business_state"] = "QUALITY_ISSUE"
    labels_path = tmp_path / "labels.jsonl"
    _write_rows(labels_path, [*common, rare])
    reviews_path = tmp_path / "reviews.jsonl"
    reviews_path.write_text("", encoding="utf-8")

    groups, _, _, summary = build_junction_gold_split(
        labels_path=labels_path,
        version_reviews_path=reviews_path,
        seed=13,
    )

    assert next(row for row in groups if row.case_id == "rare").split == "train"
    assert summary["train_missing_stratum_count"] == 0


def _label(
    case_id: str,
    source_index: int,
    fingerprint: str,
    signature: str,
) -> dict[str, object]:
    return {
        "sample_id": f"sample:{case_id}:{source_index}",
        "sample_group_id": f"junction:{case_id}",
        "case_id": case_id,
        "source_index": source_index,
        "case_root": f"/data/{case_id}/{source_index}",
        "input_fingerprint": fingerprint,
        "family": "T03",
        "source_scope": "POC_Data",
        "label_weight": 1.0,
        "label_status": "READY",
        "route_class": "T03",
        "surface_state": "accepted",
        "anchor_business_state": "SUCCESS",
        "t07_step2_is_anchor": "no",
        "terminal_business_signature": signature,
    }


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
