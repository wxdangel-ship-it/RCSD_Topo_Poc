from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_access_sets import (
    SIDE_ACCESS_FEATURE_DIM,
    SIDE_OBJECT_FEATURE_DIM,
    SIDE_ROAD_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_data import (
    EndToEndRecallExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
    ORDINARY_ANCHOR_SUCCESS,
    ORDINARY_ANCHOR_UNRESOLVED,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_relations import (
    ROAD_RELATION_FEATURE_NAMES,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


ORDINARY_SET_SIDE_COUNT = 2
ORDINARY_SET_SOURCE_SWSD = 0
ORDINARY_SET_SOURCE_RCSD = 1
ORDINARY_SET_SOURCE_UNRESOLVED = 2
ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT = 8
ORDINARY_SET_ROAD_RELATION_DIM = len(ROAD_RELATION_FEATURE_NAMES)


@dataclass(frozen=True)
class AnchorOofBusinessPrediction:
    case_key: str
    anchor_id: str
    business_state: int
    candidate_id: str = ""

    def __post_init__(self) -> None:
        if not self.case_key or not self.anchor_id:
            raise ValueError("OOF anchor prediction lacks identity")
        if self.business_state not in {
            ORDINARY_ANCHOR_UNRESOLVED,
            ORDINARY_ANCHOR_SUCCESS,
            ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE,
        }:
            raise ValueError("OOF anchor business state is unsupported")
        if (
            self.business_state == ORDINARY_ANCHOR_SUCCESS
            and not self.candidate_id
        ):
            raise ValueError("successful OOF anchor lacks selected object")
        if (
            self.business_state != ORDINARY_ANCHOR_SUCCESS
            and self.candidate_id
        ):
            raise ValueError("non-successful OOF anchor exposes an object")


@dataclass(frozen=True)
class OrdinarySegmentRoadPool:
    case_key: str
    segment_id: str
    object_feature_values: tuple[float, ...]
    road_ids: tuple[str, ...]
    road_sources: tuple[int, ...]
    road_start_node_ids: tuple[str, ...]
    road_end_node_ids: tuple[str, ...]
    road_feature_values: tuple[tuple[float, ...], ...]
    road_relations: tuple[tuple[int, int, tuple[float, ...]], ...]
    oof_anchor_relations: tuple[
        tuple[tuple[float, ...], ...],
        ...,
    ] = ()
    oof_anchor_release_ready: bool = False
    acceptable_road_ids: tuple[str, ...] = ()
    road_ownership_targets: tuple[int, ...] = ()
    road_ownership_task_mask: tuple[bool, ...] = ()
    road_business_role_targets: tuple[int, ...] = ()
    road_business_role_task_mask: tuple[bool, ...] = ()
    road_ownership_sample_weight: float = 0.0
    road_business_role_sample_weight: float = 0.0

    def __post_init__(self) -> None:
        if not self.case_key or not self.segment_id:
            raise ValueError("ordinary Segment Road pool lacks identity")
        if len(self.object_feature_values) != SIDE_OBJECT_FEATURE_DIM:
            raise ValueError("ordinary Segment object feature dimension differs")
        count = len(self.road_ids)
        if (
            not count
            or len(set(self.road_ids)) != count
            or len(self.road_sources) != count
            or len(self.road_start_node_ids) != count
            or len(self.road_end_node_ids) != count
            or len(self.road_feature_values) != count
        ):
            raise ValueError("ordinary Segment Road pool is invalid")
        if any(
            len(values) != SIDE_ROAD_FEATURE_DIM
            for values in self.road_feature_values
        ):
            raise ValueError("ordinary Segment Road feature dimension differs")
        for values in (
            self.oof_anchor_relations,
            self.road_ownership_targets,
            self.road_ownership_task_mask,
            self.road_business_role_targets,
            self.road_business_role_task_mask,
        ):
            if values and len(values) != count:
                raise ValueError("ordinary Segment Road business labels differ")


@dataclass(frozen=True)
class EndToEndOrdinarySetBatch:
    case_keys: tuple[str, ...]
    advance_right_ids: tuple[str, ...]
    side_segment_ids: tuple[tuple[str, str], ...]
    side_group_indices: torch.Tensor
    side_object_values: torch.Tensor
    side_road_values: torch.Tensor
    side_road_mask: torch.Tensor
    side_road_source_indices: torch.Tensor
    side_road_relation_values: torch.Tensor
    side_access_values: torch.Tensor
    side_access_mask: torch.Tensor
    decision_targets: torch.Tensor
    decision_task_mask: torch.Tensor
    road_member_targets: torch.Tensor
    road_task_mask: torch.Tensor
    road_cardinality_targets: torch.Tensor
    access_targets: torch.Tensor
    access_task_mask: torch.Tensor
    sample_weights: torch.Tensor
    candidate_reachable: torch.Tensor
    road_ids: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    access_road_ids: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    side_required_anchor_indices: torch.Tensor | None = None
    side_anchor_candidate_relation_values: torch.Tensor | None = None
    side_anchor_candidate_mask: torch.Tensor | None = None
    side_precomputed_anchor_context: torch.Tensor | None = None
    side_precomputed_anchor_state: torch.Tensor | None = None
    road_ownership_targets: torch.Tensor | None = None
    road_ownership_task_mask: torch.Tensor | None = None
    road_business_role_targets: torch.Tensor | None = None
    road_business_role_task_mask: torch.Tensor | None = None
    road_ownership_sample_weights: torch.Tensor | None = None
    road_business_role_sample_weights: torch.Tensor | None = None

    def __post_init__(self) -> None:
        batch_size = len(self.case_keys)
        side_shape = (batch_size, ORDINARY_SET_SIDE_COUNT)
        if (
            len(self.advance_right_ids) != batch_size
            or len(self.side_segment_ids) != batch_size
            or len(self.road_ids) != batch_size
            or len(self.access_road_ids) != batch_size
        ):
            raise ValueError("ordinary set metadata batch differs")
        if self.side_group_indices.shape != side_shape:
            raise ValueError("ordinary set group-index shape differs")
        if self.side_object_values.shape != (
            *side_shape,
            SIDE_OBJECT_FEATURE_DIM,
        ):
            raise ValueError("ordinary set object tensor shape differs")
        road_shape = self.side_road_values.shape[:3]
        if (
            self.side_road_values.ndim != 4
            or self.side_road_values.shape[-1] != SIDE_ROAD_FEATURE_DIM
            or road_shape[:2] != side_shape
            or self.side_road_mask.shape != road_shape
            or self.side_road_source_indices.shape != road_shape
            or self.road_member_targets.shape != road_shape
        ):
            raise ValueError("ordinary set Road tensor shape differs")
        relation_shape = (
            *road_shape,
            road_shape[-1],
            ORDINARY_SET_ROAD_RELATION_DIM,
        )
        if self.side_road_relation_values.shape != relation_shape:
            raise ValueError("ordinary set Road relation shape differs")
        access_shape = self.side_access_values.shape[:3]
        if (
            self.side_access_values.ndim != 4
            or self.side_access_values.shape[-1] != SIDE_ACCESS_FEATURE_DIM
            or access_shape[:2] != side_shape
            or self.side_access_mask.shape != access_shape
            or self.access_targets.shape != access_shape
        ):
            raise ValueError("ordinary set access tensor shape differs")
        for values in (
            self.decision_targets,
            self.decision_task_mask,
            self.road_task_mask,
            self.road_cardinality_targets,
            self.access_task_mask,
            self.sample_weights,
            self.candidate_reachable,
        ):
            if values.shape != side_shape:
                raise ValueError("ordinary set side target shape differs")
        anchor_values = (
            self.side_required_anchor_indices,
            self.side_anchor_candidate_relation_values,
            self.side_anchor_candidate_mask,
        )
        if any(value is not None for value in anchor_values):
            if any(value is None for value in anchor_values):
                raise ValueError("ordinary set anchor relation is partial")
            required = self.side_required_anchor_indices
            relations = self.side_anchor_candidate_relation_values
            candidate_mask = self.side_anchor_candidate_mask
            assert required is not None
            assert relations is not None
            assert candidate_mask is not None
            if (
                required.shape[:2] != side_shape
                or candidate_mask.shape[:2] != side_shape
                or relations.shape[:2] != side_shape
                or relations.shape[2] != road_shape[-1]
                or relations.shape[3:5] != candidate_mask.shape[2:4]
                or relations.shape[-1] != 4
                or required.shape[-1] != candidate_mask.shape[2]
            ):
                raise ValueError(
                    "ordinary set same-forward anchor relation shape differs"
                )
        if (
            self.side_precomputed_anchor_context is not None
            and self.side_precomputed_anchor_context.shape
            != (*road_shape, ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT)
        ):
            raise ValueError(
                "ordinary set precomputed anchor context shape differs"
            )
        if self.side_precomputed_anchor_state is not None:
            if self.side_precomputed_anchor_state.shape != side_shape:
                raise ValueError(
                    "ordinary set precomputed anchor state shape differs"
                )
            if bool(
                (
                    (self.side_precomputed_anchor_state < 0)
                    | (self.side_precomputed_anchor_state > 2)
                ).any()
            ):
                raise ValueError(
                    "ordinary set precomputed anchor state is unsupported"
                )
        business_values = (
            self.road_ownership_targets,
            self.road_ownership_task_mask,
            self.road_business_role_targets,
            self.road_business_role_task_mask,
            self.road_ownership_sample_weights,
            self.road_business_role_sample_weights,
        )
        if any(value is not None for value in business_values):
            if any(value is None for value in business_values):
                raise ValueError("ordinary set Road business labels are partial")
            for value in business_values[:4]:
                assert value is not None
                if value.shape != road_shape:
                    raise ValueError(
                        "ordinary set Road business target shape differs"
                    )
            for value in business_values[4:]:
                assert value is not None
                if value.shape != side_shape:
                    raise ValueError(
                        "ordinary set Road business weight shape differs"
                    )


def read_anchor_oof_business_predictions(
    anchor_oof_root: Path,
) -> dict[tuple[str, str], AnchorOofBusinessPrediction]:
    """Read inference-time OOF anchor decisions without using anchor truth."""
    root = normalize_runtime_path(anchor_oof_root).resolve(strict=True)
    path = root / "oof_predictions.jsonl"
    result: dict[tuple[str, str], AnchorOofBusinessPrediction] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            case_key = str(row["case_key"])
            anchor_id = str(row["anchor_id"])
            key = (case_key, anchor_id)
            if key in result:
                raise ValueError(f"duplicate OOF anchor prediction: {key}")
            predicted = str(row.get("predicted") or "")
            gate_passed = bool(row.get("gate_passed"))
            inference_success = bool(
                predicted == "SUCCESS" and gate_passed
            )
            proven_no_evidence = bool(
                row.get("no_evidence_proof_passed")
            )
            if inference_success and proven_no_evidence:
                raise ValueError(
                    f"OOF anchor has two terminal states: {key}"
                )
            candidate_id = str(row.get("candidate_predicted_id") or "")
            if inference_success:
                state = ORDINARY_ANCHOR_SUCCESS
                if not candidate_id:
                    raise ValueError(
                        f"successful OOF anchor lacks selected object: {key}"
                    )
            elif proven_no_evidence:
                state = ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE
                candidate_id = ""
            else:
                state = ORDINARY_ANCHOR_UNRESOLVED
                candidate_id = ""
            result[key] = AnchorOofBusinessPrediction(
                case_key=case_key,
                anchor_id=anchor_id,
                business_state=state,
                candidate_id=candidate_id,
            )
    return result


def read_truth_free_ordinary_segment_road_pools(
    member_store_root: Path,
    *,
    required_keys: set[tuple[str, str]],
) -> dict[tuple[str, str], OrdinarySegmentRoadPool]:
    """Read only needed Segment pools and remove prior selected-anchor state."""
    if not required_keys:
        return {}
    root = normalize_runtime_path(member_store_root).resolve(strict=True)
    path = root / "ordinary_road_member_features.jsonl"
    labels = {}
    label_path = root / "ordinary_road_member_labels.jsonl"
    if label_path.exists():
        with label_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = (str(row["case_key"]), str(row["segment_id"]))
                if key in required_keys:
                    labels[key] = row
    result: dict[tuple[str, str], OrdinarySegmentRoadPool] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (str(row["case_key"]), str(row["segment_id"]))
            if key not in required_keys:
                continue
            if bool(row.get("feature_uses_truth")):
                raise ValueError(f"ordinary Road pool uses truth: {key}")
            if int(row.get("terminal_input_count", 0)):
                raise ValueError(f"ordinary Road pool uses terminal input: {key}")
            candidates = list(row.get("candidate_rows") or ())
            label = labels.get(key) or {}
            ownership_targets = tuple(
                int(value)
                for value in label.get("road_ownership_targets") or ()
            )
            ownership_mask = tuple(
                bool(value)
                for value in label.get("road_ownership_task_mask") or ()
            )
            role_targets = tuple(
                int(value)
                for value in label.get("road_business_role_targets") or ()
            )
            role_mask = tuple(
                bool(value)
                for value in label.get("road_business_role_task_mask") or ()
            )
            result[key] = OrdinarySegmentRoadPool(
                case_key=key[0],
                segment_id=key[1],
                object_feature_values=tuple(
                    float(value)
                    for value in row["object_feature_values"]
                ),
                road_ids=tuple(str(value["road_id"]) for value in candidates),
                road_sources=tuple(
                    _road_source_index(str(value.get("source") or ""))
                    for value in candidates
                ),
                road_start_node_ids=tuple(
                    str(value.get("start_node_id") or "")
                    for value in candidates
                ),
                road_end_node_ids=tuple(
                    str(value.get("end_node_id") or "")
                    for value in candidates
                ),
                road_feature_values=tuple(
                    _without_selected_anchor_state(
                        value.get("oof_feature_values") or ()
                    )
                    for value in candidates
                ),
                road_relations=tuple(
                    (
                        int(value["left_index"]),
                        int(value["right_index"]),
                        tuple(
                            float(item)
                            for item in value["feature_values"]
                        ),
                    )
                    for value in row.get("road_relation_rows") or ()
                ),
                oof_anchor_relations=tuple(
                    tuple(
                        tuple(float(item) for item in relation)
                        for relation in (
                            value.get("oof_anchor_relation_values") or ()
                        )
                    )
                    for value in candidates
                ),
                oof_anchor_release_ready=bool(
                    row.get("oof_anchor_release_ready")
                ),
                acceptable_road_ids=tuple(
                    str(value)
                    for value in label.get("acceptable_road_ids") or ()
                ),
                road_ownership_targets=ownership_targets,
                road_ownership_task_mask=ownership_mask,
                road_business_role_targets=role_targets,
                road_business_role_task_mask=role_mask,
                road_ownership_sample_weight=float(
                    label.get("road_ownership_sample_weight") or 0.0
                ),
                road_business_role_sample_weight=float(
                    label.get("road_business_role_sample_weight") or 0.0
                ),
            )
    missing = required_keys - set(result)
    if missing:
        raise ValueError(
            "ordinary Segment Road pools are missing: "
            f"{sorted(missing)[:5]}"
        )
    return result


def collate_end_to_end_ordinary_set_batch(
    examples: Sequence[EndToEndRecallExample],
    *,
    joint_rows_by_id: Mapping[str, Mapping[str, Any]],
    road_pools: Mapping[tuple[str, str], OrdinarySegmentRoadPool],
    use_oof_anchor_context: bool = False,
    anchor_oof_predictions: Mapping[
        tuple[str, str],
        AnchorOofBusinessPrediction,
    ]
    | None = None,
) -> EndToEndOrdinarySetBatch:
    """Collate free-run ordinary sets; labels never enter inference values."""
    if not examples:
        raise ValueError("ordinary set collate requires examples")
    if use_oof_anchor_context and anchor_oof_predictions is None:
        raise ValueError("OOF anchor context requires OOF anchor predictions")
    prepared = [
        _prepare_example(
            example,
            joint_rows_by_id=joint_rows_by_id,
            road_pools=road_pools,
        )
        for example in examples
    ]
    maximum_roads = max(
        len(side["pool"].road_ids)
        for row in prepared
        for side in row["sides"]
    )
    maximum_accesses = max(
        1,
        max(
            len(side["access_rows"])
            for row in prepared
            for side in row["sides"]
        ),
    )
    maximum_required_anchors = max(
        1,
        max(
            len(side["required_anchors"])
            for row in prepared
            for side in row["sides"]
        ),
    )
    maximum_anchor_candidates = max(
        1,
        max(
            (
                len(anchor.candidate_ids)
                for row in prepared
                for side in row["sides"]
                for _, anchor in side["required_anchors"]
            ),
            default=1,
        ),
    )
    batch_size = len(prepared)
    road_values = torch.zeros(
        (
            batch_size,
            ORDINARY_SET_SIDE_COUNT,
            maximum_roads,
            SIDE_ROAD_FEATURE_DIM,
        ),
        dtype=torch.float32,
    )
    road_mask = torch.zeros(
        (batch_size, ORDINARY_SET_SIDE_COUNT, maximum_roads),
        dtype=torch.bool,
    )
    road_sources = torch.full_like(
        road_mask,
        ORDINARY_SET_SOURCE_UNRESOLVED,
        dtype=torch.long,
    )
    road_relations = torch.zeros(
        (
            batch_size,
            ORDINARY_SET_SIDE_COUNT,
            maximum_roads,
            maximum_roads,
            ORDINARY_SET_ROAD_RELATION_DIM,
        ),
        dtype=torch.float32,
    )
    access_values = torch.zeros(
        (
            batch_size,
            ORDINARY_SET_SIDE_COUNT,
            maximum_accesses,
            SIDE_ACCESS_FEATURE_DIM,
        ),
        dtype=torch.float32,
    )
    access_mask = torch.zeros(
        (batch_size, ORDINARY_SET_SIDE_COUNT, maximum_accesses),
        dtype=torch.bool,
    )
    decision_targets = torch.zeros(
        (batch_size, ORDINARY_SET_SIDE_COUNT),
        dtype=torch.long,
    )
    decision_task_mask = torch.ones(
        (batch_size, ORDINARY_SET_SIDE_COUNT),
        dtype=torch.bool,
    )
    road_member_targets = torch.zeros_like(road_mask)
    road_task_mask = torch.zeros_like(decision_task_mask)
    road_cardinality_targets = torch.zeros_like(decision_targets)
    ownership_targets = torch.zeros_like(road_sources)
    ownership_task_mask = torch.zeros_like(road_mask)
    role_targets = torch.zeros_like(road_sources)
    role_task_mask = torch.zeros_like(road_mask)
    ownership_sample_weights = torch.zeros(
        (batch_size, ORDINARY_SET_SIDE_COUNT),
        dtype=torch.float32,
    )
    role_sample_weights = torch.zeros_like(ownership_sample_weights)
    access_targets = torch.zeros_like(access_mask)
    access_task_mask = torch.zeros_like(decision_task_mask)
    sample_weights = torch.ones(
        (batch_size, ORDINARY_SET_SIDE_COUNT),
        dtype=torch.float32,
    )
    candidate_reachable = torch.zeros_like(decision_task_mask)
    side_group_indices = torch.zeros_like(decision_targets)
    side_object_values = torch.zeros(
        (
            batch_size,
            ORDINARY_SET_SIDE_COUNT,
            SIDE_OBJECT_FEATURE_DIM,
        ),
        dtype=torch.float32,
    )
    required_anchor_indices = torch.full(
        (
            batch_size,
            ORDINARY_SET_SIDE_COUNT,
            maximum_required_anchors,
        ),
        -1,
        dtype=torch.long,
    )
    anchor_candidate_relations = torch.zeros(
        (
            batch_size,
            ORDINARY_SET_SIDE_COUNT,
            maximum_roads,
            maximum_required_anchors,
            maximum_anchor_candidates,
            4,
        ),
        dtype=torch.float32,
    )
    anchor_candidate_mask = torch.zeros(
        (
            batch_size,
            ORDINARY_SET_SIDE_COUNT,
            maximum_required_anchors,
            maximum_anchor_candidates,
        ),
        dtype=torch.bool,
    )
    precomputed_anchor_context = (
        torch.zeros(
            (
                batch_size,
                ORDINARY_SET_SIDE_COUNT,
                maximum_roads,
                ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT,
            ),
            dtype=torch.float32,
        )
        if use_oof_anchor_context
        else None
    )
    precomputed_anchor_state = (
        torch.full(
            (batch_size, ORDINARY_SET_SIDE_COUNT),
            ORDINARY_ANCHOR_UNRESOLVED,
            dtype=torch.long,
        )
        if use_oof_anchor_context
        else None
    )
    for batch_index, row in enumerate(prepared):
        for side_index, side in enumerate(row["sides"]):
            pool: OrdinarySegmentRoadPool = side["pool"]
            road_count = len(pool.road_ids)
            road_values[batch_index, side_index, :road_count] = torch.tensor(
                pool.road_feature_values,
                dtype=torch.float32,
            )
            road_mask[batch_index, side_index, :road_count] = True
            road_sources[batch_index, side_index, :road_count] = torch.tensor(
                pool.road_sources,
                dtype=torch.long,
            )
            for left, right, values in pool.road_relations:
                road_relations[
                    batch_index,
                    side_index,
                    left,
                    right,
                ] = torch.tensor(values, dtype=torch.float32)
                road_relations[
                    batch_index,
                    side_index,
                    right,
                    left,
                ] = torch.tensor(values, dtype=torch.float32)
            if pool.road_ownership_targets:
                ownership_targets[
                    batch_index,
                    side_index,
                    :road_count,
                ] = torch.tensor(
                    pool.road_ownership_targets,
                    dtype=torch.long,
                )
                ownership_task_mask[
                    batch_index,
                    side_index,
                    :road_count,
                ] = torch.tensor(
                    pool.road_ownership_task_mask,
                    dtype=torch.bool,
                )
            if pool.road_business_role_targets:
                role_targets[
                    batch_index,
                    side_index,
                    :road_count,
                ] = torch.tensor(
                    pool.road_business_role_targets,
                    dtype=torch.long,
                )
                role_task_mask[
                    batch_index,
                    side_index,
                    :road_count,
                ] = torch.tensor(
                    pool.road_business_role_task_mask,
                    dtype=torch.bool,
                )
            ownership_sample_weights[batch_index, side_index] = float(
                pool.road_ownership_sample_weight
            )
            role_sample_weights[batch_index, side_index] = float(
                pool.road_business_role_sample_weight
            )
            side_object_values[batch_index, side_index] = torch.tensor(
                pool.object_feature_values,
                dtype=torch.float32,
            )
            if precomputed_anchor_context is not None:
                assert precomputed_anchor_state is not None
                assert anchor_oof_predictions is not None
                state, candidate_ids = _oof_side_anchor_business_state(
                    case_key=pool.case_key,
                    required_anchors=side["required_anchors"],
                    predictions=anchor_oof_predictions,
                )
                precomputed_anchor_state[
                    batch_index,
                    side_index,
                ] = state
                if state == ORDINARY_ANCHOR_SUCCESS:
                    for road_index in range(road_count):
                        relation_values = torch.tensor(
                            [
                                _anchor_candidate_relation(
                                    pool,
                                    road_index=road_index,
                                    candidate_id=candidate_id,
                                )
                                for candidate_id in candidate_ids
                            ],
                            dtype=torch.float32,
                        )
                        precomputed_anchor_context[
                            batch_index,
                            side_index,
                            road_index,
                        ] = torch.cat(
                            (
                                relation_values.mean(dim=0),
                                relation_values.amax(dim=0),
                            )
                        )
            for required_index, (
                anchor_index,
                anchor,
            ) in enumerate(side["required_anchors"]):
                required_anchor_indices[
                    batch_index,
                    side_index,
                    required_index,
                ] = anchor_index
                candidate_count = len(anchor.candidate_ids)
                anchor_candidate_mask[
                    batch_index,
                    side_index,
                    required_index,
                    :candidate_count,
                ] = True
                for road_index in range(road_count):
                    anchor_candidate_relations[
                        batch_index,
                        side_index,
                        road_index,
                        required_index,
                        :candidate_count,
                    ] = torch.tensor(
                        [
                            _anchor_candidate_relation(
                                pool,
                                road_index=road_index,
                                candidate_id=candidate_id,
                            )
                            for candidate_id in anchor.candidate_ids
                        ],
                        dtype=torch.float32,
                    )
            side_group_indices[batch_index, side_index] = int(
                side["group_index"]
            )
            supervision = side["supervision"]
            target_ids = set(
                pool.acceptable_road_ids
                or supervision["acceptable_road_ids"]
            )
            target_indices = [
                index
                for index, road_id in enumerate(pool.road_ids)
                if road_id in target_ids
            ]
            reachable = bool(
                target_ids
                and len(target_indices) == len(target_ids)
            )
            candidate_reachable[batch_index, side_index] = reachable
            road_task_mask[batch_index, side_index] = reachable
            road_cardinality_targets[batch_index, side_index] = len(
                target_ids
            )
            for index in target_indices:
                road_member_targets[
                    batch_index,
                    side_index,
                    index,
                ] = True
            decision_targets[batch_index, side_index] = int(
                supervision["source_index"]
            )
            sample_weights[batch_index, side_index] = float(
                row["label_weight"]
            )
            access_rows = side["access_rows"]
            if access_rows:
                access_values[
                    batch_index,
                    side_index,
                    : len(access_rows),
                ] = torch.tensor(
                    [
                        _without_access_selected_anchor_state(
                            value["feature_values"]
                        )
                        for value in access_rows
                    ],
                    dtype=torch.float32,
                )
                access_mask[
                    batch_index,
                    side_index,
                    : len(access_rows),
                ] = True
            acceptable_access = set(
                supervision["acceptable_access_road_ids"]
            )
            for index, value in enumerate(access_rows):
                if str(value["road_id"]) in acceptable_access:
                    access_targets[
                        batch_index,
                        side_index,
                        index,
                    ] = True
            access_task_mask[batch_index, side_index] = bool(
                supervision["access_supervised"]
                and access_targets[batch_index, side_index].any()
            )
    return EndToEndOrdinarySetBatch(
        case_keys=tuple(str(row["case_key"]) for row in prepared),
        advance_right_ids=tuple(
            str(row["advance_right_id"]) for row in prepared
        ),
        side_segment_ids=tuple(
            tuple(str(side["segment_id"]) for side in row["sides"])
            for row in prepared
        ),
        side_group_indices=side_group_indices,
        side_object_values=side_object_values,
        side_road_values=road_values,
        side_road_mask=road_mask,
        side_road_source_indices=road_sources,
        side_road_relation_values=road_relations,
        side_access_values=access_values,
        side_access_mask=access_mask,
        decision_targets=decision_targets,
        decision_task_mask=decision_task_mask,
        road_member_targets=road_member_targets,
        road_task_mask=road_task_mask,
        road_cardinality_targets=road_cardinality_targets,
        access_targets=access_targets,
        access_task_mask=access_task_mask,
        sample_weights=sample_weights,
        candidate_reachable=candidate_reachable,
        road_ids=tuple(
            tuple(side["pool"].road_ids for side in row["sides"])
            for row in prepared
        ),
        access_road_ids=tuple(
            tuple(
                tuple(str(value["road_id"]) for value in side["access_rows"])
                for side in row["sides"]
            )
            for row in prepared
        ),
        side_precomputed_anchor_context=precomputed_anchor_context,
        side_precomputed_anchor_state=precomputed_anchor_state,
        side_required_anchor_indices=required_anchor_indices,
        side_anchor_candidate_relation_values=(
            anchor_candidate_relations
        ),
        side_anchor_candidate_mask=anchor_candidate_mask,
        road_ownership_targets=ownership_targets,
        road_ownership_task_mask=ownership_task_mask,
        road_business_role_targets=role_targets,
        road_business_role_task_mask=role_task_mask,
        road_ownership_sample_weights=ownership_sample_weights,
        road_business_role_sample_weights=role_sample_weights,
    )


def move_end_to_end_ordinary_set_batch(
    batch: EndToEndOrdinarySetBatch,
    device: torch.device,
) -> EndToEndOrdinarySetBatch:
    return EndToEndOrdinarySetBatch(
        **{
            field: (
                value.to(device)
                if isinstance(value, torch.Tensor)
                else value
            )
            for field, value in batch.__dict__.items()
        }
    )


def collate_ordinary_set_pretraining_batch(
    examples: Sequence[Any],
) -> EndToEndOrdinarySetBatch:
    """Pack ordinary Segment labels without injecting selected-anchor state."""
    if not examples:
        raise ValueError("ordinary set pretraining requires examples")
    pair_count = (len(examples) + ORDINARY_SET_SIDE_COUNT - 1) // 2
    maximum_roads = max(len(row.road_ids) for row in examples)
    side_shape = (pair_count, ORDINARY_SET_SIDE_COUNT)
    road_shape = (*side_shape, maximum_roads)
    road_values = torch.zeros(
        (*road_shape, SIDE_ROAD_FEATURE_DIM),
        dtype=torch.float32,
    )
    road_mask = torch.zeros(road_shape, dtype=torch.bool)
    road_sources = torch.full(
        road_shape,
        ORDINARY_SET_SOURCE_UNRESOLVED,
        dtype=torch.long,
    )
    road_relations = torch.zeros(
        (
            *road_shape,
            maximum_roads,
            ORDINARY_SET_ROAD_RELATION_DIM,
        ),
        dtype=torch.float32,
    )
    object_values = torch.zeros(
        (*side_shape, SIDE_OBJECT_FEATURE_DIM),
        dtype=torch.float32,
    )
    decision_targets = torch.zeros(side_shape, dtype=torch.long)
    decision_task_mask = torch.zeros(side_shape, dtype=torch.bool)
    member_targets = torch.zeros(road_shape, dtype=torch.bool)
    road_task_mask = torch.zeros(side_shape, dtype=torch.bool)
    cardinality_targets = torch.zeros(side_shape, dtype=torch.long)
    sample_weights = torch.zeros(side_shape, dtype=torch.float32)
    candidate_reachable = torch.zeros(side_shape, dtype=torch.bool)
    ownership_targets = torch.zeros(road_shape, dtype=torch.long)
    ownership_task_mask = torch.zeros(road_shape, dtype=torch.bool)
    role_targets = torch.zeros(road_shape, dtype=torch.long)
    role_task_mask = torch.zeros(road_shape, dtype=torch.bool)
    ownership_sample_weights = torch.zeros(
        side_shape,
        dtype=torch.float32,
    )
    role_sample_weights = torch.zeros_like(ownership_sample_weights)
    precomputed_anchor_context = torch.zeros(
        (*road_shape, ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT),
        dtype=torch.float32,
    )
    segment_ids: list[list[str]] = [
        ["", ""] for _ in range(pair_count)
    ]
    road_ids: list[list[tuple[str, ...]]] = [
        [(), ()] for _ in range(pair_count)
    ]
    case_keys = ["" for _ in range(pair_count)]
    for flat_index, example in enumerate(examples):
        pair_index = flat_index // ORDINARY_SET_SIDE_COUNT
        side_index = flat_index % ORDINARY_SET_SIDE_COUNT
        count = len(example.road_ids)
        values = tuple(
            _without_selected_anchor_state(row)
            for row in example.oof_features
        )
        if len(values) != count:
            raise ValueError("ordinary pretraining Road features differ")
        object_values[pair_index, side_index] = torch.tensor(
            example.object_features,
            dtype=torch.float32,
        )
        road_values[pair_index, side_index, :count] = torch.tensor(
            values,
            dtype=torch.float32,
        )
        road_mask[pair_index, side_index, :count] = True
        road_sources[pair_index, side_index, :count] = torch.tensor(
            [_road_source_index(value) for value in example.sources],
            dtype=torch.long,
        )
        if example.oof_anchor_release_ready:
            for road_index, relations in enumerate(
                example.oof_anchor_relations
            ):
                if not relations:
                    continue
                relation_values = torch.tensor(
                    relations,
                    dtype=torch.float32,
                )
                if (
                    relation_values.ndim != 2
                    or relation_values.shape[-1] * 2
                    != ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT
                ):
                    raise ValueError(
                        "ordinary pretraining OOF anchor relation differs"
                    )
                precomputed_anchor_context[
                    pair_index,
                    side_index,
                    road_index,
                ] = torch.cat(
                    (
                        relation_values.mean(dim=0),
                        relation_values.amax(dim=0),
                    )
                )
        for left, right, values in example.road_relations:
            road_relations[
                pair_index,
                side_index,
                left,
                right,
            ] = torch.tensor(values, dtype=torch.float32)
            road_relations[
                pair_index,
                side_index,
                right,
                left,
            ] = torch.tensor(values, dtype=torch.float32)
        decision_targets[pair_index, side_index] = int(example.decision)
        decision_task_mask[pair_index, side_index] = True
        member_targets[
            pair_index,
            side_index,
            list(example.target_indices),
        ] = True
        road_task_mask[pair_index, side_index] = True
        cardinality_targets[pair_index, side_index] = len(
            example.target_indices
        )
        sample_weights[pair_index, side_index] = float(
            example.sample_weight
        )
        candidate_reachable[pair_index, side_index] = True
        ownership_targets[
            pair_index,
            side_index,
            :count,
        ] = torch.tensor(example.ownership_targets, dtype=torch.long)
        ownership_task_mask[
            pair_index,
            side_index,
            :count,
        ] = torch.tensor(example.ownership_task_mask, dtype=torch.bool)
        role_targets[
            pair_index,
            side_index,
            :count,
        ] = torch.tensor(example.business_role_targets, dtype=torch.long)
        role_task_mask[
            pair_index,
            side_index,
            :count,
        ] = torch.tensor(example.business_role_task_mask, dtype=torch.bool)
        ownership_sample_weights[pair_index, side_index] = float(
            example.ownership_sample_weight
        )
        role_sample_weights[pair_index, side_index] = float(
            example.business_role_sample_weight
        )
        segment_ids[pair_index][side_index] = str(example.segment_id)
        road_ids[pair_index][side_index] = tuple(example.road_ids)
        if not case_keys[pair_index]:
            case_keys[pair_index] = str(example.case_key)
    return EndToEndOrdinarySetBatch(
        case_keys=tuple(case_keys),
        advance_right_ids=tuple("" for _ in range(pair_count)),
        side_segment_ids=tuple(
            (values[0], values[1]) for values in segment_ids
        ),
        side_group_indices=torch.full(
            side_shape,
            -1,
            dtype=torch.long,
        ),
        side_object_values=object_values,
        side_road_values=road_values,
        side_road_mask=road_mask,
        side_road_source_indices=road_sources,
        side_road_relation_values=road_relations,
        side_access_values=torch.zeros(
            (*side_shape, 1, SIDE_ACCESS_FEATURE_DIM),
            dtype=torch.float32,
        ),
        side_access_mask=torch.zeros(
            (*side_shape, 1),
            dtype=torch.bool,
        ),
        decision_targets=decision_targets,
        decision_task_mask=decision_task_mask,
        road_member_targets=member_targets,
        road_task_mask=road_task_mask,
        road_cardinality_targets=cardinality_targets,
        access_targets=torch.zeros(
            (*side_shape, 1),
            dtype=torch.bool,
        ),
        access_task_mask=torch.zeros(side_shape, dtype=torch.bool),
        sample_weights=sample_weights,
        candidate_reachable=candidate_reachable,
        road_ids=tuple(
            (values[0], values[1]) for values in road_ids
        ),
        access_road_ids=tuple(((), ()) for _ in range(pair_count)),
        side_precomputed_anchor_context=precomputed_anchor_context,
        road_ownership_targets=ownership_targets,
        road_ownership_task_mask=ownership_task_mask,
        road_business_role_targets=role_targets,
        road_business_role_task_mask=role_task_mask,
        road_ownership_sample_weights=ownership_sample_weights,
        road_business_role_sample_weights=role_sample_weights,
    )


def _prepare_example(
    example: EndToEndRecallExample,
    *,
    joint_rows_by_id: Mapping[str, Mapping[str, Any]],
    road_pools: Mapping[tuple[str, str], OrdinarySegmentRoadPool],
) -> dict[str, Any]:
    advance = example.advance_right
    if advance is None:
        raise ValueError("ordinary set example lacks AdvanceRight")
    joint = joint_rows_by_id.get(advance.segment_id)
    if joint is None:
        raise ValueError(f"AdvanceRight joint row is missing: {advance.segment_id}")
    group_indices = {
        row.segment_id: index
        for index, row in enumerate(
            example.dependency_subgraph.ordinary_segments
        )
    }
    ordinary_by_id = {
        row.segment_id: row
        for row in example.dependency_subgraph.ordinary_segments
    }
    anchors_by_id = {
        row.anchor_id: (index, row)
        for index, row in enumerate(
            example.dependency_subgraph.anchors
        )
    }
    sides = []
    for side_name, segment_id in (
        ("source", advance.source_segment_id),
        ("target", advance.target_segment_id),
    ):
        key = (advance.case_key, segment_id)
        if segment_id not in group_indices or key not in road_pools:
            raise ValueError(f"ordinary side dependency is missing: {key}")
        ordinary = ordinary_by_id[segment_id]
        base_side = joint["base_feature"][f"{side_name}_side"]
        if str(base_side.get("owner_segment_id") or "") != segment_id:
            raise ValueError(f"ordinary side owner differs: {key}")
        sides.append(
            {
                "segment_id": segment_id,
                "group_index": group_indices[segment_id],
                "pool": road_pools[key],
                "required_anchors": tuple(
                    anchors_by_id[anchor_id]
                    for anchor_id in ordinary.required_anchor_ids
                    if anchor_id in anchors_by_id
                ),
                "access_rows": tuple(base_side.get("access_candidates") or ()),
                "supervision": joint[f"{side_name}_supervision"],
            }
        )
    return {
        "case_key": advance.case_key,
        "advance_right_id": advance.segment_id,
        "label_weight": advance.label_weight,
        "sides": tuple(sides),
    }


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
            value
            for value in candidate_id.removeprefix("ROAD:").split("|")
            if value
        )
    elif candidate_id.startswith("NODE:"):
        selected_nodes.update(
            value
            for value in candidate_id.removeprefix("NODE:").split("|")
            if value
        )
    road_match = pool.road_ids[road_index] in selected_roads
    start_match = (
        pool.road_start_node_ids[road_index] in selected_nodes
    )
    end_match = pool.road_end_node_ids[road_index] in selected_nodes
    return (
        float(road_match),
        float(start_match),
        float(end_match),
        float(road_match or start_match or end_match),
    )


def _oof_side_anchor_business_state(
    *,
    case_key: str,
    required_anchors: Sequence[tuple[int, Any]],
    predictions: Mapping[
        tuple[str, str],
        AnchorOofBusinessPrediction,
    ],
) -> tuple[int, tuple[str, ...]]:
    if not required_anchors:
        return ORDINARY_ANCHOR_UNRESOLVED, ()
    rows = [
        predictions.get((case_key, str(anchor.anchor_id)))
        for _, anchor in required_anchors
    ]
    if any(row is None for row in rows):
        return ORDINARY_ANCHOR_UNRESOLVED, ()
    states = [row.business_state for row in rows if row is not None]
    if any(state == ORDINARY_ANCHOR_UNRESOLVED for state in states):
        return ORDINARY_ANCHOR_UNRESOLVED, ()
    if any(
        state == ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE
        for state in states
    ):
        return ORDINARY_ANCHOR_PROVEN_NO_EVIDENCE, ()
    return (
        ORDINARY_ANCHOR_SUCCESS,
        tuple(
            row.candidate_id
            for row in rows
            if row is not None
        ),
    )


def _without_selected_anchor_state(
    values: Sequence[float],
) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != SIDE_ROAD_FEATURE_DIM:
        raise ValueError("ordinary selected-anchor Road feature dimension differs")
    return (
        *result[:-ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT],
        *([0.0] * ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT),
    )


def _without_access_selected_anchor_state(
    values: Sequence[float],
) -> tuple[float, ...]:
    result = [float(value) for value in values]
    if len(result) != SIDE_ACCESS_FEATURE_DIM:
        raise ValueError("ordinary access feature dimension differs")
    start = SIDE_ROAD_FEATURE_DIM - ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT
    result[start:SIDE_ROAD_FEATURE_DIM] = (
        [0.0] * ORDINARY_SET_SELECTED_ANCHOR_FEATURE_COUNT
    )
    return tuple(result)


def _road_source_index(value: str) -> int:
    if value == "SWSD":
        return ORDINARY_SET_SOURCE_SWSD
    if value == "RCSD":
        return ORDINARY_SET_SOURCE_RCSD
    raise ValueError(f"ordinary Road source is unsupported: {value}")


__all__ = [
    "AnchorOofBusinessPrediction",
    "EndToEndOrdinarySetBatch",
    "ORDINARY_SET_ROAD_RELATION_DIM",
    "ORDINARY_SET_SIDE_COUNT",
    "ORDINARY_SET_SOURCE_RCSD",
    "ORDINARY_SET_SOURCE_SWSD",
    "ORDINARY_SET_SOURCE_UNRESOLVED",
    "OrdinarySegmentRoadPool",
    "collate_end_to_end_ordinary_set_batch",
    "move_end_to_end_ordinary_set_batch",
    "read_anchor_oof_business_predictions",
    "read_truth_free_ordinary_segment_road_pools",
]
