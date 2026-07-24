from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_dataset import (
    load_p3_group_examples,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_load_p3_group_examples_joins_by_audit_identity(tmp_path: Path) -> None:
    features = tmp_path / "features.jsonl"
    contexts = tmp_path / "contexts.jsonl"
    feature_rows = [
        {
            "candidate_id": "candidate-a",
            "case_key": "T10:case-a",
            "fold": 2,
            "domain": "JSG",
            "object_type": "SEGMENT",
            "group_id": "group-a",
            "feature_tokens": ["payload:state=REVIEW"],
            "feature_signature": "feature-a",
            "truth_equivalent": False,
            "sample_weight": 0.3,
        },
        {
            "candidate_id": "candidate-b",
            "case_key": "T10:case-a",
            "fold": 2,
            "domain": "JSG",
            "object_type": "SEGMENT",
            "group_id": "group-a",
            "feature_tokens": ["payload:state=PUBLISHABLE"],
            "feature_signature": "feature-b",
            "truth_equivalent": True,
            "sample_weight": 0.3,
        },
    ]
    context_rows = [
        {
            "domain": "JSG",
            "case_key": "T10:case-a",
            "group_id": "group-a",
            "fold": 2,
            "context_tokens": ["ctx:self_type=SEGMENT"],
            "context_signature": "context-a",
        }
    ]
    _write_jsonl(features, feature_rows)
    _write_jsonl(contexts, context_rows)

    groups = load_p3_group_examples(features, contexts)

    assert len(groups) == 1
    assert groups[0].candidate_ids == ("candidate-a", "candidate-b")
    assert groups[0].truth_index == 1
    assert groups[0].truth_is_review is False
    assert groups[0].context_tokens == ("ctx:self_type=SEGMENT",)
