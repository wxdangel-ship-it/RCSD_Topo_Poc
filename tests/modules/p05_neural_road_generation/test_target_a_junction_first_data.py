from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_data import (
    STAGE1_OBJECT_INDICES,
    TASK_INDEX,
    collate_junction_first,
    read_junction_first_examples,
)


def test_read_junction_first_keeps_stage1_view_and_labels_separate(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    feature_root = store / "inference_feature_store"
    label_root = store / "training_label_store"
    feature_root.mkdir(parents=True)
    label_root.mkdir(parents=True)
    feature = {
        "sample_id": "anchor:1",
        "case_key": "T10:case",
        "anchor_id": "J1",
        "fold": 1,
        "object_features": [float(index) for index in range(64)],
        "candidate_ids": ["NODE:N1"],
        "candidate_features": [[0.0] * 64],
        "structural_member_ids": ["NODE:N1"],
        "member_local_features": [[0.0] * 12],
    }
    label = {
        "sample_id": "anchor:1",
        "sample_weight": 0.7,
        "status_label": 0,
        "status_supervised": True,
        "candidate_acceptable_indices": [0],
        "candidate_supervised": True,
        "member_acceptable_sets": [[0]],
        "member_supervised": True,
    }
    audit = {
        "sample_id": "anchor:1",
        "t07_step1_status": "yes",
        "t07_step2_status": "no",
        "t07_relation_state": "no_existing_rcsdintersection",
        "t03_available": True,
        "t03_step7_state": "accepted",
        "t03_association_class": "A",
        "t03_relation_state": "success_required_rcsd_junction",
        "t04_available": False,
        "t05_surface_sources": "T03",
        "t05_junctionization_action": "direct_relation",
        "t05_graph_status": "base_node_graph_incident",
        "t05_relation_status": "0",
    }
    _write_jsonl(feature_root / "anchor_features.jsonl", [feature])
    _write_jsonl(label_root / "anchor_labels.jsonl", [label])
    audit_path = tmp_path / "audit.jsonl"
    _write_jsonl(audit_path, [audit])

    examples = read_junction_first_examples(
        anchor_store_root=store,
        junction_audit_path=audit_path,
    )
    assert len(examples) == 1
    row = examples[0]
    assert row.stage1_features == tuple(float(index) for index in STAGE1_OBJECT_INDICES)
    assert row.task_labels["route"] == TASK_INDEX["route"]["T03"]
    assert row.task_masks["t04_relation"] is False
    batch = collate_junction_first(examples)
    assert batch.stage1_features.shape == (1, len(STAGE1_OBJECT_INDICES))
    assert batch.candidate_acceptable.tolist() == [[True]]
    assert batch.member_acceptable_sets.tolist() == [[[True]]]


def test_single_point_family_is_label_only_route_supervision(tmp_path: Path) -> None:
    store = tmp_path / "store"
    feature_root = store / "inference_feature_store"
    label_root = store / "training_label_store"
    feature_root.mkdir(parents=True)
    label_root.mkdir(parents=True)
    _write_jsonl(
        feature_root / "anchor_features.jsonl",
        [
            {
                "sample_id": "anchor:2",
                "case_key": "T04_Error:case",
                "anchor_id": "J2",
                "fold": 0,
                "object_features": [0.0] * 64,
                "candidate_ids": ["NODE:N2"],
                "candidate_features": [[0.0] * 64],
                "structural_member_ids": [],
                "member_local_features": [],
            }
        ],
    )
    _write_jsonl(
        label_root / "anchor_labels.jsonl",
        [
            {
                "sample_id": "anchor:2",
                "sample_weight": 1.0,
                "status_label": 3,
                "status_supervised": True,
                "candidate_acceptable_indices": [],
                "candidate_supervised": False,
                "member_acceptable_sets": [],
                "member_supervised": False,
            }
        ],
    )
    audit_path = tmp_path / "audit.jsonl"
    _write_jsonl(audit_path, [{"sample_id": "anchor:2"}])
    row = read_junction_first_examples(
        anchor_store_root=store,
        junction_audit_path=audit_path,
    )[0]
    assert row.task_masks["t07_step1"] is False
    assert row.task_labels["route"] == TASK_INDEX["route"]["T04"]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
