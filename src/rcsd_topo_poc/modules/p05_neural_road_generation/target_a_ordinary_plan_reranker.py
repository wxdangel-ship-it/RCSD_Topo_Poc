from __future__ import annotations

import json
import math
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
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_proposals import (
    OrdinaryPlanProposalExample,
    PLAN_PROPOSAL_FEATURE_DIM,
    StaticOrdinaryPlan,
    build_ordinary_plan_proposal_example,
    read_static_ordinary_plans,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISIONS,
    OrdinaryRoadSetExample,
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
class OrdinaryPlanRerankerConfig:
    hidden_dim: int = 96
    feedforward_dim: int = 192
    layer_count: int = 2
    head_count: int = 4
    dropout: float = 0.1
    batch_size: int = 32
    epochs: int = 60
    patience: int = 8
    learning_rate: float = 5e-4
    weight_decay: float = 2e-4
    maximum_prefix_cardinality: int = 67
    torch_num_threads: int = 4

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.feedforward_dim,
            self.layer_count,
            self.head_count,
            self.batch_size,
            self.epochs,
            self.patience,
            self.maximum_prefix_cardinality,
            self.torch_num_threads,
        ) < 1:
            raise ValueError("ordinary plan reranker config is invalid")
        if self.hidden_dim % self.head_count:
            raise ValueError("ordinary plan reranker heads do not divide hidden")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("ordinary plan reranker dropout is invalid")
        if self.learning_rate <= 0.0 or self.weight_decay < 0.0:
            raise ValueError("ordinary plan reranker optimizer is invalid")


class TargetAOrdinaryPlanProposalReranker(nn.Module):
    """Select one complete carrier proposal or explicit ABSTAIN."""

    def __init__(
        self,
        *,
        feature_dim: int = PLAN_PROPOSAL_FEATURE_DIM,
        hidden_dim: int = 96,
        feedforward_dim: int = 192,
        layer_count: int = 2,
        head_count: int = 4,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if hidden_dim % head_count:
            raise ValueError("ordinary plan reranker heads do not divide hidden")
        self.feature_dim = feature_dim
        self.encoder = nn.Sequential(
            nn.Linear(feature_dim, feedforward_dim),
            nn.GELU(),
            nn.LayerNorm(feedforward_dim),
            nn.Dropout(dropout),
            nn.Linear(feedforward_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=head_count,
            dim_feedforward=feedforward_dim,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.proposal_encoder = nn.TransformerEncoder(
            layer,
            num_layers=layer_count,
            norm=nn.LayerNorm(hidden_dim),
        )
        self.score_head = nn.Sequential(
            nn.Linear(feature_dim + hidden_dim * 3, feedforward_dim),
            nn.GELU(),
            nn.LayerNorm(feedforward_dim),
            nn.Dropout(dropout),
            nn.Linear(feedforward_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        features: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        if (
            features.ndim != 3
            or features.shape[-1] != self.feature_dim
            or mask.shape != features.shape[:2]
            or mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary plan reranker input shape differs")
        encoded = self.encoder(features)
        encoded = self.proposal_encoder(
            encoded,
            src_key_padding_mask=~mask,
        )
        mask_float = mask.unsqueeze(-1).to(encoded.dtype)
        mean = (encoded * mask_float).sum(dim=1) / mask_float.sum(
            dim=1
        ).clamp_min(1.0)
        maximum = encoded.masked_fill(
            ~mask.unsqueeze(-1),
            torch.finfo(encoded.dtype).min,
        ).max(dim=1).values
        maximum = torch.where(
            mask.any(dim=1, keepdim=True),
            maximum,
            torch.zeros_like(maximum),
        )
        expanded_mean = mean.unsqueeze(1).expand(-1, features.shape[1], -1)
        expanded_maximum = maximum.unsqueeze(1).expand(
            -1,
            features.shape[1],
            -1,
        )
        logits = self.score_head(
            torch.cat(
                (features, encoded, expanded_mean, expanded_maximum),
                dim=-1,
            )
        ).squeeze(-1)
        return logits.masked_fill(~mask, torch.finfo(logits.dtype).min)


def acceptable_plan_nll(
    logits: torch.Tensor,
    acceptable: torch.Tensor,
    valid: torch.Tensor,
) -> torch.Tensor:
    if (
        logits.shape != acceptable.shape
        or logits.shape != valid.shape
        or acceptable.dtype is not torch.bool
        or valid.dtype is not torch.bool
    ):
        raise ValueError("ordinary plan acceptable-set shapes differ")
    if bool((acceptable & ~valid).any()) or bool(
        (~acceptable.any(dim=-1)).any()
    ):
        raise ValueError("ordinary plan acceptable-set mask is invalid")
    minimum = torch.finfo(logits.dtype).min
    all_logsumexp = torch.logsumexp(
        logits.masked_fill(~valid, minimum),
        dim=-1,
    )
    acceptable_logsumexp = torch.logsumexp(
        logits.masked_fill(~acceptable, minimum),
        dim=-1,
    )
    return all_logsumexp - acceptable_logsumexp


def run_ordinary_plan_proposal_reranker_strict_oof(
    *,
    member_store_root: Path,
    static_plan_store_root: Path,
    base_trained_root: Path,
    output_root: Path,
    seed: int,
    config: OrdinaryPlanRerankerConfig = OrdinaryPlanRerankerConfig(),
    requested_device: str = "cuda",
) -> Path:
    """Train one strict-inner complete-plan reranker for each outer fold."""
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
    examples, read_summary = read_ordinary_road_set_examples(member_store)
    folds = sorted({row.fold for row in examples})
    if len(folds) < 3:
        raise ValueError("ordinary plan reranker needs at least three folds")
    base_examples, base_store = _read_base_training_examples(trained)
    base_by_key = {
        (row.case_key, row.segment_id): row for row in base_examples
    }
    _assert_base_feature_alignment(examples, base_by_key)
    keys = {(row.case_key, row.segment_id) for row in examples}
    static = read_static_ordinary_plans(
        plan_store,
        required_keys=keys,
    )
    device = _resolve_device(requested_device)
    predictions = []
    fold_summaries = []
    reranker_parameters = 0
    seen_outer: set[tuple[str, str]] = set()
    for outer_fold in folds:
        fold_seed = seed + outer_fold * 1009
        inner_fold = _inner_validation_fold(trained, outer_fold)
        if inner_fold == outer_fold:
            raise ValueError("ordinary plan reranker inner/outer fold overlaps")
        training_rows = [
            row
            for row in examples
            if row.fold not in {outer_fold, inner_fold}
        ]
        inner_rows = [row for row in examples if row.fold == inner_fold]
        outer_rows = [row for row in examples if row.fold == outer_fold]
        _assert_case_disjoint(training_rows, inner_rows)
        _assert_case_disjoint(training_rows, outer_rows)
        _assert_case_disjoint(inner_rows, outer_rows)
        base_training_rows = _aligned_base_rows(
            training_rows,
            base_by_key=base_by_key,
        )
        base_inner_rows = _aligned_base_rows(
            inner_rows,
            base_by_key=base_by_key,
        )
        inner_checkpoint = (
            trained / f"fold_{outer_fold}_inner_checkpoint.pt"
        )
        training_base = _score_base_checkpoint(
            checkpoint=inner_checkpoint,
            rows=base_training_rows,
            device=device,
        )
        training_proposals = _proposal_examples(
            training_rows,
            base_predictions=training_base,
            static=static,
            maximum_prefix_cardinality=(
                config.maximum_prefix_cardinality
            ),
        )
        inner_base = _score_base_checkpoint(
            checkpoint=inner_checkpoint,
            rows=base_inner_rows,
            device=device,
        )
        inner_proposals = _proposal_examples(
            inner_rows,
            base_predictions=inner_base,
            static=static,
            maximum_prefix_cardinality=(
                config.maximum_prefix_cardinality
            ),
        )
        reranker = _new_reranker(config, device=device, seed=fold_seed)
        history = _fit_reranker(
            reranker,
            training_proposals,
            validation_examples=inner_proposals,
            config=config,
            device=device,
            seed=fold_seed,
        )
        reranker_parameters = parameter_count(reranker)
        inner_scored = score_ordinary_plan_proposals(
            reranker,
            inner_proposals,
            batch_size=config.batch_size,
            device=device,
        )
        acceptance_threshold = choose_zero_error_plan_threshold(inner_scored)
        outer_base = _score_base_checkpoint(
            checkpoint=trained / f"fold_{outer_fold}_checkpoint.pt",
            rows=_aligned_base_rows(
                outer_rows,
                base_by_key=base_by_key,
            ),
            device=device,
        )
        outer_proposals = _proposal_examples(
            outer_rows,
            base_predictions=outer_base,
            static=static,
            maximum_prefix_cardinality=(
                config.maximum_prefix_cardinality
            ),
        )
        outer_scored = score_ordinary_plan_proposals(
            reranker,
            outer_proposals,
            batch_size=config.batch_size,
            device=device,
        )
        base_threshold = _base_acceptance_threshold(trained, outer_fold)
        for value, base, current in zip(
            outer_scored,
            outer_base,
            outer_rows,
            strict=True,
        ):
            key = (str(value["case_key"]), str(value["segment_id"]))
            if key in seen_outer:
                raise ValueError("ordinary plan reranker outer duplicate")
            seen_outer.add(key)
            accepted = bool(
                value["raw_automatic"]
                and float(value["confidence"]) >= acceptance_threshold
            )
            base_automatic = bool(
                base["release_eligible"]
                and float(base["confidence"]) >= base_threshold
            )
            base_complete_exact = bool(
                str(base["predicted_decision"])
                == DECISIONS[current.decision]
                and tuple(sorted(str(item) for item in base["selected_road_ids"]))
                == tuple(
                    sorted(
                        current.road_ids[index]
                        for index in current.target_indices
                    )
                )
            )
            value["outer_fold"] = outer_fold
            value["inner_validation_fold"] = inner_fold
            value["acceptance_threshold"] = acceptance_threshold
            value["accepted"] = accepted
            value["unsafe_accepted"] = bool(
                accepted and not value["complete_exact"]
            )
            value["base_predicted_decision"] = str(
                base["predicted_decision"]
            )
            value["base_selected_road_ids"] = list(
                base["selected_road_ids"]
            )
            value["base_confidence"] = float(base["confidence"])
            value["base_acceptance_threshold"] = base_threshold
            value["base_automatic"] = base_automatic
            value["base_complete_exact"] = base_complete_exact
            value["base_unsafe_automatic"] = bool(
                base_automatic and not base_complete_exact
            )
            predictions.append(value)
        checkpoint_path = root / f"fold_{outer_fold}_reranker.pt"
        _save_checkpoint(
            checkpoint_path,
            reranker=reranker,
            config=config,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            acceptance_threshold=acceptance_threshold,
        )
        fold_summary = {
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "training_example_count": len(training_proposals),
            "inner_example_count": len(inner_proposals),
            "outer_example_count": len(outer_proposals),
            "training_target_reachable": sum(
                int(row.target_reachable)
                for row in training_proposals
            ),
            "inner_target_reachable": sum(
                int(row.target_reachable) for row in inner_proposals
            ),
            "outer_target_reachable": sum(
                int(row.target_reachable) for row in outer_proposals
            ),
            "acceptance_threshold": acceptance_threshold,
            "best_epoch": int(
                min(
                    history,
                    key=lambda row: row["validation_loss"],
                )["epoch"]
            ),
            "history": history,
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
        del reranker
        if device.type == "cuda":
            torch.cuda.empty_cache()
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, predictions)
    expected_keys = {(row.case_key, row.segment_id) for row in examples}
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_COMPLETE_PLAN_PROPOSAL_RERANKER_STRICT_OOF",
        "decoder_contract": (
            "the frozen Road encoder supplies decision/member evidence; a "
            "small set decoder selects one complete static or learned-prefix "
            "carrier proposal, or explicit ABSTAIN"
        ),
        "strict_oof_contract": (
            "each outer reranker is trained only on Cases outside the outer "
            "and inner folds, calibrated only on the held-out inner fold, "
            "and evaluated only on the held-out outer fold"
        ),
        "candidate_contract": (
            "static truth-free v114 plans are unioned with all source-local "
            "member-score prefixes up to the configured capacity; labels "
            "only mark acceptable proposals after feature construction"
        ),
        "config": asdict(config),
        "seed": seed,
        "example_count": len(examples),
        "reranker_parameters": reranker_parameters,
        "base_parameters": _base_parameter_count(trained),
        "fold_count": len(folds),
        "folds": fold_summaries,
        "metrics": _plan_metrics(predictions),
        "read_summary": read_summary,
        "inputs": {
            "member_features": _input_record(
                member_store / "ordinary_road_member_features.jsonl"
            ),
            "member_labels": _input_record(
                member_store / "ordinary_road_member_labels.jsonl"
            ),
            "static_plan_manifest": _input_record(
                plan_store / "manifest.json"
            ),
            "base_training_summary": _input_record(
                trained / "summary.json"
            ),
            "base_member_store_summary": _input_record(
                base_store / "summary.json"
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
        "release_gate": "NO_GO",
        "wall_seconds": time.perf_counter() - started,
        "actual_device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (
            torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else ""
        ),
        "gate_pass": bool(
            seen_outer == expected_keys
            and len(predictions) == len(examples)
            and all(
                int(row["unsafe_accepted"]) == 0
                for row in predictions
            )
        ),
    }
    _write_json(root / "summary.json", summary)
    return root


def score_ordinary_plan_proposals(
    model: TargetAOrdinaryPlanProposalReranker,
    examples: Sequence[OrdinaryPlanProposalExample],
    *,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    result = []
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            batch = _collate(rows, device=device)
            logits = model(batch["features"], batch["valid"])
            probabilities = torch.softmax(logits, dim=-1)
            for index, row in enumerate(rows):
                valid_count = len(row.proposal_ids)
                values = probabilities[index, :valid_count]
                selected_index = int(values.argmax().item())
                ordered = torch.sort(values, descending=True).values
                probability = float(ordered[0].item())
                margin = float(
                    ordered[0].item() - ordered[1].item()
                    if valid_count > 1
                    else ordered[0].item()
                )
                decision = row.proposal_decisions[selected_index]
                selected_roads = row.proposal_road_ids[selected_index]
                complete_exact = bool(
                    decision == row.target_decision
                    and selected_roads == row.target_road_ids
                )
                result.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": row.case_key,
                        "segment_id": row.segment_id,
                        "fold": row.fold,
                        "selected_proposal_id": row.proposal_ids[
                            selected_index
                        ],
                        "predicted_decision": decision,
                        "selected_road_ids": list(selected_roads),
                        "target_decision": row.target_decision,
                        "target_road_ids": list(row.target_road_ids),
                        "target_reachable": row.target_reachable,
                        "proposal_count": valid_count,
                        "selected_probability": probability,
                        "set_margin": margin,
                        "confidence": probability * max(margin, 0.0),
                        "complete_exact": complete_exact,
                        "release_eligible": row.release_eligible,
                        "raw_automatic": bool(
                            decision != "ABSTAIN" and row.release_eligible
                        ),
                        "feature_uses_truth": False,
                        "terminal_input_count": 0,
                    }
                )
    return result


def choose_zero_error_plan_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    errors = [
        float(row["confidence"])
        for row in rows
        if bool(row["raw_automatic"]) and not bool(row["complete_exact"])
    ]
    if not errors:
        return 0.0
    return min(1.000001, max(errors) + 1e-9)


def _read_base_training_examples(
    trained: Path,
) -> tuple[list[OrdinaryRoadSetExample], Path]:
    summary = json.loads(
        (trained / "summary.json").read_text(encoding="utf-8")
    )
    record = summary.get("member_store_summary") or {}
    raw_path = str(record.get("path") or "")
    if not raw_path:
        raise ValueError("ordinary base member store path is missing")
    resolved = normalize_runtime_path(Path(raw_path)).resolve(strict=True)
    store = resolved.parent if resolved.is_file() else resolved
    examples, _ = read_ordinary_road_set_examples(store)
    return examples, store


def _assert_base_feature_alignment(
    current: Sequence[OrdinaryRoadSetExample],
    base_by_key: Mapping[tuple[str, str], OrdinaryRoadSetExample],
) -> None:
    current_keys = {(row.case_key, row.segment_id) for row in current}
    if current_keys != set(base_by_key):
        raise ValueError("ordinary base/current example keys differ")
    fields = (
        "fold",
        "object_features",
        "road_ids",
        "sources",
        "start_node_ids",
        "end_node_ids",
        "anchor_features",
        "teacher_anchor_relations",
        "oof_anchor_relations",
        "teacher_features",
        "oof_features",
        "oof_anchor_release_ready",
    )
    for row in current:
        base = base_by_key[(row.case_key, row.segment_id)]
        if any(getattr(row, field) != getattr(base, field) for field in fields):
            raise ValueError(
                "ordinary base/current scoring features differ: "
                f"{row.case_key}/{row.segment_id}"
            )


def _aligned_base_rows(
    current: Sequence[OrdinaryRoadSetExample],
    *,
    base_by_key: Mapping[tuple[str, str], OrdinaryRoadSetExample],
) -> list[OrdinaryRoadSetExample]:
    return [
        base_by_key[(row.case_key, row.segment_id)]
        for row in current
    ]


def _score_base_checkpoint(
    *,
    checkpoint: Path,
    rows: Sequence[OrdinaryRoadSetExample],
    device: torch.device,
) -> list[dict[str, Any]]:
    model, config = _load_checkpoint(checkpoint, device=device)
    scored = score_ordinary_road_set_examples(
        model,
        rows,
        feature_source="oof",
        batch_size=config.batch_size,
        device=device,
        include_member_probabilities=True,
    )
    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return scored


def _proposal_examples(
    rows: Sequence[OrdinaryRoadSetExample],
    *,
    base_predictions: Sequence[Mapping[str, Any]],
    static: Mapping[tuple[str, str], Sequence[StaticOrdinaryPlan]],
    maximum_prefix_cardinality: int,
) -> list[OrdinaryPlanProposalExample]:
    if len(rows) != len(base_predictions):
        raise ValueError("ordinary plan reranker base alignment differs")
    result = []
    for row, prediction in zip(rows, base_predictions, strict=True):
        key = (row.case_key, row.segment_id)
        if key != (
            str(prediction["case_key"]),
            str(prediction["segment_id"]),
        ):
            raise ValueError("ordinary plan reranker key alignment differs")
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


def _fit_reranker(
    model: TargetAOrdinaryPlanProposalReranker,
    examples: Sequence[OrdinaryPlanProposalExample],
    *,
    validation_examples: Sequence[OrdinaryPlanProposalExample],
    config: OrdinaryPlanRerankerConfig,
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
    best_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    stale_epochs = 0
    for epoch in range(config.epochs):
        order = list(range(len(examples)))
        generator.shuffle(order)
        model.train()
        total = 0.0
        mass = 0.0
        for start in range(0, len(order), config.batch_size):
            rows = [examples[index] for index in order[start : start + config.batch_size]]
            batch = _collate(rows, device=device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch["features"], batch["valid"])
            raw = acceptable_plan_nll(
                logits,
                batch["acceptable"],
                batch["valid"],
            )
            loss = (raw * batch["weights"]).sum() / batch[
                "weights"
            ].sum().clamp_min(1e-6)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
            optimizer.step()
            weight = float(batch["weights"].sum().item())
            total += float(loss.item()) * weight
            mass += weight
        validation_loss = _evaluate_reranker_loss(
            model,
            validation_examples,
            batch_size=config.batch_size,
            device=device,
        )
        history.append(
            {
                "epoch": float(epoch + 1),
                "train_loss": total / max(mass, 1e-9),
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-6:
            best_loss = validation_loss
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in model.state_dict().items()
            }
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= config.patience:
                break
    if best_state is None:
        raise ValueError("ordinary plan reranker produced no best state")
    model.load_state_dict(best_state)
    return history


def _evaluate_reranker_loss(
    model: TargetAOrdinaryPlanProposalReranker,
    examples: Sequence[OrdinaryPlanProposalExample],
    *,
    batch_size: int,
    device: torch.device,
) -> float:
    model.eval()
    total = 0.0
    mass = 0.0
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            rows = examples[start : start + batch_size]
            batch = _collate(rows, device=device)
            raw = acceptable_plan_nll(
                model(batch["features"], batch["valid"]),
                batch["acceptable"],
                batch["valid"],
            )
            total += float((raw * batch["weights"]).sum().item())
            mass += float(batch["weights"].sum().item())
    return total / max(mass, 1e-9)


def _collate(
    rows: Sequence[OrdinaryPlanProposalExample],
    *,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    if not rows:
        raise ValueError("cannot collate empty ordinary plan proposals")
    count = max(len(row.proposal_ids) for row in rows)
    features = torch.zeros(
        len(rows),
        count,
        PLAN_PROPOSAL_FEATURE_DIM,
        dtype=torch.float32,
        device=device,
    )
    valid = torch.zeros(
        len(rows),
        count,
        dtype=torch.bool,
        device=device,
    )
    acceptable = torch.zeros_like(valid)
    weights = torch.tensor(
        [row.sample_weight for row in rows],
        dtype=torch.float32,
        device=device,
    )
    for index, row in enumerate(rows):
        length = len(row.proposal_ids)
        features[index, :length] = torch.tensor(
            row.proposal_features,
            dtype=torch.float32,
            device=device,
        )
        valid[index, :length] = True
        acceptable[index, list(row.acceptable_indices)] = True
    return {
        "features": features,
        "valid": valid,
        "acceptable": acceptable,
        "weights": weights,
    }


def _new_reranker(
    config: OrdinaryPlanRerankerConfig,
    *,
    device: torch.device,
    seed: int,
) -> TargetAOrdinaryPlanProposalReranker:
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    return TargetAOrdinaryPlanProposalReranker(
        hidden_dim=config.hidden_dim,
        feedforward_dim=config.feedforward_dim,
        layer_count=config.layer_count,
        head_count=config.head_count,
        dropout=config.dropout,
    ).to(device)


def _plan_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    case_counts: dict[str, Counter[str]] = {}
    for row in rows:
        case_key = str(row["case_key"])
        case = case_counts.setdefault(case_key, Counter())
        exact = bool(row["complete_exact"])
        accepted = bool(row.get("accepted"))
        counts["example"] += 1
        counts["target_reachable"] += int(row["target_reachable"])
        counts["raw_exact"] += int(exact)
        counts["raw_automatic"] += int(row["raw_automatic"])
        counts["raw_unsafe"] += int(
            row["raw_automatic"] and not exact
        )
        counts["accepted"] += int(accepted)
        counts["accepted_exact"] += int(accepted and exact)
        counts["accepted_unsafe"] += int(
            row.get("unsafe_accepted") or False
        )
        counts["model_abstain"] += int(
            row["predicted_decision"] == "ABSTAIN"
        )
        counts["base_automatic"] += int(row.get("base_automatic") or False)
        counts["base_unsafe"] += int(
            row.get("base_unsafe_automatic") or False
        )
        case["example"] += 1
        case["exact"] += int(exact)
        case["accepted"] += int(accepted)
        case["accepted_unsafe"] += int(
            row.get("unsafe_accepted") or False
        )
    by_case = {
        key: {
            "example_count": value["example"],
            "raw_exact": value["exact"] / max(value["example"], 1),
            "accepted_count": value["accepted"],
            "accepted_coverage": value["accepted"] / max(
                value["example"], 1
            ),
            "accepted_unsafe_count": value["accepted_unsafe"],
        }
        for key, value in sorted(case_counts.items())
    }
    return {
        "counts": dict(sorted(counts.items())),
        "target_reachable_coverage": counts["target_reachable"]
        / max(counts["example"], 1),
        "raw_complete_exact": counts["raw_exact"]
        / max(counts["example"], 1),
        "raw_automatic_exact": (
            (counts["raw_automatic"] - counts["raw_unsafe"])
            / max(counts["raw_automatic"], 1)
        ),
        "accepted_coverage": counts["accepted"]
        / max(counts["example"], 1),
        "accepted_exact": counts["accepted_exact"]
        / max(counts["accepted"], 1),
        "by_case": by_case,
    }


def _inner_validation_fold(root: Path, outer_fold: int) -> int:
    path = root / f"fold_{outer_fold}_summary.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    return int(value["inner_validation_fold"])


def _base_acceptance_threshold(root: Path, outer_fold: int) -> float:
    path = root / f"fold_{outer_fold}_summary.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    return float(value["acceptance_threshold"])


def _base_parameter_count(root: Path) -> int:
    value = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    count = value.get("parameter_count", value.get("model_parameters"))
    if count is None:
        raise ValueError("ordinary base parameter count is missing")
    return int(count)


def _assert_case_disjoint(
    first: Sequence[OrdinaryRoadSetExample],
    second: Sequence[OrdinaryRoadSetExample],
) -> None:
    overlap = {row.case_key for row in first} & {
        row.case_key for row in second
    }
    if overlap:
        raise ValueError(
            "ordinary plan reranker Case leakage: "
            + ", ".join(sorted(overlap))
        )


def _save_checkpoint(
    path: Path,
    *,
    reranker: TargetAOrdinaryPlanProposalReranker,
    config: OrdinaryPlanRerankerConfig,
    outer_fold: int,
    inner_fold: int,
    acceptance_threshold: float,
) -> None:
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "config": asdict(config),
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "acceptance_threshold": acceptance_threshold,
            "feature_dim": PLAN_PROPOSAL_FEATURE_DIM,
            "state_dict": {
                key: value.detach().cpu()
                for key, value in reranker.state_dict().items()
            },
        },
        path,
    )


def _resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if requested not in {"cuda", "cpu"}:
        raise ValueError("ordinary plan reranker device is invalid")
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
    "OrdinaryPlanRerankerConfig",
    "TargetAOrdinaryPlanProposalReranker",
    "acceptable_plan_nll",
    "choose_zero_error_plan_threshold",
    "run_ordinary_plan_proposal_reranker_strict_oof",
    "score_ordinary_plan_proposals",
]
