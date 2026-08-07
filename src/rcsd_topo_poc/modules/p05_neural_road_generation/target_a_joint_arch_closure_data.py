from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_graph import (
    AnchorDependencyGroup,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_data import (
    ArchClosureBatch,
    ArchClosureReferenceStores,
    ArchClosureSegmentContextBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
    ORDINARY_ANCHOR_SUCCESS,
    ORDINARY_ANCHOR_UNRESOLVED,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
    hierarchical_anchor_selection_logits,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_data import (
    _anchor_candidate_relation,
)


@dataclass(frozen=True)
class JointArchClosureComponent:
    case_key: str
    fold: int
    segment_keys: tuple[tuple[str, str], ...]
    junction_keys: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.segment_keys and not self.junction_keys:
            raise ValueError("joint architecture component is empty")
        keys = (*self.segment_keys, *self.junction_keys)
        if any(key[0] != self.case_key for key in keys):
            raise ValueError("joint architecture component crosses Cases")


@dataclass(frozen=True)
class LiveJunctionBatch:
    keys: tuple[tuple[str, str], ...]
    business_states: torch.Tensor
    candidate_ids: tuple[str, ...]
    embeddings: torch.Tensor
    confidence_values: torch.Tensor
    selected_candidate_indices: torch.Tensor

    def __post_init__(self) -> None:
        count = len(self.keys)
        if len(set(self.keys)) != count:
            raise ValueError("live Junction output repeats an identity")
        if (
            self.business_states.shape != (count,)
            or len(self.candidate_ids) != count
            or self.embeddings.ndim != 2
            or self.embeddings.shape[0] != count
            or self.confidence_values.shape != (count, 4)
            or self.selected_candidate_indices.shape != (count,)
        ):
            raise ValueError("live Junction output shape differs")


def build_joint_arch_closure_components(
    stores: ArchClosureReferenceStores,
) -> tuple[JointArchClosureComponent, ...]:
    """Build direct business-dependency components without fallback closure."""

    adjacency: dict[tuple[str, str, str], set[tuple[str, str, str]]] = (
        defaultdict(set)
    )
    for key in stores.segments:
        adjacency[("S", *key)]
    for key in stores.junctions:
        adjacency[("J", *key)]
    for key, segment in stores.segments.items():
        segment_node = ("S", *key)
        for junction_key in segment.required_junction_keys:
            junction_node = ("J", *junction_key)
            adjacency[segment_node].add(junction_node)
            adjacency[junction_node].add(segment_node)

    seen: set[tuple[str, str, str]] = set()
    components: list[JointArchClosureComponent] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        segment_keys: list[tuple[str, str]] = []
        junction_keys: list[tuple[str, str]] = []
        while stack:
            node = stack.pop()
            key = (node[1], node[2])
            if node[0] == "S":
                segment_keys.append(key)
            else:
                junction_keys.append(key)
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        all_keys = (*segment_keys, *junction_keys)
        case_keys = {key[0] for key in all_keys}
        if len(case_keys) != 1:
            raise ValueError("joint architecture component crosses Case boundary")
        folds = {
            stores.segments[key].example.fold for key in segment_keys
        } | {stores.junctions[key].example.fold for key in junction_keys}
        if len(folds) != 1:
            raise ValueError("joint architecture component crosses Case fold")
        components.append(
            JointArchClosureComponent(
                case_key=next(iter(case_keys)),
                fold=next(iter(folds)),
                segment_keys=tuple(sorted(segment_keys)),
                junction_keys=tuple(sorted(junction_keys)),
            )
        )
    return tuple(
        sorted(
            components,
            key=lambda row: (
                row.fold,
                row.case_key,
                row.segment_keys,
                row.junction_keys,
            ),
        )
    )


def decode_live_junction_batch(
    outputs: Mapping[str, torch.Tensor],
    groups: Sequence[AnchorDependencyGroup],
    tensors: TargetABatchTensors,
    config: TargetAConfig,
    *,
    teacher_forcing: bool,
    no_evidence_threshold: float = 0.5,
) -> LiveJunctionBatch:
    """Commit one unique anchor result before the Segment decoder runs."""

    if not groups:
        raise ValueError("live Junction decode lacks groups")
    status_probabilities = torch.softmax(outputs["anchor_status_logits"], dim=-1)
    candidate_logits = outputs["anchor_candidate_logits"]
    if config.hierarchical_anchor_decoder:
        candidate_logits = hierarchical_anchor_selection_logits(
            candidate_logits,
            outputs["anchor_type_logits"],
            tensors,
            cardinality_logits=(
                outputs.get("anchor_cardinality_logits")
                if config.anchor_cardinality_hard_lock
                else None
            ),
            hard_type_lock=config.anchor_type_hard_lock,
            type_prior_weight=config.anchor_type_prior_weight,
        )
    candidate_probabilities = torch.softmax(candidate_logits, dim=-1)
    model_selected = candidate_logits.argmax(dim=-1)[:, 0]
    gate_logits = outputs.get("anchor_gate_logits")
    gate_probabilities = (
        torch.softmax(gate_logits, dim=-1)[..., 1][:, 0]
        if gate_logits is not None
        else torch.ones_like(model_selected, dtype=status_probabilities.dtype)
    )
    model_status = status_probabilities[:, 0].argmax(dim=-1)
    selected_indices = model_selected.clone()
    states: list[int] = []
    candidate_ids: list[str] = []
    keys: list[tuple[str, str]] = []
    for index, group in enumerate(groups):
        focal = group.examples[0]
        keys.append((focal.case_key, focal.anchor_id))
        state, selected_index = _committed_anchor_decision(
            focal,
            model_status=int(model_status[index].item()),
            model_selected=int(model_selected[index].item()),
            gate_probability=float(gate_probabilities[index].item()),
            no_evidence_probability=float(
                status_probabilities[
                    index,
                    0,
                    ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE],
                ].item()
            ),
            teacher_forcing=teacher_forcing,
            gate_threshold=config.anchor_gate_pass_threshold,
            no_evidence_threshold=no_evidence_threshold,
        )
        selected_indices[index] = selected_index
        states.append(state)
        candidate_ids.append(
            focal.candidate_ids[selected_index]
            if state == ORDINARY_ANCHOR_SUCCESS
            else ""
        )

    row_indices = torch.arange(
        len(groups), device=outputs["object_embeddings"].device
    )
    object_indices = tensors.anchor_object_indices[:, 0].clamp_min(0)
    embeddings = outputs["object_embeddings"][row_indices, object_indices]
    selected_probabilities = candidate_probabilities[:, 0].gather(
        1, selected_indices.unsqueeze(-1)
    ).squeeze(-1)
    confidence = torch.stack(
        (
            status_probabilities[
                :, 0, ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
            ],
            status_probabilities[
                :, 0, ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
            ],
            gate_probabilities,
            selected_probabilities,
        ),
        dim=-1,
    )
    return LiveJunctionBatch(
        keys=tuple(keys),
        business_states=torch.tensor(
            states,
            dtype=torch.long,
            device=embeddings.device,
        ),
        candidate_ids=tuple(candidate_ids),
        embeddings=embeddings,
        confidence_values=confidence,
        selected_candidate_indices=selected_indices,
    )


def bind_live_junctions(
    batch: ArchClosureBatch,
    stores: ArchClosureReferenceStores,
    live: LiveJunctionBatch,
) -> ArchClosureBatch:
    """Replace shape-only cache values with live, committed Junction outputs."""

    live_index = {key: index for index, key in enumerate(live.keys)}
    maximum_junctions = batch.context.junction_mask.shape[1]
    index_values = torch.zeros(
        (len(batch.keys), maximum_junctions),
        dtype=torch.long,
        device=live.embeddings.device,
    )
    mask = torch.zeros_like(index_values, dtype=torch.bool)
    segment_states: list[int] = []
    selected_by_segment: list[tuple[str, ...]] = []
    for row_index, key in enumerate(batch.keys):
        required = stores.segments[key].required_junction_keys
        if len(required) > maximum_junctions:
            raise ValueError("live Junction binding exceeds collated shape")
        missing = [junction for junction in required if junction not in live_index]
        if missing:
            raise ValueError(f"live Junction binding is incomplete: {key}/{missing}")
        for junction_index, junction_key in enumerate(required):
            index_values[row_index, junction_index] = live_index[junction_key]
            mask[row_index, junction_index] = True
        state, selected = _segment_live_state(required, live, live_index)
        segment_states.append(state)
        selected_by_segment.append(selected)

    embeddings = live.embeddings[index_values] * mask.unsqueeze(-1)
    confidence = live.confidence_values[index_values] * mask.unsqueeze(-1)
    states = live.business_states[index_values]
    states = torch.where(
        mask,
        states,
        torch.full_like(states, ORDINARY_ANCHOR_UNRESOLVED),
    )
    context = ArchClosureSegmentContextBatch(
        focal_feature_values=batch.context.focal_feature_values,
        peer_feature_values=batch.context.peer_feature_values,
        peer_mask=batch.context.peer_mask,
        junction_embedding_values=embeddings,
        junction_confidence_values=confidence,
        junction_state_values=states,
        junction_mask=mask,
        peer_junction_relation_mask=(
            batch.context.peer_junction_relation_mask
        ),
    )

    anchor_state = batch.ordinary.side_precomputed_anchor_state.clone()
    anchor_state[:, 0] = torch.tensor(
        segment_states,
        dtype=torch.long,
        device=anchor_state.device,
    )
    anchor_context = torch.zeros_like(
        batch.ordinary.side_precomputed_anchor_context
    )
    for batch_index, (key, selected) in enumerate(
        zip(batch.keys, selected_by_segment, strict=True)
    ):
        if not selected:
            continue
        pool = stores.plans[key].road_pool
        for road_index in range(len(pool.road_ids)):
            relations = torch.tensor(
                [
                    _anchor_candidate_relation(
                        pool,
                        road_index=road_index,
                        candidate_id=candidate_id,
                    )
                    for candidate_id in selected
                ],
                dtype=anchor_context.dtype,
                device=anchor_context.device,
            )
            anchor_context[batch_index, 0, road_index] = torch.cat(
                (relations.mean(dim=0), relations.amax(dim=0))
            )
    ordinary = replace(
        batch.ordinary,
        side_precomputed_anchor_context=anchor_context,
        side_precomputed_anchor_state=anchor_state,
    )
    model_ordinary = replace(
        batch.model_input.ordinary,
        side_precomputed_anchor_context=anchor_context,
        side_precomputed_anchor_state=anchor_state,
    )
    model_input = replace(
        batch.model_input,
        context=context,
        ordinary=model_ordinary,
    )
    return replace(
        batch,
        context=context,
        ordinary=ordinary,
        model_input=model_input,
    )


def _committed_anchor_decision(
    focal: Any,
    *,
    model_status: int,
    model_selected: int,
    gate_probability: float,
    no_evidence_probability: float,
    teacher_forcing: bool,
    gate_threshold: float,
    no_evidence_threshold: float,
) -> tuple[int, int]:
    selected = model_selected
    if teacher_forcing and focal.status_supervised:
        label = list(AnchorStatus)[focal.status_label]
        if label is AnchorStatus.SUCCESS:
            if focal.preferred_candidate_index >= 0:
                selected = focal.preferred_candidate_index
            elif focal.candidate_acceptable_indices:
                selected = focal.candidate_acceptable_indices[0]
            else:
                return ORDINARY_ANCHOR_UNRESOLVED, selected
            return ORDINARY_ANCHOR_SUCCESS, selected
        if label is AnchorStatus.NO_EVIDENCE:
            return ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE, selected
        return ORDINARY_ANCHOR_UNRESOLVED, selected
    if (
        model_status == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
        and gate_probability >= gate_threshold
    ):
        return ORDINARY_ANCHOR_SUCCESS, selected
    if (
        model_status == ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
        and no_evidence_probability >= no_evidence_threshold
        and gate_probability >= gate_threshold
    ):
        return ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE, selected
    return ORDINARY_ANCHOR_UNRESOLVED, selected


def _segment_live_state(
    required: Sequence[tuple[str, str]],
    live: LiveJunctionBatch,
    live_index: Mapping[tuple[str, str], int],
) -> tuple[int, tuple[str, ...]]:
    if not required:
        return ORDINARY_ANCHOR_UNRESOLVED, ()
    indices = [live_index[key] for key in required]
    states = [int(live.business_states[index].item()) for index in indices]
    if ORDINARY_ANCHOR_UNRESOLVED in states:
        return ORDINARY_ANCHOR_UNRESOLVED, ()
    if ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE in states:
        return ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE, ()
    candidate_ids = tuple(live.candidate_ids[index] for index in indices)
    if any(not candidate_id for candidate_id in candidate_ids):
        return ORDINARY_ANCHOR_UNRESOLVED, ()
    return ORDINARY_ANCHOR_SUCCESS, candidate_ids


__all__ = [
    "JointArchClosureComponent",
    "LiveJunctionBatch",
    "bind_live_junctions",
    "build_joint_arch_closure_components",
    "decode_live_junction_batch",
]
