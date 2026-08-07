from __future__ import annotations

import copy
import json
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_reranker import (
    TargetAOrdinaryPlanProposalReranker,
    acceptable_plan_nll,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    parameter_count,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISIONS,
    OrdinaryRoadSetExample,
    _batch_tensors,
    _forward_model,
    _input_record,
    _write_json,
    _write_jsonl,
    read_ordinary_road_set_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_beam_audit import (
    _deduplicate_joint_proposals,
    _load_model,
    beam_decode_complete_sets,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_training import (
    _resolve_device,
    _row_access_seed_mask,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


BEAM_SCALAR_FEATURE_DIM = 32
BEAM_ROAD_EMBEDDING_DIM = 128
BEAM_EMBEDDING_FEATURE_DIM = (
    BEAM_SCALAR_FEATURE_DIM + BEAM_ROAD_EMBEDDING_DIM * 5
)
BEAM_RELATION_SUMMARY_DIM = 94
BEAM_RELATIONAL_FEATURE_DIM = (
    BEAM_SCALAR_FEATURE_DIM + BEAM_RELATION_SUMMARY_DIM
)
BEAM_FEATURE_MODES = ("SCALAR", "EMBEDDING", "RELATIONAL")


@dataclass(frozen=True)
class BeamRerankerConfig:
    beam_width: int = 16
    feature_mode: str = "SCALAR"
    hidden_dim: int = 64
    feedforward_dim: int = 128
    layer_count: int = 2
    head_count: int = 4
    dropout: float = 0.1
    batch_size: int = 32
    epochs: int = 36
    patience: int = 6
    learning_rate: float = 5e-4
    weight_decay: float = 2e-4
    torch_num_threads: int = 4

    def validate(self) -> None:
        if min(
            self.beam_width,
            self.hidden_dim,
            self.feedforward_dim,
            self.layer_count,
            self.head_count,
            self.batch_size,
            self.epochs,
            self.patience,
            self.torch_num_threads,
        ) < 1:
            raise ValueError("ordinary beam reranker config is invalid")
        if self.hidden_dim % self.head_count:
            raise ValueError("ordinary beam reranker heads differ")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("ordinary beam reranker dropout differs")
        if self.learning_rate <= 0.0 or self.weight_decay < 0.0:
            raise ValueError("ordinary beam reranker optimizer differs")
        if self.feature_mode not in BEAM_FEATURE_MODES:
            raise ValueError("ordinary beam reranker feature mode differs")


@dataclass(frozen=True)
class _BeamPlanExample:
    row: OrdinaryRoadSetExample
    proposal_decisions: tuple[int, ...]
    proposal_selected_indices: tuple[tuple[int, ...], ...]
    proposal_features: tuple[tuple[float, ...], ...]
    acceptable_indices: tuple[int, ...]
    target_reachable: bool


def run_ordinary_beam_reranker_canary(
    *,
    member_store_root: Path,
    expansion_checkpoint_root: Path,
    output_root: Path,
    outer_fold: int,
    seed: int,
    config: BeamRerankerConfig = BeamRerankerConfig(),
    requested_device: str = "cuda",
) -> Path:
    """Train a strict inner/outer reranker over complete beam proposals."""
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
    fold_summary_path = checkpoint_root / f"fold_{outer_fold}_summary.json"
    with fold_summary_path.open("r", encoding="utf-8") as stream:
        fold_summary = json.load(stream)
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
        raise ValueError("ordinary beam expansion configs differ")
    training_examples = _generate_beam_examples(
        inner_model,
        training_rows,
        beam_width=config.beam_width,
        batch_size=config.batch_size,
        device=device,
        feature_mode=config.feature_mode,
    )
    validation_examples = _generate_beam_examples(
        inner_model,
        validation_rows,
        beam_width=config.beam_width,
        batch_size=config.batch_size,
        device=device,
        feature_mode=config.feature_mode,
    )
    outer_examples = _generate_beam_examples(
        outer_model,
        outer_rows,
        beam_width=config.beam_width,
        batch_size=config.batch_size,
        device=device,
        feature_mode=config.feature_mode,
    )
    feature_dim = _feature_dim(config.feature_mode)
    reranker = _new_reranker(
        config,
        feature_dim=feature_dim,
        device=device,
        seed=seed,
    )
    history = _fit_reranker(
        reranker,
        training_examples,
        validation_examples=validation_examples,
        config=config,
        device=device,
        seed=seed,
    )
    validation_scores = _score_reranker(
        reranker,
        validation_examples,
        batch_size=config.batch_size,
        device=device,
    )
    threshold = choose_zero_error_beam_threshold(validation_scores)
    outer_scores = _score_reranker(
        reranker,
        outer_examples,
        batch_size=config.batch_size,
        device=device,
    )
    for row in outer_scores:
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
    root.mkdir(parents=True)
    checkpoint_path = root / f"fold_{outer_fold}_reranker.pt"
    torch.save(
        {
            "schema_version": TARGET_A_SCHEMA_VERSION,
            "stage": "ORDINARY_BEAM_PLAN_RERANKER",
            "outer_fold": outer_fold,
            "inner_validation_fold": inner_fold,
            "acceptance_threshold": threshold,
            "config": asdict(config),
            "state_dict": reranker.state_dict(),
        },
        checkpoint_path,
    )
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, outer_scores)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_BEAM_PLAN_RERANKER_CANARY",
        "outer_fold": outer_fold,
        "inner_validation_fold": inner_fold,
        "config": asdict(config),
        "training_count": len(training_examples),
        "validation_count": len(validation_examples),
        "outer_count": len(outer_examples),
        "training_reachable_count": sum(
            row.target_reachable for row in training_examples
        ),
        "validation_reachable_count": sum(
            row.target_reachable for row in validation_examples
        ),
        "outer_reachable_count": sum(
            row.target_reachable for row in outer_examples
        ),
        "parameter_count": parameter_count(reranker),
        "history": history,
        "acceptance_threshold": threshold,
        "validation_metrics": _reranker_metrics(validation_scores),
        "metrics": _reranker_metrics(outer_scores),
        "feature_dim": feature_dim,
        "feature_mode": config.feature_mode,
        "feature_uses_truth": False,
        "proposal_generation_uses_truth": False,
        "label_contract": (
            "Exact complete plans are marked acceptable only after all "
            "proposal features are built. Unreachable targets supervise "
            "explicit ABSTAIN."
        ),
        "strict_oof_contract": (
            "The reranker trains on folds excluding inner and outer, "
            "selects epochs and safety threshold only on the held-out inner "
            "fold, and reports only the held-out outer fold."
        ),
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "This is one-fold ordinary-plan selection canary; two-seed full "
            "OOF, business-role completeness and final RoadGraph safety are "
            "not established."
        ),
        "read_summary": read_summary,
        "member_store_summary": _input_record(
            member_root / "summary.json"
        ),
        "expansion_summary": _input_record(
            checkpoint_root / "summary.json"
        ),
        "reranker_checkpoint": _input_record(checkpoint_path),
        "predictions": _input_record(prediction_path),
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def _generate_beam_examples(
    model: Any,
    rows: Sequence[OrdinaryRoadSetExample],
    *,
    beam_width: int,
    batch_size: int,
    device: torch.device,
    feature_mode: str,
) -> list[_BeamPlanExample]:
    result = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            batch_rows = rows[start : start + batch_size]
            batch = _batch_tensors(
                batch_rows,
                feature_source="oof",
                device=device,
                cardinality_count=model.cardinality_count,
                road_relation_dim=model.road_relation_dim,
            )
            outputs = _forward_model(model, batch)
            decision_log_probabilities = torch.log_softmax(
                outputs["decision_logits"],
                dim=-1,
            )
            member_probabilities = torch.sigmoid(outputs["member_logits"])
            ownership_probabilities = torch.softmax(
                outputs["ownership_logits"],
                dim=-1,
            )
            role_probabilities = torch.softmax(
                outputs["business_role_logits"],
                dim=-1,
            )
            for index, row in enumerate(batch_rows):
                length = len(row.road_ids)
                encoded = {
                    "candidate_encoded": outputs["candidate_encoded"][
                        index : index + 1, :length
                    ],
                    "graph_context": outputs["graph_context"][
                        index : index + 1
                    ],
                }
                relations = batch["road_relations"][
                    index : index + 1, :length, :length
                ]
                access_seeds = _row_access_seed_mask(
                    row,
                    feature_source="oof",
                ).to(device).unsqueeze(0)
                proposals = []
                for decision_index, source in enumerate(("SWSD", "RCSD")):
                    allowed = torch.tensor(
                        [value == source for value in row.sources],
                        dtype=torch.bool,
                        device=device,
                    ).unsqueeze(0)
                    if not bool(allowed.any()):
                        continue
                    decision_score = float(
                        decision_log_probabilities[
                            index, decision_index
                        ].item()
                    )
                    for proposal in beam_decode_complete_sets(
                        model,
                        encoded_outputs=encoded,
                        candidate_mask=allowed,
                        road_relations=relations,
                        access_seed_masks=access_seeds,
                        beam_width=beam_width,
                    ):
                        proposals.append(
                            {
                                **proposal,
                                "decision_index": decision_index,
                                "decision": DECISIONS[decision_index],
                                "log_probability": (
                                    decision_score
                                    + float(proposal["log_probability"])
                                ),
                            }
                        )
                proposals = _deduplicate_joint_proposals(
                    proposals,
                    beam_width=beam_width,
                )
                result.append(
                    _build_beam_example(
                        row,
                        proposals=proposals,
                        decision_log_probabilities=(
                            decision_log_probabilities[index]
                            .detach()
                            .to("cpu")
                        ),
                        member_probabilities=(
                            member_probabilities[index, :length]
                            .detach()
                            .to("cpu")
                        ),
                        ownership_probabilities=(
                            ownership_probabilities[index, :length]
                            .detach()
                            .to("cpu")
                        ),
                        role_probabilities=(
                            role_probabilities[index, :length]
                            .detach()
                            .to("cpu")
                        ),
                        candidate_embeddings=(
                            outputs["candidate_encoded"][index, :length]
                            .detach()
                            .to("cpu")
                        ),
                        graph_context=(
                            outputs["graph_context"][index]
                            .detach()
                            .to("cpu")
                        ),
                        road_relations=(
                            relations[0].detach().to("cpu")
                        ),
                        access_seeds=access_seeds[0].detach().to("cpu"),
                        feature_mode=feature_mode,
                    )
                )
            del batch, outputs
    return result


def _build_beam_example(
    row: OrdinaryRoadSetExample,
    *,
    proposals: Sequence[Mapping[str, Any]],
    decision_log_probabilities: torch.Tensor,
    member_probabilities: torch.Tensor,
    ownership_probabilities: torch.Tensor,
    role_probabilities: torch.Tensor,
    candidate_embeddings: torch.Tensor,
    graph_context: torch.Tensor,
    road_relations: torch.Tensor,
    access_seeds: torch.Tensor,
    feature_mode: str,
) -> _BeamPlanExample:
    scores = [float(value["log_probability"]) for value in proposals]
    top_score = max(scores, default=0.0)
    normalizer = (
        float(torch.logsumexp(torch.tensor(scores), dim=0).item())
        if scores
        else 0.0
    )
    decisions = [-1]
    selected_rows: list[tuple[int, ...]] = [tuple()]
    features = [
        _abstain_feature_vector(
            graph_context,
            feature_mode=feature_mode,
        )
    ]
    for rank, proposal in enumerate(proposals, start=1):
        decision_index = int(proposal["decision_index"])
        selected = tuple(
            int(value) for value in proposal["selected_indices"]
        )
        decisions.append(decision_index)
        selected_rows.append(selected)
        features.append(
            _proposal_feature_vector(
                rank=rank,
                beam_width=max(len(proposals), 1),
                decision_index=decision_index,
                selected=selected,
                log_probability=float(proposal["log_probability"]),
                top_log_probability=top_score,
                log_normalizer=normalizer,
                sources=row.sources,
                decision_log_probabilities=decision_log_probabilities,
                member_probabilities=member_probabilities,
                ownership_probabilities=ownership_probabilities,
                role_probabilities=role_probabilities,
                candidate_embeddings=candidate_embeddings,
                graph_context=graph_context,
                road_relations=road_relations,
                access_seeds=access_seeds,
                feature_mode=feature_mode,
            )
        )
    target = tuple(sorted(row.target_indices))
    acceptable = tuple(
        index
        for index, (decision, selected) in enumerate(
            zip(decisions, selected_rows, strict=True)
        )
        if decision == row.decision and selected == target
    )
    reachable = bool(acceptable)
    if not acceptable:
        acceptable = (0,)
    return _BeamPlanExample(
        row=row,
        proposal_decisions=tuple(decisions),
        proposal_selected_indices=tuple(selected_rows),
        proposal_features=tuple(features),
        acceptable_indices=acceptable,
        target_reachable=reachable,
    )


def _abstain_feature_vector(
    graph_context: torch.Tensor,
    *,
    feature_mode: str,
) -> tuple[float, ...]:
    scalar = (1.0,) + (0.0,) * (BEAM_SCALAR_FEATURE_DIM - 1)
    if feature_mode == "SCALAR":
        values = scalar
    elif feature_mode == "EMBEDDING":
        if graph_context.shape != (BEAM_ROAD_EMBEDDING_DIM,):
            raise ValueError("ordinary beam graph context dimension differs")
        values = (
            *scalar,
            *graph_context.tolist(),
            *(0.0,) * (BEAM_ROAD_EMBEDDING_DIM * 4),
        )
    elif feature_mode == "RELATIONAL":
        values = (*scalar, *(0.0,) * BEAM_RELATION_SUMMARY_DIM)
    else:
        raise ValueError("ordinary beam feature mode differs")
    if len(values) != _feature_dim(feature_mode):
        raise AssertionError("ordinary beam ABSTAIN feature differs")
    return tuple(float(value) for value in values)


def _proposal_feature_vector(
    *,
    rank: int,
    beam_width: int,
    decision_index: int,
    selected: Sequence[int],
    log_probability: float,
    top_log_probability: float,
    log_normalizer: float,
    sources: Sequence[str],
    decision_log_probabilities: torch.Tensor,
    member_probabilities: torch.Tensor,
    ownership_probabilities: torch.Tensor,
    role_probabilities: torch.Tensor,
    candidate_embeddings: torch.Tensor,
    graph_context: torch.Tensor,
    road_relations: torch.Tensor,
    access_seeds: torch.Tensor,
    feature_mode: str,
) -> tuple[float, ...]:
    source = "SWSD" if decision_index == 0 else "RCSD"
    source_indices = [
        index for index, value in enumerate(sources) if value == source
    ]
    selected_indices = list(selected)
    excluded_indices = [
        value for value in source_indices if value not in set(selected_indices)
    ]
    selected_member = member_probabilities[selected_indices].tolist()
    excluded_member = member_probabilities[excluded_indices].tolist()
    selected_owner = ownership_probabilities[selected_indices, 1].tolist()
    selected_no_owner = ownership_probabilities[
        selected_indices, 2
    ].tolist()
    selected_main = role_probabilities[selected_indices, 1].tolist()
    selected_connector = role_probabilities[
        selected_indices, 2
    ].tolist()
    selected_attached = role_probabilities[
        selected_indices, 3
    ].tolist()
    selected_count = len(selected_indices)
    source_count = len(source_indices)
    endpoint_relations = road_relations[..., 0] > 0.5
    edge_count = sum(
        bool(endpoint_relations[left, right])
        for offset, left in enumerate(selected_indices)
        for right in selected_indices[offset + 1 :]
    )
    possible_edges = selected_count * max(selected_count - 1, 0) / 2
    selected_seed_count = sum(
        bool(access_seeds[index]) for index in selected_indices
    )
    source_seed_count = sum(
        bool(access_seeds[index]) for index in source_indices
    )
    scalar_values = (
        0.0,
        float(decision_index == 0),
        float(decision_index == 1),
        1.0 / rank,
        rank / max(beam_width, 1),
        math.tanh(log_probability / 10.0),
        math.tanh(log_probability / max(selected_count, 1) / 3.0),
        math.tanh((log_probability - top_log_probability) / 5.0),
        math.exp(min(0.0, log_probability - log_normalizer)),
        math.exp(float(decision_log_probabilities[decision_index])),
        math.tanh(selected_count / 8.0),
        math.tanh(source_count / 32.0),
        selected_count / max(source_count, 1),
        selected_count / max(len(sources), 1),
        _mean(selected_member),
        min(selected_member, default=0.0),
        max(selected_member, default=0.0),
        max(excluded_member, default=0.0),
        min(selected_member, default=0.0)
        - max(excluded_member, default=0.0),
        _mean(selected_owner),
        min(selected_owner, default=0.0),
        _mean(selected_no_owner),
        _mean(selected_main),
        min(selected_main, default=0.0),
        max(selected_connector, default=0.0),
        max(selected_attached, default=0.0),
        edge_count / max(possible_edges, 1.0),
        math.tanh(
            _component_count(selected_indices, endpoint_relations) / 4.0
        ),
        selected_seed_count / max(selected_count, 1),
        selected_seed_count / max(source_seed_count, 1),
        float(source_seed_count > 0),
        float(selected_count == 0),
    )
    if len(scalar_values) != BEAM_SCALAR_FEATURE_DIM:
        raise AssertionError("ordinary beam scalar feature dimension differs")
    if feature_mode == "SCALAR":
        values = scalar_values
    elif feature_mode == "EMBEDDING":
        if (
            candidate_embeddings.shape
            != (len(sources), BEAM_ROAD_EMBEDDING_DIM)
            or graph_context.shape != (BEAM_ROAD_EMBEDDING_DIM,)
        ):
            raise ValueError(
                "ordinary beam Road embedding dimension differs"
            )
        selected_mean, selected_maximum = _embedding_pool(
            candidate_embeddings,
            selected_indices,
        )
        excluded_mean, excluded_maximum = _embedding_pool(
            candidate_embeddings,
            excluded_indices,
        )
        values = (
            *scalar_values,
            *graph_context.tolist(),
            *selected_mean,
            *selected_maximum,
            *excluded_mean,
            *excluded_maximum,
        )
    elif feature_mode == "RELATIONAL":
        values = (
            *scalar_values,
            *_relational_feature_vector(
                selected_indices=selected_indices,
                excluded_indices=excluded_indices,
                road_relations=road_relations,
                ownership_probabilities=ownership_probabilities,
                role_probabilities=role_probabilities,
                access_seeds=access_seeds,
            ),
        )
    else:
        raise ValueError("ordinary beam feature mode differs")
    if len(values) != _feature_dim(feature_mode):
        raise AssertionError("ordinary beam feature dimension differs")
    return tuple(float(value) for value in values)


def _embedding_pool(
    embeddings: torch.Tensor,
    indices: Sequence[int],
) -> tuple[list[float], list[float]]:
    if not indices:
        empty = [0.0] * BEAM_ROAD_EMBEDDING_DIM
        return empty, empty
    selected = embeddings[list(indices)]
    return (
        selected.mean(dim=0).tolist(),
        selected.max(dim=0).values.tolist(),
    )


def _relational_feature_vector(
    *,
    selected_indices: Sequence[int],
    excluded_indices: Sequence[int],
    road_relations: torch.Tensor,
    ownership_probabilities: torch.Tensor,
    role_probabilities: torch.Tensor,
    access_seeds: torch.Tensor,
) -> tuple[float, ...]:
    if (
        road_relations.ndim != 3
        or road_relations.shape[:2]
        != (ownership_probabilities.shape[0],) * 2
        or road_relations.shape[-1] != 13
        or role_probabilities.shape[0] != road_relations.shape[0]
        or access_seeds.shape != (road_relations.shape[0],)
    ):
        raise ValueError("ordinary beam relational evidence differs")
    selected = list(selected_indices)
    excluded = list(excluded_indices)
    endpoint_relations = road_relations[..., 0] > 0.5
    selected_relations = _pair_relation_pool(
        road_relations,
        selected,
        selected,
        same_group=True,
    )
    cut_relations = _pair_relation_pool(
        road_relations,
        selected,
        excluded,
        same_group=False,
    )
    excluded_relations = _pair_relation_pool(
        road_relations,
        excluded,
        excluded,
        same_group=True,
    )
    degrees = [
        sum(
            bool(endpoint_relations[left, right])
            for right in selected
            if right != left
        )
        for left in selected
    ]
    degree_scale = max(len(selected) - 1, 1)
    components = _component_members(selected, endpoint_relations)
    access_component_count = sum(
        any(bool(access_seeds[index]) for index in component)
        for component in components
    )
    cut_endpoint_count = sum(
        bool(endpoint_relations[left, right])
        for left in selected
        for right in excluded
    )
    topology = (
        _mean(degrees) / degree_scale,
        max(degrees, default=0) / degree_scale,
        sum(value == 1 for value in degrees) / max(len(degrees), 1),
        sum(value == 0 for value in degrees) / max(len(degrees), 1),
        sum(value >= 3 for value in degrees) / max(len(degrees), 1),
        len(components) / max(len(selected), 1),
        access_component_count / max(len(components), 1),
        cut_endpoint_count / max(len(selected) * len(excluded), 1),
    )
    excluded_owner = ownership_probabilities[excluded, 1].tolist()
    excluded_no_owner = ownership_probabilities[excluded, 2].tolist()
    excluded_main = role_probabilities[excluded, 1].tolist()
    excluded_connector = role_probabilities[excluded, 2].tolist()
    excluded_attached = role_probabilities[excluded, 3].tolist()
    excluded_business = (
        _mean(excluded_owner),
        max(excluded_owner, default=0.0),
        _mean(excluded_no_owner),
        max(excluded_no_owner, default=0.0),
        _mean(excluded_main),
        max(excluded_main, default=0.0),
        max(excluded_connector, default=0.0),
        max(excluded_attached, default=0.0),
    )
    values = (
        *selected_relations,
        *cut_relations,
        *excluded_relations,
        *topology,
        *excluded_business,
    )
    if len(values) != BEAM_RELATION_SUMMARY_DIM:
        raise AssertionError("ordinary beam relation summary differs")
    return tuple(float(value) for value in values)


def _pair_relation_pool(
    road_relations: torch.Tensor,
    left_indices: Sequence[int],
    right_indices: Sequence[int],
    *,
    same_group: bool,
) -> tuple[float, ...]:
    pairs = (
        [
            (left, right)
            for offset, left in enumerate(left_indices)
            for right in left_indices[offset + 1 :]
        ]
        if same_group
        else [
            (left, right)
            for left in left_indices
            for right in right_indices
        ]
    )
    if not pairs:
        return (0.0,) * (road_relations.shape[-1] * 2)
    values = torch.stack(
        [road_relations[left, right] for left, right in pairs],
        dim=0,
    )
    return tuple(
        float(value)
        for value in (
            *values.mean(dim=0).tolist(),
            *values.max(dim=0).values.tolist(),
        )
    )


def _feature_dim(feature_mode: str) -> int:
    if feature_mode == "SCALAR":
        return BEAM_SCALAR_FEATURE_DIM
    if feature_mode == "EMBEDDING":
        return BEAM_EMBEDDING_FEATURE_DIM
    if feature_mode == "RELATIONAL":
        return BEAM_RELATIONAL_FEATURE_DIM
    raise ValueError("ordinary beam feature mode differs")


def _component_count(
    selected: Sequence[int],
    endpoint_relations: torch.Tensor,
) -> int:
    return len(_component_members(selected, endpoint_relations))


def _component_members(
    selected: Sequence[int],
    endpoint_relations: torch.Tensor,
) -> list[set[int]]:
    remaining = set(int(value) for value in selected)
    result = []
    while remaining:
        first = remaining.pop()
        component = {first}
        stack = [first]
        while stack:
            current = stack.pop()
            connected = {
                value
                for value in remaining
                if bool(endpoint_relations[current, value])
            }
            remaining -= connected
            component |= connected
            stack.extend(connected)
        result.append(component)
    return result


def _mean(values: Sequence[float]) -> float:
    return sum(float(value) for value in values) / len(values) if values else 0.0


def _new_reranker(
    config: BeamRerankerConfig,
    *,
    feature_dim: int,
    device: torch.device,
    seed: int,
) -> TargetAOrdinaryPlanProposalReranker:
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    return TargetAOrdinaryPlanProposalReranker(
        feature_dim=feature_dim,
        hidden_dim=config.hidden_dim,
        feedforward_dim=config.feedforward_dim,
        layer_count=config.layer_count,
        head_count=config.head_count,
        dropout=config.dropout,
    ).to(device)


def _fit_reranker(
    model: TargetAOrdinaryPlanProposalReranker,
    training: Sequence[_BeamPlanExample],
    *,
    validation_examples: Sequence[_BeamPlanExample],
    config: BeamRerankerConfig,
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
        model.train()
        generator = random.Random(seed + epoch)
        order = list(training)
        generator.shuffle(order)
        total = 0.0
        weight_total = 0.0
        for start in range(0, len(order), config.batch_size):
            batch_rows = order[start : start + config.batch_size]
            batch = _collate(batch_rows, device=device)
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
            if not bool(torch.isfinite(loss)):
                raise RuntimeError("ordinary beam reranker loss is non-finite")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            optimizer.step()
            total += float((raw.detach() * batch["weights"]).sum().item())
            weight_total += float(batch["weights"].sum().item())
        train_loss = total / max(weight_total, 1e-9)
        validation_loss = _evaluate_loss(
            model,
            validation_examples,
            batch_size=config.batch_size,
            device=device,
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
            best_state = copy.deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
            if stale >= config.patience:
                break
    model.load_state_dict(best_state)
    model.eval()
    return history


def _evaluate_loss(
    model: TargetAOrdinaryPlanProposalReranker,
    rows: Sequence[_BeamPlanExample],
    *,
    batch_size: int,
    device: torch.device,
) -> float:
    model.eval()
    total = 0.0
    weight_total = 0.0
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            batch = _collate(rows[start : start + batch_size], device=device)
            raw = acceptable_plan_nll(
                model(batch["features"], batch["valid"]),
                batch["acceptable"],
                batch["valid"],
            )
            total += float((raw * batch["weights"]).sum().item())
            weight_total += float(batch["weights"].sum().item())
    return total / max(weight_total, 1e-9)


def _collate(
    rows: Sequence[_BeamPlanExample],
    *,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    count = max(len(row.proposal_features) for row in rows)
    feature_dim = len(rows[0].proposal_features[0])
    if any(
        len(features) != feature_dim
        for row in rows
        for features in row.proposal_features
    ):
        raise ValueError("ordinary beam feature dimensions differ")
    features = torch.zeros(
        len(rows),
        count,
        feature_dim,
        dtype=torch.float32,
        device=device,
    )
    valid = torch.zeros(
        len(rows), count, dtype=torch.bool, device=device
    )
    acceptable = torch.zeros_like(valid)
    for index, row in enumerate(rows):
        length = len(row.proposal_features)
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
        "weights": torch.tensor(
            [row.row.sample_weight for row in rows],
            dtype=torch.float32,
            device=device,
        ),
    }


def _score_reranker(
    model: TargetAOrdinaryPlanProposalReranker,
    rows: Sequence[_BeamPlanExample],
    *,
    batch_size: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    result = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            values = rows[start : start + batch_size]
            batch = _collate(values, device=device)
            probabilities = torch.softmax(
                model(batch["features"], batch["valid"]),
                dim=-1,
            )
            top_values, top_indices = probabilities.topk(2, dim=-1)
            for index, value in enumerate(values):
                selected_index = int(top_indices[index, 0].item())
                selected_decision_index = value.proposal_decisions[
                    selected_index
                ]
                selected = value.proposal_selected_indices[selected_index]
                label_correct = selected_index in value.acceptable_indices
                raw_complete_exact = bool(
                    selected_index > 0 and label_correct
                )
                confidence = float(
                    top_values[index, 0].item()
                    * max(
                        0.0,
                        (
                            top_values[index, 0]
                            - top_values[index, 1]
                        ).item(),
                    )
                )
                result.append(
                    {
                        "schema_version": TARGET_A_SCHEMA_VERSION,
                        "case_key": value.row.case_key,
                        "segment_id": value.row.segment_id,
                        "fold": value.row.fold,
                        "truth_decision": DECISIONS[value.row.decision],
                        "truth_cardinality": len(
                            value.row.target_indices
                        ),
                        "target_reachable": value.target_reachable,
                        "proposal_count": len(value.proposal_features),
                        "selected_proposal_index": selected_index,
                        "selected_decision": (
                            DECISIONS[selected_decision_index]
                            if selected_decision_index >= 0
                            else "ABSTAIN"
                        ),
                        "selected_road_ids": [
                            value.row.road_ids[item] for item in selected
                        ],
                        "selected_cardinality": len(selected),
                        "selection_label_correct": label_correct,
                        "raw_complete_exact": raw_complete_exact,
                        "release_eligible": bool(
                            value.row.oof_anchor_release_ready
                        ),
                        "raw_automatic": bool(
                            selected_index > 0
                            and value.row.oof_anchor_release_ready
                        ),
                        "confidence": confidence,
                    }
                )
    return result


def choose_zero_error_beam_threshold(
    rows: Sequence[Mapping[str, Any]],
) -> float:
    unsafe = [
        float(row["confidence"])
        for row in rows
        if bool(row["raw_automatic"])
        and not bool(row["raw_complete_exact"])
    ]
    return math.nextafter(max(unsafe), math.inf) if unsafe else 0.0


def _reranker_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    count = len(rows)
    automatic = sum(bool(row.get("automatic")) for row in rows)
    unsafe = sum(bool(row.get("unsafe_automatic")) for row in rows)
    raw_automatic = sum(bool(row["raw_automatic"]) for row in rows)
    raw_unsafe = sum(
        bool(row["raw_automatic"]) and not bool(row["raw_complete_exact"])
        for row in rows
    )
    long_rows = [
        row for row in rows if int(row["truth_cardinality"]) >= 10
    ]
    return {
        "count": count,
        "reachable_count": sum(bool(row["target_reachable"]) for row in rows),
        "selection_label_accuracy": sum(
            bool(row["selection_label_correct"]) for row in rows
        )
        / count,
        "raw_complete_exact": sum(
            bool(row["raw_complete_exact"]) for row in rows
        )
        / count,
        "raw_automatic_count": raw_automatic,
        "raw_unsafe_count": raw_unsafe,
        "automatic_count": automatic,
        "automatic_coverage": automatic / count,
        "unsafe_automatic_count": unsafe,
        "long_10_plus_count": len(long_rows),
        "long_10_plus_reachable_count": sum(
            bool(row["target_reachable"]) for row in long_rows
        ),
        "long_10_plus_raw_exact_count": sum(
            bool(row["raw_complete_exact"]) for row in long_rows
        ),
    }


def _assert_case_disjoint(
    left: Sequence[OrdinaryRoadSetExample],
    right: Sequence[OrdinaryRoadSetExample],
) -> None:
    overlap = {row.case_key for row in left} & {
        row.case_key for row in right
    }
    if overlap:
        raise ValueError("ordinary beam reranker Case split overlaps")


__all__ = [
    "BEAM_EMBEDDING_FEATURE_DIM",
    "BEAM_FEATURE_MODES",
    "BEAM_RELATIONAL_FEATURE_DIM",
    "BEAM_SCALAR_FEATURE_DIM",
    "BeamRerankerConfig",
    "choose_zero_error_beam_threshold",
    "run_ordinary_beam_reranker_canary",
]
