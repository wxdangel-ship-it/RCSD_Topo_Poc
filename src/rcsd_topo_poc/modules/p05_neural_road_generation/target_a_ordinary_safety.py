from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    sha256_file,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_data import (
    OrdinaryAnchorConditionedExample,
    read_oof_anchor_conditioned_ordinary_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_oof import (
    _predict_conditioned_plans,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


_LEGACY_ARM_FEATURE_DIM = 16
_ARM_PROJECTION_KEY = "ordinary_plan_arm_projection.0.weight"
_SAFETY_HIDDEN_DIM = 32
_NEIGHBOR_OBJECT_FEATURE_COUNT = 8
_NEIGHBOR_PLAN_FEATURE_COUNT = 23
_NEIGHBOR_EVIDENCE_DIM = (
    _NEIGHBOR_OBJECT_FEATURE_COUNT
    + 2 * _NEIGHBOR_PLAN_FEATURE_COUNT
    + 3
)
_JUNCTION_NEIGHBOR_CONTEXT_DIM = 2 * (_NEIGHBOR_EVIDENCE_DIM + 1)


class _OrdinaryUseSafetyHead(nn.Module):
    def __init__(self, feature_dim: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(feature_dim, _SAFETY_HIDDEN_DIM),
            nn.GELU(),
            nn.LayerNorm(_SAFETY_HIDDEN_DIM),
            nn.Linear(_SAFETY_HIDDEN_DIM, 1),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.layers(features).squeeze(-1)


def migrate_legacy_ordinary_arm_projection(
    checkpoint_state: Mapping[str, torch.Tensor],
    target_state: Mapping[str, torch.Tensor],
) -> dict[str, torch.Tensor]:
    """Load a 16D v45 arm projection into the 22D v46-compatible network."""
    migrated = dict(checkpoint_state)
    old_weight = checkpoint_state.get(_ARM_PROJECTION_KEY)
    target_weight = target_state.get(_ARM_PROJECTION_KEY)
    if old_weight is None or target_weight is None:
        return migrated
    if old_weight.shape == target_weight.shape:
        return migrated
    expected_old = 2 * _LEGACY_ARM_FEATURE_DIM
    expected_target = 2 * ORDINARY_PLAN_ARM_FEATURE_DIM
    if (
        old_weight.ndim != 2
        or target_weight.ndim != 2
        or old_weight.shape[0] != target_weight.shape[0]
        or old_weight.shape[1] != expected_old
        or target_weight.shape[1] != expected_target
    ):
        raise ValueError(
            "ordinary arm checkpoint projection cannot be migrated"
        )
    expanded = target_weight.detach().clone().zero_()
    expanded[:, :_LEGACY_ARM_FEATURE_DIM] = old_weight[
        :, :_LEGACY_ARM_FEATURE_DIM
    ]
    second_target = ORDINARY_PLAN_ARM_FEATURE_DIM
    expanded[
        :,
        second_target : second_target + _LEGACY_ARM_FEATURE_DIM,
    ] = old_weight[:, _LEGACY_ARM_FEATURE_DIM:]
    migrated[_ARM_PROJECTION_KEY] = expanded
    return migrated


def run_ordinary_use_safety_strict_nested(
    *,
    candidate_store_root: Path,
    preflight_root: Path,
    anchor_store_root: Path,
    anchor_oof_root: Path,
    ordinary_oof_root: Path,
    output_root: Path,
    run_id: str,
    seed: int,
    batch_size: int = 64,
    requested_device: str = "cpu",
    training_epochs: int = 300,
) -> Path:
    """Fit a nested safety head that may only turn predicted USE into ABSTAIN."""
    started = time.perf_counter()
    if batch_size < 1 or training_epochs < 1:
        raise ValueError("ordinary safety batch/epoch configuration is invalid")
    device = _resolve_device(requested_device)
    torch.set_num_threads(4)
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    preflight = normalize_runtime_path(preflight_root).resolve(strict=True)
    anchor_store = normalize_runtime_path(anchor_store_root).resolve(
        strict=True
    )
    anchor_oof = normalize_runtime_path(anchor_oof_root).resolve(strict=True)
    ordinary_root = normalize_runtime_path(ordinary_oof_root).resolve(
        strict=True
    )
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    examples = read_oof_anchor_conditioned_ordinary_examples(
        candidate_store_root=candidate_root,
        preflight_root=preflight,
        anchor_store_root=anchor_store,
        anchor_oof_root=anchor_oof,
        include_anchor_plan_relations=True,
        include_plan_member_relations=True,
        include_plan_arm_relations=True,
    )
    candidate_groups = _read_jsonl(
        candidate_root / "inference_plan_groups.jsonl"
    )
    neighbor_context_by_id = truth_free_junction_neighbor_context(
        [
            {
                "sample_id": example.sample_id,
                "case_key": example.case_key,
                "segment_id": example.segment_id,
                "required_anchor_ids": example.base.required_anchor_ids,
            }
            for example in examples
        ],
        candidate_groups,
    )
    examples_by_fold: dict[int, list[OrdinaryAnchorConditionedExample]] = {}
    for example in examples:
        examples_by_fold.setdefault(example.fold, []).append(example)
    run_summary = _read_json(ordinary_root / "summary.json")
    expected_outer = {
        str(row["sample_id"]): row
        for row in _read_jsonl(ordinary_root / "oof_predictions.jsonl")
    }
    fold_contracts = {
        int(row["outer_fold"]): row for row in run_summary["folds"]
    }
    all_predictions: list[dict[str, Any]] = []
    fold_summaries: list[dict[str, Any]] = []
    safety_parameter_count = 0
    feature_dim = 0

    for outer_fold in sorted(examples_by_fold):
        contract = fold_contracts[outer_fold]
        inner_fold = int(contract["inner_validation_fold"])
        inner_training = [
            example
            for example in examples
            if example.fold not in {outer_fold, inner_fold}
        ]
        inner_validation = examples_by_fold[inner_fold]
        outer_validation = examples_by_fold[outer_fold]
        inner_model, inner_migrated = _load_carrier_model(
            ordinary_root / f"fold_{outer_fold}_inner_checkpoint.pt",
            device=device,
        )
        outer_model, outer_migrated = _load_carrier_model(
            ordinary_root / f"fold_{outer_fold}_checkpoint.pt",
            device=device,
        )
        inner_training_predictions = _predict_conditioned_plans(
            inner_model,
            inner_training,
            batch_size=batch_size,
            device=device,
        )
        inner_validation_predictions = _predict_conditioned_plans(
            inner_model,
            inner_validation,
            batch_size=batch_size,
            device=device,
        )
        outer_predictions = _predict_conditioned_plans(
            outer_model,
            outer_validation,
            batch_size=batch_size,
            device=device,
        )
        _verify_replayed_outer_predictions(
            outer_predictions,
            expected_outer,
            outer_fold=outer_fold,
        )

        fit_rows = _use_safety_rows(
            inner_training,
            inner_training_predictions,
            neighbor_context_by_id,
        )
        calibration_rows = _use_safety_rows(
            inner_validation,
            inner_validation_predictions,
            neighbor_context_by_id,
        )
        outer_use_rows = _use_safety_rows(
            outer_validation,
            outer_predictions,
            neighbor_context_by_id,
        )
        (
            safety_head,
            feature_mean,
            feature_scale,
            fit_history,
        ) = _fit_safety_head(
            fit_rows,
            seed=seed + outer_fold * 100 + 71,
            epoch_count=training_epochs,
            device=device,
        )
        feature_dim = len(fit_rows[0]["features"]) if fit_rows else 0
        safety_parameter_count = (
            sum(parameter.numel() for parameter in safety_head.parameters())
            if safety_head is not None
            else 0
        )
        calibration_scores = _score_safety_rows(
            safety_head,
            calibration_rows,
            feature_mean,
            feature_scale,
            device=device,
        )
        threshold, threshold_reason = zero_unsafe_calibration_threshold(
            calibration_scores
        )
        outer_scores = _score_safety_rows(
            safety_head,
            outer_use_rows,
            feature_mean,
            feature_scale,
            device=device,
        )
        for row in outer_predictions:
            row["outer_fold"] = outer_fold
            row["inner_validation_fold"] = inner_fold
        score_by_id = {
            str(row["sample_id"]): row for row in outer_scores
        }
        augmented = _apply_use_safety_gate(
            outer_predictions,
            score_by_id,
            threshold=threshold,
            threshold_reason=threshold_reason,
        )
        all_predictions.extend(augmented)

        checkpoint_path = root / f"fold_{outer_fold}_safety_head.pt"
        torch.save(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "stage": "ORDINARY_USE_SAFETY_STRICT_NESTED",
                "outer_fold": outer_fold,
                "inner_validation_fold": inner_fold,
                "seed": seed + outer_fold * 100 + 71,
                "feature_dim": feature_dim,
                "hidden_dim": _SAFETY_HIDDEN_DIM,
                "parameter_count": safety_parameter_count,
                "feature_mean": feature_mean,
                "feature_scale": feature_scale,
                "threshold": threshold,
                "threshold_reason": threshold_reason,
                "model_state_dict": (
                    {
                        key: value.detach().cpu()
                        for key, value in safety_head.state_dict().items()
                    }
                    if safety_head is not None
                    else {}
                ),
            },
            checkpoint_path,
        )
        fold_summary = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "legacy_inner_checkpoint_migrated": inner_migrated,
            "legacy_outer_checkpoint_migrated": outer_migrated,
            "fit_use_count": len(fit_rows),
            "fit_unsafe_count": sum(
                not bool(row["safe"]) for row in fit_rows
            ),
            "calibration_use_count": len(calibration_rows),
            "calibration_unsafe_count": sum(
                not bool(row["safe"]) for row in calibration_rows
            ),
            "threshold": threshold,
            "threshold_reason": threshold_reason,
            "metrics": _safety_metrics(augmented),
            "fit_history": fit_history,
            "checkpoint": str(checkpoint_path.resolve()),
            "checkpoint_sha256": sha256_file(checkpoint_path),
        }
        fold_summaries.append(fold_summary)
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_summary)

    all_predictions.sort(key=lambda row: row["sample_id"])
    prediction_path = root / "safety_predictions.jsonl"
    _write_jsonl(prediction_path, all_predictions)
    metrics = _safety_metrics(all_predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_USE_SAFETY_STRICT_NESTED",
        "scope": (
            "The safety head cannot change anchoring or carrier ranking. "
            "It may only convert an automatic USE_RCSD plan into ABSTAIN."
        ),
        "leakage_contract": (
            "Safety features use inference-time object, OOF anchor, selected "
            "plan/member/arm evidence, candidate-set context, and carrier "
            "probability. Truth is used only for fitting, inner calibration, "
            "and outer evaluation."
        ),
        "example_count": len(examples),
        "feature_dim": feature_dim,
        "junction_neighbor_context_dim": _JUNCTION_NEIGHBOR_CONTEXT_DIM,
        "junction_neighbor_group_count": len(candidate_groups),
        "safety_hidden_dim": _SAFETY_HIDDEN_DIM,
        "safety_parameter_count": safety_parameter_count,
        "ordinary_parameter_count": int(
            run_summary["model_contract"]["parameter_count"]
        ),
        "combined_parameter_count": int(
            run_summary["model_contract"]["parameter_count"]
        )
        + safety_parameter_count,
        "folds": fold_summaries,
        "metrics": metrics,
        "unsafe_anchor_bypass_count": sum(
            bool(row["anchor_gate_fallback_required"])
            and row["effective_decision"] != "ABSTAIN"
            for row in all_predictions
        ),
        "terminal_feature_count": 0,
        "raw_id_embedding_count": 0,
        "release_gate": "NO_GO",
        "use_safety_diagnostic_gate": (
            "PASS"
            if metrics["accepted_use_unsafe_count"] == 0
            and metrics["accepted_use_count"] > 0
            else "NO_GO"
        ),
        "ordinary_oof_summary_sha256": sha256_file(
            ordinary_root / "summary.json"
        ),
        "candidate_store_manifest_sha256": sha256_file(
            candidate_root / "manifest.json"
        ),
        "preflight_summary_sha256": sha256_file(
            preflight / "summary.json"
        ),
        "predictions": {
            "path": str(prediction_path.resolve()),
            "sha256": sha256_file(prediction_path),
        },
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def ordinary_use_safety_features(
    example: OrdinaryAnchorConditionedExample,
    *,
    predicted_plan_id: str,
    predicted_probability: float,
    neighbor_context: Sequence[float] = (),
) -> tuple[float, ...]:
    """Build label-free safety evidence for the carrier-selected USE plan."""
    try:
        selected_index = example.base.candidate_ids.index(predicted_plan_id)
    except ValueError as exc:
        raise ValueError("predicted plan is absent from the candidate set") from exc
    if example.base.candidate_decisions[selected_index] != "USE_RCSD":
        raise ValueError("ordinary USE safety features require a USE plan")
    selected = example.conditioned_candidate_features[selected_index]
    keep = _mean_rows(
        [
            features
            for decision, features in zip(
                example.base.candidate_decisions,
                example.conditioned_candidate_features,
                strict=True,
            )
            if decision == "KEEP_SWSD"
        ],
        len(selected),
    )
    use_mean = _mean_rows(
        [
            features
            for decision, features in zip(
                example.base.candidate_decisions,
                example.conditioned_candidate_features,
                strict=True,
            )
            if decision == "USE_RCSD"
        ],
        len(selected),
    )
    members = example.conditioned_member_features[selected_index]
    arms = example.conditioned_arm_features[selected_index]
    scalars = (
        float(predicted_probability),
        math.tanh(len(example.base.candidate_ids) / 16.0),
        math.tanh(
            sum(
                decision == "USE_RCSD"
                for decision in example.base.candidate_decisions
            )
            / 16.0
        ),
        math.tanh(len(example.base.candidate_road_ids[selected_index]) / 12.0),
        math.tanh(len(members) / 12.0),
        math.tanh(len(example.base.required_anchor_ids) / 4.0),
        float(example.all_required_anchors_resolved),
        math.tanh(example.anchor_resolved_count / 4.0),
    )
    result = (
        *scalars,
        *example.base.object_features,
        *example.anchor_condition_features,
        *selected,
        *(left - right for left, right in zip(selected, keep, strict=True)),
        *(
            left - right
            for left, right in zip(selected, use_mean, strict=True)
        ),
        *_aggregate_rows(members, mode="mean"),
        *_aggregate_rows(members, mode="max"),
        *_aggregate_rows(members, mode="min"),
        *_aggregate_rows(arms, mode="mean"),
        *_aggregate_rows(arms, mode="max"),
        *neighbor_context,
    )
    if not result or not all(math.isfinite(value) for value in result):
        raise ValueError("ordinary safety features are empty or non-finite")
    return tuple(float(value) for value in result)


def truth_free_junction_neighbor_context(
    targets: Sequence[Mapping[str, Any]],
    candidate_groups: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[float, ...]]:
    """Aggregate all inference candidates sharing each frozen semantic anchor."""
    by_anchor: dict[
        tuple[str, str],
        list[tuple[str, tuple[float, ...]]],
    ] = {}
    for group in candidate_groups:
        if str(group.get("segment_type")) != "STANDARD":
            continue
        vector = _truth_free_group_neighbor_evidence(group)
        segment_id = str(group["segment_id"])
        case_key = str(group["case_key"])
        for anchor_id in group.get("required_anchor_ids") or ():
            by_anchor.setdefault(
                (case_key, str(anchor_id)),
                [],
            ).append((segment_id, vector))
    result: dict[str, tuple[float, ...]] = {}
    zero_anchor = (0.0,) * (_NEIGHBOR_EVIDENCE_DIM + 1)
    for target in targets:
        case_key = str(target["case_key"])
        segment_id = str(target["segment_id"])
        per_anchor = []
        for anchor_id in target.get("required_anchor_ids") or ():
            neighbors = [
                vector
                for neighbor_id, vector in by_anchor.get(
                    (case_key, str(anchor_id)),
                    (),
                )
                if neighbor_id != segment_id
            ]
            per_anchor.append(
                (
                    math.tanh(len(neighbors) / 8.0),
                    *_mean_rows(neighbors, _NEIGHBOR_EVIDENCE_DIM),
                )
            )
        context = (
            (
                *_mean_rows(
                    per_anchor,
                    _NEIGHBOR_EVIDENCE_DIM + 1,
                ),
                *_aggregate_rows(per_anchor, mode="max"),
            )
            if per_anchor
            else (*zero_anchor, *zero_anchor)
        )
        if len(context) != _JUNCTION_NEIGHBOR_CONTEXT_DIM:
            raise RuntimeError("Junction neighbor context dimension differs")
        result[str(target["sample_id"])] = tuple(
            float(value) for value in context
        )
    return result


def zero_unsafe_calibration_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[float, str]:
    unsafe_scores = [
        float(row["safety_score"])
        for row in rows
        if not bool(row["safe"])
    ]
    if not unsafe_scores:
        return 1.0, "NO_UNSAFE_IN_INNER_CALIBRATION"
    maximum = max(unsafe_scores)
    if maximum >= 1.0:
        return 1.0, "UNSAFE_SCORE_AT_ONE"
    return math.nextafter(maximum, 1.0), "ABOVE_MAX_INNER_UNSAFE"


def _load_carrier_model(
    checkpoint_path: Path,
    *,
    device: torch.device,
) -> tuple[TargetAJointNetwork, bool]:
    checkpoint = torch.load(
        checkpoint_path,
        map_location=device,
        weights_only=False,
    )
    model = TargetAJointNetwork(TargetAConfig(**checkpoint["config"])).to(device)
    state = checkpoint["model_state_dict"]
    migrated = state[_ARM_PROJECTION_KEY].shape != model.state_dict()[
        _ARM_PROJECTION_KEY
    ].shape
    model.load_state_dict(
        migrate_legacy_ordinary_arm_projection(state, model.state_dict()),
        strict=True,
    )
    model.eval()
    return model, migrated


def _use_safety_rows(
    examples: Sequence[OrdinaryAnchorConditionedExample],
    predictions: Sequence[Mapping[str, Any]],
    neighbor_context_by_id: Mapping[str, Sequence[float]],
) -> list[dict[str, Any]]:
    by_id = {example.sample_id: example for example in examples}
    result = []
    for prediction in predictions:
        if (
            not bool(prediction["automatic_decision"])
            or prediction["effective_decision"] != "USE_RCSD"
        ):
            continue
        example = by_id[str(prediction["sample_id"])]
        result.append(
            {
                "sample_id": prediction["sample_id"],
                "case_key": prediction["case_key"],
                "preferred_decision": prediction["preferred_decision"],
                "safe": prediction["acceptable_exact"] is True,
                "features": ordinary_use_safety_features(
                    example,
                    predicted_plan_id=str(
                        prediction["raw_predicted_plan_id"]
                    ),
                    predicted_probability=float(
                        prediction["raw_predicted_probability"]
                    ),
                    neighbor_context=neighbor_context_by_id[
                        str(prediction["sample_id"])
                    ],
                ),
            }
        )
    return result


def _truth_free_group_neighbor_evidence(
    group: Mapping[str, Any],
) -> tuple[float, ...]:
    object_features = tuple(
        float(value)
        for value in group["object_features"][
            :_NEIGHBOR_OBJECT_FEATURE_COUNT
        ]
    )
    use_features = [
        tuple(
            float(value)
            for value in candidate["features"][
                :_NEIGHBOR_PLAN_FEATURE_COUNT
            ]
        )
        for candidate in group["candidates"]
        if (
            str(candidate.get("decision")) == "USE_RCSD"
            and bool(candidate.get("hard_valid", True))
        )
    ]
    vector = (
        *object_features,
        *_mean_rows(use_features, _NEIGHBOR_PLAN_FEATURE_COUNT),
        *(
            _aggregate_rows(use_features, mode="max")
            if use_features
            else (0.0,) * _NEIGHBOR_PLAN_FEATURE_COUNT
        ),
        math.tanh(len(group["candidates"]) / 16.0),
        math.tanh(len(use_features) / 16.0),
        float(bool(use_features)),
    )
    if len(vector) != _NEIGHBOR_EVIDENCE_DIM:
        raise RuntimeError("truth-free neighbor evidence dimension differs")
    return tuple(float(value) for value in vector)


def _fit_safety_head(
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    epoch_count: int,
    device: torch.device,
) -> tuple[
    _OrdinaryUseSafetyHead | None,
    torch.Tensor,
    torch.Tensor,
    list[dict[str, float]],
]:
    if not rows:
        return None, torch.zeros(0), torch.ones(0), []
    features = torch.tensor(
        [row["features"] for row in rows],
        dtype=torch.float32,
        device=device,
    )
    labels = torch.tensor(
        [float(bool(row["safe"])) for row in rows],
        dtype=torch.float32,
        device=device,
    )
    mean = features.mean(dim=0)
    scale = features.std(dim=0, unbiased=False).clamp_min(1e-4)
    if labels.min() == labels.max():
        return None, mean.detach().cpu(), scale.detach().cpu(), []
    torch.manual_seed(seed)
    head = _OrdinaryUseSafetyHead(features.shape[1]).to(device)
    optimizer = torch.optim.AdamW(
        head.parameters(),
        lr=0.01,
        weight_decay=1e-3,
    )
    safe_count = labels.sum().clamp_min(1.0)
    unsafe_count = (1.0 - labels).sum().clamp_min(1.0)
    weights = torch.where(
        labels.bool(),
        0.5 / safe_count,
        0.5 / unsafe_count,
    )
    normalized = (features - mean) / scale
    history: list[dict[str, float]] = []
    for epoch in range(epoch_count):
        optimizer.zero_grad(set_to_none=True)
        logits = head(normalized)
        raw = nn.functional.binary_cross_entropy_with_logits(
            logits,
            labels,
            reduction="none",
        )
        loss = (raw * weights).sum()
        loss.backward()
        optimizer.step()
        if epoch in {0, epoch_count - 1}:
            history.append(
                {
                    "epoch": float(epoch + 1),
                    "loss": float(loss.detach().cpu()),
                }
            )
    return (
        head,
        mean.detach().cpu(),
        scale.detach().cpu(),
        history,
    )


def _score_safety_rows(
    head: _OrdinaryUseSafetyHead | None,
    rows: Sequence[Mapping[str, Any]],
    mean: torch.Tensor,
    scale: torch.Tensor,
    *,
    device: torch.device,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    if head is None:
        scores = [0.0] * len(rows)
    else:
        features = torch.tensor(
            [row["features"] for row in rows],
            dtype=torch.float32,
            device=device,
        )
        with torch.no_grad():
            scores = torch.sigmoid(
                head(
                    (features - mean.to(device))
                    / scale.to(device)
                )
            ).cpu().tolist()
    return [
        {
            "sample_id": row["sample_id"],
            "case_key": row["case_key"],
            "preferred_decision": row["preferred_decision"],
            "safe": bool(row["safe"]),
            "safety_score": float(score),
        }
        for row, score in zip(rows, scores, strict=True)
    ]


def _apply_use_safety_gate(
    predictions: Sequence[Mapping[str, Any]],
    scores: Mapping[str, Mapping[str, Any]],
    *,
    threshold: float,
    threshold_reason: str,
) -> list[dict[str, Any]]:
    result = []
    for prediction in predictions:
        row = dict(prediction)
        is_use = (
            bool(row["automatic_decision"])
            and row["effective_decision"] == "USE_RCSD"
        )
        score_row = scores.get(str(row["sample_id"]))
        accepted_use = bool(
            is_use
            and score_row is not None
            and float(score_row["safety_score"]) > threshold
        )
        row.update(
            {
                "use_safety_applied": is_use,
                "use_safety_score": (
                    float(score_row["safety_score"])
                    if score_row is not None
                    else None
                ),
                "use_safety_threshold": threshold,
                "use_safety_threshold_reason": threshold_reason,
                "use_safety_accepted": accepted_use,
                "use_safety_unsafe_auto": bool(
                    accepted_use and row["acceptable_exact"] is not True
                ),
                "post_safety_effective_decision": (
                    "ABSTAIN" if is_use and not accepted_use
                    else row["effective_decision"]
                ),
                "post_safety_automatic_decision": bool(
                    row["automatic_decision"]
                    and (not is_use or accepted_use)
                ),
            }
        )
        result.append(row)
    return result


def _safety_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    raw_use = [
        row
        for row in rows
        if bool(row["automatic_decision"])
        and row["effective_decision"] == "USE_RCSD"
    ]
    accepted_use = [
        row for row in raw_use if bool(row["use_safety_accepted"])
    ]
    post_automatic = [
        row for row in rows if bool(row["post_safety_automatic_decision"])
    ]
    return {
        "count": len(rows),
        "raw_use_count": len(raw_use),
        "raw_use_unsafe_count": sum(
            row["acceptable_exact"] is not True for row in raw_use
        ),
        "raw_keep_to_use_count": sum(
            row["preferred_decision"] == "KEEP_SWSD" for row in raw_use
        ),
        "accepted_use_count": len(accepted_use),
        "accepted_use_safe_count": sum(
            row["acceptable_exact"] is True for row in accepted_use
        ),
        "accepted_use_unsafe_count": sum(
            row["acceptable_exact"] is not True for row in accepted_use
        ),
        "accepted_keep_to_use_count": sum(
            row["preferred_decision"] == "KEEP_SWSD"
            for row in accepted_use
        ),
        "accepted_use_coverage": (
            len(accepted_use) / len(raw_use) if raw_use else 0.0
        ),
        "post_safety_automatic_decision_count": len(post_automatic),
        "post_safety_automatic_coverage": (
            len(post_automatic) / len(rows) if rows else 0.0
        ),
        "post_safety_automatic_plan_exact": (
            sum(row["acceptable_exact"] is True for row in post_automatic)
            / len(post_automatic)
            if post_automatic
            else 0.0
        ),
    }


def _verify_replayed_outer_predictions(
    predictions: Sequence[Mapping[str, Any]],
    expected: Mapping[str, Mapping[str, Any]],
    *,
    outer_fold: int,
) -> None:
    for row in predictions:
        reference = expected.get(str(row["sample_id"]))
        if reference is None or int(reference["outer_fold"]) != outer_fold:
            raise ValueError("replayed outer prediction lacks its OOF reference")
        if (
            row["raw_predicted_plan_id"]
            != reference["raw_predicted_plan_id"]
            or abs(
                float(row["raw_predicted_probability"])
                - float(reference["raw_predicted_probability"])
            )
            > 1e-7
        ):
            raise ValueError("legacy v45 carrier replay differs")


def _aggregate_rows(
    rows: Sequence[Sequence[float]],
    *,
    mode: str,
) -> tuple[float, ...]:
    if not rows:
        return ()
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("safety relation rows have inconsistent dimensions")
    columns = list(zip(*rows, strict=True))
    if mode == "mean":
        return tuple(sum(column) / len(column) for column in columns)
    if mode == "max":
        return tuple(max(column) for column in columns)
    if mode == "min":
        return tuple(min(column) for column in columns)
    raise ValueError(f"unsupported safety aggregation: {mode}")


def _mean_rows(
    rows: Sequence[Sequence[float]],
    width: int,
) -> tuple[float, ...]:
    if not rows:
        return (0.0,) * width
    result = _aggregate_rows(rows, mode="mean")
    if len(result) != width:
        raise ValueError("safety candidate feature dimension differs")
    return result


def _resolve_device(requested: str) -> torch.device:
    normalized = requested.casefold()
    if normalized == "cpu":
        return torch.device("cpu")
    if normalized == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    raise ValueError(f"unsupported or unavailable safety device: {requested}")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


__all__ = [
    "migrate_legacy_ordinary_arm_projection",
    "ordinary_use_safety_features",
    "run_ordinary_use_safety_strict_nested",
    "truth_free_junction_neighbor_context",
    "zero_unsafe_calibration_threshold",
]
