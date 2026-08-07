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

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_network import (
    TargetAOrdinaryAccessDecoder,
    parameter_count,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


@dataclass(frozen=True)
class OrdinaryAccessTrainingConfig:
    hidden_dim: int = 128
    context_dim: int = 192
    dropout: float = 0.1
    batch_size: int = 64
    max_epochs: int = 80
    patience: int = 12
    learning_rate: float = 5e-4
    weight_decay: float = 2e-4
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
            raise ValueError("ordinary access training dimensions are invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("ordinary access dropout is invalid")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("ordinary access optimizer config is invalid")


@dataclass(frozen=True)
class OrdinaryAccessExample:
    case_key: str
    segment_id: str
    junc_node_id: str
    fold: int
    proposal_ids: tuple[str, ...]
    road_ids: tuple[str, ...]
    operations: tuple[str, ...]
    fractions: tuple[float, ...]
    teacher_features: tuple[tuple[float, ...], ...]
    oof_features: tuple[tuple[float, ...], ...]
    acceptable_indices: tuple[int, ...]
    sample_weight: float
    oof_anchor_release_ready: bool
    upstream_plan_release_blocked: bool


def run_ordinary_access_strict_nested_oof(
    *,
    conditioned_store_root: Path,
    output_root: Path,
    seed: int,
    config: OrdinaryAccessTrainingConfig = OrdinaryAccessTrainingConfig(),
    requested_device: str = "cuda",
) -> Path:
    """Train access selection with teacher anchors and score with OOF anchors."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    store = normalize_runtime_path(conditioned_store_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples, read_summary = read_ordinary_access_examples(store)
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("ordinary access strict OOF needs three folds")
    feature_dim = len(examples[0].teacher_features[0])
    device = _resolve_device(requested_device)
    predictions: list[dict[str, Any]] = []
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
        inner_oof_scores = score_ordinary_access_examples(
            tuning["model"],
            inner_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        acceptance_threshold = choose_zero_error_threshold(inner_oof_scores)
        teacher_scores = score_ordinary_access_examples(
            final["model"],
            outer_validation,
            feature_source="teacher",
            batch_size=config.batch_size,
            device=device,
        )
        oof_scores = score_ordinary_access_examples(
            final["model"],
            outer_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        teacher_by_key = {
            _score_key(row): row for row in teacher_scores
        }
        decoded = []
        for score in oof_scores:
            key = _score_key(score)
            teacher = teacher_by_key[key]
            row = dict(score)
            row["teacher_predicted_index"] = int(
                teacher["predicted_index"]
            )
            row["teacher_exact"] = bool(teacher["raw_exact"])
            row["acceptance_threshold"] = acceptance_threshold
            row["automatic"] = bool(
                row["release_eligible"]
                and float(row["confidence"]) >= acceptance_threshold
            )
            row["unsafe_automatic"] = bool(
                row["automatic"] and not row["raw_exact"]
            )
            row["effective_decision"] = (
                "SELECT_ACCESS" if row["automatic"] else "ABSTAIN"
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
            "inner_train_count": len(inner_training),
            "inner_validation_count": len(inner_validation),
            "outer_train_count": len(outer_training),
            "outer_validation_count": len(outer_validation),
            "best_epoch": tuning["best_epoch"],
            "best_validation_loss": tuning["best_validation_loss"],
            "acceptance_threshold": acceptance_threshold,
            "metrics": ordinary_access_metrics(decoded),
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "inner_checkpoint": _input_record(inner_checkpoint),
            "outer_checkpoint": _input_record(outer_checkpoint),
        }
        fold_summaries.append(fold_summary)
        _write_json(
            root / f"fold_{outer_fold}_summary.json",
            fold_summary,
        )
    predictions.sort(
        key=lambda row: (
            row["case_key"],
            row["segment_id"],
            row["junc_node_id"],
        )
    )
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    metrics = ordinary_access_metrics(predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ACCESS_DECODER_STRICT_NESTED_OOF",
        "model_scope": (
            "A candidate-set decoder selects one complete access Road and its "
            "deterministic endpoint/split position after anchor and complete "
            "ordinary Road-plan decisions."
        ),
        "training_condition": (
            "Teacher forcing uses only independently supervised exact anchor "
            "objects. OOF scoring uses only anchor-model predictions."
        ),
        "release_constraint": (
            "Access cannot repair or bypass anchor/Road-plan decisions. "
            "Automatic selection additionally requires a proven-safe OOF "
            "anchor, an exact upstream Road plan, and an inner-only "
            "zero-error confidence threshold."
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
        "read_summary": read_summary,
        "example_count": len(examples),
        "fold_count": len(folds),
        "metrics": metrics,
        "folds": fold_summaries,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "release_gate": "NO_GO",
        "selection_diagnostic_gate": (
            "PASS"
            if metrics["unsafe_automatic_count"] == 0
            and metrics["automatic_count"] > 0
            else "NO_GO"
        ),
        "release_no_go_reason": (
            "This head covers ordinary access Road/position only. Complete "
            "ordinary Road/Node topology, AdvanceRight, and global structured "
            "decode are not yet jointly released."
        ),
        "legacy_comparison": {
            "p13_raw_exact": 0.646907,
            "local_control_5m_exact": 0.680412,
            "comparison_note": (
                "P13 and 5m Local Control score AdvanceRight Road subsets. "
                "Ordinary access exact is a different downstream business "
                "object and is reported separately, not as a replacement."
            ),
        },
        "conditioned_store_summary": _input_record(store / "summary.json"),
        "predictions": _input_record(prediction_path),
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(predictions) == len(examples)
            and {_score_key(row) for row in predictions}
            == {
                (row.case_key, row.segment_id, row.junc_node_id)
                for row in examples
            }
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary access OOF coverage gate failed")
    return root


def read_ordinary_access_examples(
    root: Path,
) -> tuple[list[OrdinaryAccessExample], dict[str, int]]:
    store = normalize_runtime_path(root).resolve(strict=True)
    labels = {
        (
            str(row["case_key"]),
            str(row["segment_id"]),
            str(row["junc_node_id"]),
        ): row
        for row in _read_jsonl(
            store / "ordinary_access_training_labels.jsonl"
        )
    }
    examples = []
    counts: Counter[str] = Counter()
    current_key: tuple[str, str, str] | None = None
    current_rows: list[dict[str, Any]] = []
    path = store / "ordinary_access_conditioned_candidates.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (
                str(row["case_key"]),
                str(row["segment_id"]),
                str(row["junc_node_id"]),
            )
            if current_key is not None and key != current_key:
                example = _access_example(
                    current_key,
                    current_rows,
                    labels[current_key],
                )
                _count_example(example, labels[current_key], counts)
                if example is not None:
                    examples.append(example)
                current_rows = []
            current_key = key
            current_rows.append(row)
    if current_key is not None:
        example = _access_example(
            current_key,
            current_rows,
            labels[current_key],
        )
        _count_example(example, labels[current_key], counts)
        if example is not None:
            examples.append(example)
    if not examples:
        raise ValueError("ordinary access training has no usable examples")
    feature_dim = len(examples[0].teacher_features[0])
    if any(
        len(values) != feature_dim
        for row in examples
        for values in (*row.teacher_features, *row.oof_features)
    ):
        raise ValueError("ordinary access feature dimension differs")
    counts["usable_example"] = len(examples)
    counts["feature_dim"] = feature_dim
    return examples, dict(sorted(counts.items()))


def acceptable_set_nll(
    logits: torch.Tensor,
    acceptable: torch.Tensor,
    valid: torch.Tensor,
) -> torch.Tensor:
    if logits.shape != acceptable.shape or logits.shape != valid.shape:
        raise ValueError("ordinary access acceptable-set shapes differ")
    minimum = torch.finfo(logits.dtype).min
    return torch.logsumexp(
        logits.masked_fill(~valid, minimum),
        dim=-1,
    ) - torch.logsumexp(
        logits.masked_fill(~acceptable, minimum),
        dim=-1,
    )


def score_ordinary_access_examples(
    model: TargetAOrdinaryAccessDecoder,
    examples: Sequence[OrdinaryAccessExample],
    *,
    feature_source: str,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    if feature_source not in {"teacher", "oof"}:
        raise ValueError("ordinary access feature source is invalid")
    model.eval()
    result = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            values, mask, acceptable, _ = _batch_tensors(
                rows,
                feature_source=feature_source,
                device=device,
            )
            logits = model(values, mask)
            probabilities = torch.softmax(
                logits.masked_fill(~mask, torch.finfo(logits.dtype).min),
                dim=-1,
            )
            top_values, top_indices = probabilities.topk(
                min(2, probabilities.shape[-1]),
                dim=-1,
            )
            for index, row in enumerate(rows):
                selected = int(top_indices[index, 0].item())
                confidence = float(top_values[index, 0].item())
                margin = confidence
                if top_values.shape[-1] > 1:
                    margin -= float(top_values[index, 1].item())
                result.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": row.case_key,
                        "segment_id": row.segment_id,
                        "junc_node_id": row.junc_node_id,
                        "fold": row.fold,
                        "feature_source": feature_source,
                        "predicted_index": selected,
                        "predicted_proposal_id": row.proposal_ids[selected],
                        "predicted_road_id": row.road_ids[selected],
                        "predicted_operation": row.operations[selected],
                        "predicted_fraction": row.fractions[selected],
                        "acceptable_indices": list(row.acceptable_indices),
                        "raw_exact": bool(acceptable[index, selected]),
                        "confidence": confidence,
                        "margin": margin,
                        "candidate_count": len(row.proposal_ids),
                        "oof_anchor_release_ready": (
                            row.oof_anchor_release_ready
                        ),
                        "upstream_plan_release_blocked": (
                            row.upstream_plan_release_blocked
                        ),
                        "release_eligible": bool(
                            row.oof_anchor_release_ready
                            and not row.upstream_plan_release_blocked
                        ),
                    }
                )
    return result


def choose_zero_error_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    unsafe = [
        float(row["confidence"])
        for row in rows
        if bool(row["release_eligible"]) and not bool(row["raw_exact"])
    ]
    if not unsafe:
        return 0.0
    return min(1.000001, max(unsafe) + 1e-7)


def ordinary_access_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    count = len(rows)
    exact = sum(bool(row["raw_exact"]) for row in rows)
    teacher_exact = sum(bool(row.get("teacher_exact")) for row in rows)
    automatic = [row for row in rows if bool(row.get("automatic"))]
    unsafe = [row for row in automatic if not bool(row["raw_exact"])]
    eligible = [row for row in rows if bool(row["release_eligible"])]
    per_case: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        per_case.setdefault(str(row["case_key"]), []).append(row)
    case_exact = {
        case_key: sum(bool(row["raw_exact"]) for row in values) / len(values)
        for case_key, values in per_case.items()
    }
    return {
        "count": count,
        "oof_raw_exact": exact / count if count else 0.0,
        "teacher_raw_exact": teacher_exact / count if count else 0.0,
        "release_eligible_count": len(eligible),
        "automatic_count": len(automatic),
        "automatic_coverage": len(automatic) / count if count else 0.0,
        "automatic_exact": (
            sum(bool(row["raw_exact"]) for row in automatic)
            / len(automatic)
            if automatic
            else 0.0
        ),
        "unsafe_automatic_count": len(unsafe),
        "case_count": len(per_case),
        "worst_case_exact": min(case_exact.values()) if case_exact else 0.0,
    }


def _access_example(
    key: tuple[str, str, str],
    proposals: Sequence[Mapping[str, Any]],
    label: Mapping[str, Any],
) -> OrdinaryAccessExample | None:
    if not bool(label["access_task_mask"]):
        return None
    if not bool(label.get("teacher_condition_available")):
        return None
    if (
        "teacher_carrier_ready" in label
        and not bool(label["teacher_carrier_ready"])
    ):
        return None
    proposal_ids = tuple(str(row["proposal_id"]) for row in proposals)
    index_by_id = {
        proposal_id: index for index, proposal_id in enumerate(proposal_ids)
    }
    acceptable = tuple(
        sorted(
            {
                index_by_id[str(target["proposal_id"])]
                for target in label["acceptable_access_targets"]
                if str(target.get("proposal_id") or "") in index_by_id
            }
        )
    )
    if not acceptable:
        return None
    base = [
        [
            *[float(value) for value in row["object_feature_values"]],
            *[float(value) for value in row["plan_feature_values"]],
            *[float(value) for value in row["member_feature_values"]],
            *[float(value) for value in row["geometry_feature_values"]],
        ]
        for row in proposals
    ]
    return OrdinaryAccessExample(
        case_key=key[0],
        segment_id=key[1],
        junc_node_id=key[2],
        fold=int(label["fold"]),
        proposal_ids=proposal_ids,
        road_ids=tuple(str(row["road_id"]) for row in proposals),
        operations=tuple(str(row["operation"]) for row in proposals),
        fractions=tuple(float(row["projected_fraction"]) for row in proposals),
        teacher_features=tuple(
            tuple(
                [
                    *values,
                    *[
                        float(value)
                        for value in proposal[
                            "teacher_anchor_feature_values"
                        ]
                    ],
                    *[
                        float(value)
                        for value in proposal.get(
                            "teacher_carrier_feature_values",
                            (),
                        )
                    ],
                ]
            )
            for values, proposal in zip(base, proposals)
        ),
        oof_features=tuple(
            tuple(
                [
                    *values,
                    *[
                        float(value)
                        for value in proposal["oof_anchor_feature_values"]
                    ],
                    *[
                        float(value)
                        for value in proposal.get(
                            "oof_carrier_feature_values",
                            (),
                        )
                    ],
                ]
            )
            for values, proposal in zip(base, proposals)
        ),
        acceptable_indices=acceptable,
        sample_weight=float(label["access_label_weight"]),
        oof_anchor_release_ready=bool(
            label.get("oof_anchor_release_ready")
        ),
        upstream_plan_release_blocked=bool(
            label.get("upstream_plan_release_blocked")
        ),
    )


def _count_example(
    example: OrdinaryAccessExample | None,
    label: Mapping[str, Any],
    counts: Counter[str],
) -> None:
    counts["label"] += 1
    counts["access_task_mask"] += int(label["access_task_mask"])
    counts["teacher_condition_available"] += int(
        label.get("teacher_condition_available") or False
    )
    counts["teacher_carrier_ready"] += int(
        label.get("teacher_carrier_ready", True)
    )
    if example is None:
        if not bool(label["access_task_mask"]):
            counts["masked_by_access_label"] += 1
        elif not bool(label.get("teacher_condition_available")):
            counts["masked_anchor_object_unknown"] += 1
        elif (
            "teacher_carrier_ready" in label
            and not bool(label["teacher_carrier_ready"])
        ):
            counts["masked_complete_carrier_unknown"] += 1
        else:
            counts["masked_target_unreachable"] += 1


def _fit_model(
    training: Sequence[OrdinaryAccessExample],
    validation: Sequence[OrdinaryAccessExample],
    *,
    feature_dim: int,
    config: OrdinaryAccessTrainingConfig,
    device: torch.device,
    seed: int,
) -> dict[str, Any]:
    model = _new_model(feature_dim, config, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    best_state = copy.deepcopy(model.state_dict())
    best_loss = float("inf")
    best_epoch = 1
    stale = 0
    history = []
    for epoch in range(1, config.max_epochs + 1):
        train_loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            batch_size=config.batch_size,
            device=device,
            seed=seed + epoch,
        )
        validation_loss = _evaluate_loss(
            model,
            validation,
            batch_size=config.batch_size,
            device=device,
        )
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-8:
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
    training: Sequence[OrdinaryAccessExample],
    *,
    feature_dim: int,
    config: OrdinaryAccessTrainingConfig,
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
            batch_size=config.batch_size,
            device=device,
            seed=seed + epoch,
        )
        history.append({"epoch": float(epoch), "train_loss": loss})
    return {"model": model, "history": history}


def _new_model(
    feature_dim: int,
    config: OrdinaryAccessTrainingConfig,
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
    examples: Sequence[OrdinaryAccessExample],
    *,
    optimizer: torch.optim.Optimizer,
    batch_size: int,
    device: torch.device,
    seed: int,
) -> float:
    model.train()
    order = list(range(len(examples)))
    random.Random(seed).shuffle(order)
    total = 0.0
    weight_total = 0.0
    for start in range(0, len(order), batch_size):
        rows = [examples[index] for index in order[start : start + batch_size]]
        values, mask, acceptable, weights = _batch_tensors(
            rows,
            feature_source="teacher",
            device=device,
        )
        optimizer.zero_grad(set_to_none=True)
        logits = model(values, mask)
        raw = acceptable_set_nll(logits, acceptable, mask)
        loss = (raw * weights).sum() / weights.sum().clamp_min(1e-6)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        optimizer.step()
        total += float((raw.detach() * weights).sum().item())
        weight_total += float(weights.sum().item())
    return total / max(weight_total, 1e-9)


def _evaluate_loss(
    model: TargetAOrdinaryAccessDecoder,
    examples: Sequence[OrdinaryAccessExample],
    *,
    batch_size: int,
    device: torch.device,
) -> float:
    model.eval()
    total = 0.0
    weight_total = 0.0
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            values, mask, acceptable, weights = _batch_tensors(
                rows,
                feature_source="teacher",
                device=device,
            )
            raw = acceptable_set_nll(model(values, mask), acceptable, mask)
            total += float((raw * weights).sum().item())
            weight_total += float(weights.sum().item())
    return total / max(weight_total, 1e-9)


def _batch_tensors(
    examples: Sequence[OrdinaryAccessExample],
    *,
    feature_source: str,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    candidate_count = max(len(row.proposal_ids) for row in examples)
    source = [
        row.teacher_features if feature_source == "teacher" else row.oof_features
        for row in examples
    ]
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
    acceptable = torch.zeros_like(mask)
    weights = torch.tensor(
        [row.sample_weight for row in examples],
        dtype=torch.float32,
        device=device,
    )
    for row_index, (row, features) in enumerate(zip(examples, source)):
        length = len(features)
        values[row_index, :length] = torch.tensor(
            features,
            dtype=torch.float32,
            device=device,
        )
        mask[row_index, :length] = True
        acceptable[row_index, list(row.acceptable_indices)] = True
    return values, mask, acceptable, weights


def _save_checkpoint(
    path: Path,
    model: TargetAOrdinaryAccessDecoder,
    *,
    config: OrdinaryAccessTrainingConfig,
    feature_dim: int,
    fold: int,
    inner_fold: int,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ORDINARY_ACCESS_DECODER",
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


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _assert_case_disjoint(
    training: Sequence[OrdinaryAccessExample],
    validation: Sequence[OrdinaryAccessExample],
) -> None:
    overlap = {row.case_key for row in training} & {
        row.case_key for row in validation
    }
    if overlap:
        raise ValueError(f"ordinary access Case leakage: {sorted(overlap)[:5]}")


def _score_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["case_key"]),
        str(row["segment_id"]),
        str(row["junc_node_id"]),
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            stream.write("\n")


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


__all__ = [
    "OrdinaryAccessExample",
    "OrdinaryAccessTrainingConfig",
    "acceptable_set_nll",
    "choose_zero_error_threshold",
    "ordinary_access_metrics",
    "read_ordinary_access_examples",
    "run_ordinary_access_strict_nested_oof",
    "score_ordinary_access_examples",
]
