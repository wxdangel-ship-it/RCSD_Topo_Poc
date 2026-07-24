from __future__ import annotations

import copy
import hashlib
import math
import os
import random
import time
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    select_inner_validation_cases,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p0_models import (
    SafetyEvidenceExample,
    SchemeAP2P2P2P0Config,
)


class LinearRiskProbe(nn.Module):
    def __init__(self, input_dim: int) -> None:
        super().__init__()
        self.network = nn.Linear(input_dim, 1)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features).squeeze(-1)


class ShallowRiskProbe(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, max(2, hidden_dim // 2)),
            nn.ReLU(),
            nn.Linear(max(2, hidden_dim // 2), 1),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features).squeeze(-1)


def train_probe_fold(
    examples: Sequence[SafetyEvidenceExample],
    *,
    case_folds: Mapping[str, int],
    held_out_fold: int,
    probe_name: str,
    config: SchemeAP2P2P2P0Config,
) -> dict[str, Any]:
    seed = config.probe_seed + held_out_fold + (0 if probe_name == "LINEAR" else 1000)
    train_cases, inner_cases, held_cases = select_inner_validation_cases(
        case_folds,
        held_out_fold=held_out_fold,
        seed=seed,
        ratio=config.inner_validation_ratio,
    )
    train = [example for example in examples if example.case_key in set(train_cases)]
    inner = [example for example in examples if example.case_key in set(inner_cases)]
    held = [example for example in examples if example.case_key in set(held_cases)]
    if not train or not inner or not held:
        raise ValueError("probe train/inner/held-out scope must not be empty")
    means, scales = _normalization(train)
    train_x, train_y = _tensors(train, means, scales)
    inner_x, inner_y = _tensors(inner, means, scales)
    held_x, _held_y = _tensors(held, means, scales)

    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(config.torch_num_threads)
    model: nn.Module
    if probe_name == "LINEAR":
        model = LinearRiskProbe(train_x.shape[1])
    elif probe_name == "SHALLOW_MLP":
        model = ShallowRiskProbe(train_x.shape[1], config.hidden_dim)
    else:
        raise ValueError(f"unsupported preregistered probe: {probe_name}")
    parameters = sum(parameter.numel() for parameter in model.parameters())
    if parameters >= 100_000:
        raise ValueError(f"probe parameter count exceeds contract: {parameters}")
    positive = float(train_y.sum())
    negative = float(len(train_y) - positive)
    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(negative / max(1.0, positive), dtype=torch.float32)
    )
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    best_state: dict[str, torch.Tensor] | None = None
    best_loss = math.inf
    best_epoch = 0
    stale = 0
    history: list[dict[str, Any]] = []
    started = time.perf_counter()
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(train_x), train_y)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        model.eval()
        with torch.no_grad():
            inner_loss = float(criterion(model(inner_x), inner_y))
        history.append(
            {"epoch": epoch, "train_loss": float(loss.detach()), "inner_loss": inner_loss}
        )
        if inner_loss < best_loss - 1e-9:
            best_loss = inner_loss
            best_epoch = epoch
            best_state = copy.deepcopy(
                {key: value.detach().cpu() for key, value in model.state_dict().items()}
            )
            stale = 0
        else:
            stale += 1
            if stale >= config.patience:
                break
    if best_state is None:
        raise RuntimeError("probe training did not produce a checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        inner_probability = torch.sigmoid(model(inner_x)).tolist()
        held_probability = torch.sigmoid(model(held_x)).tolist()
    threshold = select_zero_error_threshold(inner, inner_probability)
    held_rows = decision_rows(held, held_probability, threshold=threshold)
    metrics = probe_metrics(held, held_rows)
    return {
        "model": model,
        "state_signature": state_signature(model),
        "parameter_count": parameters,
        "means": means,
        "scales": scales,
        "threshold": threshold,
        "history": history,
        "held_out_examples": held,
        "held_out_probabilities": held_probability,
        "held_out_rows": held_rows,
        "summary": {
            "probe": probe_name,
            "held_out_fold": held_out_fold,
            "best_epoch": best_epoch,
            "best_inner_loss": best_loss,
            "parameter_count": parameters,
            "threshold": threshold,
            "train_case_keys": list(train_cases),
            "inner_validation_case_keys": list(inner_cases),
            "held_out_case_keys": list(held_cases),
            "case_overlap_count": len(
                (set(train_cases) & set(inner_cases))
                | (set(train_cases) & set(held_cases))
                | (set(inner_cases) & set(held_cases))
            ),
            "training_wall_seconds": time.perf_counter() - started,
            **metrics,
        },
    }


def select_zero_error_threshold(
    examples: Sequence[SafetyEvidenceExample], probabilities: Sequence[float]
) -> float:
    unsafe = [
        float(probability)
        for example, probability in zip(examples, probabilities, strict=True)
        if _preeligible(example) and example.unsafe
    ]
    return min(unsafe) if unsafe else 0.0


def decision_rows(
    examples: Sequence[SafetyEvidenceExample],
    probabilities: Sequence[float],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for example, probability in zip(examples, probabilities, strict=True):
        accepted = _preeligible(example) and float(probability) < threshold
        if accepted:
            reason = "evidence_probe_passed"
        elif not example.candidate_agreement:
            reason = "base_seed_candidate_disagreement"
        elif example.hard_unsafe:
            reason = "hard_unsafe"
        elif example.proposal_target == "REVIEW_FALLBACK":
            reason = "review_proposal"
        else:
            reason = "evidence_risk_threshold"
        rows.append(
            {
                "case_key": example.case_key,
                "group_id": example.group_id,
                "object_type": "SEGMENT",
                "fold": example.fold,
                "proposal_candidate_id": example.proposal_candidate_id,
                "proposal_target": example.proposal_target,
                "unsafe_probability": float(probability),
                "risk": 1.0 - float(probability),
                "safety_probability": 1.0 - float(probability),
                "anomaly_probability": float(probability),
                "risk_threshold": threshold,
                "accepted": accepted,
                "decision": "ACCEPT" if accepted else "FALLBACK",
                "fallback_unit": "SEGMENT",
                "reason": reason,
                "feature_uses_truth": False,
                "feature_uses_identifier": False,
            }
        )
    return rows


def probe_metrics(
    examples: Sequence[SafetyEvidenceExample], rows: Sequence[Mapping[str, Any]]
) -> dict[str, float | int]:
    if len(examples) != len(rows):
        raise ValueError("probe metric denominator differs")
    accepted = [
        example
        for example, row in zip(examples, rows, strict=True)
        if bool(row["accepted"])
    ]
    unsafe = [example for example in examples if example.unsafe]
    accepted_by_group = {
        example.group_id: bool(row["accepted"])
        for example, row in zip(examples, rows, strict=True)
    }
    use = [example for example in examples if example.truth_target == "USE_RCSD"]
    return {
        "accepted_count": len(accepted),
        "accepted_wrong_count": sum(not example.proposal_correct for example in accepted),
        "accepted_precision": sum(example.proposal_correct for example in accepted)
        / max(1, len(accepted)),
        "safe_coverage": len(accepted) / max(1, len(examples)),
        "use_rcsd_safe_coverage": sum(accepted_by_group[example.group_id] for example in use)
        / max(1, len(use)),
        "unsafe_fallback_recall": sum(
            not accepted_by_group[example.group_id] for example in unsafe
        )
        / max(1, len(unsafe)),
        "review_auto_publish_count": sum(
            accepted_by_group[example.group_id] for example in examples if example.review_target
        ),
    }


def state_signature(model: nn.Module) -> str:
    digest = hashlib.sha256()
    for key, value in sorted(model.state_dict().items()):
        digest.update(key.encode("utf-8"))
        digest.update(value.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def _normalization(
    examples: Sequence[SafetyEvidenceExample],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    width = len(examples[0].features)
    means = tuple(
        sum(example.features[index] for example in examples) / len(examples)
        for index in range(width)
    )
    scales = tuple(
        max(
            1e-6,
            math.sqrt(
                sum((example.features[index] - means[index]) ** 2 for example in examples)
                / len(examples)
            ),
        )
        for index in range(width)
    )
    return means, scales


def _tensors(
    examples: Sequence[SafetyEvidenceExample],
    means: Sequence[float],
    scales: Sequence[float],
) -> tuple[torch.Tensor, torch.Tensor]:
    features = torch.tensor(
        [
            [
                (value - means[index]) / scales[index]
                for index, value in enumerate(example.features)
            ]
            for example in examples
        ],
        dtype=torch.float32,
    )
    targets = torch.tensor(
        [float(example.unsafe or example.hard_unsafe or not example.candidate_agreement) for example in examples],
        dtype=torch.float32,
    )
    return features, targets


def _preeligible(example: SafetyEvidenceExample) -> bool:
    return (
        example.candidate_agreement
        and not example.hard_unsafe
        and example.proposal_target != "REVIEW_FALLBACK"
    )


__all__ = [
    "LinearRiskProbe",
    "ShallowRiskProbe",
    "decision_rows",
    "probe_metrics",
    "select_zero_error_threshold",
    "state_signature",
    "train_probe_fold",
]
