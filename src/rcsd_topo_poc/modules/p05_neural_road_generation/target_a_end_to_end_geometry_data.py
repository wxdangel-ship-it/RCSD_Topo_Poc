from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _read_roads,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_candidates import (
    _attachment_proposals,
    _splice_proposal,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_teacher import (
    GeometryRoad,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_data import (
    EndToEndRecallExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


_LOCAL_CANDIDATE_FEATURE_DIM = 50
_GEOMETRY_FEATURE_DIM = 26
_PROPOSAL_TYPE_COUNT = 3
END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM = (
    _PROPOSAL_TYPE_COUNT
    + _LOCAL_CANDIDATE_FEATURE_DIM
    + ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM
    + _GEOMETRY_FEATURE_DIM
)
_PROPOSAL_TYPE_INDEX = {
    "SOURCE_ATTACHMENT": 0,
    "TARGET_ATTACHMENT": 1,
    "MIDDLE_SPLICE": 2,
}
_RCSD_ORDINARY_DECISIONS = {
    "USE_RCSD",
    "T06_MAIN_RCSD_ATTACHED_SWSD",
}


@dataclass(frozen=True)
class EndToEndGeometryExample:
    recall: EndToEndRecallExample
    proposals: tuple[Mapping[str, Any], ...]
    acceptable_geometry_variants: tuple[Mapping[str, Any], ...]
    geometry_label_task_mask: bool
    geometry_task_mask: bool
    geometry_label_weight: float

    def __post_init__(self) -> None:
        advance = self.recall.advance_right
        if advance is None:
            raise ValueError("geometry example requires AdvanceRight")
        proposal_ids = [str(row["proposal_id"]) for row in self.proposals]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("geometry proposal ids repeat")
        reachable = [
            variant
            for variant in self.acceptable_geometry_variants
            if bool(variant.get("reachable"))
        ]
        if self.geometry_task_mask and not reachable:
            raise ValueError("supervised geometry has no reachable variant")

    @property
    def case_key(self) -> str:
        advance = self.recall.advance_right
        if advance is None:
            raise RuntimeError("geometry example lacks AdvanceRight")
        return advance.case_key

    @property
    def segment_id(self) -> str:
        advance = self.recall.advance_right
        if advance is None:
            raise RuntimeError("geometry example lacks AdvanceRight")
        return advance.segment_id

    @property
    def fold(self) -> int:
        advance = self.recall.advance_right
        if advance is None:
            raise RuntimeError("geometry example lacks AdvanceRight")
        return advance.fold


@dataclass(frozen=True)
class EndToEndGeometryBatch:
    values: torch.Tensor
    mask: torch.Tensor


def build_union_geometry_examples(
    recall_examples: Sequence[EndToEndRecallExample],
    advance_right_rows: Sequence[Mapping[str, Any]],
    *,
    geometry_candidate_root: Path,
) -> tuple[EndToEndGeometryExample, ...]:
    """Build one truth-free geometry union for every recall-first subgraph."""
    root = normalize_runtime_path(geometry_candidate_root).resolve(strict=True)
    road_stores, rcsd_ids = _read_inference_roads(root)
    labels = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in _read_jsonl(
            root / "advance_right_geometry_training_labels.jsonl"
        )
    }
    advance_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in advance_right_rows
    }
    result = []
    for recall in recall_examples:
        advance = recall.advance_right
        if advance is None:
            continue
        key = (advance.case_key, advance.segment_id)
        source = advance_by_key.get(key)
        label = labels.get(key)
        if source is None or label is None:
            raise ValueError(f"geometry input is missing: {key}")
        proposals = _union_proposals(
            recall,
            source,
            roads=road_stores[advance.case_key],
            rcsd_ids=rcsd_ids[advance.case_key],
        )
        variants = tuple(
            dict(row) for row in label["acceptable_geometry_variants"]
        )
        reachable_ids = {str(row["proposal_id"]) for row in proposals}
        union_reachable = tuple(
            {
                **row,
                "reachable": bool(
                    row.get("reachable")
                    and set(str(value) for value in row["proposal_ids"])
                    <= reachable_ids
                ),
            }
            for row in variants
        )
        label_requires_action = bool(
            label["geometry_task_mask"]
            and any(
                row.get("reachable") and row.get("proposal_ids")
                for row in variants
            )
        )
        task_mask = bool(
            label_requires_action
            and any(
                row["reachable"] and row["proposal_ids"]
                for row in union_reachable
            )
        )
        result.append(
            EndToEndGeometryExample(
                recall=recall,
                proposals=proposals,
                acceptable_geometry_variants=union_reachable,
                geometry_label_task_mask=label_requires_action,
                geometry_task_mask=task_mask,
                geometry_label_weight=(
                    float(label["geometry_label_weight"])
                    if task_mask
                    else 0.0
                ),
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda row: (row.fold, row.case_key, row.segment_id),
        )
    )


def collate_end_to_end_geometry_batch(
    examples: Sequence[EndToEndGeometryExample],
) -> EndToEndGeometryBatch:
    proposal_count = max(1, max(len(row.proposals) for row in examples))
    values = torch.zeros(
        (
            len(examples),
            proposal_count,
            END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM,
        ),
        dtype=torch.float32,
    )
    mask = torch.zeros(
        (len(examples), proposal_count),
        dtype=torch.bool,
    )
    for index, example in enumerate(examples):
        if not example.proposals:
            continue
        encoded = torch.tensor(
            [_proposal_features(row) for row in example.proposals],
            dtype=torch.float32,
        )
        values[index, : encoded.shape[0]] = encoded
        mask[index, : encoded.shape[0]] = True
    return EndToEndGeometryBatch(values=values, mask=mask)


def geometry_candidate_metrics(
    examples: Sequence[EndToEndGeometryExample],
) -> dict[str, Any]:
    supervised = [row for row in examples if row.geometry_task_mask]
    original_supervised = [
        row for row in examples if row.geometry_label_task_mask
    ]
    counts: dict[str, int] = defaultdict(int)
    for example in examples:
        for proposal in example.proposals:
            counts[str(proposal["proposal_type"])] += 1
    return {
        "example_count": len(examples),
        "proposal_count": sum(len(row.proposals) for row in examples),
        "max_proposal_count": max(
            (len(row.proposals) for row in examples),
            default=0,
        ),
        "proposal_counts": dict(sorted(counts.items())),
        "supervised_count": len(supervised),
        "reachable_supervised_count": len(original_supervised),
        "supervised_recall": (
            len(supervised) / len(original_supervised)
            if original_supervised
            else 0.0
        ),
        "feature_dim": END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM,
        "terminal_input_count": 0,
        "feature_uses_truth": False,
    }


def geometry_candidate_gap_rows(
    examples: Sequence[EndToEndGeometryExample],
) -> list[dict[str, Any]]:
    result = []
    for example in examples:
        if not example.geometry_label_task_mask or example.geometry_task_mask:
            continue
        available = {
            str(row["proposal_id"]): row for row in example.proposals
        }
        missing_ids = sorted(
            {
                str(proposal_id)
                for variant in example.acceptable_geometry_variants
                for proposal_id in variant["proposal_ids"]
                if str(proposal_id) not in available
            }
        )
        result.append(
            {
                "case_key": example.case_key,
                "segment_id": example.segment_id,
                "fold": example.fold,
                "truth_plan_type": (
                    example.recall.advance_right.truth_plan_type
                    if example.recall.advance_right is not None
                    else ""
                ),
                "proposal_count": len(example.proposals),
                "missing_proposal_ids": missing_ids,
                "available_proposal_types": sorted(
                    {
                        str(row["proposal_type"])
                        for row in example.proposals
                    }
                ),
            }
        )
    return result


def _union_proposals(
    example: EndToEndRecallExample,
    source: Mapping[str, Any],
    *,
    roads: Mapping[str, GeometryRoad],
    rcsd_ids: set[str],
) -> tuple[Mapping[str, Any], ...]:
    advance = example.advance_right
    if advance is None:
        return ()
    base_feature = source.get("base_feature")
    if not isinstance(base_feature, Mapping):
        raise ValueError("geometry source lacks base feature")
    candidate_rows = list(base_feature.get("candidate_rows") or ())
    candidate_features = {
        str(row["candidate_road_id"]): tuple(
            float(value) for value in row["local_feature_values"]
        )
        for row in candidate_rows
    }
    if any(
        len(values) != _LOCAL_CANDIDATE_FEATURE_DIM
        for values in candidate_features.values()
    ):
        raise ValueError("AdvanceRight local geometry feature differs")
    ordinary = {
        row.segment_id: row
        for row in example.dependency_subgraph.ordinary_segments
    }
    by_id: dict[str, Mapping[str, Any]] = {}
    for side, segment_id in (
        ("source", advance.source_segment_id),
        ("target", advance.target_segment_id),
    ):
        target_members = _union_rcsd_members(
            ordinary[segment_id],
            rcsd_ids=rcsd_ids,
        )
        target_members.update(
            _union_side_rcsd_candidates(
                base_feature,
                side=side,
                rcsd_ids=rcsd_ids,
            )
        )
        for candidate_id, features in candidate_features.items():
            candidate = roads[candidate_id]
            for endpoint_index in (0, 1):
                for target_id, target_features in target_members.items():
                    for proposal in _attachment_proposals(
                        case_key=advance.case_key,
                        object_id=advance.segment_id,
                        side=side,
                        candidate=candidate,
                        endpoint_index=endpoint_index,
                        target=roads[target_id],
                        candidate_feature_values=features,
                        target_member_feature_values=target_features,
                    ):
                        by_id[str(proposal["proposal_id"])] = proposal
    for candidate_id, features in candidate_features.items():
        for swsd_id in base_feature.get("fixed_swsd_road_ids") or ():
            proposal = _splice_proposal(
                case_key=advance.case_key,
                object_id=advance.segment_id,
                candidate=roads[candidate_id],
                swsd=roads[str(swsd_id)],
                candidate_feature_values=features,
            )
            by_id[str(proposal["proposal_id"])] = proposal
    return tuple(
        sorted(
            by_id.values(),
            key=lambda row: (
                str(row["proposal_type"]),
                str(row["proposal_id"]),
            ),
        )
    )


def _union_rcsd_members(
    ordinary: Any,
    *,
    rcsd_ids: set[str],
) -> dict[str, tuple[float, ...]]:
    features: dict[str, list[tuple[float, ...]]] = defaultdict(list)
    for decision, member_ids, member_features in zip(
        ordinary.candidate_decisions,
        ordinary.candidate_member_ids,
        ordinary.candidate_member_features,
        strict=True,
    ):
        if str(decision) not in _RCSD_ORDINARY_DECISIONS:
            continue
        for road_id, values in zip(
            member_ids,
            member_features,
            strict=True,
        ):
            if str(road_id) in rcsd_ids:
                features[str(road_id)].append(
                    tuple(float(value) for value in values)
                )
    return {
        road_id: _mean_feature(rows)
        for road_id, rows in sorted(features.items())
    }


def _union_side_rcsd_candidates(
    base_feature: Mapping[str, Any],
    *,
    side: str,
    rcsd_ids: set[str],
) -> dict[str, tuple[float, ...]]:
    context = base_feature.get(f"{side}_side")
    if not isinstance(context, Mapping):
        return {}
    result = {}
    for row in context.get("road_candidates") or ():
        road_id = str(row.get("road_id") or "")
        if road_id not in rcsd_ids:
            continue
        values = tuple(
            float(value)
            for value in (
                list(row.get("feature_values") or ())[
                    :ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM
                ]
            )
        )
        if len(values) != ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM:
            raise ValueError("AdvanceRight side Road evidence differs")
        result[road_id] = values
    return result


def _mean_feature(rows: Sequence[Sequence[float]]) -> tuple[float, ...]:
    if not rows:
        raise ValueError("cannot pool an empty member feature set")
    if any(
        len(row) != ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM for row in rows
    ):
        raise ValueError("ordinary member geometry feature differs")
    return tuple(
        sum(float(row[index]) for row in rows) / len(rows)
        for index in range(ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM)
    )


def _proposal_features(row: Mapping[str, Any]) -> list[float]:
    proposal_type = str(row["proposal_type"])
    type_index = _PROPOSAL_TYPE_INDEX[proposal_type]
    type_values = [
        float(index == type_index) for index in range(_PROPOSAL_TYPE_COUNT)
    ]
    values = [
        *type_values,
        *[float(value) for value in row["candidate_feature_values"]],
        *[float(value) for value in row["target_member_feature_values"]],
        *[float(value) for value in row["geometry_feature_values"]],
    ]
    if len(values) != END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM:
        raise ValueError("end-to-end geometry proposal feature differs")
    return values


def _read_inference_roads(
    root: Path,
) -> tuple[dict[str, dict[str, GeometryRoad]], dict[str, set[str]]]:
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    if (
        not bool(summary.get("crs_consistent"))
        or not bool(summary.get("crs_metric"))
        or bool(summary.get("silent_fix"))
    ):
        raise ValueError("geometry candidate CRS/topology contract is invalid")
    inputs = summary.get("inputs", {}).get("inference_roads", ())
    by_case: dict[str, dict[str, GeometryRoad]] = defaultdict(dict)
    rcsd_ids: dict[str, set[str]] = defaultdict(set)
    for record in inputs:
        case_key = str(record["case_key"])
        role = str(record["role"])
        path = normalize_runtime_path(Path(str(record["path"]))).resolve(
            strict=True
        )
        for road in _read_roads(path):
            value = GeometryRoad(
                road_id=road.road_id,
                start_node_id=road.snodeid,
                end_node_id=road.enodeid,
                geometry=road.geometry,
            )
            existing = by_case[case_key].get(value.road_id)
            if (
                existing is not None
                and not existing.geometry.equals(value.geometry)
            ):
                raise ValueError(
                    f"Road id has two geometries: {case_key}:{value.road_id}"
                )
            by_case[case_key][value.road_id] = value
            if role == "RAW_RCSD_ROADS":
                rcsd_ids[case_key].add(value.road_id)
    return dict(by_case), dict(rcsd_ids)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


__all__ = [
    "END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM",
    "EndToEndGeometryBatch",
    "EndToEndGeometryExample",
    "build_union_geometry_examples",
    "collate_end_to_end_geometry_batch",
    "geometry_candidate_gap_rows",
    "geometry_candidate_metrics",
]
