from __future__ import annotations

import copy
import random
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    group_probabilities,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    HierarchicalTrainingExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_training import (
    HierarchicalFoldResult,
    decision_from_score,
    encode_hierarchical_examples,
    model_state_signature,
    score_hierarchical_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p9_models import (
    SchemeAP2P3P9Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p9_source import (
    EncodedSourceRow,
    SourceFoldTransform,
    build_source_fold_transform,
    encode_source_rows,
)


_TARGET_IDS = {
    "KEEP_SWSD": 0,
    "MIXED_CARRIER": 1,
    "REVIEW_FALLBACK": 2,
    "USE_RCSD": 3,
}


class CarrierSourceResidualAdapter(nn.Module):
    def __init__(
        self,
        *,
        source_dim: int,
        hidden_dim: int,
        bottleneck_dim: int,
        dropout: float,
    ) -> None:
        super().__init__()
        if min(source_dim, hidden_dim, bottleneck_dim) < 1:
            raise ValueError("source adapter dimensions must be positive")
        self.source_dim = source_dim
        self.network = nn.Sequential(
            nn.Linear(source_dim + len(_TARGET_IDS), hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, bottleneck_dim),
            nn.GELU(),
            nn.Linear(bottleneck_dim, 1),
        )

    def forward(
        self,
        source_values: torch.Tensor,
        target_ids: torch.Tensor,
    ) -> torch.Tensor:
        if source_values.ndim != 2 or source_values.shape[1] != self.source_dim:
            raise ValueError("source adapter input shape differs")
        if target_ids.ndim != 1 or target_ids.shape[0] != source_values.shape[0]:
            raise ValueError("source adapter target shape differs")
        target_one_hot = nn.functional.one_hot(
            target_ids,
            num_classes=len(_TARGET_IDS),
        ).to(dtype=source_values.dtype)
        return self.network(
            torch.cat((source_values, target_one_hot), dim=1)
        ).squeeze(-1)


@dataclass
class SourceAdapterFoldResult:
    model: CarrierSourceResidualAdapter
    transform: SourceFoldTransform
    training_summary: dict[str, Any]
    held_out_scores: list[dict[str, Any]]


def train_source_adapter_fold(
    control: HierarchicalFoldResult,
    examples: Sequence[HierarchicalTrainingExample],
    source_rows: Sequence[Mapping[str, Any]],
    *,
    promotion_fields: Sequence[str],
    config: SchemeAP2P3P9Config,
    held_out_fold: int,
    seed: int,
) -> SourceAdapterFoldResult:
    summary = control.training_summary
    if (
        int(summary["held_out_fold"]) != held_out_fold
        or int(summary["seed"]) != seed
    ):
        raise ValueError("Control checkpoint and adapter fold identity differ")
    train_cases = tuple(str(value) for value in summary["train_case_keys"])
    inner_cases = tuple(
        str(value) for value in summary["inner_validation_case_keys"]
    )
    held_out_cases = tuple(
        str(value) for value in summary["held_out_case_keys"]
    )
    transform = build_source_fold_transform(
        source_rows,
        fields=promotion_fields,
        train_case_keys=train_cases,
    )
    encoded_source = encode_source_rows(source_rows, transform)
    source_by_group = {row.group_id: row for row in encoded_source}
    if len(source_by_group) != len(examples):
        raise ValueError("encoded source and Control example denominators differ")

    encoded_control = encode_hierarchical_examples(examples, control.transform)
    train_indices = [
        index
        for index, example in enumerate(examples)
        if example.group.case_key in set(train_cases)
        and source_by_group[example.group.group_id].source_applicable
    ]
    inner_indices = [
        index
        for index, example in enumerate(examples)
        if example.group.case_key in set(inner_cases)
        and source_by_group[example.group.group_id].source_applicable
    ]
    held_out_indices = [
        index
        for index, example in enumerate(examples)
        if example.group.case_key in set(held_out_cases)
    ]
    if not train_indices or not inner_indices or not held_out_indices:
        raise ValueError("P9 adapter fold lacks train/inner/held-out scope")

    device = torch.device("cpu")
    torch.set_num_threads(config.engine_config.base_config.torch_num_threads)
    control.model.eval()
    for value in control.model.parameters():
        value.requires_grad_(False)
    train_control_scores = score_hierarchical_examples(
        control.model,
        examples,
        encoded_control,
        indices=train_indices,
        batch_group_count=config.adapter_batch_group_count,
        device=device,
    )
    inner_control_scores = score_hierarchical_examples(
        control.model,
        examples,
        encoded_control,
        indices=inner_indices,
        batch_group_count=config.adapter_batch_group_count,
        device=device,
    )
    held_out_control_scores = control.held_out_scores

    initialization_seed = seed * 10_000 + held_out_fold
    random.seed(initialization_seed)
    torch.manual_seed(initialization_seed)
    torch.use_deterministic_algorithms(True)
    adapter = CarrierSourceResidualAdapter(
        source_dim=transform.pooled_dimension,
        hidden_dim=config.adapter_hidden_dim,
        bottleneck_dim=config.adapter_bottleneck_dim,
        dropout=config.adapter_dropout,
    ).to(device)
    adapter_parameter_count = parameter_count(adapter)
    control_parameter_count = int(summary["parameter_count"])
    if adapter_parameter_count > config.adapter_max_parameter_count:
        raise ValueError("source adapter exceeds the 300K parameter gate")
    if (
        adapter_parameter_count + control_parameter_count
        > config.total_max_parameter_count
    ):
        raise ValueError("Control plus source adapter exceeds the 3.2M gate")

    optimizer = torch.optim.AdamW(
        adapter.parameters(),
        lr=config.adapter_learning_rate,
        weight_decay=config.adapter_weight_decay,
    )
    best_state: dict[str, torch.Tensor] | None = None
    best_inner_loss = float("inf")
    best_epoch = 0
    epochs_without_improvement = 0
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    for epoch in range(1, config.adapter_max_epochs + 1):
        adapter.train()
        order = list(range(len(train_control_scores)))
        random.Random(initialization_seed * 1_000 + epoch).shuffle(order)
        train_total = 0.0
        train_weight = 0
        for start in range(0, len(order), config.adapter_batch_group_count):
            rows = [
                train_control_scores[index]
                for index in order[
                    start : start + config.adapter_batch_group_count
                ]
            ]
            optimizer.zero_grad(set_to_none=True)
            loss = _adapter_loss(
                adapter,
                rows,
                source_by_group,
                examples,
                device=device,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                adapter.parameters(), max_norm=5.0
            )
            optimizer.step()
            train_total += float(loss.item()) * len(rows)
            train_weight += len(rows)
        adapter.eval()
        with torch.no_grad():
            inner_loss = float(
                _adapter_loss(
                    adapter,
                    inner_control_scores,
                    source_by_group,
                    examples,
                    device=device,
                ).item()
            )
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_total / max(1, train_weight),
                "inner_loss": inner_loss,
            }
        )
        if inner_loss < best_inner_loss - 1e-6:
            best_inner_loss = inner_loss
            best_epoch = epoch
            best_state = copy.deepcopy(adapter.state_dict())
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= config.adapter_patience:
                break
    if best_state is None:
        raise ValueError("source adapter fold did not produce a model state")
    adapter.load_state_dict(best_state)
    adapter.eval()
    inference_started = time.perf_counter()
    held_out_scores = score_source_treatment(
        held_out_control_scores,
        adapter,
        source_by_group,
        device=device,
    )
    inference_seconds = time.perf_counter() - inference_started
    return SourceAdapterFoldResult(
        model=adapter,
        transform=transform,
        held_out_scores=held_out_scores,
        training_summary={
            "seed": seed,
            "held_out_fold": held_out_fold,
            "train_case_keys": list(train_cases),
            "inner_validation_case_keys": list(inner_cases),
            "held_out_case_keys": list(held_out_cases),
            "train_source_group_count": len(train_indices),
            "inner_source_group_count": len(inner_indices),
            "held_out_group_count": len(held_out_indices),
            "held_out_source_group_count": sum(
                source_by_group[examples[index].group.group_id].source_applicable
                for index in held_out_indices
            ),
            "best_epoch": best_epoch,
            "best_inner_loss": best_inner_loss,
            "epochs_ran": len(history),
            "history": history,
            "source_dimension": transform.pooled_dimension,
            "source_transform_signature": transform.signature,
            "adapter_parameter_count": adapter_parameter_count,
            "control_parameter_count": control_parameter_count,
            "total_parameter_count": (
                adapter_parameter_count + control_parameter_count
            ),
            "adapter_model_signature": model_state_signature(adapter),
            "control_model_signature": str(summary["model_signature"]),
            "wall_seconds": time.perf_counter() - started,
            "inference_seconds": inference_seconds,
            "device": str(device),
        },
    )


def score_source_treatment(
    control_scores: Sequence[Mapping[str, Any]],
    adapter: CarrierSourceResidualAdapter,
    source_by_group: Mapping[str, EncodedSourceRow],
    *,
    device: torch.device,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    adapter.eval()
    with torch.no_grad():
        for control_row in control_scores:
            group_id = str(control_row["group_id"])
            source = source_by_group[group_id]
            if not source.source_applicable:
                rows.append(dict(control_row))
                continue
            targets = [
                _target_id(value)
                for value in control_row["candidate_targets"]
            ]
            source_tensor = torch.tensor(
                [source.values] * len(targets),
                dtype=torch.float32,
                device=device,
            )
            target_tensor = torch.tensor(
                targets,
                dtype=torch.long,
                device=device,
            )
            residuals = adapter(source_tensor, target_tensor)
            candidate_scores = torch.tensor(
                control_row["candidate_scores"],
                dtype=torch.float32,
                device=device,
            ) + residuals
            probabilities = torch.softmax(candidate_scores, dim=0)
            correctness = [
                float(value)
                for value in control_row[
                    "candidate_correctness_probabilities"
                ]
            ]
            probability_values = probabilities.cpu().tolist()
            utility_values = [
                probability * correctness_probability
                for probability, correctness_probability in zip(
                    probability_values,
                    correctness,
                    strict=True,
                )
            ]
            candidate_ids = [
                str(value) for value in control_row["candidate_ids"]
            ]
            selected_index = max(
                range(len(candidate_ids)),
                key=lambda index: (
                    utility_values[index],
                    probability_values[index],
                    candidate_ids[index],
                ),
            )
            row = dict(control_row)
            row.update(
                {
                    "candidate_scores": candidate_scores.cpu().tolist(),
                    "candidate_probabilities": probability_values,
                    "candidate_utilities": utility_values,
                    "selected_index": selected_index,
                    "selected_candidate_id": candidate_ids[selected_index],
                    "selected_target": row["candidate_targets"][
                        selected_index
                    ],
                    "carrier_confidence": utility_values[selected_index],
                }
            )
            rows.append(row)
    return sorted(rows, key=lambda row: str(row["group_id"]))


def build_control_treatment_decisions(
    *,
    control_scores: Sequence[Mapping[str, Any]],
    treatment_scores: Sequence[Mapping[str, Any]],
    control: HierarchicalFoldResult,
    adapter: SourceAdapterFoldResult,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    control_signature = str(control.training_summary["model_signature"])
    treatment_signature = (
        f"{control_signature}+"
        f"{adapter.training_summary['adapter_model_signature']}"
    )
    control_decisions = [
        decision_from_score(
            row,
            control.thresholds,
            seed=seed,
            model_signature=control_signature,
        )
        for row in control_scores
    ]
    treatment_decisions = [
        decision_from_score(
            row,
            control.thresholds,
            seed=seed,
            model_signature=treatment_signature,
        )
        for row in treatment_scores
    ]
    return control_decisions, treatment_decisions


def _adapter_loss(
    adapter: CarrierSourceResidualAdapter,
    score_rows: Sequence[Mapping[str, Any]],
    source_by_group: Mapping[str, EncodedSourceRow],
    examples: Sequence[HierarchicalTrainingExample],
    *,
    device: torch.device,
) -> torch.Tensor:
    if not score_rows:
        raise ValueError("source adapter loss has no groups")
    example_by_id = {
        example.group.group_id: example for example in examples
    }
    all_source: list[tuple[float, ...]] = []
    all_target_ids: list[int] = []
    all_base_scores: list[float] = []
    all_group_indices: list[int] = []
    truth_mask: list[bool] = []
    group_weights: list[float] = []
    for group_index, row in enumerate(score_rows):
        group_id = str(row["group_id"])
        source = source_by_group[group_id]
        if not source.source_applicable:
            raise ValueError("no-source group reached adapter loss")
        candidate_ids = [str(value) for value in row["candidate_ids"]]
        targets = [str(value) for value in row["candidate_targets"]]
        truth_id = str(row["truth_candidate_id"])
        all_source.extend([source.values] * len(candidate_ids))
        all_target_ids.extend(_target_id(value) for value in targets)
        all_base_scores.extend(float(value) for value in row["candidate_scores"])
        all_group_indices.extend([group_index] * len(candidate_ids))
        truth_mask.extend(value == truth_id for value in candidate_ids)
        group_weights.append(
            float(example_by_id[group_id].group.sample_weight)
        )
    source_tensor = torch.tensor(
        all_source, dtype=torch.float32, device=device
    )
    target_tensor = torch.tensor(
        all_target_ids, dtype=torch.long, device=device
    )
    base_tensor = torch.tensor(
        all_base_scores, dtype=torch.float32, device=device
    )
    group_index_tensor = torch.tensor(
        all_group_indices, dtype=torch.long, device=device
    )
    truth_tensor = torch.tensor(
        truth_mask, dtype=torch.bool, device=device
    )
    weight_tensor = torch.tensor(
        group_weights, dtype=torch.float32, device=device
    )
    candidate_scores = base_tensor + adapter(source_tensor, target_tensor)
    probabilities = group_probabilities(
        candidate_scores,
        group_index_tensor,
        len(score_rows),
    )
    truth_probability = torch.zeros_like(weight_tensor)
    truth_probability.scatter_add_(
        0,
        group_index_tensor,
        probabilities * truth_tensor.to(probabilities.dtype),
    )
    each = -torch.log(truth_probability.clamp_min(1e-12))
    return torch.sum(each * weight_tensor) / weight_tensor.sum().clamp_min(
        1e-12
    )


def _target_id(value: Any) -> int:
    text = str(value)
    if text not in _TARGET_IDS:
        raise ValueError(f"unsupported carrier target: {text}")
    return _TARGET_IDS[text]


__all__ = [
    "CarrierSourceResidualAdapter",
    "SourceAdapterFoldResult",
    "build_control_treatment_decisions",
    "score_source_treatment",
    "train_source_adapter_fold",
]
