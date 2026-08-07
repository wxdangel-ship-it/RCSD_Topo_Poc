from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import torch
from torch import nn


RISK_FEATURE_NAMES = (
    "decision_keep",
    "decision_use",
    "decision_abstain",
    "log_plan_candidate_count",
    "log_within_decision_candidate_count",
    "log_predicted_plan_road_count",
    "log_predicted_plan_member_count",
    "plan_confidence",
    "plan_margin",
    "plan_normalized_entropy",
    "decision_confidence",
    "decision_margin",
    "within_decision_confidence",
    "within_decision_margin",
    "within_decision_normalized_entropy",
    "required_anchor_count",
    "anchor_observed_fraction",
    "no_evidence_keep_exception",
    "anchor_predicted_road_fraction",
    "anchor_candidate_confidence_min",
    "anchor_candidate_confidence_mean",
    "anchor_candidate_margin_min",
    "anchor_candidate_margin_mean",
    "anchor_candidate_entropy_max",
    "anchor_candidate_entropy_mean",
    "anchor_status_confidence_min",
    "anchor_status_confidence_mean",
    "anchor_status_margin_min",
    "anchor_status_margin_mean",
    "anchor_status_entropy_max",
    "anchor_status_entropy_mean",
    "anchor_gate_probability_min",
    "anchor_gate_probability_mean",
    "anchor_gate_margin_min",
    "anchor_gate_margin_mean",
    "anchor_joint_score_min",
    "anchor_joint_score_mean",
    "anchor_log_candidate_count_max",
    "anchor_log_candidate_count_mean",
    "anchor_no_evidence_probability_max",
    "anchor_no_evidence_probability_mean",
)


@dataclass(frozen=True)
class CaseJointRiskGateConfig:
    hidden_dim: int = 16
    learning_rate: float = 0.01
    weight_decay: float = 0.01
    epoch_count: int = 300
    seed: int = 20260791
    requested_device: str = "cpu"

    def validate(self) -> None:
        if self.hidden_dim < 1:
            raise ValueError("risk hidden_dim must be positive")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("risk optimizer parameters are invalid")
        if self.epoch_count < 1:
            raise ValueError("risk epoch_count must be positive")
        if self.requested_device not in {"cpu", "cuda"}:
            raise ValueError("risk requested_device must be cpu or cuda")


class CaseJointRiskHead(nn.Module):
    def __init__(self, feature_dim: int, hidden_dim: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.layers(features).squeeze(-1)


@dataclass
class CaseJointRiskFit:
    model: CaseJointRiskHead
    feature_mean: torch.Tensor
    feature_scale: torch.Tensor
    training_loss: float
    training_count: int
    positive_count: int
    negative_count: int


@dataclass
class CrossFittedCaseJointRiskResult:
    cross_fitted_scores: dict[str, float]
    threshold: float
    final_fit: CaseJointRiskFit
    fold_summaries: list[dict[str, Any]]


def case_joint_risk_features(
    row: Mapping[str, Any],
    *,
    anchor_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[float, ...]:
    required_ids = tuple(str(value) for value in row["required_anchor_ids"])
    anchors = [
        anchor_by_key.get((str(row["case_key"]), anchor_id))
        for anchor_id in required_ids
    ]
    observed = [anchor for anchor in anchors if anchor is not None]
    required_count = len(required_ids)
    decision = str(row["predicted_decision"])

    payload = {
        "decision_keep": float(decision == "KEEP_SWSD"),
        "decision_use": float(decision == "USE_RCSD"),
        "decision_abstain": float(decision == "ABSTAIN"),
        "log_plan_candidate_count": math.log1p(
            float(row["plan_candidate_count"])
        ),
        "log_within_decision_candidate_count": math.log1p(
            float(row["within_decision_candidate_count"])
        ),
        "log_predicted_plan_road_count": math.log1p(
            float(row["predicted_plan_road_count"])
        ),
        "log_predicted_plan_member_count": math.log1p(
            float(row["predicted_plan_member_count"])
        ),
        "plan_confidence": float(row["plan_confidence"]),
        "plan_margin": float(row["plan_margin"]),
        "plan_normalized_entropy": float(row["plan_normalized_entropy"]),
        "decision_confidence": float(row["decision_confidence"]),
        "decision_margin": float(row["decision_margin"]),
        "within_decision_confidence": float(
            row["within_decision_confidence"]
        ),
        "within_decision_margin": float(row["within_decision_margin"]),
        "within_decision_normalized_entropy": float(
            row["within_decision_normalized_entropy"]
        ),
        "required_anchor_count": float(required_count),
        "anchor_observed_fraction": (
            len(observed) / required_count if required_count else 0.0
        ),
        "no_evidence_keep_exception": float(
            bool(row.get("no_evidence_keep_exception"))
        ),
        "anchor_predicted_road_fraction": _fraction(
            observed,
            lambda anchor: str(anchor["candidate_predicted_id"]).startswith(
                "ROAD:"
            ),
        ),
    }
    _add_anchor_aggregates(payload, observed)
    return tuple(float(payload[name]) for name in RISK_FEATURE_NAMES)


def fit_cross_fitted_case_joint_risk_gate(
    ordinary_rows: Sequence[Mapping[str, Any]],
    anchor_rows: Sequence[Mapping[str, Any]],
    *,
    config: CaseJointRiskGateConfig,
) -> CrossFittedCaseJointRiskResult:
    config.validate()
    eligible = [row for row in ordinary_rows if _risk_training_eligible(row)]
    folds = sorted({int(row["fold"]) for row in eligible})
    if len(folds) < 3:
        raise ValueError("cross-fitted risk gate requires at least three folds")
    _assert_case_disjoint_folds(eligible)
    anchor_by_key = _anchor_index(anchor_rows)
    cross_fitted_scores: dict[str, float] = {}
    fold_summaries = []
    for fold in folds:
        training = [row for row in eligible if int(row["fold"]) != fold]
        validation = [row for row in eligible if int(row["fold"]) == fold]
        fit = fit_case_joint_risk_head(
            training,
            anchor_by_key=anchor_by_key,
            config=CaseJointRiskGateConfig(
                **{
                    **config.__dict__,
                    "seed": config.seed + fold * 101,
                }
            ),
        )
        scores = score_case_joint_risk_rows(
            fit,
            validation,
            anchor_by_key=anchor_by_key,
            requested_device=config.requested_device,
        )
        for row, score in zip(validation, scores, strict=True):
            sample_id = str(row["sample_id"])
            if sample_id in cross_fitted_scores:
                raise ValueError("duplicate cross-fitted risk sample")
            cross_fitted_scores[sample_id] = score
        fold_summaries.append(
            {
                "fold": fold,
                "training_count": len(training),
                "validation_count": len(validation),
                "training_positive_count": fit.positive_count,
                "training_negative_count": fit.negative_count,
                "training_loss": fit.training_loss,
            }
        )
    threshold = zero_unsafe_risk_threshold(
        eligible,
        cross_fitted_scores,
    )
    final_fit = fit_case_joint_risk_head(
        eligible,
        anchor_by_key=anchor_by_key,
        config=config,
    )
    return CrossFittedCaseJointRiskResult(
        cross_fitted_scores=cross_fitted_scores,
        threshold=threshold,
        final_fit=final_fit,
        fold_summaries=fold_summaries,
    )


def fit_case_joint_risk_head(
    rows: Sequence[Mapping[str, Any]],
    *,
    anchor_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    config: CaseJointRiskGateConfig,
) -> CaseJointRiskFit:
    config.validate()
    if not rows:
        raise ValueError("risk training scope is empty")
    labels = torch.tensor(
        [float(_risk_truth_safe(row)) for row in rows],
        dtype=torch.float32,
    )
    positive_count = int(labels.sum().item())
    negative_count = len(rows) - positive_count
    if positive_count == 0 or negative_count == 0:
        raise ValueError("risk training requires positive and negative labels")
    features = torch.tensor(
        [
            case_joint_risk_features(
                row,
                anchor_by_key=anchor_by_key,
            )
            for row in rows
        ],
        dtype=torch.float32,
    )
    feature_mean = features.mean(dim=0)
    feature_scale = features.std(dim=0, unbiased=False).clamp_min(1e-4)
    normalized = (features - feature_mean) / feature_scale
    device = _resolve_device(config.requested_device)
    normalized = normalized.to(device)
    labels = labels.to(device)
    random.seed(config.seed)
    torch.manual_seed(config.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(config.seed)
    model = CaseJointRiskHead(
        len(RISK_FEATURE_NAMES),
        config.hidden_dim,
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    positive_weight = len(rows) / (2.0 * positive_count)
    negative_weight = len(rows) / (2.0 * negative_count)
    sample_weights = torch.where(
        labels > 0.5,
        torch.full_like(labels, positive_weight),
        torch.full_like(labels, negative_weight),
    )
    loss_value = float("nan")
    for _ in range(config.epoch_count):
        optimizer.zero_grad(set_to_none=True)
        logits = model(normalized)
        raw = nn.functional.binary_cross_entropy_with_logits(
            logits,
            labels,
            reduction="none",
        )
        loss = (raw * sample_weights).mean()
        if not torch.isfinite(loss):
            raise RuntimeError("risk training produced non-finite loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        loss_value = float(loss.detach().item())
    model.eval()
    return CaseJointRiskFit(
        model=model,
        feature_mean=feature_mean.cpu(),
        feature_scale=feature_scale.cpu(),
        training_loss=loss_value,
        training_count=len(rows),
        positive_count=positive_count,
        negative_count=negative_count,
    )


def score_case_joint_risk_rows(
    fit: CaseJointRiskFit,
    rows: Sequence[Mapping[str, Any]],
    *,
    anchor_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    requested_device: str,
) -> list[float]:
    if not rows:
        return []
    device = _resolve_device(requested_device)
    fit.model.to(device)
    features = torch.tensor(
        [
            case_joint_risk_features(
                row,
                anchor_by_key=anchor_by_key,
            )
            for row in rows
        ],
        dtype=torch.float32,
    )
    normalized = (
        features - fit.feature_mean
    ) / fit.feature_scale
    with torch.no_grad():
        scores = torch.sigmoid(fit.model(normalized.to(device))).cpu()
    return [float(value) for value in scores.tolist()]


def zero_unsafe_risk_threshold(
    rows: Sequence[Mapping[str, Any]],
    scores_by_sample: Mapping[str, float],
) -> float:
    unsafe_scores = [
        float(scores_by_sample[str(row["sample_id"])])
        for row in rows
        if _risk_training_eligible(row) and not _risk_truth_safe(row)
    ]
    if not unsafe_scores:
        return 0.0
    return math.nextafter(max(unsafe_scores), math.inf)


def apply_case_joint_risk_gate(
    rows: Sequence[Mapping[str, Any]],
    scores_by_sample: Mapping[str, float],
    *,
    threshold: float,
    allow_no_evidence_keep: bool = False,
) -> list[dict[str, Any]]:
    result = []
    for source in rows:
        row = dict(source)
        score = float(scores_by_sample.get(str(row["sample_id"]), 0.0))
        accepted = bool(
            row["base_releasable"]
            and row["predicted_decision"] != "ABSTAIN"
            and score >= threshold
            and (
                allow_no_evidence_keep
                or not row.get("no_evidence_keep_exception")
            )
        )
        row["risk_score"] = score
        row["risk_threshold"] = threshold
        row["risk_accepted"] = accepted
        result.append(row)
    return result


def case_joint_risk_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    automatic = [row for row in rows if row["risk_accepted"]]
    safe = [
        row
        for row in automatic
        if _joint_truth_ready(row) and row["joint_truth_correct"]
    ]
    unsafe = [
        row
        for row in automatic
        if _joint_truth_ready(row) and not row["joint_truth_correct"]
    ]
    review = [row for row in automatic if not _joint_truth_ready(row)]
    use_scope = [
        row
        for row in rows
        if _joint_truth_ready(row)
        and "USE_RCSD" in row.get("acceptable_decisions", ())
    ]
    safe_use = [
        row
        for row in safe
        if row["predicted_decision"] == "USE_RCSD"
    ]
    denominator = max(len(rows), 1)
    use_denominator = max(len(use_scope), 1)
    return {
        "ordinary_count": len(rows),
        "truth_ready_count": sum(
            bool(row["truth_label_ready"]) for row in rows
        ),
        "joint_truth_ready_count": sum(_joint_truth_ready(row) for row in rows),
        "use_acceptable_count": len(use_scope),
        "automatic_count": len(automatic),
        "automatic_correct_count": len(safe),
        "unsafe_auto_count": len(unsafe),
        "automatic_unverified_count": len(review),
        "review_auto_count": len(review),
        "automatic_exact": len(safe) / max(len(automatic), 1),
        "automatic_correct_coverage": len(safe) / denominator,
        "use_automatic_correct_count": len(safe_use),
        "use_automatic_correct_coverage": len(safe_use) / use_denominator,
        "positive_keep_automatic_count": sum(
            row["predicted_decision"] == "KEEP_SWSD" for row in safe
        ),
        "no_evidence_keep_automatic_count": sum(
            bool(row.get("no_evidence_keep_exception"))
            for row in automatic
        ),
    }


def _joint_truth_ready(row: Mapping[str, Any]) -> bool:
    return bool(
        row["truth_label_ready"]
        and row.get("required_anchor_truth_ready", True)
    )


def risk_fit_checkpoint_payload(
    fit: CaseJointRiskFit,
    *,
    config: CaseJointRiskGateConfig,
) -> dict[str, Any]:
    return {
        "feature_names": RISK_FEATURE_NAMES,
        "config": config.__dict__,
        "feature_mean": fit.feature_mean,
        "feature_scale": fit.feature_scale,
        "state_dict": fit.model.state_dict(),
        "training_loss": fit.training_loss,
        "training_count": fit.training_count,
        "positive_count": fit.positive_count,
        "negative_count": fit.negative_count,
    }


def _add_anchor_aggregates(
    payload: dict[str, float],
    anchors: Sequence[Mapping[str, Any]],
) -> None:
    specifications = (
        (
            "candidate_confidence",
            "anchor_candidate_confidence",
            ("min", "mean"),
        ),
        ("candidate_margin", "anchor_candidate_margin", ("min", "mean")),
        (
            "candidate_normalized_entropy",
            "anchor_candidate_entropy",
            ("max", "mean"),
        ),
        (
            "status_confidence",
            "anchor_status_confidence",
            ("min", "mean"),
        ),
        ("status_margin", "anchor_status_margin", ("min", "mean")),
        (
            "status_normalized_entropy",
            "anchor_status_entropy",
            ("max", "mean"),
        ),
        (
            "anchor_gate_success_probability",
            "anchor_gate_probability",
            ("min", "mean"),
        ),
        ("anchor_gate_margin", "anchor_gate_margin", ("min", "mean")),
        ("joint_score", "anchor_joint_score", ("min", "mean")),
        (
            "candidate_count",
            "anchor_log_candidate_count",
            ("max", "mean"),
        ),
        (
            "no_evidence_probability",
            "anchor_no_evidence_probability",
            ("max", "mean"),
        ),
    )
    for source_name, output_prefix, reducers in specifications:
        values = [
            (
                math.log1p(float(anchor[source_name]))
                if source_name == "candidate_count"
                else float(anchor[source_name])
            )
            for anchor in anchors
        ]
        for reducer in reducers:
            payload[f"{output_prefix}_{reducer}"] = _reduce(
                values,
                reducer,
            )


def _reduce(values: Sequence[float], reducer: str) -> float:
    if not values:
        return 0.0
    if reducer == "min":
        return min(values)
    if reducer == "max":
        return max(values)
    if reducer == "mean":
        return sum(values) / len(values)
    raise ValueError(f"unsupported risk aggregate: {reducer}")


def _fraction(
    rows: Sequence[Mapping[str, Any]],
    predicate: Any,
) -> float:
    if not rows:
        return 0.0
    return sum(bool(predicate(row)) for row in rows) / len(rows)


def _risk_training_eligible(row: Mapping[str, Any]) -> bool:
    return bool(
        row["base_releasable"]
        and row["predicted_decision"] != "ABSTAIN"
    )


def _risk_truth_safe(row: Mapping[str, Any]) -> bool:
    return bool(row["truth_label_ready"] and row["joint_truth_correct"])


def _anchor_index(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    for row in rows:
        key = (str(row["case_key"]), str(row["anchor_id"]))
        if key in result:
            raise ValueError("duplicate Case/anchor risk evidence")
        result[key] = row
    return result


def _assert_case_disjoint_folds(
    rows: Sequence[Mapping[str, Any]],
) -> None:
    case_fold = {}
    for row in rows:
        case_key = str(row["case_key"])
        fold = int(row["fold"])
        previous = case_fold.setdefault(case_key, fold)
        if previous != fold:
            raise ValueError("risk calibration Case crosses folds")


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    return torch.device(requested)
