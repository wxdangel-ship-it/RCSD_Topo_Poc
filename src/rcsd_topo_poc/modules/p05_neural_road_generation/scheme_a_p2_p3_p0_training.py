from __future__ import annotations

import copy
import hashlib
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    group_probabilities,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1EncodedBatch,
    P1EncodedGroup,
    P1FoldVocabulary,
    build_fold_vocabulary,
    collate_groups,
    encode_groups,
    select_inner_validation_cases,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    AUXILIARY_TARGET_NAMES,
    HierarchicalThresholds,
    HierarchicalTrainingExample,
    SchemeAP2P3P0Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_network import (
    SchemeAHierarchicalCarrierClueScorer,
    hierarchical_loss,
)


@dataclass(frozen=True)
class HierarchicalFoldTransform:
    vocabulary: P1FoldVocabulary
    evidence_mean: tuple[float, ...]
    evidence_scale: tuple[float, ...]


@dataclass(frozen=True)
class HierarchicalEncodedExample:
    source_index: int
    carrier: P1EncodedGroup
    evidence_features: tuple[float, ...]
    auxiliary_targets: tuple[bool, ...]


@dataclass(frozen=True)
class HierarchicalEncodedBatch:
    carrier: P1EncodedBatch
    group_evidence: torch.Tensor
    auxiliary_targets: torch.Tensor


@dataclass
class HierarchicalFoldResult:
    model: SchemeAHierarchicalCarrierClueScorer
    transform: HierarchicalFoldTransform
    thresholds: HierarchicalThresholds
    training_summary: dict[str, Any]
    inner_scores: list[dict[str, Any]]
    held_out_scores: list[dict[str, Any]]


def build_fold_transform(
    examples: Sequence[HierarchicalTrainingExample],
    *,
    train_case_keys: Sequence[str],
    inner_validation_case_keys: Sequence[str],
    held_out_case_keys: Sequence[str],
    dataset_manifest_sha256: str,
) -> HierarchicalFoldTransform:
    vocabulary = build_fold_vocabulary(
        [example.group for example in examples],
        train_case_keys=train_case_keys,
        inner_validation_case_keys=inner_validation_case_keys,
        held_out_case_keys=held_out_case_keys,
        dataset_manifest_sha256=dataset_manifest_sha256,
    )
    train_scope = set(train_case_keys)
    rows = [
        example.evidence_features
        for example in examples
        if example.group.case_key in train_scope
    ]
    if not rows:
        raise ValueError("fold transform has no training evidence")
    dimension = len(rows[0])
    if any(len(row) != dimension for row in rows):
        raise ValueError("fold evidence dimensions differ")
    means = tuple(sum(row[index] for row in rows) / len(rows) for index in range(dimension))
    scales = tuple(
        max(
            1e-6,
            math.sqrt(
                sum((row[index] - means[index]) ** 2 for row in rows) / len(rows)
            ),
        )
        for index in range(dimension)
    )
    return HierarchicalFoldTransform(
        vocabulary=vocabulary,
        evidence_mean=means,
        evidence_scale=scales,
    )


def encode_hierarchical_examples(
    examples: Sequence[HierarchicalTrainingExample],
    transform: HierarchicalFoldTransform,
) -> list[HierarchicalEncodedExample]:
    carrier = encode_groups([example.group for example in examples], transform.vocabulary)
    result: list[HierarchicalEncodedExample] = []
    for index, (example, encoded) in enumerate(zip(examples, carrier, strict=True)):
        evidence = tuple(
            (value - transform.evidence_mean[feature_index])
            / transform.evidence_scale[feature_index]
            for feature_index, value in enumerate(example.evidence_features)
        )
        result.append(
            HierarchicalEncodedExample(
                source_index=index,
                carrier=encoded,
                evidence_features=evidence,
                auxiliary_targets=example.auxiliary_targets,
            )
        )
    return result


def collate_hierarchical_examples(
    examples: Sequence[HierarchicalEncodedExample], *, device: torch.device
) -> HierarchicalEncodedBatch:
    if not examples:
        raise ValueError("cannot collate an empty hierarchical batch")
    return HierarchicalEncodedBatch(
        carrier=collate_groups([example.carrier for example in examples], device=device),
        group_evidence=torch.tensor(
            [example.evidence_features for example in examples],
            dtype=torch.float32,
            device=device,
        ),
        auxiliary_targets=torch.tensor(
            [example.auxiliary_targets for example in examples],
            dtype=torch.bool,
            device=device,
        ),
    )


def train_hierarchical_fold(
    examples: Sequence[HierarchicalTrainingExample],
    *,
    config: SchemeAP2P3P0Config,
    held_out_fold: int,
    seed: int,
    dataset_manifest_sha256: str,
) -> HierarchicalFoldResult:
    case_folds = {example.group.case_key: example.group.fold for example in examples}
    train_cases, inner_cases, held_out_cases = select_inner_validation_cases(
        case_folds,
        held_out_fold=held_out_fold,
        seed=seed,
        ratio=config.inner_validation_ratio,
    )
    transform = build_fold_transform(
        examples,
        train_case_keys=train_cases,
        inner_validation_case_keys=inner_cases,
        held_out_case_keys=held_out_cases,
        dataset_manifest_sha256=dataset_manifest_sha256,
    )
    encoded = encode_hierarchical_examples(examples, transform)
    train_indices = [
        index for index, example in enumerate(examples) if example.group.case_key in set(train_cases)
    ]
    inner_indices = [
        index for index, example in enumerate(examples) if example.group.case_key in set(inner_cases)
    ]
    held_out_indices = [
        index
        for index, example in enumerate(examples)
        if example.group.case_key in set(held_out_cases)
    ]
    device = _resolve_device(config.device)
    torch.set_num_threads(config.torch_num_threads)
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    vocabulary = transform.vocabulary
    model = SchemeAHierarchicalCarrierClueScorer(
        candidate_vocabulary_size=len(vocabulary.candidate_tokens) + 1,
        object_vocabulary_size=len(vocabulary.object_tokens) + 1,
        context_vocabulary_size=len(vocabulary.context_tokens) + 1,
        object_type_count=len(vocabulary.object_types) + 1,
        numeric_dim=config.numeric_dim,
        evidence_dim=config.expected_evidence_dim,
        auxiliary_dim=len(AUXILIARY_TARGET_NAMES),
        embedding_dim=config.embedding_dim,
        hidden_dim=config.hidden_dim,
        type_embedding_dim=config.type_embedding_dim,
        evidence_hidden_dim=config.evidence_hidden_dim,
        dropout=config.dropout,
    ).to(device)
    model_parameter_count = parameter_count(model)
    if model_parameter_count > config.hard_max_parameter_count:
        raise ValueError("hierarchical model exceeds hard parameter-count gate")
    if model_parameter_count < config.target_min_parameter_count:
        raise ValueError("hierarchical model is below preregistered parameter scale")
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    train_examples = [examples[index] for index in train_indices]
    clue_positive_weight = _binary_positive_weight(
        [example.group.anomaly_target for example in train_examples]
    )
    auxiliary_positive_weights = torch.tensor(
        [
            _binary_positive_weight(
                [example.auxiliary_targets[index] for example in train_examples]
            )
            for index in range(len(AUXILIARY_TARGET_NAMES))
        ],
        dtype=torch.float32,
        device=device,
    )
    best_state: dict[str, torch.Tensor] | None = None
    best_inner_loss = float("inf")
    best_epoch = 0
    epochs_without_improvement = 0
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        train_total = 0.0
        train_weight = 0
        for batch_examples in _iter_encoded_batches(
            encoded,
            train_indices,
            batch_group_count=config.batch_group_count,
            seed=seed * 10_000 + epoch,
        ):
            batch = collate_hierarchical_examples(batch_examples, device=device)
            optimizer.zero_grad(set_to_none=True)
            outputs = _forward(model, batch)
            loss, _ = hierarchical_loss(
                *outputs,
                batch.carrier.candidate_group_index,
                batch.carrier.truth_mask,
                batch.carrier.group_weights,
                batch.carrier.anomaly_targets,
                batch.auxiliary_targets,
                candidate_correctness_loss_weight=config.candidate_correctness_loss_weight,
                clue_loss_weight=config.clue_loss_weight,
                auxiliary_loss_weight=config.auxiliary_loss_weight,
                clue_positive_weight=clue_positive_weight,
                auxiliary_positive_weights=auxiliary_positive_weights,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
            optimizer.step()
            train_total += float(loss.item()) * len(batch_examples)
            train_weight += len(batch_examples)
        inner_loss = _evaluation_loss(
            model,
            encoded,
            inner_indices,
            config=config,
            device=device,
            clue_positive_weight=clue_positive_weight,
            auxiliary_positive_weights=auxiliary_positive_weights,
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
            best_state = copy.deepcopy(model.state_dict())
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= config.patience:
                break
    if best_state is None:
        raise ValueError("hierarchical fold did not produce a model state")
    model.load_state_dict(best_state)
    inner_scores = score_hierarchical_examples(
        model,
        examples,
        encoded,
        indices=inner_indices,
        batch_group_count=config.batch_group_count,
        device=device,
    )
    thresholds = select_hierarchical_thresholds(inner_scores)
    held_out_scores = score_hierarchical_examples(
        model,
        examples,
        encoded,
        indices=held_out_indices,
        batch_group_count=config.batch_group_count,
        device=device,
    )
    case_latencies: list[dict[str, Any]] = []
    for case_key in sorted(held_out_cases):
        case_indices = [
            index for index in held_out_indices if examples[index].group.case_key == case_key
        ]
        inference_started = time.perf_counter()
        score_hierarchical_examples(
            model,
            examples,
            encoded,
            indices=case_indices,
            batch_group_count=config.batch_group_count,
            device=device,
        )
        case_latencies.append(
            {
                "case_key": case_key,
                "seconds": time.perf_counter() - inference_started,
                "segment_count": len(case_indices),
            }
        )
    elapsed = time.perf_counter() - started
    return HierarchicalFoldResult(
        model=model,
        transform=transform,
        thresholds=thresholds,
        inner_scores=inner_scores,
        held_out_scores=held_out_scores,
        training_summary={
            "seed": seed,
            "held_out_fold": held_out_fold,
            "train_case_keys": list(train_cases),
            "inner_validation_case_keys": list(inner_cases),
            "held_out_case_keys": list(held_out_cases),
            "train_group_count": len(train_indices),
            "inner_group_count": len(inner_indices),
            "held_out_group_count": len(held_out_indices),
            "best_epoch": best_epoch,
            "best_inner_loss": best_inner_loss,
            "epochs_ran": len(history),
            "history": history,
            "parameter_count": model_parameter_count,
            "model_signature": model_state_signature(model),
            "carrier_threshold": thresholds.carrier_threshold,
            "clue_threshold": thresholds.clue_threshold,
            "wall_seconds": elapsed,
            "case_inference_latencies": case_latencies,
            "device": str(device),
        },
    )


def score_hierarchical_examples(
    model: SchemeAHierarchicalCarrierClueScorer,
    source_examples: Sequence[HierarchicalTrainingExample],
    encoded_examples: Sequence[HierarchicalEncodedExample],
    *,
    indices: Sequence[int],
    batch_group_count: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    rows: list[dict[str, Any]] = []
    with torch.no_grad():
        for batch_examples in _iter_encoded_batches(
            encoded_examples,
            indices,
            batch_group_count=batch_group_count,
            seed=None,
        ):
            batch = collate_hierarchical_examples(batch_examples, device=device)
            (
                candidate_scores,
                candidate_correctness_logits,
                clue_logits,
                auxiliary_logits,
            ) = _forward(model, batch)
            probabilities = group_probabilities(
                candidate_scores,
                batch.carrier.candidate_group_index,
                len(batch_examples),
            )
            correctness = torch.sigmoid(candidate_correctness_logits)
            clue = torch.sigmoid(clue_logits).cpu().tolist()
            auxiliary = torch.sigmoid(auxiliary_logits).cpu().tolist()
            cursor = 0
            for local_index, encoded in enumerate(batch_examples):
                source = source_examples[encoded.source_index]
                count = len(encoded.carrier.candidate_ids)
                local_scores = candidate_scores[cursor : cursor + count].cpu().tolist()
                local_probabilities = probabilities[cursor : cursor + count].cpu().tolist()
                local_correctness = correctness[cursor : cursor + count].cpu().tolist()
                utilities = [
                    probability * correctness_probability
                    for probability, correctness_probability in zip(
                        local_probabilities, local_correctness, strict=True
                    )
                ]
                selected_index = max(
                    range(count),
                    key=lambda index: (
                        utilities[index],
                        local_probabilities[index],
                        encoded.carrier.candidate_ids[index],
                    ),
                )
                rows.append(
                    {
                        "case_key": source.group.case_key,
                        "fold": source.group.fold,
                        "group_id": source.group.group_id,
                        "object_id": source.group.object_id,
                        "candidate_ids": list(encoded.carrier.candidate_ids),
                        "candidate_targets": list(encoded.carrier.candidate_targets),
                        "candidate_scores": local_scores,
                        "candidate_probabilities": local_probabilities,
                        "candidate_correctness_probabilities": local_correctness,
                        "candidate_utilities": utilities,
                        "selected_index": selected_index,
                        "selected_candidate_id": encoded.carrier.candidate_ids[selected_index],
                        "selected_target": encoded.carrier.candidate_targets[selected_index],
                        "carrier_confidence": utilities[selected_index],
                        "clue_probability": clue[local_index],
                        "auxiliary_probabilities": auxiliary[local_index],
                        "truth_candidate_id": source.group.candidates[
                            source.group.truth_index
                        ].candidate_id,
                        "truth_target": source.group.truth_target,
                        "clue_target": source.group.anomaly_target,
                        "review_target": source.group.truth_target == "REVIEW_FALLBACK",
                    }
                )
                cursor += count
    return sorted(rows, key=lambda row: str(row["group_id"]))


def select_hierarchical_thresholds(
    inner_scores: Sequence[Mapping[str, Any]],
) -> HierarchicalThresholds:
    if not inner_scores:
        raise ValueError("inner validation scores must not be empty")
    positive_clues = [
        float(row["clue_probability"]) for row in inner_scores if bool(row["clue_target"])
    ]
    if not positive_clues:
        raise ValueError("inner validation has no positive RealityChangeClue label")
    clue_threshold = min(positive_clues)
    carrier_wrong_confidences = [
        float(row["carrier_confidence"])
        for row in inner_scores
        if str(row["selected_target"]) != "REVIEW_FALLBACK"
        and float(row["clue_probability"]) < clue_threshold
        and str(row["selected_candidate_id"]) != str(row["truth_candidate_id"])
    ]
    carrier_threshold = max(carrier_wrong_confidences, default=0.0)
    return HierarchicalThresholds(
        carrier_threshold=min(1.0, max(0.0, carrier_threshold)),
        clue_threshold=min(1.0, max(0.0, clue_threshold)),
    )


def decision_from_score(
    row: Mapping[str, Any],
    thresholds: HierarchicalThresholds,
    *,
    seed: int,
    model_signature: str,
) -> dict[str, Any]:
    clue = float(row["clue_probability"]) >= thresholds.clue_threshold
    review = str(row["selected_target"]) == "REVIEW_FALLBACK"
    carrier_safe = float(row["carrier_confidence"]) > thresholds.carrier_threshold
    accepted = carrier_safe and not clue and not review
    if review:
        reason = "review_never_auto_publish"
    elif clue:
        reason = "reality_change_clue"
    elif not carrier_safe:
        reason = "carrier_confidence_fallback"
    else:
        reason = "hierarchical_carrier_accept"
    return {
        "case_key": row["case_key"],
        "fold": int(row["fold"]),
        "group_id": row["group_id"],
        "object_id": row["object_id"],
        "proposal_candidate_id": row["selected_candidate_id"],
        "proposal_target": row["selected_target"],
        "accepted": accepted,
        "risk": 1.0 - float(row["carrier_confidence"]),
        "safety_probability": float(row["carrier_confidence"]),
        "anomaly_probability": float(row["clue_probability"]),
        "clue_predicted": clue,
        "carrier_threshold": thresholds.carrier_threshold,
        "clue_threshold": thresholds.clue_threshold,
        "reason": reason,
        "seed": seed,
        "model_signature": model_signature,
    }


def model_state_signature(model: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        digest.update(name.encode("utf-8"))
        digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def _evaluation_loss(
    model: SchemeAHierarchicalCarrierClueScorer,
    encoded: Sequence[HierarchicalEncodedExample],
    indices: Sequence[int],
    *,
    config: SchemeAP2P3P0Config,
    device: torch.device,
    clue_positive_weight: float,
    auxiliary_positive_weights: torch.Tensor,
) -> float:
    model.eval()
    total = 0.0
    count = 0
    with torch.no_grad():
        for batch_examples in _iter_encoded_batches(
            encoded,
            indices,
            batch_group_count=config.batch_group_count,
            seed=None,
        ):
            batch = collate_hierarchical_examples(batch_examples, device=device)
            loss, _ = hierarchical_loss(
                *_forward(model, batch),
                batch.carrier.candidate_group_index,
                batch.carrier.truth_mask,
                batch.carrier.group_weights,
                batch.carrier.anomaly_targets,
                batch.auxiliary_targets,
                candidate_correctness_loss_weight=config.candidate_correctness_loss_weight,
                clue_loss_weight=config.clue_loss_weight,
                auxiliary_loss_weight=config.auxiliary_loss_weight,
                clue_positive_weight=clue_positive_weight,
                auxiliary_positive_weights=auxiliary_positive_weights,
            )
            total += float(loss.item()) * len(batch_examples)
            count += len(batch_examples)
    return total / max(1, count)


def _forward(
    model: SchemeAHierarchicalCarrierClueScorer,
    batch: HierarchicalEncodedBatch,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    carrier = batch.carrier
    return model(
        candidate_token_ids=carrier.candidate_token_ids,
        candidate_offsets=carrier.candidate_offsets,
        object_token_ids=carrier.object_token_ids,
        object_offsets=carrier.object_offsets,
        context_token_ids=carrier.context_token_ids,
        context_offsets=carrier.context_offsets,
        numeric_features=carrier.numeric_features,
        group_evidence=batch.group_evidence,
        candidate_group_index=carrier.candidate_group_index,
        group_type_ids=carrier.group_type_ids,
    )


def _iter_encoded_batches(
    encoded: Sequence[HierarchicalEncodedExample],
    indices: Sequence[int],
    *,
    batch_group_count: int,
    seed: int | None,
) -> Iterable[list[HierarchicalEncodedExample]]:
    ordered = list(indices)
    if seed is not None:
        random.Random(seed).shuffle(ordered)
    for start in range(0, len(ordered), batch_group_count):
        yield [encoded[index] for index in ordered[start : start + batch_group_count]]


def _binary_positive_weight(values: Sequence[bool]) -> float:
    positive = sum(values)
    negative = len(values) - positive
    if positive == 0 or negative == 0:
        raise ValueError("binary training target lacks positive/negative examples")
    return min(20.0, max(0.25, negative / positive))


def _resolve_device(value: str) -> torch.device:
    if value == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("CUDA was requested but is unavailable")
        return torch.device("cuda")
    if value == "auto" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


__all__ = [
    "HierarchicalEncodedBatch",
    "HierarchicalEncodedExample",
    "HierarchicalFoldResult",
    "HierarchicalFoldTransform",
    "build_fold_transform",
    "collate_hierarchical_examples",
    "decision_from_score",
    "encode_hierarchical_examples",
    "model_state_signature",
    "score_hierarchical_examples",
    "select_hierarchical_thresholds",
    "train_hierarchical_fold",
]
