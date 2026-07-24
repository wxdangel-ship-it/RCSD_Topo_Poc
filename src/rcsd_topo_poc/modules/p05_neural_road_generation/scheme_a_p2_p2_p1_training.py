from __future__ import annotations

import copy
import math
import os
import random
import time
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import scheme_a_p1_loss
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1EncodedGroup,
    P1GroupExample,
    build_fold_vocabulary,
    collate_groups,
    encode_groups,
    score_encoded_groups,
    select_inner_validation_cases,
    selection_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_models import (
    SchemeAP2P2P1Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p1_network import (
    SchemeASegmentSafetyHead,
    parameter_count,
)


def train_segment_safety_fold(
    groups: Sequence[P1GroupExample],
    *,
    proposals: Mapping[str, Mapping[str, Any]],
    case_folds: Mapping[str, int],
    held_out_fold: int,
    seed: int,
    dataset_signature: str,
    config: SchemeAP2P2P1Config,
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
        dataset_manifest_sha256=dataset_signature,
    )
    train_scope = set(train_cases)
    inner_scope = set(inner_cases)
    held_scope = set(held_out_cases)
    train_groups = [group for group in groups if group.case_key in train_scope]
    inner_groups = [group for group in groups if group.case_key in inner_scope]
    held_groups = [group for group in groups if group.case_key in held_scope]
    encoded_train = encode_groups(train_groups, vocabulary)
    encoded_inner = encode_groups(inner_groups, vocabulary)
    encoded_held = encode_groups(held_groups, vocabulary)

    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(config.torch_num_threads)
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.benchmark = False
    device = _resolve_device(config.device)
    model = SchemeASegmentSafetyHead(
        candidate_vocabulary_size=len(vocabulary.candidate_tokens) + 1,
        object_vocabulary_size=len(vocabulary.object_tokens) + 1,
        context_vocabulary_size=len(vocabulary.context_tokens) + 1,
        object_type_count=len(vocabulary.object_types) + 1,
        numeric_dim=config.numeric_dim,
        embedding_dim=config.embedding_dim,
        hidden_dim=config.hidden_dim,
        type_embedding_dim=config.type_embedding_dim,
        dropout=config.dropout,
    ).to(device)
    parameters = parameter_count(model)
    if not config.min_parameter_count <= parameters <= config.max_parameter_count:
        raise ValueError(f"safety-head parameter count outside contract: {parameters}")
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    anomaly_positive = sum(group.anomaly_target for group in train_groups)
    anomaly_negative = len(train_groups) - anomaly_positive
    anomaly_positive_weight = anomaly_negative / max(1, anomaly_positive)
    history: list[dict[str, Any]] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_metric = -math.inf
    best_epoch = 0
    stale_epochs = 0
    started = time.perf_counter()
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        loss_total = listwise_total = anomaly_total = 0.0
        batch_count = 0
        for batch_groups in _iter_batches(
            encoded_train,
            batch_group_count=config.batch_group_count,
            seed=seed * 1000 + epoch,
        ):
            batch = collate_groups(batch_groups, device=device)
            optimizer.zero_grad(set_to_none=True)
            candidate_scores, anomaly_logits = model(
                candidate_token_ids=batch.candidate_token_ids,
                candidate_offsets=batch.candidate_offsets,
                object_token_ids=batch.object_token_ids,
                object_offsets=batch.object_offsets,
                context_token_ids=batch.context_token_ids,
                context_offsets=batch.context_offsets,
                numeric_features=batch.numeric_features,
                candidate_group_index=batch.candidate_group_index,
                group_type_ids=batch.group_type_ids,
            )
            loss, parts = scheme_a_p1_loss(
                candidate_scores,
                anomaly_logits,
                batch.candidate_group_index,
                batch.truth_mask,
                batch.group_weights,
                batch.anomaly_targets,
                anomaly_loss_weight=config.anomaly_loss_weight,
                anomaly_positive_weight=anomaly_positive_weight,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            loss_total += float(loss.detach().cpu())
            listwise_total += float(parts["listwise_loss"].detach().cpu())
            anomaly_total += float(parts["anomaly_loss"].detach().cpu())
            batch_count += 1
        inner_scores, inner_probabilities, inner_anomaly = score_encoded_groups(
            model,
            encoded_inner,
            batch_group_count=config.batch_group_count,
            device=device,
        )
        metrics = selection_metrics(
            inner_groups, inner_scores, inner_probabilities, inner_anomaly
        )
        metric = (
            metrics["candidate_exact_accuracy"]
            + 0.20 * metrics["segment_macro_f1"]
            + 0.25 * metrics["anomaly_f1"]
            - 0.05 * metrics["ece"]
        )
        history.append(
            {
                "epoch": epoch,
                "train_loss": loss_total / max(1, batch_count),
                "train_listwise_loss": listwise_total / max(1, batch_count),
                "train_anomaly_loss": anomaly_total / max(1, batch_count),
                **{f"inner_{key}": value for key, value in metrics.items()},
                "selection_metric": metric,
            }
        )
        if metric > best_metric + 1e-9:
            best_metric = metric
            best_epoch = epoch
            best_state = copy.deepcopy(
                {key: value.detach().cpu() for key, value in model.state_dict().items()}
            )
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= config.patience:
                break
    if best_state is None:
        raise RuntimeError("safety-head training did not produce a checkpoint")
    model.load_state_dict(best_state)
    model.to(device)
    inner_scores, inner_probabilities, inner_anomaly = score_encoded_groups(
        model,
        encoded_inner,
        batch_group_count=config.batch_group_count,
        device=device,
    )
    thresholds = select_safety_threshold(
        inner_groups,
        inner_scores,
        inner_probabilities,
        inner_anomaly,
        proposals=proposals,
    )
    held_scores, held_probabilities, held_anomaly = score_encoded_groups(
        model,
        encoded_held,
        batch_group_count=config.batch_group_count,
        device=device,
    )
    held_decisions, held_evaluation = safety_decision_rows(
        held_groups,
        held_scores,
        held_probabilities,
        held_anomaly,
        proposals=proposals,
        risk_threshold=float(thresholds["risk_threshold"]),
    )
    held_metrics = safety_metrics(held_groups, held_decisions, held_evaluation)
    return {
        "model": model,
        "device": device,
        "vocabulary": vocabulary,
        "train_groups": train_groups,
        "inner_groups": inner_groups,
        "held_out_groups": held_groups,
        "held_out_scores": held_scores,
        "held_out_probabilities": held_probabilities,
        "held_out_anomaly_probabilities": held_anomaly,
        "held_out_decisions": held_decisions,
        "held_out_evaluation": held_evaluation,
        "thresholds": thresholds,
        "history": history,
        "summary": {
            "seed": seed,
            "held_out_fold": held_out_fold,
            "best_epoch": best_epoch,
            "best_inner_metric": best_metric,
            "parameter_count": parameters,
            "train_case_count": len(train_cases),
            "inner_validation_case_count": len(inner_cases),
            "held_out_case_count": len(held_out_cases),
            "train_group_count": len(train_groups),
            "inner_validation_group_count": len(inner_groups),
            "held_out_group_count": len(held_groups),
            "training_wall_seconds": time.perf_counter() - started,
            "device": str(device),
            **thresholds,
            **{f"held_out_{key}": value for key, value in held_metrics.items()},
        },
    }


def select_safety_threshold(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
    *,
    proposals: Mapping[str, Mapping[str, Any]],
) -> dict[str, float]:
    raw = _raw_rows(groups, scores, probabilities, anomaly_probabilities, proposals)
    unsafe_preeligible_risks = [
        float(row["risk"])
        for row in raw
        if row["preeligible"]
        and (
            not row["proposal_correct"]
            or row["anomaly_target"]
            or row["truth_target"] == "REVIEW_FALLBACK"
        )
    ]
    risk_threshold = (
        math.nextafter(max(unsafe_preeligible_risks), math.inf)
        if unsafe_preeligible_risks
        else 0.0
    )
    decisions, evaluation = safety_decision_rows(
        groups,
        scores,
        probabilities,
        anomaly_probabilities,
        proposals=proposals,
        risk_threshold=risk_threshold,
    )
    metrics = safety_metrics(groups, decisions, evaluation)
    if metrics["accepted_wrong_count"] != 0 or metrics["unsafe_fallback_recall"] != 1.0:
        raise ValueError("inner safety threshold did not preserve the zero-error contract")
    return {
        "risk_threshold": risk_threshold,
        **{f"inner_{key}": value for key, value in metrics.items()},
    }


def safety_decision_rows(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
    *,
    proposals: Mapping[str, Mapping[str, Any]],
    risk_threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw = _raw_rows(groups, scores, probabilities, anomaly_probabilities, proposals)
    decisions: list[dict[str, Any]] = []
    evaluation: list[dict[str, Any]] = []
    for row in raw:
        accepted = bool(row["preeligible"]) and float(row["risk"]) >= risk_threshold
        if accepted:
            reason = "safety_head_passed"
        elif not row["proposal_candidate_id"]:
            reason = "base_seed_candidate_disagreement"
        elif row["hard_unsafe"]:
            reason = "hard_unsafe"
        elif row["proposal_target"] == "REVIEW_FALLBACK":
            reason = "review_proposal"
        elif not row["safety_matches_proposal"]:
            reason = "safety_candidate_disagreement"
        else:
            reason = "safety_risk_threshold"
        decisions.append(
            {
                "case_key": row["case_key"],
                "group_id": row["group_id"],
                "object_type": "SEGMENT",
                "fold": row["fold"],
                "proposal_candidate_id": row["proposal_candidate_id"],
                "proposal_target": row["proposal_target"],
                "safety_candidate_id": row["safety_candidate_id"],
                "safety_target": row["safety_target"],
                "safety_probability": row["safety_probability"],
                "anomaly_probability": row["anomaly_probability"],
                "risk": row["risk"],
                "risk_threshold": risk_threshold,
                "accepted": accepted,
                "decision": "ACCEPT" if accepted else "FALLBACK",
                "fallback_unit": "SEGMENT",
                "reason": reason,
                "feature_uses_truth": False,
                "feature_uses_identifier": False,
            }
        )
        evaluation.append(
            {
                "case_key": row["case_key"],
                "group_id": row["group_id"],
                "truth_candidate_id": row["truth_candidate_id"],
                "truth_target": row["truth_target"],
                "anomaly_target": row["anomaly_target"],
                "proposal_correct": row["proposal_correct"],
                "accepted": accepted,
                "label_only": True,
            }
        )
    return decisions, evaluation


def safety_metrics(
    groups: Sequence[P1GroupExample],
    decisions: Sequence[Mapping[str, Any]],
    evaluation: Sequence[Mapping[str, Any]],
) -> dict[str, float | int]:
    if len(groups) != len(decisions) or len(groups) != len(evaluation):
        raise ValueError("safety metric denominator differs")
    accepted = [row for row in evaluation if bool(row["accepted"])]
    wrong = [row for row in accepted if not bool(row["proposal_correct"])]
    unsafe = [
        row
        for row in evaluation
        if not bool(row["proposal_correct"])
        or bool(row["anomaly_target"])
        or row["truth_target"] == "REVIEW_FALLBACK"
    ]
    use_groups = [group for group in groups if group.truth_target == "USE_RCSD"]
    accepted_by_group = {str(row["group_id"]): bool(row["accepted"]) for row in evaluation}
    use_accepted = sum(accepted_by_group[group.group_id] for group in use_groups)
    review_auto = sum(
        bool(row["accepted"]) and row["truth_target"] == "REVIEW_FALLBACK"
        for row in evaluation
    )
    return {
        "accepted_count": len(accepted),
        "accepted_wrong_count": len(wrong),
        "accepted_precision": sum(bool(row["proposal_correct"]) for row in accepted)
        / max(1, len(accepted)),
        "safe_coverage": len(accepted) / max(1, len(groups)),
        "use_rcsd_safe_coverage": use_accepted / max(1, len(use_groups)),
        "unsafe_fallback_recall": sum(not bool(row["accepted"]) for row in unsafe)
        / max(1, len(unsafe)),
        "review_auto_publish_count": review_auto,
    }


def _raw_rows(
    groups: Sequence[P1GroupExample],
    scores: Sequence[Sequence[float]],
    probabilities: Sequence[Sequence[float]],
    anomaly_probabilities: Sequence[float],
    proposals: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group, group_scores, group_probabilities, anomaly_probability in zip(
        groups, scores, probabilities, anomaly_probabilities, strict=True
    ):
        proposal = proposals[group.group_id]
        proposal_id = str(proposal.get("candidate_id") or "")
        safety_index = max(
            range(len(group_scores)),
            key=lambda index: (float(group_scores[index]), group.candidates[index].candidate_id),
        )
        safety_candidate = group.candidates[safety_index]
        proposal_indices = [
            index for index, candidate in enumerate(group.candidates) if candidate.candidate_id == proposal_id
        ]
        proposal_probability = (
            float(group_probabilities[proposal_indices[0]]) if len(proposal_indices) == 1 else 0.0
        )
        safety_matches = safety_candidate.candidate_id == proposal_id and bool(proposal_id)
        risk = min(proposal_probability, 1.0 - float(anomaly_probability)) if safety_matches else 0.0
        rows.append(
            {
                "case_key": group.case_key,
                "group_id": group.group_id,
                "fold": group.fold,
                "proposal_candidate_id": proposal_id,
                "proposal_target": str(proposal.get("candidate_target") or ""),
                "safety_candidate_id": safety_candidate.candidate_id,
                "safety_target": safety_candidate.candidate_target,
                "safety_probability": proposal_probability,
                "anomaly_probability": float(anomaly_probability),
                "risk": risk,
                "hard_unsafe": group.hard_unsafe,
                "safety_matches_proposal": safety_matches,
                "preeligible": bool(proposal_id)
                and not group.hard_unsafe
                and str(proposal.get("candidate_target") or "") != "REVIEW_FALLBACK"
                and safety_matches,
                "truth_candidate_id": group.candidates[group.truth_index].candidate_id,
                "truth_target": group.truth_target,
                "anomaly_target": group.anomaly_target,
                "proposal_correct": proposal_id == group.candidates[group.truth_index].candidate_id,
            }
        )
    return rows


def _iter_batches(
    groups: Sequence[P1EncodedGroup], *, batch_group_count: int, seed: int
) -> Iterable[list[P1EncodedGroup]]:
    indices = list(range(len(groups)))
    random.Random(seed).shuffle(indices)
    for start in range(0, len(indices), batch_group_count):
        yield [groups[index] for index in indices[start : start + batch_group_count]]


def _resolve_device(value: str) -> torch.device:
    if value == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable")
    if value in {"auto", "cuda"} and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


__all__ = [
    "safety_decision_rows",
    "safety_metrics",
    "select_safety_threshold",
    "train_segment_safety_fold",
]
