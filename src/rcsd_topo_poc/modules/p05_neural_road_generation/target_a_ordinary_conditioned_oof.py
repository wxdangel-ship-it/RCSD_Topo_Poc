from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    sha256_file,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_nested_oof import (
    _inner_fold_for_outer,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    FallbackScope,
    TARGET_A_SCHEMA_VERSION,
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
    model_contract,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_data import (
    OrdinaryAnchorConditionedExample,
    collate_oof_anchor_conditioned_ordinary_batch,
    conditioned_ordinary_batches,
    read_oof_anchor_conditioned_ordinary_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    move_training_batch,
    train_target_a_fixed_epochs,
    train_target_a_stage,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def run_oof_anchor_conditioned_ordinary_strict_nested(
    *,
    candidate_store_root: Path,
    preflight_root: Path,
    anchor_store_root: Path,
    anchor_oof_root: Path,
    output_root: Path,
    run_id: str,
    config: TargetAConfig,
    seed: int,
    batch_size: int,
    requested_device: str = "cuda",
    balance_decision_classes: bool = False,
    balance_cases: bool = False,
    include_anchor_plan_relations: bool = False,
    include_plan_member_relations: bool = False,
    include_plan_arm_relations: bool = False,
) -> Path:
    """Evaluate ordinary complete Road plans under Scheme A anchor gating."""
    started = time.perf_counter()
    config.validate()
    if not config.ordinary_oof_anchor_condition_encoder:
        raise ValueError("ordinary OOF anchor conditioning must be enabled")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(
        strict=True
    )
    preflight = normalize_runtime_path(preflight_root).resolve(strict=True)
    anchor_store = normalize_runtime_path(anchor_store_root).resolve(
        strict=True
    )
    anchor_oof = normalize_runtime_path(anchor_oof_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    examples = read_oof_anchor_conditioned_ordinary_examples(
        candidate_store_root=candidate_root,
        preflight_root=preflight,
        anchor_store_root=anchor_store,
        anchor_oof_root=anchor_oof,
        include_anchor_plan_relations=include_anchor_plan_relations,
        include_plan_member_relations=include_plan_member_relations,
        include_plan_arm_relations=include_plan_arm_relations,
    )
    folds = sorted({example.fold for example in examples})
    if len(folds) < 3:
        raise ValueError("strict nested ordinary OOF requires three folds")
    device = _resolve_device(requested_device)
    predictions: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for outer_fold in folds:
        inner_fold = _inner_fold_for_outer(folds, outer_fold)
        (
            inner_training,
            inner_validation,
            outer_training,
            outer_validation,
        ) = _strict_nested_split(
            examples,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
        )
        inner_decision_weights = (
            _balanced_decision_weights(inner_training)
            if balance_decision_classes
            else None
        )
        inner_training_case_weights = (
            _balanced_case_weights(inner_training)
            if balance_cases
            else None
        )
        inner_validation_case_weights = (
            _balanced_case_weights(inner_validation)
            if balance_cases
            else None
        )
        tuning_result = train_target_a_stage(
            conditioned_ordinary_batches(
                inner_training,
                batch_size=batch_size,
                decision_class_weights=inner_decision_weights,
                case_weights=inner_training_case_weights,
            ),
            conditioned_ordinary_batches(
                inner_validation,
                batch_size=batch_size,
                decision_class_weights=inner_decision_weights,
                case_weights=inner_validation_case_weights,
            ),
            config=config,
            seed=seed + outer_fold * 100 + 17,
            device=device,
        )
        outer_decision_weights = (
            _balanced_decision_weights(outer_training)
            if balance_decision_classes
            else None
        )
        outer_training_case_weights = (
            _balanced_case_weights(outer_training)
            if balance_cases
            else None
        )
        final_result = train_target_a_fixed_epochs(
            conditioned_ordinary_batches(
                outer_training,
                batch_size=batch_size,
                decision_class_weights=outer_decision_weights,
                case_weights=outer_training_case_weights,
            ),
            config=config,
            seed=seed + outer_fold * 100 + 53,
            device=device,
            epoch_count=tuning_result.best_epoch,
        )
        fold_predictions = _predict_conditioned_plans(
            final_result.model,
            outer_validation,
            batch_size=batch_size,
            device=device,
        )
        for row in fold_predictions:
            row.update(
                {
                    "outer_fold": outer_fold,
                    "inner_validation_fold": inner_fold,
                }
            )
        predictions.extend(fold_predictions)

        tuning_checkpoint = root / (
            f"fold_{outer_fold}_inner_checkpoint.pt"
        )
        final_checkpoint = root / f"fold_{outer_fold}_checkpoint.pt"
        _save_checkpoint(
            tuning_checkpoint,
            model=tuning_result.model,
            stage="ORDINARY_OOF_ANCHOR_CONDITIONED_STRICT_NESTED_INNER",
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 17,
            config=config,
            epoch_count=tuning_result.best_epoch,
        )
        _save_checkpoint(
            final_checkpoint,
            model=final_result.model,
            stage="ORDINARY_OOF_ANCHOR_CONDITIONED_STRICT_NESTED_OUTER",
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            seed=seed + outer_fold * 100 + 53,
            config=config,
            epoch_count=final_result.epoch_count,
        )
        fold_row = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "inner_train_example_count": len(inner_training),
            "inner_validation_example_count": len(inner_validation),
            "outer_train_example_count": len(outer_training),
            "outer_validation_example_count": len(outer_validation),
            "outer_fallback_required_count": sum(
                example.fallback_required
                for example in outer_validation
            ),
            "inner_decision_class_weights": inner_decision_weights,
            "outer_decision_class_weights": outer_decision_weights,
            "inner_train_case_weight_range": _weight_range(
                inner_training_case_weights
            ),
            "inner_validation_case_weight_range": _weight_range(
                inner_validation_case_weights
            ),
            "outer_train_case_weight_range": _weight_range(
                outer_training_case_weights
            ),
            "selected_epoch": tuning_result.best_epoch,
            "inner_best_validation_loss": (
                tuning_result.best_validation_loss
            ),
            "inner_wall_seconds": tuning_result.wall_seconds,
            "outer_fit_wall_seconds": final_result.wall_seconds,
            "inner_state_signature": tuning_result.state_signature,
            "outer_state_signature": final_result.state_signature,
            "inner_checkpoint": str(tuning_checkpoint.resolve()),
            "inner_checkpoint_sha256": sha256_file(tuning_checkpoint),
            "outer_checkpoint": str(final_checkpoint.resolve()),
            "outer_checkpoint_sha256": sha256_file(final_checkpoint),
            "metrics": _conditioned_plan_metrics(fold_predictions),
            "inner_history": tuning_result.history,
            "outer_history": final_result.history,
        }
        fold_rows.append(fold_row)
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_row)

    predictions.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    coverage_ok = (
        len(predictions) == len(examples)
        and {row["sample_id"] for row in predictions}
        == {example.sample_id for example in examples}
    )
    unsafe_anchor_bypass_count = sum(
        bool(
            row["anchor_gate_fallback_required"]
            and row["effective_decision"] != "ABSTAIN"
        )
        for row in predictions
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_OOF_ANCHOR_CONDITIONED_STRICT_NESTED",
        "run_id": run_id,
        "seed": seed,
        "requested_device": requested_device,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "config": asdict(config),
        "balance_decision_classes": balance_decision_classes,
        "balance_cases": balance_cases,
        "include_anchor_plan_relations": include_anchor_plan_relations,
        "include_plan_member_relations": include_plan_member_relations,
        "include_plan_arm_relations": include_plan_arm_relations,
        "model_contract": model_contract(TargetAJointNetwork(config)),
        "candidate_store_manifest_sha256": sha256_file(
            candidate_root / "manifest.json"
        ),
        "preflight_summary_sha256": sha256_file(
            preflight / "summary.json"
        ),
        "anchor_store_manifest_sha256": sha256_file(
            anchor_store / "manifest.json"
        ),
        "anchor_oof_summary_sha256": sha256_file(
            anchor_oof / "summary.json"
        ),
        "example_count": len(examples),
        "conditioned_label_reachable_count": sum(
            example.conditioned_label_reachable
            for example in examples
        ),
        "anchor_gate_fallback_required_count": sum(
            example.fallback_required for example in examples
        ),
        "all_required_anchors_resolved_count": sum(
            example.all_required_anchors_resolved
            for example in examples
        ),
        "all_required_anchors_success_count": sum(
            example.all_required_anchors_success
            for example in examples
        ),
        "missing_anchor_condition_count": sum(
            bool(example.missing_anchor_ids) for example in examples
        ),
        "fold_count": len(folds),
        "folds": fold_rows,
        "oof_metrics": _conditioned_plan_metrics(predictions),
        "oof_coverage_exact": coverage_ok,
        "unsafe_anchor_bypass_count": unsafe_anchor_bypass_count,
        "terminal_feature_count": 0,
        "raw_id_embedding_count": 0,
        "anchor_condition_contract": (
            "OOF predicted anchor status, gate probability, and selected "
            "candidate inference features only; no anchor truth or terminal "
            "T03-T06 state enters ordinary inference inputs. Optional "
            "candidate relations compare selected OOF RCSD Node/Road members "
            "with each plan graph and discard the raw identifiers."
        ),
        "scheme_a_gate_contract": (
            "Only USE_RCSD and the explicit T06 main-RCSD/attached-SWSD "
            "candidate require every required anchor to predict SUCCESS. "
            "KEEP_SWSD and ABSTAIN remain enabled."
        ),
        "ordinary_decision_class_balance": (
            (
                "Inverse weighted class mass is derived from each inner/outer "
                "training partition only and applies only to ordinary plan loss."
            )
            if balance_decision_classes
            else "disabled"
        ),
        "ordinary_case_balance": (
            (
                "Each training or inner-validation partition gives every "
                "Case equal total loss mass while retaining the formal "
                "per-example label confidence weight."
            )
            if balance_cases
            else "disabled"
        ),
        "release_gate": "NO_GO",
        "scope_statement": (
            "This is an OOF diagnostic for ordinary Segment complete Road "
            "plans. Anchor-gated fallback rows are safety outcomes, not "
            "positive KEEP_SWSD decisions or full RoadGraph exact."
        ),
        "wall_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    if not coverage_ok:
        raise RuntimeError(f"conditioned ordinary OOF coverage differs: {root}")
    if unsafe_anchor_bypass_count:
        raise RuntimeError(f"Scheme A anchor gate was bypassed: {root}")
    return root


def _strict_nested_split(
    examples: Sequence[OrdinaryAnchorConditionedExample],
    *,
    outer_fold: int,
    inner_fold: int,
) -> tuple[
    list[OrdinaryAnchorConditionedExample],
    list[OrdinaryAnchorConditionedExample],
    list[OrdinaryAnchorConditionedExample],
    list[OrdinaryAnchorConditionedExample],
]:
    if outer_fold == inner_fold:
        raise ValueError("outer and inner validation folds must differ")
    inner_training = [
        example
        for example in examples
        if example.fold not in {outer_fold, inner_fold}
    ]
    inner_validation = [
        example for example in examples if example.fold == inner_fold
    ]
    outer_training = [
        example for example in examples if example.fold != outer_fold
    ]
    outer_validation = [
        example for example in examples if example.fold == outer_fold
    ]
    if not all(
        (
            inner_training,
            inner_validation,
            outer_training,
            outer_validation,
        )
    ):
        raise ValueError("strict nested ordinary split has an empty partition")
    if {row.case_key for row in outer_training} & {
        row.case_key for row in outer_validation
    }:
        raise AssertionError("outer ordinary Case leaked into training")
    if {row.case_key for row in inner_training} & {
        row.case_key for row in inner_validation
    }:
        raise AssertionError("inner ordinary Case leaked into training")
    return (
        inner_training,
        inner_validation,
        outer_training,
        outer_validation,
    )


def _balanced_decision_weights(
    examples: Sequence[OrdinaryAnchorConditionedExample],
) -> dict[str, float]:
    class_mass: dict[str, float] = defaultdict(float)
    for example in examples:
        if example.conditioned_label_reachable:
            class_mass[example.base.preferred_decision] += (
                example.base.sample_weight
            )
    if not class_mass or min(class_mass.values()) <= 0:
        raise ValueError("ordinary decision class mass is invalid")
    total = sum(class_mass.values())
    class_count = len(class_mass)
    return {
        decision: total / (class_count * mass)
        for decision, mass in sorted(class_mass.items())
    }


def _balanced_case_weights(
    examples: Sequence[OrdinaryAnchorConditionedExample],
) -> dict[str, float]:
    case_counts: dict[str, int] = defaultdict(int)
    for example in examples:
        case_counts[example.case_key] += 1
    if not case_counts or min(case_counts.values()) <= 0:
        raise ValueError("ordinary Case counts are invalid")
    example_count = sum(case_counts.values())
    case_count = len(case_counts)
    return {
        case_key: example_count / (case_count * count)
        for case_key, count in sorted(case_counts.items())
    }


def _weight_range(
    weights: Mapping[str, float] | None,
) -> list[float] | None:
    if weights is None:
        return None
    return [min(weights.values()), max(weights.values())]


def _predict_conditioned_plans(
    model: TargetAJointNetwork,
    examples: Sequence[OrdinaryAnchorConditionedExample],
    *,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    rows: list[dict[str, Any]] = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            source_examples = examples[start : start + batch_size]
            batch = move_training_batch(
                collate_oof_anchor_conditioned_ordinary_batch(
                    source_examples
                ),
                device,
            )
            outputs = model(batch.tensors)
            probabilities = torch.softmax(
                outputs["ordinary_plan_logits"][:, 0, :],
                dim=-1,
            ).detach().cpu()
            clue_probabilities = torch.softmax(
                outputs["clue_logits"][:, 0, :],
                dim=-1,
            ).detach().cpu()
            fallback_probabilities = torch.softmax(
                outputs["fallback_scope_logits"][:, 0, :],
                dim=-1,
            ).detach().cpu()
            predicted_indices = probabilities.argmax(dim=-1).tolist()
            predicted_clues = clue_probabilities.argmax(dim=-1).tolist()
            predicted_fallback_scopes = (
                fallback_probabilities.argmax(dim=-1).tolist()
            )
            for (
                example,
                predicted_index,
                predicted_clue,
                predicted_fallback_scope,
                probability,
                clue_probability,
                fallback_probability,
            ) in zip(
                source_examples,
                predicted_indices,
                predicted_clues,
                predicted_fallback_scopes,
                probabilities.tolist(),
                clue_probabilities.tolist(),
                fallback_probabilities.tolist(),
                strict=True,
            ):
                base = example.base
                acceptable = set(
                    example.conditioned_acceptable_indices
                )
                raw_decision = base.candidate_decisions[predicted_index]
                anchor_forced_fallback = example.fallback_required
                predicted_scope = list(FallbackScope)[
                    predicted_fallback_scope
                ].value
                release_scope = (
                    predicted_scope
                    if predicted_scope != FallbackScope.NONE.value
                    else (
                        FallbackScope.SEGMENT.value
                        if anchor_forced_fallback
                        else FallbackScope.NONE.value
                    )
                )
                release_fallback_required = (
                    release_scope != FallbackScope.NONE.value
                )
                effective_decision = (
                    "ABSTAIN"
                    if release_fallback_required
                    else raw_decision
                )
                acceptable_decisions = sorted(
                    {
                        base.candidate_decisions[index]
                        for index in acceptable
                    }
                )
                rows.append(
                    {
                        "sample_id": base.sample_id,
                        "case_key": base.case_key,
                        "segment_id": base.segment_id,
                        "fold": base.fold,
                        "required_anchor_count": len(
                            base.required_anchor_ids
                        ),
                        "anchor_resolved_count": (
                            example.anchor_resolved_count
                        ),
                        "anchor_success_count": (
                            example.anchor_success_count
                        ),
                        "all_required_anchors_resolved": (
                            example.all_required_anchors_resolved
                        ),
                        "all_required_anchors_success": (
                            example.all_required_anchors_success
                        ),
                        "missing_anchor_ids": list(
                            example.missing_anchor_ids
                        ),
                        "conditioned_label_reachable": (
                            example.conditioned_label_reachable
                        ),
                        "carrier_label_evaluable": bool(
                            base.carrier_task_mask
                            and not anchor_forced_fallback
                            and example.conditioned_label_reachable
                        ),
                        "anchor_gate_fallback_required": (
                            anchor_forced_fallback
                        ),
                        "raw_predicted_plan_id": (
                            base.candidate_ids[predicted_index]
                        ),
                        "raw_predicted_decision": raw_decision,
                        "raw_predicted_probability": float(
                            probability[predicted_index]
                        ),
                        "predicted_clue": bool(predicted_clue),
                        "predicted_clue_probability": float(
                            clue_probability[predicted_clue]
                        ),
                        "clue_label_evaluable": base.clue_task_mask,
                        "clue_label": (
                            bool(base.clue_label)
                            if base.clue_task_mask
                            else None
                        ),
                        "predicted_fallback_scope": predicted_scope,
                        "predicted_fallback_scope_probability": float(
                            fallback_probability[
                                predicted_fallback_scope
                            ]
                        ),
                        "fallback_none_probability": float(
                            fallback_probability[
                                list(FallbackScope).index(
                                    FallbackScope.NONE
                                )
                            ]
                        ),
                        "fallback_segment_probability": float(
                            fallback_probability[
                                list(FallbackScope).index(
                                    FallbackScope.SEGMENT
                                )
                            ]
                        ),
                        "fallback_junction_probability": float(
                            fallback_probability[
                                list(FallbackScope).index(
                                    FallbackScope.JUNCTION
                                )
                            ]
                        ),
                        "release_fallback_scope": release_scope,
                        "release_fallback_required": (
                            release_fallback_required
                        ),
                        "fallback_scope_label_evaluable": (
                            base.fallback_scope_task_mask
                        ),
                        "fallback_scope_label": (
                            list(FallbackScope)[
                                base.fallback_scope_label
                            ].value
                            if base.fallback_scope_task_mask
                            else None
                        ),
                        "effective_decision": effective_decision,
                        "automatic_decision": bool(
                            not release_fallback_required
                            and raw_decision != "ABSTAIN"
                        ),
                        "enabled_plan_ids": [
                            candidate_id
                            for candidate_id, enabled in zip(
                                base.candidate_ids,
                                example.enabled_candidate_mask,
                                strict=True,
                            )
                            if enabled
                        ],
                        "acceptable_plan_ids": [
                            base.candidate_ids[index]
                            for index in (
                                example.conditioned_acceptable_indices
                            )
                        ],
                        "acceptable_decisions": acceptable_decisions,
                        "preferred_plan_id": (
                            base.candidate_ids[
                                example.conditioned_preferred_index
                            ]
                            if example.conditioned_preferred_index >= 0
                            else ""
                        ),
                        "preferred_decision": base.preferred_decision,
                        "acceptable_exact": (
                            predicted_index in acceptable
                            if (
                                base.carrier_task_mask
                                and not anchor_forced_fallback
                                and example.conditioned_label_reachable
                            )
                            else None
                        ),
                        "preferred_exact": (
                            predicted_index
                            == example.conditioned_preferred_index
                            if example.conditioned_preferred_index >= 0
                            else None
                        ),
                        "fallback_safe_success": (
                            release_fallback_required
                        ),
                    }
                )
    return rows


def _conditioned_plan_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not rows:
        raise ValueError("conditioned plan metrics require prediction rows")
    reachable = [
        row for row in rows if bool(row["conditioned_label_reachable"])
    ]
    carrier_evaluable = [
        row for row in rows if bool(row["carrier_label_evaluable"])
    ]
    fallback_required = [
        row for row in rows if bool(row["anchor_gate_fallback_required"])
    ]
    release_fallback = [
        row for row in rows if bool(row["release_fallback_required"])
    ]
    automatic = [
        row for row in rows if bool(row["automatic_decision"])
    ]
    automatic_evaluable = [
        row for row in automatic if bool(row["carrier_label_evaluable"])
    ]
    preferred_rows = [
        row
        for row in carrier_evaluable
        if row.get("preferred_exact") is not None
    ]
    clue_evaluable = [
        row for row in rows if bool(row["clue_label_evaluable"])
    ]
    fallback_scope_evaluable = [
        row
        for row in rows
        if bool(row["fallback_scope_label_evaluable"])
    ]
    per_preferred: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        decision = str(row.get("preferred_decision") or "")
        counts = per_preferred[decision]
        counts["support"] += 1
        counts["fallback_required"] += int(
            bool(row["anchor_gate_fallback_required"])
        )
        counts["automatic"] += int(bool(row["automatic_decision"]))
        if row.get("acceptable_exact") is not None:
            counts["reachable"] += 1
            counts["acceptable_exact"] += int(
                bool(row["acceptable_exact"])
            )
    return {
        "count": len(rows),
        "conditioned_label_reachable_count": len(reachable),
        "carrier_label_evaluable_count": len(carrier_evaluable),
        "anchor_gate_fallback_required_count": len(fallback_required),
        "release_fallback_count": len(release_fallback),
        "anchor_gate_fallback_safe_rate": (
            sum(bool(row["fallback_safe_success"]) for row in fallback_required)
            / len(fallback_required)
            if fallback_required
            else 1.0
        ),
        "reachable_complete_plan_acceptable_exact": (
            sum(bool(row["acceptable_exact"]) for row in carrier_evaluable)
            / len(carrier_evaluable)
            if carrier_evaluable
            else 0.0
        ),
        "reachable_preferred_plan_exact": (
            sum(bool(row["preferred_exact"]) for row in preferred_rows)
            / len(preferred_rows)
            if preferred_rows
            else 0.0
        ),
        "automatic_decision_count": len(automatic),
        "automatic_acceptance_coverage": len(automatic) / len(rows),
        "automatic_carrier_evaluable_count": len(automatic_evaluable),
        "automatic_complete_plan_acceptable_exact": (
            sum(bool(row["acceptable_exact"]) for row in automatic_evaluable)
            / len(automatic_evaluable)
            if automatic_evaluable
            else 0.0
        ),
        "clue_evaluable_count": len(clue_evaluable),
        "clue_accuracy": (
            sum(
                bool(row["predicted_clue"]) == bool(row["clue_label"])
                for row in clue_evaluable
            )
            / len(clue_evaluable)
            if clue_evaluable
            else 0.0
        ),
        "fallback_scope_evaluable_count": len(fallback_scope_evaluable),
        "fallback_scope_exact": (
            sum(
                row["release_fallback_scope"]
                == row["fallback_scope_label"]
                for row in fallback_scope_evaluable
            )
            / len(fallback_scope_evaluable)
            if fallback_scope_evaluable
            else 0.0
        ),
        "unsafe_scope_bypass_count": sum(
            bool(
                row["fallback_scope_label_evaluable"]
                and row["fallback_scope_label"] != FallbackScope.NONE.value
                and row["automatic_decision"]
            )
            for row in rows
        ),
        "positive_keep_decision_count": sum(
            bool(
                row["automatic_decision"]
                and row["raw_predicted_decision"] == "KEEP_SWSD"
            )
            for row in rows
        ),
        "abstain_prediction_count": sum(
            row["raw_predicted_decision"] == "ABSTAIN"
            for row in reachable
        ),
        "unsafe_anchor_bypass_count": sum(
            bool(
                row["anchor_gate_fallback_required"]
                and row["effective_decision"] != "ABSTAIN"
            )
            for row in rows
        ),
        "per_preferred_decision": {
            decision: {
                "support": counts["support"],
                "conditioned_label_reachable_count": counts["reachable"],
                "anchor_gate_fallback_required_count": (
                    counts["fallback_required"]
                ),
                "automatic_decision_count": counts["automatic"],
                "reachable_complete_plan_acceptable_exact": (
                    counts["acceptable_exact"] / counts["reachable"]
                    if counts["reachable"]
                    else 0.0
                ),
            }
            for decision, counts in sorted(per_preferred.items())
        },
    }


def _save_checkpoint(
    path: Path,
    *,
    model: TargetAJointNetwork,
    stage: str,
    outer_fold: int,
    inner_fold: int,
    seed: int,
    config: TargetAConfig,
    epoch_count: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": stage,
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "seed": seed,
            "epoch_count": epoch_count,
            "config": asdict(config),
            "model_contract": model_contract(model),
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
            raise RuntimeError("CUDA was requested but is not available")
        return torch.device("cuda")
    if normalized == "cpu":
        return torch.device("cpu")
    raise ValueError(f"unsupported Target A device: {requested}")


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


__all__ = ["run_oof_anchor_conditioned_ordinary_strict_nested"]
