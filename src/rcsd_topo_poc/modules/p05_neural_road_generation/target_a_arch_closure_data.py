from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_access_sets import (
    SIDE_ACCESS_FEATURE_DIM,
    SIDE_OBJECT_FEATURE_DIM,
    SIDE_ROAD_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
    ORDINARY_ANCHOR_SUCCESS,
    ORDINARY_ANCHOR_UNRESOLVED,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    ORDINARY_SET_ROAD_RELATION_DIM,
    ORDINARY_SET_SIDE_COUNT,
    ORDINARY_SET_SOURCE_UNRESOLVED,
    EndToEndOrdinarySetBatch,
    OrdinarySegmentRoadPool,
    move_end_to_end_ordinary_set_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_data import (
    OrdinaryJointAccessBatch,
    OrdinaryJointBreakBatch,
    OrdinaryJointMainlineExample,
    _anchor_candidate_relation,
    _collate_access,
    _collate_breaks,
    _ordinary_mainline_side_group_indices,
    move_ordinary_joint_access_batch,
    move_ordinary_joint_break_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_structured_data import (
    OrdinaryJointStructuredPlanBatch,
    collate_ordinary_joint_structured_plan_batch,
    move_ordinary_joint_structured_plan_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
)


JUNCTION_CONFIDENCE_DIM = 4


@dataclass(frozen=True)
class ArchClosureJunctionRecord:
    key: tuple[str, str]
    example: AnchorPretrainExample
    direct_dependency_keys: tuple[tuple[str, str], ...]
    direct_segment_keys: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ArchClosureSegmentRecord:
    key: tuple[str, str]
    example: OrdinaryPlanTrainingExample
    required_junction_keys: tuple[tuple[str, str], ...]
    context_segment_keys: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ArchClosurePlanRecord:
    key: tuple[str, str]
    ledger: Mapping[str, Any]
    road_pool: OrdinarySegmentRoadPool
    access_features_by_junction: Mapping[
        str, tuple[Mapping[str, Any], ...]
    ]
    break_tasks: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ArchClosureReferenceStores:
    junctions: Mapping[tuple[str, str], ArchClosureJunctionRecord]
    segments: Mapping[tuple[str, str], ArchClosureSegmentRecord]
    plans: Mapping[tuple[str, str], ArchClosurePlanRecord]

    def __post_init__(self) -> None:
        if not self.junctions or not self.segments or not self.plans:
            raise ValueError("architecture-closure reference store is empty")
        if set(self.segments) != set(self.plans):
            raise ValueError("SegmentStore and PlanStore identities differ")


@dataclass(frozen=True)
class ArchClosureJunctionCacheEntry:
    key: tuple[str, str]
    business_state: int
    candidate_id: str
    embedding: torch.Tensor
    confidence_values: torch.Tensor

    def __post_init__(self) -> None:
        if self.business_state not in {
            ORDINARY_ANCHOR_UNRESOLVED,
            ORDINARY_ANCHOR_SUCCESS,
            ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
        }:
            raise ValueError("Junction cache business state is unsupported")
        if self.embedding.ndim != 1:
            raise ValueError("Junction cache embedding is not a vector")
        if self.confidence_values.shape != (JUNCTION_CONFIDENCE_DIM,):
            raise ValueError("Junction cache confidence shape differs")
        if self.business_state == ORDINARY_ANCHOR_SUCCESS and not self.candidate_id:
            raise ValueError("successful Junction cache lacks anchor object")
        if self.business_state != ORDINARY_ANCHOR_SUCCESS and self.candidate_id:
            raise ValueError("non-success Junction cache exposes an anchor object")


@dataclass(frozen=True)
class ArchClosureSegmentContextBatch:
    focal_feature_values: torch.Tensor
    peer_feature_values: torch.Tensor
    peer_mask: torch.Tensor
    junction_embedding_values: torch.Tensor
    junction_confidence_values: torch.Tensor
    junction_state_values: torch.Tensor
    junction_mask: torch.Tensor
    peer_junction_relation_mask: torch.Tensor

    def __post_init__(self) -> None:
        if (
            self.focal_feature_values.ndim != 2
            or self.focal_feature_values.shape[-1] != TARGET_A_FEATURE_DIM
        ):
            raise ValueError("focal Segment feature shape differs")
        if (
            self.peer_feature_values.ndim != 3
            or self.peer_feature_values.shape[-1] != TARGET_A_FEATURE_DIM
            or self.peer_mask.shape != self.peer_feature_values.shape[:2]
        ):
            raise ValueError("peer Segment feature shape differs")
        junction_shape = self.junction_embedding_values.shape[:2]
        if (
            self.junction_embedding_values.ndim != 3
            or self.junction_confidence_values.shape
            != (*junction_shape, JUNCTION_CONFIDENCE_DIM)
            or self.junction_state_values.shape != junction_shape
            or self.junction_mask.shape != junction_shape
        ):
            raise ValueError("Junction reference tensor shape differs")
        if self.peer_junction_relation_mask.shape != (
            self.focal_feature_values.shape[0],
            self.peer_feature_values.shape[1],
            self.junction_embedding_values.shape[1],
        ):
            raise ValueError("peer-Junction relation shape differs")


@dataclass(frozen=True)
class ArchClosureOrdinaryInput:
    side_group_indices: torch.Tensor
    side_object_values: torch.Tensor
    side_road_values: torch.Tensor
    side_road_mask: torch.Tensor
    side_road_source_indices: torch.Tensor
    side_road_relation_values: torch.Tensor
    side_access_values: torch.Tensor
    side_access_mask: torch.Tensor
    side_precomputed_anchor_context: torch.Tensor
    side_precomputed_anchor_state: torch.Tensor


@dataclass(frozen=True)
class ArchClosureAccessInput:
    proposal_values: torch.Tensor
    proposal_road_indices: torch.Tensor
    proposal_mask: torch.Tensor


@dataclass(frozen=True)
class ArchClosureBreakInput:
    parent_road_indices: torch.Tensor
    parent_mask: torch.Tensor
    candidate_values: torch.Tensor
    candidate_mask: torch.Tensor


@dataclass(frozen=True)
class ArchClosureStructuredPlanInput:
    plan_feature_values: torch.Tensor
    plan_mask: torch.Tensor
    plan_hard_valid: torch.Tensor
    plan_base_decisions: torch.Tensor
    plan_road_membership: torch.Tensor
    plan_role_values: torch.Tensor
    plan_ownership_values: torch.Tensor
    plan_access_road_membership: torch.Tensor
    access_group_arm_indices: torch.Tensor


@dataclass(frozen=True)
class ArchClosureModelInput:
    keys: tuple[tuple[str, str], ...]
    context: ArchClosureSegmentContextBatch
    ordinary: ArchClosureOrdinaryInput
    access: ArchClosureAccessInput
    breaks: ArchClosureBreakInput
    structured: ArchClosureStructuredPlanInput


@dataclass(frozen=True)
class ArchClosureBatch:
    keys: tuple[tuple[str, str], ...]
    model_input: ArchClosureModelInput
    context: ArchClosureSegmentContextBatch
    ordinary: EndToEndOrdinarySetBatch
    access: OrdinaryJointAccessBatch
    breaks: OrdinaryJointBreakBatch
    structured: OrdinaryJointStructuredPlanBatch
    examples: tuple[OrdinaryJointMainlineExample, ...]


def build_arch_closure_reference_stores(
    examples: Sequence[OrdinaryJointMainlineExample],
) -> ArchClosureReferenceStores:
    """Normalize one city-store read into unique Junction/Segment/Plan rows."""

    if not examples:
        raise ValueError("architecture-closure examples are empty")
    anchors: dict[tuple[str, str], AnchorPretrainExample] = {}
    segments: dict[tuple[str, str], OrdinaryPlanTrainingExample] = {}
    plans: dict[tuple[str, str], ArchClosurePlanRecord] = {}
    for row in examples:
        focal = row.joint.ordinary_segments[0]
        key = (row.joint.case_key, focal.segment_id)
        previous_segment = segments.setdefault(key, focal)
        if previous_segment != focal:
            raise ValueError(f"SegmentStore evidence differs: {key}")
        if key in plans:
            raise ValueError(f"PlanStore has duplicate Segment: {key}")
        plans[key] = ArchClosurePlanRecord(
            key=key,
            ledger=row.ledger,
            road_pool=row.road_pool,
            access_features_by_junction=row.access_features_by_junction,
            break_tasks=row.break_tasks,
        )
        for anchor in row.joint.anchors:
            anchor_key = (anchor.case_key, anchor.anchor_id)
            previous_anchor = anchors.setdefault(anchor_key, anchor)
            if previous_anchor != anchor:
                raise ValueError(f"JunctionStore evidence differs: {anchor_key}")

    segments_by_junction: dict[
        tuple[str, str], set[tuple[str, str]]
    ] = defaultdict(set)
    for key, segment in segments.items():
        for anchor_id in segment.required_anchor_ids:
            junction_key = (key[0], str(anchor_id))
            if junction_key not in anchors:
                raise ValueError(
                    f"Segment required Junction is missing: {key}/{anchor_id}"
                )
            segments_by_junction[junction_key].add(key)

    direct_dependencies: dict[
        tuple[str, str], set[tuple[str, str]]
    ] = {key: {key} for key in anchors}
    for key, anchor in anchors.items():
        for dependency_id in anchor.dependency_anchor_ids or (anchor.anchor_id,):
            dependency_key = (key[0], str(dependency_id))
            if dependency_key not in anchors:
                continue
            direct_dependencies[key].add(dependency_key)
            direct_dependencies[dependency_key].add(key)

    junction_store = {
        key: ArchClosureJunctionRecord(
            key=key,
            example=anchor,
            direct_dependency_keys=tuple(sorted(direct_dependencies[key])),
            direct_segment_keys=tuple(sorted(segments_by_junction.get(key, ()))),
        )
        for key, anchor in anchors.items()
    }
    segment_store = {}
    for key, segment in segments.items():
        required = tuple((key[0], str(value)) for value in segment.required_anchor_ids)
        context = set()
        for junction_key in required:
            context.update(segments_by_junction[junction_key])
        context.discard(key)
        segment_store[key] = ArchClosureSegmentRecord(
            key=key,
            example=segment,
            required_junction_keys=required,
            context_segment_keys=tuple(sorted(context)),
        )
    return ArchClosureReferenceStores(
        junctions=junction_store,
        segments=segment_store,
        plans=plans,
    )


def read_arch_closure_junction_cache(
    path: Path,
) -> dict[tuple[str, str], ArchClosureJunctionCacheEntry]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    keys = tuple(tuple(value) for value in payload["keys"])
    states = payload["business_states"]
    embeddings = payload["embeddings"]
    confidence = payload["confidence_values"]
    candidate_ids = tuple(str(value) for value in payload["candidate_ids"])
    if (
        states.shape != (len(keys),)
        or embeddings.shape[0] != len(keys)
        or confidence.shape != (len(keys), JUNCTION_CONFIDENCE_DIM)
        or len(candidate_ids) != len(keys)
        or len(set(keys)) != len(keys)
    ):
        raise ValueError("Junction cache package shape differs")
    return {
        key: ArchClosureJunctionCacheEntry(
            key=key,
            business_state=int(states[index]),
            candidate_id=candidate_ids[index],
            embedding=embeddings[index].float(),
            confidence_values=confidence[index].float(),
        )
        for index, key in enumerate(keys)
    }


def collate_arch_closure_batch(
    stores: ArchClosureReferenceStores,
    keys: Sequence[tuple[str, str]],
    *,
    junction_cache: Mapping[
        tuple[str, str], ArchClosureJunctionCacheEntry
    ],
    teacher_forcing: bool,
) -> ArchClosureBatch:
    if not keys:
        raise ValueError("architecture-closure batch is empty")
    examples = tuple(_plan_example(stores, key) for key in keys)
    context = _collate_context(stores, keys, junction_cache=junction_cache)
    ordinary = _collate_ordinary(
        stores,
        keys,
        junction_cache=junction_cache,
    )
    access = _collate_access(examples)
    breaks = _collate_breaks(examples)
    structured = collate_ordinary_joint_structured_plan_batch(
        examples,
        ordinary,
        access,
        teacher_forcing=teacher_forcing,
    )
    return ArchClosureBatch(
        keys=tuple(keys),
        model_input=_model_input(
            tuple(keys),
            context=context,
            ordinary=ordinary,
            access=access,
            breaks=breaks,
            structured=structured,
        ),
        context=context,
        ordinary=ordinary,
        access=access,
        breaks=breaks,
        structured=structured,
        examples=examples,
    )


def move_arch_closure_batch(
    batch: ArchClosureBatch,
    device: torch.device,
) -> ArchClosureBatch:
    context = ArchClosureSegmentContextBatch(
        **{
            name: value.to(device)
            for name, value in batch.context.__dict__.items()
        }
    )
    ordinary = move_end_to_end_ordinary_set_batch(batch.ordinary, device)
    access = move_ordinary_joint_access_batch(batch.access, device)
    breaks = move_ordinary_joint_break_batch(batch.breaks, device)
    structured = move_ordinary_joint_structured_plan_batch(
        batch.structured, device
    )
    return ArchClosureBatch(
        keys=batch.keys,
        model_input=_model_input(
            batch.keys,
            context=context,
            ordinary=ordinary,
            access=access,
            breaks=breaks,
            structured=structured,
        ),
        context=context,
        ordinary=ordinary,
        access=access,
        breaks=breaks,
        structured=structured,
        examples=batch.examples,
    )


def _model_input(
    keys: tuple[tuple[str, str], ...],
    *,
    context: ArchClosureSegmentContextBatch,
    ordinary: EndToEndOrdinarySetBatch,
    access: OrdinaryJointAccessBatch,
    breaks: OrdinaryJointBreakBatch,
    structured: OrdinaryJointStructuredPlanBatch,
) -> ArchClosureModelInput:
    if (
        ordinary.side_precomputed_anchor_context is None
        or ordinary.side_precomputed_anchor_state is None
    ):
        raise ValueError("architecture-closure model input lacks locked anchor")
    return ArchClosureModelInput(
        keys=keys,
        context=context,
        ordinary=ArchClosureOrdinaryInput(
            side_group_indices=ordinary.side_group_indices,
            side_object_values=ordinary.side_object_values,
            side_road_values=ordinary.side_road_values,
            side_road_mask=ordinary.side_road_mask,
            side_road_source_indices=ordinary.side_road_source_indices,
            side_road_relation_values=ordinary.side_road_relation_values,
            side_access_values=ordinary.side_access_values,
            side_access_mask=ordinary.side_access_mask,
            side_precomputed_anchor_context=(
                ordinary.side_precomputed_anchor_context
            ),
            side_precomputed_anchor_state=(
                ordinary.side_precomputed_anchor_state
            ),
        ),
        access=ArchClosureAccessInput(
            proposal_values=access.proposal_values,
            proposal_road_indices=access.proposal_road_indices,
            proposal_mask=access.proposal_mask,
        ),
        breaks=ArchClosureBreakInput(
            parent_road_indices=breaks.parent_road_indices,
            parent_mask=breaks.parent_mask,
            candidate_values=breaks.candidate_values,
            candidate_mask=breaks.candidate_mask,
        ),
        structured=ArchClosureStructuredPlanInput(
            plan_feature_values=structured.plan_feature_values,
            plan_mask=structured.plan_mask,
            plan_hard_valid=structured.plan_hard_valid,
            plan_base_decisions=structured.plan_base_decisions,
            plan_road_membership=structured.plan_road_membership,
            plan_role_values=structured.plan_role_targets,
            plan_ownership_values=structured.plan_ownership_targets,
            plan_access_road_membership=(
                structured.plan_access_road_membership
            ),
            access_group_arm_indices=structured.access_group_arm_indices,
        ),
    )


def _plan_example(
    stores: ArchClosureReferenceStores,
    key: tuple[str, str],
) -> OrdinaryJointMainlineExample:
    segment = stores.segments[key].example
    plan = stores.plans[key]
    joint = _ReferenceJoint(
        case_key=key[0],
        fold=segment.fold,
        ordinary_segments=(segment,),
    )
    return OrdinaryJointMainlineExample(
        joint=joint,  # type: ignore[arg-type]
        ledger=plan.ledger,
        road_pool=plan.road_pool,
        access_features_by_junction=plan.access_features_by_junction,
        break_tasks=plan.break_tasks,
    )


@dataclass(frozen=True)
class _ReferenceJoint:
    case_key: str
    fold: int
    ordinary_segments: tuple[OrdinaryPlanTrainingExample, ...]


def _collate_context(
    stores: ArchClosureReferenceStores,
    keys: Sequence[tuple[str, str]],
    *,
    junction_cache: Mapping[
        tuple[str, str], ArchClosureJunctionCacheEntry
    ],
) -> ArchClosureSegmentContextBatch:
    maximum_peers = max(1, max(len(stores.segments[key].context_segment_keys) for key in keys))
    maximum_junctions = max(
        1, max(len(stores.segments[key].required_junction_keys) for key in keys)
    )
    first_cache = next(iter(junction_cache.values()))
    hidden_dim = first_cache.embedding.shape[0]
    focal = torch.zeros((len(keys), TARGET_A_FEATURE_DIM))
    peers = torch.zeros((len(keys), maximum_peers, TARGET_A_FEATURE_DIM))
    peer_mask = torch.zeros((len(keys), maximum_peers), dtype=torch.bool)
    junctions = torch.zeros((len(keys), maximum_junctions, hidden_dim))
    confidence = torch.zeros(
        (len(keys), maximum_junctions, JUNCTION_CONFIDENCE_DIM)
    )
    states = torch.full(
        (len(keys), maximum_junctions),
        ORDINARY_ANCHOR_UNRESOLVED,
        dtype=torch.long,
    )
    junction_mask = torch.zeros(
        (len(keys), maximum_junctions), dtype=torch.bool
    )
    relations = torch.zeros(
        (len(keys), maximum_peers, maximum_junctions), dtype=torch.bool
    )
    for row_index, key in enumerate(keys):
        segment = stores.segments[key]
        focal[row_index] = torch.tensor(segment.example.object_features)
        for peer_index, peer_key in enumerate(segment.context_segment_keys):
            peer = stores.segments[peer_key]
            peers[row_index, peer_index] = torch.tensor(
                peer.example.object_features
            )
            peer_mask[row_index, peer_index] = True
        for junction_index, junction_key in enumerate(
            segment.required_junction_keys
        ):
            cached = junction_cache.get(junction_key)
            if cached is None:
                raise ValueError(f"Segment Junction cache is missing: {key}/{junction_key}")
            junctions[row_index, junction_index] = cached.embedding
            confidence[row_index, junction_index] = cached.confidence_values
            states[row_index, junction_index] = cached.business_state
            junction_mask[row_index, junction_index] = True
            direct = set(stores.junctions[junction_key].direct_segment_keys)
            for peer_index, peer_key in enumerate(segment.context_segment_keys):
                relations[row_index, peer_index, junction_index] = peer_key in direct
    return ArchClosureSegmentContextBatch(
        focal_feature_values=focal,
        peer_feature_values=peers,
        peer_mask=peer_mask,
        junction_embedding_values=junctions,
        junction_confidence_values=confidence,
        junction_state_values=states,
        junction_mask=junction_mask,
        peer_junction_relation_mask=relations,
    )


def _collate_ordinary(
    stores: ArchClosureReferenceStores,
    keys: Sequence[tuple[str, str]],
    *,
    junction_cache: Mapping[
        tuple[str, str], ArchClosureJunctionCacheEntry
    ],
) -> EndToEndOrdinarySetBatch:
    batch_size = len(keys)
    side_shape = (batch_size, ORDINARY_SET_SIDE_COUNT)
    maximum_roads = max(len(stores.plans[key].road_pool.road_ids) for key in keys)
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
    anchor_context = torch.zeros((*road_shape, 8))
    anchor_state = torch.full(
        side_shape, ORDINARY_ANCHOR_UNRESOLVED, dtype=torch.long
    )
    road_ids = []
    segment_ids = []
    for batch_index, key in enumerate(keys):
        segment = stores.segments[key]
        plan = stores.plans[key]
        pool = plan.road_pool
        count = len(pool.road_ids)
        object_values[batch_index, 0] = torch.tensor(pool.object_feature_values)
        road_values[batch_index, 0, :count] = torch.tensor(pool.road_feature_values)
        road_mask[batch_index, 0, :count] = True
        road_sources[batch_index, 0, :count] = torch.tensor(pool.road_sources)
        for left, right, values in pool.road_relations:
            road_relations[batch_index, 0, left, right] = torch.tensor(values)
            road_relations[batch_index, 0, right, left] = torch.tensor(values)
        label = plan.ledger["plan_label"]
        preferred = str(label.get("preferred_decision") or "")
        if preferred == "KEEP_SWSD":
            decision_targets[batch_index, 0] = ORDINARY_DECISION_KEEP_SWSD
            decision_task_mask[batch_index, 0] = bool(label.get("task_mask"))
        elif preferred in {"USE_RCSD", "T06_MAIN_RCSD_ATTACHED_SWSD"}:
            decision_targets[batch_index, 0] = ORDINARY_DECISION_USE_RCSD
            decision_task_mask[batch_index, 0] = bool(label.get("task_mask"))
        target_ids = set(pool.acceptable_road_ids)
        target_indices = [
            index for index, road_id in enumerate(pool.road_ids) if road_id in target_ids
        ]
        reachable = bool(target_ids) and len(target_indices) == len(target_ids)
        candidate_reachable[batch_index, 0] = reachable
        road_task_mask[batch_index, 0] = bool(
            plan.ledger["road_label"].get("task_mask") and reachable
        )
        member_targets[batch_index, 0, target_indices] = True
        cardinality_targets[batch_index, 0] = len(target_ids)
        sample_weights[batch_index, 0] = float(label.get("label_weight") or 0.0)
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
        state, selected = _segment_anchor_state(
            segment.required_junction_keys,
            junction_cache=junction_cache,
        )
        anchor_state[batch_index, 0] = state
        if state == ORDINARY_ANCHOR_SUCCESS:
            for road_index in range(count):
                relations = torch.tensor(
                    [
                        _anchor_candidate_relation(
                            pool,
                            road_index=road_index,
                            candidate_id=candidate_id,
                        )
                        for candidate_id in selected
                    ]
                )
                anchor_context[batch_index, 0, road_index] = torch.cat(
                    (relations.mean(dim=0), relations.amax(dim=0))
                )
        road_ids.append((pool.road_ids, ()))
        segment_ids.append((key[1], ""))
    return EndToEndOrdinarySetBatch(
        case_keys=tuple(key[0] for key in keys),
        advance_right_ids=tuple("" for _ in keys),
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
        access_road_ids=tuple(((), ()) for _ in keys),
        side_precomputed_anchor_context=anchor_context,
        side_precomputed_anchor_state=anchor_state,
        road_ownership_targets=ownership_targets,
        road_ownership_task_mask=ownership_task_mask,
        road_business_role_targets=role_targets,
        road_business_role_task_mask=role_task_mask,
        road_ownership_sample_weights=ownership_weights,
        road_business_role_sample_weights=role_weights,
    )


def _segment_anchor_state(
    required: Sequence[tuple[str, str]],
    *,
    junction_cache: Mapping[
        tuple[str, str], ArchClosureJunctionCacheEntry
    ],
) -> tuple[int, tuple[str, ...]]:
    rows = [junction_cache.get(key) for key in required]
    if not rows or any(
        row is None or row.business_state == ORDINARY_ANCHOR_UNRESOLVED
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


__all__ = [
    "ArchClosureBatch",
    "ArchClosureAccessInput",
    "ArchClosureBreakInput",
    "ArchClosureJunctionCacheEntry",
    "ArchClosureJunctionRecord",
    "ArchClosureModelInput",
    "ArchClosureOrdinaryInput",
    "ArchClosurePlanRecord",
    "ArchClosureReferenceStores",
    "ArchClosureSegmentContextBatch",
    "ArchClosureSegmentRecord",
    "ArchClosureStructuredPlanInput",
    "JUNCTION_CONFIDENCE_DIM",
    "build_arch_closure_reference_stores",
    "collate_arch_closure_batch",
    "move_arch_closure_batch",
    "read_arch_closure_junction_cache",
]
