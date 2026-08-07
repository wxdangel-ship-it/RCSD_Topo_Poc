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
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryAnchorRoadGraphDecoder,
    TargetAOrdinaryAnchorRoadRoleGraphDecoder,
    TargetAOrdinaryJointRoadGraphDecoder,
    TargetAOrdinaryRoadSetDecoder,
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_members import (
    ROAD_BUSINESS_ROLE_LABELS,
    ROAD_OWNERSHIP_LABELS,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


DECISIONS = ("KEEP_SWSD", "USE_RCSD")
DECISION_INDEX = {value: index for index, value in enumerate(DECISIONS)}
T06_MIXED_TARGET_STATE = "T06_MAIN_RCSD_ATTACHED_SWSD"
OrdinaryRoadSetModel = (
    TargetAOrdinaryRoadSetDecoder
    | TargetAOrdinaryJointRoadGraphDecoder
    | TargetAOrdinaryAnchorRoadGraphDecoder
    | TargetAOrdinaryAnchorRoadRoleGraphDecoder
)


@dataclass(frozen=True)
class OrdinaryRoadSetTrainingConfig:
    hidden_dim: int = 128
    context_dim: int = 192
    structured_graph_decoder: bool = False
    anchor_relation_decoder: bool = False
    ownership_role_decoder: bool = False
    business_member_fusion: bool = True
    graph_layers: int = 2
    graph_heads: int = 4
    graph_attention_scope: str = "ENDPOINT"
    road_relation_dim: int = 0
    road_relation_attention_bias: bool = True
    road_relation_graph_adjacency: bool = True
    component_edge_decoder: bool = False
    cardinality_count: int = 65
    dropout: float = 0.1
    batch_size: int = 48
    max_epochs: int = 100
    patience: int = 15
    learning_rate: float = 4e-4
    weight_decay: float = 2e-4
    decision_loss_weight: float = 1.0
    cardinality_loss_weight: float = 0.5
    cardinality_class_weight_cap: float = 0.0
    cardinality_ordinal_loss_weight: float = 0.0
    member_loss_weight: float = 2.0
    ownership_loss_weight: float = 1.0
    business_role_loss_weight: float = 0.5
    component_edge_loss_weight: float = 0.0
    teacher_training_loss_weight: float = 1.0
    oof_training_loss_weight: float = 0.0
    oof_early_stopping: bool = False
    torch_num_threads: int = 4

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.context_dim,
            self.graph_layers,
            self.graph_heads,
            self.cardinality_count,
            self.batch_size,
            self.max_epochs,
            self.patience,
            self.torch_num_threads,
        ) < 1:
            raise ValueError("ordinary Road-set training config is invalid")
        if self.hidden_dim % self.graph_heads:
            raise ValueError(
                "ordinary Road-set graph heads do not divide hidden dim"
            )
        if self.anchor_relation_decoder and not self.structured_graph_decoder:
            raise ValueError(
                "ordinary anchor relation decoder needs graph decoder"
            )
        if self.road_relation_dim < 0 or (
            self.road_relation_dim > 0 and not self.structured_graph_decoder
        ):
            raise ValueError(
                "ordinary Road relation decoder needs graph decoder"
            )
        if self.ownership_role_decoder and not self.anchor_relation_decoder:
            raise ValueError(
                "ordinary ownership/role decoder needs anchor relation decoder"
            )
        if self.component_edge_decoder and (
            not self.ownership_role_decoder or self.road_relation_dim < 1
        ):
            raise ValueError(
                "ordinary component edge decoder needs roles and relations"
            )
        if self.component_edge_decoder != (
            self.component_edge_loss_weight > 0.0
        ):
            raise ValueError(
                "ordinary component edge decoder/loss differs"
            )
        if self.graph_attention_scope not in {
            "ENDPOINT",
            "FULL",
            "ENDPOINT_THEN_FULL",
        }:
            raise ValueError("ordinary Road-set attention scope is invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("ordinary Road-set dropout is invalid")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("ordinary Road-set optimizer config is invalid")
        if min(
            self.cardinality_class_weight_cap,
            self.cardinality_ordinal_loss_weight,
        ) < 0.0:
            raise ValueError("ordinary Road-set cardinality config is invalid")
        if min(
            self.teacher_training_loss_weight,
            self.oof_training_loss_weight,
            self.ownership_loss_weight,
            self.business_role_loss_weight,
            self.component_edge_loss_weight,
        ) < 0.0:
            raise ValueError("ordinary Road-set view weights are invalid")
        if (
            self.teacher_training_loss_weight
            + self.oof_training_loss_weight
            <= 0.0
        ):
            raise ValueError("ordinary Road-set training views are disabled")


@dataclass(frozen=True)
class OrdinaryRoadSetExample:
    case_key: str
    segment_id: str
    fold: int
    object_features: tuple[float, ...]
    road_ids: tuple[str, ...]
    sources: tuple[str, ...]
    start_node_ids: tuple[str, ...]
    end_node_ids: tuple[str, ...]
    anchor_features: tuple[tuple[float, ...], ...]
    teacher_anchor_relations: tuple[
        tuple[tuple[float, ...], ...],
        ...,
    ]
    oof_anchor_relations: tuple[
        tuple[tuple[float, ...], ...],
        ...,
    ]
    teacher_features: tuple[tuple[float, ...], ...]
    oof_features: tuple[tuple[float, ...], ...]
    decision: int
    target_indices: tuple[int, ...]
    ownership_targets: tuple[int, ...]
    ownership_task_mask: tuple[bool, ...]
    business_role_targets: tuple[int, ...]
    business_role_task_mask: tuple[bool, ...]
    sample_weight: float
    oof_anchor_release_ready: bool
    target_state: str = ""
    ownership_sample_weight: float = 0.0
    business_role_sample_weight: float = 0.0
    road_relations: tuple[
        tuple[int, int, tuple[float, ...]],
        ...,
    ] = ()
    member_sample_weights: tuple[float, ...] = ()


def run_ordinary_road_set_strict_nested_oof(
    *,
    member_store_root: Path,
    output_root: Path,
    seed: int,
    config: OrdinaryRoadSetTrainingConfig = OrdinaryRoadSetTrainingConfig(),
    requested_device: str = "cuda",
) -> Path:
    """Train a structured ordinary Road-set decoder under strict Case OOF."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    store = normalize_runtime_path(member_store_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    examples, read_summary = read_ordinary_road_set_examples(store)
    if (
        int(read_summary["road_relation_feature_dim"])
        != config.road_relation_dim
    ):
        raise ValueError(
            "ordinary Road relation feature dimension differs from config"
        )
    validate_cardinality_capacity(
        maximum_target_cardinality=read_summary[
            "maximum_target_cardinality"
        ],
        cardinality_count=config.cardinality_count,
    )
    if config.ownership_role_decoder and (
        read_summary.get("ownership_label", 0) < 1
        or read_summary.get("business_role_label", 0) < 1
    ):
        raise ValueError(
            "ordinary ownership/role decoder has no business labels"
        )
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("ordinary Road-set strict OOF needs three folds")
    root.mkdir(parents=True)
    object_dim = len(examples[0].object_features)
    candidate_dim = len(examples[0].teacher_features[0])
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
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 17,
        )
        final = _fit_fixed_epochs(
            outer_training,
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 53,
            epoch_count=tuning["best_epoch"],
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
            row["teacher_decision_exact"] = bool(
                teacher["decision_exact"]
            )
            row["teacher_road_set_exact"] = bool(
                teacher["road_set_exact"]
            )
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
            inner_checkpoint,
            tuning["model"],
            config=config,
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
        )
        _save_checkpoint(
            outer_checkpoint,
            final["model"],
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
            "inner_training_view_count": len(inner_training)
            * int(config.teacher_training_loss_weight > 0.0)
            + len(inner_training)
            * int(config.oof_training_loss_weight > 0.0),
            "inner_validation_count": len(inner_validation),
            "outer_train_count": len(outer_training),
            "outer_training_view_count": len(outer_training)
            * int(config.teacher_training_loss_weight > 0.0)
            + len(outer_training)
            * int(config.oof_training_loss_weight > 0.0),
            "outer_validation_count": len(outer_validation),
            "early_stopping_condition": (
                "STRICT_OOF_ANCHOR"
                if config.oof_early_stopping
                else "TEACHER_ANCHOR"
            ),
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
    predictions.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    metrics = ordinary_road_set_metrics(predictions)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": (
            "ORDINARY_JOINT_ROAD_GRAPH_DECODER_STRICT_NESTED_OOF"
            if config.structured_graph_decoder
            else "ORDINARY_ROAD_SET_DECODER_STRICT_NESTED_OOF"
        ),
        "decoder_kind": (
            (
                "ANCHOR_ROAD_OWNERSHIP_ROLE_CROSS_ATTENTION_"
                if config.ownership_role_decoder
                else "ANCHOR_ROAD_CROSS_ATTENTION_"
                if config.anchor_relation_decoder
                else ""
            )
            + (
                "AUXILIARY_"
                if config.ownership_role_decoder
                and not config.business_member_fusion
                else ""
            )
            + f"{config.graph_attention_scope}_ROAD_GRAPH"
            if config.structured_graph_decoder
            else "UNORDERED_SET"
        ),
        "model_scope": (
            "The decoder jointly predicts KEEP_SWSD/USE_RCSD, raw Road "
            "cardinality, and the complete Road member set from the "
            "anchor-conditioned candidate pool; Road relations are "
            + (
                (
                    "first conditioned on each independently selected "
                    "semantic anchor, then "
                )
                if config.anchor_relation_decoder
                else ""
            )
            + (
                "encoded by the configured graph-attention scope."
                if config.structured_graph_decoder
                else "not encoded by the unordered-set baseline."
            )
        ),
        "output_boundary": (
            "Generated split IDs and final Node IDs remain deterministic "
            "write-out. "
            + (
                "Each candidate Road also emits current-Segment ownership "
                "and an explicit business role; access/position remains "
                "outside this stage."
                if config.ownership_role_decoder
                else "Road role and access/position heads are evaluated "
                "separately and are not claimed by this stage."
            )
        ),
        "hard_anchor_contract": (
            "Candidate expansion may include every anchor alternative, but "
            "teacher/OOF selected-anchor relations are separate inputs and "
            "Road scores cannot change the selected anchor."
        ),
        "training_view_contract": (
            "teacher and strict-OOF anchor-conditioned views share labels and "
            "enter loss only with their configured weights; held-out Case "
            "features never enter an outer-fold model"
        ),
        "early_stopping_condition": (
            "STRICT_OOF_ANCHOR"
            if config.oof_early_stopping
            else "TEACHER_ANCHOR"
        ),
        "object_feature_dim": object_dim,
        "candidate_feature_dim": candidate_dim,
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
            (
                ""
                if config.ownership_role_decoder
                else "Road roles, "
            )
            + "access Road/position, final Node recipe, "
            "AdvanceRight, and global ownership/topology decode remain "
            "outside this isolated member-set stage."
        ),
        "member_store_summary": _input_record(store / "summary.json"),
        "predictions": _input_record(prediction_path),
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            len(predictions) == len(examples)
            and {
                (row["case_key"], row["segment_id"]) for row in predictions
            }
            == {(row.case_key, row.segment_id) for row in examples}
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("ordinary Road-set OOF coverage gate failed")
    return root


def read_ordinary_road_set_examples(
    root: Path,
) -> tuple[list[OrdinaryRoadSetExample], dict[str, int]]:
    store = normalize_runtime_path(root).resolve(strict=True)
    labels = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(store / "ordinary_road_member_labels.jsonl")
    }
    examples = []
    counts: Counter[str] = Counter()
    path = store / "ordinary_road_member_features.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            feature = json.loads(line)
            key = (str(feature["case_key"]), str(feature["segment_id"]))
            label = labels[key]
            counts["feature"] += 1
            counts["label_task"] += int(label["task_mask"])
            counts["teacher_anchor_ready"] += int(
                label["teacher_anchor_ready"]
            )
            if not bool(label["task_mask"]):
                continue
            target_state = str(
                label.get("target_state") or label["preferred_decision"]
            )
            decision = str(label["preferred_decision"])
            if decision == T06_MIXED_TARGET_STATE:
                decision = "USE_RCSD"
                counts["mapped_t06_mixed_decision"] += 1
            if decision not in DECISION_INDEX:
                counts["masked_unsupported_decision"] += 1
                continue
            candidates = feature["candidate_rows"]
            anchor_features = tuple(
                tuple(float(value) for value in row)
                for row in (
                    feature.get("anchor_role_feature_values") or ()
                )
            )
            empty_anchor_relations = [
                [0.0] * 4 for _ in anchor_features
            ]
            index_by_id = {
                str(row["road_id"]): index
                for index, row in enumerate(candidates)
            }
            target_indices = tuple(
                sorted(
                    index_by_id[str(road_id)]
                    for road_id in label["acceptable_road_ids"]
                )
            )
            if not target_indices:
                counts["masked_empty_target"] += 1
                continue
            ownership_targets = tuple(
                int(value)
                for value in label.get("road_ownership_targets")
                or [0] * len(candidates)
            )
            ownership_task_mask = tuple(
                bool(value)
                for value in label.get("road_ownership_task_mask")
                or [False] * len(candidates)
            )
            business_role_targets = tuple(
                int(value)
                for value in label.get("road_business_role_targets")
                or [0] * len(candidates)
            )
            business_role_task_mask = tuple(
                bool(value)
                for value in label.get("road_business_role_task_mask")
                or [False] * len(candidates)
            )
            member_sample_weights = tuple(
                float(value)
                for value in label.get("road_member_sample_weights")
                or [float(label["sample_weight"])] * len(candidates)
            )
            if any(
                len(values) != len(candidates)
                for values in (
                    member_sample_weights,
                    ownership_targets,
                    ownership_task_mask,
                    business_role_targets,
                    business_role_task_mask,
                )
            ):
                raise ValueError(
                    "ordinary Road business label alignment differs"
                )
            examples.append(
                OrdinaryRoadSetExample(
                    case_key=key[0],
                    segment_id=key[1],
                    fold=int(label["fold"]),
                    object_features=tuple(
                        float(value)
                        for value in feature["object_feature_values"]
                    ),
                    road_ids=tuple(
                        str(row["road_id"]) for row in candidates
                    ),
                    sources=tuple(
                        str(row["source"]) for row in candidates
                    ),
                    start_node_ids=tuple(
                        str(row["start_node_id"]) for row in candidates
                    ),
                    end_node_ids=tuple(
                        str(row["end_node_id"]) for row in candidates
                    ),
                    anchor_features=anchor_features,
                    teacher_anchor_relations=tuple(
                        tuple(
                            tuple(float(value) for value in relation)
                            for relation in (
                                row.get(
                                    "teacher_anchor_relation_values"
                                )
                                or empty_anchor_relations
                            )
                        )
                        for row in candidates
                    ),
                    oof_anchor_relations=tuple(
                        tuple(
                            tuple(float(value) for value in relation)
                            for relation in (
                                row.get("oof_anchor_relation_values")
                                or empty_anchor_relations
                            )
                        )
                        for row in candidates
                    ),
                    teacher_features=tuple(
                        tuple(
                            float(value)
                            for value in row["teacher_feature_values"]
                        )
                        for row in candidates
                    ),
                    oof_features=tuple(
                        tuple(
                            float(value)
                            for value in row["oof_feature_values"]
                        )
                        for row in candidates
                    ),
                    decision=DECISION_INDEX[decision],
                    target_indices=target_indices,
                    ownership_targets=ownership_targets,
                    ownership_task_mask=ownership_task_mask,
                    business_role_targets=business_role_targets,
                    business_role_task_mask=business_role_task_mask,
                    sample_weight=float(label["sample_weight"]),
                    oof_anchor_release_ready=bool(
                        label["oof_anchor_release_ready"]
                    ),
                    target_state=target_state,
                    ownership_sample_weight=float(
                        label.get("road_ownership_sample_weight")
                        or label["sample_weight"]
                    ),
                    business_role_sample_weight=float(
                        label.get("road_business_role_sample_weight")
                        or label["sample_weight"]
                    ),
                    road_relations=tuple(
                        (
                            int(row["left_index"]),
                            int(row["right_index"]),
                            tuple(
                                float(value)
                                for value in row["feature_values"]
                            ),
                        )
                        for row in feature.get("road_relation_rows") or ()
                    ),
                    member_sample_weights=member_sample_weights,
                )
            )
            counts[f"usable_{decision}"] += 1
            counts[f"usable_target_state_{target_state}"] += 1
            counts["ownership_label"] += sum(ownership_task_mask)
            counts["business_role_label"] += sum(business_role_task_mask)
    if not examples:
        raise ValueError("ordinary Road-set training has no examples")
    object_dim = len(examples[0].object_features)
    candidate_dim = len(examples[0].teacher_features[0])
    if any(
        len(row.object_features) != object_dim
        or any(
            len(values) != candidate_dim
            for values in (*row.teacher_features, *row.oof_features)
        )
        for row in examples
    ):
        raise ValueError("ordinary Road-set feature dimension differs")
    counts["usable_example"] = len(examples)
    counts["object_feature_dim"] = object_dim
    counts["candidate_feature_dim"] = candidate_dim
    counts["anchor_feature_dim"] = max(
        (
            len(value)
            for row in examples
            for value in row.anchor_features
        ),
        default=0,
    )
    counts["anchor_relation_dim"] = max(
        (
            len(value)
            for row in examples
            for candidate in row.teacher_anchor_relations
            for value in candidate
        ),
        default=0,
    )
    counts["maximum_target_cardinality"] = max(
        len(row.target_indices) for row in examples
    )
    counts["road_relation_feature_dim"] = max(
        (
            len(values)
            for row in examples
            for _, _, values in row.road_relations
        ),
        default=0,
    )
    return examples, dict(sorted(counts.items()))


def validate_cardinality_capacity(
    *,
    maximum_target_cardinality: int,
    cardinality_count: int,
) -> None:
    if maximum_target_cardinality >= cardinality_count:
        raise ValueError(
            "ordinary Road-set cardinality capacity is smaller than "
            f"complete target: maximum={maximum_target_cardinality}, "
            f"count={cardinality_count}"
        )


def balanced_member_bce(
    logits: torch.Tensor,
    targets: torch.Tensor,
    valid: torch.Tensor,
    candidate_weight_ratios: torch.Tensor | None = None,
) -> torch.Tensor:
    if logits.shape != targets.shape or logits.shape != valid.shape:
        raise ValueError("ordinary Road member BCE shapes differ")
    ratios = (
        torch.ones_like(logits)
        if candidate_weight_ratios is None
        else candidate_weight_ratios
    )
    if ratios.shape != logits.shape:
        raise ValueError("ordinary Road member weights differ")
    raw = nn.functional.binary_cross_entropy_with_logits(
        torch.where(valid, logits, torch.zeros_like(logits)),
        targets.to(logits.dtype),
        reduction="none",
    )
    positive = targets & valid
    negative = ~targets & valid
    positive_weights = ratios * positive.to(ratios.dtype)
    negative_weights = ratios * negative.to(ratios.dtype)
    positive_mean = (raw * positive_weights).sum(
        dim=-1
    ) / positive_weights.sum(dim=-1).clamp_min(1e-6)
    negative_mean = (raw * negative_weights).sum(
        dim=-1
    ) / negative_weights.sum(dim=-1).clamp_min(1e-6)
    return (positive_mean + negative_mean) / 2.0


def balanced_component_edge_bce(
    logits: torch.Tensor,
    targets: torch.Tensor,
    valid: torch.Tensor,
) -> torch.Tensor:
    if (
        logits.ndim != 3
        or logits.shape != targets.shape
        or logits.shape != valid.shape
    ):
        raise ValueError("ordinary Road component BCE shapes differ")
    raw = nn.functional.binary_cross_entropy_with_logits(
        torch.where(valid, logits, torch.zeros_like(logits)),
        targets.to(logits.dtype),
        reduction="none",
    )
    dimensions = (1, 2)
    positive = targets & valid
    negative = ~targets & valid
    positive_count = positive.sum(dim=dimensions)
    negative_count = negative.sum(dim=dimensions)
    positive_mean = (
        raw * positive.to(raw.dtype)
    ).sum(dim=dimensions) / positive_count.clamp_min(1)
    negative_mean = (
        raw * negative.to(raw.dtype)
    ).sum(dim=dimensions) / negative_count.clamp_min(1)
    present_count = (
        (positive_count > 0).to(raw.dtype)
        + (negative_count > 0).to(raw.dtype)
    )
    return (positive_mean + negative_mean) / present_count.clamp_min(1.0)


def masked_candidate_cross_entropy(
    logits: torch.Tensor,
    targets: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    if (
        logits.ndim != 3
        or targets.shape != logits.shape[:2]
        or mask.shape != logits.shape[:2]
    ):
        raise ValueError("ordinary Road business loss shapes differ")
    raw = nn.functional.cross_entropy(
        logits.transpose(1, 2),
        targets,
        reduction="none",
    )
    class_losses = []
    class_present = []
    for class_index in range(logits.shape[-1]):
        class_mask = mask & (targets == class_index)
        class_float = class_mask.to(raw.dtype)
        class_losses.append(
            (raw * class_float).sum(dim=-1)
            / class_float.sum(dim=-1).clamp_min(1.0)
        )
        class_present.append(class_mask.any(dim=-1))
    losses = torch.stack(class_losses, dim=-1)
    present = torch.stack(class_present, dim=-1)
    return (
        losses * present.to(losses.dtype)
    ).sum(dim=-1) / present.sum(dim=-1).clamp_min(1)


def score_ordinary_road_set_examples(
    model: OrdinaryRoadSetModel,
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    feature_source: str,
    batch_size: int,
    device: torch.device,
    member_probability_threshold: float | None = None,
    include_member_probabilities: bool = False,
) -> list[dict[str, Any]]:
    if feature_source not in {"teacher", "oof"}:
        raise ValueError("ordinary Road-set feature source is invalid")
    if member_probability_threshold is not None and not (
        0.0 <= member_probability_threshold <= 1.0
    ):
        raise ValueError("ordinary Road-set member threshold is invalid")
    model.eval()
    result = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            batch = _batch_tensors(
                rows,
                feature_source=feature_source,
                device=device,
                cardinality_count=model.cardinality_count,
                road_relation_dim=getattr(model, "road_relation_dim", 0),
            )
            outputs = _forward_model(model, batch)
            decision_probabilities = torch.softmax(
                outputs["decision_logits"], dim=-1
            )
            cardinality_probabilities = torch.softmax(
                outputs["cardinality_logits"], dim=-1
            )
            member_probabilities = torch.sigmoid(outputs["member_logits"])
            ownership_predictions = (
                outputs["ownership_logits"].argmax(dim=-1)
                if "ownership_logits" in outputs
                else None
            )
            business_role_predictions = (
                outputs["business_role_logits"].argmax(dim=-1)
                if "business_role_logits" in outputs
                else None
            )
            component_edge_probabilities = (
                torch.sigmoid(outputs["component_edge_logits"])
                if "component_edge_logits" in outputs
                else None
            )
            for index, row in enumerate(rows):
                decision = int(
                    decision_probabilities[index].argmax().item()
                )
                source = "SWSD" if decision == 0 else "RCSD"
                valid_indices = [
                    candidate_index
                    for candidate_index, value in enumerate(row.sources)
                    if value == source
                ]
                predicted_cardinality = int(
                    cardinality_probabilities[index].argmax().item()
                )
                predicted_cardinality = max(
                    1,
                    min(predicted_cardinality, len(valid_indices)),
                )
                selected_indices = select_member_indices(
                    probabilities=[
                        float(member_probabilities[index, value].item())
                        for value in range(len(row.road_ids))
                    ],
                    road_ids=row.road_ids,
                    valid_indices=valid_indices,
                    predicted_cardinality=predicted_cardinality,
                    probability_threshold=member_probability_threshold,
                )
                predicted_cardinality = len(selected_indices)
                target = set(row.target_indices)
                selected = set(selected_indices)
                intersection = len(target & selected)
                precision = intersection / len(selected) if selected else 0.0
                recall = intersection / len(target) if target else 0.0
                f1 = (
                    2.0 * precision * recall / (precision + recall)
                    if precision + recall
                    else 0.0
                )
                decision_confidence = float(
                    decision_probabilities[index, decision].item()
                )
                cardinality_confidence = float(
                    cardinality_probabilities[
                        index,
                        min(
                            predicted_cardinality,
                            model.cardinality_count - 1,
                        ),
                    ].item()
                )
                selected_min = min(
                    (
                        float(member_probabilities[index, value].item())
                        for value in selected_indices
                    ),
                    default=0.0,
                )
                excluded_max = max(
                    (
                        float(member_probabilities[index, value].item())
                        for value in valid_indices
                        if value not in selected
                    ),
                    default=0.0,
                )
                set_margin = selected_min - excluded_max
                confidence = (
                    decision_confidence
                    * cardinality_confidence
                    * max(0.0, set_margin)
                )
                decision_exact = decision == row.decision
                road_set_exact = selected == target
                ownership_enabled = [
                    value
                    for value, enabled in enumerate(
                        row.ownership_task_mask
                    )
                    if enabled and ownership_predictions is not None
                ]
                ownership_correct = sum(
                    int(
                        int(ownership_predictions[index, value].item())
                        == row.ownership_targets[value]
                    )
                    for value in ownership_enabled
                )
                ownership_target_counts = [
                    sum(
                        int(row.ownership_targets[value] == class_index)
                        for value in ownership_enabled
                    )
                    for class_index in range(len(ROAD_OWNERSHIP_LABELS))
                ]
                ownership_prediction_counts = [
                    sum(
                        int(
                            int(
                                ownership_predictions[index, value].item()
                            )
                            == class_index
                        )
                        for value in ownership_enabled
                    )
                    for class_index in range(len(ROAD_OWNERSHIP_LABELS))
                ]
                ownership_class_correct = [
                    sum(
                        int(
                            row.ownership_targets[value] == class_index
                            and int(
                                ownership_predictions[index, value].item()
                            )
                            == class_index
                        )
                        for value in ownership_enabled
                    )
                    for class_index in range(len(ROAD_OWNERSHIP_LABELS))
                ]
                role_enabled = [
                    value
                    for value, enabled in enumerate(
                        row.business_role_task_mask
                    )
                    if enabled and business_role_predictions is not None
                ]
                role_correct = sum(
                    int(
                        int(
                            business_role_predictions[index, value].item()
                        )
                        == row.business_role_targets[value]
                    )
                    for value in role_enabled
                )
                role_target_counts = [
                    sum(
                        int(
                            row.business_role_targets[value] == class_index
                        )
                        for value in role_enabled
                    )
                    for class_index in range(
                        len(ROAD_BUSINESS_ROLE_LABELS)
                    )
                ]
                role_prediction_counts = [
                    sum(
                        int(
                            int(
                                business_role_predictions[
                                    index, value
                                ].item()
                            )
                            == class_index
                        )
                        for value in role_enabled
                    )
                    for class_index in range(
                        len(ROAD_BUSINESS_ROLE_LABELS)
                    )
                ]
                role_class_correct = [
                    sum(
                        int(
                            row.business_role_targets[value] == class_index
                            and int(
                                business_role_predictions[
                                    index, value
                                ].item()
                            )
                            == class_index
                        )
                        for value in role_enabled
                    )
                    for class_index in range(
                        len(ROAD_BUSINESS_ROLE_LABELS)
                    )
                ]
                component_edge_task_count = 0
                component_edge_target_count = 0
                component_edge_prediction_count = 0
                component_edge_correct_count = 0
                component_edge_f1 = 0.0
                if component_edge_probabilities is not None:
                    edge_mask = batch["component_edge_task_mask"][
                        index
                    ]
                    edge_truth = (
                        batch["component_edge_targets"][index] & edge_mask
                    )
                    edge_prediction = (
                        component_edge_probabilities[index] >= 0.5
                    ) & edge_mask
                    component_edge_task_count = int(edge_mask.sum().item())
                    component_edge_target_count = int(
                        edge_truth.sum().item()
                    )
                    component_edge_prediction_count = int(
                        edge_prediction.sum().item()
                    )
                    component_edge_correct_count = int(
                        (edge_truth & edge_prediction).sum().item()
                    )
                    edge_precision = (
                        component_edge_correct_count
                        / component_edge_prediction_count
                        if component_edge_prediction_count
                        else 0.0
                    )
                    edge_recall = (
                        component_edge_correct_count
                        / component_edge_target_count
                        if component_edge_target_count
                        else 0.0
                    )
                    component_edge_f1 = (
                        2.0
                        * edge_precision
                        * edge_recall
                        / (edge_precision + edge_recall)
                        if edge_precision + edge_recall
                        else 0.0
                    )
                decoded = {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": row.case_key,
                        "segment_id": row.segment_id,
                        "fold": row.fold,
                        "feature_source": feature_source,
                        "selection_mode": (
                            "MEMBER_THRESHOLD"
                            if member_probability_threshold is not None
                            else "CARDINALITY_TOPK"
                        ),
                        "member_probability_threshold": (
                            member_probability_threshold
                        ),
                        "predicted_decision": DECISIONS[decision],
                        "truth_decision": DECISIONS[row.decision],
                        "truth_target_state": (
                            row.target_state or DECISIONS[row.decision]
                        ),
                        "predicted_cardinality": predicted_cardinality,
                        "truth_cardinality": len(target),
                        "selected_road_ids": [
                            row.road_ids[value] for value in selected_indices
                        ],
                        "target_road_ids": [
                            row.road_ids[value]
                            for value in row.target_indices
                        ],
                        "decision_exact": decision_exact,
                        "road_set_exact": road_set_exact,
                        "complete_exact": decision_exact and road_set_exact,
                        "ownership_label_count": len(ownership_enabled),
                        "ownership_correct_count": ownership_correct,
                        "ownership_target_counts": (
                            ownership_target_counts
                        ),
                        "ownership_prediction_counts": (
                            ownership_prediction_counts
                        ),
                        "ownership_class_correct_counts": (
                            ownership_class_correct
                        ),
                        "ownership_exact": bool(
                            ownership_enabled
                            and ownership_correct
                            == len(ownership_enabled)
                        ),
                        "business_role_label_count": len(role_enabled),
                        "business_role_correct_count": role_correct,
                        "business_role_target_counts": role_target_counts,
                        "business_role_prediction_counts": (
                            role_prediction_counts
                        ),
                        "business_role_class_correct_counts": (
                            role_class_correct
                        ),
                        "business_role_exact": bool(
                            role_enabled
                            and role_correct == len(role_enabled)
                        ),
                        "component_edge_task_count": (
                            component_edge_task_count
                        ),
                        "component_edge_target_count": (
                            component_edge_target_count
                        ),
                        "component_edge_prediction_count": (
                            component_edge_prediction_count
                        ),
                        "component_edge_correct_count": (
                            component_edge_correct_count
                        ),
                        "component_edge_f1": component_edge_f1,
                        "road_precision": precision,
                        "road_recall": recall,
                        "road_f1": f1,
                        "decision_confidence": decision_confidence,
                        "cardinality_confidence": cardinality_confidence,
                        "set_margin": set_margin,
                        "confidence": confidence,
                        "candidate_count": len(row.road_ids),
                        "oof_anchor_release_ready": (
                            row.oof_anchor_release_ready
                        ),
                        "release_eligible": row.oof_anchor_release_ready,
                    }
                if ownership_predictions is not None:
                    decoded["selected_road_business_roles"] = [
                        {
                            "road_id": row.road_ids[value],
                            "ownership": ROAD_OWNERSHIP_LABELS[
                                int(
                                    ownership_predictions[
                                        index, value
                                    ].item()
                                )
                            ],
                            "business_role": ROAD_BUSINESS_ROLE_LABELS[
                                int(
                                    business_role_predictions[
                                        index, value
                                    ].item()
                                )
                            ],
                        }
                        for value in selected_indices
                    ]
                if include_member_probabilities:
                    decoded["candidate_road_ids"] = list(row.road_ids)
                    decoded["candidate_sources"] = list(row.sources)
                    decoded["candidate_member_probabilities"] = [
                        float(member_probabilities[index, value].item())
                        for value in range(len(row.road_ids))
                    ]
                    if ownership_predictions is not None:
                        decoded["candidate_predicted_ownership"] = [
                            ROAD_OWNERSHIP_LABELS[
                                int(
                                    ownership_predictions[
                                        index, value
                                    ].item()
                                )
                            ]
                            for value in range(len(row.road_ids))
                        ]
                        decoded["candidate_predicted_business_role"] = [
                            ROAD_BUSINESS_ROLE_LABELS[
                                int(
                                    business_role_predictions[
                                        index, value
                                    ].item()
                                )
                            ]
                            for value in range(len(row.road_ids))
                        ]
                result.append(decoded)
    return result


def select_member_indices(
    *,
    probabilities: Sequence[float],
    road_ids: Sequence[str],
    valid_indices: Sequence[int],
    predicted_cardinality: int,
    probability_threshold: float | None,
) -> tuple[int, ...]:
    if len(probabilities) != len(road_ids):
        raise ValueError("ordinary Road-set probability alignment differs")
    ranked = sorted(
        valid_indices,
        key=lambda value: (-float(probabilities[value]), road_ids[value]),
    )
    if probability_threshold is None:
        return tuple(sorted(ranked[:predicted_cardinality]))
    selected = [
        value
        for value in ranked
        if float(probabilities[value]) >= probability_threshold
    ]
    if not selected and ranked:
        selected = ranked[:1]
    return tuple(sorted(selected))


def choose_zero_exact_error_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    errors = [
        float(row["confidence"])
        for row in rows
        if bool(row["release_eligible"]) and not bool(row["complete_exact"])
    ]
    if not errors:
        return 0.0
    return min(1.000001, max(errors) + 1e-9)


def candidate_class_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    prefix: str,
    labels: Sequence[str],
) -> dict[str, dict[str, float | int]]:
    target_counts = [0] * len(labels)
    prediction_counts = [0] * len(labels)
    correct_counts = [0] * len(labels)
    for row in rows:
        for output, key in (
            (target_counts, f"{prefix}_target_counts"),
            (prediction_counts, f"{prefix}_prediction_counts"),
            (correct_counts, f"{prefix}_class_correct_counts"),
        ):
            values = row.get(key) or ()
            for index, value in enumerate(values):
                if index < len(output):
                    output[index] += int(value)
    return {
        label: {
            "target_count": target_counts[index],
            "prediction_count": prediction_counts[index],
            "correct_count": correct_counts[index],
            "recall": (
                correct_counts[index] / target_counts[index]
                if target_counts[index]
                else 0.0
            ),
            "precision": (
                correct_counts[index] / prediction_counts[index]
                if prediction_counts[index]
                else 0.0
            ),
        }
        for index, label in enumerate(labels)
    }


def ordinary_road_set_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    count = len(rows)
    ownership_count = sum(
        int(row.get("ownership_label_count") or 0) for row in rows
    )
    business_role_count = sum(
        int(row.get("business_role_label_count") or 0) for row in rows
    )
    component_edge_target_count = sum(
        int(row.get("component_edge_target_count") or 0) for row in rows
    )
    component_edge_prediction_count = sum(
        int(row.get("component_edge_prediction_count") or 0)
        for row in rows
    )
    component_edge_correct_count = sum(
        int(row.get("component_edge_correct_count") or 0) for row in rows
    )
    component_edge_precision = (
        component_edge_correct_count / component_edge_prediction_count
        if component_edge_prediction_count
        else 0.0
    )
    component_edge_recall = (
        component_edge_correct_count / component_edge_target_count
        if component_edge_target_count
        else 0.0
    )
    ownership_classes = candidate_class_metrics(
        rows,
        prefix="ownership",
        labels=ROAD_OWNERSHIP_LABELS,
    )
    business_role_classes = candidate_class_metrics(
        rows,
        prefix="business_role",
        labels=ROAD_BUSINESS_ROLE_LABELS,
    )
    automatic = [row for row in rows if bool(row.get("automatic"))]
    unsafe = [
        row for row in automatic if not bool(row["complete_exact"])
    ]
    per_case: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        per_case.setdefault(str(row["case_key"]), []).append(row)
    case_exact = {
        key: sum(bool(row["complete_exact"]) for row in values) / len(values)
        for key, values in per_case.items()
    }
    return {
        "count": count,
        "decision_exact": (
            sum(bool(row["decision_exact"]) for row in rows) / count
            if count
            else 0.0
        ),
        "road_set_exact": (
            sum(bool(row["road_set_exact"]) for row in rows) / count
            if count
            else 0.0
        ),
        "complete_exact": (
            sum(bool(row["complete_exact"]) for row in rows) / count
            if count
            else 0.0
        ),
        "road_macro_f1": (
            sum(float(row["road_f1"]) for row in rows) / count
            if count
            else 0.0
        ),
        "ownership_accuracy": (
            sum(
                int(row.get("ownership_correct_count") or 0)
                for row in rows
            )
            / ownership_count
            if ownership_count
            else 0.0
        ),
        "ownership_example_exact": (
            sum(bool(row.get("ownership_exact")) for row in rows)
            / sum(
                int(int(row.get("ownership_label_count") or 0) > 0)
                for row in rows
            )
            if ownership_count
            else 0.0
        ),
        "ownership_classes": ownership_classes,
        "business_role_accuracy": (
            sum(
                int(row.get("business_role_correct_count") or 0)
                for row in rows
            )
            / business_role_count
            if business_role_count
            else 0.0
        ),
        "business_role_example_exact": (
            sum(bool(row.get("business_role_exact")) for row in rows)
            / sum(
                int(int(row.get("business_role_label_count") or 0) > 0)
                for row in rows
            )
            if business_role_count
            else 0.0
        ),
        "business_role_classes": business_role_classes,
        "component_edge_precision": component_edge_precision,
        "component_edge_recall": component_edge_recall,
        "component_edge_f1": (
            2.0
            * component_edge_precision
            * component_edge_recall
            / (component_edge_precision + component_edge_recall)
            if component_edge_precision + component_edge_recall
            else 0.0
        ),
        "teacher_complete_exact": (
            sum(bool(row.get("teacher_complete_exact")) for row in rows)
            / count
            if count
            else 0.0
        ),
        "release_eligible_count": sum(
            bool(row["release_eligible"]) for row in rows
        ),
        "automatic_count": len(automatic),
        "automatic_coverage": len(automatic) / count if count else 0.0,
        "automatic_exact": (
            sum(bool(row["complete_exact"]) for row in automatic)
            / len(automatic)
            if automatic
            else 0.0
        ),
        "unsafe_automatic_count": len(unsafe),
        "case_count": len(per_case),
        "worst_case_complete_exact": (
            min(case_exact.values()) if case_exact else 0.0
        ),
    }


def _fit_model(
    training: Sequence[OrdinaryRoadSetExample],
    validation: Sequence[OrdinaryRoadSetExample],
    *,
    object_dim: int,
    candidate_dim: int,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
    seed: int,
) -> dict[str, Any]:
    model = _new_model(object_dim, candidate_dim, config, device)
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
    training: Sequence[OrdinaryRoadSetExample],
    *,
    object_dim: int,
    candidate_dim: int,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
    seed: int,
    epoch_count: int,
) -> dict[str, Any]:
    model = _new_model(object_dim, candidate_dim, config, device)
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
                "epoch": float(epoch),
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
    return {"model": model, "history": history}


def _new_model(
    object_dim: int,
    candidate_dim: int,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
) -> OrdinaryRoadSetModel:
    model_class = (
        TargetAOrdinaryAnchorRoadRoleGraphDecoder
        if config.ownership_role_decoder
        else TargetAOrdinaryAnchorRoadGraphDecoder
        if config.anchor_relation_decoder
        else TargetAOrdinaryJointRoadGraphDecoder
        if config.structured_graph_decoder
        else TargetAOrdinaryRoadSetDecoder
    )
    return model_class(
        object_feature_dim=object_dim,
        candidate_feature_dim=candidate_dim,
        hidden_dim=config.hidden_dim,
        context_dim=config.context_dim,
        **(
            {
                "graph_layers": config.graph_layers,
                "num_heads": config.graph_heads,
                "attention_scope": config.graph_attention_scope,
                "road_relation_dim": config.road_relation_dim,
                "road_relation_attention_bias": (
                    config.road_relation_attention_bias
                ),
                "road_relation_graph_adjacency": (
                    config.road_relation_graph_adjacency
                ),
            }
            if config.structured_graph_decoder
            else {}
        ),
        **(
            {
                "ownership_count": len(ROAD_OWNERSHIP_LABELS),
                "business_role_count": len(ROAD_BUSINESS_ROLE_LABELS),
                "fuse_business_into_membership": (
                    config.business_member_fusion
                ),
                "component_edge_decoder": (
                    config.component_edge_decoder
                ),
            }
            if config.ownership_role_decoder
            else {}
        ),
        cardinality_count=config.cardinality_count,
        dropout=config.dropout,
    ).to(device)


def _forward_model(
    model: OrdinaryRoadSetModel,
    batch: Mapping[str, torch.Tensor],
) -> dict[str, torch.Tensor]:
    common = {
        "object_features": batch["objects"],
        "candidate_features": batch["candidates"],
        "candidate_mask": batch["mask"],
    }
    graph_adjacency = (
        batch["adjacency"]
        if getattr(model, "road_relation_graph_adjacency", True)
        else batch["endpoint_adjacency"]
    )
    if isinstance(model, TargetAOrdinaryAnchorRoadGraphDecoder):
        component_inputs = (
            {"component_adjacency": batch["component_adjacency"]}
            if isinstance(
                model,
                TargetAOrdinaryAnchorRoadRoleGraphDecoder,
            )
            else {}
        )
        return model(
            **common,
            **component_inputs,
            adjacency=graph_adjacency,
            road_relations=batch["road_relations"],
            anchor_features=batch["anchors"],
            anchor_mask=batch["anchor_mask"],
            anchor_relations=batch["anchor_relations"],
        )
    if isinstance(model, TargetAOrdinaryJointRoadGraphDecoder):
        return model(
            **common,
            adjacency=graph_adjacency,
            road_relations=batch["road_relations"],
        )
    return model(**common)


def _cardinality_class_weights(
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
) -> torch.Tensor | None:
    if config.cardinality_class_weight_cap <= 0.0:
        return None
    counts = Counter()
    total = 0.0
    for row in examples:
        target = min(
            len(row.target_indices),
            config.cardinality_count - 1,
        )
        weight = max(0.0, float(row.sample_weight))
        counts[target] += weight
        total += weight
    observed = max(len(counts), 1)
    values = [
        min(
            config.cardinality_class_weight_cap,
            max(
                0.25,
                total / (observed * max(counts[index], 1e-6)),
            ),
        )
        for index in range(config.cardinality_count)
    ]
    return torch.tensor(values, dtype=torch.float32, device=device)


def _train_epoch(
    model: OrdinaryRoadSetModel,
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    optimizer: torch.optim.Optimizer,
    config: OrdinaryRoadSetTrainingConfig,
    device: torch.device,
    seed: int,
    cardinality_weights: torch.Tensor | None,
) -> float:
    model.train()
    training_views = [
        (index, feature_source, view_weight)
        for index in range(len(examples))
        for feature_source, view_weight in (
            ("teacher", config.teacher_training_loss_weight),
            ("oof", config.oof_training_loss_weight),
        )
        if view_weight > 0.0
    ]
    order = list(range(len(training_views)))
    random.Random(seed).shuffle(order)
    total = 0.0
    weight_total = 0.0
    for start in range(0, len(order), config.batch_size):
        batch_views = [
            training_views[index]
            for index in order[start : start + config.batch_size]
        ]
        rows = [examples[index] for index, _, _ in batch_views]
        batch = _batch_tensors(
            rows,
            feature_source=[source for _, source, _ in batch_views],
            sample_weight_multipliers=[
                weight for _, _, weight in batch_views
            ],
            device=device,
            cardinality_count=config.cardinality_count,
            road_relation_dim=config.road_relation_dim,
        )
        optimizer.zero_grad(set_to_none=True)
        outputs = _forward_model(model, batch)
        raw = _loss_rows(
            outputs,
            batch,
            config,
            cardinality_weights=cardinality_weights,
        )
        loss = (raw * batch["weights"]).sum() / batch[
            "weights"
        ].sum().clamp_min(1e-6)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        optimizer.step()
        total += float((raw.detach() * batch["weights"]).sum().item())
        weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _evaluate_loss(
    model: OrdinaryRoadSetModel,
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
            batch = _batch_tensors(
                rows,
                feature_source=(
                    "oof" if config.oof_early_stopping else "teacher"
                ),
                device=device,
                cardinality_count=config.cardinality_count,
                road_relation_dim=config.road_relation_dim,
            )
            outputs = _forward_model(model, batch)
            raw = _loss_rows(
                outputs,
                batch,
                config,
                cardinality_weights=cardinality_weights,
            )
            total += float((raw * batch["weights"]).sum().item())
            weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _loss_rows(
    outputs: Mapping[str, torch.Tensor],
    batch: Mapping[str, torch.Tensor],
    config: OrdinaryRoadSetTrainingConfig,
    *,
    cardinality_weights: torch.Tensor | None,
) -> torch.Tensor:
    decision = nn.functional.cross_entropy(
        outputs["decision_logits"],
        batch["decisions"],
        reduction="none",
    )
    cardinality = nn.functional.cross_entropy(
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
    cardinality_ordinal = nn.functional.smooth_l1_loss(
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
    total = (
        config.decision_loss_weight * decision
        + config.cardinality_loss_weight * cardinality
        + config.cardinality_ordinal_loss_weight * cardinality_ordinal
        + config.member_loss_weight * members
    )
    if config.ownership_role_decoder:
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
            total
            + config.ownership_loss_weight
            * ownership
            * batch["ownership_weight_ratios"]
            + config.business_role_loss_weight
            * business_role
            * batch["business_role_weight_ratios"]
        )
    if config.component_edge_decoder:
        component_edges = balanced_component_edge_bce(
            outputs["component_edge_logits"],
            batch["component_edge_targets"],
            batch["component_edge_task_mask"],
        )
        total = (
            total
            + config.component_edge_loss_weight * component_edges
        )
    return total


def _batch_tensors(
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    feature_source: str | Sequence[str],
    sample_weight_multipliers: Sequence[float] | None = None,
    device: torch.device,
    cardinality_count: int,
    road_relation_dim: int,
) -> dict[str, torch.Tensor]:
    candidate_count = max(len(row.road_ids) for row in examples)
    feature_sources = (
        [feature_source] * len(examples)
        if isinstance(feature_source, str)
        else list(feature_source)
    )
    if len(feature_sources) != len(examples) or any(
        value not in {"teacher", "oof"} for value in feature_sources
    ):
        raise ValueError("ordinary Road-set feature sources are invalid")
    weight_multipliers = (
        [1.0] * len(examples)
        if sample_weight_multipliers is None
        else [float(value) for value in sample_weight_multipliers]
    )
    if len(weight_multipliers) != len(examples) or min(
        weight_multipliers,
        default=0.0,
    ) < 0.0:
        raise ValueError("ordinary Road-set sample multipliers are invalid")
    features = [
        row.teacher_features if source == "teacher" else row.oof_features
        for row, source in zip(examples, feature_sources)
    ]
    anchor_relation_rows = [
        (
            row.teacher_anchor_relations
            if source == "teacher"
            else row.oof_anchor_relations
        )
        for row, source in zip(examples, feature_sources)
    ]
    candidate_dim = len(features[0][0])
    anchor_count = max(
        1,
        max(len(row.anchor_features) for row in examples),
    )
    anchor_feature_dim = max(
        (
            len(value)
            for row in examples
            for value in row.anchor_features
        ),
        default=3,
    )
    anchor_relation_dim = max(
        (
            len(value)
            for relations in anchor_relation_rows
            for candidate in relations
            for value in candidate
        ),
        default=4,
    )
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
    adjacency = torch.zeros(
        len(examples),
        candidate_count,
        candidate_count,
        dtype=torch.bool,
        device=device,
    )
    endpoint_adjacency = torch.zeros_like(adjacency)
    road_relations = torch.zeros(
        len(examples),
        candidate_count,
        candidate_count,
        road_relation_dim,
        dtype=torch.float32,
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
    ownership_task_mask = torch.zeros_like(mask)
    business_role_targets = torch.zeros_like(ownership_targets)
    business_role_task_mask = torch.zeros_like(mask)
    anchors = torch.zeros(
        len(examples),
        anchor_count,
        anchor_feature_dim,
        dtype=torch.float32,
        device=device,
    )
    anchor_mask = torch.zeros(
        len(examples),
        anchor_count,
        dtype=torch.bool,
        device=device,
    )
    anchor_relations = torch.zeros(
        len(examples),
        candidate_count,
        anchor_count,
        anchor_relation_dim,
        dtype=torch.float32,
        device=device,
    )
    for index, (row, values) in enumerate(zip(examples, features)):
        length = len(values)
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
        if len(member_weights) != length or min(
            member_weights,
            default=0.0,
        ) < 0.0:
            raise ValueError("ordinary Road member weights differ")
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
        ownership_task_mask[index, :length] = torch.tensor(
            row.ownership_task_mask,
            dtype=torch.bool,
            device=device,
        )
        business_role_targets[index, :length] = torch.tensor(
            row.business_role_targets,
            dtype=torch.long,
            device=device,
        )
        business_role_task_mask[index, :length] = torch.tensor(
            row.business_role_task_mask,
            dtype=torch.bool,
            device=device,
        )
        if row.road_relations:
            if any(
                not 0 <= left < length
                or not 0 <= right < length
                or left == right
                or len(relation_values) != road_relation_dim
                for left, right, relation_values in row.road_relations
            ):
                raise ValueError(
                    "ordinary Road relation alignment differs"
                )
            left_indices = torch.tensor(
                [left for left, _, _ in row.road_relations],
                dtype=torch.long,
                device=device,
            )
            right_indices = torch.tensor(
                [right for _, right, _ in row.road_relations],
                dtype=torch.long,
                device=device,
            )
            relation_values_tensor = torch.tensor(
                [
                    relation_values
                    for _, _, relation_values in row.road_relations
                ],
                dtype=torch.float32,
                device=device,
            )
            road_relations[index, left_indices, right_indices] = (
                relation_values_tensor
            )
            road_relations[index, right_indices, left_indices] = (
                relation_values_tensor
            )
            adjacency[index, left_indices, right_indices] = True
            adjacency[index, right_indices, left_indices] = True
        if row.anchor_features:
            anchor_length = len(row.anchor_features)
            anchors[index, :anchor_length] = torch.tensor(
                row.anchor_features,
                dtype=torch.float32,
                device=device,
            )
            anchor_mask[index, :anchor_length] = True
            relations = anchor_relation_rows[index]
            if len(relations) != length or any(
                len(candidate) != anchor_length
                for candidate in relations
            ):
                raise ValueError(
                    "ordinary anchor-Road relation alignment differs"
                )
            anchor_relations[
                index,
                :length,
                :anchor_length,
            ] = torch.tensor(
                relations,
                dtype=torch.float32,
                device=device,
            )
        endpoint_sets = [
            {row.start_node_ids[value], row.end_node_ids[value]}
            for value in range(length)
        ]
        for left in range(length):
            for right in range(left + 1, length):
                if endpoint_sets[left] & endpoint_sets[right]:
                    adjacency[index, left, right] = True
                    adjacency[index, right, left] = True
                    endpoint_adjacency[index, left, right] = True
                    endpoint_adjacency[index, right, left] = True
    component_adjacency = adjacency.clone()
    for index, row in enumerate(examples):
        source_index: dict[str, int] = {}
        source_values = []
        for source in row.sources:
            if source not in source_index:
                source_index[source] = len(source_index)
            source_values.append(source_index[source])
        source_tensor = torch.tensor(
            source_values,
            dtype=torch.long,
            device=device,
        )
        length = len(source_values)
        same_source = (
            source_tensor.unsqueeze(0) == source_tensor.unsqueeze(1)
        )
        component_adjacency[index, :length, :length] &= same_source
    component_edge_targets = targets.unsqueeze(1) & targets.unsqueeze(2)
    upper_triangle = torch.triu(
        torch.ones(
            candidate_count,
            candidate_count,
            dtype=torch.bool,
            device=device,
        ),
        diagonal=1,
    )
    component_edge_task_mask = (
        component_adjacency & upper_triangle.unsqueeze(0)
    )
    return {
        "objects": objects,
        "candidates": candidates,
        "mask": mask,
        "adjacency": adjacency,
        "endpoint_adjacency": endpoint_adjacency,
        "component_adjacency": component_adjacency,
        "component_edge_targets": component_edge_targets,
        "component_edge_task_mask": component_edge_task_mask,
        "road_relations": road_relations,
        "targets": targets,
        "member_weight_ratios": member_weight_ratios,
        "ownership_targets": ownership_targets,
        "ownership_task_mask": ownership_task_mask,
        "business_role_targets": business_role_targets,
        "business_role_task_mask": business_role_task_mask,
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
        "anchors": anchors,
        "anchor_mask": anchor_mask,
        "anchor_relations": anchor_relations,
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
        "weights": torch.tensor(
            [
                row.sample_weight * multiplier
                for row, multiplier in zip(examples, weight_multipliers)
            ],
            dtype=torch.float32,
            device=device,
        ),
    }


def _save_checkpoint(
    path: Path,
    model: OrdinaryRoadSetModel,
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
                "ORDINARY_ANCHOR_ROAD_GRAPH_DECODER"
                if config.anchor_relation_decoder
                else "ORDINARY_JOINT_ROAD_GRAPH_DECODER"
                if config.structured_graph_decoder
                else "ORDINARY_ROAD_SET_DECODER"
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
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _assert_case_disjoint(
    training: Sequence[OrdinaryRoadSetExample],
    validation: Sequence[OrdinaryRoadSetExample],
) -> None:
    overlap = {row.case_key for row in training} & {
        row.case_key for row in validation
    }
    if overlap:
        raise ValueError(
            f"ordinary Road-set Case leakage: {sorted(overlap)[:5]}"
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
    "DECISIONS",
    "OrdinaryRoadSetExample",
    "OrdinaryRoadSetTrainingConfig",
    "balanced_member_bce",
    "choose_zero_exact_error_threshold",
    "ordinary_road_set_metrics",
    "read_ordinary_road_set_examples",
    "run_ordinary_road_set_strict_nested_oof",
    "score_ordinary_road_set_examples",
]
