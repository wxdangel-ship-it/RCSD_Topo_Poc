from __future__ import annotations

import copy
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_data import (
    TASK_CLASSES,
    JunctionFirstBatch,
    JunctionFirstExample,
    collate_junction_first,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_first_network import (
    JunctionFirstConfig,
    JunctionFirstNetwork,
)


TASK_LOSS_WEIGHTS: Mapping[str, float] = {
    "t07_step1": 1.0,
    "t07_step2": 1.0,
    "route": 1.0,
    "t07_relation": 0.75,
    "t03_surface": 0.50,
    "t03_association": 0.50,
    "t03_relation": 0.75,
    "t04_surface": 0.50,
    "t04_relation": 0.75,
    "t05_surface_source": 0.50,
    "t05_junctionization": 1.0,
    "t05_graph": 0.75,
    "t05_relation": 0.75,
    "anchor_status": 1.50,
}


@dataclass(frozen=True)
class JunctionFirstTrainingResult:
    model: JunctionFirstNetwork
    best_epoch: int
    history: tuple[Mapping[str, float], ...]
    wall_seconds: float


def compute_junction_first_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionFirstBatch,
    *,
    class_weights: Mapping[str, torch.Tensor] | None = None,
) -> tuple[torch.Tensor, dict[str, float]]:
    components: list[tuple[float, torch.Tensor]] = []
    metrics: dict[str, float] = {}
    for task, task_weight in TASK_LOSS_WEIGHTS.items():
        loss = _weighted_masked_cross_entropy(
            outputs[f"{task}_logits"],
            batch.task_labels[task],
            batch.task_masks[task],
            batch.sample_weights,
            None if class_weights is None else class_weights.get(task),
        )
        components.append((task_weight, loss))
        metrics[f"{task}_loss"] = float(loss.detach().item())

    candidate_loss = _candidate_acceptable_nll(
        outputs["candidate_logits"],
        batch.candidate_mask,
        batch.candidate_acceptable,
        batch.candidate_task_mask,
        batch.sample_weights,
    )
    member_loss = _member_acceptable_set_loss(
        outputs["member_logits"],
        batch,
    )
    member_type_loss, member_cardinality_loss = _member_structure_loss(
        outputs,
        batch,
    )
    components.extend(
        (
            (1.0, candidate_loss),
            (1.0, member_loss),
            (0.5, member_type_loss),
            (0.5, member_cardinality_loss),
        )
    )
    metrics.update(
        {
            "candidate_loss": float(candidate_loss.detach().item()),
            "member_loss": float(member_loss.detach().item()),
            "member_type_loss": float(member_type_loss.detach().item()),
            "member_cardinality_loss": float(
                member_cardinality_loss.detach().item()
            ),
        }
    )
    denominator = sum(weight for weight, _ in components)
    total = sum(weight * value for weight, value in components) / denominator
    metrics["total_loss"] = float(total.detach().item())
    return total, metrics


def train_junction_first_canary(
    examples: Sequence[JunctionFirstExample],
    *,
    validation_fold: int,
    seed: int,
    epochs: int = 24,
    batch_size: int = 24,
    learning_rate: float = 2e-4,
    weight_decay: float = 2e-4,
    device: torch.device | str = "cpu",
    config: JunctionFirstConfig = JunctionFirstConfig(),
    epoch_callback: Callable[[Mapping[str, float]], None] | None = None,
) -> JunctionFirstTrainingResult:
    if epochs < 3 or batch_size < 1:
        raise ValueError("junction canary training controls are invalid")
    train_rows = [row for row in examples if row.fold != validation_fold]
    validation_rows = [row for row in examples if row.fold == validation_fold]
    if not train_rows or not validation_rows:
        raise ValueError("junction canary train/validation split is empty")

    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    model = JunctionFirstNetwork(config).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    class_weights = {
        task: value.to(device)
        for task, value in build_class_weights(train_rows).items()
    }
    history: list[dict[str, float]] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_score: tuple[float, float, float] | None = None
    best_epoch = -1
    started = time.perf_counter()
    for epoch in range(1, epochs + 1):
        model.train()
        forcing = teacher_forcing_ratio(epoch, epochs)
        train_loss = 0.0
        train_count = 0
        order = list(range(len(train_rows)))
        random.Random(seed + epoch).shuffle(order)
        for start in range(0, len(order), batch_size):
            rows = [train_rows[index] for index in order[start : start + batch_size]]
            batch = collate_junction_first(rows).to(device)
            optimizer.zero_grad(set_to_none=True)
            outputs = model(
                batch,
                teacher_labels=batch.task_labels,
                teacher_masks=batch.task_masks,
                teacher_forcing_ratio=forcing,
            )
            loss, _ = compute_junction_first_loss(
                outputs,
                batch,
                class_weights=class_weights,
            )
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += float(loss.detach().item()) * len(rows)
            train_count += len(rows)

        validation = evaluate_junction_first(
            model,
            validation_rows,
            batch_size=batch_size,
            device=device,
            class_weights=class_weights,
        )
        row = {
            "epoch": float(epoch),
            "teacher_forcing_ratio": forcing,
            "train_loss": train_loss / max(1, train_count),
            **validation,
        }
        history.append(row)
        if epoch_callback is not None:
            epoch_callback(row)
        score = (
            validation["business_chain_exact"],
            validation["complete_anchor_exact"],
            -validation["validation_loss"],
        )
        if best_score is None or score > best_score:
            best_score = score
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
    if best_state is None:
        raise RuntimeError("junction canary produced no checkpoint")
    model.load_state_dict(best_state)
    return JunctionFirstTrainingResult(
        model=model,
        best_epoch=best_epoch,
        history=tuple(history),
        wall_seconds=time.perf_counter() - started,
    )


@torch.no_grad()
def evaluate_junction_first(
    model: JunctionFirstNetwork,
    examples: Sequence[JunctionFirstExample],
    *,
    batch_size: int,
    device: torch.device | str,
    class_weights: Mapping[str, torch.Tensor] | None = None,
) -> dict[str, float]:
    model.eval()
    task_correct = {task: 0 for task in TASK_CLASSES}
    task_total = {task: 0 for task in TASK_CLASSES}
    candidate_correct = candidate_total = 0
    member_correct = member_total = 0
    anchor_correct = anchor_total = 0
    dangerous_success = review_success = 0
    chain_correct = chain_total = 0
    loss_sum = 0.0
    row_count = 0
    for start in range(0, len(examples), batch_size):
        rows = examples[start : start + batch_size]
        batch = collate_junction_first(rows).to(device)
        outputs = model(batch, teacher_forcing_ratio=0.0)
        loss, _ = compute_junction_first_loss(
            outputs,
            batch,
            class_weights=class_weights,
        )
        loss_sum += float(loss.item()) * len(rows)
        row_count += len(rows)
        predictions = {
            task: outputs[f"{task}_logits"].argmax(dim=-1)
            for task in TASK_CLASSES
        }
        for task in TASK_CLASSES:
            mask = batch.task_masks[task]
            task_correct[task] += int(
                ((predictions[task] == batch.task_labels[task]) & mask).sum().item()
            )
            task_total[task] += int(mask.sum().item())

        candidate_prediction = outputs["candidate_logits"].masked_fill(
            ~batch.candidate_mask,
            torch.finfo(outputs["candidate_logits"].dtype).min,
        ).argmax(dim=-1)
        candidate_exact = batch.candidate_acceptable.gather(
            1,
            candidate_prediction.unsqueeze(-1),
        ).squeeze(-1)
        candidate_correct += int(
            (candidate_exact & batch.candidate_task_mask).sum().item()
        )
        candidate_total += int(batch.candidate_task_mask.sum().item())

        decoded_members = decode_member_sets(outputs, batch)
        member_exact = (
            (
                decoded_members.unsqueeze(1) == batch.member_acceptable_sets
            ).all(dim=-1)
            & batch.member_acceptable_set_mask
        ).any(dim=-1)
        member_correct += int((member_exact & batch.member_task_mask).sum().item())
        member_total += int(batch.member_task_mask.sum().item())

        status_mask = batch.task_masks["anchor_status"]
        status_exact = predictions["anchor_status"] == batch.task_labels["anchor_status"]
        true_success = batch.task_labels["anchor_status"].eq(0) & status_mask
        predicted_success = predictions["anchor_status"].eq(0)
        full_set_exact = torch.where(
            batch.member_task_mask,
            member_exact,
            torch.where(batch.candidate_task_mask, candidate_exact, torch.zeros_like(status_exact)),
        )
        set_verifiable = batch.member_task_mask | batch.candidate_task_mask
        complete = status_exact & (~true_success | (set_verifiable & full_set_exact))
        anchor_correct += int((complete & status_mask).sum().item())
        anchor_total += int(status_mask.sum().item())
        dangerous_success += int(
            (predicted_success & status_mask & (~true_success | ~full_set_exact)).sum().item()
        )
        review_success += int((predicted_success & ~status_mask).sum().item())

        for index in range(len(rows)):
            supervised_tasks = [
                task for task in TASK_CLASSES if bool(batch.task_masks[task][index])
            ]
            if not supervised_tasks:
                continue
            exact = all(
                int(predictions[task][index]) == int(batch.task_labels[task][index])
                for task in supervised_tasks
            )
            if bool(true_success[index]):
                exact = exact and bool(set_verifiable[index]) and bool(full_set_exact[index])
            chain_total += 1
            chain_correct += int(exact)

    result = {
        "validation_loss": loss_sum / max(1, row_count),
        "candidate_exact": candidate_correct / max(1, candidate_total),
        "candidate_total": float(candidate_total),
        "member_exact": member_correct / max(1, member_total),
        "member_total": float(member_total),
        "complete_anchor_exact": anchor_correct / max(1, anchor_total),
        "complete_anchor_total": float(anchor_total),
        "dangerous_success_count": float(dangerous_success),
        "review_success_count": float(review_success),
        "business_chain_exact": chain_correct / max(1, chain_total),
        "business_chain_total": float(chain_total),
    }
    for task in TASK_CLASSES:
        result[f"{task}_accuracy"] = task_correct[task] / max(1, task_total[task])
        result[f"{task}_total"] = float(task_total[task])
    return result


def decode_member_sets(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionFirstBatch,
) -> torch.Tensor:
    selected_type = outputs["member_type_logits"].argmax(dim=-1)
    cardinality = outputs["member_cardinality_logits"].argmax(dim=-1) + 1
    type_mask = torch.where(
        selected_type.unsqueeze(-1).bool(),
        batch.member_is_road,
        ~batch.member_is_road,
    ) & batch.member_mask
    scores = outputs["member_logits"].masked_fill(
        ~type_mask,
        torch.finfo(outputs["member_logits"].dtype).min,
    )
    decoded = torch.zeros_like(batch.member_mask)
    for index in range(scores.shape[0]):
        available = int(type_mask[index].sum().item())
        if available < 1:
            continue
        count = min(int(cardinality[index].item()), available)
        selected = scores[index].topk(count).indices
        decoded[index, selected] = True
    return decoded


def build_class_weights(
    examples: Sequence[JunctionFirstExample],
) -> Mapping[str, torch.Tensor]:
    result: dict[str, torch.Tensor] = {}
    for task, classes in TASK_CLASSES.items():
        counts = torch.zeros(len(classes), dtype=torch.float32)
        for row in examples:
            if row.task_masks.get(task, False):
                counts[int(row.task_labels[task])] += row.sample_weight
        present = counts.gt(0)
        weights = torch.ones_like(counts)
        if bool(present.any()):
            mean = counts[present].mean()
            weights[present] = (mean / counts[present]).sqrt().clamp(0.25, 4.0)
            weights[present] /= weights[present].mean()
        result[task] = weights
    return result


def teacher_forcing_ratio(epoch: int, epochs: int) -> float:
    if epoch < 1 or epoch > epochs or epochs < 3:
        raise ValueError("teacher forcing schedule inputs are invalid")
    first = max(1, epochs // 3)
    second = max(first + 1, (epochs * 2) // 3)
    if epoch <= first:
        return 1.0
    if epoch >= second:
        return 0.0
    return 1.0 - (epoch - first) / (second - first)


def _weighted_masked_cross_entropy(
    logits: torch.Tensor,
    labels: torch.Tensor,
    mask: torch.Tensor,
    sample_weights: torch.Tensor,
    class_weights: torch.Tensor | None,
) -> torch.Tensor:
    active = mask & labels.ge(0)
    if not bool(active.any()):
        return logits.sum() * 0.0
    losses = nn.functional.cross_entropy(
        logits,
        labels.clamp_min(0),
        weight=class_weights,
        reduction="none",
    )
    weights = sample_weights * active.to(sample_weights.dtype)
    return (losses * weights).sum() / weights.sum().clamp_min(1e-8)


def _candidate_acceptable_nll(
    logits: torch.Tensor,
    valid: torch.Tensor,
    acceptable: torch.Tensor,
    task_mask: torch.Tensor,
    sample_weights: torch.Tensor,
) -> torch.Tensor:
    active = task_mask & acceptable.any(dim=-1) & valid.any(dim=-1)
    if not bool(active.any()):
        return logits.sum() * 0.0
    minimum = torch.finfo(logits.dtype).min
    denominator = torch.logsumexp(logits.masked_fill(~valid, minimum), dim=-1)
    numerator = torch.logsumexp(logits.masked_fill(~acceptable, minimum), dim=-1)
    losses = denominator - numerator
    weights = sample_weights * active.to(sample_weights.dtype)
    return (losses * weights).sum() / weights.sum().clamp_min(1e-8)


def _member_acceptable_set_loss(
    logits: torch.Tensor,
    batch: JunctionFirstBatch,
) -> torch.Tensor:
    active = batch.member_task_mask & batch.member_acceptable_set_mask.any(dim=-1)
    if not bool(active.any()):
        return logits.sum() * 0.0
    included = nn.functional.softplus(-logits).unsqueeze(1)
    excluded = nn.functional.softplus(logits).unsqueeze(1)
    option_loss = torch.where(batch.member_acceptable_sets, included, excluded)
    option_loss = (option_loss * batch.member_mask.unsqueeze(1)).sum(dim=-1) / batch.member_mask.sum(
        dim=-1
    ).clamp_min(1).unsqueeze(-1)
    option_loss = option_loss.masked_fill(
        ~batch.member_acceptable_set_mask,
        torch.finfo(option_loss.dtype).max,
    )
    losses = option_loss.amin(dim=-1)
    weights = batch.sample_weights * active.to(batch.sample_weights.dtype)
    return (losses * weights).sum() / weights.sum().clamp_min(1e-8)


def _member_structure_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionFirstBatch,
) -> tuple[torch.Tensor, torch.Tensor]:
    option_mask = batch.member_acceptable_set_mask
    selected_road = (
        batch.member_acceptable_sets & batch.member_is_road.unsqueeze(1)
    ).any(dim=-1)
    selected_node = (
        batch.member_acceptable_sets & ~batch.member_is_road.unsqueeze(1)
    ).any(dim=-1)
    valid_options = option_mask & (selected_road ^ selected_node)
    type_acceptable = torch.stack(
        (
            (valid_options & selected_node).any(dim=-1),
            (valid_options & selected_road).any(dim=-1),
        ),
        dim=-1,
    )
    counts = batch.member_acceptable_sets.sum(dim=-1).clamp_min(1) - 1
    cardinality_acceptable = torch.zeros_like(
        outputs["member_cardinality_logits"], dtype=torch.bool
    )
    for option_index in range(counts.shape[1]):
        active = valid_options[:, option_index]
        if bool(active.any()):
            cardinality_acceptable[active, counts[active, option_index]] = True
    active = batch.member_task_mask & valid_options.any(dim=-1)
    type_loss = _acceptable_class_nll(
        outputs["member_type_logits"],
        type_acceptable,
        active,
        batch.sample_weights,
    )
    cardinality_loss = _acceptable_class_nll(
        outputs["member_cardinality_logits"],
        cardinality_acceptable,
        active,
        batch.sample_weights,
    )
    return type_loss, cardinality_loss


def _acceptable_class_nll(
    logits: torch.Tensor,
    acceptable: torch.Tensor,
    active: torch.Tensor,
    sample_weights: torch.Tensor,
) -> torch.Tensor:
    active = active & acceptable.any(dim=-1)
    if not bool(active.any()):
        return logits.sum() * 0.0
    minimum = torch.finfo(logits.dtype).min
    losses = torch.logsumexp(logits, dim=-1) - torch.logsumexp(
        logits.masked_fill(~acceptable, minimum),
        dim=-1,
    )
    weights = sample_weights * active.to(sample_weights.dtype)
    return (losses * weights).sum() / weights.sum().clamp_min(1e-8)


__all__ = [
    "JunctionFirstTrainingResult",
    "build_class_weights",
    "compute_junction_first_loss",
    "decode_member_sets",
    "evaluate_junction_first",
    "teacher_forcing_ratio",
    "train_junction_first_canary",
]
