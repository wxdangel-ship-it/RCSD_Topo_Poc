from __future__ import annotations

from pathlib import Path

import numpy as np

from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_training import _entity_guard_masks


def _graph(path: Path, road_ids: list[str], edges: list[tuple[int, int]]) -> None:
    edge_index = np.asarray(edges, dtype=np.int64).T if edges else np.empty((2, 0), dtype=np.int64)
    np.savez(path, road_ids=np.asarray(road_ids), edge_index=edge_index)


def test_oof_entity_guard_removes_direct_ids_and_one_hop_neighbors(tmp_path: Path) -> None:
    train_path = tmp_path / "train.npz"
    held_out_path = tmp_path / "held_out.npz"
    _graph(train_path, ["shared", "neighbor", "safe"], [(0, 1), (1, 0)])
    _graph(held_out_path, ["shared", "held"], [])
    index = [
        {"sample_id": "train", "fold": 1, "graph_path": str(train_path)},
        {"sample_id": "held", "fold": 0, "graph_path": str(held_out_path)},
    ]

    masks, audit = _entity_guard_masks(index, held_out_fold=0, hops=1)

    assert masks["train"].tolist() == [False, False, True]
    assert audit[0]["direct_overlap_removed"] == 1
    assert audit[0]["neighbor_removed"] == 1
    assert audit[0]["retained_count"] == 1
