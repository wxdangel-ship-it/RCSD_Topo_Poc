from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import torch
from torch import nn


PLAN_RISK_FEATURE_NAMES = (
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
    "plan_validity_head_present",
    "selected_plan_validity_probability",
    "selected_plan_validity_margin",
    "selected_plan_validity_gap",
    "plan_validity_positive_fraction",
    "decision_confidence",
    "decision_margin",
    "decision_head_agrees",
    "decision_head_confidence",
    "decision_head_margin",
    "decision_head_normalized_entropy",
    "decision_validity_head_present",
    "selected_decision_validity_probability",
    "selected_decision_validity_margin",
    "selected_decision_validity_gap",
    "decision_validity_positive_fraction",
    "within_decision_confidence",
    "within_decision_margin",
    "within_decision_normalized_entropy",
)

ANCHOR_RISK_FEATURE_NAMES = (
    "required_anchor_count",
    "primary_observed_fraction",
    "secondary_observed_fraction",
    "candidate_id_agreement_fraction",
    "candidate_type_agreement_fraction",
    "secondary_success_fraction",
    "primary_candidate_confidence_min",
    "primary_candidate_confidence_mean",
    "primary_candidate_margin_min",
    "primary_candidate_margin_mean",
    "primary_candidate_entropy_max",
    "primary_candidate_entropy_mean",
    "primary_status_confidence_min",
    "primary_status_confidence_mean",
    "primary_status_margin_min",
    "primary_status_margin_mean",
    "primary_status_entropy_max",
    "primary_status_entropy_mean",
    "primary_gate_probability_min",
    "primary_gate_probability_mean",
    "primary_joint_score_min",
    "primary_joint_score_mean",
    "secondary_success_probability_min",
    "secondary_success_probability_mean",
    "secondary_gate_probability_min",
    "secondary_gate_probability_mean",
    "secondary_candidate_probability_min",
    "secondary_candidate_probability_mean",
    "secondary_candidate_margin_min",
    "secondary_candidate_margin_mean",
    "secondary_type_probability_min",
    "secondary_type_probability_mean",
    "secondary_type_margin_min",
    "secondary_type_margin_mean",
    "secondary_member_inclusion_margin_min",
    "secondary_member_inclusion_margin_mean",
    "secondary_member_excluded_probability_max",
    "secondary_member_excluded_probability_mean",
    "secondary_member_entropy_max",
    "secondary_member_entropy_mean",
    "secondary_cardinality_residual_max",
    "secondary_cardinality_residual_mean",
    "secondary_set_mean_log_probability_min",
    "secondary_set_mean_log_probability_mean",
)


@dataclass(frozen=True)
class DualRiskGateConfig:
    learning_rate: float = 0.02
    weight_decay: float = 0.05
    epoch_count: int = 400
    seed: int = 20260797
    requested_device: str = "cpu"

    def validate(self) -> None:
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("dual risk optimizer parameters are invalid")
        if self.epoch_count < 1:
            raise ValueError("dual risk epoch_count must be positive")
        if self.requested_device not in {"cpu", "cuda"}:
            raise ValueError("dual risk requested_device must be cpu or cuda")


class LinearRiskHead(nn.Module):
    def __init__(self, feature_dim: int) -> None:
        super().__init__()
        self.output = nn.Linear(feature_dim, 1)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.output(features).squeeze(-1)


@dataclass
class PercentileRiskFit:
    model: LinearRiskHead
    feature_mean: torch.Tensor
    feature_scale: torch.Tensor
    reference_scores: torch.Tensor
    training_loss: float
    positive_count: int
    negative_count: int


@dataclass
class CrossFittedDualRiskResult:
    anchor_scores: dict[str, float]
    plan_scores: dict[str, float]
    anchor_threshold: float
    plan_threshold: float
    final_anchor_fit: PercentileRiskFit
    final_plan_fit: PercentileRiskFit
    fold_summaries: list[dict[str, Any]]


def plan_risk_features(row: Mapping[str, Any]) -> tuple[float, ...]:
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
        "plan_validity_head_present": float(
            row.get("plan_validity_head_present", False)
        ),
        "selected_plan_validity_probability": float(
            row.get("selected_plan_validity_probability", 0.5)
        ),
        "selected_plan_validity_margin": float(
            row.get("selected_plan_validity_margin", 0.0)
        ),
        "selected_plan_validity_gap": float(
            row.get("selected_plan_validity_gap", 0.0)
        ),
        "plan_validity_positive_fraction": float(
            row.get("plan_validity_positive_fraction", 0.0)
        ),
        "decision_confidence": float(row["decision_confidence"]),
        "decision_margin": float(row["decision_margin"]),
        "decision_head_agrees": float(row["decision_head_agrees"]),
        "decision_head_confidence": float(row["decision_head_confidence"]),
        "decision_head_margin": float(row["decision_head_margin"]),
        "decision_head_normalized_entropy": float(
            row["decision_head_normalized_entropy"]
        ),
        "decision_validity_head_present": float(
            row.get("decision_validity_head_present", False)
        ),
        "selected_decision_validity_probability": float(
            row.get("selected_decision_validity_probability", 0.5)
        ),
        "selected_decision_validity_margin": float(
            row.get("selected_decision_validity_margin", 0.0)
        ),
        "selected_decision_validity_gap": float(
            row.get("selected_decision_validity_gap", 0.0)
        ),
        "decision_validity_positive_fraction": float(
            row.get("decision_validity_positive_fraction", 0.0)
        ),
        "within_decision_confidence": float(
            row["within_decision_confidence"]
        ),
        "within_decision_margin": float(row["within_decision_margin"]),
        "within_decision_normalized_entropy": float(
            row["within_decision_normalized_entropy"]
        ),
    }
    return tuple(float(payload[name]) for name in PLAN_RISK_FEATURE_NAMES)


def anchor_risk_features(
    row: Mapping[str, Any],
    *,
    primary_anchor_by_key: Mapping[
        tuple[str, str],
        Mapping[str, Any],
    ],
    secondary_anchor_by_key: Mapping[
        tuple[str, str],
        Mapping[str, Any],
    ],
) -> tuple[float, ...]:
    case_key = str(row["case_key"])
    required_ids = tuple(str(value) for value in row["required_anchor_ids"])
    primary = [
        primary_anchor_by_key.get((case_key, anchor_id))
        for anchor_id in required_ids
    ]
    secondary = [
        secondary_anchor_by_key.get((case_key, anchor_id))
        for anchor_id in required_ids
    ]
    paired = [
        (left, right)
        for left, right in zip(primary, secondary, strict=True)
        if left is not None and right is not None
    ]
    primary_rows = [value for value in primary if value is not None]
    secondary_rows = [value for value in secondary if value is not None]
    count = len(required_ids)
    payload = {
        "required_anchor_count": float(count),
        "primary_observed_fraction": (
            len(primary_rows) / count if count else 0.0
        ),
        "secondary_observed_fraction": (
            len(secondary_rows) / count if count else 0.0
        ),
        "candidate_id_agreement_fraction": _paired_fraction(
            paired,
            lambda left, right: (
                str(left["candidate_predicted_id"])
                == str(right["candidate_predicted_id"])
            ),
        ),
        "candidate_type_agreement_fraction": _paired_fraction(
            paired,
            lambda left, right: (
                str(left["candidate_predicted_id"]).split(":", 1)[0]
                == str(right["candidate_predicted_id"]).split(":", 1)[0]
            ),
        ),
        "secondary_success_fraction": _fraction(
            secondary_rows,
            lambda value: str(value["predicted"]) == "SUCCESS",
        ),
    }
    _add_aggregates(
        payload,
        primary_rows,
        (
            (
                "candidate_confidence",
                "primary_candidate_confidence",
                ("min", "mean"),
            ),
            (
                "candidate_margin",
                "primary_candidate_margin",
                ("min", "mean"),
            ),
            (
                "candidate_normalized_entropy",
                "primary_candidate_entropy",
                ("max", "mean"),
            ),
            (
                "status_confidence",
                "primary_status_confidence",
                ("min", "mean"),
            ),
            (
                "status_margin",
                "primary_status_margin",
                ("min", "mean"),
            ),
            (
                "status_normalized_entropy",
                "primary_status_entropy",
                ("max", "mean"),
            ),
            (
                "anchor_gate_success_probability",
                "primary_gate_probability",
                ("min", "mean"),
            ),
            (
                "joint_score",
                "primary_joint_score",
                ("min", "mean"),
            ),
        ),
    )
    _add_aggregates(
        payload,
        secondary_rows,
        (
            (
                "success_probability",
                "secondary_success_probability",
                ("min", "mean"),
            ),
            (
                "gate_pass_probability",
                "secondary_gate_probability",
                ("min", "mean"),
            ),
            (
                "candidate_probability",
                "secondary_candidate_probability",
                ("min", "mean"),
            ),
            (
                "candidate_margin",
                "secondary_candidate_margin",
                ("min", "mean"),
            ),
            (
                "anchor_type_probability",
                "secondary_type_probability",
                ("min", "mean"),
            ),
            (
                "anchor_type_margin",
                "secondary_type_margin",
                ("min", "mean"),
            ),
            (
                "member_inclusion_margin",
                "secondary_member_inclusion_margin",
                ("min", "mean"),
            ),
            (
                "member_max_excluded_probability",
                "secondary_member_excluded_probability",
                ("max", "mean"),
            ),
            (
                "member_mean_entropy",
                "secondary_member_entropy",
                ("max", "mean"),
            ),
            (
                "member_cardinality_residual",
                "secondary_cardinality_residual",
                ("max", "mean"),
            ),
            (
                "member_set_mean_log_probability",
                "secondary_set_mean_log_probability",
                ("min", "mean"),
            ),
        ),
    )
    return tuple(float(payload[name]) for name in ANCHOR_RISK_FEATURE_NAMES)


def fit_cross_fitted_dual_risk_gate(
    ordinary_rows: Sequence[Mapping[str, Any]],
    primary_anchor_rows: Sequence[Mapping[str, Any]],
    secondary_anchor_rows: Sequence[Mapping[str, Any]],
    *,
    config: DualRiskGateConfig,
) -> CrossFittedDualRiskResult:
    config.validate()
    eligible = [row for row in ordinary_rows if _eligible(row)]
    folds = sorted({int(row["fold"]) for row in eligible})
    if len(folds) < 3:
        raise ValueError("dual risk gate requires at least three folds")
    _assert_case_disjoint_folds(eligible)
    primary_index = _anchor_index(
        primary_anchor_rows,
        id_field="candidate_predicted_id",
    )
    secondary_index = _anchor_index(
        secondary_anchor_rows,
        id_field="candidate_predicted_id",
    )

    def anchor_features(value: Mapping[str, Any]) -> tuple[float, ...]:
        return anchor_risk_features(
            value,
            primary_anchor_by_key=primary_index,
            secondary_anchor_by_key=secondary_index,
        )

    anchor_scores = {}
    plan_scores = {}
    fold_summaries = []
    for fold in folds:
        training = [row for row in eligible if int(row["fold"]) != fold]
        validation = [row for row in eligible if int(row["fold"]) == fold]
        anchor_fit = _fit_percentile_head(
            training,
            feature_builder=anchor_features,
            label_builder=_anchor_truth_safe,
            feature_count=len(ANCHOR_RISK_FEATURE_NAMES),
            config=config,
            seed=config.seed + fold * 211,
        )
        plan_fit = _fit_percentile_head(
            training,
            feature_builder=plan_risk_features,
            label_builder=_plan_truth_safe,
            feature_count=len(PLAN_RISK_FEATURE_NAMES),
            config=config,
            seed=config.seed + fold * 211 + 97,
        )
        local_anchor_scores = _score_percentiles(
            anchor_fit,
            validation,
            feature_builder=anchor_features,
            requested_device=config.requested_device,
        )
        local_plan_scores = _score_percentiles(
            plan_fit,
            validation,
            feature_builder=plan_risk_features,
            requested_device=config.requested_device,
        )
        for row, anchor_score, plan_score in zip(
            validation,
            local_anchor_scores,
            local_plan_scores,
            strict=True,
        ):
            sample_id = str(row["sample_id"])
            if sample_id in anchor_scores:
                raise ValueError("duplicate dual-risk cross-fitted sample")
            anchor_scores[sample_id] = anchor_score
            plan_scores[sample_id] = plan_score
        fold_summaries.append(
            {
                "fold": fold,
                "training_count": len(training),
                "validation_count": len(validation),
                "anchor_training_loss": anchor_fit.training_loss,
                "plan_training_loss": plan_fit.training_loss,
            }
        )
    anchor_threshold = _zero_unsafe_threshold(
        eligible,
        anchor_scores,
        label_builder=_anchor_truth_safe,
    )
    plan_threshold = _zero_unsafe_threshold(
        eligible,
        plan_scores,
        label_builder=_plan_truth_safe,
    )
    final_anchor_fit = _fit_percentile_head(
        eligible,
        feature_builder=anchor_features,
        label_builder=_anchor_truth_safe,
        feature_count=len(ANCHOR_RISK_FEATURE_NAMES),
        config=config,
        seed=config.seed,
    )
    final_plan_fit = _fit_percentile_head(
        eligible,
        feature_builder=plan_risk_features,
        label_builder=_plan_truth_safe,
        feature_count=len(PLAN_RISK_FEATURE_NAMES),
        config=config,
        seed=config.seed + 97,
    )
    return CrossFittedDualRiskResult(
        anchor_scores=anchor_scores,
        plan_scores=plan_scores,
        anchor_threshold=anchor_threshold,
        plan_threshold=plan_threshold,
        final_anchor_fit=final_anchor_fit,
        final_plan_fit=final_plan_fit,
        fold_summaries=fold_summaries,
    )


def score_dual_risk_rows(
    result: CrossFittedDualRiskResult,
    rows: Sequence[Mapping[str, Any]],
    primary_anchor_rows: Sequence[Mapping[str, Any]],
    secondary_anchor_rows: Sequence[Mapping[str, Any]],
    *,
    requested_device: str,
) -> tuple[list[float], list[float]]:
    primary_index = _anchor_index(
        primary_anchor_rows,
        id_field="candidate_predicted_id",
    )
    secondary_index = _anchor_index(
        secondary_anchor_rows,
        id_field="candidate_predicted_id",
    )

    def anchor_features(value: Mapping[str, Any]) -> tuple[float, ...]:
        return anchor_risk_features(
            value,
            primary_anchor_by_key=primary_index,
            secondary_anchor_by_key=secondary_index,
        )

    return (
        _score_percentiles(
            result.final_anchor_fit,
            rows,
            feature_builder=anchor_features,
            requested_device=requested_device,
        ),
        _score_percentiles(
            result.final_plan_fit,
            rows,
            feature_builder=plan_risk_features,
            requested_device=requested_device,
        ),
    )


def apply_dual_risk_gate(
    rows: Sequence[Mapping[str, Any]],
    *,
    anchor_scores: Mapping[str, float],
    plan_scores: Mapping[str, float],
    anchor_threshold: float,
    plan_threshold: float,
) -> list[dict[str, Any]]:
    result = []
    for source in rows:
        row = dict(source)
        sample_id = str(row["sample_id"])
        anchor_score = float(anchor_scores.get(sample_id, 0.0))
        plan_score = float(plan_scores.get(sample_id, 0.0))
        accepted = bool(
            _eligible(row)
            and anchor_score >= anchor_threshold
            and plan_score >= plan_threshold
        )
        row["anchor_risk_score"] = anchor_score
        row["anchor_risk_threshold"] = anchor_threshold
        row["plan_risk_score"] = plan_score
        row["plan_risk_threshold"] = plan_threshold
        row["risk_accepted"] = accepted
        result.append(row)
    return result


def zero_unsafe_dual_thresholds(
    rows: Sequence[Mapping[str, Any]],
    *,
    anchor_scores: Mapping[str, float],
    plan_scores: Mapping[str, float],
) -> dict[str, Any]:
    eligible = [row for row in rows if _eligible(row)]
    anchor_candidates = sorted(
        {
            float(anchor_scores[str(row["sample_id"])])
            for row in eligible
        }
    )
    best = None
    for anchor_threshold in anchor_candidates:
        anchor_passed = [
            row
            for row in eligible
            if float(anchor_scores[str(row["sample_id"])])
            >= anchor_threshold
        ]
        unsafe_plan_scores = [
            float(plan_scores[str(row["sample_id"])])
            for row in anchor_passed
            if not _final_truth_safe(row)
        ]
        plan_threshold = (
            math.nextafter(max(unsafe_plan_scores), math.inf)
            if unsafe_plan_scores
            else 0.0
        )
        automatic = [
            row
            for row in anchor_passed
            if float(plan_scores[str(row["sample_id"])])
            >= plan_threshold
        ]
        unsafe_count = sum(
            not _final_truth_safe(row) for row in automatic
        )
        if unsafe_count:
            raise AssertionError("dual threshold search accepted unsafe row")
        correct_count = len(automatic)
        use_count = sum(
            row["predicted_decision"] == "USE_RCSD"
            for row in automatic
        )
        candidate = (
            correct_count,
            use_count,
            anchor_threshold + plan_threshold,
            anchor_threshold,
            plan_threshold,
        )
        if best is None or candidate > best[0]:
            best = (candidate, automatic)
    if best is None:
        return {
            "anchor_threshold": math.inf,
            "plan_threshold": math.inf,
            "automatic_correct_count": 0,
            "use_automatic_correct_count": 0,
            "unsafe_auto_count": 0,
        }
    candidate, automatic = best
    return {
        "anchor_threshold": candidate[3],
        "plan_threshold": candidate[4],
        "automatic_correct_count": len(automatic),
        "use_automatic_correct_count": sum(
            row["predicted_decision"] == "USE_RCSD"
            for row in automatic
        ),
        "unsafe_auto_count": 0,
    }


def within_scope_percentile_scores(
    rows: Sequence[Mapping[str, Any]],
    scores: Mapping[str, float],
    *,
    scope_builder: Callable[[Mapping[str, Any]], tuple[str, ...]],
) -> dict[str, float]:
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        if _eligible(row):
            groups.setdefault(scope_builder(row), []).append(row)
    result = {}
    for group_rows in groups.values():
        ordered = sorted(
            (
                float(scores[str(row["sample_id"])]),
                str(row["sample_id"]),
            )
            for row in group_rows
        )
        denominator = max(len(ordered), 1)
        index = 0
        while index < len(ordered):
            end = index + 1
            while end < len(ordered) and ordered[end][0] == ordered[index][0]:
                end += 1
            percentile = end / denominator
            for _, sample_id in ordered[index:end]:
                result[sample_id] = percentile
            index = end
    return result


def percentile_fit_payload(
    fit: PercentileRiskFit,
    *,
    feature_names: Sequence[str],
    config: DualRiskGateConfig,
) -> dict[str, Any]:
    return {
        "feature_names": tuple(feature_names),
        "config": config.__dict__,
        "state_dict": fit.model.state_dict(),
        "feature_mean": fit.feature_mean,
        "feature_scale": fit.feature_scale,
        "reference_scores": fit.reference_scores,
        "training_loss": fit.training_loss,
        "positive_count": fit.positive_count,
        "negative_count": fit.negative_count,
    }


def _fit_percentile_head(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_builder: Callable[[Mapping[str, Any]], tuple[float, ...]],
    label_builder: Callable[[Mapping[str, Any]], bool],
    feature_count: int,
    config: DualRiskGateConfig,
    seed: int,
) -> PercentileRiskFit:
    if not rows:
        raise ValueError("dual risk training scope is empty")
    labels = torch.tensor(
        [float(label_builder(row)) for row in rows],
        dtype=torch.float32,
    )
    positive_count = int(labels.sum().item())
    negative_count = len(rows) - positive_count
    if positive_count == 0 or negative_count == 0:
        raise ValueError("dual risk head requires both label classes")
    features = torch.tensor(
        [feature_builder(row) for row in rows],
        dtype=torch.float32,
    )
    if features.shape[1] != feature_count:
        raise ValueError("dual risk feature dimension differs")
    feature_mean = features.mean(dim=0)
    feature_scale = features.std(dim=0, unbiased=False).clamp_min(1e-4)
    normalized = (features - feature_mean) / feature_scale
    device = _resolve_device(config.requested_device)
    normalized = normalized.to(device)
    labels = labels.to(device)
    random.seed(seed)
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    model = LinearRiskHead(feature_count).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    positive_weight = len(rows) / (2.0 * positive_count)
    negative_weight = len(rows) / (2.0 * negative_count)
    weights = torch.where(
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
        loss = (raw * weights).mean()
        if not torch.isfinite(loss):
            raise RuntimeError("dual risk training produced non-finite loss")
        loss.backward()
        optimizer.step()
        loss_value = float(loss.detach().item())
    model.eval()
    with torch.no_grad():
        reference_scores = torch.sort(model(normalized).cpu()).values
    return PercentileRiskFit(
        model=model,
        feature_mean=feature_mean,
        feature_scale=feature_scale,
        reference_scores=reference_scores,
        training_loss=loss_value,
        positive_count=positive_count,
        negative_count=negative_count,
    )


def _score_percentiles(
    fit: PercentileRiskFit,
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_builder: Callable[[Mapping[str, Any]], tuple[float, ...]],
    requested_device: str,
) -> list[float]:
    if not rows:
        return []
    device = _resolve_device(requested_device)
    fit.model.to(device)
    features = torch.tensor(
        [feature_builder(row) for row in rows],
        dtype=torch.float32,
    )
    normalized = (features - fit.feature_mean) / fit.feature_scale
    with torch.no_grad():
        raw = fit.model(normalized.to(device)).cpu()
    ranks = torch.searchsorted(
        fit.reference_scores,
        raw,
        right=True,
    )
    return [
        float(value) / max(len(fit.reference_scores), 1)
        for value in ranks.tolist()
    ]


def _zero_unsafe_threshold(
    rows: Sequence[Mapping[str, Any]],
    scores: Mapping[str, float],
    *,
    label_builder: Callable[[Mapping[str, Any]], bool],
) -> float:
    unsafe = [
        float(scores[str(row["sample_id"])])
        for row in rows
        if not label_builder(row)
    ]
    if not unsafe:
        return 0.0
    return math.nextafter(max(unsafe), math.inf)


def _eligible(row: Mapping[str, Any]) -> bool:
    return bool(
        row["base_releasable"]
        and row["predicted_decision"] != "ABSTAIN"
        and not row.get("no_evidence_keep_exception")
    )


def _anchor_truth_safe(row: Mapping[str, Any]) -> bool:
    return bool(row["required_anchor_truth_correct"])


def _plan_truth_safe(row: Mapping[str, Any]) -> bool:
    return bool(row["truth_label_ready"] and row["plan_correct"])


def _final_truth_safe(row: Mapping[str, Any]) -> bool:
    return bool(row["truth_label_ready"] and row["joint_truth_correct"])


def _anchor_index(
    rows: Sequence[Mapping[str, Any]],
    *,
    id_field: str,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    for row in rows:
        if id_field not in row:
            raise ValueError("dual risk anchor evidence lacks predicted object")
        key = (str(row["case_key"]), str(row["anchor_id"]))
        if key in result:
            raise ValueError("duplicate dual-risk Case/anchor evidence")
        result[key] = row
    return result


def _add_aggregates(
    payload: dict[str, float],
    rows: Sequence[Mapping[str, Any]],
    specifications: Sequence[
        tuple[str, str, Sequence[str]]
    ],
) -> None:
    for source_name, output_prefix, reducers in specifications:
        values = [float(row[source_name]) for row in rows]
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
    raise ValueError(f"unsupported dual risk aggregate: {reducer}")


def _fraction(
    rows: Sequence[Mapping[str, Any]],
    predicate: Callable[[Mapping[str, Any]], bool],
) -> float:
    if not rows:
        return 0.0
    return sum(bool(predicate(row)) for row in rows) / len(rows)


def _paired_fraction(
    rows: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    predicate: Callable[[Mapping[str, Any], Mapping[str, Any]], bool],
) -> float:
    if not rows:
        return 0.0
    return sum(bool(predicate(left, right)) for left, right in rows) / len(rows)


def _assert_case_disjoint_folds(
    rows: Sequence[Mapping[str, Any]],
) -> None:
    case_fold = {}
    for row in rows:
        case_key = str(row["case_key"])
        fold = int(row["fold"])
        previous = case_fold.setdefault(case_key, fold)
        if previous != fold:
            raise ValueError("dual risk calibration Case crosses folds")


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    return torch.device(requested)
