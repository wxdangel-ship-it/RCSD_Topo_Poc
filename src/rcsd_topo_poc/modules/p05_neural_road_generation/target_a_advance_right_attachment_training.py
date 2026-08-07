from __future__ import annotations

import copy
import json
import random
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_network import (
    TargetAOrdinaryAccessDecoder,
    parameter_count,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


CONDITION_FEATURE_DIM = 16


@dataclass(frozen=True)
class AdvanceRightAttachmentTrainingConfig:
    hidden_dim: int = 128
    context_dim: int = 192
    dropout: float = 0.1
    batch_size: int = 48
    max_epochs: int = 80
    patience: int = 12
    learning_rate: float = 4e-4
    weight_decay: float = 2e-4
    teacher_training_loss_weight: float = 0.5
    oof_training_loss_weight: float = 1.0
    torch_num_threads: int = 4

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.context_dim,
            self.batch_size,
            self.max_epochs,
            self.patience,
            self.torch_num_threads,
        ) < 1:
            raise ValueError("attachment training dimensions are invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("attachment dropout is invalid")
        if self.learning_rate <= 0.0 or self.weight_decay < 0.0:
            raise ValueError("attachment optimizer config is invalid")
        if min(
            self.teacher_training_loss_weight,
            self.oof_training_loss_weight,
        ) < 0.0:
            raise ValueError("attachment view weights are invalid")
        if (
            self.teacher_training_loss_weight
            + self.oof_training_loss_weight
            <= 0.0
        ):
            raise ValueError("attachment training views cannot both be disabled")


@dataclass(frozen=True)
class AdvanceRightAttachmentExample:
    case_key: str
    object_id: str
    side: str
    fold: int
    proposal_ids: tuple[str, ...]
    road_ids: tuple[str, ...]
    operations: tuple[str, ...]
    fractions: tuple[float, ...]
    teacher_features: tuple[tuple[float, ...], ...]
    oof_features: tuple[tuple[float, ...], ...]
    target_index: int
    sample_weight: float
    oof_release_ready: bool


def run_advance_right_attachment_strict_nested_oof(
    *,
    access_conditioning_store_root: Path,
    attachment_supervision_root: Path,
    output_root: Path,
    seed: int,
    config: AdvanceRightAttachmentTrainingConfig = (
        AdvanceRightAttachmentTrainingConfig()
    ),
    requested_device: str = "cuda",
) -> Path:
    """Train one-of-N T06 side attachment selection with strict Case OOF."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    store = normalize_runtime_path(
        access_conditioning_store_root
    ).resolve(strict=True)
    supervision = normalize_runtime_path(
        attachment_supervision_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples, read_summary = read_attachment_examples(store, supervision)
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("attachment strict OOF needs at least three folds")
    feature_dim = len(examples[0].teacher_features[0])
    device = _resolve_device(requested_device)
    predictions = []
    fold_summaries = []
    model_parameters = 0
    for outer_fold in folds:
        inner_fold = folds[(folds.index(outer_fold) + 1) % len(folds)]
        inner_training = [
            row
            for row in examples
            if row.fold not in {outer_fold, inner_fold}
        ]
        inner_validation = [
            row for row in examples if row.fold == inner_fold
        ]
        outer_training = [
            row for row in examples if row.fold != outer_fold
        ]
        outer_validation = [
            row for row in examples if row.fold == outer_fold
        ]
        _assert_case_disjoint(inner_training, inner_validation)
        _assert_case_disjoint(outer_training, outer_validation)
        tuning = _fit_model(
            inner_training,
            inner_validation,
            feature_dim=feature_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 17,
        )
        final = _fit_fixed_epochs(
            outer_training,
            feature_dim=feature_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 53,
            epoch_count=tuning["best_epoch"],
        )
        model_parameters = parameter_count(final["model"])
        inner_scores = score_attachment_examples(
            tuning["model"],
            inner_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        acceptance_threshold = choose_zero_error_threshold(inner_scores)
        teacher_scores = score_attachment_examples(
            final["model"],
            outer_validation,
            feature_source="teacher",
            batch_size=config.batch_size,
            device=device,
        )
        oof_scores = score_attachment_examples(
            final["model"],
            outer_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        teacher_by_key = {_score_key(row): row for row in teacher_scores}
        decoded = []
        for score in oof_scores:
            teacher = teacher_by_key[_score_key(score)]
            row = dict(score)
            row["teacher_selected_proposal_id"] = str(
                teacher["selected_proposal_id"]
            )
            row["teacher_exact"] = bool(teacher["raw_exact"])
            row["acceptance_threshold"] = acceptance_threshold
            row["automatic"] = bool(
                row["release_eligible"]
                and float(row["selection_confidence"])
                >= acceptance_threshold
            )
            row["unsafe_automatic"] = bool(
                row["automatic"] and not row["raw_exact"]
            )
            row["effective_decision"] = (
                "SELECT_ATTACHMENT" if row["automatic"] else "ABSTAIN"
            )
            row["outer_fold"] = outer_fold
            row["inner_validation_fold"] = inner_fold
            decoded.append(row)
        predictions.extend(decoded)
        inner_checkpoint = root / f"fold_{outer_fold}_inner_checkpoint.pt"
        outer_checkpoint = root / f"fold_{outer_fold}_checkpoint.pt"
        _save_checkpoint(
            inner_checkpoint,
            tuning["model"],
            config=config,
            feature_dim=feature_dim,
            fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
        )
        _save_checkpoint(
            outer_checkpoint,
            final["model"],
            config=config,
            feature_dim=feature_dim,
            fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
        )
        fold_summary = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "best_epoch": tuning["best_epoch"],
            "best_validation_loss": tuning["best_validation_loss"],
            "inner_train_count": len(inner_training),
            "inner_validation_count": len(inner_validation),
            "outer_train_count": len(outer_training),
            "outer_validation_count": len(outer_validation),
            "acceptance_threshold": acceptance_threshold,
            "metrics": attachment_metrics(decoded),
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "inner_checkpoint": _input_record(inner_checkpoint),
            "outer_checkpoint": _input_record(outer_checkpoint),
        }
        fold_summaries.append(fold_summary)
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_summary)

    predictions.sort(key=_score_key)
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    metrics = attachment_metrics(predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_SIDE_ATTACHMENT_STRICT_NESTED_OOF",
        "model_scope": (
            "For one AdvanceRight source or target side, select exactly one "
            "pre-break parent Road and split/reused-endpoint proposal."
        ),
        "business_constraint": (
            "The scorer cannot change adjacent ordinary carrier state, anchor, "
            "candidate set or frozen skeleton. Final release requires both "
            "sides, the complete AdvanceRight Road plan and graph legality."
        ),
        "training_condition": (
            "Teacher and strict OOF adjacent ordinary carrier condition views "
            "share the same candidate encoder. T06 terminal values are labels "
            "only and are absent from inference features."
        ),
        "feature_dim": feature_dim,
        "parameter_count": model_parameters,
        "config": asdict(config),
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "example_count": len(examples),
        "fold_count": len(folds),
        "read_summary": read_summary,
        "metrics": metrics,
        "folds": fold_summaries,
        "access_conditioning_summary": _input_record(store / "summary.json"),
        "attachment_supervision_summary": _input_record(
            supervision / "summary.json"
        ),
        "oof_predictions": _input_record(prediction_path),
        "wall_seconds": time.perf_counter() - started,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "strict_case_oof": True,
        "decision": (
            "GO"
            if metrics["unsafe_automatic_count"] == 0
            and metrics["automatic_count"] > 0
            else "NO_GO"
        ),
    }
    _write_json(root / "summary.json", summary)
    return root


def read_attachment_examples(
    access_conditioning_store_root: Path,
    attachment_supervision_root: Path,
) -> tuple[list[AdvanceRightAttachmentExample], dict[str, int]]:
    feature_rows = {
        _object_key(row): row
        for row in _read_jsonl(
            access_conditioning_store_root
            / "advance_right_access_set_features.jsonl"
        )
    }
    teacher_conditions = {
        _object_key(row): row
        for row in _read_jsonl(
            access_conditioning_store_root
            / "advance_right_teacher_conditions.jsonl"
        )
    }
    oof_conditions = {
        _object_key(row): row
        for row in _read_jsonl(
            access_conditioning_store_root
            / "advance_right_oof_conditions.jsonl"
        )
    }
    counts: Counter[str] = Counter()
    examples = []
    for label in _read_jsonl(
        attachment_supervision_root
        / "advance_right_attachment_supervision.jsonl"
    ):
        counts["supervision_action"] += 1
        if not bool(label["attachment_task_mask"]):
            counts["masked_by_supervision"] += 1
            continue
        key = _object_key(label)
        side = str(label["side"]).lower()
        feature = feature_rows[key]
        side_feature = feature[f"{side}_side"]
        candidates = list(side_feature.get("access_candidates") or ())
        fraction = label.get("pre_break_parent_position_fraction_audit")
        matches = [
            index
            for index, candidate in enumerate(candidates)
            if str(candidate.get("road_id") or "")
            == str(label["pre_break_parent_road_id"])
            and str(candidate.get("operation") or "")
            == str(label["attachment_operation"])
            and fraction is not None
            and abs(
                float(candidate.get("projected_fraction") or 0.0)
                - float(fraction)
            )
            <= 1e-6
        ]
        if len(matches) != 1:
            counts[f"candidate_match_count_{len(matches)}"] += 1
            continue
        teacher_condition = teacher_conditions[key][f"{side}_condition"]
        oof_condition = oof_conditions[key][f"{side}_condition"]
        base_features = [
            (
                *[float(value) for value in side_feature["object_feature_values"]],
                *[float(value) for value in row["feature_values"]],
            )
            for row in candidates
        ]
        teacher_condition_values = condition_feature_values(teacher_condition)
        oof_condition_values = condition_feature_values(oof_condition)
        example = AdvanceRightAttachmentExample(
            case_key=key[0],
            object_id=key[1],
            side=side.upper(),
            fold=int(feature["fold"]),
            proposal_ids=tuple(str(row["proposal_id"]) for row in candidates),
            road_ids=tuple(str(row["road_id"]) for row in candidates),
            operations=tuple(str(row["operation"]) for row in candidates),
            fractions=tuple(
                float(row["projected_fraction"]) for row in candidates
            ),
            teacher_features=tuple(
                tuple((*values, *teacher_condition_values))
                for values in base_features
            ),
            oof_features=tuple(
                tuple((*values, *oof_condition_values))
                for values in base_features
            ),
            target_index=matches[0],
            sample_weight=float(label["attachment_label_weight"]),
            oof_release_ready=bool(oof_condition["complete_release_ready"]),
        )
        examples.append(example)
        counts["usable_example"] += 1
        counts[f"fold_{example.fold}"] += 1
        counts["oof_release_ready"] += int(example.oof_release_ready)
    if not examples:
        raise ValueError("attachment training has no reachable examples")
    feature_dim = len(examples[0].teacher_features[0])
    if any(
        len(values) != feature_dim
        for row in examples
        for values in (*row.teacher_features, *row.oof_features)
    ):
        raise ValueError("attachment feature dimension differs")
    counts["feature_dim"] = feature_dim
    return examples, dict(sorted(counts.items()))


def condition_feature_values(condition: Mapping[str, Any]) -> tuple[float, ...]:
    source = str(condition.get("access_source") or "UNRESOLVED")
    decision = str(condition.get("selected_decision") or "")
    values = (
        float(source == "SWSD"),
        float(source == "RCSD"),
        float(source not in {"SWSD", "RCSD"}),
        float(decision == "KEEP_SWSD"),
        float(decision == "USE_RCSD"),
        float(decision not in {"KEEP_SWSD", "USE_RCSD"}),
        min(len(condition.get("selected_road_ids") or ()) / 16.0, 1.0),
        min(len(condition.get("access_road_ids") or ()) / 4.0, 1.0),
        float(condition.get("carrier_probability") or 0.0),
        float(bool(condition.get("access_source_resolved"))),
        float(bool(condition.get("access_road_resolved"))),
        float(bool(condition.get("ordinary_release_ready"))),
        float(bool(condition.get("access_release_ready"))),
        float(bool(condition.get("complete_release_ready"))),
        float(str(condition.get("resolution") or "").endswith("LOCKED")),
        1.0,
    )
    if len(values) != CONDITION_FEATURE_DIM:
        raise AssertionError("attachment condition dimension differs")
    return values


def score_attachment_examples(
    model: TargetAOrdinaryAccessDecoder,
    examples: Sequence[AdvanceRightAttachmentExample],
    *,
    feature_source: str,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    if feature_source not in {"teacher", "oof"}:
        raise ValueError("attachment feature source is invalid")
    model.eval()
    result = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            values, mask, _ = _batch_tensors(
                rows,
                feature_source=feature_source,
                device=device,
            )
            logits = model(values, mask)
            for index, row in enumerate(rows):
                length = len(row.proposal_ids)
                probabilities = torch.softmax(logits[index, :length], dim=0)
                selected = int(torch.argmax(probabilities).item())
                confidence = float(probabilities[selected].item())
                result.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": row.case_key,
                        "object_id": row.object_id,
                        "side": row.side,
                        "fold": row.fold,
                        "feature_source": feature_source,
                        "candidate_count": length,
                        "target_index": row.target_index,
                        "selected_index": selected,
                        "target_proposal_id": row.proposal_ids[row.target_index],
                        "selected_proposal_id": row.proposal_ids[selected],
                        "selected_road_id": row.road_ids[selected],
                        "selected_operation": row.operations[selected],
                        "selected_fraction": row.fractions[selected],
                        "selection_confidence": confidence,
                        "raw_exact": selected == row.target_index,
                        "release_eligible": row.oof_release_ready,
                    }
                )
    return result


def choose_zero_error_threshold(rows: Sequence[Mapping[str, Any]]) -> float:
    eligible = [row for row in rows if bool(row["release_eligible"])]
    unsafe = [
        float(row["selection_confidence"])
        for row in eligible
        if not bool(row["raw_exact"])
    ]
    if not eligible or not unsafe:
        return 1.000001
    return min(1.000001, max(unsafe) + 1e-7)


def attachment_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    raw_exact = sum(bool(row["raw_exact"]) for row in rows)
    teacher_exact = sum(bool(row.get("teacher_exact")) for row in rows)
    automatic = [row for row in rows if bool(row.get("automatic"))]
    unsafe = [row for row in automatic if not bool(row["raw_exact"])]
    per_case: dict[str, list[Mapping[str, Any]]] = {}
    per_side: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        per_case.setdefault(str(row["case_key"]), []).append(row)
        per_side.setdefault(str(row["side"]), []).append(row)
    return {
        "count": count,
        "oof_raw_exact": raw_exact / max(count, 1),
        "teacher_raw_exact": teacher_exact / max(count, 1),
        "release_eligible_count": sum(
            bool(row["release_eligible"]) for row in rows
        ),
        "automatic_count": len(automatic),
        "automatic_coverage": len(automatic) / max(count, 1),
        "unsafe_automatic_count": len(unsafe),
        "worst_case_exact": min(
            (
                sum(bool(row["raw_exact"]) for row in values) / len(values)
                for values in per_case.values()
            ),
            default=0.0,
        ),
        "per_side_exact": {
            side: sum(bool(row["raw_exact"]) for row in values) / len(values)
            for side, values in sorted(per_side.items())
        },
    }


def _fit_model(
    training: Sequence[AdvanceRightAttachmentExample],
    validation: Sequence[AdvanceRightAttachmentExample],
    *,
    feature_dim: int,
    config: AdvanceRightAttachmentTrainingConfig,
    device: torch.device,
    seed: int,
) -> dict[str, Any]:
    model = _new_model(feature_dim, config, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    best_loss = float("inf")
    best_epoch = 1
    best_state = copy.deepcopy(model.state_dict())
    stale = 0
    history = []
    for epoch in range(1, config.max_epochs + 1):
        train_loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            config=config,
            device=device,
            seed=seed + epoch,
        )
        validation_loss = _evaluate_loss(
            model,
            validation,
            device=device,
            batch_size=config.batch_size,
        )
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-6:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
        if stale >= config.patience:
            break
    model.load_state_dict(best_state)
    return {
        "model": model,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "history": history,
    }


def _fit_fixed_epochs(
    training: Sequence[AdvanceRightAttachmentExample],
    *,
    feature_dim: int,
    config: AdvanceRightAttachmentTrainingConfig,
    device: torch.device,
    seed: int,
    epoch_count: int,
) -> dict[str, Any]:
    model = _new_model(feature_dim, config, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    history = []
    for epoch in range(1, epoch_count + 1):
        loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            config=config,
            device=device,
            seed=seed + epoch,
        )
        history.append({"epoch": float(epoch), "train_loss": loss})
    return {"model": model, "history": history}


def _new_model(
    feature_dim: int,
    config: AdvanceRightAttachmentTrainingConfig,
    device: torch.device,
) -> TargetAOrdinaryAccessDecoder:
    return TargetAOrdinaryAccessDecoder(
        feature_dim=feature_dim,
        hidden_dim=config.hidden_dim,
        context_dim=config.context_dim,
        dropout=config.dropout,
    ).to(device)


def _train_epoch(
    model: TargetAOrdinaryAccessDecoder,
    examples: Sequence[AdvanceRightAttachmentExample],
    *,
    optimizer: torch.optim.Optimizer,
    config: AdvanceRightAttachmentTrainingConfig,
    device: torch.device,
    seed: int,
) -> float:
    model.train()
    order = list(range(len(examples)))
    random.Random(seed).shuffle(order)
    total = 0.0
    weight_total = 0.0
    for start in range(0, len(order), config.batch_size):
        rows = [
            examples[index]
            for index in order[start : start + config.batch_size]
        ]
        teacher_values, mask, weights = _batch_tensors(
            rows,
            feature_source="teacher",
            device=device,
        )
        oof_values, oof_mask, _ = _batch_tensors(
            rows,
            feature_source="oof",
            device=device,
        )
        if not torch.equal(mask, oof_mask):
            raise ValueError("attachment teacher and OOF masks differ")
        targets = torch.tensor(
            [row.target_index for row in rows],
            dtype=torch.long,
            device=device,
        )
        optimizer.zero_grad(set_to_none=True)
        teacher_loss = F.cross_entropy(
            model(teacher_values, mask).masked_fill(~mask, -1e9),
            targets,
            reduction="none",
        )
        oof_loss = F.cross_entropy(
            model(oof_values, mask).masked_fill(~mask, -1e9),
            targets,
            reduction="none",
        )
        view_weight = (
            config.teacher_training_loss_weight
            + config.oof_training_loss_weight
        )
        raw = (
            config.teacher_training_loss_weight * teacher_loss
            + config.oof_training_loss_weight * oof_loss
        ) / view_weight
        loss = (raw * weights).sum() / weights.sum().clamp_min(1e-6)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        optimizer.step()
        total += float((raw.detach() * weights).sum().item())
        weight_total += float(weights.sum().item())
    return total / max(weight_total, 1e-9)


def _evaluate_loss(
    model: TargetAOrdinaryAccessDecoder,
    examples: Sequence[AdvanceRightAttachmentExample],
    *,
    device: torch.device,
    batch_size: int,
) -> float:
    model.eval()
    total = 0.0
    weight_total = 0.0
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            values, mask, weights = _batch_tensors(
                rows,
                feature_source="oof",
                device=device,
            )
            targets = torch.tensor(
                [row.target_index for row in rows],
                dtype=torch.long,
                device=device,
            )
            raw = F.cross_entropy(
                model(values, mask).masked_fill(~mask, -1e9),
                targets,
                reduction="none",
            )
            total += float((raw * weights).sum().item())
            weight_total += float(weights.sum().item())
    return total / max(weight_total, 1e-9)


def _batch_tensors(
    examples: Sequence[AdvanceRightAttachmentExample],
    *,
    feature_source: str,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    source = [
        row.teacher_features
        if feature_source == "teacher"
        else row.oof_features
        for row in examples
    ]
    candidate_count = max(len(values) for values in source)
    feature_dim = len(source[0][0])
    values = torch.zeros(
        len(examples),
        candidate_count,
        feature_dim,
        dtype=torch.float32,
        device=device,
    )
    mask = torch.zeros(
        len(examples),
        candidate_count,
        dtype=torch.bool,
        device=device,
    )
    weights = torch.tensor(
        [row.sample_weight for row in examples],
        dtype=torch.float32,
        device=device,
    )
    for index, features in enumerate(source):
        length = len(features)
        values[index, :length] = torch.tensor(
            features,
            dtype=torch.float32,
            device=device,
        )
        mask[index, :length] = True
    return values, mask, weights


def _assert_case_disjoint(
    training: Sequence[AdvanceRightAttachmentExample],
    validation: Sequence[AdvanceRightAttachmentExample],
) -> None:
    overlap = {row.case_key for row in training} & {
        row.case_key for row in validation
    }
    if overlap:
        raise ValueError(f"attachment Case split overlaps: {sorted(overlap)}")


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if requested == "cuda":
        raise RuntimeError("CUDA was requested but is unavailable")
    return torch.device(requested)


def _object_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["case_key"]), str(row["object_id"])


def _score_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(row["case_key"]), str(row["object_id"]), str(row["side"])


def _save_checkpoint(
    path: Path,
    model: TargetAOrdinaryAccessDecoder,
    *,
    config: AdvanceRightAttachmentTrainingConfig,
    feature_dim: int,
    fold: int,
    inner_fold: int,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ADVANCE_RIGHT_SIDE_ATTACHMENT_DECODER",
            "config": asdict(config),
            "feature_dim": feature_dim,
            "fold": fold,
            "inner_fold": inner_fold,
            "epoch_count": epoch_count,
            "state_dict": {
                key: value.detach().cpu()
                for key, value in model.state_dict().items()
            },
        },
        path,
    )


def _input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "AdvanceRightAttachmentTrainingConfig",
    "attachment_metrics",
    "condition_feature_values",
    "read_attachment_examples",
    "run_advance_right_attachment_strict_nested_oof",
]
