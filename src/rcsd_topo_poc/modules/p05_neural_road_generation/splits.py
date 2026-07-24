from __future__ import annotations

import hashlib
from collections import defaultdict

from rcsd_topo_poc.modules.p05_neural_road_generation.models import SplitAssignment, TrainingSample


def fold_for_group(sample_group_id: str, split_seed: str, *, fold_count: int = 5) -> int:
    if fold_count < 3:
        raise ValueError("fold_count must be at least 3")
    digest = hashlib.sha256(f"{split_seed}|{sample_group_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % fold_count


def split_name(fold: int) -> str:
    if fold == 0:
        return "test"
    if fold == 1:
        return "validation"
    return "train"


def build_grouped_split(samples: list[TrainingSample], split_seed: str) -> list[SplitAssignment]:
    assignments = [
        SplitAssignment(
            sample_id=sample.sample_id,
            sample_group_id=sample.sample_group_id,
            fold=(fold := fold_for_group(sample.sample_group_id, split_seed)),
            split=split_name(fold),
        )
        for sample in samples
    ]
    assignments.sort(key=lambda item: (item.fold, item.sample_group_id, item.sample_id))
    assert_no_group_leakage(assignments)
    return assignments


def assert_no_group_leakage(assignments: list[SplitAssignment]) -> None:
    group_splits: dict[str, set[str]] = defaultdict(set)
    for assignment in assignments:
        group_splits[assignment.sample_group_id].add(assignment.split)
    leaked = {group: splits for group, splits in group_splits.items() if len(splits) != 1}
    if leaked:
        raise AssertionError(f"sample groups cross split boundaries: {leaked}")


__all__ = ["assert_no_group_leakage", "build_grouped_split", "fold_for_group", "split_name"]
