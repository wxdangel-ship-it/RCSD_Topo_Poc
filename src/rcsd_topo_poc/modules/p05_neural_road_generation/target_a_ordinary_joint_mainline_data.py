from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_access_sets import (
    SIDE_ACCESS_FEATURE_DIM,
    SIDE_OBJECT_FEATURE_DIM,
    SIDE_ROAD_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_data import (
    CaseJointExample,
    PackedCaseJointBatch,
    build_focal_ordinary_dependency_examples,
    build_segment_joint_examples,
    collate_case_joint_batch,
    focal_joint_anchor_repeat_counts,
    pack_case_joint_batches,
    segment_joint_anchor_repeat_counts,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    read_anchor_pretraining_stores,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    AnchorOofBusinessPrediction,
    ORDINARY_SET_ROAD_RELATION_DIM,
    ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT,
    ORDINARY_SET_SIDE_COUNT,
    ORDINARY_SET_SOURCE_RCSD,
    ORDINARY_SET_SOURCE_SWSD,
    ORDINARY_SET_SOURCE_UNRESOLVED,
    EndToEndOrdinarySetBatch,
    OrdinarySegmentRoadPool,
    read_truth_free_ordinary_segment_road_pools,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
    ORDINARY_ANCHOR_SUCCESS,
    ORDINARY_ANCHOR_UNRESOLVED,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    read_ordinary_plan_training_examples,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


ACCESS_COLLECTION_FEATURE_DIM = SIDE_ACCESS_FEATURE_DIM
BREAK_CANDIDATE_SOURCES = (
    "PARENT_ENDPOINT",
    "T01_ANCHOR_PROJECTION",
    "ALL_ANCHOR_OBJECT",
    "CANDIDATE_ROAD_ENDPOINT_NEAR",
    "CANDIDATE_ROAD_INTERSECTION",
    "T07_SURFACE_BOUNDARY_INTERSECTION",
    "LEARNED_GRID_PRIOR",
)
BREAK_CANDIDATE_FEATURE_DIM = 4 + len(BREAK_CANDIDATE_SOURCES)
BREAK_OWNERSHIP_NAMES = ("FULL", "PREFIX", "SUFFIX", "OTHER")
MAXIMUM_BREAK_COUNT = 9
BREAK_TARGET_TOLERANCE_M = 5.0
_RESOLVED_NO_ACCESS_STATES = frozenset(
    {
        "DETACHED_JUNC_NODE_NO_ACCESS_REQUIRED",
        "EXEMPT_JUNC_NODE_NO_REQUIRED_ACCESS",
    }
)


@dataclass(frozen=True)
class OrdinaryJointAccessBatch:
    proposal_values: torch.Tensor
    proposal_road_indices: torch.Tensor
    proposal_mask: torch.Tensor
    proposal_targets: torch.Tensor
    task_mask: torch.Tensor
    cardinality_targets: torch.Tensor
    sample_weights: torch.Tensor
    junction_ids: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    proposal_ids: tuple[
        tuple[
            tuple[tuple[str, ...], ...],
            tuple[tuple[str, ...], ...],
        ],
        ...,
    ]

    def __post_init__(self) -> None:
        if (
            self.proposal_values.ndim != 5
            or self.proposal_values.shape[-1] != ACCESS_COLLECTION_FEATURE_DIM
        ):
            raise ValueError("ordinary joint access proposal shape differs")
        shape = self.proposal_values.shape[:-1]
        if (
            self.proposal_road_indices.shape != shape
            or self.proposal_mask.shape != shape
            or self.proposal_targets.shape != shape
        ):
            raise ValueError("ordinary joint access mask/target shape differs")
        group_shape = shape[:-1]
        for values in (
            self.task_mask,
            self.cardinality_targets,
            self.sample_weights,
        ):
            if values.shape != group_shape:
                raise ValueError("ordinary joint access group shape differs")


@dataclass(frozen=True)
class OrdinaryJointBreakBatch:
    parent_road_indices: torch.Tensor
    parent_mask: torch.Tensor
    candidate_values: torch.Tensor
    candidate_fractions: torch.Tensor
    candidate_mask: torch.Tensor
    candidate_targets: torch.Tensor
    task_mask: torch.Tensor
    presence_targets: torch.Tensor
    cardinality_targets: torch.Tensor
    ownership_targets: torch.Tensor
    sample_weights: torch.Tensor
    parent_road_ids: tuple[
        tuple[tuple[str, ...], tuple[str, ...]], ...
    ]

    def __post_init__(self) -> None:
        if (
            self.candidate_values.ndim != 5
            or self.candidate_values.shape[-1] != BREAK_CANDIDATE_FEATURE_DIM
        ):
            raise ValueError("ordinary joint break candidate shape differs")
        candidate_shape = self.candidate_values.shape[:-1]
        for values in (
            self.candidate_fractions,
            self.candidate_mask,
            self.candidate_targets,
        ):
            if values.shape != candidate_shape:
                raise ValueError("ordinary joint break candidate tensor differs")
        parent_shape = candidate_shape[:-1]
        for values in (
            self.parent_road_indices,
            self.parent_mask,
            self.task_mask,
            self.presence_targets,
            self.cardinality_targets,
            self.ownership_targets,
            self.sample_weights,
        ):
            if values.shape != parent_shape:
                raise ValueError("ordinary joint break parent tensor differs")


@dataclass(frozen=True)
class OrdinaryJointMainlineExample:
    joint: CaseJointExample
    ledger: Mapping[str, Any]
    road_pool: OrdinarySegmentRoadPool
    access_features_by_junction: Mapping[str, tuple[Mapping[str, Any], ...]]
    break_tasks: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if not self.joint.ordinary_segments:
            raise ValueError("ordinary joint mainline requires a focal Segment")
        ordinary = self.joint.ordinary_segments[0]
        key = (self.joint.case_key, ordinary.segment_id)
        if key != (self.road_pool.case_key, self.road_pool.segment_id):
            raise ValueError("ordinary joint mainline Road pool identity differs")
        if key != (
            str(self.ledger["case_key"]),
            str(self.ledger["segment_id"]),
        ):
            raise ValueError("ordinary joint mainline ledger identity differs")


@dataclass(frozen=True)
class OrdinaryJointMainlineBatch:
    packed: PackedCaseJointBatch
    ordinary: EndToEndOrdinarySetBatch
    access: OrdinaryJointAccessBatch
    breaks: OrdinaryJointBreakBatch
    examples: tuple[OrdinaryJointMainlineExample, ...]


def read_ordinary_joint_mainline_examples(
    *,
    anchor_store_root: Path,
    candidate_store_root: Path,
    plan_label_root: Path,
    ledger_root: Path,
    road_member_store_root: Path,
    access_feature_store_root: Path,
    break_task_store_root: Path,
    include_junction_context_segments: bool = False,
) -> tuple[OrdinaryJointMainlineExample, ...]:
    """Read each city-derived store once and join by frozen Segment identity."""

    anchors = read_anchor_pretraining_stores(
        normalize_runtime_path(anchor_store_root).resolve(strict=True)
    )
    ordinary = read_ordinary_plan_training_examples(
        candidate_store_root=normalize_runtime_path(
            candidate_store_root
        ).resolve(strict=True),
        preflight_root=normalize_runtime_path(plan_label_root).resolve(
            strict=True
        ),
    )
    joints = (
        build_focal_ordinary_dependency_examples(
            anchors,
            ordinary,
            lightweight_context_segments=True,
        )
        if include_junction_context_segments
        else build_segment_joint_examples(anchors, ordinary)
    )
    ledger_path = (
        normalize_runtime_path(ledger_root).resolve(strict=True)
        / "ordinary_joint_ledger.jsonl"
    )
    ledger = _unique_index(_read_jsonl(ledger_path), "ordinary joint ledger")
    required_keys = {
        (row.case_key, row.ordinary_segments[0].segment_id) for row in joints
    }
    pools = read_truth_free_ordinary_segment_road_pools(
        normalize_runtime_path(road_member_store_root).resolve(strict=True),
        required_keys=required_keys,
    )
    access_features = _read_access_features(
        normalize_runtime_path(access_feature_store_root).resolve(strict=True)
        / "ordinary_access_conditioned_candidates.jsonl",
        required_keys=required_keys,
    )
    break_tasks = _read_break_tasks(
        normalize_runtime_path(break_task_store_root).resolve(strict=True)
        / "parent_road_break_tasks.jsonl",
        required_keys=required_keys,
    )
    missing_ledger = sorted(required_keys - set(ledger))
    if missing_ledger:
        raise ValueError(
            f"ordinary joint mainline lacks ledger rows: {missing_ledger[:3]}"
        )
    result = []
    for joint in joints:
        segment_id = joint.ordinary_segments[0].segment_id
        key = (joint.case_key, segment_id)
        result.append(
            OrdinaryJointMainlineExample(
                joint=joint,
                ledger=ledger[key],
                road_pool=pools[key],
                access_features_by_junction={
                    junction_id: tuple(values)
                    for (case_key, owner_id, junction_id), values in access_features.items()
                    if (case_key, owner_id) == key
                },
                break_tasks=tuple(break_tasks.get(key, ())),
            )
        )
    return tuple(result)


def pack_ordinary_joint_mainline_batches(
    examples: Sequence[OrdinaryJointMainlineExample],
    *,
    teacher_forcing: bool,
    max_batch_size: int,
    max_anchor_groups: int,
    junction_context_segments: bool = False,
    anchor_repeat_counts: Mapping[tuple[str, str], int] | None = None,
    anchor_receives_segment_context: bool = False,
    segment_peer_context: bool | None = None,
    canonical_anchor_predictions: Mapping[
        tuple[str, str], AnchorOofBusinessPrediction
    ]
    | None = None,
) -> tuple[OrdinaryJointMainlineBatch, ...]:
    if not examples:
        raise ValueError("ordinary joint mainline examples are empty")
    joints = tuple(row.joint for row in examples)
    repeat_counts = anchor_repeat_counts
    if repeat_counts is None:
        repeat_counts = (
            focal_joint_anchor_repeat_counts(joints)
            if junction_context_segments
            else segment_joint_anchor_repeat_counts(joints)
        )
    peer_context = (
        junction_context_segments
        if segment_peer_context is None
        else segment_peer_context
    )
    case_batches = [
        collate_case_joint_batch(
            row.joint,
            teacher_forcing=teacher_forcing,
            include_candidate_relations=True,
            retain_anchor_structural_evidence=True,
            retain_ordinary_member_evidence=True,
            retain_ordinary_arm_evidence=True,
            anchor_repeat_counts=repeat_counts,
            focal_only_supervision=junction_context_segments,
            bidirectional_segment_anchor_context=(
                anchor_receives_segment_context
            ),
            segment_peer_context=peer_context,
        )
        for row in examples
    ]
    packed = pack_case_joint_batches(
        case_batches,
        max_batch_size=max_batch_size,
        max_anchor_groups=max_anchor_groups,
    )
    by_key = {
        (row.joint.case_key, row.joint.ordinary_segments[0].segment_id): row
        for row in examples
    }
    return tuple(
        _collate_packed_mainline(
            row,
            by_key=by_key,
            canonical_anchor_predictions=canonical_anchor_predictions,
        )
        for row in packed
    )


def move_ordinary_joint_access_batch(
    batch: OrdinaryJointAccessBatch,
    device: torch.device,
) -> OrdinaryJointAccessBatch:
    return OrdinaryJointAccessBatch(
        **{
            key: value.to(device) if isinstance(value, torch.Tensor) else value
            for key, value in batch.__dict__.items()
        }
    )


def move_ordinary_joint_break_batch(
    batch: OrdinaryJointBreakBatch,
    device: torch.device,
) -> OrdinaryJointBreakBatch:
    return OrdinaryJointBreakBatch(
        **{
            key: value.to(device) if isinstance(value, torch.Tensor) else value
            for key, value in batch.__dict__.items()
        }
    )


def build_break_candidate_features(
    source_values: Mapping[str, Sequence[float]],
    *,
    parent_length_m: float,
) -> tuple[tuple[float, ...], tuple[tuple[float, ...], ...]]:
    """Build inference-only break positions; teacher/terminal positions are ignored."""

    source_index = {
        name: index for index, name in enumerate(BREAK_CANDIDATE_SOURCES)
    }
    by_fraction: dict[float, set[str]] = defaultdict(set)
    for source, values in source_values.items():
        if source not in source_index or source == "LEARNED_GRID_PRIOR":
            continue
        for value in values:
            fraction = min(max(float(value), 0.0), 1.0)
            by_fraction[round(fraction, 10)].add(source)
    for index in range(10):
        by_fraction[round(0.05 + index * 0.10, 10)].add(
            "LEARNED_GRID_PRIOR"
        )
    fractions = tuple(sorted(by_fraction))
    length_feature = math.log1p(max(parent_length_m, 0.0)) / 8.0
    rows = []
    for fraction in fractions:
        flags = [0.0] * len(BREAK_CANDIDATE_SOURCES)
        for source in by_fraction[fraction]:
            flags[source_index[source]] = 1.0
        rows.append(
            (
                fraction,
                1.0 - fraction,
                min(fraction, 1.0 - fraction),
                length_feature,
                *flags,
            )
        )
    return fractions, tuple(rows)


def _ordinary_mainline_side_group_indices(batch_size: int) -> torch.Tensor:
    """Map only the focal ordinary Segment; the second side is padding."""

    if batch_size < 1:
        raise ValueError("ordinary joint mainline batch is empty")
    indices = torch.full(
        (batch_size, ORDINARY_SET_SIDE_COUNT),
        -1,
        dtype=torch.long,
    )
    indices[:, 0] = 0
    return indices


def _collate_packed_mainline(
    packed: PackedCaseJointBatch,
    *,
    by_key: Mapping[tuple[str, str], OrdinaryJointMainlineExample],
    canonical_anchor_predictions: Mapping[
        tuple[str, str], AnchorOofBusinessPrediction
    ]
    | None,
) -> OrdinaryJointMainlineBatch:
    examples = tuple(
        by_key[(member.example.case_key, member.example.ordinary_segments[0].segment_id)]
        for member in packed.members
    )
    ordinary = _collate_ordinary_set(
        packed,
        examples,
        canonical_anchor_predictions=canonical_anchor_predictions,
    )
    access = _collate_access(examples)
    breaks = _collate_breaks(examples)
    return OrdinaryJointMainlineBatch(
        packed=packed,
        ordinary=ordinary,
        access=access,
        breaks=breaks,
        examples=examples,
    )


def _collate_ordinary_set(
    packed: PackedCaseJointBatch,
    examples: Sequence[OrdinaryJointMainlineExample],
    *,
    canonical_anchor_predictions: Mapping[
        tuple[str, str], AnchorOofBusinessPrediction
    ]
    | None = None,
) -> EndToEndOrdinarySetBatch:
    batch_size = len(examples)
    side_shape = (batch_size, ORDINARY_SET_SIDE_COUNT)
    maximum_roads = max(len(row.road_pool.road_ids) for row in examples)
    road_shape = (*side_shape, maximum_roads)
    road_values = torch.zeros((*road_shape, SIDE_ROAD_FEATURE_DIM))
    road_mask = torch.zeros(road_shape, dtype=torch.bool)
    road_sources = torch.full(
        road_shape, ORDINARY_SET_SOURCE_UNRESOLVED, dtype=torch.long
    )
    road_relations = torch.zeros(
        (*road_shape, maximum_roads, ORDINARY_SET_ROAD_RELATION_DIM)
    )
    object_values = torch.zeros((*side_shape, SIDE_OBJECT_FEATURE_DIM))
    decision_targets = torch.zeros(side_shape, dtype=torch.long)
    decision_task_mask = torch.zeros(side_shape, dtype=torch.bool)
    member_targets = torch.zeros(road_shape, dtype=torch.bool)
    road_task_mask = torch.zeros(side_shape, dtype=torch.bool)
    cardinality_targets = torch.zeros(side_shape, dtype=torch.long)
    sample_weights = torch.zeros(side_shape)
    candidate_reachable = torch.zeros(side_shape, dtype=torch.bool)
    ownership_targets = torch.zeros(road_shape, dtype=torch.long)
    ownership_task_mask = torch.zeros(road_shape, dtype=torch.bool)
    role_targets = torch.zeros(road_shape, dtype=torch.long)
    role_task_mask = torch.zeros(road_shape, dtype=torch.bool)
    ownership_weights = torch.zeros(side_shape)
    role_weights = torch.zeros(side_shape)
    required_source = packed.training_batch.tensors.ordinary_required_anchor_indices
    maximum_required = required_source.shape[-1]
    maximum_anchor_candidates = packed.training_batch.tensors.anchor_candidate_mask.shape[-1]
    required_indices = torch.full(
        (*side_shape, maximum_required), -1, dtype=torch.long
    )
    anchor_relations = torch.zeros(
        (
            *side_shape,
            maximum_roads,
            maximum_required,
            maximum_anchor_candidates,
            4,
        )
    )
    anchor_candidate_mask = torch.zeros(
        (*side_shape, maximum_required, maximum_anchor_candidates),
        dtype=torch.bool,
    )
    precomputed_anchor_context = (
        torch.zeros((*road_shape, 8))
        if canonical_anchor_predictions is not None
        else None
    )
    precomputed_anchor_state = (
        torch.zeros(side_shape, dtype=torch.long)
        if canonical_anchor_predictions is not None
        else None
    )
    road_ids: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    segment_ids = []
    for batch_index, (member, example) in enumerate(
        zip(packed.members, examples, strict=True)
    ):
        pool = example.road_pool
        ledger = example.ledger
        count = len(pool.road_ids)
        object_values[batch_index, 0] = torch.tensor(pool.object_feature_values)
        road_values[batch_index, 0, :count] = torch.tensor(pool.road_feature_values)
        road_mask[batch_index, 0, :count] = True
        road_sources[batch_index, 0, :count] = torch.tensor(pool.road_sources)
        for left, right, values in pool.road_relations:
            road_relations[batch_index, 0, left, right] = torch.tensor(values)
            road_relations[batch_index, 0, right, left] = torch.tensor(values)
        plan = ledger["plan_label"]
        preferred = str(plan.get("preferred_decision") or "")
        if preferred == "KEEP_SWSD":
            decision_targets[batch_index, 0] = ORDINARY_DECISION_KEEP_SWSD
            decision_task_mask[batch_index, 0] = bool(plan.get("task_mask"))
        elif preferred in {"USE_RCSD", "T06_MAIN_RCSD_ATTACHED_SWSD"}:
            decision_targets[batch_index, 0] = ORDINARY_DECISION_USE_RCSD
            decision_task_mask[batch_index, 0] = bool(plan.get("task_mask"))
        target_ids = set(pool.acceptable_road_ids)
        target_indices = [
            index for index, road_id in enumerate(pool.road_ids) if road_id in target_ids
        ]
        reachable = bool(target_ids) and len(target_indices) == len(target_ids)
        candidate_reachable[batch_index, 0] = reachable
        road_task_mask[batch_index, 0] = bool(
            ledger["road_label"].get("task_mask") and reachable
        )
        member_targets[batch_index, 0, target_indices] = True
        cardinality_targets[batch_index, 0] = len(target_ids)
        sample_weights[batch_index, 0] = float(plan.get("label_weight") or 0.0)
        if pool.road_ownership_targets:
            ownership_targets[batch_index, 0, :count] = torch.tensor(
                pool.road_ownership_targets
            )
            ownership_task_mask[batch_index, 0, :count] = torch.tensor(
                pool.road_ownership_task_mask
            )
        if pool.road_business_role_targets:
            role_targets[batch_index, 0, :count] = torch.tensor(
                pool.road_business_role_targets
            )
            role_task_mask[batch_index, 0, :count] = torch.tensor(
                pool.road_business_role_task_mask
            )
        ownership_weights[batch_index, 0] = pool.road_ownership_sample_weight
        role_weights[batch_index, 0] = pool.road_business_role_sample_weight
        required_indices[batch_index, 0] = required_source[batch_index, 0]
        _fill_anchor_relations(
            anchor_relations[batch_index, 0],
            anchor_candidate_mask[batch_index, 0],
            member=member,
            pool=pool,
        )
        if canonical_anchor_predictions is not None:
            assert precomputed_anchor_context is not None
            assert precomputed_anchor_state is not None
            state, candidate_ids = _canonical_side_anchor_business_state(
                case_key=example.joint.case_key,
                required_anchor_ids=(
                    member.metadata.ordinary_required_anchor_ids[0]
                ),
                predictions=canonical_anchor_predictions,
            )
            precomputed_anchor_state[batch_index, 0] = state
            if state == ORDINARY_ANCHOR_SUCCESS:
                valid_candidate_ids = {
                    candidate_id
                    for anchor in example.joint.anchors
                    if anchor.anchor_id
                    in member.metadata.ordinary_required_anchor_ids[0]
                    for candidate_id in anchor.candidate_ids
                }
                unknown = set(candidate_ids) - valid_candidate_ids
                if unknown:
                    raise ValueError(
                        "canonical anchor selected an object outside the "
                        f"focal evidence: {example.joint.case_key}/"
                        f"{pool.segment_id}/{sorted(unknown)}"
                    )
                for road_index in range(count):
                    relations = torch.tensor(
                        [
                            _anchor_candidate_relation(
                                pool,
                                road_index=road_index,
                                candidate_id=candidate_id,
                            )
                            for candidate_id in candidate_ids
                        ]
                    )
                    precomputed_anchor_context[
                        batch_index, 0, road_index
                    ] = torch.cat(
                        (relations.mean(dim=0), relations.amax(dim=0))
                    )
        road_ids.append((pool.road_ids, ()))
        segment_ids.append((pool.segment_id, ""))
    return EndToEndOrdinarySetBatch(
        case_keys=tuple(row.joint.case_key for row in examples),
        advance_right_ids=tuple("" for _ in examples),
        side_segment_ids=tuple(segment_ids),
        side_group_indices=_ordinary_mainline_side_group_indices(batch_size),
        side_object_values=object_values,
        side_road_values=road_values,
        side_road_mask=road_mask,
        side_road_source_indices=road_sources,
        side_road_relation_values=road_relations,
        side_access_values=torch.zeros((*side_shape, 1, SIDE_ACCESS_FEATURE_DIM)),
        side_access_mask=torch.zeros((*side_shape, 1), dtype=torch.bool),
        decision_targets=decision_targets,
        decision_task_mask=decision_task_mask,
        road_member_targets=member_targets,
        road_task_mask=road_task_mask,
        road_cardinality_targets=cardinality_targets,
        access_targets=torch.zeros((*side_shape, 1), dtype=torch.bool),
        access_task_mask=torch.zeros(side_shape, dtype=torch.bool),
        sample_weights=sample_weights,
        candidate_reachable=candidate_reachable,
        road_ids=tuple(road_ids),
        access_road_ids=tuple(((), ()) for _ in examples),
        side_precomputed_anchor_context=precomputed_anchor_context,
        side_precomputed_anchor_state=precomputed_anchor_state,
        side_required_anchor_indices=required_indices,
        side_anchor_candidate_relation_values=anchor_relations,
        side_anchor_candidate_mask=anchor_candidate_mask,
        road_ownership_targets=ownership_targets,
        road_ownership_task_mask=ownership_task_mask,
        road_business_role_targets=role_targets,
        road_business_role_task_mask=role_task_mask,
        road_ownership_sample_weights=ownership_weights,
        road_business_role_sample_weights=role_weights,
    )


def _canonical_side_anchor_business_state(
    *,
    case_key: str,
    required_anchor_ids: Sequence[str],
    predictions: Mapping[
        tuple[str, str], AnchorOofBusinessPrediction
    ],
) -> tuple[int, tuple[str, ...]]:
    """Aggregate locked per-Junction anchor results for one focal Segment."""

    if not required_anchor_ids:
        return ORDINARY_ANCHOR_UNRESOLVED, ()
    rows = [
        predictions.get((case_key, str(anchor_id)))
        for anchor_id in required_anchor_ids
    ]
    if any(
        row is None
        or row.business_state == ORDINARY_ANCHOR_UNRESOLVED
        for row in rows
    ):
        return ORDINARY_ANCHOR_UNRESOLVED, ()
    if any(
        row.business_state == ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE
        for row in rows
        if row is not None
    ):
        return ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE, ()
    return ORDINARY_ANCHOR_SUCCESS, tuple(
        row.candidate_id for row in rows if row is not None
    )


def _fill_anchor_relations(
    destination: torch.Tensor,
    candidate_mask: torch.Tensor,
    *,
    member: Any,
    pool: OrdinarySegmentRoadPool,
) -> None:
    required_ids = member.metadata.ordinary_required_anchor_ids[0]
    anchor_index = {
        anchor_id: index for index, anchor_id in enumerate(member.metadata.anchor_ids)
    }
    candidate_ids = member.metadata.anchor_candidate_ids
    for required_position, anchor_id in enumerate(required_ids):
        index = anchor_index.get(anchor_id)
        if index is None:
            continue
        ids = candidate_ids[index]
        candidate_mask[required_position, : len(ids)] = True
        for road_index in range(len(pool.road_ids)):
            for candidate_index, candidate_id in enumerate(ids):
                destination[
                    road_index, required_position, candidate_index
                ] = torch.tensor(
                    _anchor_candidate_relation(
                        pool,
                        road_index=road_index,
                        candidate_id=candidate_id,
                    )
                )


def _collate_access(
    examples: Sequence[OrdinaryJointMainlineExample],
) -> OrdinaryJointAccessBatch:
    prepared = [_prepare_access_groups(row) for row in examples]
    maximum_groups = max(1, max(len(row) for row in prepared))
    maximum_proposals = max(
        1,
        max((len(group["proposals"]) for row in prepared for group in row), default=0),
    )
    shape = (len(examples), ORDINARY_SET_SIDE_COUNT, maximum_groups, maximum_proposals)
    values = torch.zeros((*shape, ACCESS_COLLECTION_FEATURE_DIM))
    road_indices = torch.full(shape, -1, dtype=torch.long)
    mask = torch.zeros(shape, dtype=torch.bool)
    targets = torch.zeros(shape, dtype=torch.bool)
    task = torch.zeros(shape[:-1], dtype=torch.bool)
    cardinality = torch.zeros(shape[:-1], dtype=torch.long)
    weights = torch.zeros(shape[:-1])
    junction_ids = []
    proposal_ids = []
    for batch_index, groups in enumerate(prepared):
        side_junctions = []
        side_proposals = []
        for group_index, group in enumerate(groups):
            proposals = group["proposals"]
            count = len(proposals)
            values[batch_index, 0, group_index, :count] = torch.tensor(
                [row["feature_values"] for row in proposals]
            )
            road_indices[batch_index, 0, group_index, :count] = torch.tensor(
                [row["road_index"] for row in proposals]
            )
            mask[batch_index, 0, group_index, :count] = True
            target_ids = set(group["target_proposal_ids"])
            for proposal_index, proposal in enumerate(proposals):
                if proposal["proposal_id"] in target_ids:
                    targets[batch_index, 0, group_index, proposal_index] = True
            reachable = bool(target_ids) and sum(
                bool(value) for value in targets[batch_index, 0, group_index]
            ) == len(target_ids)
            task[batch_index, 0, group_index] = bool(
                group["task_mask"] and reachable
            )
            cardinality[batch_index, 0, group_index] = len(target_ids)
            weights[batch_index, 0, group_index] = float(group["label_weight"])
            side_junctions.append(str(group["junction_id"]))
            side_proposals.append(
                tuple(str(row["proposal_id"]) for row in proposals)
            )
        junction_ids.append((tuple(side_junctions), ()))
        proposal_ids.append((tuple(side_proposals), ()))
    return OrdinaryJointAccessBatch(
        proposal_values=values,
        proposal_road_indices=road_indices,
        proposal_mask=mask,
        proposal_targets=targets,
        task_mask=task,
        cardinality_targets=cardinality,
        sample_weights=weights,
        junction_ids=tuple(junction_ids),
        proposal_ids=tuple(proposal_ids),
    )


def _prepare_access_groups(
    example: OrdinaryJointMainlineExample,
) -> tuple[dict[str, Any], ...]:
    pool_by_road = {
        road_id: (index, values)
        for index, (road_id, values) in enumerate(zip(
            example.road_pool.road_ids,
            example.road_pool.road_feature_values,
            strict=True,
        ))
    }
    labels_by_junction = {
        str(row["junction_id"]): row
        for row in example.ledger.get("access_labels") or ()
    }
    source = example.joint.ordinary_segments[0]
    inference_junction_ids = set(source.junc_node_ids) | set(
        example.access_features_by_junction
    )
    groups = []
    for junction_id in sorted(inference_junction_ids):
        label = labels_by_junction.get(junction_id) or {}
        raw = example.access_features_by_junction.get(junction_id, ())
        proposals = []
        for row in raw:
            road = pool_by_road.get(str(row["road_id"]))
            geometry = tuple(
                float(value) for value in row.get("geometry_feature_values") or ()
            )
            if road is None or len(geometry) != (
                SIDE_ACCESS_FEATURE_DIM - SIDE_ROAD_FEATURE_DIM
            ):
                continue
            road_index, road_values = road
            proposals.append(
                {
                    "proposal_id": str(row["proposal_id"]),
                    "road_index": road_index,
                    "feature_values": (*road_values, *geometry),
                }
            )
        collections = list(label.get("acceptable_access_collections") or ())
        target_ids: tuple[str, ...] = ()
        task_mask = False
        if bool(label.get("task_mask")) and len(collections) == 1:
            target_ids = tuple(
                str(value) for value in collections[0].get("proposal_ids") or ()
            )
            task_mask = True
        elif str(label.get("label_state") or "") in _RESOLVED_NO_ACCESS_STATES:
            task_mask = True
        groups.append(
            {
                "junction_id": junction_id,
                "proposals": tuple(
                    sorted(proposals, key=lambda row: row["proposal_id"])
                ),
                "target_proposal_ids": target_ids,
                "task_mask": task_mask,
                "label_weight": float(label.get("label_weight") or 0.0),
            }
        )
    return tuple(groups)


def _collate_breaks(
    examples: Sequence[OrdinaryJointMainlineExample],
) -> OrdinaryJointBreakBatch:
    prepared = [_prepare_break_groups(row) for row in examples]
    maximum_parents = max(1, max(len(row) for row in prepared))
    maximum_candidates = max(
        1,
        max((len(group["fractions"]) for row in prepared for group in row), default=0),
    )
    parent_shape = (len(examples), ORDINARY_SET_SIDE_COUNT, maximum_parents)
    candidate_shape = (*parent_shape, maximum_candidates)
    parent_indices = torch.full(parent_shape, -1, dtype=torch.long)
    parent_mask = torch.zeros(parent_shape, dtype=torch.bool)
    values = torch.zeros((*candidate_shape, BREAK_CANDIDATE_FEATURE_DIM))
    fractions = torch.zeros(candidate_shape)
    candidate_mask = torch.zeros(candidate_shape, dtype=torch.bool)
    targets = torch.zeros(candidate_shape, dtype=torch.bool)
    task = torch.zeros(parent_shape, dtype=torch.bool)
    presence = torch.zeros(parent_shape, dtype=torch.bool)
    cardinality = torch.zeros(parent_shape, dtype=torch.long)
    ownership = torch.zeros(parent_shape, dtype=torch.long)
    weights = torch.zeros(parent_shape)
    parent_ids = []
    for batch_index, groups in enumerate(prepared):
        side_ids = []
        for parent_index, group in enumerate(groups):
            count = len(group["fractions"])
            parent_indices[batch_index, 0, parent_index] = group["road_index"]
            parent_mask[batch_index, 0, parent_index] = True
            values[batch_index, 0, parent_index, :count] = torch.tensor(
                group["feature_values"]
            )
            fractions[batch_index, 0, parent_index, :count] = torch.tensor(
                group["fractions"]
            )
            candidate_mask[batch_index, 0, parent_index, :count] = True
            target_indices = group["target_indices"]
            targets[batch_index, 0, parent_index, target_indices] = True
            task[batch_index, 0, parent_index] = bool(group["task_mask"])
            presence[batch_index, 0, parent_index] = bool(group["presence"])
            cardinality[batch_index, 0, parent_index] = len(target_indices)
            ownership[batch_index, 0, parent_index] = int(group["ownership"])
            weights[batch_index, 0, parent_index] = float(group["sample_weight"])
            side_ids.append(str(group["parent_road_id"]))
        parent_ids.append((tuple(side_ids), ()))
    return OrdinaryJointBreakBatch(
        parent_road_indices=parent_indices,
        parent_mask=parent_mask,
        candidate_values=values,
        candidate_fractions=fractions,
        candidate_mask=candidate_mask,
        candidate_targets=targets,
        task_mask=task,
        presence_targets=presence,
        cardinality_targets=cardinality,
        ownership_targets=ownership,
        sample_weights=weights,
        parent_road_ids=tuple(parent_ids),
    )


def _prepare_break_groups(
    example: OrdinaryJointMainlineExample,
) -> tuple[dict[str, Any], ...]:
    road_index = {
        road_id: index for index, road_id in enumerate(example.road_pool.road_ids)
    }
    groups = []
    for row in example.break_tasks:
        parent_id = str(row["raw_parent_road_id"])
        if parent_id not in road_index:
            continue
        fractions, features = build_break_candidate_features(
            row.get("candidate_fractions") or {},
            parent_length_m=float(row.get("parent_length_m") or 0.0),
        )
        truth = tuple(float(value) for value in row.get("truth_break_fractions") or ())
        target_indices = []
        reachable = True
        for truth_fraction in truth:
            if not fractions:
                reachable = False
                break
            nearest = min(
                range(len(fractions)),
                key=lambda index: abs(fractions[index] - truth_fraction),
            )
            error_m = abs(fractions[nearest] - truth_fraction) * float(
                row.get("parent_length_m") or 0.0
            )
            if error_m > BREAK_TARGET_TOLERANCE_M:
                reachable = False
                break
            target_indices.append(nearest)
        target_indices = sorted(set(target_indices))
        state = str(row.get("target_state") or "")
        labeled = bool(row.get("task_mask")) and state in {"BREAK", "NO_BREAK"}
        task_mask = labeled and reachable and (
            (state == "BREAK" and bool(target_indices))
            or (state == "NO_BREAK" and not target_indices)
        )
        raw_ownership = str(row.get("truth_ownership") or "OTHER")
        ownership_name = (
            raw_ownership if raw_ownership in BREAK_OWNERSHIP_NAMES else "OTHER"
        )
        groups.append(
            {
                "parent_road_id": parent_id,
                "road_index": road_index[parent_id],
                "fractions": fractions,
                "feature_values": features,
                "target_indices": target_indices,
                "task_mask": task_mask,
                "presence": state == "BREAK",
                "ownership": BREAK_OWNERSHIP_NAMES.index(ownership_name),
                "sample_weight": float(row.get("sample_weight") or 0.0),
            }
        )
    return tuple(groups)


def _anchor_candidate_relation(
    pool: OrdinarySegmentRoadPool,
    *,
    road_index: int,
    candidate_id: str,
) -> tuple[float, float, float, float]:
    selected_roads: set[str] = set()
    selected_nodes: set[str] = set()
    if candidate_id.startswith("ROAD:"):
        selected_roads.update(
            value for value in candidate_id.removeprefix("ROAD:").split("|") if value
        )
    elif candidate_id.startswith("NODE:"):
        selected_nodes.update(
            value for value in candidate_id.removeprefix("NODE:").split("|") if value
        )
    road_match = pool.road_ids[road_index] in selected_roads
    start_match = pool.road_start_node_ids[road_index] in selected_nodes
    end_match = pool.road_end_node_ids[road_index] in selected_nodes
    return (
        float(road_match),
        float(start_match),
        float(end_match),
        float(road_match or start_match or end_match),
    )


def _read_access_features(
    path: Path,
    *,
    required_keys: set[tuple[str, str]],
) -> dict[tuple[str, str, str], list[Mapping[str, Any]]]:
    result: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(path):
        key = (str(row["case_key"]), str(row["segment_id"]))
        if key not in required_keys:
            continue
        if bool(row.get("feature_uses_truth")) or int(row.get("terminal_input_count", 0)):
            raise ValueError(f"ordinary access inference feature uses truth: {key}")
        result[(*key, str(row["junc_node_id"]))].append(row)
    return result


def _read_break_tasks(
    path: Path,
    *,
    required_keys: set[tuple[str, str]],
) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    result: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for row in _read_jsonl(path):
        key = (str(row["case_key"]), str(row["segment_id"]))
        if key not in required_keys:
            continue
        unique = (*key, str(row["raw_parent_road_id"]))
        if unique in seen:
            raise ValueError(f"duplicate ordinary break parent: {unique}")
        seen.add(unique)
        if bool(row.get("feature_uses_truth")) or int(row.get("terminal_input_count", 0)):
            raise ValueError(f"ordinary break inference feature uses truth: {key}")
        result[key].append(row)
    return result


def _unique_index(
    rows: Iterable[Mapping[str, Any]],
    label: str,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    for row in rows:
        key = (str(row["case_key"]), str(row["segment_id"]))
        if key in result:
            raise ValueError(f"duplicate {label}: {key}")
        result[key] = row
    return result


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = [
    "ACCESS_COLLECTION_FEATURE_DIM",
    "BREAK_CANDIDATE_FEATURE_DIM",
    "BREAK_OWNERSHIP_NAMES",
    "MAXIMUM_BREAK_COUNT",
    "OrdinaryJointAccessBatch",
    "OrdinaryJointBreakBatch",
    "OrdinaryJointMainlineBatch",
    "OrdinaryJointMainlineExample",
    "build_break_candidate_features",
    "move_ordinary_joint_access_batch",
    "move_ordinary_joint_break_batch",
    "pack_ordinary_joint_mainline_batches",
    "read_ordinary_joint_mainline_examples",
]
