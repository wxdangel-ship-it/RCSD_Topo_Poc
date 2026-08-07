from __future__ import annotations

import copy
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_beam_reranker import (
    BEAM_FEATURE_MODES,
    BEAM_RELATIONAL_FEATURE_DIM,
    BEAM_SCALAR_FEATURE_DIM,
    _BeamPlanExample,
    _assert_case_disjoint,
    _generate_beam_examples,
    _reranker_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_beam_structured_energy import (
    StructuredEnergyWeights,
    proposal_energy,
    select_structured_energy_weights,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_reranker import (
    acceptable_plan_nll,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISIONS,
    OrdinaryRoadSetExample,
    _input_record,
    _write_json,
    _write_jsonl,
    read_ordinary_road_set_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_same_plan_affinity import (
    _AffinityView,
    _encode_affinity_views,
    _read_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_beam_audit import (
    _load_model,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_training import (
    _resolve_device,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


@dataclass(frozen=True)
class PairwisePlanDecoderConfig:
    beam_width: int = 16
    feature_mode: str = "SCALAR"
    use_structured_base: bool = False
    hidden_dim: int = 64
    dropout: float = 0.1
    batch_size: int = 8
    epochs: int = 36
    patience: int = 6
    learning_rate: float = 5e-4
    weight_decay: float = 2e-4
    torch_num_threads: int = 4

    def validate(self) -> None:
        if self.feature_mode not in {"SCALAR", "RELATIONAL"}:
            raise ValueError("pairwise plan decoder feature mode differs")
        if min(
            self.beam_width,
            self.hidden_dim,
            self.batch_size,
            self.epochs,
            self.patience,
            self.learning_rate,
            self.torch_num_threads,
        ) <= 0:
            raise ValueError("pairwise plan decoder config differs")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("pairwise plan decoder dropout differs")
        if self.weight_decay < 0.0:
            raise ValueError("pairwise plan decoder weight decay differs")


@dataclass(frozen=True)
class _PairwisePlanView:
    plan: _BeamPlanExample
    candidate_signals: torch.Tensor
    road_relations: torch.Tensor
    source_indices: torch.Tensor
    base_energies: torch.Tensor


class PairwiseStructuredPlanDecoder(nn.Module):
    """Score complete Road sets from plan, Road and Road-pair evidence."""

    def __init__(
        self,
        *,
        plan_feature_dim: int = BEAM_SCALAR_FEATURE_DIM,
        signal_dim: int = 3,
        relation_dim: int = 13,
        hidden_dim: int = 64,
        dropout: float = 0.1,
        use_structured_base: bool = False,
    ) -> None:
        super().__init__()
        unary_hidden = max(hidden_dim // 2, 16)
        self.plan_feature_dim = plan_feature_dim
        self.signal_dim = signal_dim
        self.relation_dim = relation_dim
        self.plan_head = nn.Sequential(
            nn.LayerNorm(plan_feature_dim),
            nn.Linear(plan_feature_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        self.unary_head = nn.Sequential(
            nn.LayerNorm(signal_dim),
            nn.Linear(signal_dim, unary_hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(unary_hidden, 2),
        )
        self.pair_head = nn.Sequential(
            nn.LayerNorm(relation_dim),
            nn.Linear(relation_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 2),
        )
        self.term_weights = nn.Parameter(
            torch.zeros(5)
            if use_structured_base
            else torch.ones(5)
        )
        self.base_scale_raw = nn.Parameter(
            torch.tensor(
                math.log(math.expm1(1.0))
                if use_structured_base
                else -20.0
            )
        )
        self.term_bias = nn.Parameter(torch.zeros(1))

    def forward(
        self,
        *,
        plan_features: torch.Tensor,
        base_energies: torch.Tensor,
        plan_valid: torch.Tensor,
        plan_decisions: torch.Tensor,
        plan_selected: torch.Tensor,
        candidate_signals: torch.Tensor,
        candidate_valid: torch.Tensor,
        candidate_sources: torch.Tensor,
        road_relations: torch.Tensor,
    ) -> torch.Tensor:
        batch_size, plan_count, candidate_count = plan_selected.shape
        if (
            plan_features.shape
            != (batch_size, plan_count, self.plan_feature_dim)
            or base_energies.shape != (batch_size, plan_count)
            or plan_valid.shape != (batch_size, plan_count)
            or plan_decisions.shape != (batch_size, plan_count)
            or candidate_signals.shape
            != (batch_size, candidate_count, self.signal_dim)
            or candidate_valid.shape != (batch_size, candidate_count)
            or candidate_sources.shape != (batch_size, candidate_count)
            or road_relations.shape
            != (
                batch_size,
                candidate_count,
                candidate_count,
                self.relation_dim,
            )
        ):
            raise ValueError("pairwise plan decoder input shape differs")
        plan_base = self.plan_head(plan_features).squeeze(-1)
        unary_scores = self.unary_head(candidate_signals)
        pair_scores = self.pair_head(road_relations)
        allowed = (
            candidate_sources.unsqueeze(1)
            == plan_decisions.unsqueeze(-1)
        ) & candidate_valid.unsqueeze(1)
        selected = plan_selected & allowed
        excluded = allowed & ~selected
        selected_unary = _masked_mean(
            unary_scores[..., 0].unsqueeze(1),
            selected,
            dimensions=(-1,),
        )
        excluded_unary = _masked_mean(
            unary_scores[..., 1].unsqueeze(1),
            excluded,
            dimensions=(-1,),
        )
        upper = torch.triu(
            torch.ones(
                candidate_count,
                candidate_count,
                dtype=torch.bool,
                device=plan_features.device,
            ),
            diagonal=1,
        )
        pair_valid = (
            candidate_valid.unsqueeze(1)
            & candidate_valid.unsqueeze(2)
            & upper.unsqueeze(0)
        )
        inside_mask = (
            selected.unsqueeze(-1)
            & selected.unsqueeze(-2)
            & pair_valid.unsqueeze(1)
        )
        boundary_mask = (
            (
                selected.unsqueeze(-1) & excluded.unsqueeze(-2)
            )
            | (
                excluded.unsqueeze(-1) & selected.unsqueeze(-2)
            )
        ) & pair_valid.unsqueeze(1)
        inside_pair = _masked_mean(
            pair_scores[..., 0].unsqueeze(1),
            inside_mask,
            dimensions=(-1, -2),
        )
        boundary_pair = _masked_mean(
            pair_scores[..., 1].unsqueeze(1),
            boundary_mask,
            dimensions=(-1, -2),
        )
        terms = torch.stack(
            (
                plan_base,
                selected_unary,
                excluded_unary,
                inside_pair,
                boundary_pair,
            ),
            dim=-1,
        )
        residual = (
            terms * self.term_weights.view(1, 1, -1)
        ).sum(dim=-1) + self.term_bias
        logits = (
            torch.nn.functional.softplus(self.base_scale_raw)
            * base_energies
            + residual
        )
        return logits.masked_fill(~plan_valid, 0.0)


def run_pairwise_plan_decoder_canary(
    *,
    member_store_root: Path,
    expansion_checkpoint_root: Path,
    output_root: Path,
    outer_fold: int,
    seed: int,
    config: PairwisePlanDecoderConfig = PairwisePlanDecoderConfig(),
    requested_device: str = "cuda",
) -> Path:
    """Train a strict inner/outer complete-plan pairwise decoder."""
    started = time.perf_counter()
    config.validate()
    torch.set_num_threads(config.torch_num_threads)
    member_root = normalize_runtime_path(member_store_root).resolve(
        strict=True
    )
    checkpoint_root = normalize_runtime_path(
        expansion_checkpoint_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    rows, read_summary = read_ordinary_road_set_examples(member_root)
    fold_summary = _read_json(
        checkpoint_root / f"fold_{outer_fold}_summary.json"
    )
    inner_fold = int(fold_summary["inner_validation_fold"])
    training_rows = [
        row for row in rows if row.fold not in {outer_fold, inner_fold}
    ]
    validation_rows = [row for row in rows if row.fold == inner_fold]
    outer_rows = [row for row in rows if row.fold == outer_fold]
    _assert_case_disjoint(training_rows, validation_rows)
    _assert_case_disjoint(training_rows, outer_rows)
    _assert_case_disjoint(validation_rows, outer_rows)
    device = _resolve_device(requested_device)
    inner_model, inner_config = _load_model(
        checkpoint_root / f"fold_{outer_fold}_inner_checkpoint.pt",
        rows=training_rows,
        device=device,
    )
    outer_model, outer_config = _load_model(
        checkpoint_root / f"fold_{outer_fold}_checkpoint.pt",
        rows=outer_rows,
        device=device,
    )
    if inner_config != outer_config:
        raise ValueError("pairwise plan decoder expansion configs differ")
    training_views = _generate_plan_views(
        inner_model,
        training_rows,
        beam_width=config.beam_width,
        device=device,
        feature_mode=config.feature_mode,
    )
    validation_views = _generate_plan_views(
        inner_model,
        validation_rows,
        beam_width=config.beam_width,
        device=device,
        feature_mode=config.feature_mode,
    )
    outer_views = _generate_plan_views(
        outer_model,
        outer_rows,
        beam_width=config.beam_width,
        device=device,
        feature_mode=config.feature_mode,
    )
    structured_selection = None
    structured_weights = None
    if config.use_structured_base:
        if config.feature_mode != "RELATIONAL":
            raise ValueError("structured base requires RELATIONAL features")
        structured_selection = select_structured_energy_weights(
            [view.plan for view in validation_views]
        )
        structured_weights = structured_selection["weights"]
        training_views = _attach_structured_base(
            training_views,
            weights=structured_weights,
        )
        validation_views = _attach_structured_base(
            validation_views,
            weights=structured_weights,
        )
        outer_views = _attach_structured_base(
            outer_views,
            weights=structured_weights,
        )
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    decoder = PairwiseStructuredPlanDecoder(
        plan_feature_dim=(
            BEAM_RELATIONAL_FEATURE_DIM
            if config.feature_mode == "RELATIONAL"
            else BEAM_SCALAR_FEATURE_DIM
        ),
        hidden_dim=config.hidden_dim,
        dropout=config.dropout,
        use_structured_base=config.use_structured_base,
    ).to(device)
    history = _fit_decoder(
        decoder,
        training_views,
        validation_views=validation_views,
        config=config,
        device=device,
        seed=seed,
    )
    inner_scores = _score_decoder(
        decoder,
        validation_views,
        batch_size=config.batch_size,
        device=device,
    )
    threshold = _choose_zero_error_threshold(inner_scores)
    outer_scores = _score_decoder(
        decoder,
        outer_views,
        batch_size=config.batch_size,
        device=device,
    )
    _apply_release_threshold(outer_scores, threshold=threshold)
    root.mkdir(parents=True)
    checkpoint_path = root / f"fold_{outer_fold}_decoder.pt"
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ORDINARY_PAIRWISE_PLAN_DECODER",
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "config": asdict(config),
            "state_dict": decoder.state_dict(),
        },
        checkpoint_path,
    )
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, outer_scores)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_PAIRWISE_PLAN_DECODER_CANARY",
        "outer_fold": outer_fold,
        "inner_validation_fold": inner_fold,
        "config": asdict(config),
        "training_count": len(training_views),
        "validation_count": len(validation_views),
        "outer_count": len(outer_views),
        "parameter_count": parameter_count(decoder),
        "structured_base_weights": (
            asdict(structured_weights)
            if structured_weights is not None
            else None
        ),
        "structured_base_selection": (
            structured_selection["summary"]
            if structured_selection is not None
            else None
        ),
        "history": history,
        "acceptance_threshold": threshold,
        "inner_metrics": _pairwise_plan_metrics(inner_scores),
        "metrics": _pairwise_plan_metrics(outer_scores),
        "feature_uses_truth": False,
        "training_label_contract": (
            "Complete-plan acceptable indices enter only listwise loss. "
            "Plan, Road and Road-pair inference features are truth-free."
        ),
        "business_boundary": (
            "Road-pair relation energy ranks existing complete carrier "
            "proposals; it is not a T06 path group, candidate expansion or "
            "deterministic business rule."
        ),
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "This is one-fold pairwise-plan canary; full OOF, two-seed "
            "agreement and final RoadGraph safety are not passed."
        ),
        "read_summary": read_summary,
        "member_store_summary": _input_record(
            member_root / "summary.json"
        ),
        "expansion_summary": _input_record(
            checkpoint_root / "summary.json"
        ),
        "checkpoint": _input_record(checkpoint_path),
        "predictions": _input_record(prediction_path),
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def _generate_plan_views(
    model: Any,
    rows: Sequence[OrdinaryRoadSetExample],
    *,
    beam_width: int,
    device: torch.device,
    feature_mode: str,
) -> list[_PairwisePlanView]:
    plans = _generate_beam_examples(
        model,
        rows,
        beam_width=beam_width,
        batch_size=32,
        device=device,
        feature_mode=feature_mode,
    )
    affinity_views = _encode_affinity_views(
        model,
        rows,
        batch_size=32,
        device=device,
    )
    by_key = {
        (view.row.case_key, view.row.segment_id): view
        for view in affinity_views
    }
    result = []
    for plan in plans:
        key = (plan.row.case_key, plan.row.segment_id)
        view = by_key[key]
        if plan.row.road_ids != view.row.road_ids:
            raise ValueError("pairwise plan Road order differs")
        source_indices = torch.tensor(
            [
                0 if source == "SWSD" else 1
                for source in plan.row.sources
            ],
            dtype=torch.long,
        )
        if any(
            source not in {"SWSD", "RCSD"}
            for source in plan.row.sources
        ):
            raise ValueError("pairwise plan candidate source differs")
        result.append(
            _PairwisePlanView(
                plan=plan,
                candidate_signals=view.candidate_signals,
                road_relations=view.road_relations,
                source_indices=source_indices,
                base_energies=torch.zeros(
                    len(plan.proposal_features),
                    dtype=torch.float32,
                ),
            )
        )
    return result


def _attach_structured_base(
    views: Sequence[_PairwisePlanView],
    *,
    weights: StructuredEnergyWeights,
) -> list[_PairwisePlanView]:
    result = []
    for view in views:
        proposal_energies = [
            proposal_energy(features, weights=weights)
            for features in view.plan.proposal_features[1:]
        ]
        if proposal_energies:
            maximum = max(proposal_energies)
            base_energies = torch.tensor(
                [-1.0]
                + [value - maximum for value in proposal_energies],
                dtype=torch.float32,
            )
        else:
            base_energies = torch.zeros(1, dtype=torch.float32)
        result.append(
            _PairwisePlanView(
                plan=view.plan,
                candidate_signals=view.candidate_signals,
                road_relations=view.road_relations,
                source_indices=view.source_indices,
                base_energies=base_energies,
            )
        )
    return result


def _collate_plan_views(
    views: Sequence[_PairwisePlanView],
    *,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    plan_count = max(len(view.plan.proposal_features) for view in views)
    candidate_count = max(len(view.plan.row.road_ids) for view in views)
    feature_dim = len(views[0].plan.proposal_features[0])
    if any(
        len(features) != feature_dim
        for view in views
        for features in view.plan.proposal_features
    ):
        raise ValueError("pairwise plan feature dimensions differ")
    batch_size = len(views)
    plan_features = torch.zeros(
        batch_size,
        plan_count,
        feature_dim,
        dtype=torch.float32,
        device=device,
    )
    base_energies = torch.zeros(
        batch_size,
        plan_count,
        dtype=torch.float32,
        device=device,
    )
    plan_valid = torch.zeros(
        batch_size, plan_count, dtype=torch.bool, device=device
    )
    plan_decisions = torch.full(
        (batch_size, plan_count),
        -1,
        dtype=torch.long,
        device=device,
    )
    plan_selected = torch.zeros(
        batch_size,
        plan_count,
        candidate_count,
        dtype=torch.bool,
        device=device,
    )
    acceptable = torch.zeros_like(plan_valid)
    signals = torch.zeros(
        batch_size,
        candidate_count,
        3,
        dtype=torch.float32,
        device=device,
    )
    candidate_valid = torch.zeros(
        batch_size, candidate_count, dtype=torch.bool, device=device
    )
    candidate_sources = torch.full(
        (batch_size, candidate_count),
        -2,
        dtype=torch.long,
        device=device,
    )
    relations = torch.zeros(
        batch_size,
        candidate_count,
        candidate_count,
        13,
        dtype=torch.float32,
        device=device,
    )
    for batch_index, view in enumerate(views):
        proposal_length = len(view.plan.proposal_features)
        candidate_length = len(view.plan.row.road_ids)
        plan_features[batch_index, :proposal_length] = torch.tensor(
            view.plan.proposal_features,
            dtype=torch.float32,
            device=device,
        )
        base_energies[batch_index, :proposal_length] = (
            view.base_energies.to(device)
        )
        plan_valid[batch_index, :proposal_length] = True
        plan_decisions[batch_index, :proposal_length] = torch.tensor(
            view.plan.proposal_decisions,
            dtype=torch.long,
            device=device,
        )
        for proposal_index, selected in enumerate(
            view.plan.proposal_selected_indices
        ):
            plan_selected[
                batch_index,
                proposal_index,
                list(selected),
            ] = True
        acceptable[
            batch_index,
            list(view.plan.acceptable_indices),
        ] = True
        signals[batch_index, :candidate_length] = (
            view.candidate_signals.to(device)
        )
        candidate_valid[batch_index, :candidate_length] = True
        candidate_sources[batch_index, :candidate_length] = (
            view.source_indices.to(device)
        )
        relations[
            batch_index,
            :candidate_length,
            :candidate_length,
        ] = view.road_relations.to(device)
    return {
        "plan_features": plan_features,
        "base_energies": base_energies,
        "plan_valid": plan_valid,
        "plan_decisions": plan_decisions,
        "plan_selected": plan_selected,
        "acceptable": acceptable,
        "candidate_signals": signals,
        "candidate_valid": candidate_valid,
        "candidate_sources": candidate_sources,
        "road_relations": relations,
        "weights": torch.tensor(
            [view.plan.row.sample_weight for view in views],
            dtype=torch.float32,
            device=device,
        ),
    }


def _forward_decoder(
    model: PairwiseStructuredPlanDecoder,
    batch: Mapping[str, torch.Tensor],
) -> torch.Tensor:
    return model(
        plan_features=batch["plan_features"],
        base_energies=batch["base_energies"],
        plan_valid=batch["plan_valid"],
        plan_decisions=batch["plan_decisions"],
        plan_selected=batch["plan_selected"],
        candidate_signals=batch["candidate_signals"],
        candidate_valid=batch["candidate_valid"],
        candidate_sources=batch["candidate_sources"],
        road_relations=batch["road_relations"],
    )


def _fit_decoder(
    model: PairwiseStructuredPlanDecoder,
    training: Sequence[_PairwisePlanView],
    *,
    validation_views: Sequence[_PairwisePlanView],
    config: PairwisePlanDecoderConfig,
    device: torch.device,
    seed: int,
) -> list[dict[str, float]]:
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    best_state = copy.deepcopy(model.state_dict())
    best_loss = math.inf
    stale = 0
    history = []
    for epoch in range(1, config.epochs + 1):
        order = list(training)
        random.Random(seed + epoch).shuffle(order)
        model.train()
        total = 0.0
        weight_total = 0.0
        for start in range(0, len(order), config.batch_size):
            values = order[start : start + config.batch_size]
            batch = _collate_plan_views(values, device=device)
            optimizer.zero_grad(set_to_none=True)
            raw = acceptable_plan_nll(
                _forward_decoder(model, batch),
                batch["acceptable"],
                batch["plan_valid"],
            )
            loss = (raw * batch["weights"]).sum() / batch[
                "weights"
            ].sum().clamp_min(1e-6)
            if not bool(torch.isfinite(loss)):
                raise RuntimeError("pairwise plan decoder loss is non-finite")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            optimizer.step()
            total += float(
                (raw.detach() * batch["weights"]).sum().item()
            )
            weight_total += float(batch["weights"].sum().item())
        training_loss = total / max(weight_total, 1e-9)
        validation_loss = _evaluate_decoder_loss(
            model,
            validation_views,
            batch_size=config.batch_size,
            device=device,
        )
        history.append(
            {
                "epoch": epoch,
                "training_loss": training_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-8:
            best_loss = validation_loss
            best_state = copy.deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
            if stale >= config.patience:
                break
    model.load_state_dict(best_state)
    model.eval()
    return history


def _evaluate_decoder_loss(
    model: PairwiseStructuredPlanDecoder,
    views: Sequence[_PairwisePlanView],
    *,
    batch_size: int,
    device: torch.device,
) -> float:
    total = 0.0
    weight_total = 0.0
    model.eval()
    with torch.no_grad():
        for start in range(0, len(views), batch_size):
            batch = _collate_plan_views(
                views[start : start + batch_size],
                device=device,
            )
            raw = acceptable_plan_nll(
                _forward_decoder(model, batch),
                batch["acceptable"],
                batch["plan_valid"],
            )
            total += float((raw * batch["weights"]).sum().item())
            weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _score_decoder(
    model: PairwiseStructuredPlanDecoder,
    views: Sequence[_PairwisePlanView],
    *,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    result = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(views), batch_size):
            values = views[start : start + batch_size]
            batch = _collate_plan_views(values, device=device)
            logits = _forward_decoder(model, batch).masked_fill(
                ~batch["plan_valid"],
                -torch.inf,
            )
            probabilities = torch.softmax(logits, dim=-1)
            for index, view in enumerate(values):
                count = len(view.plan.proposal_features)
                values_row = probabilities[index, :count]
                top_values, top_indices = values_row.topk(min(2, count))
                selected_index = int(top_indices[0].item())
                margin = (
                    float((top_values[0] - top_values[1]).item())
                    if len(top_values) > 1
                    else float(top_values[0].item())
                )
                confidence = float(top_values[0].item()) * max(
                    0.0, margin
                )
                decision_index = view.plan.proposal_decisions[
                    selected_index
                ]
                selected = view.plan.proposal_selected_indices[
                    selected_index
                ]
                correct = selected_index in view.plan.acceptable_indices
                result.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": view.plan.row.case_key,
                        "segment_id": view.plan.row.segment_id,
                        "fold": view.plan.row.fold,
                        "truth_decision": DECISIONS[
                            view.plan.row.decision
                        ],
                        "truth_cardinality": len(
                            view.plan.row.target_indices
                        ),
                        "target_reachable": view.plan.target_reachable,
                        "proposal_count": count,
                        "selected_proposal_index": selected_index,
                        "selected_decision": (
                            DECISIONS[decision_index]
                            if decision_index >= 0
                            else "ABSTAIN"
                        ),
                        "selected_road_ids": [
                            view.plan.row.road_ids[value]
                            for value in selected
                        ],
                        "selected_cardinality": len(selected),
                        "selection_label_correct": correct,
                        "raw_complete_exact": correct,
                        "release_eligible": bool(
                            view.plan.row.oof_anchor_release_ready
                        ),
                        "raw_automatic": bool(
                            decision_index >= 0
                            and view.plan.row.oof_anchor_release_ready
                        ),
                        "confidence": confidence,
                    }
                )
    return result


def _choose_zero_error_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    unsafe = [
        float(row["confidence"])
        for row in rows
        if bool(row["raw_automatic"])
        and not bool(row["raw_complete_exact"])
    ]
    return math.nextafter(max(unsafe), math.inf) if unsafe else 0.0


def _pairwise_plan_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    metrics = _reranker_metrics(rows)
    reachable = [row for row in rows if bool(row["target_reachable"])]
    unreachable = [
        row for row in rows if not bool(row["target_reachable"])
    ]
    long_reachable = [
        row
        for row in reachable
        if int(row["truth_cardinality"]) >= 10
    ]
    reachable_exact = sum(
        bool(row["raw_complete_exact"]) for row in reachable
    )
    unreachable_abstain = sum(
        str(row["selected_decision"]) == "ABSTAIN"
        for row in unreachable
    )
    long_reachable_exact = sum(
        bool(row["raw_complete_exact"]) for row in long_reachable
    )
    metrics.update(
        {
            "raw_complete_exact_including_safe_abstain": metrics[
                "raw_complete_exact"
            ],
            "reachable_plan_count": len(reachable),
            "reachable_plan_exact_count": reachable_exact,
            "reachable_plan_exact": (
                reachable_exact / len(reachable) if reachable else 0.0
            ),
            "unreachable_count": len(unreachable),
            "unreachable_safe_abstain_count": unreachable_abstain,
            "unreachable_safe_abstain_rate": (
                unreachable_abstain / len(unreachable)
                if unreachable
                else 0.0
            ),
            "long_10_plus_reachable_plan_count": len(long_reachable),
            "long_10_plus_reachable_plan_exact_count": (
                long_reachable_exact
            ),
            "long_10_plus_reachable_plan_exact": (
                long_reachable_exact / len(long_reachable)
                if long_reachable
                else 0.0
            ),
        }
    )
    return metrics


def _apply_release_threshold(
    rows: Sequence[dict[str, Any]],
    *,
    threshold: float,
) -> None:
    for row in rows:
        row["acceptance_threshold"] = threshold
        row["automatic"] = bool(
            row["raw_automatic"]
            and float(row["confidence"]) >= threshold
        )
        row["unsafe_automatic"] = bool(
            row["automatic"] and not row["raw_complete_exact"]
        )
        row["effective_decision"] = (
            row["selected_decision"] if row["automatic"] else "ABSTAIN"
        )


def _masked_mean(
    values: torch.Tensor,
    mask: torch.Tensor,
    *,
    dimensions: tuple[int, ...],
) -> torch.Tensor:
    weighted = (values * mask.to(values.dtype)).sum(dim=dimensions)
    count = mask.sum(dim=dimensions).clamp_min(1)
    return weighted / count


__all__ = [
    "PairwisePlanDecoderConfig",
    "PairwiseStructuredPlanDecoder",
    "run_pairwise_plan_decoder_canary",
]
