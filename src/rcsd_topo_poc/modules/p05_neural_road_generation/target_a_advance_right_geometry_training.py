from __future__ import annotations

import copy
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_network import (
    TargetAAdvanceRightGeometryDecoder,
    trainable_parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_training import (
    AUTOMATIC_PLAN_TYPES,
    CARDINALITY_COUNT,
    _plan_class_weights,
    _safety_negative_weight,
    _structured_selection_loss,
    collate_advance_right_batch,
    decode_advance_right_scores,
    read_advance_right_conditioned_examples,
    score_advance_right_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


PROPOSAL_TYPE_INDEX = {
    "SOURCE_ATTACHMENT": 0,
    "TARGET_ATTACHMENT": 1,
    "MIDDLE_SPLICE": 2,
}
PROPOSAL_FEATURE_DIM = 113


def run_advance_right_geometry_strict_nested_oof(
    *,
    conditioned_store_root: Path,
    geometry_candidate_store_root: Path,
    base_oof_root: Path,
    output_root: Path,
    seed: int,
    batch_size: int = 32,
    requested_device: str = "cuda",
    max_epochs: int = 120,
    patience: int = 18,
    learning_rate: float = 5e-4,
    weight_decay: float = 2e-4,
    minimum_geometry_acceptance_threshold: float = 0.0,
    fine_tune_base: bool = False,
    base_loss_weight: float = 0.0,
) -> Path:
    """Train split/splice selection, optionally jointly tuning the encoder."""
    started = time.perf_counter()
    if min(batch_size, max_epochs, patience) < 1:
        raise ValueError("geometry training configuration is invalid")
    if fine_tune_base != (base_loss_weight > 0.0):
        raise ValueError(
            "fine_tune_base requires a positive base_loss_weight and vice versa"
        )
    conditioned_root = normalize_runtime_path(
        conditioned_store_root
    ).resolve(strict=True)
    geometry_root = normalize_runtime_path(
        geometry_candidate_store_root
    ).resolve(strict=True)
    base_root = normalize_runtime_path(base_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples = read_geometry_examples(conditioned_root, geometry_root)
    folds = sorted({int(row["fold"]) for row in examples})
    if len(folds) < 3:
        raise ValueError("geometry strict OOF requires three folds")
    device = _resolve_device(requested_device)
    torch.set_num_threads(4)

    predictions = []
    fold_summaries = []
    model_parameters = 0
    geometry_parameters = 0
    for outer_fold in folds:
        inner_fold = folds[(folds.index(outer_fold) + 1) % len(folds)]
        inner_training = [
            row
            for row in examples
            if int(row["fold"]) not in {outer_fold, inner_fold}
        ]
        inner_validation = [
            row for row in examples if int(row["fold"]) == inner_fold
        ]
        outer_training = [
            row for row in examples if int(row["fold"]) != outer_fold
        ]
        outer_validation = [
            row for row in examples if int(row["fold"]) == outer_fold
        ]
        _assert_case_disjoint(inner_training, inner_validation)
        _assert_case_disjoint(outer_training, outer_validation)
        base_fold_summary = json.loads(
            (base_root / f"fold_{outer_fold}_summary.json").read_text(
                encoding="utf-8"
            )
        )
        tuning = _fit_geometry_model(
            inner_training,
            inner_validation,
            base_checkpoint=base_root
            / f"fold_{outer_fold}_inner_checkpoint.pt",
            seed=seed + outer_fold * 100 + 17,
            batch_size=batch_size,
            device=device,
            max_epochs=max_epochs,
            patience=patience,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            fine_tune_base=fine_tune_base,
            base_loss_weight=base_loss_weight,
        )
        final = _fit_geometry_fixed_epochs(
            outer_training,
            base_checkpoint=base_root / f"fold_{outer_fold}_checkpoint.pt",
            seed=seed + outer_fold * 100 + 53,
            batch_size=batch_size,
            device=device,
            epoch_count=tuning["best_epoch"],
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            fine_tune_base=fine_tune_base,
            base_loss_weight=base_loss_weight,
        )
        model_parameters = parameter_count(final["model"])
        geometry_parameters = trainable_parameter_count(final["model"])
        inner_rows = score_geometry_examples(
            tuning["model"],
            inner_validation,
            batch_size=batch_size,
            device=device,
            base_safety_threshold=float(
                base_fold_summary["safety_threshold"]
            ),
            base_acceptance_threshold=float(
                base_fold_summary["acceptance_threshold"]
            ),
            geometry_acceptance_threshold=0.0,
        )
        geometry_threshold = max(
            minimum_geometry_acceptance_threshold,
            choose_zero_error_geometry_threshold(inner_rows),
        )
        outer_rows = score_geometry_examples(
            final["model"],
            outer_validation,
            batch_size=batch_size,
            device=device,
            base_safety_threshold=float(
                base_fold_summary["safety_threshold"]
            ),
            base_acceptance_threshold=float(
                base_fold_summary["acceptance_threshold"]
            ),
            geometry_acceptance_threshold=geometry_threshold,
        )
        for row in outer_rows:
            row["outer_fold"] = outer_fold
            row["inner_validation_fold"] = inner_fold
        predictions.extend(outer_rows)
        checkpoint_path = root / f"fold_{outer_fold}_checkpoint.pt"
        _save_checkpoint(
            checkpoint_path,
            model=final["model"],
            base_checkpoint=base_root / f"fold_{outer_fold}_checkpoint.pt",
            fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 53,
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
            "base_safety_threshold": float(
                base_fold_summary["safety_threshold"]
            ),
            "base_acceptance_threshold": float(
                base_fold_summary["acceptance_threshold"]
            ),
            "geometry_acceptance_threshold": geometry_threshold,
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "metrics": geometry_metrics(outer_rows),
            "checkpoint": _input_record(checkpoint_path),
        }
        fold_summaries.append(fold_summary)
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_summary)

    predictions.sort(key=lambda row: (row["case_key"], row["object_id"]))
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    metrics = geometry_metrics(predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_GEOMETRY_STRUCTURED_DECODER_STRICT_OOF",
        "model_scope": (
            "The hierarchical conditional encoder and structured geometry "
            "head are jointly optimized with carrier and geometry losses."
            if fine_tune_base
            else (
                "The hierarchical conditional encoder is reused and frozen. "
                "A structured head selects source/target attachment proposals "
                "and the MIXED_SPLICE RCSD/SWSD proposal."
            )
        ),
        "output_scope": {
            "trained": [
                "attachment_side",
                "advance_right_endpoint",
                "adjacent_ordinary_road",
                "ordinary_road_split_fraction",
                "mixed_rcsd_road",
                "mixed_swsd_road",
                "mixed_two_splice_fractions",
                "geometry_safety_or_fallback",
            ],
            "deterministic_only": [
                "execute_split_or_splice",
                "generate_final_node_id",
                "write_final_geometry",
            ],
        },
        "example_count": len(examples),
        "fold_count": len(folds),
        "seed": seed,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "patience": patience,
        "learning_rate": learning_rate,
        "weight_decay": weight_decay,
        "base_loss_weight": base_loss_weight,
        "minimum_geometry_acceptance_threshold": (
            minimum_geometry_acceptance_threshold
        ),
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "parameter_count": model_parameters,
        "trainable_geometry_parameter_count": geometry_parameters,
        "trainable_parameter_count": geometry_parameters,
        "base_encoder_frozen": not fine_tune_base,
        "metrics": metrics,
        "folds": fold_summaries,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "silent_fix": False,
        "release_gate": "NO_GO",
        "selection_diagnostic_gate": (
            "PASS"
            if metrics["unsafe_automatic_count"] == 0
            and metrics["automatic_count"] > 0
            else "NO_GO"
        ),
        "release_no_go_reason": (
            "The global conflict decoder, generated Node recipe validation and "
            "complete RoadGraph execution/evaluation are still pending."
        ),
        "inputs": {
            "conditioned_summary": _input_record(
                conditioned_root / "summary.json"
            ),
            "geometry_candidate_summary": _input_record(
                geometry_root / "summary.json"
            ),
            "base_oof_summary": _input_record(base_root / "summary.json"),
        },
        "outputs": {"oof_predictions": _input_record(prediction_path)},
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def read_geometry_examples(
    conditioned_root: Path,
    geometry_root: Path,
) -> list[dict[str, Any]]:
    examples = read_advance_right_conditioned_examples(conditioned_root)
    proposals: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(
        geometry_root / "advance_right_geometry_inference_candidates.jsonl"
    ):
        proposals[(str(row["case_key"]), str(row["object_id"]))].append(row)
    labels = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in _read_jsonl(
            geometry_root / "advance_right_geometry_training_labels.jsonl"
        )
    }
    result = []
    for source in examples:
        row = dict(source)
        key = (str(row["case_key"]), str(row["object_id"]))
        row["geometry_proposals"] = sorted(
            proposals.get(key, []),
            key=lambda value: (
                str(value["proposal_type"]),
                str(value["proposal_id"]),
            ),
        )
        label = labels[key]
        for field in (
            "geometry_task_mask",
            "geometry_safety_target",
            "geometry_safety_weight",
            "geometry_label_weight",
            "acceptable_geometry_variants",
        ):
            row[field] = copy.deepcopy(label[field])
        result.append(row)
    result.sort(key=lambda row: (row["case_key"], row["object_id"]))
    return result


def collate_geometry_batch(
    examples: Sequence[Mapping[str, Any]],
    *,
    device: torch.device,
) -> dict[str, Any]:
    base = collate_advance_right_batch(examples, device=device)
    proposal_count = max(
        1,
        max(len(row["geometry_proposals"]) for row in examples),
    )
    values = torch.zeros(
        (len(examples), proposal_count, PROPOSAL_FEATURE_DIM),
        dtype=torch.float32,
    )
    mask = torch.zeros(
        (len(examples), proposal_count),
        dtype=torch.bool,
    )
    for index, example in enumerate(examples):
        proposals = list(example["geometry_proposals"])
        if not proposals:
            continue
        encoded = [_proposal_features(row) for row in proposals]
        tensor = torch.tensor(encoded, dtype=torch.float32)
        if tensor.shape[-1] != PROPOSAL_FEATURE_DIM:
            raise ValueError("geometry proposal feature dim differs")
        values[index, : len(proposals)] = tensor
        mask[index, : len(proposals)] = True
    base["proposal_values"] = values.to(device)
    base["proposal_mask"] = mask.to(device)
    return base


def geometry_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: Mapping[str, Any],
    *,
    base_loss_weight: float = 0.0,
    plan_weights: torch.Tensor | None = None,
    safety_negative_weight: float = 1.0,
) -> torch.Tensor:
    examples = batch["examples"]
    safety_target = torch.tensor(
        [float(row["geometry_safety_target"]) for row in examples],
        dtype=torch.float32,
        device=outputs["geometry_safety_logits"].device,
    )
    safety_weight = torch.tensor(
        [float(row["geometry_safety_weight"]) for row in examples],
        dtype=torch.float32,
        device=outputs["geometry_safety_logits"].device,
    )
    safety = nn.functional.binary_cross_entropy_with_logits(
        outputs["geometry_safety_logits"],
        safety_target,
        reduction="none",
    )
    total = (safety * safety_weight).sum() / safety_weight.sum().clamp_min(1.0)
    selection_losses = []
    selection_weights = []
    for index, example in enumerate(examples):
        if not bool(example["geometry_task_mask"]):
            continue
        variants = [
            row
            for row in example["acceptable_geometry_variants"]
            if bool(row["reachable"]) and row["proposal_ids"]
        ]
        if not variants:
            continue
        proposals = list(example["geometry_proposals"])
        logits = outputs["geometry_proposal_logits"][index, : len(proposals)]
        by_id = {
            str(row["proposal_id"]): position
            for position, row in enumerate(proposals)
        }
        by_type: dict[str, list[int]] = defaultdict(list)
        for position, proposal in enumerate(proposals):
            by_type[str(proposal["proposal_type"])].append(position)
        variant_losses = []
        for variant in variants:
            terms = []
            for proposal_id in variant["proposal_ids"]:
                positive = by_id[str(proposal_id)]
                proposal_type = str(proposals[positive]["proposal_type"])
                positions = by_type[proposal_type]
                slot_logits = logits[positions]
                target_index = positions.index(positive)
                terms.append(
                    nn.functional.cross_entropy(
                        slot_logits.unsqueeze(0),
                        torch.tensor(
                            [target_index],
                            dtype=torch.long,
                            device=logits.device,
                        ),
                    )
                )
            variant_losses.append(torch.stack(terms).sum())
        selection_losses.append(torch.stack(variant_losses).min())
        selection_weights.append(float(example["geometry_label_weight"]))
    if selection_losses:
        losses = torch.stack(selection_losses)
        weights = torch.tensor(
            selection_weights,
            dtype=losses.dtype,
            device=losses.device,
        )
        total = total + (losses * weights).sum() / weights.sum().clamp_min(1.0)
    if base_loss_weight > 0.0:
        if plan_weights is None:
            raise ValueError("joint geometry loss requires plan weights")
        total = total + base_loss_weight * _base_joint_loss(
            outputs,
            examples,
            plan_weights=plan_weights,
            safety_negative_weight=safety_negative_weight,
        )
    return total


def _base_joint_loss(
    outputs: Mapping[str, torch.Tensor],
    examples: Sequence[Mapping[str, Any]],
    *,
    plan_weights: torch.Tensor,
    safety_negative_weight: float,
) -> torch.Tensor:
    """Keep carrier plan, safety and complete Road-set heads trainable."""
    device = outputs["plan_type_logits"].device
    plan_targets = torch.tensor(
        [int(row["plan_type_index"]) for row in examples],
        dtype=torch.long,
        device=device,
    )
    plan_loss = nn.functional.cross_entropy(
        outputs["plan_type_logits"],
        plan_targets,
        weight=plan_weights,
    )
    safety_targets = torch.tensor(
        [float(bool(row["safety_target"])) for row in examples],
        dtype=torch.float32,
        device=device,
    )
    safety_losses = nn.functional.binary_cross_entropy_with_logits(
        outputs["safety_logits"],
        safety_targets,
        reduction="none",
    )
    safety_weights = torch.where(
        safety_targets > 0.5,
        torch.ones_like(safety_targets),
        torch.full_like(safety_targets, safety_negative_weight),
    )
    safety_loss = (safety_losses * safety_weights).mean()
    supervised_indices = [
        index
        for index, row in enumerate(examples)
        if bool(row["candidate_supervised"])
    ]
    if supervised_indices:
        cardinality_targets = torch.tensor(
            [
                min(
                    int(examples[index]["truth_cardinality"]),
                    CARDINALITY_COUNT - 1,
                )
                for index in supervised_indices
            ],
            dtype=torch.long,
            device=device,
        )
        cardinality_loss = nn.functional.cross_entropy(
            outputs["cardinality_logits"][supervised_indices],
            cardinality_targets,
        )
        selection_loss = torch.stack(
            [
                _structured_selection_loss(
                    outputs["candidate_logits"][index],
                    examples[index],
                    device=device,
                )
                for index in supervised_indices
            ]
        ).mean()
    else:
        zero = outputs["candidate_logits"].sum() * 0.0
        cardinality_loss = zero
        selection_loss = zero
    return (
        plan_loss
        + 0.8 * safety_loss
        + 0.7 * cardinality_loss
        + selection_loss
    )


def score_geometry_examples(
    model: TargetAAdvanceRightGeometryDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
    device: torch.device,
    base_safety_threshold: float,
    base_acceptance_threshold: float,
    geometry_acceptance_threshold: float,
) -> list[dict[str, Any]]:
    base_scores = score_advance_right_examples(
        model.base,
        examples,
        batch_size=batch_size,
        device=device,
    )
    base_decoded = decode_advance_right_scores(
        base_scores,
        safety_threshold=base_safety_threshold,
        acceptance_threshold=base_acceptance_threshold,
    )
    geometry_scores: dict[tuple[str, str], dict[str, Any]] = {}
    model.eval()
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            source = list(examples[start : start + batch_size])
            batch = collate_geometry_batch(source, device=device)
            outputs = model(
                **{key: value for key, value in batch.items() if key != "examples"}
            )
            probabilities = torch.sigmoid(
                outputs["geometry_proposal_logits"]
            ).cpu()
            safety = torch.sigmoid(outputs["geometry_safety_logits"]).cpu()
            for index, example in enumerate(source):
                count = len(example["geometry_proposals"])
                geometry_scores[
                    (str(example["case_key"]), str(example["object_id"]))
                ] = {
                    "geometry_proposal_probabilities": [
                        float(value) for value in probabilities[index, :count]
                    ],
                    "geometry_safety_probability": float(safety[index]),
                }
    result = []
    examples_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in examples
    }
    for base in base_decoded:
        key = (str(base["case_key"]), str(base["object_id"]))
        example = examples_by_key[key]
        scored = geometry_scores[key]
        result.append(
            decode_geometry_score(
                base,
                example,
                scored,
                geometry_acceptance_threshold=(
                    geometry_acceptance_threshold
                ),
            )
        )
    return result


def decode_geometry_score(
    base: Mapping[str, Any],
    example: Mapping[str, Any],
    scored: Mapping[str, Any],
    *,
    geometry_acceptance_threshold: float,
) -> dict[str, Any]:
    proposals = list(example["geometry_proposals"])
    probabilities = [
        float(value)
        for value in scored["geometry_proposal_probabilities"]
    ]
    selected_roads = set(
        str(value) for value in base["raw_selected_candidate_road_ids"]
    )
    required_types = _required_proposal_types(base, example)
    selected = []
    missing = []
    for proposal_type in required_types:
        choices = [
            (index, row)
            for index, row in enumerate(proposals)
            if str(row["proposal_type"]) == proposal_type
            and _proposal_candidate_road(row) in selected_roads
        ]
        if not choices:
            missing.append(proposal_type)
            continue
        index, row = max(
            choices,
            key=lambda value: (
                probabilities[value[0]],
                str(value[1]["proposal_id"]),
            ),
        )
        selected.append(
            {
                "proposal_id": str(row["proposal_id"]),
                "proposal_type": proposal_type,
                "probability": probabilities[index],
                "operation": str(row.get("operation") or "SPLICE"),
                "selected_rcsd_road_id": str(
                    row.get("selected_rcsd_road_id")
                    or row.get("rcsd_road_id")
                    or ""
                ),
                "selected_endpoint_index": row.get(
                    "selected_endpoint_index"
                ),
                "target_ordinary_road_id": str(
                    row.get("target_ordinary_road_id") or ""
                ),
                "target_fraction": row.get("target_fraction"),
                "parent_piece": row.get("parent_piece"),
                "swsd_road_id": str(row.get("swsd_road_id") or ""),
                "rcsd_fraction": row.get("rcsd_fraction"),
                "swsd_fraction": row.get("swsd_fraction"),
                "gap_m": float(row["gap_m"]),
            }
        )
    selected_ids = sorted(row["proposal_id"] for row in selected)
    acceptable = [
        sorted(str(value) for value in row["proposal_ids"])
        for row in example["acceptable_geometry_variants"]
        if bool(row["reachable"])
    ]
    truth_plan_type = str(example["truth_plan_type"])
    predicted_plan_type = str(base["predicted_plan_type"])
    if truth_plan_type == "SWSD_ONLY" and predicted_plan_type == "SWSD_ONLY":
        geometry_exact = not selected_ids and not missing
    elif truth_plan_type in {"RCSD_ONLY", "MIXED_SPLICE"}:
        geometry_exact = selected_ids in acceptable and not missing
    else:
        geometry_exact = predicted_plan_type == truth_plan_type and not selected_ids
    complete_exact = bool(base["raw_plan_exact"]) and geometry_exact
    safety_probability = float(scored["geometry_safety_probability"])
    selection_probability = min(
        [row["probability"] for row in selected] or [1.0]
    )
    geometry_confidence = min(safety_probability, selection_probability)
    geometry_pass = (
        not missing
        and geometry_confidence >= geometry_acceptance_threshold
    )
    automatic = bool(base["automatic_decision"] and geometry_pass)
    return {
        **base,
        "geometry_task_mask": bool(example["geometry_task_mask"]),
        "geometry_safety_target": bool(
            example["geometry_safety_target"]
        ),
        "geometry_safety_probability": safety_probability,
        "required_geometry_proposal_types": required_types,
        "selected_geometry_proposals": selected,
        "missing_geometry_proposal_types": missing,
        "geometry_proposal_exact": geometry_exact,
        "raw_complete_plan_geometry_exact": complete_exact,
        "geometry_selection_probability": selection_probability,
        "geometry_confidence": geometry_confidence,
        "geometry_acceptance_threshold": geometry_acceptance_threshold,
        "geometry_pass": geometry_pass,
        "base_automatic_decision": bool(base["automatic_decision"]),
        "automatic_decision": automatic,
        "effective_decision": (
            predicted_plan_type if automatic else "ABSTAIN"
        ),
        "unsafe_automatic": bool(automatic and not complete_exact),
        "positive_keep_swsd": bool(
            automatic and predicted_plan_type == "SWSD_ONLY"
        ),
    }


def choose_zero_error_geometry_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    thresholds = sorted(
        {
            0.0,
            1.000001,
            *[float(row["geometry_confidence"]) for row in rows],
        }
    )
    best_threshold = 1.000001
    best_count = -1
    for threshold in thresholds:
        accepted = [
            row
            for row in rows
            if bool(row["base_automatic_decision"])
            and not row["missing_geometry_proposal_types"]
            and float(row["geometry_confidence"]) >= threshold
        ]
        wrong = sum(
            not bool(row["raw_complete_plan_geometry_exact"])
            for row in accepted
        )
        if wrong == 0 and (
            len(accepted) > best_count
            or (
                len(accepted) == best_count
                and threshold < best_threshold
            )
        ):
            best_threshold = threshold
            best_count = len(accepted)
    return best_threshold


def geometry_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("geometry metrics require rows")
    automatic = [row for row in rows if bool(row["automatic_decision"])]
    action = [
        row
        for row in rows
        if str(row["truth_plan_type"]) in {"RCSD_ONLY", "MIXED_SPLICE"}
        and bool(row["geometry_task_mask"])
    ]
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counts = by_type[str(row["truth_plan_type"])]
        counts["support"] += 1
        counts["complete_exact"] += int(
            bool(row["raw_complete_plan_geometry_exact"])
        )
        counts["automatic"] += int(bool(row["automatic_decision"]))
        counts["unsafe"] += int(bool(row["unsafe_automatic"]))
    return {
        "count": len(rows),
        "geometry_action_supervised_count": len(action),
        "geometry_action_exact": (
            sum(bool(row["geometry_proposal_exact"]) for row in action)
            / len(action)
            if action
            else 0.0
        ),
        "raw_complete_plan_geometry_exact": sum(
            bool(row["raw_complete_plan_geometry_exact"]) for row in rows
        )
        / len(rows),
        "automatic_count": len(automatic),
        "automatic_coverage": len(automatic) / len(rows),
        "automatic_exact": (
            sum(
                bool(row["raw_complete_plan_geometry_exact"])
                for row in automatic
            )
            / len(automatic)
            if automatic
            else 0.0
        ),
        "unsafe_automatic_count": sum(
            bool(row["unsafe_automatic"]) for row in rows
        ),
        "positive_keep_swsd_count": sum(
            bool(row["positive_keep_swsd"]) for row in rows
        ),
        "fallback_count": len(rows) - len(automatic),
        "per_truth_plan_type": {
            plan_type: {
                "support": counts["support"],
                "complete_exact": (
                    counts["complete_exact"] / counts["support"]
                    if counts["support"]
                    else 0.0
                ),
                "automatic_count": counts["automatic"],
                "unsafe_automatic_count": counts["unsafe"],
            }
            for plan_type, counts in sorted(by_type.items())
        },
    }


def _fit_geometry_model(
    training: Sequence[Mapping[str, Any]],
    validation: Sequence[Mapping[str, Any]],
    *,
    base_checkpoint: Path,
    seed: int,
    batch_size: int,
    device: torch.device,
    max_epochs: int,
    patience: int,
    learning_rate: float,
    weight_decay: float,
    fine_tune_base: bool = False,
    base_loss_weight: float = 0.0,
) -> dict[str, Any]:
    model = _new_model(
        base_checkpoint,
        seed=seed,
        device=device,
        fine_tune_base=fine_tune_base,
    )
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    plan_weights = _plan_class_weights(training, device)
    safety_negative_weight = _safety_negative_weight(training)
    best_state = None
    best_loss = float("inf")
    best_epoch = 0
    stale = 0
    history = []
    for epoch in range(1, max_epochs + 1):
        train_loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            batch_size=batch_size,
            device=device,
            seed=seed * 1000 + epoch,
            base_loss_weight=base_loss_weight,
            plan_weights=plan_weights,
            safety_negative_weight=safety_negative_weight,
        )
        validation_loss = _evaluate_loss(
            model,
            validation,
            batch_size=batch_size,
            device=device,
            base_loss_weight=base_loss_weight,
            plan_weights=plan_weights,
            safety_negative_weight=safety_negative_weight,
        )
        history.append(
            {
                "epoch": epoch,
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
        if stale >= patience:
            break
    if best_state is None:
        raise RuntimeError("geometry training produced no checkpoint")
    model.load_state_dict(best_state)
    return {
        "model": model,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "history": history,
    }


def _fit_geometry_fixed_epochs(
    training: Sequence[Mapping[str, Any]],
    *,
    base_checkpoint: Path,
    seed: int,
    batch_size: int,
    device: torch.device,
    epoch_count: int,
    learning_rate: float,
    weight_decay: float,
    fine_tune_base: bool = False,
    base_loss_weight: float = 0.0,
) -> dict[str, Any]:
    model = _new_model(
        base_checkpoint,
        seed=seed,
        device=device,
        fine_tune_base=fine_tune_base,
    )
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    plan_weights = _plan_class_weights(training, device)
    safety_negative_weight = _safety_negative_weight(training)
    history = []
    for epoch in range(1, epoch_count + 1):
        loss = _train_epoch(
            model,
            training,
            optimizer=optimizer,
            batch_size=batch_size,
            device=device,
            seed=seed * 1000 + epoch,
            base_loss_weight=base_loss_weight,
            plan_weights=plan_weights,
            safety_negative_weight=safety_negative_weight,
        )
        history.append({"epoch": epoch, "train_loss": loss})
    return {"model": model, "history": history}


def _train_epoch(
    model: TargetAAdvanceRightGeometryDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    optimizer: torch.optim.Optimizer,
    batch_size: int,
    device: torch.device,
    seed: int,
    base_loss_weight: float = 0.0,
    plan_weights: torch.Tensor | None = None,
    safety_negative_weight: float = 1.0,
) -> float:
    model.train()
    if base_loss_weight <= 0.0:
        model.base.eval()
    order = list(range(len(examples)))
    random.Random(seed).shuffle(order)
    total = 0.0
    count = 0
    for start in range(0, len(order), batch_size):
        source = [examples[index] for index in order[start : start + batch_size]]
        batch = collate_geometry_batch(source, device=device)
        optimizer.zero_grad(set_to_none=True)
        outputs = model(
            **{key: value for key, value in batch.items() if key != "examples"}
        )
        loss = geometry_loss(
            outputs,
            batch,
            base_loss_weight=base_loss_weight,
            plan_weights=plan_weights,
            safety_negative_weight=safety_negative_weight,
        )
        loss.backward()
        nn.utils.clip_grad_norm_(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            5.0,
        )
        optimizer.step()
        total += float(loss.detach().cpu()) * len(source)
        count += len(source)
    return total / max(count, 1)


def _evaluate_loss(
    model: TargetAAdvanceRightGeometryDecoder,
    examples: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
    device: torch.device,
    base_loss_weight: float = 0.0,
    plan_weights: torch.Tensor | None = None,
    safety_negative_weight: float = 1.0,
) -> float:
    model.eval()
    total = 0.0
    count = 0
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            source = list(examples[start : start + batch_size])
            batch = collate_geometry_batch(source, device=device)
            outputs = model(
                **{key: value for key, value in batch.items() if key != "examples"}
            )
            loss = geometry_loss(
                outputs,
                batch,
                base_loss_weight=base_loss_weight,
                plan_weights=plan_weights,
                safety_negative_weight=safety_negative_weight,
            )
            total += float(loss.cpu()) * len(source)
            count += len(source)
    return total / max(count, 1)


def _new_model(
    base_checkpoint: Path,
    *,
    seed: int,
    device: torch.device,
    fine_tune_base: bool = False,
) -> TargetAAdvanceRightGeometryDecoder:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    checkpoint = torch.load(
        base_checkpoint,
        map_location="cpu",
        weights_only=False,
    )
    model = TargetAAdvanceRightGeometryDecoder()
    model.load_base_state_dict(checkpoint["model_state_dict"])
    if not fine_tune_base:
        model.freeze_base()
    return model.to(device)


def _required_proposal_types(
    base: Mapping[str, Any],
    example: Mapping[str, Any],
) -> list[str]:
    plan_type = str(base["predicted_plan_type"])
    if plan_type == "RCSD_ONLY":
        return ["SOURCE_ATTACHMENT", "TARGET_ATTACHMENT"]
    if plan_type == "MIXED_SPLICE":
        side = (
            "SOURCE_ATTACHMENT"
            if str(example["source_context"]["data_source"]) == "RCSD"
            else "TARGET_ATTACHMENT"
        )
        return [side, "MIDDLE_SPLICE"]
    return []


def _proposal_candidate_road(row: Mapping[str, Any]) -> str:
    return str(
        row.get("selected_rcsd_road_id")
        or row.get("rcsd_road_id")
        or ""
    )


def _proposal_features(row: Mapping[str, Any]) -> list[float]:
    one_hot = [0.0, 0.0, 0.0]
    one_hot[PROPOSAL_TYPE_INDEX[str(row["proposal_type"])]] = 1.0
    values = [
        *[float(value) for value in row["candidate_feature_values"]],
        *[float(value) for value in row["target_member_feature_values"]],
        *[float(value) for value in row["geometry_feature_values"]],
        *one_hot,
    ]
    return values


def _assert_case_disjoint(
    training: Sequence[Mapping[str, Any]],
    validation: Sequence[Mapping[str, Any]],
) -> None:
    if {row["case_key"] for row in training} & {
        row["case_key"] for row in validation
    }:
        raise ValueError("geometry Case leaked across a fold")


def _save_checkpoint(
    path: Path,
    *,
    model: TargetAAdvanceRightGeometryDecoder,
    base_checkpoint: Path,
    fold: int,
    inner_fold: int,
    seed: int,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ADVANCE_RIGHT_GEOMETRY_STRUCTURED_DECODER",
            "outer_fold": fold,
            "inner_validation_fold": inner_fold,
            "seed": seed,
            "epoch_count": epoch_count,
            "parameter_count": parameter_count(model),
            "trainable_geometry_parameter_count": trainable_parameter_count(
                model
            ),
            "base_checkpoint": _input_record(base_checkpoint),
            "model_state_dict": {
                key: value.detach().cpu()
                for key, value in sorted(model.state_dict().items())
            },
        },
        path,
    )


def _resolve_device(requested: str) -> torch.device:
    normalized = requested.casefold()
    if normalized == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but unavailable")
        return torch.device("cuda")
    if normalized == "cpu":
        return torch.device("cpu")
    raise ValueError(f"unsupported geometry device: {requested}")


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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "choose_zero_error_geometry_threshold",
    "collate_geometry_batch",
    "decode_geometry_score",
    "geometry_loss",
    "geometry_metrics",
    "read_geometry_examples",
    "run_advance_right_geometry_strict_nested_oof",
]
