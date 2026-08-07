from __future__ import annotations

import gzip
import json
from pathlib import Path

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    TASK_INDEX,
    collate_junction_joint,
    read_junction_joint_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_ROLE_INDEX,
    GEOMETRY_TOKEN_DIM,
    MEMBER_FEATURE_DIM,
    OBJECT_FEATURE_DIM,
)


def test_joint_store_reader_separates_drivezone_and_maps_raw_object_gold(
    tmp_path: Path,
) -> None:
    root = _write_store(tmp_path)
    examples = read_junction_joint_examples(root)
    assert len(examples) == 1
    row = examples[0]
    assert row.supervision_source == "STRONG_GOLD"
    assert row.supervision_group == "GOLD:"
    assert row.object_acceptable_sets == ((2,),)
    assert row.object_supervised
    assert row.task_labels["final_state"] == TASK_INDEX["final_state"]["SUCCESS"]

    batch = collate_junction_joint(examples)
    assert batch.step1_token_mask.sum().item() == 2
    assert batch.step2_token_mask.sum().item() == 1
    assert batch.drivezone_grid.sum().item() == 2
    drivezone = GEOMETRY_ROLE_INDEX["DRIVEZONE"]
    assert torch.all(batch.step1_tokens[0, :2, drivezone] == 1.0)
    assert batch.object_acceptable_sets[0, 0, 2]
    assert batch.selectable_object_mask[0, 2]
    assert batch.object_supervision_mask[0, 2]
    assert batch.object_role_task_mask[0].tolist() == [True, True]
    assert batch.main_object_target[0, 2]
    assert batch.main_object_task_mask[0]
    assert batch.geometry_object_anchor_projection_fraction.shape == (1, 4)
    assert batch.geometry_object_length_m[0, 2] == 0.0
    assert batch.geometry_object_member_index[0].tolist() == [-1, -1, 0, -1]
    assert batch.swsd_arm_mask[0].tolist() == [True]
    assert batch.member_arm_mask[0, 0].tolist() == [True]
    assert not batch.selectable_object_mask[0, 0]


def test_joint_reader_rejects_split_mismatch(tmp_path: Path) -> None:
    root = _write_store(tmp_path)
    lineage = root / "lineage_store/junction_lineage.jsonl"
    row = json.loads(lineage.read_text(encoding="utf-8"))
    row["split"] = "validation"
    lineage.write_text(json.dumps(row) + "\n", encoding="utf-8")
    try:
        read_junction_joint_examples(root)
    except ValueError as error:
        assert "split differs" in str(error)
    else:
        raise AssertionError("split mismatch must fail")


def test_joint_reader_accepts_case_gzip_shards(tmp_path: Path) -> None:
    root = _write_store(tmp_path)
    for path in (
        root / "inference_feature_store/junction_features.jsonl",
        root / "training_label_store/junction_labels.jsonl",
        root / "lineage_store/junction_lineage.jsonl",
    ):
        target = path.with_name("case-a.jsonl.gz")
        with gzip.open(target, "wt", encoding="utf-8") as stream:
            stream.write(path.read_text(encoding="utf-8"))
        path.unlink()

    examples = read_junction_joint_examples(root)
    assert [row.sample_id for row in examples] == ["sample-1"]


def test_joint_reader_preserves_partial_road_only_object_supervision(
    tmp_path: Path,
) -> None:
    root = _write_store(tmp_path)
    feature_path = root / "inference_feature_store/junction_features.jsonl"
    feature = json.loads(feature_path.read_text(encoding="utf-8"))
    feature["geometry_token_features"].append(_token("RCSD_ROAD"))
    feature["geometry_object_spans"].append(
        _span("ROAD:901", GEOMETRY_ROLE_INDEX["RCSD_ROAD"], 5, 6)
    )
    _jsonl(feature_path, feature)
    label_path = root / "training_label_store/junction_labels.jsonl"
    label = json.loads(label_path.read_text(encoding="utf-8"))
    label["raw_object_target_object_ids"] = ["ROAD:901"]
    label["raw_object_target_object_sets"] = [["ROAD:901"]]
    label["raw_object_supervision_roles"] = ["ROAD"]
    _jsonl(label_path, label)

    batch = collate_junction_joint(read_junction_joint_examples(root))
    assert batch.selectable_object_mask[0, 2]
    assert not batch.object_supervision_mask[0, 2]
    assert batch.object_supervision_mask[0, 4]
    assert batch.object_role_task_mask[0].tolist() == [False, True]
    assert batch.object_acceptable_sets[0, 0, 4]


def test_joint_reader_preserves_raw_member_graph_and_object_mapping(
    tmp_path: Path,
) -> None:
    root = _write_store(tmp_path)
    feature_path = root / "inference_feature_store/junction_features.jsonl"
    feature = json.loads(feature_path.read_text(encoding="utf-8"))
    feature["structural_member_ids"] = ["NODE:900", "ROAD:901", "ROAD:902"]
    feature["member_local_features"] = [
        [0.0] * MEMBER_FEATURE_DIM,
        [0.1] * MEMBER_FEATURE_DIM,
        [0.2] * MEMBER_FEATURE_DIM,
    ]
    feature["member_arm_features"] = [
        [[1.0, 0.0, 0.5, 1.0, 0.0, 0.0, 0.0]],
        [[0.0, 1.0, 0.5, 0.0, 1.0, 0.0, 0.0]],
        [[0.0, -1.0, 0.5, 0.0, 0.0, 1.0, 0.0]],
    ]
    relation = [1.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.875]
    feature["member_relation_edges"] = [[1, 2, relation], [2, 1, relation]]
    incidence = [1.0, 0.0, 1.0, 0.0]
    feature["member_incidence_edges"] = [[0, 1, incidence]]
    feature["geometry_token_features"].extend(
        [_token("RCSD_ROAD"), _token("RCSD_ROAD")]
    )
    feature["geometry_object_spans"].extend(
        [
            _span("ROAD:901", GEOMETRY_ROLE_INDEX["RCSD_ROAD"], 5, 6),
            _span("ROAD:902", GEOMETRY_ROLE_INDEX["RCSD_ROAD"], 6, 7),
        ]
    )
    _jsonl(feature_path, feature)

    batch = collate_junction_joint(read_junction_joint_examples(root))
    assert batch.member_relation_mask[0, 1, 2]
    assert batch.member_relation_mask[0, 2, 1]
    assert torch.allclose(batch.member_relation_features[0, 1, 2], torch.tensor(relation))
    assert batch.member_incidence_mask[0, 0, 1]
    assert torch.allclose(
        batch.member_incidence_features[0, 0, 1], torch.tensor(incidence)
    )
    assert batch.geometry_object_member_index[0].tolist() == [-1, -1, 0, -1, 1, 2]


def _write_store(tmp_path: Path) -> Path:
    root = tmp_path / "joint"
    (root / "inference_feature_store").mkdir(parents=True)
    (root / "training_label_store").mkdir()
    (root / "lineage_store").mkdir()
    roles = GEOMETRY_ROLE_INDEX
    tokens = [
        _token("SWSD_NODE"),
        _token("DRIVEZONE"),
        _token("DRIVEZONE"),
        _token("RCSD_NODE"),
        _token("RCSD_INTERSECTION"),
    ]
    feature = {
        "sample_id": "sample-1",
        "anchor_id": "100",
        "input_fingerprint": "abc",
        "object_features": [0.0] * OBJECT_FEATURE_DIM,
        "candidate_ids": ["NODE:900"],
        "candidate_features": [[0.0] * OBJECT_FEATURE_DIM],
        "structural_member_ids": ["NODE:900"],
        "swsd_arm_features": [[1.0, 0.0, 0.5, 1.0, 0.0, 0.0, 0.0]],
        "member_arm_features": [
            [[1.0, 0.0, 0.5, 1.0, 0.0, 0.0, 0.0]]
        ],
        "member_local_features": [[0.0] * MEMBER_FEATURE_DIM],
        "member_relation_edges": [],
        "geometry_token_features": tokens,
        "geometry_object_spans": [
            _span("SWSD_NODE:100", roles["SWSD_NODE"], 0, 1),
            _span("DRIVEZONE:1", roles["DRIVEZONE"], 1, 3),
            _span("NODE:900", roles["RCSD_NODE"], 3, 4),
            _span("RCSD_INTERSECTION:2", roles["RCSD_INTERSECTION"], 4, 5),
        ],
        "drivezone_grid_indices": [0, 129],
    }
    label = {
        "sample_id": "sample-1",
        "split": "train",
        "sample_weight": 1.0,
        "task_labels": {
            "t07_step1": "yes",
            "t07_step2": "yes",
            "surface_mode": "VIRTUAL_SURFACE",
            "surface_state": "accepted",
            "relation_state": "success_offset_fact_with_rcsd_junction",
            "junctionization_action": "direct_relation",
            "final_state": "SUCCESS",
        },
        "task_masks": {
            "t07_step1": True,
            "t07_step2": True,
            "surface_mode": True,
            "surface_state": True,
            "relation_state": True,
            "junctionization_action": True,
            "final_state": True,
        },
        "candidate_acceptable_indices": [0],
        "candidate_supervised": True,
        "member_acceptable_sets": [[0]],
        "member_supervised": True,
        "raw_object_target_kind": "NODE",
        "raw_object_target_ids": ["900"],
        "raw_object_target_object_ids": ["NODE:900"],
        "break_position_targets": [],
        "selected_main_target": {"kind": "RAW_NODE", "object_id": "NODE:900"},
        "surface_grid_indices": [0, 129],
        "surface_grid_supervised": True,
        "junction_node_point_targets": [
            {"dx_m": 25.6, "dy_m": -12.8, "is_selected_main": True}
        ],
        "topology_geometry_supervised": True,
    }
    lineage = {"sample_id": "sample-1", "split": "train"}
    _jsonl(root / "inference_feature_store/junction_features.jsonl", feature)
    _jsonl(root / "training_label_store/junction_labels.jsonl", label)
    _jsonl(root / "lineage_store/junction_lineage.jsonl", lineage)
    return root


def _token(role: str) -> list[float]:
    row = [0.0] * GEOMETRY_TOKEN_DIM
    row[GEOMETRY_ROLE_INDEX[role]] = 1.0
    row[15] = 1.0
    return row


def _span(object_id: str, role: int, start: int, end: int) -> dict[str, object]:
    return {
        "object_id": object_id,
        "role_index": role,
        "token_start": start,
        "token_end": end,
        "geometry_valid": True,
    }


def _jsonl(path: Path, row: dict[str, object]) -> None:
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
