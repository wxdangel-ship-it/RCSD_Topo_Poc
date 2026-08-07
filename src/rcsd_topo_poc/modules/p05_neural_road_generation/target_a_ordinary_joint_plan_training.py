from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_plan_data import (
    collate_joint_plan_batch,
    merge_current_labels_into_base_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_plan_network import (
    TargetAOrdinaryJointPlanNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_proposals import (
    OrdinaryPlanProposalExample,
    StaticOrdinaryPlan,
    build_ordinary_plan_proposal_example,
    read_static_ordinary_plans,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_reranker import (
    _assert_case_disjoint,
    _base_acceptance_threshold,
    _inner_validation_fold,
    _plan_metrics,
    _read_base_training_examples,
    acceptable_plan_nll,
    choose_zero_error_plan_threshold,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_members import (
    ROAD_BUSINESS_ROLE_LABELS,
    ROAD_OWNERSHIP_LABELS,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    OrdinaryRoadSetExample,
    OrdinaryRoadSetTrainingConfig,
    _loss_rows,
    read_ordinary_road_set_examples,
    score_ordinary_road_set_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_set_full_inference import (
    _load_checkpoint,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


@dataclass(frozen=True)
class OrdinaryJointPlanTrainingConfig:
    plan_hidden_dim: int = 128
    plan_feedforward_dim: int = 192
    dropout: float = 0.1
    batch_size: int = 16
    max_epochs: int = 30
    patience: int = 5
    learning_rate: float = 1e-4
    weight_decay: float = 2e-4
    plan_loss_weight: float = 1.0
    validity_loss_weight: float = 1.0
    base_loss_weight: float = 0.5
    maximum_prefix_cardinality: int = 67
    torch_num_threads: int = 4
    outer_folds: tuple[int, ...] = ()

    def validate(self) -> None:
        if min(
            self.plan_hidden_dim,
            self.plan_feedforward_dim,
            self.batch_size,
            self.max_epochs,
            self.patience,
            self.maximum_prefix_cardinality,
            self.torch_num_threads,
        ) < 1:
            raise ValueError("ordinary joint plan training config is invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("ordinary joint plan dropout is invalid")
        if self.learning_rate <= 0.0 or self.weight_decay < 0.0:
            raise ValueError("ordinary joint plan optimizer is invalid")
        if min(
            self.plan_loss_weight,
            self.validity_loss_weight,
            self.base_loss_weight,
        ) < 0.0 or (
            self.plan_loss_weight
            + self.validity_loss_weight
            + self.base_loss_weight
            <= 0.0
        ):
            raise ValueError("ordinary joint plan losses are disabled")
        if len(set(self.outer_folds)) != len(self.outer_folds):
            raise ValueError("ordinary joint plan outer folds repeat")


def run_ordinary_joint_plan_strict_nested_oof(
    *,
    member_store_root: Path,
    static_plan_store_root: Path,
    base_trained_root: Path,
    output_root: Path,
    seed: int,
    config: OrdinaryJointPlanTrainingConfig = (
        OrdinaryJointPlanTrainingConfig()
    ),
    requested_device: str = "cuda",
) -> Path:
    """Fine-tune the shared Road encoder with a complete-plan loss."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    member_store = normalize_runtime_path(member_store_root).resolve(
        strict=True
    )
    plan_store = normalize_runtime_path(static_plan_store_root).resolve(
        strict=True
    )
    trained = normalize_runtime_path(base_trained_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    current, read_summary = read_ordinary_road_set_examples(member_store)
    base, base_store = _read_base_training_examples(trained)
    examples = merge_current_labels_into_base_features(current, base)
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("ordinary joint plan needs at least three folds")
    selected_folds = (
        list(config.outer_folds) if config.outer_folds else folds
    )
    if not set(selected_folds) <= set(folds):
        raise ValueError("ordinary joint plan outer fold is unknown")
    keys = {(row.case_key, row.segment_id) for row in examples}
    static = read_static_ordinary_plans(
        plan_store,
        required_keys=keys,
    )
    device = _resolve_device(requested_device)
    predictions = []
    fold_summaries = []
    seen_outer: set[tuple[str, str]] = set()
    model_parameters = 0
    base_parameters = 0
    for outer_fold in selected_folds:
        fold_seed = seed + outer_fold * 1009
        inner_fold = _inner_validation_fold(trained, outer_fold)
        training_rows = [
            row
            for row in examples
            if row.fold not in {outer_fold, inner_fold}
        ]
        inner_rows = [row for row in examples if row.fold == inner_fold]
        outer_rows = [row for row in examples if row.fold == outer_fold]
        outer_training_rows = [
            row for row in examples if row.fold != outer_fold
        ]
        _assert_case_disjoint(training_rows, inner_rows)
        _assert_case_disjoint(training_rows, outer_rows)
        _assert_case_disjoint(inner_rows, outer_rows)
        inner_base_model, inner_base_config = _load_checkpoint(
            trained / f"fold_{outer_fold}_inner_checkpoint.pt",
            device=device,
        )
        base_parameters = parameter_count(inner_base_model)
        training_base_predictions = _score_base(
            inner_base_model,
            training_rows,
            base_config=inner_base_config,
            device=device,
        )
        inner_base_predictions = _score_base(
            inner_base_model,
            inner_rows,
            base_config=inner_base_config,
            device=device,
        )
        training_proposals = _proposal_examples(
            training_rows,
            base_predictions=training_base_predictions,
            static=static,
            maximum_prefix_cardinality=(
                config.maximum_prefix_cardinality
            ),
        )
        inner_proposals = _proposal_examples(
            inner_rows,
            base_predictions=inner_base_predictions,
            static=static,
            maximum_prefix_cardinality=(
                config.maximum_prefix_cardinality
            ),
        )
        inner_model = _new_joint_model(
            base_model=inner_base_model,
            base_config=inner_base_config,
            config=config,
            device=device,
            seed=fold_seed,
        )
        history, best_epoch = _fit_with_validation(
            inner_model,
            training_rows,
            training_proposals,
            validation_rows=inner_rows,
            validation_proposals=inner_proposals,
            base_config=inner_base_config,
            config=config,
            device=device,
            seed=fold_seed,
        )
        inner_scored = score_ordinary_joint_plan_examples(
            inner_model,
            inner_rows,
            inner_proposals,
            base_config=inner_base_config,
            batch_size=config.batch_size,
            device=device,
        )
        acceptance_threshold = choose_zero_error_plan_threshold(
            inner_scored
        )
        del inner_model
        if device.type == "cuda":
            torch.cuda.empty_cache()
        outer_base_model, outer_base_config = _load_checkpoint(
            trained / f"fold_{outer_fold}_checkpoint.pt",
            device=device,
        )
        outer_training_base_predictions = _score_base(
            outer_base_model,
            outer_training_rows,
            base_config=outer_base_config,
            device=device,
        )
        outer_base_predictions = _score_base(
            outer_base_model,
            outer_rows,
            base_config=outer_base_config,
            device=device,
        )
        outer_training_proposals = _proposal_examples(
            outer_training_rows,
            base_predictions=outer_training_base_predictions,
            static=static,
            maximum_prefix_cardinality=(
                config.maximum_prefix_cardinality
            ),
        )
        outer_proposals = _proposal_examples(
            outer_rows,
            base_predictions=outer_base_predictions,
            static=static,
            maximum_prefix_cardinality=(
                config.maximum_prefix_cardinality
            ),
        )
        outer_model = _new_joint_model(
            base_model=outer_base_model,
            base_config=outer_base_config,
            config=config,
            device=device,
            seed=fold_seed + 17,
        )
        outer_history = _fit_fixed_epochs(
            outer_model,
            outer_training_rows,
            outer_training_proposals,
            epochs=best_epoch,
            base_config=outer_base_config,
            config=config,
            device=device,
            seed=fold_seed + 17,
        )
        model_parameters = parameter_count(outer_model)
        outer_scored = score_ordinary_joint_plan_examples(
            outer_model,
            outer_rows,
            outer_proposals,
            base_config=outer_base_config,
            batch_size=config.batch_size,
            device=device,
        )
        base_threshold = _base_acceptance_threshold(
            trained,
            outer_fold,
        )
        for value, base_value in zip(
            outer_scored,
            outer_base_predictions,
            strict=True,
        ):
            key = (str(value["case_key"]), str(value["segment_id"]))
            if key in seen_outer:
                raise ValueError("ordinary joint plan outer duplicate")
            seen_outer.add(key)
            accepted = bool(
                value["raw_automatic"]
                and float(value["confidence"]) >= acceptance_threshold
            )
            base_automatic = bool(
                base_value["release_eligible"]
                and float(base_value["confidence"]) >= base_threshold
            )
            value["outer_fold"] = outer_fold
            value["inner_validation_fold"] = inner_fold
            value["acceptance_threshold"] = acceptance_threshold
            value["accepted"] = accepted
            value["unsafe_accepted"] = bool(
                accepted and not value["complete_exact"]
            )
            value["base_predicted_decision"] = str(
                base_value["predicted_decision"]
            )
            value["base_selected_road_ids"] = list(
                base_value["selected_road_ids"]
            )
            value["base_confidence"] = float(base_value["confidence"])
            value["base_acceptance_threshold"] = base_threshold
            value["base_complete_exact"] = bool(
                base_value["complete_exact"]
            )
            value["base_automatic"] = base_automatic
            value["base_unsafe_automatic"] = bool(
                base_automatic
                and not bool(base_value["complete_exact"])
            )
            predictions.append(value)
        checkpoint_path = root / f"fold_{outer_fold}_joint_plan.pt"
        _save_checkpoint(
            checkpoint_path,
            model=outer_model,
            config=config,
            base_config=outer_base_config,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            acceptance_threshold=acceptance_threshold,
            best_epoch=best_epoch,
        )
        fold_summary = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "training_example_count": len(training_rows),
            "inner_example_count": len(inner_rows),
            "outer_training_example_count": len(
                outer_training_rows
            ),
            "outer_example_count": len(outer_rows),
            "best_epoch": best_epoch,
            "acceptance_threshold": acceptance_threshold,
            "inner_history": history,
            "outer_history": outer_history,
            "metrics": _plan_metrics(
                [
                    row
                    for row in predictions
                    if int(row["outer_fold"]) == outer_fold
                ]
            ),
            "checkpoint": _input_record(checkpoint_path),
        }
        _write_json(root / f"fold_{outer_fold}_summary.json", fold_summary)
        fold_summaries.append(fold_summary)
        del outer_model
        if device.type == "cuda":
            torch.cuda.empty_cache()
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    expected_keys = {
        (row.case_key, row.segment_id)
        for row in examples
        if row.fold in selected_folds
    }
    full_fold_coverage = selected_folds == folds
    metrics = _plan_metrics(predictions)
    selection_gate = bool(
        seen_outer == expected_keys
        and len(predictions) == len(expected_keys)
        and not metrics["counts"].get("accepted_unsafe", 0)
    )
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_SHARED_ENCODER_JOINT_PLAN_STRICT_NESTED_OOF",
        "model_scope": (
            "the v175 Road/anchor/ownership/role encoder is initialized from "
            "its strict checkpoint and fine-tuned by complete-plan "
            "acceptable-set loss plus its original auxiliary losses"
        ),
        "strict_oof_contract": (
            "inner model trains outside outer/inner and selects epoch on "
            "inner; outer model retrains that epoch count on every non-outer "
            "Case and evaluates outer only"
        ),
        "proposal_contract": (
            "truth-free static complete plans and checkpoint-local member "
            "prefixes are frozen before current labels mark acceptable sets"
        ),
        "config": asdict(config),
        "seed": seed,
        "example_count": len(predictions),
        "full_dataset_example_count": len(examples),
        "fold_count": len(selected_folds),
        "full_fold_count": len(folds),
        "full_fold_coverage": full_fold_coverage,
        "folds": fold_summaries,
        "base_parameters": base_parameters,
        "model_parameters": model_parameters,
        "joint_plan_head_parameters": model_parameters - base_parameters,
        "metrics": metrics,
        "read_summary": read_summary,
        "inputs": {
            "member_features": _input_record(
                member_store / "ordinary_road_member_features.jsonl"
            ),
            "member_labels": _input_record(
                member_store / "ordinary_road_member_labels.jsonl"
            ),
            "base_member_store_summary": _input_record(
                base_store / "summary.json"
            ),
            "static_plan_manifest": _input_record(
                plan_store / "manifest.json"
            ),
            "base_training_summary": _input_record(
                trained / "summary.json"
            ),
        },
        "outputs": {
            "predictions": _input_record(prediction_path),
        },
        "feature_uses_truth": False,
        "label_only_acceptability": True,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "skeleton_mutation_count": 0,
        "selection_diagnostic_gate_pass": selection_gate,
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "partial fold diagnostic"
            if not full_fold_coverage
            else "anchor, access, AdvanceRight and final RoadGraph gates "
            "remain outside this ordinary complete-plan stage"
        ),
        "gate_pass": False,
        "wall_seconds": time.perf_counter() - started,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
    }
    _write_json(root / "summary.json", summary)
    return root


def score_ordinary_joint_plan_examples(
    model: TargetAOrdinaryJointPlanNetwork,
    rows: Sequence[OrdinaryRoadSetExample],
    proposals: Sequence[OrdinaryPlanProposalExample],
    *,
    base_config: OrdinaryRoadSetTrainingConfig,
    batch_size: int,
    device: torch.device,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    if top_k < 1:
        raise ValueError("ordinary joint plan top-k is invalid")
    model.eval()
    result = []
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            batch_rows = rows[start : start + batch_size]
            batch_proposals = proposals[start : start + batch_size]
            batch = collate_joint_plan_batch(
                batch_rows,
                batch_proposals,
                base_config=base_config,
                device=device,
            )
            outputs = model(**_network_inputs(batch))
            probabilities = torch.softmax(
                outputs["plan_logits"],
                dim=-1,
            )
            validity_probabilities = torch.sigmoid(
                outputs["plan_validity_logits"]
            )
            base_outputs = outputs["base_outputs"]
            if (
                "ownership_logits" not in base_outputs
                or "business_role_logits" not in base_outputs
            ):
                raise ValueError(
                    "ordinary joint plan lacks ownership/role outputs"
                )
            ownership_predictions = base_outputs[
                "ownership_logits"
            ].argmax(dim=-1)
            role_predictions = base_outputs[
                "business_role_logits"
            ].argmax(dim=-1)
            for index, (row, proposal) in enumerate(
                zip(batch_rows, batch_proposals, strict=True)
            ):
                count = len(proposal.proposal_ids)
                values = probabilities[index, :count]
                ordered_values, ordered_indices = torch.sort(
                    values,
                    descending=True,
                )
                selected_index = int(ordered_indices[0].item())
                probability = float(ordered_values[0].item())
                validity_probability = float(
                    validity_probabilities[
                        index,
                        selected_index,
                    ].item()
                )
                margin = float(
                    ordered_values[0].item()
                    - ordered_values[1].item()
                    if count > 1
                    else ordered_values[0].item()
                )
                decision = proposal.proposal_decisions[selected_index]
                selected_roads = proposal.proposal_road_ids[
                    selected_index
                ]
                complete_exact = bool(
                    decision == proposal.target_decision
                    and selected_roads == proposal.target_road_ids
                )
                alternatives = []
                candidate_index = {
                    road_id: value
                    for value, road_id in enumerate(row.road_ids)
                }
                for rank in range(min(top_k, count)):
                    plan_index = int(ordered_indices[rank].item())
                    plan_road_ids = proposal.proposal_road_ids[
                        plan_index
                    ]
                    alternatives.append(
                        {
                            "rank": rank + 1,
                            "proposal_id": proposal.proposal_ids[
                                plan_index
                            ],
                            "decision": proposal.proposal_decisions[
                                plan_index
                            ],
                            "road_ids": list(
                                plan_road_ids
                            ),
                            "road_business_assignments": [
                                {
                                    "road_id": road_id,
                                    "source": row.sources[
                                        candidate_index[road_id]
                                    ],
                                    "start_node_id": row.start_node_ids[
                                        candidate_index[road_id]
                                    ],
                                    "end_node_id": row.end_node_ids[
                                        candidate_index[road_id]
                                    ],
                                    "ownership": (
                                        ROAD_OWNERSHIP_LABELS[
                                            int(
                                                ownership_predictions[
                                                    index,
                                                    candidate_index[
                                                        road_id
                                                    ],
                                                ].item()
                                            )
                                        ]
                                    ),
                                    "business_role": (
                                        ROAD_BUSINESS_ROLE_LABELS[
                                            int(
                                                role_predictions[
                                                    index,
                                                    candidate_index[
                                                        road_id
                                                    ],
                                                ].item()
                                            )
                                        ]
                                    ),
                                }
                                for road_id in plan_road_ids
                            ],
                            "probability": float(
                                ordered_values[rank].item()
                            ),
                            "validity_probability": float(
                                validity_probabilities[
                                    index,
                                    plan_index,
                                ].item()
                            ),
                        }
                    )
                result.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": proposal.case_key,
                        "segment_id": proposal.segment_id,
                        "fold": proposal.fold,
                        "selected_proposal_id": proposal.proposal_ids[
                            selected_index
                        ],
                        "predicted_decision": decision,
                        "selected_road_ids": list(selected_roads),
                        "top_plan_candidates": alternatives,
                        "selected_road_business_assignments": (
                            alternatives[0][
                                "road_business_assignments"
                            ]
                        ),
                        "target_decision": proposal.target_decision,
                        "target_road_ids": list(
                            proposal.target_road_ids
                        ),
                        "target_reachable": proposal.target_reachable,
                        "proposal_count": count,
                        "selected_probability": probability,
                        "selected_validity_probability": (
                            validity_probability
                        ),
                        "set_margin": margin,
                        "selection_confidence": (
                            probability * max(margin, 0.0)
                        ),
                        "confidence": (
                            validity_probability
                            * probability
                            * max(margin, 0.0)
                        ),
                        "complete_exact": complete_exact,
                        "release_eligible": (
                            proposal.release_eligible
                        ),
                        "raw_automatic": bool(
                            decision != "ABSTAIN"
                            and proposal.release_eligible
                        ),
                        "feature_uses_truth": False,
                        "terminal_input_count": 0,
                    }
                )
    return result


def _fit_with_validation(
    model: TargetAOrdinaryJointPlanNetwork,
    rows: Sequence[OrdinaryRoadSetExample],
    proposals: Sequence[OrdinaryPlanProposalExample],
    *,
    validation_rows: Sequence[OrdinaryRoadSetExample],
    validation_proposals: Sequence[OrdinaryPlanProposalExample],
    base_config: OrdinaryRoadSetTrainingConfig,
    config: OrdinaryJointPlanTrainingConfig,
    device: torch.device,
    seed: int,
) -> tuple[list[dict[str, float]], int]:
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    generator = random.Random(seed)
    history = []
    best_loss = float("inf")
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    stale_epochs = 0
    for epoch in range(config.max_epochs):
        train_loss = _train_epoch(
            model,
            rows,
            proposals,
            optimizer=optimizer,
            base_config=base_config,
            config=config,
            device=device,
            generator=generator,
        )
        validation_loss = _evaluate_loss(
            model,
            validation_rows,
            validation_proposals,
            base_config=base_config,
            config=config,
            device=device,
        )
        history.append(
            {
                "epoch": float(epoch + 1),
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-6:
            best_loss = validation_loss
            best_epoch = epoch + 1
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in model.state_dict().items()
            }
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= config.patience:
                break
    if best_state is None or best_epoch < 1:
        raise ValueError("ordinary joint plan produced no best state")
    model.load_state_dict(best_state)
    return history, best_epoch


def _fit_fixed_epochs(
    model: TargetAOrdinaryJointPlanNetwork,
    rows: Sequence[OrdinaryRoadSetExample],
    proposals: Sequence[OrdinaryPlanProposalExample],
    *,
    epochs: int,
    base_config: OrdinaryRoadSetTrainingConfig,
    config: OrdinaryJointPlanTrainingConfig,
    device: torch.device,
    seed: int,
) -> list[dict[str, float]]:
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    generator = random.Random(seed)
    history = []
    for epoch in range(epochs):
        history.append(
            {
                "epoch": float(epoch + 1),
                "train_loss": _train_epoch(
                    model,
                    rows,
                    proposals,
                    optimizer=optimizer,
                    base_config=base_config,
                    config=config,
                    device=device,
                    generator=generator,
                ),
            }
        )
    return history


def _train_epoch(
    model: TargetAOrdinaryJointPlanNetwork,
    rows: Sequence[OrdinaryRoadSetExample],
    proposals: Sequence[OrdinaryPlanProposalExample],
    *,
    optimizer: torch.optim.Optimizer,
    base_config: OrdinaryRoadSetTrainingConfig,
    config: OrdinaryJointPlanTrainingConfig,
    device: torch.device,
    generator: random.Random,
) -> float:
    order = list(range(len(rows)))
    generator.shuffle(order)
    model.train()
    total = 0.0
    mass = 0.0
    for start in range(0, len(order), config.batch_size):
        indices = order[start : start + config.batch_size]
        batch_rows = [rows[index] for index in indices]
        batch_proposals = [proposals[index] for index in indices]
        batch = collate_joint_plan_batch(
            batch_rows,
            batch_proposals,
            base_config=base_config,
            device=device,
        )
        optimizer.zero_grad(set_to_none=True)
        outputs = model(**_network_inputs(batch))
        losses = _joint_loss_rows(
            outputs,
            batch,
            base_config=base_config,
            config=config,
        )
        weights = batch["weights"]
        loss = (losses * weights).sum() / weights.sum().clamp_min(1e-6)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()
        weight = float(weights.sum().item())
        total += float(loss.item()) * weight
        mass += weight
    return total / max(mass, 1e-9)


def _evaluate_loss(
    model: TargetAOrdinaryJointPlanNetwork,
    rows: Sequence[OrdinaryRoadSetExample],
    proposals: Sequence[OrdinaryPlanProposalExample],
    *,
    base_config: OrdinaryRoadSetTrainingConfig,
    config: OrdinaryJointPlanTrainingConfig,
    device: torch.device,
) -> float:
    model.eval()
    total = 0.0
    mass = 0.0
    with torch.no_grad():
        for start in range(0, len(rows), config.batch_size):
            batch = collate_joint_plan_batch(
                rows[start : start + config.batch_size],
                proposals[start : start + config.batch_size],
                base_config=base_config,
                device=device,
            )
            outputs = model(**_network_inputs(batch))
            losses = _joint_loss_rows(
                outputs,
                batch,
                base_config=base_config,
                config=config,
            )
            weights = batch["weights"]
            total += float((losses * weights).sum().item())
            mass += float(weights.sum().item())
    return total / max(mass, 1e-9)


def _joint_loss_rows(
    outputs: Mapping[str, Any],
    batch: Mapping[str, Any],
    *,
    base_config: OrdinaryRoadSetTrainingConfig,
    config: OrdinaryJointPlanTrainingConfig,
) -> torch.Tensor:
    plan = acceptable_plan_nll(
        outputs["plan_logits"],
        batch["proposal_acceptable"],
        batch["proposal_valid"],
    )
    validity_targets = (
        batch["proposal_acceptable"]
        & (batch["proposal_decisions"] != 2)
    )
    validity = balanced_plan_validity_bce(
        outputs["plan_validity_logits"],
        validity_targets,
        batch["proposal_valid"],
    )
    base = _loss_rows(
        outputs["base_outputs"],
        batch["base_batch"],
        base_config,
        cardinality_weights=None,
    )
    return (
        config.plan_loss_weight * plan
        + config.validity_loss_weight * validity
        + config.base_loss_weight * base
    )


def balanced_plan_validity_bce(
    logits: torch.Tensor,
    targets: torch.Tensor,
    valid: torch.Tensor,
) -> torch.Tensor:
    if (
        logits.shape != targets.shape
        or logits.shape != valid.shape
        or targets.dtype is not torch.bool
        or valid.dtype is not torch.bool
    ):
        raise ValueError("ordinary plan validity shapes differ")
    raw = nn.functional.binary_cross_entropy_with_logits(
        logits,
        targets.to(logits.dtype),
        reduction="none",
    )
    positive = targets & valid
    negative = ~targets & valid
    positive_loss = (raw * positive.to(raw.dtype)).sum(dim=-1) / (
        positive.sum(dim=-1).clamp_min(1).to(raw.dtype)
    )
    negative_loss = (raw * negative.to(raw.dtype)).sum(dim=-1) / (
        negative.sum(dim=-1).clamp_min(1).to(raw.dtype)
    )
    positive_present = positive.any(dim=-1).to(raw.dtype)
    negative_present = negative.any(dim=-1).to(raw.dtype)
    return (
        positive_loss * positive_present
        + negative_loss * negative_present
    ) / (positive_present + negative_present).clamp_min(1.0)


def _score_base(
    model,
    rows: Sequence[OrdinaryRoadSetExample],
    *,
    base_config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
) -> list[dict[str, Any]]:
    return score_ordinary_road_set_examples(
        model,
        rows,
        feature_source="oof",
        batch_size=base_config.batch_size,
        device=device,
        include_member_probabilities=True,
    )


def _proposal_examples(
    rows: Sequence[OrdinaryRoadSetExample],
    *,
    base_predictions: Sequence[Mapping[str, Any]],
    static: Mapping[
        tuple[str, str],
        Sequence[StaticOrdinaryPlan],
    ],
    maximum_prefix_cardinality: int,
) -> list[OrdinaryPlanProposalExample]:
    if len(rows) != len(base_predictions):
        raise ValueError("ordinary joint plan base alignment differs")
    result = []
    for row, prediction in zip(rows, base_predictions, strict=True):
        key = (row.case_key, row.segment_id)
        if key != (
            str(prediction["case_key"]),
            str(prediction["segment_id"]),
        ):
            raise ValueError("ordinary joint plan base key differs")
        result.append(
            build_ordinary_plan_proposal_example(
                row=row,
                base_prediction=prediction,
                static_plans=static[key],
                maximum_prefix_cardinality=(
                    maximum_prefix_cardinality
                ),
            )
        )
    return result


def _new_joint_model(
    *,
    base_model,
    base_config: OrdinaryRoadSetTrainingConfig,
    config: OrdinaryJointPlanTrainingConfig,
    device: torch.device,
    seed: int,
) -> TargetAOrdinaryJointPlanNetwork:
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    return TargetAOrdinaryJointPlanNetwork(
        base_model=base_model,
        base_hidden_dim=base_config.hidden_dim,
        plan_hidden_dim=config.plan_hidden_dim,
        plan_feedforward_dim=config.plan_feedforward_dim,
        dropout=config.dropout,
    ).to(device)


def _network_inputs(
    batch: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "base_batch": batch["base_batch"],
        "proposal_features": batch["proposal_features"],
        "proposal_valid": batch["proposal_valid"],
        "proposal_membership": batch["proposal_membership"],
        "proposal_decisions": batch["proposal_decisions"],
        "proposal_cardinalities": batch["proposal_cardinalities"],
        "candidate_sources": batch["candidate_sources"],
    }


def _save_checkpoint(
    path: Path,
    *,
    model: TargetAOrdinaryJointPlanNetwork,
    config: OrdinaryJointPlanTrainingConfig,
    base_config: OrdinaryRoadSetTrainingConfig,
    outer_fold: int,
    inner_fold: int,
    acceptance_threshold: float,
    best_epoch: int,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "config": asdict(config),
            "base_config": asdict(base_config),
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "acceptance_threshold": acceptance_threshold,
            "best_epoch": best_epoch,
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
    if requested not in {"cuda", "cpu"}:
        raise ValueError("ordinary joint plan device is invalid")
    return torch.device("cpu")


def _input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": resolved.as_posix(),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            )


__all__ = [
    "OrdinaryJointPlanTrainingConfig",
    "balanced_plan_validity_bce",
    "run_ordinary_joint_plan_strict_nested_oof",
    "score_ordinary_joint_plan_examples",
]
