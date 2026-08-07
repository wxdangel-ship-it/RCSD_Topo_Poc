from __future__ import annotations

import copy
import random
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    OrdinaryRoadSetExample,
    OrdinaryRoadSetTrainingConfig,
    _assert_case_disjoint,
    _cardinality_class_weights,
    _input_record,
    _write_json,
    _write_jsonl,
    balanced_member_bce,
    choose_zero_exact_error_threshold,
    masked_candidate_cross_entropy,
    ordinary_road_set_metrics,
    read_ordinary_road_set_examples,
    score_ordinary_road_set_examples,
    validate_cardinality_capacity,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_members import (
    ROAD_BUSINESS_ROLE_LABELS,
    ROAD_OWNERSHIP_LABELS,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_role_set_network import (
    TargetAOrdinaryCountAwareRoleSetDecoder,
    TargetAOrdinaryRoleSetDecoder,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


DEFAULT_ROLE_SET_CONFIG = OrdinaryRoadSetTrainingConfig(
    structured_graph_decoder=True,
    anchor_relation_decoder=True,
    ownership_role_decoder=True,
    business_member_fusion=False,
    cardinality_count=67,
    batch_size=48,
    max_epochs=80,
    patience=12,
    learning_rate=4e-4,
    weight_decay=2e-4,
    teacher_training_loss_weight=0.5,
    oof_training_loss_weight=1.0,
    oof_early_stopping=True,
)
CARDINALITY_ORDINAL_LOSS_WEIGHT = 0.5
MEMBER_MASS_LOSS_WEIGHT = 0.2


def run_ordinary_role_set_strict_nested_oof(
    *,
    member_store_root: Path,
    output_root: Path,
    seed: int,
    config: OrdinaryRoadSetTrainingConfig = DEFAULT_ROLE_SET_CONFIG,
    requested_device: str = "cuda",
    count_aware: bool = False,
) -> Path:
    """Pretrain the exact joint set forward with auxiliary Road roles."""
    started = time.perf_counter()
    config.validate()
    if (
        not config.ownership_role_decoder
        or config.business_member_fusion
        or config.component_edge_decoder
    ):
        raise ValueError(
            "ordinary role-set pretraining requires auxiliary-only roles"
        )
    store = normalize_runtime_path(member_store_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    examples, read_summary = read_ordinary_road_set_examples(store)
    validate_cardinality_capacity(
        maximum_target_cardinality=read_summary[
            "maximum_target_cardinality"
        ],
        cardinality_count=config.cardinality_count,
    )
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("ordinary role-set strict OOF needs three folds")
    root.mkdir(parents=True)
    torch.set_num_threads(config.torch_num_threads)
    device = _resolve_device(requested_device)
    object_dim = len(examples[0].object_features)
    candidate_dim = len(examples[0].teacher_features[0])
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
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 17,
            count_aware=count_aware,
        )
        final = _fit_fixed_epochs(
            outer_training,
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 53,
            epoch_count=tuning["best_epoch"],
            count_aware=count_aware,
        )
        model_parameters = parameter_count(final["model"])
        inner_scores = score_ordinary_road_set_examples(
            tuning["model"],
            inner_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        threshold = choose_zero_exact_error_threshold(inner_scores)
        teacher_scores = score_ordinary_road_set_examples(
            final["model"],
            outer_validation,
            feature_source="teacher",
            batch_size=config.batch_size,
            device=device,
        )
        oof_scores = score_ordinary_road_set_examples(
            final["model"],
            outer_validation,
            feature_source="oof",
            batch_size=config.batch_size,
            device=device,
        )
        teacher_by_key = {
            (row["case_key"], row["segment_id"]): row
            for row in teacher_scores
        }
        decoded = []
        for score in oof_scores:
            teacher = teacher_by_key[
                (score["case_key"], score["segment_id"])
            ]
            row = dict(score)
            row["teacher_complete_exact"] = bool(
                teacher["complete_exact"]
            )
            row["acceptance_threshold"] = threshold
            row["automatic"] = bool(
                row["release_eligible"]
                and float(row["confidence"]) >= threshold
            )
            row["unsafe_automatic"] = bool(
                row["automatic"] and not row["complete_exact"]
            )
            row["effective_decision"] = (
                row["predicted_decision"] if row["automatic"] else "ABSTAIN"
            )
            row["outer_fold"] = outer_fold
            row["inner_validation_fold"] = inner_fold
            decoded.append(row)
        predictions.extend(decoded)
        inner_checkpoint = root / f"fold_{outer_fold}_inner_checkpoint.pt"
        outer_checkpoint = root / f"fold_{outer_fold}_checkpoint.pt"
        _save_checkpoint(
            tuning["model"],
            inner_checkpoint,
            config=config,
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
        )
        _save_checkpoint(
            final["model"],
            outer_checkpoint,
            config=config,
            object_dim=object_dim,
            candidate_dim=candidate_dim,
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
            "acceptance_threshold": threshold,
            "metrics": ordinary_road_set_metrics(decoded),
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
        key=lambda row: (row["case_key"], row["segment_id"])
    )
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    metrics = ordinary_road_set_metrics(predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_ROLE_AWARE_SET_DECODER_STRICT_NESTED_OOF",
        "decoder_kind": (
            "COUNT_AWARE_UNORDERED_SET_WITH_AUXILIARY_OWNERSHIP_ROLE"
            if count_aware
            else "UNORDERED_SET_WITH_AUXILIARY_OWNERSHIP_ROLE"
        ),
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "torch_version": torch.__version__,
        "object_feature_dim": object_dim,
        "candidate_feature_dim": candidate_dim,
        "parameter_count": model_parameters,
        "config": asdict(config),
        "example_count": len(examples),
        "fold_count": len(folds),
        "read_summary": read_summary,
        "metrics": metrics,
        "folds": fold_summaries,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "membership_forward_contract": (
            "The object/Road encoders, set pooling, decision, cardinality "
            "and member heads are identical to the AdvanceRight joint "
            "ordinary decoder. Ownership and business role are auxiliary "
            "outputs and never rewrite member logits."
        ),
        "count_aware": count_aware,
        "cardinality_ordinal_loss_weight": (
            CARDINALITY_ORDINAL_LOSS_WEIGHT if count_aware else 0.0
        ),
        "member_mass_loss_weight": (
            MEMBER_MASS_LOSS_WEIGHT if count_aware else 0.0
        ),
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "access, final Node recipe, AdvanceRight and global decoder "
            "remain outside this pretraining stage"
        ),
        "gate_pass": len(predictions) == len(examples),
        "member_store_summary": _input_record(store / "summary.json"),
        "predictions": _input_record(prediction_path),
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary role-set OOF coverage gate failed")
    return root


def collate_role_set_batch(
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    feature_sources: str | Sequence[str],
    sample_weight_multipliers: Sequence[float] | None = None,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    """Collate only tensors consumed by the unordered-set forward."""
    if not examples:
        raise ValueError("cannot collate an empty ordinary role-set batch")
    sources = (
        [feature_sources] * len(examples)
        if isinstance(feature_sources, str)
        else list(feature_sources)
    )
    if len(sources) != len(examples) or any(
        source not in {"teacher", "oof"} for source in sources
    ):
        raise ValueError("ordinary role-set feature sources differ")
    multipliers = (
        [1.0] * len(examples)
        if sample_weight_multipliers is None
        else [float(value) for value in sample_weight_multipliers]
    )
    if len(multipliers) != len(examples) or min(
        multipliers,
        default=0.0,
    ) < 0.0:
        raise ValueError("ordinary role-set sample multipliers differ")
    feature_rows = [
        row.teacher_features if source == "teacher" else row.oof_features
        for row, source in zip(examples, sources)
    ]
    candidate_count = max(len(row.road_ids) for row in examples)
    candidate_dim = len(feature_rows[0][0])
    objects = torch.tensor(
        [row.object_features for row in examples],
        dtype=torch.float32,
        device=device,
    )
    candidates = torch.zeros(
        len(examples),
        candidate_count,
        candidate_dim,
        dtype=torch.float32,
        device=device,
    )
    mask = torch.zeros(
        len(examples),
        candidate_count,
        dtype=torch.bool,
        device=device,
    )
    targets = torch.zeros_like(mask)
    member_weight_ratios = torch.zeros(
        len(examples),
        candidate_count,
        dtype=torch.float32,
        device=device,
    )
    ownership_targets = torch.zeros(
        len(examples),
        candidate_count,
        dtype=torch.long,
        device=device,
    )
    ownership_mask = torch.zeros_like(mask)
    role_targets = torch.zeros_like(ownership_targets)
    role_mask = torch.zeros_like(mask)
    for index, (row, values) in enumerate(zip(examples, feature_rows)):
        length = len(values)
        if any(len(value) != candidate_dim for value in values):
            raise ValueError("ordinary role-set candidate dimension differs")
        candidates[index, :length] = torch.tensor(
            values,
            dtype=torch.float32,
            device=device,
        )
        mask[index, :length] = True
        targets[index, list(row.target_indices)] = True
        member_weights = (
            row.member_sample_weights
            or (row.sample_weight,) * length
        )
        if len(member_weights) != length:
            raise ValueError("ordinary role-set member weights differ")
        member_weight_ratios[index, :length] = torch.tensor(
            [
                (
                    float(value) / row.sample_weight
                    if row.sample_weight > 0.0
                    else 0.0
                )
                for value in member_weights
            ],
            dtype=torch.float32,
            device=device,
        )
        ownership_targets[index, :length] = torch.tensor(
            row.ownership_targets,
            dtype=torch.long,
            device=device,
        )
        ownership_mask[index, :length] = torch.tensor(
            row.ownership_task_mask,
            dtype=torch.bool,
            device=device,
        )
        role_targets[index, :length] = torch.tensor(
            row.business_role_targets,
            dtype=torch.long,
            device=device,
        )
        role_mask[index, :length] = torch.tensor(
            row.business_role_task_mask,
            dtype=torch.bool,
            device=device,
        )
    return {
        "objects": objects,
        "candidates": candidates,
        "mask": mask,
        "targets": targets,
        "member_weight_ratios": member_weight_ratios,
        "ownership_targets": ownership_targets,
        "ownership_task_mask": ownership_mask,
        "business_role_targets": role_targets,
        "business_role_task_mask": role_mask,
        "decisions": torch.tensor(
            [row.decision for row in examples],
            dtype=torch.long,
            device=device,
        ),
        "cardinalities": torch.tensor(
            [len(row.target_indices) for row in examples],
            dtype=torch.long,
            device=device,
        ),
        "ownership_weight_ratios": torch.tensor(
            [
                (
                    (
                        row.ownership_sample_weight
                        if row.ownership_sample_weight > 0.0
                        else row.sample_weight
                    )
                    / row.sample_weight
                    if row.sample_weight > 0.0
                    else 0.0
                )
                for row in examples
            ],
            dtype=torch.float32,
            device=device,
        ),
        "business_role_weight_ratios": torch.tensor(
            [
                (
                    (
                        row.business_role_sample_weight
                        if row.business_role_sample_weight > 0.0
                        else row.sample_weight
                    )
                    / row.sample_weight
                    if row.sample_weight > 0.0
                    else 0.0
                )
                for row in examples
            ],
            dtype=torch.float32,
            device=device,
        ),
        "weights": torch.tensor(
            [
                row.sample_weight * multiplier
                for row, multiplier in zip(examples, multipliers)
            ],
            dtype=torch.float32,
            device=device,
        ),
    }


def _role_set_loss_rows(
    outputs: dict[str, torch.Tensor],
    batch: dict[str, torch.Tensor],
    config: OrdinaryRoadSetTrainingConfig,
    *,
    cardinality_weights: torch.Tensor | None,
) -> torch.Tensor:
    decision = torch.nn.functional.cross_entropy(
        outputs["decision_logits"],
        batch["decisions"],
        reduction="none",
    )
    cardinality = torch.nn.functional.cross_entropy(
        outputs["cardinality_logits"],
        batch["cardinalities"],
        weight=cardinality_weights,
        reduction="none",
    )
    cardinality_probabilities = torch.softmax(
        outputs["cardinality_logits"],
        dim=-1,
    )
    cardinality_values = torch.arange(
        outputs["cardinality_logits"].shape[-1],
        dtype=torch.float32,
        device=outputs["cardinality_logits"].device,
    )
    expected_cardinality = (
        cardinality_probabilities * cardinality_values
    ).sum(dim=-1)
    cardinality_ordinal = torch.nn.functional.smooth_l1_loss(
        expected_cardinality,
        batch["cardinalities"].to(dtype=torch.float32),
        reduction="none",
    )
    members = balanced_member_bce(
        outputs["member_logits"],
        batch["targets"],
        batch["mask"],
        batch["member_weight_ratios"],
    )
    ownership = masked_candidate_cross_entropy(
        outputs["ownership_logits"],
        batch["ownership_targets"],
        batch["ownership_task_mask"],
    )
    business_role = masked_candidate_cross_entropy(
        outputs["business_role_logits"],
        batch["business_role_targets"],
        batch["business_role_task_mask"],
    )
    total = (
        config.decision_loss_weight * decision
        + config.cardinality_loss_weight * cardinality
        + config.cardinality_ordinal_loss_weight * cardinality_ordinal
        + config.member_loss_weight * members
        + config.ownership_loss_weight
        * ownership
        * batch["ownership_weight_ratios"]
        + config.business_role_loss_weight
        * business_role
        * batch["business_role_weight_ratios"]
    )
    if "cardinality_ordinal_logits" in outputs:
        thresholds = torch.arange(
            outputs["cardinality_ordinal_logits"].shape[-1],
            device=outputs["cardinality_ordinal_logits"].device,
        )
        ordinal_targets = (
            batch["cardinalities"].unsqueeze(-1) > thresholds.unsqueeze(0)
        ).to(outputs["cardinality_ordinal_logits"].dtype)
        ordinal = torch.nn.functional.binary_cross_entropy_with_logits(
            outputs["cardinality_ordinal_logits"],
            ordinal_targets,
            reduction="none",
        ).mean(dim=-1)
        member_mass = torch.nn.functional.smooth_l1_loss(
            outputs["soft_member_count"],
            batch["cardinalities"].to(dtype=torch.float32),
            reduction="none",
        )
        total = (
            total
            + CARDINALITY_ORDINAL_LOSS_WEIGHT * ordinal
            + MEMBER_MASS_LOSS_WEIGHT * member_mass
        )
    return total


def _train_epoch(
    model: TargetAOrdinaryRoleSetDecoder,
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    optimizer: torch.optim.Optimizer,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
    seed: int,
    cardinality_weights: torch.Tensor | None,
) -> float:
    model.train()
    views = [
        (index, source, weight)
        for index in range(len(examples))
        for source, weight in (
            ("teacher", config.teacher_training_loss_weight),
            ("oof", config.oof_training_loss_weight),
        )
        if weight > 0.0
    ]
    random.Random(seed).shuffle(views)
    total = 0.0
    weight_total = 0.0
    for start in range(0, len(views), config.batch_size):
        selected = views[start : start + config.batch_size]
        rows = [examples[index] for index, _, _ in selected]
        batch = collate_role_set_batch(
            rows,
            feature_sources=[source for _, source, _ in selected],
            sample_weight_multipliers=[
                weight for _, _, weight in selected
            ],
            device=device,
        )
        optimizer.zero_grad(set_to_none=True)
        outputs = model(
            object_features=batch["objects"],
            candidate_features=batch["candidates"],
            candidate_mask=batch["mask"],
        )
        raw = _role_set_loss_rows(
            outputs,
            batch,
            config,
            cardinality_weights=cardinality_weights,
        )
        loss = (raw * batch["weights"]).sum() / batch[
            "weights"
        ].sum().clamp_min(1e-6)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        optimizer.step()
        total += float((raw.detach() * batch["weights"]).sum().item())
        weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _evaluate_loss(
    model: TargetAOrdinaryRoleSetDecoder,
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
    cardinality_weights: torch.Tensor | None,
) -> float:
    model.eval()
    total = 0.0
    weight_total = 0.0
    with torch.no_grad():
        for start in range(0, len(examples), config.batch_size):
            rows = examples[start : start + config.batch_size]
            batch = collate_role_set_batch(
                rows,
                feature_sources=(
                    "oof" if config.oof_early_stopping else "teacher"
                ),
                device=device,
            )
            outputs = model(
                object_features=batch["objects"],
                candidate_features=batch["candidates"],
                candidate_mask=batch["mask"],
            )
            raw = _role_set_loss_rows(
                outputs,
                batch,
                config,
                cardinality_weights=cardinality_weights,
            )
            total += float((raw * batch["weights"]).sum().item())
            weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _fit_model(
    training: Sequence[OrdinaryRoadSetExample],
    validation: Sequence[OrdinaryRoadSetExample],
    *,
    object_dim: int,
    candidate_dim: int,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
    seed: int,
    count_aware: bool,
) -> dict[str, Any]:
    model = _new_model(
        object_dim,
        candidate_dim,
        config=config,
        device=device,
        seed=seed,
        count_aware=count_aware,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    cardinality_weights = _cardinality_class_weights(
        training,
        config=config,
        device=device,
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
            config=config,
            device=device,
            seed=seed + epoch,
            cardinality_weights=cardinality_weights,
        )
        validation_loss = _evaluate_loss(
            model,
            validation,
            config=config,
            device=device,
            cardinality_weights=cardinality_weights,
        )
        history.append(
            {
                "epoch": epoch,
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
    model.eval()
    return {
        "model": model,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "history": history,
    }


def _fit_fixed_epochs(
    training: Sequence[OrdinaryRoadSetExample],
    *,
    object_dim: int,
    candidate_dim: int,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
    seed: int,
    epoch_count: int,
    count_aware: bool,
) -> dict[str, Any]:
    model = _new_model(
        object_dim,
        candidate_dim,
        config=config,
        device=device,
        seed=seed,
        count_aware=count_aware,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    cardinality_weights = _cardinality_class_weights(
        training,
        config=config,
        device=device,
    )
    history = []
    for epoch in range(1, epoch_count + 1):
        history.append(
            {
                "epoch": epoch,
                "train_loss": _train_epoch(
                    model,
                    training,
                    optimizer=optimizer,
                    config=config,
                    device=device,
                    seed=seed + epoch,
                    cardinality_weights=cardinality_weights,
                ),
            }
        )
    model.eval()
    return {"model": model, "history": history}


def _new_model(
    object_dim: int,
    candidate_dim: int,
    *,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
    seed: int,
    count_aware: bool = False,
) -> TargetAOrdinaryRoleSetDecoder | TargetAOrdinaryCountAwareRoleSetDecoder:
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    model_class = (
        TargetAOrdinaryCountAwareRoleSetDecoder
        if count_aware
        else TargetAOrdinaryRoleSetDecoder
    )
    return model_class(
        object_feature_dim=object_dim,
        candidate_feature_dim=candidate_dim,
        hidden_dim=config.hidden_dim,
        context_dim=config.context_dim,
        cardinality_count=config.cardinality_count,
        ownership_count=len(ROAD_OWNERSHIP_LABELS),
        business_role_count=len(ROAD_BUSINESS_ROLE_LABELS),
        dropout=config.dropout,
    ).to(device)


def _save_checkpoint(
    model: TargetAOrdinaryRoleSetDecoder
    | TargetAOrdinaryCountAwareRoleSetDecoder,
    path: Path,
    *,
    config: OrdinaryRoadSetTrainingConfig,
    object_dim: int,
    candidate_dim: int,
    fold: int,
    inner_fold: int,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": (
                "ORDINARY_COUNT_AWARE_ROLE_SET_DECODER"
                if isinstance(
                    model,
                    TargetAOrdinaryCountAwareRoleSetDecoder,
                )
                else "ORDINARY_ROLE_AWARE_SET_DECODER"
            ),
            "config": asdict(config),
            "object_dim": object_dim,
            "candidate_dim": candidate_dim,
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
    normalized = requested.casefold()
    if normalized == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
        return torch.device("cuda")
    if normalized == "cpu":
        return torch.device("cpu")
    raise ValueError(f"unsupported ordinary role-set device: {requested}")


__all__ = [
    "DEFAULT_ROLE_SET_CONFIG",
    "run_ordinary_role_set_strict_nested_oof",
]
