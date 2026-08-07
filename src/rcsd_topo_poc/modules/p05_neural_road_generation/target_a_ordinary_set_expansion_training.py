from __future__ import annotations

import copy
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import torch
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISIONS,
    OrdinaryRoadSetExample,
    _assert_case_disjoint,
    _batch_tensors,
    _forward_model,
    _input_record,
    _write_json,
    _write_jsonl,
    choose_zero_exact_error_threshold,
    ordinary_road_set_metrics,
    read_ordinary_road_set_examples,
    score_ordinary_road_set_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_network import (
    TargetAOrdinarySetExpansionDecoder,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


@dataclass(frozen=True)
class SetExpansionTrainingConfig:
    cardinality_count: int = 67
    road_relation_dim: int = 13
    batch_size: int = 32
    encode_batch_size: int = 32
    maximum_epochs: int = 24
    patience: int = 4
    learning_rate: float = 6e-4
    weight_decay: float = 2e-4
    teacher_view_weight: float = 0.5
    oof_view_weight: float = 1.0
    prefix_state_count: int = 4
    frontier_teacher_forcing: bool = False
    component_action_decoder: bool = False
    remaining_vs_stop_weight: float = 0.0
    remaining_vs_stop_margin: float = 0.0
    stop_logit_bias_candidates: tuple[float, ...] = (0.0,)
    torch_num_threads: int = 4

    def validate(self) -> None:
        if min(
            self.cardinality_count,
            self.road_relation_dim,
            self.batch_size,
            self.encode_batch_size,
            self.maximum_epochs,
            self.patience,
            self.learning_rate,
            self.prefix_state_count,
        ) <= 0:
            raise ValueError("set expansion training config is invalid")
        if min(self.teacher_view_weight, self.oof_view_weight) < 0.0:
            raise ValueError("set expansion view weight is invalid")
        if self.prefix_state_count < 4:
            raise ValueError("set expansion needs at least four prefix states")
        if min(
            self.remaining_vs_stop_weight,
            self.remaining_vs_stop_margin,
        ) < 0.0:
            raise ValueError("set expansion STOP-ranking config is invalid")
        if not self.stop_logit_bias_candidates or any(
            not math.isfinite(float(value))
            for value in self.stop_logit_bias_candidates
        ):
            raise ValueError("set expansion STOP-bias candidates are invalid")


DEFAULT_SET_EXPANSION_CONFIG = SetExpansionTrainingConfig()


@dataclass(frozen=True)
class _CachedExpansionView:
    row: OrdinaryRoadSetExample
    feature_source: str
    candidate_encoded: torch.Tensor
    graph_context: torch.Tensor
    road_relations: torch.Tensor
    target_mask: torch.Tensor
    allowed_mask: torch.Tensor
    access_seed_mask: torch.Tensor
    weight: float


def run_ordinary_set_expansion_strict_nested_oof(
    *,
    member_store_root: Path,
    base_checkpoint_root: Path,
    output_root: Path,
    seed: int,
    requested_device: str = "cuda",
    outer_folds: Sequence[int] | None = None,
    config: SetExpansionTrainingConfig = DEFAULT_SET_EXPANSION_CONFIG,
) -> Path:
    """Train a frozen-encoder, order-free autoregressive Road-set decoder."""
    started = time.perf_counter()
    config.validate()
    store = normalize_runtime_path(member_store_root).resolve(strict=True)
    base_root = normalize_runtime_path(base_checkpoint_root).resolve(
        strict=True
    )
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    examples, read_summary = read_ordinary_road_set_examples(store)
    if int(read_summary["road_relation_feature_dim"]) != config.road_relation_dim:
        raise ValueError("set expansion Road relation dimension differs")
    all_folds = sorted({row.fold for row in examples})
    selected_folds = (
        all_folds
        if outer_folds is None
        else sorted({int(value) for value in outer_folds})
    )
    if not selected_folds or any(value not in all_folds for value in selected_folds):
        raise ValueError("set expansion outer folds differ")
    root.mkdir(parents=True)
    torch.set_num_threads(config.torch_num_threads)
    device = _resolve_device(requested_device)
    object_dim = len(examples[0].object_features)
    candidate_dim = len(examples[0].teacher_features[0])
    anchor_dim = max(
        (
            len(value)
            for row in examples
            for value in row.anchor_features
        ),
        default=3,
    )
    anchor_relation_dim = max(
        (
            len(values)
            for row in examples
            for candidate in row.teacher_anchor_relations
            for values in candidate
        ),
        default=4,
    )
    predictions: list[dict[str, Any]] = []
    fold_summaries = []
    trainable_parameters = 0
    model_parameters = 0
    for outer_fold in selected_folds:
        inner_fold = all_folds[
            (all_folds.index(outer_fold) + 1) % len(all_folds)
        ]
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
            checkpoint_path=base_root
            / f"fold_{outer_fold}_inner_checkpoint.pt",
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            anchor_dim=anchor_dim,
            anchor_relation_dim=anchor_relation_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 17,
        )
        final = _fit_fixed_epochs(
            outer_training,
            checkpoint_path=base_root
            / f"fold_{outer_fold}_checkpoint.pt",
            object_dim=object_dim,
            candidate_dim=candidate_dim,
            anchor_dim=anchor_dim,
            anchor_relation_dim=anchor_relation_dim,
            config=config,
            device=device,
            seed=seed + outer_fold * 100 + 53,
            epoch_count=tuning["best_epoch"],
        )
        model_parameters = parameter_count(final["model"])
        trainable_parameters = sum(
            value.numel()
            for value in final["model"].parameters()
            if value.requires_grad
        )
        stop_bias_selection = _choose_stop_logit_bias(
            tuning["model"],
            inner_validation,
            feature_source="oof",
            batch_size=config.encode_batch_size,
            device=device,
            candidates=config.stop_logit_bias_candidates,
        )
        inner_scores = stop_bias_selection["scores"]
        stop_logit_bias = float(stop_bias_selection["selected_bias"])
        threshold = choose_zero_exact_error_threshold(inner_scores)
        outer_scores = score_set_expansion_examples(
            final["model"],
            outer_validation,
            feature_source="oof",
            batch_size=config.encode_batch_size,
            device=device,
            stop_logit_bias=stop_logit_bias,
        )
        decoded = []
        for score in outer_scores:
            row = dict(score)
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
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
            stop_logit_bias=stop_logit_bias,
        )
        _save_checkpoint(
            final["model"],
            outer_checkpoint,
            config=config,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            epoch_count=tuning["best_epoch"],
            stop_logit_bias=stop_logit_bias,
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
            "selected_stop_logit_bias": stop_logit_bias,
            "stop_logit_bias_audit": stop_bias_selection["audit"],
            "metrics": ordinary_road_set_metrics(decoded),
            "inner_history": tuning["history"],
            "outer_history": final["history"],
            "inner_cache_seconds": tuning["cache_seconds"],
            "outer_cache_seconds": final["cache_seconds"],
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
    full_oof = selected_folds == all_folds
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_SET_EXPANSION_STRICT_NESTED_OOF",
        "decoder_kind": (
            "COMPONENT_ACTION_AUTOREGRESSIVE_ROAD_SET"
            if config.component_action_decoder
            else "ORDER_FREE_AUTOREGRESSIVE_ROAD_SET"
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
        "config": config.__dict__,
        "selected_outer_folds": selected_folds,
        "available_folds": all_folds,
        "full_oof": full_oof,
        "example_count": len(examples),
        "prediction_count": len(predictions),
        "parameter_count": model_parameters,
        "trainable_parameter_count": trainable_parameters,
        "read_summary": read_summary,
        "metrics": ordinary_road_set_metrics(predictions),
        "folds": fold_summaries,
        "feature_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "encoder_frozen": True,
        "encoder_cache_contract": (
            "Each strict-fold v175 encoder evaluates inference-time "
            "teacher/OOF features once. Detached Road embeddings and graph "
            "contexts are reused only by the expansion head."
        ),
        "expansion_contract": (
            "Every remaining truth Road is an admissible next action during "
            "teacher forcing. STOP is correct only after the full set. "
            "Inference is greedy and never reads truth cardinality."
        ),
        "state_sampling_contract": (
            f"Each training view uses up to {config.prefix_state_count} "
            "order-free target prefixes. When the configured count exceeds "
            "four, all prefixes are used for small sets and evenly spaced "
            "plus late prefixes are used for larger sets. Remaining truth "
            "Roads may additionally be ranked above STOP. "
            + (
                "Training prefixes start from a source/target arm anchor "
                "Road and expand over exact endpoint relations before "
                "starting another component. "
                if config.frontier_teacher_forcing
                else ""
            )
            + "Inference remains truth-free."
        ),
        "stop_calibration_contract": (
            "Each outer fold selects one declared STOP-logit bias using only "
            "its disjoint inner validation fold. The selected value is then "
            "frozen for the held-out outer fold and saved in its checkpoint."
        ),
        "component_action_contract": (
            "The decoder separately scores CONTINUE_FRONTIER, "
            "START_COMPONENT and STOP. Road probabilities are normalized "
            "inside their truth-free action group, so candidate count does "
            "not change action mass."
            if config.component_action_decoder
            else "DISABLED"
        ),
        "source_gate": (
            "KEEP_SWSD permits SWSD only; ordinary USE_RCSD permits RCSD "
            "only. Explicit T06 mixed targets are excluded from expansion "
            "loss and remain fallback-only in this decoder version."
        ),
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "This is an ordinary decoder experiment; full OOF, access, "
            "AdvanceRight and complete RoadGraph safety are not all passed."
        ),
        "gate_pass": len(predictions)
        == sum(row.fold in selected_folds for row in examples),
        "member_store_summary": _input_record(store / "summary.json"),
        "base_checkpoint_summary": _input_record(base_root / "summary.json"),
        "predictions": _input_record(prediction_path),
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("set expansion OOF coverage gate failed")
    return root


def _new_model(
    *,
    checkpoint_path: Path,
    object_dim: int,
    candidate_dim: int,
    anchor_dim: int,
    anchor_relation_dim: int,
    config: SetExpansionTrainingConfig,
    device: torch.device,
    seed: int,
) -> TargetAOrdinarySetExpansionDecoder:
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    model = TargetAOrdinarySetExpansionDecoder(
        object_feature_dim=object_dim,
        candidate_feature_dim=candidate_dim,
        anchor_feature_dim=anchor_dim,
        anchor_relation_dim=anchor_relation_dim,
        road_relation_dim=config.road_relation_dim,
        cardinality_count=config.cardinality_count,
        component_action_decoder=config.component_action_decoder,
    ).to(device)
    payload = torch.load(
        checkpoint_path,
        map_location=device,
        weights_only=False,
    )
    missing, unexpected = model.load_state_dict(
        payload["state_dict"],
        strict=False,
    )
    allowed_missing = {
        key
        for key in model.state_dict()
        if key.startswith(
            (
                "next_road_head.",
                "stop_head.",
                "component_action_head.",
            )
        )
    }
    if set(missing) != allowed_missing or unexpected:
        raise ValueError(
            "set expansion base checkpoint is incompatible: "
            f"missing={missing}, unexpected={unexpected}"
        )
    for name, value in model.named_parameters():
        value.requires_grad = name.startswith(
            (
                "next_road_head.",
                "stop_head.",
                "component_action_head.",
            )
        )
    model.eval()
    return model


def _cache_views(
    model: TargetAOrdinarySetExpansionDecoder,
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    feature_sources: Sequence[tuple[str, float]],
    config: SetExpansionTrainingConfig,
    device: torch.device,
) -> list[_CachedExpansionView]:
    model.eval()
    relation_cache: dict[
        tuple[str, str], torch.Tensor
    ] = {}
    result = []
    with torch.no_grad():
        for feature_source, view_weight in feature_sources:
            if view_weight <= 0.0:
                continue
            for start in range(0, len(examples), config.encode_batch_size):
                rows = examples[start : start + config.encode_batch_size]
                batch = _batch_tensors(
                    rows,
                    feature_source=feature_source,
                    device=device,
                    cardinality_count=config.cardinality_count,
                    road_relation_dim=config.road_relation_dim,
                )
                outputs = _forward_model(model, batch)
                for index, row in enumerate(rows):
                    length = len(row.road_ids)
                    key = (row.case_key, row.segment_id)
                    relations = relation_cache.get(key)
                    if relations is None:
                        relations = (
                            batch["road_relations"][
                                index, :length, :length
                            ]
                            .detach()
                            .to("cpu")
                            .contiguous()
                        )
                        relation_cache[key] = relations
                    target = torch.zeros(length, dtype=torch.bool)
                    target[list(row.target_indices)] = True
                    allowed = torch.tensor(
                        [
                            source
                            == ("SWSD" if row.decision == 0 else "RCSD")
                            for source in row.sources
                        ],
                        dtype=torch.bool,
                    )
                    access_seed = _row_access_seed_mask(
                        row,
                        feature_source=feature_source,
                    )
                    if not bool((target & ~allowed).any()):
                        cardinality_weight = _cardinality_weight(
                            len(row.target_indices)
                        )
                        result.append(
                            _CachedExpansionView(
                                row=row,
                                feature_source=feature_source,
                                candidate_encoded=outputs[
                                    "candidate_encoded"
                                ][index, :length]
                                .detach()
                                .to("cpu")
                                .contiguous(),
                                graph_context=outputs["graph_context"][
                                    index
                                ]
                                .detach()
                                .to("cpu")
                                .contiguous(),
                                road_relations=relations,
                                target_mask=target,
                                allowed_mask=allowed,
                                access_seed_mask=access_seed,
                                weight=(
                                    row.sample_weight
                                    * view_weight
                                    * cardinality_weight
                                ),
                            )
                        )
                del batch, outputs
    return result


def _cardinality_weight(cardinality: int) -> float:
    if cardinality >= 10:
        return 3.0
    if cardinality >= 6:
        return 2.0
    if cardinality >= 3:
        return 1.5
    return 1.0


def _row_access_seed_mask(
    row: OrdinaryRoadSetExample,
    *,
    feature_source: str,
) -> torch.Tensor:
    view_anchor_relations = (
        row.teacher_anchor_relations
        if feature_source == "teacher"
        else row.oof_anchor_relations
    )
    return torch.tensor(
        [
            any(
                anchor_index < len(row.anchor_features)
                and sum(row.anchor_features[anchor_index][:2]) > 0.5
                and len(values) > 3
                and (
                    float(values[0]) > 0.5
                    or float(values[3]) > 0.5
                )
                for anchor_index, values in enumerate(
                    candidate_relations
                )
            )
            for candidate_relations in view_anchor_relations
        ],
        dtype=torch.bool,
    )


def _fit_model(
    training: Sequence[OrdinaryRoadSetExample],
    validation: Sequence[OrdinaryRoadSetExample],
    *,
    checkpoint_path: Path,
    object_dim: int,
    candidate_dim: int,
    anchor_dim: int,
    anchor_relation_dim: int,
    config: SetExpansionTrainingConfig,
    device: torch.device,
    seed: int,
) -> dict[str, Any]:
    model = _new_model(
        checkpoint_path=checkpoint_path,
        object_dim=object_dim,
        candidate_dim=candidate_dim,
        anchor_dim=anchor_dim,
        anchor_relation_dim=anchor_relation_dim,
        config=config,
        device=device,
        seed=seed,
    )
    cache_started = time.perf_counter()
    train_views = _cache_views(
        model,
        training,
        feature_sources=(
            ("teacher", config.teacher_view_weight),
            ("oof", config.oof_view_weight),
        ),
        config=config,
        device=device,
    )
    validation_views = _cache_views(
        model,
        validation,
        feature_sources=(("oof", 1.0),),
        config=config,
        device=device,
    )
    cache_seconds = time.perf_counter() - cache_started
    optimizer = torch.optim.AdamW(
        [
            value
            for value in model.parameters()
            if value.requires_grad
        ],
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    best_state = {
        key: copy.deepcopy(value)
        for key, value in model.state_dict().items()
        if key.startswith(
            (
                "next_road_head.",
                "stop_head.",
                "component_action_head.",
            )
        )
    }
    best_loss = float("inf")
    best_epoch = 1
    stale = 0
    history = []
    for epoch in range(1, config.maximum_epochs + 1):
        train_loss = _train_epoch(
            model,
            train_views,
            optimizer=optimizer,
            config=config,
            device=device,
            seed=seed + epoch,
        )
        validation_loss = _evaluate_loss(
            model,
            validation_views,
            config=config,
            device=device,
            seed=seed + 10000,
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
            best_state = {
                key: copy.deepcopy(value)
                for key, value in model.state_dict().items()
                if key.startswith(
                    (
                        "next_road_head.",
                        "stop_head.",
                        "component_action_head.",
                    )
                )
            }
            stale = 0
        else:
            stale += 1
            if stale >= config.patience:
                break
    model.load_state_dict(best_state, strict=False)
    model.eval()
    return {
        "model": model,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "history": history,
        "cache_seconds": cache_seconds,
    }


def _fit_fixed_epochs(
    training: Sequence[OrdinaryRoadSetExample],
    *,
    checkpoint_path: Path,
    object_dim: int,
    candidate_dim: int,
    anchor_dim: int,
    anchor_relation_dim: int,
    config: SetExpansionTrainingConfig,
    device: torch.device,
    seed: int,
    epoch_count: int,
) -> dict[str, Any]:
    model = _new_model(
        checkpoint_path=checkpoint_path,
        object_dim=object_dim,
        candidate_dim=candidate_dim,
        anchor_dim=anchor_dim,
        anchor_relation_dim=anchor_relation_dim,
        config=config,
        device=device,
        seed=seed,
    )
    cache_started = time.perf_counter()
    train_views = _cache_views(
        model,
        training,
        feature_sources=(
            ("teacher", config.teacher_view_weight),
            ("oof", config.oof_view_weight),
        ),
        config=config,
        device=device,
    )
    cache_seconds = time.perf_counter() - cache_started
    optimizer = torch.optim.AdamW(
        [
            value
            for value in model.parameters()
            if value.requires_grad
        ],
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    history = []
    for epoch in range(1, epoch_count + 1):
        train_loss = _train_epoch(
            model,
            train_views,
            optimizer=optimizer,
            config=config,
            device=device,
            seed=seed + epoch,
        )
        history.append({"epoch": epoch, "train_loss": train_loss})
    model.eval()
    return {
        "model": model,
        "history": history,
        "cache_seconds": cache_seconds,
    }


def _collate_cached(
    views: Sequence[_CachedExpansionView],
    *,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    candidate_count = max(
        value.candidate_encoded.shape[0] for value in views
    )
    hidden_dim = views[0].candidate_encoded.shape[-1]
    relation_dim = views[0].road_relations.shape[-1]
    candidates = torch.zeros(
        len(views),
        candidate_count,
        hidden_dim,
        dtype=torch.float32,
        device=device,
    )
    contexts = torch.zeros(
        len(views),
        views[0].graph_context.shape[-1],
        dtype=torch.float32,
        device=device,
    )
    relations = torch.zeros(
        len(views),
        candidate_count,
        candidate_count,
        relation_dim,
        dtype=torch.float32,
        device=device,
    )
    targets = torch.zeros(
        len(views),
        candidate_count,
        dtype=torch.bool,
        device=device,
    )
    allowed = torch.zeros_like(targets)
    access_seeds = torch.zeros_like(targets)
    for index, value in enumerate(views):
        length = value.candidate_encoded.shape[0]
        candidates[index, :length] = value.candidate_encoded.to(device)
        contexts[index] = value.graph_context.to(device)
        relations[index, :length, :length] = value.road_relations.to(device)
        targets[index, :length] = value.target_mask.to(device)
        allowed[index, :length] = value.allowed_mask.to(device)
        access_seeds[index, :length] = value.access_seed_mask.to(device)
    return {
        "candidate_encoded": candidates,
        "graph_context": contexts,
        "road_relations": relations,
        "targets": targets,
        "allowed": allowed,
        "access_seeds": access_seeds,
        "weights": torch.tensor(
            [value.weight for value in views],
            dtype=torch.float32,
            device=device,
        ),
    }


def _prefix_masks(
    targets: torch.Tensor,
    *,
    seed: int,
    state_count: int = 4,
) -> tuple[torch.Tensor, torch.Tensor]:
    if state_count < 4:
        raise ValueError("set expansion needs at least four prefix states")
    generator = random.Random(seed)
    result = torch.zeros(
        targets.shape[0],
        state_count,
        targets.shape[1],
        dtype=torch.bool,
        device=targets.device,
    )
    state_weights = torch.ones(
        targets.shape[0],
        state_count,
        dtype=torch.float32,
        device=targets.device,
    )
    for index in range(targets.shape[0]):
        values = targets[index].nonzero(as_tuple=False).flatten().tolist()
        cardinality = len(values)
        if cardinality < 1:
            raise ValueError("set expansion target is empty")
        if state_count > 4:
            generator.shuffle(values)
            counts = _prefix_counts(
                cardinality,
                state_count=state_count,
            )
            state_weights[index] = 0.0
            for state, count in enumerate(counts):
                result[index, state, values[:count]] = True
                state_weights[index, state] = 1.0
            continue
        random_count = (
            generator.randrange(1, cardinality)
            if cardinality > 1
            else 0
        )
        late_count = max(0, cardinality - 1)
        generator.shuffle(values)
        result[index, 1, values[:random_count]] = True
        result[index, 2, values[:late_count]] = True
        result[index, 3, values] = True
        states = [
            tuple(result[index, state].nonzero().flatten().tolist())
            for state in range(4)
        ]
        for state in range(1, 4):
            if states[state] in states[:state]:
                state_weights[index, state] = 0.0
    return result, state_weights


def _prefix_counts(
    cardinality: int,
    *,
    state_count: int,
) -> list[int]:
    if cardinality < 1 or state_count < 4:
        raise ValueError("set expansion prefix-count request is invalid")
    if cardinality + 1 <= state_count:
        return list(range(cardinality + 1))
    counts = {0, 1, 2, cardinality}
    late_start = max(0, cardinality - min(7, state_count // 2))
    counts.update(range(late_start, cardinality + 1))
    for index in range(state_count):
        counts.add(round(index * cardinality / (state_count - 1)))
    ordered = sorted(counts)
    if len(ordered) <= state_count:
        return ordered
    required = {0, 1, 2, cardinality, cardinality - 1}
    optional = [value for value in ordered if value not in required]
    remaining = state_count - len(required)
    if remaining < 0:
        raise AssertionError("set expansion required prefixes overflow")
    if remaining and optional:
        chosen = {
            optional[
                round(index * (len(optional) - 1) / max(remaining - 1, 1))
            ]
            for index in range(remaining)
        }
        if len(chosen) < remaining:
            for value in reversed(optional):
                chosen.add(value)
                if len(chosen) == remaining:
                    break
    else:
        chosen = set()
    result = sorted(required | chosen)
    if len(result) != state_count:
        raise AssertionError("set expansion prefix sampling differs")
    return result


def _frontier_prefix_masks(
    targets: torch.Tensor,
    access_seeds: torch.Tensor,
    road_relations: torch.Tensor,
    *,
    seed: int,
    state_count: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    if (
        access_seeds.shape != targets.shape
        or road_relations.shape[:3]
        != (targets.shape[0], targets.shape[1], targets.shape[1])
        or road_relations.shape[-1] < 1
    ):
        raise ValueError("frontier prefix inputs differ")
    generator = random.Random(seed)
    result = torch.zeros(
        targets.shape[0],
        state_count,
        targets.shape[1],
        dtype=torch.bool,
        device=targets.device,
    )
    state_weights = torch.zeros(
        targets.shape[0],
        state_count,
        dtype=torch.float32,
        device=targets.device,
    )
    endpoint_relations = road_relations[..., 0] > 0.5
    for index in range(targets.shape[0]):
        remaining = set(
            targets[index].nonzero(as_tuple=False).flatten().tolist()
        )
        order: list[int] = []
        selected: set[int] = set()
        while remaining:
            frontier = {
                candidate
                for candidate in remaining
                if any(
                    bool(endpoint_relations[index, candidate, chosen])
                    for chosen in selected
                )
            }
            if frontier:
                choices = frontier
            else:
                seeded = {
                    candidate
                    for candidate in remaining
                    if bool(access_seeds[index, candidate])
                }
                choices = seeded or remaining
            chosen = generator.choice(sorted(choices))
            order.append(chosen)
            selected.add(chosen)
            remaining.remove(chosen)
        counts = _prefix_counts(
            len(order),
            state_count=state_count,
        )
        for state, count in enumerate(counts):
            result[index, state, order[:count]] = True
            state_weights[index, state] = 1.0
    return result, state_weights


def _frontier_acceptable_masks(
    targets: torch.Tensor,
    selected: torch.Tensor,
    access_seeds: torch.Tensor,
    road_relations: torch.Tensor,
) -> torch.Tensor:
    if selected.shape[:1] + selected.shape[2:] != targets.shape:
        raise ValueError("frontier selected-mask shape differs")
    remaining = targets.unsqueeze(1) & ~selected
    endpoint_relations = road_relations[..., 0] > 0.5
    frontier = (
        endpoint_relations.unsqueeze(1)
        & selected.unsqueeze(2)
    ).any(dim=-1) & remaining
    seeded = remaining & access_seeds.unsqueeze(1)
    has_selected = selected.any(dim=-1, keepdim=True)
    has_frontier = frontier.any(dim=-1, keepdim=True)
    has_seeded = seeded.any(dim=-1, keepdim=True)
    return torch.where(
        has_selected & has_frontier,
        frontier,
        torch.where(has_seeded, seeded, remaining),
    )


def _expansion_loss_rows(
    model: TargetAOrdinarySetExpansionDecoder,
    batch: dict[str, torch.Tensor],
    *,
    config: SetExpansionTrainingConfig,
    seed: int,
) -> torch.Tensor:
    if config.frontier_teacher_forcing:
        selected, state_weights = _frontier_prefix_masks(
            batch["targets"],
            batch["access_seeds"],
            batch["road_relations"],
            seed=seed,
            state_count=config.prefix_state_count,
        )
    else:
        selected, state_weights = _prefix_masks(
            batch["targets"],
            seed=seed,
            state_count=config.prefix_state_count,
        )
    outputs = model.decode_next(
        encoded_outputs={
            "candidate_encoded": batch["candidate_encoded"],
            "graph_context": batch["graph_context"],
        },
        candidate_mask=batch["allowed"],
        road_relations=batch["road_relations"],
        selected_masks=selected,
        access_seed_masks=batch["access_seeds"],
    )
    logits = torch.cat(
        (
            outputs["next_road_logits"],
            outputs["stop_logits"].unsqueeze(-1),
        ),
        dim=-1,
    )
    log_probabilities = torch.log_softmax(logits, dim=-1)
    remaining = batch["targets"].unsqueeze(1) & ~selected
    acceptable = torch.zeros_like(logits, dtype=torch.bool)
    acceptable[..., :-1] = (
        _frontier_acceptable_masks(
            batch["targets"],
            selected,
            batch["access_seeds"],
            batch["road_relations"],
        )
        if config.frontier_teacher_forcing
        else remaining
    )
    acceptable[..., -1] = ~remaining.any(dim=-1)
    selected_log_probability = torch.logsumexp(
        log_probabilities.masked_fill(
            ~acceptable,
            torch.finfo(log_probabilities.dtype).min,
        ),
        dim=-1,
    )
    state_losses = -selected_log_probability
    if config.remaining_vs_stop_weight > 0.0:
        currently_acceptable = acceptable[..., :-1]
        stop_differences = (
            outputs["stop_logits"].unsqueeze(-1)
            - outputs["next_road_logits"]
            + config.remaining_vs_stop_margin
        )
        remaining_count = currently_acceptable.sum(dim=-1)
        remaining_stop_loss = (
            F.softplus(stop_differences) * currently_acceptable
        ).sum(dim=-1) / remaining_count.clamp_min(1).to(
            stop_differences.dtype
        )
        remaining_stop_loss = torch.where(
            remaining_count > 0,
            remaining_stop_loss,
            torch.zeros_like(remaining_stop_loss),
        )
        state_losses = (
            state_losses
            + config.remaining_vs_stop_weight * remaining_stop_loss
        )
    return (
        state_losses * state_weights
    ).sum(dim=-1) / state_weights.sum(dim=-1).clamp_min(1.0)


def _bucketed_batches(
    views: Sequence[_CachedExpansionView],
    *,
    batch_size: int,
    seed: int,
) -> list[list[_CachedExpansionView]]:
    ordered = sorted(
        views,
        key=lambda value: value.candidate_encoded.shape[0],
    )
    buckets = [
        ordered[start : start + batch_size]
        for start in range(0, len(ordered), batch_size)
    ]
    generator = random.Random(seed)
    for values in buckets:
        generator.shuffle(values)
    generator.shuffle(buckets)
    return buckets


def _train_epoch(
    model: TargetAOrdinarySetExpansionDecoder,
    views: Sequence[_CachedExpansionView],
    *,
    optimizer: torch.optim.Optimizer,
    config: SetExpansionTrainingConfig,
    device: torch.device,
    seed: int,
) -> float:
    model.train()
    total = 0.0
    weight_total = 0.0
    for batch_index, values in enumerate(
        _bucketed_batches(
            views,
            batch_size=config.batch_size,
            seed=seed,
        )
    ):
        batch = _collate_cached(values, device=device)
        optimizer.zero_grad(set_to_none=True)
        raw = _expansion_loss_rows(
            model,
            batch,
            config=config,
            seed=seed * 100000 + batch_index,
        )
        if not bool(torch.isfinite(raw).all()):
            raise RuntimeError("set expansion training loss is non-finite")
        loss = (raw * batch["weights"]).sum() / batch[
            "weights"
        ].sum().clamp_min(1e-6)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            [
                value
                for value in model.parameters()
                if value.requires_grad
            ],
            2.0,
        )
        optimizer.step()
        total += float((raw.detach() * batch["weights"]).sum().item())
        weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _evaluate_loss(
    model: TargetAOrdinarySetExpansionDecoder,
    views: Sequence[_CachedExpansionView],
    *,
    config: SetExpansionTrainingConfig,
    device: torch.device,
    seed: int,
) -> float:
    model.eval()
    total = 0.0
    weight_total = 0.0
    with torch.no_grad():
        for batch_index, values in enumerate(
            _bucketed_batches(
                views,
                batch_size=config.batch_size,
                seed=seed,
            )
        ):
            batch = _collate_cached(values, device=device)
            raw = _expansion_loss_rows(
                model,
                batch,
                config=config,
                seed=seed * 100000 + batch_index,
            )
            if not bool(torch.isfinite(raw).all()):
                raise RuntimeError(
                    "set expansion validation loss is non-finite"
                )
            total += float((raw * batch["weights"]).sum().item())
            weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def score_set_expansion_examples(
    model: TargetAOrdinarySetExpansionDecoder,
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    feature_source: str,
    batch_size: int,
    device: torch.device,
    stop_logit_bias: float = 0.0,
) -> list[dict[str, Any]]:
    base_rows = score_ordinary_road_set_examples(
        model,
        examples,
        feature_source=feature_source,
        batch_size=batch_size,
        device=device,
        include_member_probabilities=True,
    )
    result = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            batch = _batch_tensors(
                rows,
                feature_source=feature_source,
                device=device,
                cardinality_count=model.cardinality_count,
                road_relation_dim=model.road_relation_dim,
            )
            outputs = _forward_model(model, batch)
            decision_probabilities = torch.softmax(
                outputs["decision_logits"],
                dim=-1,
            )
            decisions = decision_probabilities.argmax(dim=-1)
            allowed = torch.zeros_like(batch["mask"])
            access_seeds = torch.zeros_like(batch["mask"])
            for index, row in enumerate(rows):
                source = (
                    "SWSD" if int(decisions[index].item()) == 0 else "RCSD"
                )
                allowed[index, : len(row.sources)] = torch.tensor(
                    [value == source for value in row.sources],
                    dtype=torch.bool,
                    device=device,
                )
                access_seeds[index, : len(row.sources)] = (
                    _row_access_seed_mask(
                        row,
                        feature_source=feature_source,
                    ).to(device)
                )
            selected = torch.zeros_like(allowed)
            active = allowed.any(dim=-1)
            confidence = torch.ones(
                len(rows), dtype=torch.float32, device=device
            )
            margin = torch.ones_like(confidence)
            maximum_steps = int(allowed.sum(dim=-1).max().item()) + 1
            for _ in range(maximum_steps):
                if not bool(active.any()):
                    break
                step = model.decode_next(
                    encoded_outputs=outputs,
                    candidate_mask=allowed,
                    road_relations=batch["road_relations"],
                    selected_masks=selected,
                    access_seed_masks=access_seeds,
                )
                logits = torch.cat(
                    (
                        step["next_road_logits"].squeeze(1),
                        step["stop_logits"] + stop_logit_bias,
                    ),
                    dim=-1,
                )
                probabilities = torch.softmax(logits, dim=-1)
                top_values, top_indices = probabilities.topk(2, dim=-1)
                chosen = top_indices[:, 0]
                chosen_probability = top_values[:, 0]
                chosen_margin = top_values[:, 0] - top_values[:, 1]
                confidence = torch.where(
                    active,
                    torch.minimum(confidence, chosen_probability),
                    confidence,
                )
                margin = torch.where(
                    active,
                    torch.minimum(margin, chosen_margin),
                    margin,
                )
                stop = chosen == allowed.shape[1]
                add = active & ~stop
                if bool(add.any()):
                    selected[
                        add,
                        chosen[add],
                    ] = True
                active &= ~stop
            for index, row in enumerate(rows):
                base = dict(base_rows[start + index])
                selected_indices = (
                    selected[index, : len(row.road_ids)]
                    .nonzero(as_tuple=False)
                    .flatten()
                    .tolist()
                )
                target = set(row.target_indices)
                predicted = set(selected_indices)
                intersection = len(target & predicted)
                precision = (
                    intersection / len(predicted) if predicted else 0.0
                )
                recall = intersection / len(target) if target else 0.0
                f1 = (
                    2.0 * precision * recall / (precision + recall)
                    if precision + recall
                    else 0.0
                )
                road_exact = predicted == target
                decision_exact = int(decisions[index].item()) == row.decision
                base.update(
                    {
                        "selection_mode": "ORDER_FREE_SET_EXPANSION",
                        "stop_logit_bias": float(stop_logit_bias),
                        "member_probability_threshold": None,
                        "predicted_cardinality": len(selected_indices),
                        "selected_road_ids": [
                            row.road_ids[value]
                            for value in selected_indices
                        ],
                        "road_set_exact": road_exact,
                        "complete_exact": decision_exact and road_exact,
                        "road_precision": precision,
                        "road_recall": recall,
                        "road_f1": f1,
                        "cardinality_confidence": float(
                            confidence[index].item()
                        ),
                        "set_margin": float(margin[index].item()),
                        "confidence": float(
                            decision_probabilities[
                                index, decisions[index]
                            ].item()
                            * confidence[index].item()
                            * max(0.0, margin[index].item())
                        ),
                    }
                )
                ownership = base.get("candidate_predicted_ownership") or []
                roles = (
                    base.get("candidate_predicted_business_role") or []
                )
                base["selected_road_business_roles"] = [
                    {
                        "road_id": row.road_ids[value],
                        "ownership": ownership[value],
                        "business_role": roles[value],
                    }
                    for value in selected_indices
                    if value < len(ownership) and value < len(roles)
                ]
                for key in (
                    "candidate_road_ids",
                    "candidate_sources",
                    "candidate_member_probabilities",
                    "candidate_predicted_ownership",
                    "candidate_predicted_business_role",
                ):
                    base.pop(key, None)
                result.append(base)
    return result


def _choose_stop_logit_bias(
    model: TargetAOrdinarySetExpansionDecoder,
    examples: Sequence[OrdinaryRoadSetExample],
    *,
    feature_source: str,
    batch_size: int,
    device: torch.device,
    candidates: Sequence[float],
) -> dict[str, Any]:
    audit = []
    scored = {}
    for raw_bias in candidates:
        bias = float(raw_bias)
        scores = score_set_expansion_examples(
            model,
            examples,
            feature_source=feature_source,
            batch_size=batch_size,
            device=device,
            stop_logit_bias=bias,
        )
        metrics = ordinary_road_set_metrics(scores)
        audit.append(
            {
                "stop_logit_bias": bias,
                "complete_exact": float(metrics["complete_exact"]),
                "road_macro_f1": float(metrics["road_macro_f1"]),
                "decision_exact": float(metrics["decision_exact"]),
            }
        )
        scored[bias] = scores
    selected = max(
        audit,
        key=lambda row: (
            row["complete_exact"],
            row["road_macro_f1"],
            row["decision_exact"],
            -abs(row["stop_logit_bias"]),
            -row["stop_logit_bias"],
        ),
    )
    return {
        "selected_bias": selected["stop_logit_bias"],
        "scores": scored[selected["stop_logit_bias"]],
        "audit": audit,
    }


def _save_checkpoint(
    model: TargetAOrdinarySetExpansionDecoder,
    path: Path,
    *,
    config: SetExpansionTrainingConfig,
    outer_fold: int,
    inner_fold: int,
    epoch_count: int,
    stop_logit_bias: float,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ORDINARY_SET_EXPANSION_DECODER",
            "config": config.__dict__,
            "outer_fold": outer_fold,
            "inner_fold": inner_fold,
            "epoch_count": epoch_count,
            "stop_logit_bias": stop_logit_bias,
            "state_dict": model.state_dict(),
        },
        path,
    )


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    device = torch.device(requested)
    if device.type not in {"cpu", "cuda"}:
        raise ValueError("set expansion device is invalid")
    return device


__all__ = [
    "DEFAULT_SET_EXPANSION_CONFIG",
    "SetExpansionTrainingConfig",
    "run_ordinary_set_expansion_strict_nested_oof",
    "score_set_expansion_examples",
]
