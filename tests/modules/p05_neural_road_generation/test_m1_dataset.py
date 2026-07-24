from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_dataset import (
    _CaseGraph,
    _Label,
    _Road,
    _apply_entity_guard,
    _operation_labels,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_models import M1DatasetConfig


def _road(road_id: str, x0: float, x1: float, *, parent: str = "") -> _Road:
    properties = {"id": road_id, "snodeid": f"n{x0}", "enodeid": f"n{x1}", "direction": 2, "source": 1}
    if parent:
        properties["t06_split_original_road_id"] = parent
    return _Road(road_id, "t05_rcsdroad_out", properties, LineString([(x0, 0.0), (x1, 0.0)]), "EPSG:3857")


def _empty_label() -> _Label:
    return _Label("DROP", [], [], [], [], True, np.zeros((3, 4, 2), dtype=np.float32), np.zeros(3, dtype=np.float32), "context", 0.3)


def _graph(sample_id: str, split: str, roads: list[_Road], edges: set[tuple[int, int]]) -> _CaseGraph:
    fold = {"test": 0, "validation": 1, "train": 2}[split]
    return _CaseGraph(sample_id, "T10", sample_id, "t10_case", split, fold, "EPSG:3857", roads, [_empty_label() for _ in roads], edges, [], 0, 0, [], True)


def test_m1_dataset_config_rejects_unsafe_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="polyline_points"):
        M1DatasetConfig(tmp_path, tmp_path, "run", polyline_points=3)
    with pytest.raises(ValueError, match="entity_guard_hops"):
        M1DatasetConfig(tmp_path, tmp_path, "run", entity_guard_hops=0)


def test_operation_labels_cover_keep_drop_split_and_uncovered() -> None:
    candidates = [_road("keep", 0, 10), _road("split", 10, 20), _road("drop", 20, 30)]
    truth = {
        "keep": _road("keep", 0, 10),
        "split_a": _road("split_a", 10, 15, parent="split"),
        "split_b": _road("split_b", 15, 20, parent="split"),
        "free": _road("free", 30, 40),
    }
    labels, uncovered, accounted, anomalies = _operation_labels(
        candidates,
        truth,
        target_truth_ids={"split_a", "split_b"},
        target_weight=0.7,
        context_weight=0.3,
        polyline_points=4,
    )
    assert [label.operation for label in labels] == ["KEEP", "SPLIT_2", "DROP"]
    assert labels[1].label_weight == 0.7
    assert labels[0].label_weight == 0.3
    assert labels[1].split_fraction_valid
    assert labels[1].split_fractions == pytest.approx([0.5])
    assert uncovered == ["free"]
    assert accounted == 3
    assert anomalies == []


def test_case_scope_weights_negative_candidates_as_checked_truth() -> None:
    candidates = [_road("keep", 0, 10), _road("drop", 10, 20)]
    labels, _, _, _ = _operation_labels(
        candidates,
        {"keep": _road("keep", 0, 10)},
        target_truth_ids={"keep"},
        target_weight=0.7,
        context_weight=0.3,
        polyline_points=4,
        all_candidates_target=True,
    )
    assert [label.label_weight for label in labels] == [0.7, 0.7]


def test_entity_guard_prefers_test_and_removes_one_hop_neighbor() -> None:
    train = _graph("train", "train", [_road("shared", 0, 1), _road("neighbor", 1, 2), _road("far", 10, 11)], {(0, 1), (1, 0)})
    validation = _graph("validation", "validation", [_road("validation_only", 3, 4)], set())
    test = _graph("test", "test", [_road("shared", 0, 1)], set())
    audit = _apply_entity_guard([train, validation, test], 1)
    assert train.direct_guarded_out == {0}
    assert train.guarded_out == {0, 1}
    assert validation.guarded_out == set()
    assert test.guarded_out == set()
    assert {row["decision"] for row in audit} == {"removed_direct_overlap", "removed_guard_neighbor"}
