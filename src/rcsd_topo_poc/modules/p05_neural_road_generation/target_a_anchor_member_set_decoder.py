from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_graph import (
    build_anchor_dependency_batches,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ANCHOR_TYPE_NODE,
    ANCHOR_TYPE_ROAD,
    TargetABatchTensors,
    TargetAJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    move_training_batch,
)


@dataclass(frozen=True)
class AnchorMemberSetSelection:
    selected_members: torch.Tensor
    type_prediction: torch.Tensor
    cardinality_prediction: torch.Tensor
    type_probability: torch.Tensor
    cardinality_probability: torch.Tensor
    exact_set_geometric_probability: torch.Tensor
    inclusion_margin: torch.Tensor
    confidence: torch.Tensor


def decode_anchor_member_sets(
    outputs: Mapping[str, torch.Tensor],
    batch: TargetABatchTensors,
    *,
    member_probability_threshold: float | None = None,
) -> AnchorMemberSetSelection:
    """Decode one exact typed subset from atomic inference members."""
    if (
        member_probability_threshold is not None
        and not 0.0 < member_probability_threshold < 1.0
    ):
        raise ValueError("anchor member threshold must be in (0, 1)")
    member_logits = outputs.get("anchor_member_logits")
    type_logits = outputs.get("anchor_type_logits")
    cardinality_logits = outputs.get("anchor_cardinality_logits")
    member_mask = batch.anchor_member_mask
    member_is_road = batch.anchor_member_is_road
    if (
        member_logits is None
        or type_logits is None
        or cardinality_logits is None
        or member_mask is None
        or member_is_road is None
    ):
        raise ValueError("atomic anchor decoding lacks member/type/cardinality")
    if (
        member_logits.shape != member_mask.shape
        or member_logits.shape != member_is_road.shape
    ):
        raise ValueError("atomic anchor member tensor shapes differ")
    if type_logits.shape != member_logits.shape[:-1] + (2,):
        raise ValueError("atomic anchor type shape differs")
    if cardinality_logits.shape[:3] != type_logits.shape:
        raise ValueError("atomic anchor cardinality shape differs")

    type_probabilities = torch.softmax(type_logits, dim=-1)
    type_prediction = type_logits.argmax(dim=-1)
    selected_cardinality_logits = torch.gather(
        cardinality_logits,
        -2,
        type_prediction.unsqueeze(-1).unsqueeze(-1).expand(
            *type_prediction.shape,
            1,
            cardinality_logits.shape[-1],
        ),
    ).squeeze(-2)
    cardinality_probabilities = torch.softmax(
        selected_cardinality_logits,
        dim=-1,
    )
    cardinality_prediction = (
        selected_cardinality_logits.argmax(dim=-1) + 1
    )
    selected_type_is_road = type_prediction.eq(ANCHOR_TYPE_ROAD)
    same_type = member_mask & (
        member_is_road == selected_type_is_road.unsqueeze(-1)
    )
    available_count = same_type.sum(dim=-1)
    if bool((available_count < 1).any()):
        raise ValueError("atomic anchor predicted an unavailable object type")
    member_probabilities = torch.sigmoid(member_logits).clamp(
        1e-7,
        1.0 - 1e-7,
    )
    ranked = member_logits.masked_fill(
        ~same_type,
        torch.finfo(member_logits.dtype).min,
    ).argsort(dim=-1, descending=True)
    if member_probability_threshold is None:
        cardinality_prediction = torch.minimum(
            cardinality_prediction,
            available_count,
        )
        rank_indices = torch.arange(
            member_logits.shape[-1],
            device=member_logits.device,
        )
        rank_selected = rank_indices < cardinality_prediction.unsqueeze(-1)
        selected = torch.zeros_like(member_mask)
        selected.scatter_(-1, ranked, rank_selected)
        selected &= same_type
    else:
        selected = same_type & member_probabilities.ge(
            member_probability_threshold
        )
        empty = ~selected.any(dim=-1)
        top_one = ranked[..., 0]
        fallback = torch.zeros_like(selected)
        fallback.scatter_(
            -1,
            top_one.unsqueeze(-1),
            True,
        )
        selected |= fallback & empty.unsqueeze(-1)
        selected &= same_type
        cardinality_prediction = selected.sum(dim=-1)
    exact_log_probability = torch.where(
        selected,
        torch.log(member_probabilities),
        torch.log1p(-member_probabilities),
    )
    typed_count = same_type.sum(dim=-1).clamp_min(1)
    exact_geometric_probability = torch.exp(
        (
            exact_log_probability
            * same_type.to(exact_log_probability.dtype)
        ).sum(dim=-1)
        / typed_count.to(exact_log_probability.dtype)
    )
    min_included = member_probabilities.masked_fill(
        ~selected,
        1.0,
    ).amin(dim=-1)
    max_excluded = member_probabilities.masked_fill(
        ~same_type | selected,
        0.0,
    ).amax(dim=-1)
    type_probability = torch.gather(
        type_probabilities,
        -1,
        type_prediction.unsqueeze(-1),
    ).squeeze(-1)
    cardinality_probability = torch.gather(
        cardinality_probabilities,
        -1,
        cardinality_prediction.sub(1).clamp_max(
            cardinality_probabilities.shape[-1] - 1
        ).unsqueeze(-1),
    ).squeeze(-1)
    if member_probability_threshold is not None:
        cardinality_probability = torch.minimum(
            min_included,
            1.0 - max_excluded,
        )
    confidence = torch.stack(
        (
            type_probability,
            cardinality_probability,
            exact_geometric_probability,
        ),
        dim=-1,
    ).amin(dim=-1)
    return AnchorMemberSetSelection(
        selected_members=selected,
        type_prediction=type_prediction,
        cardinality_prediction=cardinality_prediction,
        type_probability=type_probability,
        cardinality_probability=cardinality_probability,
        exact_set_geometric_probability=exact_geometric_probability,
        inclusion_margin=min_included - max_excluded,
        confidence=confidence,
    )


def predict_anchor_member_sets(
    model: TargetAJointNetwork,
    examples: Sequence[AnchorPretrainExample],
    *,
    config: TargetAConfig,
    device: torch.device,
    max_anchor_count: int = 128,
    member_probability_threshold: float | None = None,
) -> list[dict[str, Any]]:
    model.eval()
    rows = []
    with torch.no_grad():
        for packed in build_anchor_dependency_batches(
            examples,
            max_anchor_count=max_anchor_count,
        ):
            moved = move_training_batch(packed.training_batch, device)
            outputs = model(moved.tensors)
            decoded = decode_anchor_member_sets(
                outputs,
                moved.tensors,
                member_probability_threshold=member_probability_threshold,
            )
            status_probabilities = torch.softmax(
                outputs["anchor_status_logits"],
                dim=-1,
            )
            gate_probabilities = (
                torch.softmax(outputs["anchor_gate_logits"], dim=-1)[..., 1]
                if config.learned_anchor_gate
                else torch.ones_like(decoded.confidence)
            )
            for batch_index, group in enumerate(packed.groups):
                example = group.examples[0]
                selected = decoded.selected_members[batch_index, 0]
                selected_indices = tuple(
                    int(index)
                    for index in selected.nonzero(as_tuple=False)
                    .flatten()
                    .tolist()
                )
                acceptable = set(example.member_acceptable_sets)
                set_correct = (
                    example.member_supervised
                    and selected_indices in acceptable
                )
                status_prediction = int(
                    status_probabilities[batch_index, 0].argmax().item()
                )
                gate_probability = float(
                    gate_probabilities[batch_index, 0].item()
                )
                base_released = bool(
                    status_prediction
                    == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
                    and gate_probability >= config.anchor_gate_pass_threshold
                )
                success_probability = float(
                    status_probabilities[
                        batch_index,
                        0,
                        ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS],
                    ].item()
                )
                set_confidence = float(
                    decoded.confidence[batch_index, 0].item()
                )
                selected_ids = tuple(
                    example.structural_member_ids[index]
                    for index in selected_indices
                )
                rows.append(
                    {
                        "sample_id": example.sample_id,
                        "case_key": example.case_key,
                        "anchor_id": example.anchor_id,
                        "fold": example.fold,
                        "status_prediction": status_prediction,
                        "status_truth": example.status_label,
                        "status_supervised": example.status_supervised,
                        "gate_probability": gate_probability,
                        "base_released": base_released,
                        "member_supervised": example.member_supervised,
                        "member_only_supervised": bool(
                            example.member_supervised
                            and not example.candidate_supervised
                        ),
                        "candidate_supervised": example.candidate_supervised,
                        "selected_member_indices": selected_indices,
                        "selected_member_ids": selected_ids,
                        "selected_object_type": (
                            "ROAD"
                            if int(
                                decoded.type_prediction[
                                    batch_index,
                                    0,
                                ].item()
                            )
                            == ANCHOR_TYPE_ROAD
                            else "NODE"
                        ),
                        "selected_cardinality": int(
                            decoded.cardinality_prediction[
                                batch_index,
                                0,
                            ].item()
                        ),
                        "type_probability": float(
                            decoded.type_probability[
                                batch_index,
                                0,
                            ].item()
                        ),
                        "cardinality_probability": float(
                            decoded.cardinality_probability[
                                batch_index,
                                0,
                            ].item()
                        ),
                        "exact_set_geometric_probability": float(
                            decoded.exact_set_geometric_probability[
                                batch_index,
                                0,
                            ].item()
                        ),
                        "inclusion_margin": float(
                            decoded.inclusion_margin[
                                batch_index,
                                0,
                            ].item()
                        ),
                        "set_confidence": set_confidence,
                        "joint_score": min(
                            success_probability,
                            gate_probability,
                            set_confidence,
                        ),
                        "member_set_correct": set_correct,
                        "label_reason": example.label_reason,
                    }
                )
    return sorted(
        rows,
        key=lambda row: (
            str(row["case_key"]),
            str(row["anchor_id"]),
        ),
    )


def zero_unsafe_member_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    unsafe = [
        float(row["joint_score"])
        for row in rows
        if row["base_released"]
        and (
            not row["member_supervised"]
            or not row["member_set_correct"]
        )
    ]
    if not unsafe:
        return 0.0
    return math.nextafter(max(unsafe), math.inf)


def anchor_member_set_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    release_threshold: float,
) -> dict[str, Any]:
    supervised = [row for row in rows if row["member_supervised"]]
    member_only = [
        row for row in supervised if row["member_only_supervised"]
    ]
    automatic = [
        row
        for row in rows
        if row["base_released"]
        and float(row["joint_score"]) >= release_threshold
    ]
    correct_automatic = [
        row
        for row in automatic
        if row["member_supervised"] and row["member_set_correct"]
    ]
    unsafe = [
        row
        for row in automatic
        if row["member_supervised"] and not row["member_set_correct"]
    ]
    review = [
        row for row in automatic if not row["member_supervised"]
    ]
    by_type: Counter[str] = Counter()
    by_type_correct: Counter[str] = Counter()
    by_cardinality: Counter[str] = Counter()
    by_cardinality_correct: Counter[str] = Counter()
    for row in supervised:
        object_type = str(row["selected_object_type"])
        cardinality = str(row["selected_cardinality"])
        by_type[object_type] += 1
        by_type_correct[object_type] += int(row["member_set_correct"])
        by_cardinality[cardinality] += 1
        by_cardinality_correct[cardinality] += int(
            row["member_set_correct"]
        )
    denominator = max(len(supervised), 1)
    member_only_denominator = max(len(member_only), 1)
    return {
        "row_count": len(rows),
        "member_supervised_count": len(supervised),
        "member_set_exact_count": sum(
            bool(row["member_set_correct"]) for row in supervised
        ),
        "member_set_exact": sum(
            bool(row["member_set_correct"]) for row in supervised
        )
        / denominator,
        "member_only_supervised_count": len(member_only),
        "member_only_exact_count": sum(
            bool(row["member_set_correct"]) for row in member_only
        ),
        "member_only_exact": sum(
            bool(row["member_set_correct"]) for row in member_only
        )
        / member_only_denominator,
        "release_threshold": release_threshold,
        "automatic_count": len(automatic),
        "automatic_correct_count": len(correct_automatic),
        "unsafe_auto_count": len(unsafe),
        "review_auto_count": len(review),
        "automatic_correct_coverage": len(correct_automatic)
        / max(len(rows), 1),
        "exact_by_predicted_type": {
            key: {
                "correct": by_type_correct[key],
                "total": total,
                "exact": by_type_correct[key] / total,
            }
            for key, total in sorted(by_type.items())
        },
        "exact_by_predicted_cardinality": {
            key: {
                "correct": by_cardinality_correct[key],
                "total": total,
                "exact": by_cardinality_correct[key] / total,
            }
            for key, total in sorted(
                by_cardinality.items(),
                key=lambda item: int(item[0]),
            )
        },
    }


__all__ = [
    "AnchorMemberSetSelection",
    "anchor_member_set_metrics",
    "decode_anchor_member_sets",
    "predict_anchor_member_sets",
    "zero_unsafe_member_threshold",
]
