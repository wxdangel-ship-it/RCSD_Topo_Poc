from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_evidence import (
    ANCHOR_ARM_FEATURE_DIM,
    ANCHOR_MEMBER_INCIDENCE_DIM,
    ANCHOR_MEMBER_RELATION_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_RELATION_DIM,
    GEOMETRY_ROLE_INDEX,
    GEOMETRY_TOKEN_DIM,
    GEOMETRY_RADIUS_M,
    MEMBER_FEATURE_DIM,
    OBJECT_FEATURE_DIM,
    SURFACE_GRID_HALF_EXTENT_M,
    SURFACE_GRID_SIZE,
    audit_junction_joint_feature_rows,
)


MAX_BREAKS_PER_ROAD = 2
OBJECT_ROLE_INDICES = (
    GEOMETRY_ROLE_INDEX["RCSD_NODE"],
    GEOMETRY_ROLE_INDEX["RCSD_ROAD"],
)
VIRTUAL_SURFACE_CARRIER_ROLE_INDICES = (
    GEOMETRY_ROLE_INDEX["SWSD_ROAD"],
    GEOMETRY_ROLE_INDEX["RCSD_ROAD"],
    GEOMETRY_ROLE_INDEX["DRIVEZONE"],
    GEOMETRY_ROLE_INDEX["DIVSTRIP"],
    GEOMETRY_ROLE_INDEX["RCSD_INTERSECTION"],
)

TASK_CLASSES: Mapping[str, tuple[str, ...]] = {
    "t07_step1": ("no", "yes"),
    "t07_step2": ("no", "yes", "fail1", "fail2"),
    "surface_mode": (
        "EXISTING_RCSD_INTERSECTION",
        "VIRTUAL_SURFACE",
        "NO_VALID_SURFACE",
        "AMBIGUOUS",
    ),
    "surface_state": ("accepted", "rejected", "runtime_failed"),
    "relation_state": (
        "geometry_not_accepted",
        "no_related_rcsd",
        "rcsd_present_not_junction",
        "runtime_failed",
        "success_offset_fact_with_rcsd_junction",
        "success_required_rcsd_junction",
        "existing_rcsdintersection_matched",
        "intersection_shared_by_multiple_groups",
        "multiple_intersections_for_group",
        "no_existing_rcsdintersection",
        "rcsdintersection_no_rcsd_semantic_node",
        "t_junction_not_strict_single_surface",
        "t_junction_surface_contains_other_swsd_semantic_junction",
        "t_junction_surface_multiple_rcsd_semantic_nodes",
        "t_junction_surface_no_rcsd_semantic_node",
    ),
    "junctionization_action": (
        "direct_relation",
        "failure_relation",
        "group_existing_rcsd_nodes",
        "split_rcsdroad_generate_rcsdnode",
    ),
    "final_state": (
        "SUCCESS",
        "NO_RCSD_EVIDENCE",
        "QUALITY_ISSUE",
    ),
}
TASK_INDEX: Mapping[str, Mapping[str, int]] = {
    task: {value: index for index, value in enumerate(values)}
    for task, values in TASK_CLASSES.items()
}


@dataclass(frozen=True)
class GeometryObject:
    object_id: str
    role_index: int
    token_start: int
    token_end: int
    geometry_valid: bool
    anchor_projection_fraction: float
    length_m: float


@dataclass(frozen=True)
class RoadBreakTarget:
    object_index: int
    fraction: float
    road_length_m: float
    is_selected_main: bool


@dataclass(frozen=True)
class JunctionJointExample:
    sample_id: str
    anchor_id: str
    split: str
    supervision_source: str
    supervision_group: str
    sample_weight: float
    object_features: torch.Tensor
    candidate_ids: tuple[str, ...]
    candidate_features: torch.Tensor
    member_ids: tuple[str, ...]
    member_features: torch.Tensor
    swsd_arm_features: torch.Tensor
    member_arm_features: tuple[torch.Tensor, ...]
    member_relation_edges: tuple[tuple[int, int, tuple[float, ...]], ...]
    member_incidence_edges: tuple[tuple[int, int, tuple[float, ...]], ...]
    geometry_tokens: torch.Tensor
    geometry_objects: tuple[GeometryObject, ...]
    geometry_relation_edges: tuple[tuple[int, int, tuple[float, ...]], ...]
    drivezone_grid: torch.Tensor
    task_labels: Mapping[str, int]
    task_masks: Mapping[str, bool]
    candidate_acceptable_indices: tuple[int, ...]
    candidate_supervised: bool
    member_acceptable_sets: tuple[tuple[int, ...], ...]
    member_supervised: bool
    object_acceptable_sets: tuple[tuple[int, ...], ...]
    object_supervision_roles: tuple[int, ...]
    object_supervised: bool
    surface_object_acceptable_sets: tuple[tuple[int, ...], ...]
    surface_object_supervised: bool
    virtual_surface_carrier_acceptable_sets: tuple[tuple[int, ...], ...]
    virtual_surface_carrier_supervised: bool
    surface_target: torch.Tensor
    surface_supervised: bool
    road_break_targets: tuple[RoadBreakTarget, ...]
    main_object_index: int | None
    complete_junction_supervised: bool
    topology_geometry_supervised: bool


@dataclass(frozen=True)
class JunctionJointBatch:
    sample_ids: tuple[str, ...]
    splits: tuple[str, ...]
    supervision_sources: tuple[str, ...]
    supervision_groups: tuple[str, ...]
    sample_weights: torch.Tensor
    object_features: torch.Tensor
    candidate_features: torch.Tensor
    candidate_mask: torch.Tensor
    candidate_acceptable: torch.Tensor
    candidate_task_mask: torch.Tensor
    member_features: torch.Tensor
    member_mask: torch.Tensor
    swsd_arm_features: torch.Tensor
    swsd_arm_mask: torch.Tensor
    member_arm_features: torch.Tensor
    member_arm_mask: torch.Tensor
    member_relation_features: torch.Tensor
    member_relation_mask: torch.Tensor
    member_incidence_features: torch.Tensor
    member_incidence_mask: torch.Tensor
    member_acceptable_sets: torch.Tensor
    member_acceptable_set_mask: torch.Tensor
    member_task_mask: torch.Tensor
    geometry_tokens: torch.Tensor
    geometry_token_mask: torch.Tensor
    geometry_token_object_index: torch.Tensor
    geometry_object_mask: torch.Tensor
    geometry_object_roles: torch.Tensor
    geometry_object_member_index: torch.Tensor
    geometry_object_anchor_projection_fraction: torch.Tensor
    geometry_object_length_m: torch.Tensor
    geometry_relation_index: torch.Tensor
    geometry_relation_features: torch.Tensor
    geometry_relation_mask: torch.Tensor
    selectable_object_mask: torch.Tensor
    object_supervision_mask: torch.Tensor
    object_role_task_mask: torch.Tensor
    object_acceptable_sets: torch.Tensor
    object_acceptable_set_mask: torch.Tensor
    object_task_mask: torch.Tensor
    surface_object_acceptable_sets: torch.Tensor
    surface_object_acceptable_set_mask: torch.Tensor
    surface_object_task_mask: torch.Tensor
    virtual_surface_carrier_acceptable_sets: torch.Tensor
    virtual_surface_carrier_acceptable_set_mask: torch.Tensor
    virtual_surface_carrier_task_mask: torch.Tensor
    step1_tokens: torch.Tensor
    step1_token_mask: torch.Tensor
    step2_tokens: torch.Tensor
    step2_token_mask: torch.Tensor
    drivezone_grid: torch.Tensor
    surface_targets: torch.Tensor
    surface_task_mask: torch.Tensor
    break_fraction_targets: torch.Tensor
    break_road_length_m: torch.Tensor
    break_target_mask: torch.Tensor
    break_main_mask: torch.Tensor
    main_object_target: torch.Tensor
    main_object_task_mask: torch.Tensor
    break_main_task_mask: torch.Tensor
    complete_junction_task_mask: torch.Tensor
    topology_geometry_task_mask: torch.Tensor
    task_labels: Mapping[str, torch.Tensor]
    task_masks: Mapping[str, torch.Tensor]

    def to(self, device: torch.device | str) -> JunctionJointBatch:
        values: dict[str, Any] = {}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, torch.Tensor):
                values[name] = value.to(device)
            elif isinstance(value, Mapping):
                values[name] = {
                    key: item.to(device) if isinstance(item, torch.Tensor) else item
                    for key, item in value.items()
                }
            else:
                values[name] = value
        return JunctionJointBatch(**values)


def virtual_surface_carrier_candidate_mask(
    batch: JunctionJointBatch,
    *,
    limit: int = 64,
) -> torch.Tensor:
    """Keep the nearest inference-evidence carrier objects without Gold access."""
    if limit < 1:
        raise ValueError("virtual surface carrier candidate limit is invalid")
    result = torch.zeros_like(batch.geometry_object_mask)
    allowed = torch.zeros_like(batch.geometry_object_mask)
    for role_index in VIRTUAL_SURFACE_CARRIER_ROLE_INDICES:
        allowed |= batch.geometry_object_roles.eq(role_index)
    allowed &= batch.geometry_object_mask
    maximum = torch.finfo(batch.geometry_tokens.dtype).max
    for row_index in range(batch.geometry_tokens.shape[0]):
        candidates = allowed[row_index].nonzero(as_tuple=False).flatten()
        if candidates.numel() == 0:
            continue
        distances = torch.full(
            (candidates.numel(),),
            maximum,
            dtype=batch.geometry_tokens.dtype,
            device=batch.geometry_tokens.device,
        )
        for rank, object_index in enumerate(candidates):
            token_mask = (
                batch.geometry_token_mask[row_index]
                & batch.geometry_token_object_index[row_index].eq(object_index)
            )
            if bool(token_mask.any()):
                relative_xy = batch.geometry_tokens[row_index, token_mask, 7:9]
                distances[rank] = relative_xy.square().sum(dim=-1).min()
        selected = candidates[distances.argsort()[:limit]]
        result[row_index, selected] = True
    return result


def relation_candidate_constraints(
    batch: JunctionJointBatch,
    action_indices: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Apply only the object-kind and cardinality invariants of each model action."""
    batch_size = batch.geometry_object_mask.shape[0]
    if action_indices.shape != (batch_size,):
        raise ValueError("junction relation action index shape differs")
    if action_indices.dtype not in {torch.int32, torch.int64}:
        raise ValueError("junction relation action indices must be integral")
    if bool(
        (
            (action_indices < 0)
            | (action_indices >= len(TASK_CLASSES["junctionization_action"]))
        ).any()
    ):
        raise ValueError("junction relation action index is invalid")

    selectable = batch.selectable_object_mask & batch.geometry_object_mask
    node_mask = selectable & batch.geometry_object_roles.eq(
        GEOMETRY_ROLE_INDEX["RCSD_NODE"]
    )
    road_mask = selectable & batch.geometry_object_roles.eq(
        GEOMETRY_ROLE_INDEX["RCSD_ROAD"]
    )
    candidate_mask = torch.zeros_like(selectable)
    minimum = torch.zeros(batch_size, dtype=torch.long, device=selectable.device)
    maximum = torch.zeros_like(minimum)
    feasible = torch.ones(batch_size, dtype=torch.bool, device=selectable.device)
    action_index = TASK_INDEX["junctionization_action"]
    for row_index in range(batch_size):
        action = int(action_indices[row_index])
        if action == action_index["failure_relation"]:
            continue
        if action in {
            action_index["direct_relation"],
            action_index["group_existing_rcsd_nodes"],
        }:
            allowed = node_mask[row_index]
        else:
            allowed = road_mask[row_index]
        available = int(allowed.sum())
        required = (
            2
            if action == action_index["group_existing_rcsd_nodes"]
            else 1
        )
        if available < required:
            feasible[row_index] = False
            continue
        candidate_mask[row_index] = allowed
        minimum[row_index] = required
        maximum[row_index] = (
            1
            if action == action_index["direct_relation"]
            else available
        )
    return candidate_mask, minimum, maximum, feasible


def virtual_surface_carrier_object_grid(
    batch: JunctionJointBatch,
    *,
    dilation_cells: int = 2,
) -> torch.Tensor:
    """Rasterize candidate carrier token traces for objective-aligned training."""
    if dilation_cells < 0:
        raise ValueError("virtual surface carrier dilation is invalid")
    candidate_mask = virtual_surface_carrier_candidate_mask(batch)
    batch_size, object_count = candidate_mask.shape
    normalized = batch.geometry_tokens[..., 7:9] * (
        GEOMETRY_RADIUS_M / SURFACE_GRID_HALF_EXTENT_M
    )
    inside = normalized.abs().le(1.0).all(dim=-1) & batch.geometry_token_mask
    object_index = batch.geometry_token_object_index
    safe_object_index = object_index.clamp_min(0)
    inside &= object_index.ge(0) & candidate_mask.gather(1, safe_object_index)
    cells = (((normalized + 1.0) * 0.5) * SURFACE_GRID_SIZE).floor().long()
    cells = cells.clamp(0, SURFACE_GRID_SIZE - 1)
    batch_index = torch.arange(
        batch_size,
        device=batch.geometry_tokens.device,
    ).unsqueeze(1).expand_as(object_index)
    flat = (
        (
            batch_index * object_count + safe_object_index
        )
        * SURFACE_GRID_SIZE
        * SURFACE_GRID_SIZE
        + cells[..., 1] * SURFACE_GRID_SIZE
        + cells[..., 0]
    )
    grid = batch.geometry_tokens.new_zeros(
        batch_size * object_count * SURFACE_GRID_SIZE * SURFACE_GRID_SIZE
    )
    grid.scatter_add_(
        0,
        flat.reshape(-1),
        inside.reshape(-1).to(grid.dtype),
    )
    grid = grid.reshape(
        batch_size * object_count,
        1,
        SURFACE_GRID_SIZE,
        SURFACE_GRID_SIZE,
    ).clamp_max(1.0)
    if dilation_cells:
        kernel = 2 * dilation_cells + 1
        grid = torch.nn.functional.max_pool2d(
            grid,
            kernel_size=kernel,
            stride=1,
            padding=dilation_cells,
        )
    return grid.reshape(
        batch_size,
        object_count,
        SURFACE_GRID_SIZE,
        SURFACE_GRID_SIZE,
    )


def read_junction_joint_examples(
    store_root: Path,
    *,
    splits: Iterable[str] | None = None,
) -> tuple[JunctionJointExample, ...]:
    root = Path(store_root).resolve(strict=True)
    feature_paths = _store_paths(
        root / "inference_feature_store/junction_features.jsonl"
    )
    label_paths = _store_paths(root / "training_label_store/junction_labels.jsonl")
    lineage_paths = _store_paths(root / "lineage_store/junction_lineage.jsonl")
    if len(feature_paths) > 1 and not (
        {path.name for path in feature_paths}
        == {path.name for path in label_paths}
        == {path.name for path in lineage_paths}
    ):
        raise ValueError("junction joint case shard scopes differ")
    allowed = None if splits is None else {str(value) for value in splits}

    labels = _index_rows(label_paths)
    lineage = _index_rows(lineage_paths)
    if set(labels) != set(lineage):
        raise ValueError("junction joint label and lineage scopes differ")

    examples: list[JunctionJointExample] = []
    seen: set[str] = set()
    for feature in _read_jsonl_paths(feature_paths):
        sample_id = str(feature["sample_id"])
        if sample_id in seen or sample_id not in labels:
            raise ValueError("junction joint feature scope is not one-to-one")
        seen.add(sample_id)
        leakage = audit_junction_joint_feature_rows((feature,))
        if not leakage["passed"]:
            raise ValueError(f"junction inference feature leakage: {leakage}")
        label = labels[sample_id]
        if str(label["split"]) != str(lineage[sample_id]["split"]):
            raise ValueError("junction joint split differs between label and lineage")
        if allowed is None or str(label["split"]) in allowed:
            examples.append(_example(feature, label, lineage[sample_id]))
    if seen != set(labels):
        raise ValueError("junction joint feature and label scopes differ")
    return tuple(examples)


def collate_junction_joint(
    examples: Sequence[JunctionJointExample],
) -> JunctionJointBatch:
    if not examples:
        raise ValueError("junction joint batch is empty")
    batch_size = len(examples)
    max_candidates = max(1, max(len(row.candidate_ids) for row in examples))
    max_members = max(1, max(len(row.member_ids) for row in examples))
    max_swsd_arms = max(1, max(row.swsd_arm_features.shape[0] for row in examples))
    max_member_arms = max(
        1,
        max(
            (features.shape[0] for row in examples for features in row.member_arm_features),
            default=0,
        ),
    )
    max_tokens = max(row.geometry_tokens.shape[0] for row in examples)
    max_objects = max(len(row.geometry_objects) for row in examples)
    max_geometry_relations = max(
        1,
        max(len(row.geometry_relation_edges) for row in examples),
    )
    max_candidate_options = 1
    max_member_options = max(1, max(len(row.member_acceptable_sets) for row in examples))
    max_object_options = max(1, max(len(row.object_acceptable_sets) for row in examples))
    max_surface_object_options = max(
        1,
        max(len(row.surface_object_acceptable_sets) for row in examples),
    )
    max_virtual_surface_carrier_options = max(
        1,
        max(
            len(row.virtual_surface_carrier_acceptable_sets) for row in examples
        ),
    )
    max_step1 = max(1, max(_role_token_count(row, "DRIVEZONE") for row in examples))
    max_step2 = max(
        1,
        max(_role_token_count(row, "RCSD_INTERSECTION") for row in examples),
    )

    objects = torch.stack([row.object_features for row in examples])
    candidates = torch.zeros(batch_size, max_candidates, OBJECT_FEATURE_DIM)
    candidate_mask = torch.zeros(batch_size, max_candidates, dtype=torch.bool)
    candidate_acceptable = torch.zeros(
        batch_size,
        max_candidate_options,
        max_candidates,
        dtype=torch.bool,
    )
    members = torch.zeros(batch_size, max_members, MEMBER_FEATURE_DIM)
    member_mask = torch.zeros(batch_size, max_members, dtype=torch.bool)
    swsd_arms = torch.zeros(batch_size, max_swsd_arms, ANCHOR_ARM_FEATURE_DIM)
    swsd_arm_mask = torch.zeros(batch_size, max_swsd_arms, dtype=torch.bool)
    member_arms = torch.zeros(
        batch_size,
        max_members,
        max_member_arms,
        ANCHOR_ARM_FEATURE_DIM,
    )
    member_arm_mask = torch.zeros(
        batch_size,
        max_members,
        max_member_arms,
        dtype=torch.bool,
    )
    member_relations = torch.zeros(
        batch_size,
        max_members,
        max_members,
        ANCHOR_MEMBER_RELATION_DIM,
    )
    member_relation_mask = torch.zeros(
        batch_size,
        max_members,
        max_members,
        dtype=torch.bool,
    )
    member_incidence = torch.zeros(
        batch_size,
        max_members,
        max_members,
        ANCHOR_MEMBER_INCIDENCE_DIM,
    )
    member_incidence_mask = torch.zeros(
        batch_size,
        max_members,
        max_members,
        dtype=torch.bool,
    )
    member_sets = torch.zeros(
        batch_size,
        max_member_options,
        max_members,
        dtype=torch.bool,
    )
    member_set_mask = torch.zeros(batch_size, max_member_options, dtype=torch.bool)
    tokens = torch.zeros(batch_size, max_tokens, GEOMETRY_TOKEN_DIM)
    token_mask = torch.zeros(batch_size, max_tokens, dtype=torch.bool)
    token_object_index = torch.full((batch_size, max_tokens), -1, dtype=torch.long)
    geometry_object_mask = torch.zeros(batch_size, max_objects, dtype=torch.bool)
    geometry_object_roles = torch.full((batch_size, max_objects), -1, dtype=torch.long)
    geometry_object_member_index = torch.full(
        (batch_size, max_objects),
        -1,
        dtype=torch.long,
    )
    geometry_object_anchor_projection = torch.zeros(batch_size, max_objects)
    geometry_object_length = torch.zeros(batch_size, max_objects)
    geometry_relation_index = torch.zeros(
        batch_size,
        max_geometry_relations,
        2,
        dtype=torch.long,
    )
    geometry_relation_features = torch.zeros(
        batch_size,
        max_geometry_relations,
        GEOMETRY_RELATION_DIM,
    )
    geometry_relation_mask = torch.zeros(
        batch_size,
        max_geometry_relations,
        dtype=torch.bool,
    )
    selectable = torch.zeros(batch_size, max_objects, dtype=torch.bool)
    object_supervision = torch.zeros(batch_size, max_objects, dtype=torch.bool)
    object_sets = torch.zeros(
        batch_size,
        max_object_options,
        max_objects,
        dtype=torch.bool,
    )
    object_set_mask = torch.zeros(batch_size, max_object_options, dtype=torch.bool)
    surface_object_sets = torch.zeros(
        batch_size,
        max_surface_object_options,
        max_objects,
        dtype=torch.bool,
    )
    surface_object_set_mask = torch.zeros(
        batch_size,
        max_surface_object_options,
        dtype=torch.bool,
    )
    virtual_surface_carrier_sets = torch.zeros(
        batch_size,
        max_virtual_surface_carrier_options,
        max_objects,
        dtype=torch.bool,
    )
    virtual_surface_carrier_set_mask = torch.zeros(
        batch_size,
        max_virtual_surface_carrier_options,
        dtype=torch.bool,
    )
    step1 = torch.zeros(batch_size, max_step1, GEOMETRY_TOKEN_DIM)
    step1_mask = torch.zeros(batch_size, max_step1, dtype=torch.bool)
    step2 = torch.zeros(batch_size, max_step2, GEOMETRY_TOKEN_DIM)
    step2_mask = torch.zeros(batch_size, max_step2, dtype=torch.bool)
    surfaces = torch.stack([row.surface_target for row in examples])
    drivezone_grids = torch.stack([row.drivezone_grid for row in examples])
    break_fractions = torch.zeros(batch_size, max_objects, MAX_BREAKS_PER_ROAD)
    break_road_length = torch.zeros(batch_size, max_objects)
    break_mask = torch.zeros(
        batch_size,
        max_objects,
        MAX_BREAKS_PER_ROAD,
        dtype=torch.bool,
    )
    break_main = torch.zeros_like(break_mask)
    main_object = torch.zeros(batch_size, max_objects, dtype=torch.bool)
    main_object_task = torch.zeros(batch_size, dtype=torch.bool)
    break_main_task = torch.zeros(batch_size, dtype=torch.bool)
    task_labels = {
        task: torch.full((batch_size,), -1, dtype=torch.long) for task in TASK_CLASSES
    }
    task_masks = {
        task: torch.zeros(batch_size, dtype=torch.bool) for task in TASK_CLASSES
    }

    for batch_index, row in enumerate(examples):
        candidate_count = row.candidate_features.shape[0]
        candidates[batch_index, :candidate_count] = row.candidate_features
        candidate_mask[batch_index, :candidate_count] = True
        for index in row.candidate_acceptable_indices:
            _require_index(index, candidate_count, "candidate")
            candidate_acceptable[batch_index, 0, index] = True

        member_count = row.member_features.shape[0]
        members[batch_index, :member_count] = row.member_features
        member_mask[batch_index, :member_count] = True
        swsd_arm_count = row.swsd_arm_features.shape[0]
        swsd_arms[batch_index, :swsd_arm_count] = row.swsd_arm_features
        swsd_arm_mask[batch_index, :swsd_arm_count] = True
        for member_index, arm_features in enumerate(row.member_arm_features):
            arm_count = arm_features.shape[0]
            member_arms[batch_index, member_index, :arm_count] = arm_features
            member_arm_mask[batch_index, member_index, :arm_count] = True
        for left, right, relation in row.member_relation_edges:
            _require_index(left, member_count, "member relation left")
            _require_index(right, member_count, "member relation right")
            if left == right or member_relation_mask[batch_index, left, right]:
                raise ValueError("junction member relation is repeated or self-linked")
            member_relations[batch_index, left, right] = torch.tensor(relation)
            member_relation_mask[batch_index, left, right] = True
        for left, right, incidence in row.member_incidence_edges:
            _require_index(left, member_count, "member incidence left")
            _require_index(right, member_count, "member incidence right")
            if left == right or member_incidence_mask[batch_index, left, right]:
                raise ValueError("junction member incidence is repeated or self-linked")
            member_incidence[batch_index, left, right] = torch.tensor(incidence)
            member_incidence_mask[batch_index, left, right] = True
        for option_index, option in enumerate(row.member_acceptable_sets):
            member_set_mask[batch_index, option_index] = True
            for index in option:
                _require_index(index, member_count, "member")
                member_sets[batch_index, option_index, index] = True

        token_count = row.geometry_tokens.shape[0]
        tokens[batch_index, :token_count] = row.geometry_tokens
        token_mask[batch_index, :token_count] = True
        member_index_by_id = {
            object_id: index for index, object_id in enumerate(row.member_ids)
        }
        for object_index, span in enumerate(row.geometry_objects):
            geometry_object_mask[batch_index, object_index] = True
            geometry_object_roles[batch_index, object_index] = span.role_index
            geometry_object_member_index[batch_index, object_index] = (
                member_index_by_id.get(span.object_id, -1)
            )
            geometry_object_anchor_projection[batch_index, object_index] = (
                span.anchor_projection_fraction
            )
            geometry_object_length[batch_index, object_index] = span.length_m
            selectable[batch_index, object_index] = span.role_index in {
                GEOMETRY_ROLE_INDEX["RCSD_NODE"],
                GEOMETRY_ROLE_INDEX["RCSD_ROAD"],
            }
            object_supervision[batch_index, object_index] = (
                span.role_index in row.object_supervision_roles
            )
            token_object_index[
                batch_index,
                span.token_start : span.token_end,
            ] = object_index
        if bool((token_object_index[batch_index, :token_count] < 0).any()):
            raise ValueError("junction geometry token has no object span")
        for edge_index, (left, right, features) in enumerate(
            row.geometry_relation_edges
        ):
            _require_index(left, len(row.geometry_objects), "geometry relation left")
            _require_index(right, len(row.geometry_objects), "geometry relation right")
            geometry_relation_index[batch_index, edge_index] = torch.tensor(
                (left, right),
                dtype=torch.long,
            )
            geometry_relation_features[batch_index, edge_index] = torch.tensor(
                features,
                dtype=torch.float32,
            )
            geometry_relation_mask[batch_index, edge_index] = True
        for option_index, option in enumerate(row.object_acceptable_sets):
            object_set_mask[batch_index, option_index] = True
            for index in option:
                _require_index(index, len(row.geometry_objects), "raw object")
                object_sets[batch_index, option_index, index] = True
        for option_index, option in enumerate(row.surface_object_acceptable_sets):
            surface_object_set_mask[batch_index, option_index] = True
            for index in option:
                _require_index(index, len(row.geometry_objects), "surface object")
                surface_object_sets[batch_index, option_index, index] = True
        for option_index, option in enumerate(
            row.virtual_surface_carrier_acceptable_sets
        ):
            virtual_surface_carrier_set_mask[batch_index, option_index] = True
            for index in option:
                _require_index(
                    index,
                    len(row.geometry_objects),
                    "virtual surface carrier",
                )
                virtual_surface_carrier_sets[
                    batch_index,
                    option_index,
                    index,
                ] = True

        _copy_role_tokens(row, "DRIVEZONE", step1, step1_mask, batch_index)
        _copy_role_tokens(
            row,
            "RCSD_INTERSECTION",
            step2,
            step2_mask,
            batch_index,
        )
        breaks_by_object: dict[int, list[RoadBreakTarget]] = {}
        for target in row.road_break_targets:
            breaks_by_object.setdefault(target.object_index, []).append(target)
        for object_index, targets in breaks_by_object.items():
            if len(targets) > MAX_BREAKS_PER_ROAD:
                raise ValueError("junction Road break Gold exceeds decoder capacity")
            for rank, target in enumerate(sorted(targets, key=lambda value: value.fraction)):
                break_fractions[batch_index, object_index, rank] = target.fraction
                break_road_length[batch_index, object_index] = target.road_length_m
                break_mask[batch_index, object_index, rank] = True
                break_main[batch_index, object_index, rank] = target.is_selected_main
        if row.main_object_index is not None:
            _require_index(row.main_object_index, len(row.geometry_objects), "main object")
            main_object[batch_index, row.main_object_index] = True
            main_object_task[batch_index] = True
        break_main_task[batch_index] = any(
            target.is_selected_main for target in row.road_break_targets
        )
        for task in TASK_CLASSES:
            task_labels[task][batch_index] = int(row.task_labels[task])
            task_masks[task][batch_index] = bool(row.task_masks[task])

    return JunctionJointBatch(
        sample_ids=tuple(row.sample_id for row in examples),
        splits=tuple(row.split for row in examples),
        supervision_sources=tuple(row.supervision_source for row in examples),
        supervision_groups=tuple(row.supervision_group for row in examples),
        sample_weights=torch.tensor([row.sample_weight for row in examples]),
        object_features=objects,
        candidate_features=candidates,
        candidate_mask=candidate_mask,
        candidate_acceptable=candidate_acceptable,
        candidate_task_mask=torch.tensor(
            [row.candidate_supervised for row in examples], dtype=torch.bool
        ),
        member_features=members,
        member_mask=member_mask,
        swsd_arm_features=swsd_arms,
        swsd_arm_mask=swsd_arm_mask,
        member_arm_features=member_arms,
        member_arm_mask=member_arm_mask,
        member_relation_features=member_relations,
        member_relation_mask=member_relation_mask,
        member_incidence_features=member_incidence,
        member_incidence_mask=member_incidence_mask,
        member_acceptable_sets=member_sets,
        member_acceptable_set_mask=member_set_mask,
        member_task_mask=torch.tensor(
            [row.member_supervised for row in examples], dtype=torch.bool
        ),
        geometry_tokens=tokens,
        geometry_token_mask=token_mask,
        geometry_token_object_index=token_object_index,
        geometry_object_mask=geometry_object_mask,
        geometry_object_roles=geometry_object_roles,
        geometry_object_member_index=geometry_object_member_index,
        geometry_object_anchor_projection_fraction=geometry_object_anchor_projection,
        geometry_object_length_m=geometry_object_length,
        geometry_relation_index=geometry_relation_index,
        geometry_relation_features=geometry_relation_features,
        geometry_relation_mask=geometry_relation_mask,
        selectable_object_mask=selectable,
        object_supervision_mask=object_supervision,
        object_role_task_mask=torch.tensor(
            [
                [role in row.object_supervision_roles for role in OBJECT_ROLE_INDICES]
                for row in examples
            ],
            dtype=torch.bool,
        ),
        object_acceptable_sets=object_sets,
        object_acceptable_set_mask=object_set_mask,
        object_task_mask=torch.tensor(
            [row.object_supervised for row in examples], dtype=torch.bool
        ),
        surface_object_acceptable_sets=surface_object_sets,
        surface_object_acceptable_set_mask=surface_object_set_mask,
        surface_object_task_mask=torch.tensor(
            [row.surface_object_supervised for row in examples], dtype=torch.bool
        ),
        virtual_surface_carrier_acceptable_sets=virtual_surface_carrier_sets,
        virtual_surface_carrier_acceptable_set_mask=(
            virtual_surface_carrier_set_mask
        ),
        virtual_surface_carrier_task_mask=torch.tensor(
            [row.virtual_surface_carrier_supervised for row in examples],
            dtype=torch.bool,
        ),
        step1_tokens=step1,
        step1_token_mask=step1_mask,
        step2_tokens=step2,
        step2_token_mask=step2_mask,
        drivezone_grid=drivezone_grids.unsqueeze(1),
        surface_targets=surfaces,
        surface_task_mask=torch.tensor(
            [row.surface_supervised for row in examples], dtype=torch.bool
        ),
        break_fraction_targets=break_fractions,
        break_road_length_m=break_road_length,
        break_target_mask=break_mask,
        break_main_mask=break_main,
        main_object_target=main_object,
        main_object_task_mask=main_object_task,
        break_main_task_mask=break_main_task,
        complete_junction_task_mask=torch.tensor(
            [row.complete_junction_supervised for row in examples],
            dtype=torch.bool,
        ),
        topology_geometry_task_mask=torch.tensor(
            [row.topology_geometry_supervised for row in examples],
            dtype=torch.bool,
        ),
        task_labels=task_labels,
        task_masks=task_masks,
    )


def _example(
    feature: Mapping[str, Any],
    label: Mapping[str, Any],
    lineage: Mapping[str, Any],
) -> JunctionJointExample:
    object_features = _tensor_1d(feature["object_features"], OBJECT_FEATURE_DIM)
    candidate_features = _tensor_2d(
        feature.get("candidate_features") or (),
        OBJECT_FEATURE_DIM,
    )
    member_features = _tensor_2d(
        feature.get("member_local_features") or (),
        MEMBER_FEATURE_DIM,
    )
    member_ids = tuple(
        str(value) for value in feature.get("structural_member_ids") or ()
    )
    if member_features.shape[0] != len(member_ids):
        raise ValueError("junction member IDs/local features differ")
    swsd_arm_features = _tensor_2d(
        feature.get("swsd_arm_features") or (),
        ANCHOR_ARM_FEATURE_DIM,
    )
    raw_member_arms = tuple(feature.get("member_arm_features") or ())
    if len(raw_member_arms) != len(member_ids):
        raise ValueError("junction member IDs/arm features differ")
    member_arm_features = tuple(
        _tensor_2d(values, ANCHOR_ARM_FEATURE_DIM) for values in raw_member_arms
    )
    member_relation_edges = _member_edges(
        feature.get("member_relation_edges") or (),
        len(member_ids),
        width=ANCHOR_MEMBER_RELATION_DIM,
        role="relation",
    )
    member_incidence_edges = _member_edges(
        feature.get("member_incidence_edges") or (),
        len(member_ids),
        width=ANCHOR_MEMBER_INCIDENCE_DIM,
        role="incidence",
    )
    geometry_tokens = _tensor_2d(
        feature["geometry_token_features"],
        GEOMETRY_TOKEN_DIM,
    )
    geometry_objects = tuple(
        GeometryObject(
            object_id=str(span["object_id"]),
            role_index=int(span["role_index"]),
            token_start=int(span["token_start"]),
            token_end=int(span["token_end"]),
            geometry_valid=bool(span["geometry_valid"]),
            anchor_projection_fraction=_anchor_projection_fraction(
                geometry_tokens[int(span["token_start"]) : int(span["token_end"])]
            ),
            length_m=(
                float(geometry_tokens[int(span["token_start"]), 12])
                * GEOMETRY_RADIUS_M
            ),
        )
        for span in feature["geometry_object_spans"]
    )
    _validate_spans(geometry_objects, geometry_tokens.shape[0])
    geometry_relation_edges = _member_edges(
        feature.get("geometry_relation_edges") or (),
        len(geometry_objects),
        width=GEOMETRY_RELATION_DIM,
        role="geometry relation",
    )

    task_labels: dict[str, int] = {}
    task_masks: dict[str, bool] = {}
    for task, classes in TASK_CLASSES.items():
        raw = str(label.get("task_labels", {}).get(task) or "")
        masked = bool(label.get("task_masks", {}).get(task))
        if masked and raw not in TASK_INDEX[task]:
            raise ValueError(f"unknown {task} label: {raw}")
        task_labels[task] = TASK_INDEX[task].get(raw, -1)
        task_masks[task] = masked

    object_index = {span.object_id: index for index, span in enumerate(geometry_objects)}
    raw_options = tuple(
        tuple(str(value) for value in option)
        for option in label.get("raw_object_target_object_sets") or ()
    )
    desired = tuple(str(value) for value in label.get("raw_object_target_object_ids") or ())
    if not raw_options and not desired:
        raw_kind = str(label.get("raw_object_target_kind") or "")
        desired = tuple(
            f"{raw_kind}:{value}"
            for value in label.get("raw_object_target_ids") or ()
        )
    desired_options = raw_options or ((desired,) if desired else ())
    reachable = bool(desired_options) and all(
        option and all(value in object_index for value in option)
        for option in desired_options
    )
    object_options = tuple(
        tuple(sorted(object_index[value] for value in option))
        for option in desired_options
    ) if reachable else ()
    raw_surface_options = tuple(
        tuple(str(value) for value in option)
        for option in label.get("surface_object_target_object_sets") or ()
    )
    surface_reachable = bool(raw_surface_options) and all(
        option
        and all(
            value in object_index
            and geometry_objects[object_index[value]].role_index
            == GEOMETRY_ROLE_INDEX["RCSD_INTERSECTION"]
            for value in option
        )
        for option in raw_surface_options
    )
    surface_object_options = (
        tuple(
            tuple(sorted(object_index[value] for value in option))
            for option in raw_surface_options
        )
        if surface_reachable
        else ()
    )
    raw_virtual_surface_carrier_options = tuple(
        tuple(str(value) for value in option)
        for option in label.get("virtual_surface_carrier_target_object_sets") or ()
    )
    virtual_surface_carrier_reachable = bool(
        raw_virtual_surface_carrier_options
    ) and all(
        option
        and len(option) <= 8
        and all(
            value in object_index
            and geometry_objects[object_index[value]].role_index
            in VIRTUAL_SURFACE_CARRIER_ROLE_INDICES
            for value in option
        )
        for option in raw_virtual_surface_carrier_options
    )
    virtual_surface_carrier_options = (
        tuple(
            tuple(sorted(object_index[value] for value in option))
            for option in raw_virtual_surface_carrier_options
        )
        if virtual_surface_carrier_reachable
        else ()
    )
    raw_supervision_roles = tuple(
        str(value) for value in label.get("raw_object_supervision_roles") or ()
    )
    role_names = raw_supervision_roles or ("NODE", "ROAD")
    unknown_roles = set(role_names) - {"NODE", "ROAD"}
    if unknown_roles:
        raise ValueError(f"unknown raw object supervision roles: {sorted(unknown_roles)}")
    object_supervision_roles = tuple(
        GEOMETRY_ROLE_INDEX[f"RCSD_{role}"] for role in role_names
    )
    surface = torch.zeros(SURFACE_GRID_SIZE, SURFACE_GRID_SIZE)
    for flat_index in label.get("surface_grid_indices") or ():
        index = int(flat_index)
        _require_index(index, SURFACE_GRID_SIZE * SURFACE_GRID_SIZE, "surface")
        surface[index // SURFACE_GRID_SIZE, index % SURFACE_GRID_SIZE] = 1.0
    drivezone_grid = torch.zeros(SURFACE_GRID_SIZE, SURFACE_GRID_SIZE)
    for flat_index in feature.get("drivezone_grid_indices") or ():
        index = int(flat_index)
        _require_index(index, SURFACE_GRID_SIZE * SURFACE_GRID_SIZE, "DriveZone grid")
        drivezone_grid[
            index // SURFACE_GRID_SIZE,
            index % SURFACE_GRID_SIZE,
        ] = 1.0
    road_break_targets: list[RoadBreakTarget] = []
    for target in label.get("break_position_targets") or ():
        road_object = str(target["road_object_id"])
        if road_object not in object_index:
            reachable = False
            continue
        fraction = float(target["fraction"])
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("junction Road break fraction is invalid")
        road_break_targets.append(
            RoadBreakTarget(
                object_index=object_index[road_object],
                fraction=fraction,
                road_length_m=float(target["road_length_m"]),
                is_selected_main=bool(target.get("is_selected_main")),
            )
        )
    main_target = label.get("selected_main_target") or {}
    main_object_index = None
    if str(main_target.get("kind")) == "RAW_NODE":
        main_object_id = str(main_target.get("object_id") or "")
        if main_object_id in object_index:
            main_object_index = object_index[main_object_id]
        else:
            reachable = False
    return JunctionJointExample(
        sample_id=str(feature["sample_id"]),
        anchor_id=str(feature["anchor_id"]),
        split=str(label["split"]),
        supervision_source=(
            "T10_WEAK" if str(lineage.get("family")) == "T10" else "STRONG_GOLD"
        ),
        supervision_group=(
            str(lineage.get("case_key") or "")
            if str(lineage.get("family")) == "T10"
            else f"GOLD:{lineage.get('case_id') or ''}"
        ),
        sample_weight=float(label["sample_weight"]),
        object_features=object_features,
        candidate_ids=tuple(str(value) for value in feature.get("candidate_ids") or ()),
        candidate_features=candidate_features,
        member_ids=member_ids,
        member_features=member_features,
        swsd_arm_features=swsd_arm_features,
        member_arm_features=member_arm_features,
        member_relation_edges=member_relation_edges,
        member_incidence_edges=member_incidence_edges,
        geometry_tokens=geometry_tokens,
        geometry_objects=geometry_objects,
        geometry_relation_edges=geometry_relation_edges,
        drivezone_grid=drivezone_grid,
        task_labels=task_labels,
        task_masks=task_masks,
        candidate_acceptable_indices=tuple(
            int(value) for value in label.get("candidate_acceptable_indices") or ()
        ),
        candidate_supervised=bool(label.get("candidate_supervised")),
        member_acceptable_sets=tuple(
            tuple(int(value) for value in option)
            for option in label.get("member_acceptable_sets") or ()
        ),
        member_supervised=bool(label.get("member_supervised")),
        object_acceptable_sets=object_options,
        object_supervision_roles=object_supervision_roles,
        object_supervised=reachable,
        surface_object_acceptable_sets=surface_object_options,
        surface_object_supervised=bool(
            label.get("surface_object_supervised") and surface_reachable
        ),
        virtual_surface_carrier_acceptable_sets=(
            virtual_surface_carrier_options
        ),
        virtual_surface_carrier_supervised=bool(
            label.get("virtual_surface_carrier_supervised")
            and virtual_surface_carrier_reachable
        ),
        surface_target=surface,
        surface_supervised=bool(label.get("surface_grid_supervised")),
        road_break_targets=tuple(road_break_targets),
        main_object_index=main_object_index,
        complete_junction_supervised=bool(
            label.get("complete_junction_supervised")
        ),
        topology_geometry_supervised=bool(
            label.get("topology_geometry_supervised") and reachable
        ),
    )


def _anchor_projection_fraction(tokens: torch.Tensor) -> float:
    if tokens.shape[0] < 2:
        return float(tokens[0, 11]) if tokens.shape[0] else 0.0
    best: tuple[float, float] | None = None
    for first, second in zip(tokens[:-1], tokens[1:]):
        start_fraction = float(first[11])
        end_fraction = float(second[11])
        if end_fraction < start_fraction:
            continue
        ax, ay = float(first[7]), float(first[8])
        bx, by = float(second[7]), float(second[8])
        vx, vy = bx - ax, by - ay
        denominator = vx * vx + vy * vy
        ratio = 0.0 if denominator == 0.0 else -(ax * vx + ay * vy) / denominator
        ratio = min(1.0, max(0.0, ratio))
        px, py = ax + ratio * vx, ay + ratio * vy
        candidate = (
            px * px + py * py,
            start_fraction + ratio * (end_fraction - start_fraction),
        )
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is not None:
        return best[1]
    distances = tokens[:, 7].square() + tokens[:, 8].square()
    return float(tokens[int(distances.argmin()), 11])


def _role_token_count(row: JunctionJointExample, role: str) -> int:
    index = GEOMETRY_ROLE_INDEX[role]
    return sum(
        span.token_end - span.token_start
        for span in row.geometry_objects
        if span.role_index == index
    )


def _copy_role_tokens(
    row: JunctionJointExample,
    role: str,
    output: torch.Tensor,
    mask: torch.Tensor,
    batch_index: int,
) -> None:
    role_index = GEOMETRY_ROLE_INDEX[role]
    selections = [
        row.geometry_tokens[span.token_start : span.token_end]
        for span in row.geometry_objects
        if span.role_index == role_index
    ]
    if not selections:
        return
    values = torch.cat(selections, dim=0)
    output[batch_index, : values.shape[0]] = values
    mask[batch_index, : values.shape[0]] = True


def _validate_spans(spans: Sequence[GeometryObject], token_count: int) -> None:
    cursor = 0
    for span in spans:
        if span.token_start != cursor or span.token_end <= span.token_start:
            raise ValueError("junction geometry object spans are not contiguous")
        if span.role_index < 0 or span.role_index >= len(GEOMETRY_ROLE_INDEX):
            raise ValueError("junction geometry object role is invalid")
        cursor = span.token_end
    if cursor != token_count:
        raise ValueError("junction geometry object spans do not cover all tokens")


def _tensor_1d(values: Sequence[Any], width: int) -> torch.Tensor:
    tensor = torch.tensor(values, dtype=torch.float32)
    if tensor.shape != (width,):
        raise ValueError("junction scalar feature dimension differs")
    return tensor


def _tensor_2d(values: Sequence[Sequence[Any]], width: int) -> torch.Tensor:
    if not values:
        return torch.zeros(0, width)
    tensor = torch.tensor(values, dtype=torch.float32)
    if tensor.ndim != 2 or tensor.shape[1] != width:
        raise ValueError("junction set feature dimension differs")
    return tensor


def _member_edges(
    values: Sequence[Sequence[Any]],
    member_count: int,
    *,
    width: int,
    role: str,
) -> tuple[tuple[int, int, tuple[float, ...]], ...]:
    result: list[tuple[int, int, tuple[float, ...]]] = []
    seen: set[tuple[int, int]] = set()
    for raw in values:
        if len(raw) != 3:
            raise ValueError(f"junction member {role} row differs")
        left, right = int(raw[0]), int(raw[1])
        _require_index(left, member_count, f"member {role} left")
        _require_index(right, member_count, f"member {role} right")
        if left == right or (left, right) in seen:
            raise ValueError(f"junction member {role} is repeated or self-linked")
        features = tuple(float(value) for value in raw[2])
        if len(features) != width:
            raise ValueError(f"junction member {role} dimension differs")
        if not bool(torch.isfinite(torch.tensor(features)).all()):
            raise ValueError(f"junction member {role} is not finite")
        seen.add((left, right))
        result.append((left, right, features))
    return tuple(result)


def _require_index(index: int, size: int, role: str) -> None:
    if index < 0 or index >= size:
        raise ValueError(f"junction {role} target index is out of range")


def _store_paths(monolith_path: Path) -> tuple[Path, ...]:
    if monolith_path.is_file():
        return (monolith_path,)
    shards = tuple(sorted(monolith_path.parent.glob("*.jsonl.gz")))
    if not shards:
        raise FileNotFoundError(monolith_path)
    return shards


def _index_rows(paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl_paths(paths):
        sample_id = str(row["sample_id"])
        if sample_id in result:
            raise ValueError(f"junction joint row is duplicated: {sample_id}")
        result[sample_id] = row
    return result


def _read_jsonl_paths(paths: Sequence[Path]) -> Iterable[dict[str, Any]]:
    for path in paths:
        yield from _read_jsonl(path)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


__all__ = [
    "JunctionJointBatch",
    "JunctionJointExample",
    "MAX_BREAKS_PER_ROAD",
    "TASK_CLASSES",
    "TASK_INDEX",
    "VIRTUAL_SURFACE_CARRIER_ROLE_INDICES",
    "collate_junction_joint",
    "read_junction_joint_examples",
    "relation_candidate_constraints",
    "virtual_surface_carrier_candidate_mask",
    "virtual_surface_carrier_object_grid",
]
