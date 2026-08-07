from __future__ import annotations

import itertools
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_beam_reranker import (
    BEAM_RELATIONAL_FEATURE_DIM,
    _BeamPlanExample,
    _generate_beam_examples,
    _reranker_metrics,
    _assert_case_disjoint,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISIONS,
    _input_record,
    _write_json,
    _write_jsonl,
    read_ordinary_road_set_examples,
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
class StructuredEnergyWeights:
    total_log_probability: float
    per_road_log_probability: float
    membership_margin: float
    ownership_margin: float
    role_margin: float


def run_ordinary_beam_structured_energy_canary(
    *,
    member_store_root: Path,
    expansion_checkpoint_root: Path,
    output_root: Path,
    outer_fold: int,
    beam_width: int = 16,
    batch_size: int = 32,
    requested_device: str = "cuda",
) -> Path:
    """Fit interpretable complete-plan energy only on the inner fold."""
    started = time.perf_counter()
    if beam_width < 1 or batch_size < 1 or outer_fold < 0:
        raise ValueError("ordinary beam structured-energy config differs")
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
    with (
        checkpoint_root / f"fold_{outer_fold}_summary.json"
    ).open("r", encoding="utf-8") as stream:
        fold_summary = json.load(stream)
    inner_fold = int(fold_summary["inner_validation_fold"])
    inner_rows = [row for row in rows if row.fold == inner_fold]
    outer_rows = [row for row in rows if row.fold == outer_fold]
    _assert_case_disjoint(inner_rows, outer_rows)
    device = _resolve_device(requested_device)
    inner_model, inner_config = _load_model(
        checkpoint_root / f"fold_{outer_fold}_inner_checkpoint.pt",
        rows=inner_rows,
        device=device,
    )
    outer_model, outer_config = _load_model(
        checkpoint_root / f"fold_{outer_fold}_checkpoint.pt",
        rows=outer_rows,
        device=device,
    )
    if inner_config != outer_config:
        raise ValueError("ordinary beam expansion configs differ")
    inner_examples = _generate_beam_examples(
        inner_model,
        inner_rows,
        beam_width=beam_width,
        batch_size=batch_size,
        device=device,
        feature_mode="RELATIONAL",
    )
    outer_examples = _generate_beam_examples(
        outer_model,
        outer_rows,
        beam_width=beam_width,
        batch_size=batch_size,
        device=device,
        feature_mode="RELATIONAL",
    )
    selection = select_structured_energy_weights(inner_examples)
    weights = selection["weights"]
    inner_scores = score_structured_energy_examples(
        inner_examples,
        weights=weights,
    )
    threshold = _choose_zero_error_threshold(inner_scores)
    outer_scores = score_structured_energy_examples(
        outer_examples,
        weights=weights,
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
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, outer_scores)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ORDINARY_BEAM_STRUCTURED_ENERGY_CANARY",
        "outer_fold": outer_fold,
        "inner_validation_fold": inner_fold,
        "beam_width": beam_width,
        "feature_mode": "RELATIONAL",
        "feature_dim": BEAM_RELATIONAL_FEATURE_DIM,
        "selected_weights": asdict(weights),
        "weight_selection": selection["summary"],
        "acceptance_threshold": threshold,
        "inner_count": len(inner_examples),
        "outer_count": len(outer_examples),
        "inner_metrics": _reranker_metrics(inner_scores),
        "metrics": _reranker_metrics(outer_scores),
        "feature_uses_truth": False,
        "proposal_generation_uses_truth": False,
        "selection_contract": (
            "Only the held-out inner fold selects five non-negative energy "
            "weights and the zero-error confidence threshold. The outer "
            "fold is read once for final evaluation."
        ),
        "energy_contract": (
            "Complete-plan score combines model beam probability, "
            "per-Road-normalized beam probability, membership inclusion "
            "margin, ownership inclusion margin and business-role "
            "inclusion margin. No terminal labels enter plan features."
        ),
        "release_gate": "NO_GO",
        "release_no_go_reason": (
            "This is one-fold ordinary structured-energy canary; full OOF, "
            "two-seed agreement and final RoadGraph safety are not passed."
        ),
        "read_summary": read_summary,
        "member_store_summary": _input_record(
            member_root / "summary.json"
        ),
        "expansion_summary": _input_record(
            checkpoint_root / "summary.json"
        ),
        "predictions": _input_record(prediction_path),
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_json(root / "summary.json", summary)
    return root


def select_structured_energy_weights(
    examples: Sequence[_BeamPlanExample],
) -> dict[str, Any]:
    candidates = (
        (0.0, 0.25, 0.5, 1.0),
        (0.0, 0.5, 1.0, 2.0, 4.0),
        (0.0, 0.5, 1.0, 2.0, 4.0),
        (0.0, 0.5, 1.0, 2.0),
        (0.0, 0.5, 1.0, 2.0),
    )
    best: tuple[tuple[float, ...], StructuredEnergyWeights] | None = None
    top_rows = []
    total_weight = sum(row.row.sample_weight for row in examples)
    long_count = sum(len(row.row.target_indices) >= 10 for row in examples)
    for raw in itertools.product(*candidates):
        weights = StructuredEnergyWeights(*map(float, raw))
        correct_weight = 0.0
        correct_count = 0
        long_correct = 0
        for example in examples:
            selected = _select_proposal_index(example, weights=weights)
            correct = selected in example.acceptable_indices
            correct_weight += example.row.sample_weight * correct
            correct_count += int(correct)
            long_correct += int(
                correct and len(example.row.target_indices) >= 10
            )
        weighted_accuracy = correct_weight / max(total_weight, 1e-9)
        long_accuracy = long_correct / max(long_count, 1)
        simplicity = sum(abs(value) for value in raw)
        score = (
            weighted_accuracy,
            long_accuracy,
            correct_count / len(examples),
            -simplicity,
            *(-float(value) for value in raw),
        )
        top_rows.append(
            {
                "weights": asdict(weights),
                "weighted_label_accuracy": weighted_accuracy,
                "label_accuracy": correct_count / len(examples),
                "long_10_plus_accuracy": long_accuracy,
            }
        )
        if best is None or score > best[0]:
            best = (score, weights)
    if best is None:
        raise ValueError("ordinary beam energy grid is empty")
    top_rows.sort(
        key=lambda row: (
            -row["weighted_label_accuracy"],
            -row["long_10_plus_accuracy"],
            -row["label_accuracy"],
            sum(abs(value) for value in row["weights"].values()),
        )
    )
    return {
        "weights": best[1],
        "summary": {
            "candidate_count": math.prod(len(values) for values in candidates),
            "top_candidates": top_rows[:10],
        },
    }


def score_structured_energy_examples(
    examples: Sequence[_BeamPlanExample],
    *,
    weights: StructuredEnergyWeights,
) -> list[dict[str, Any]]:
    result = []
    for example in examples:
        energies = [
            proposal_energy(features, weights=weights)
            for features in example.proposal_features[1:]
        ]
        if not energies:
            raise ValueError("ordinary beam energy proposals are empty")
        probabilities = torch.softmax(
            torch.tensor(energies, dtype=torch.float64),
            dim=0,
        )
        count = min(2, len(energies))
        top_values, top_indices = probabilities.topk(count)
        selected_plan_offset = int(top_indices[0].item())
        selected_index = selected_plan_offset + 1
        if count > 1:
            margin = float((top_values[0] - top_values[1]).item())
        else:
            margin = float(top_values[0].item())
        confidence = float(top_values[0].item()) * max(0.0, margin)
        selected_decision_index = example.proposal_decisions[selected_index]
        selected = example.proposal_selected_indices[selected_index]
        correct = selected_index in example.acceptable_indices
        result.append(
            {
                "schema_version": TARGET_A_SCHEMA_VERSION,
                "case_key": example.row.case_key,
                "segment_id": example.row.segment_id,
                "fold": example.row.fold,
                "truth_decision": DECISIONS[example.row.decision],
                "truth_cardinality": len(example.row.target_indices),
                "target_reachable": example.target_reachable,
                "proposal_count": len(energies),
                "selected_proposal_index": selected_index,
                "selected_decision": DECISIONS[selected_decision_index],
                "selected_road_ids": [
                    example.row.road_ids[index] for index in selected
                ],
                "selected_cardinality": len(selected),
                "selection_label_correct": correct,
                "raw_complete_exact": correct,
                "release_eligible": bool(
                    example.row.oof_anchor_release_ready
                ),
                "raw_automatic": bool(
                    example.row.oof_anchor_release_ready
                ),
                "confidence": confidence,
            }
        )
    return result


def proposal_energy(
    features: Sequence[float],
    *,
    weights: StructuredEnergyWeights,
) -> float:
    if len(features) != BEAM_RELATIONAL_FEATURE_DIM:
        raise ValueError("ordinary beam energy feature dimension differs")
    total_log_probability = _inverse_tanh(float(features[5])) * 10.0
    per_road_log_probability = _inverse_tanh(float(features[6])) * 3.0
    membership_margin = float(features[18])
    ownership_margin = float(features[19]) - float(features[119])
    role_margin = float(features[22]) - float(features[123])
    return (
        weights.total_log_probability * total_log_probability
        + weights.per_road_log_probability * per_road_log_probability
        + weights.membership_margin * membership_margin
        + weights.ownership_margin * ownership_margin
        + weights.role_margin * role_margin
    )


def _inverse_tanh(value: float) -> float:
    clipped = min(max(value, -1.0 + 1e-7), 1.0 - 1e-7)
    return math.atanh(clipped)


def _select_proposal_index(
    example: _BeamPlanExample,
    *,
    weights: StructuredEnergyWeights,
) -> int:
    energies = [
        proposal_energy(features, weights=weights)
        for features in example.proposal_features[1:]
    ]
    return max(
        range(1, len(example.proposal_features)),
        key=lambda index: (energies[index - 1], -index),
    )


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


__all__ = [
    "StructuredEnergyWeights",
    "proposal_energy",
    "run_ordinary_beam_structured_energy_canary",
    "score_structured_energy_examples",
    "select_structured_energy_weights",
]
