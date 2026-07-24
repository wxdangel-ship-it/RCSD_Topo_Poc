from __future__ import annotations

import copy
import math
import random
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_models import (
    JSGP3OOFConfig,
    P3FoldVocabulary,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p3_network import (
    ContextSetScorer,
    expected_calibration_error,
    group_probabilities,
    listwise_group_loss,
    parameter_count,
)


REVIEW_TOKENS = {"payload:state=REVIEW", "payload:state=UNKNOWN"}


@dataclass(frozen=True)
class P3GroupExample:
    case_key: str
    fold: int
    domain: str
    group_id: str
    object_type: str
    candidate_ids: tuple[str, ...]
    candidate_tokens: tuple[tuple[str, ...], ...]
    feature_signatures: tuple[str, ...]
    context_tokens: tuple[str, ...]
    context_signature: str
    truth_index: int
    sample_weight: float

    @property
    def truth_is_review(self) -> bool:
        return bool(set(self.candidate_tokens[self.truth_index]) & REVIEW_TOKENS)

    @property
    def candidate_review_mask(self) -> tuple[bool, ...]:
        return tuple(bool(set(tokens) & REVIEW_TOKENS) for tokens in self.candidate_tokens)


@dataclass(frozen=True)
class EncodedGroup:
    source_index: int
    candidate_token_ids: tuple[tuple[int, ...], ...]
    context_token_ids: tuple[int, ...]
    truth_index: int
    object_type_id: int
    weight: float


@dataclass(frozen=True)
class EncodedBatch:
    candidate_token_ids: torch.Tensor
    candidate_offsets: torch.Tensor
    context_token_ids: torch.Tensor
    context_offsets: torch.Tensor
    candidate_group_index: torch.Tensor
    group_type_ids: torch.Tensor
    truth_mask: torch.Tensor
    group_weights: torch.Tensor


def select_inner_validation_cases(
    case_folds: Mapping[str, int],
    *,
    held_out_fold: int,
    seed: int,
    ratio: float,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    held_out = tuple(sorted(case for case, fold in case_folds.items() if fold == held_out_fold))
    outer_train = sorted(case for case, fold in case_folds.items() if fold != held_out_fold)
    ranked = sorted(
        outer_train,
        key=lambda case: (canonical_sha256({"seed": seed, "case": case}), case),
    )
    inner_count = max(1, min(len(ranked) - 1, int(math.ceil(len(ranked) * ratio))))
    inner = tuple(sorted(ranked[:inner_count]))
    train = tuple(sorted(set(outer_train) - set(inner)))
    if set(train) & set(inner) or (set(train) | set(inner)) & set(held_out):
        raise ValueError("train/inner/held-out Case leakage")
    if set(train) | set(inner) | set(held_out) != set(case_folds):
        raise ValueError("train/inner/held-out Case coverage mismatch")
    return train, inner, held_out


def build_fold_vocabulary(
    groups: Sequence[P3GroupExample],
    *,
    train_case_keys: Sequence[str],
    inner_validation_case_keys: Sequence[str],
    held_out_case_keys: Sequence[str],
    dataset_manifest_sha256: str,
) -> P3FoldVocabulary:
    train_scope = set(train_case_keys)
    candidate_tokens: set[str] = set()
    context_tokens: set[str] = set()
    object_types: set[str] = set()
    for group in groups:
        if group.case_key not in train_scope:
            continue
        for tokens in group.candidate_tokens:
            candidate_tokens.update(tokens)
        context_tokens.update(group.context_tokens)
        object_types.add(group.object_type)
    if not candidate_tokens or not context_tokens or not object_types:
        raise ValueError("training vocabulary must not be empty")
    return P3FoldVocabulary(
        candidate_tokens={token: index for index, token in enumerate(sorted(candidate_tokens), 1)},
        context_tokens={token: index for index, token in enumerate(sorted(context_tokens), 1)},
        object_types={token: index for index, token in enumerate(sorted(object_types), 1)},
        train_case_keys=tuple(sorted(train_case_keys)),
        inner_validation_case_keys=tuple(sorted(inner_validation_case_keys)),
        held_out_case_keys=tuple(sorted(held_out_case_keys)),
        dataset_manifest_sha256=dataset_manifest_sha256,
    )


def _type_weights(groups: Sequence[P3GroupExample], case_scope: set[str]) -> dict[str, float]:
    counts = Counter(group.object_type for group in groups if group.case_key in case_scope)
    raw = {key: 1.0 / math.sqrt(value) for key, value in counts.items() if value > 0}
    mean = sum(raw.values()) / max(1, len(raw))
    return {key: value / mean for key, value in raw.items()}


def encode_groups(
    groups: Sequence[P3GroupExample],
    vocabulary: P3FoldVocabulary,
    *,
    type_weights: Mapping[str, float],
    review_weight: float,
) -> list[EncodedGroup]:
    result: list[EncodedGroup] = []
    for index, group in enumerate(groups):
        candidate_ids = tuple(
            tuple(vocabulary.candidate_tokens.get(token, 0) for token in tokens) or (0,)
            for tokens in group.candidate_tokens
        )
        context_ids = (
            tuple(vocabulary.context_tokens.get(token, 0) for token in group.context_tokens)
            or (0,)
        )
        object_type_id = vocabulary.object_types.get(group.object_type, 0)
        weight = group.sample_weight * float(type_weights.get(group.object_type, 1.0))
        if group.truth_is_review:
            weight *= review_weight
        result.append(
            EncodedGroup(
                source_index=index,
                candidate_token_ids=candidate_ids,
                context_token_ids=context_ids,
                truth_index=group.truth_index,
                object_type_id=object_type_id,
                weight=weight,
            )
        )
    return result


def collate_groups(groups: Sequence[EncodedGroup], *, device: torch.device) -> EncodedBatch:
    if not groups:
        raise ValueError("cannot collate an empty group batch")
    candidate_tokens: list[int] = []
    candidate_offsets: list[int] = []
    context_tokens: list[int] = []
    context_offsets: list[int] = []
    candidate_group_index: list[int] = []
    group_type_ids: list[int] = []
    truth_mask: list[bool] = []
    group_weights: list[float] = []
    for group_index, group in enumerate(groups):
        group_type_ids.append(group.object_type_id)
        group_weights.append(group.weight)
        context_offsets.append(len(context_tokens))
        context_tokens.extend(group.context_token_ids)
        for candidate_index, token_ids in enumerate(group.candidate_token_ids):
            candidate_offsets.append(len(candidate_tokens))
            candidate_tokens.extend(token_ids)
            candidate_group_index.append(group_index)
            truth_mask.append(candidate_index == group.truth_index)
    return EncodedBatch(
        candidate_token_ids=torch.tensor(candidate_tokens, dtype=torch.long, device=device),
        candidate_offsets=torch.tensor(candidate_offsets, dtype=torch.long, device=device),
        context_token_ids=torch.tensor(context_tokens, dtype=torch.long, device=device),
        context_offsets=torch.tensor(context_offsets, dtype=torch.long, device=device),
        candidate_group_index=torch.tensor(
            candidate_group_index, dtype=torch.long, device=device
        ),
        group_type_ids=torch.tensor(group_type_ids, dtype=torch.long, device=device),
        truth_mask=torch.tensor(truth_mask, dtype=torch.bool, device=device),
        group_weights=torch.tensor(group_weights, dtype=torch.float32, device=device),
    )


def _forward(model: ContextSetScorer, batch: EncodedBatch) -> torch.Tensor:
    return model(
        candidate_token_ids=batch.candidate_token_ids,
        candidate_offsets=batch.candidate_offsets,
        context_token_ids=batch.context_token_ids,
        context_offsets=batch.context_offsets,
        candidate_group_index=batch.candidate_group_index,
        group_type_ids=batch.group_type_ids,
    )


def _iter_batches(
    groups: Sequence[EncodedGroup],
    *,
    batch_group_count: int,
    seed: int | None,
) -> Iterable[list[EncodedGroup]]:
    indices = list(range(len(groups)))
    if seed is not None:
        random.Random(seed).shuffle(indices)
    for start in range(0, len(indices), batch_group_count):
        yield [groups[index] for index in indices[start : start + batch_group_count]]


def score_encoded_groups(
    model: ContextSetScorer,
    groups: Sequence[EncodedGroup],
    *,
    batch_group_count: int,
    device: torch.device,
) -> tuple[list[list[float]], list[list[float]], dict[str, float]]:
    model.eval()
    all_scores: list[list[float]] = []
    all_probabilities: list[list[float]] = []
    selected_confidence: list[float] = []
    selected_correctness: list[bool] = []
    correct = 0
    with torch.no_grad():
        for batch_groups in _iter_batches(
            groups, batch_group_count=batch_group_count, seed=None
        ):
            batch = collate_groups(batch_groups, device=device)
            scores = _forward(model, batch)
            probabilities = group_probabilities(
                scores, batch.candidate_group_index, len(batch_groups)
            )
            cursor = 0
            for group in batch_groups:
                count = len(group.candidate_token_ids)
                group_scores = scores[cursor : cursor + count].detach().cpu().tolist()
                group_probabilities_list = (
                    probabilities[cursor : cursor + count].detach().cpu().tolist()
                )
                selected = max(range(count), key=lambda index: (group_scores[index], -index))
                is_correct = selected == group.truth_index
                correct += is_correct
                selected_confidence.append(group_probabilities_list[selected])
                selected_correctness.append(is_correct)
                all_scores.append(group_scores)
                all_probabilities.append(group_probabilities_list)
                cursor += count
    confidence_tensor = torch.tensor(selected_confidence, dtype=torch.float32)
    correctness_tensor = torch.tensor(selected_correctness, dtype=torch.bool)
    return all_scores, all_probabilities, {
        "top1_accuracy": correct / max(1, len(groups)),
        "ece": expected_calibration_error(confidence_tensor, correctness_tensor),
    }


def selection_metrics(
    groups: Sequence[P3GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
) -> dict[str, float]:
    if len(groups) != len(scores) or len(groups) != len(probabilities):
        raise ValueError("group/score/probability lengths differ")
    jsg_correct = 0
    jsg_count = 0
    review_truth_count = 0
    review_truth_selected = 0
    review_selected_count = 0
    review_selected_correct = 0
    selected_confidences: list[float] = []
    selected_correctness: list[bool] = []
    for group, group_scores, group_probabilities in zip(
        groups, scores, probabilities, strict=True
    ):
        if len(group_scores) != len(group.candidate_ids) or len(group_probabilities) != len(
            group.candidate_ids
        ):
            raise ValueError(f"candidate score length differs: {group.case_key}/{group.group_id}")
        selected = max(
            range(len(group_scores)),
            key=lambda index: (float(group_scores[index]), group.candidate_ids[index]),
        )
        is_correct = selected == group.truth_index
        if group.domain != "JSG":
            continue
        jsg_count += 1
        jsg_correct += is_correct
        selected_confidences.append(float(group_probabilities[selected]))
        selected_correctness.append(is_correct)
        if group.truth_is_review:
            review_truth_count += 1
            review_truth_selected += is_correct
        if group.candidate_review_mask[selected]:
            review_selected_count += 1
            review_selected_correct += is_correct
    confidence_tensor = torch.tensor(selected_confidences, dtype=torch.float32)
    correctness_tensor = torch.tensor(selected_correctness, dtype=torch.bool)
    return {
        "jsg_top1_accuracy": jsg_correct / max(1, jsg_count),
        "jsg_ece": expected_calibration_error(confidence_tensor, correctness_tensor),
        "review_unknown_recall": (
            review_truth_selected / review_truth_count if review_truth_count else 1.0
        ),
        "review_unknown_precision": (
            review_selected_correct / review_selected_count if review_selected_count else 1.0
        ),
    }


def _resolve_device(value: str) -> torch.device:
    if value == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("CUDA requested but unavailable")
        return torch.device("cuda")
    if value == "auto" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def train_fold_model(
    groups: Sequence[P3GroupExample],
    *,
    case_folds: Mapping[str, int],
    held_out_fold: int,
    seed: int,
    dataset_manifest_sha256: str,
    config: JSGP3OOFConfig,
) -> dict[str, Any]:
    train_cases, inner_cases, held_out_cases = select_inner_validation_cases(
        case_folds,
        held_out_fold=held_out_fold,
        seed=seed,
        ratio=config.inner_validation_ratio,
    )
    vocabulary = build_fold_vocabulary(
        groups,
        train_case_keys=train_cases,
        inner_validation_case_keys=inner_cases,
        held_out_case_keys=held_out_cases,
        dataset_manifest_sha256=dataset_manifest_sha256,
    )
    train_scope = set(train_cases)
    inner_scope = set(inner_cases)
    held_out_scope = set(held_out_cases)
    type_weights = _type_weights(groups, train_scope)
    train_source = [group for group in groups if group.case_key in train_scope]
    inner_source = [group for group in groups if group.case_key in inner_scope]
    held_out_source = [group for group in groups if group.case_key in held_out_scope]
    encoded_train = encode_groups(
        train_source,
        vocabulary,
        type_weights=type_weights,
        review_weight=config.review_weight,
    )
    encoded_inner = encode_groups(
        inner_source, vocabulary, type_weights=type_weights, review_weight=1.0
    )
    encoded_held_out = encode_groups(
        held_out_source, vocabulary, type_weights=type_weights, review_weight=1.0
    )

    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(config.torch_num_threads)
    device = _resolve_device(config.device)
    model = ContextSetScorer(
        candidate_vocabulary_size=len(vocabulary.candidate_tokens) + 1,
        context_vocabulary_size=len(vocabulary.context_tokens) + 1,
        object_type_count=len(vocabulary.object_types) + 1,
        embedding_dim=config.embedding_dim,
        hidden_dim=config.hidden_dim,
        type_embedding_dim=config.type_embedding_dim,
        dropout=config.dropout,
    ).to(device)
    parameters = parameter_count(model)
    if parameters > config.max_parameter_count:
        raise ValueError(f"P3 parameter count exceeds limit: {parameters}")
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    history: list[dict[str, Any]] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_metric = -math.inf
    best_epoch = 0
    stale_epochs = 0
    started = time.perf_counter()
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        loss_sum = 0.0
        batch_count = 0
        for batch_groups in _iter_batches(
            encoded_train,
            batch_group_count=config.batch_group_count,
            seed=seed * 1000 + epoch,
        ):
            batch = collate_groups(batch_groups, device=device)
            optimizer.zero_grad(set_to_none=True)
            scores = _forward(model, batch)
            loss = listwise_group_loss(
                scores,
                batch.candidate_group_index,
                batch.truth_mask,
                batch.group_weights,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            loss_sum += float(loss.detach().cpu())
            batch_count += 1
        inner_scores, inner_probabilities, inner_metrics = score_encoded_groups(
            model,
            encoded_inner,
            batch_group_count=config.batch_group_count,
            device=device,
        )
        inner_selection = selection_metrics(
            inner_source, inner_scores, inner_probabilities
        )
        metric = float(inner_selection["jsg_top1_accuracy"]) - 0.1 * float(
            inner_selection["jsg_ece"]
        )
        history.append(
            {
                "epoch": epoch,
                "train_loss": loss_sum / max(1, batch_count),
                "inner_top1_accuracy": inner_metrics["top1_accuracy"],
                "inner_ece": inner_metrics["ece"],
                **{f"inner_{key}": value for key, value in inner_selection.items()},
                "selection_metric": metric,
            }
        )
        if metric > best_metric + 1e-9:
            best_metric = metric
            best_epoch = epoch
            best_state = {
                key: value.detach().cpu().clone() for key, value in model.state_dict().items()
            }
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= config.patience:
                break
    if best_state is None:
        raise RuntimeError("P3 training did not produce a checkpoint")
    model.load_state_dict(best_state)
    model.to(device)
    held_scores, held_probabilities, held_metrics = score_encoded_groups(
        model,
        encoded_held_out,
        batch_group_count=config.batch_group_count,
        device=device,
    )
    held_selection = selection_metrics(
        held_out_source, held_scores, held_probabilities
    )
    return {
        "model": model,
        "device": device,
        "vocabulary": vocabulary,
        "type_weights": type_weights,
        "train_groups": train_source,
        "inner_groups": inner_source,
        "held_out_groups": held_out_source,
        "held_out_encoded": encoded_held_out,
        "held_out_scores": held_scores,
        "held_out_probabilities": held_probabilities,
        "held_out_metrics": held_metrics,
        "history": history,
        "summary": {
            "seed": seed,
            "held_out_fold": held_out_fold,
            "best_epoch": best_epoch,
            "best_inner_metric": best_metric,
            "parameter_count": parameters,
            "candidate_vocabulary_size": len(vocabulary.candidate_tokens) + 1,
            "context_vocabulary_size": len(vocabulary.context_tokens) + 1,
            "object_type_count": len(vocabulary.object_types) + 1,
            "train_case_count": len(train_cases),
            "inner_validation_case_count": len(inner_cases),
            "held_out_case_count": len(held_out_cases),
            "train_group_count": len(train_source),
            "inner_validation_group_count": len(inner_source),
            "held_out_group_count": len(held_out_source),
            "training_wall_seconds": time.perf_counter() - started,
            "device": str(device),
            "held_out_top1_accuracy": held_metrics["top1_accuracy"],
            "held_out_ece": held_metrics["ece"],
            **{f"held_out_{key}": value for key, value in held_selection.items()},
        },
    }


__all__ = [
    "P3GroupExample",
    "build_fold_vocabulary",
    "collate_groups",
    "encode_groups",
    "score_encoded_groups",
    "selection_metrics",
    "select_inner_validation_cases",
    "train_fold_model",
]
