from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Mapping

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    ORDINARY_SET_SOURCE_RCSD,
    ORDINARY_SET_SOURCE_SWSD,
    EndToEndOrdinarySetBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_network import (
    TargetAEndToEndOrdinarySetNetwork,
)


def beam_decode_ordinary_side(
    model: TargetAEndToEndOrdinarySetNetwork,
    encoded_outputs: Mapping[str, torch.Tensor],
    ordinary_set: EndToEndOrdinarySetBatch,
    *,
    side_index: int,
    effective_decision: int,
    beam_width: int,
    stop_logit_bias: float = 0.0,
) -> list[dict[str, Any]]:
    """Propose complete source-gated Road sets without reading labels."""
    if (
        beam_width < 1
        or len(ordinary_set.case_keys) != 1
        or side_index not in {0, 1}
    ):
        raise ValueError("ordinary side beam config differs")
    road_count = ordinary_set.side_road_mask.shape[-1]
    sources = ordinary_set.side_road_source_indices
    if effective_decision == ORDINARY_SET_SOURCE_SWSD:
        source_mask = sources.eq(ORDINARY_SET_SOURCE_SWSD)
    elif effective_decision == ORDINARY_SET_SOURCE_RCSD:
        source_mask = sources.eq(ORDINARY_SET_SOURCE_RCSD)
    else:
        return []
    allowed = torch.zeros_like(ordinary_set.side_road_mask)
    allowed[0, side_index] = (
        ordinary_set.side_road_mask[0, side_index]
        & source_mask[0, side_index]
    )
    maximum_steps = int(allowed[0, side_index].sum().item()) + 1
    if maximum_steps <= 1:
        return []
    beams: list[tuple[tuple[int, ...], float, bool]] = [
        ((), 0.0, False)
    ]
    for _ in range(maximum_steps):
        active = [value for value in beams if not value[2]]
        if not active:
            break
        selected_masks = torch.zeros(
            1,
            2,
            len(active),
            road_count,
            dtype=torch.bool,
            device=allowed.device,
        )
        for state_index, (selected, _, _) in enumerate(active):
            if selected:
                selected_masks[
                    0,
                    side_index,
                    state_index,
                    list(selected),
                ] = True
        step = model.decode_ordinary_next(
            encoded_outputs,
            ordinary_set,
            selected_masks,
            candidate_mask=allowed,
        )
        logits = torch.cat(
            (
                step["next_road_logits"][0, side_index],
                (
                    step["stop_logits"][0, side_index]
                    + float(stop_logit_bias)
                ).unsqueeze(-1),
            ),
            dim=-1,
        )
        log_probabilities = torch.log_softmax(logits, dim=-1)
        expanded = [value for value in beams if value[2]]
        for state_index, (selected, score, _) in enumerate(active):
            count = min(beam_width, log_probabilities.shape[-1])
            values, actions = torch.topk(
                log_probabilities[state_index],
                count,
            )
            for value, action in zip(
                values.tolist(),
                actions.tolist(),
                strict=True,
            ):
                if not math.isfinite(value) or value < -1e20:
                    continue
                stopped = action == road_count
                next_selected = (
                    selected
                    if stopped
                    else tuple(sorted((*selected, int(action))))
                )
                expanded.append(
                    (
                        next_selected,
                        score + float(value),
                        stopped,
                    )
                )
        beams = _deduplicate_beam_states(
            expanded,
            beam_width=beam_width,
        )
    completed = [value for value in beams if value[2]]
    return [
        {
            "selected_indices": list(selected),
            "log_probability": float(score),
        }
        for selected, score, _ in completed
    ]


def diverse_beam_decode_ordinary_side(
    model: TargetAEndToEndOrdinarySetNetwork,
    encoded_outputs: Mapping[str, torch.Tensor],
    ordinary_set: EndToEndOrdinarySetBatch,
    *,
    side_index: int,
    effective_decision: int,
    active_beam_width: int,
    proposal_width: int,
    cardinality_logits: torch.Tensor | None = None,
    stop_logit_bias: float = 0.0,
    length_normalization_alpha: float = 0.7,
    cardinality_score_weight: float = 0.5,
) -> list[dict[str, Any]]:
    """Keep unfinished paths independent from completed proposal slots."""
    if (
        min(active_beam_width, proposal_width) < 1
        or length_normalization_alpha < 0.0
        or cardinality_score_weight < 0.0
        or len(ordinary_set.case_keys) != 1
        or side_index not in {0, 1}
    ):
        raise ValueError("ordinary diverse beam config differs")
    road_count = ordinary_set.side_road_mask.shape[-1]
    sources = ordinary_set.side_road_source_indices
    if effective_decision == ORDINARY_SET_SOURCE_SWSD:
        source_mask = sources.eq(ORDINARY_SET_SOURCE_SWSD)
    elif effective_decision == ORDINARY_SET_SOURCE_RCSD:
        source_mask = sources.eq(ORDINARY_SET_SOURCE_RCSD)
    else:
        return []
    allowed = torch.zeros_like(ordinary_set.side_road_mask)
    allowed[0, side_index] = (
        ordinary_set.side_road_mask[0, side_index]
        & source_mask[0, side_index]
    )
    allowed_count = int(allowed[0, side_index].sum().item())
    if allowed_count < 1:
        return []
    active: list[tuple[tuple[int, ...], float]] = [((), 0.0)]
    completed: list[tuple[tuple[int, ...], float]] = []
    for _ in range(allowed_count + 1):
        if not active:
            break
        selected_masks = torch.zeros(
            1,
            2,
            len(active),
            road_count,
            dtype=torch.bool,
            device=allowed.device,
        )
        for state_index, (selected, _) in enumerate(active):
            if selected:
                selected_masks[
                    0,
                    side_index,
                    state_index,
                    list(selected),
                ] = True
        step = model.decode_ordinary_next(
            encoded_outputs,
            ordinary_set,
            selected_masks,
            candidate_mask=allowed,
        )
        logits = torch.cat(
            (
                step["next_road_logits"][0, side_index],
                (
                    step["stop_logits"][0, side_index]
                    + float(stop_logit_bias)
                ).unsqueeze(-1),
            ),
            dim=-1,
        )
        log_probabilities = torch.log_softmax(logits, dim=-1)
        expanded: list[tuple[tuple[int, ...], float]] = []
        for state_index, (selected, score) in enumerate(active):
            count = min(
                active_beam_width + 1,
                log_probabilities.shape[-1],
            )
            values, actions = torch.topk(
                log_probabilities[state_index],
                count,
            )
            for value, action in zip(
                values.tolist(),
                actions.tolist(),
                strict=True,
            ):
                if not math.isfinite(value) or value < -1e20:
                    continue
                next_score = score + float(value)
                if action == road_count:
                    completed.append((selected, next_score))
                else:
                    expanded.append(
                        (
                            tuple(sorted((*selected, int(action)))),
                            next_score,
                        )
                    )
        active = _deduplicate_active_states(
            expanded,
            beam_width=active_beam_width,
        )
    return _rank_diverse_completed_sets(
        completed,
        proposal_width=proposal_width,
        cardinality_logits=cardinality_logits,
        length_normalization_alpha=length_normalization_alpha,
        cardinality_score_weight=cardinality_score_weight,
    )


def ranked_subset_proposals(
    member_logits: torch.Tensor,
    cardinality_logits: torch.Tensor,
    road_relations: torch.Tensor,
    allowed_mask: torch.Tensor,
    *,
    proposal_width: int = 128,
    cardinality_width: int = 8,
    boundary_width: int = 4,
    seed_width: int = 6,
) -> list[dict[str, Any]]:
    """Build complete Road-set proposals from inference-only evidence."""
    road_count = int(member_logits.shape[0])
    if (
        member_logits.ndim != 1
        or cardinality_logits.ndim != 1
        or cardinality_logits.shape[0] < 2
        or road_relations.ndim != 3
        or road_relations.shape[:2] != (road_count, road_count)
        or road_relations.shape[-1] < 1
        or allowed_mask.shape != (road_count,)
        or min(
            proposal_width,
            cardinality_width,
            boundary_width,
            seed_width,
        )
        < 1
    ):
        raise ValueError("ranked subset proposal evidence differs")
    members = member_logits.detach().to(
        device="cpu",
        dtype=torch.float32,
    )
    cardinalities = cardinality_logits.detach().to(
        device="cpu",
        dtype=torch.float32,
    )
    relations = road_relations.detach().to(
        device="cpu",
        dtype=torch.float32,
    )
    allowed = allowed_mask.detach().to(
        device="cpu",
        dtype=torch.bool,
    )
    ranked_allowed = sorted(
        allowed.nonzero(as_tuple=False).flatten().tolist(),
        key=lambda index: (-float(members[index].item()), index),
    )
    allowed_count = len(ranked_allowed)
    maximum_cardinality = min(
        allowed_count,
        int(cardinalities.shape[0]) - 1,
    )
    if maximum_cardinality < 1:
        return []
    valid_cardinality_logits = cardinalities[
        1 : maximum_cardinality + 1
    ]
    valid_probabilities = torch.softmax(
        valid_cardinality_logits,
        dim=0,
    )
    expected_cardinality = float(
        (
            valid_probabilities
            * torch.arange(
                1,
                maximum_cardinality + 1,
                dtype=torch.float32,
            )
        ).sum().item()
    )
    top_count = min(cardinality_width, maximum_cardinality)
    top_cardinalities = (
        torch.topk(valid_cardinality_logits, top_count)
        .indices.add(1)
        .tolist()
    )
    rounded_expected = int(round(expected_cardinality))
    positive_cardinality = sum(
        float(members[index].item()) >= 0.0
        for index in ranked_allowed
    )
    detailed_cardinalities = {
        int(value)
        for value in top_cardinalities
        if 1 <= int(value) <= maximum_cardinality
    }
    detailed_cardinalities.update(
        value
        for value in (
            rounded_expected - 1,
            rounded_expected,
            rounded_expected + 1,
        )
        if 1 <= value <= maximum_cardinality
    )
    detailed_cardinalities.update(
        value
        for value in range(
            positive_cardinality - 2,
            positive_cardinality + 3,
        )
        if 1 <= value <= maximum_cardinality
    )
    detailed_cardinalities.update(
        min(value, maximum_cardinality)
        for value in (1, 2, 4, 8, 12, 16, 24, 32)
        if value <= allowed_count
    )
    detailed_cardinalities.add(maximum_cardinality)
    enumeration_width = max(1, proposal_width // 2)
    candidate_cardinalities = set(
        range(
            1,
            min(maximum_cardinality, enumeration_width) + 1,
        )
    )
    candidate_cardinalities.update(detailed_cardinalities)
    cardinality_log_probabilities = torch.log_softmax(
        cardinalities,
        dim=0,
    )
    endpoint_relations = torch.maximum(
        relations[:, :, 0],
        relations[:, :, 0].transpose(0, 1),
    ).gt(0.0)
    endpoint_neighbors = {
        index: set(
            endpoint_relations[index]
            .nonzero(as_tuple=False)
            .flatten()
            .tolist()
        )
        for index in ranked_allowed
    }
    connected_orders = [
        _connected_ranked_order(
            ranked_allowed,
            endpoint_neighbors,
            seed=seed,
        )
        for seed in ranked_allowed[:seed_width]
    ]
    unselected_log_probabilities = torch.nn.functional.logsigmoid(
        -members
    )
    selected_log_probability_gains = (
        torch.nn.functional.logsigmoid(members)
        - unselected_log_probabilities
    )
    member_log_probability_baseline = float(
        unselected_log_probabilities[ranked_allowed].sum().item()
    )
    by_cardinality: dict[int, list[dict[str, Any]]] = {}
    for cardinality in sorted(candidate_cardinalities):
        selected_base = tuple(
            sorted(ranked_allowed[:cardinality])
        )
        candidates = {selected_base}
        if cardinality in detailed_cardinalities:
            selected_boundary = ranked_allowed[
                max(0, cardinality - boundary_width) : cardinality
            ]
            excluded_boundary = ranked_allowed[
                cardinality : cardinality + boundary_width
            ]
            for removed in selected_boundary:
                for added in excluded_boundary:
                    candidates.add(
                        tuple(
                            sorted(
                                (
                                    set(selected_base) - {removed}
                                )
                                | {added}
                            )
                        )
                    )
            for removed in combinations(selected_boundary[-3:], 2):
                for added in combinations(excluded_boundary[:4], 2):
                    candidates.add(
                        tuple(
                            sorted(
                                (
                                    set(selected_base) - set(removed)
                                )
                                | set(added)
                            )
                        )
                    )
            for connected_order in connected_orders:
                candidates.add(
                    tuple(
                        sorted(
                            connected_order[:cardinality]
                        )
                    )
                )
        candidate_rows = sorted(candidates)
        candidate_masks = torch.zeros(
            len(candidate_rows),
            road_count,
            dtype=torch.float32,
        )
        for index, selected in enumerate(candidate_rows):
            candidate_masks[index, list(selected)] = 1.0
        member_scores = (
            member_log_probability_baseline
            + candidate_masks[:, ranked_allowed].matmul(
                selected_log_probability_gains[ranked_allowed]
            )
        ) / max(allowed_count, 1)
        connected_pair_counts = (
            (
                candidate_masks.matmul(
                    endpoint_relations.to(dtype=torch.float32)
                )
                * candidate_masks
            ).sum(dim=1)
            * 0.5
        )
        connectivity_scores = connected_pair_counts / max(
            cardinality - 1,
            1,
        )
        proposal_scores = (
            member_scores
            + 0.25
            * float(
                cardinality_log_probabilities[
                    cardinality
                ].item()
            )
            + 0.10 * connectivity_scores
        )
        scored = [
            {
                "selected_indices": list(selected),
                "log_probability": float(score),
            }
            for selected, score in zip(
                candidate_rows,
                proposal_scores.tolist(),
                strict=True,
            )
        ]
        scored.sort(
            key=lambda value: (
                -float(value["log_probability"]),
                tuple(value["selected_indices"]),
            )
        )
        by_cardinality[cardinality] = scored
    coverage = sorted(
        (
            values[0]
            for values in by_cardinality.values()
            if values
        ),
        key=lambda value: (
            -float(
                cardinality_log_probabilities[
                    len(value["selected_indices"])
                ].item()
            ),
            len(value["selected_indices"]),
        ),
    )
    detailed_variants = sorted(
        (
            value
            for cardinality in detailed_cardinalities
            for value in by_cardinality.get(cardinality, [])[1:]
        ),
        key=lambda value: (
            -float(value["log_probability"]),
            tuple(value["selected_indices"]),
        ),
    )
    selected_proposals: list[dict[str, Any]] = []
    seen: set[tuple[int, ...]] = set()
    for value in (*coverage, *detailed_variants):
        key = tuple(value["selected_indices"])
        if key in seen:
            continue
        seen.add(key)
        selected_proposals.append(value)
        if len(selected_proposals) == proposal_width:
            break
    selected_proposals.sort(
        key=lambda value: (
            -float(value["log_probability"]),
            tuple(value["selected_indices"]),
        )
    )
    return selected_proposals


def slice_ordinary_encoded_outputs(
    outputs: Mapping[str, torch.Tensor],
    index: int,
) -> dict[str, torch.Tensor]:
    return {
        key: outputs[key][index : index + 1]
        for key in (
            "_ordinary_road_encoded",
            "_ordinary_expansion_context",
        )
    }


def _deduplicate_beam_states(
    states: list[tuple[tuple[int, ...], float, bool]],
    *,
    beam_width: int,
) -> list[tuple[tuple[int, ...], float, bool]]:
    best: dict[tuple[tuple[int, ...], bool], float] = {}
    for selected, score, stopped in states:
        key = (selected, stopped)
        best[key] = max(score, best.get(key, -math.inf))
    return sorted(
        (
            (selected, score, stopped)
            for (selected, stopped), score in best.items()
        ),
        key=lambda value: (-value[1], value[2], value[0]),
    )[:beam_width]


def _deduplicate_active_states(
    states: list[tuple[tuple[int, ...], float]],
    *,
    beam_width: int,
) -> list[tuple[tuple[int, ...], float]]:
    best: dict[tuple[int, ...], float] = {}
    for selected, score in states:
        best[selected] = max(score, best.get(selected, -math.inf))
    return sorted(
        best.items(),
        key=lambda value: (-value[1], value[0]),
    )[:beam_width]


def _rank_diverse_completed_sets(
    states: list[tuple[tuple[int, ...], float]],
    *,
    proposal_width: int,
    cardinality_logits: torch.Tensor | None,
    length_normalization_alpha: float,
    cardinality_score_weight: float,
) -> list[dict[str, Any]]:
    best: dict[tuple[int, ...], float] = {}
    for selected, score in states:
        best[selected] = max(score, best.get(selected, -math.inf))
    cardinality_log_probabilities = (
        torch.log_softmax(cardinality_logits.detach(), dim=-1).cpu()
        if cardinality_logits is not None
        else None
    )
    scored = []
    for selected, raw_score in best.items():
        cardinality = len(selected)
        cardinality_score = (
            float(
                cardinality_log_probabilities[
                    min(
                        cardinality,
                        len(cardinality_log_probabilities) - 1,
                    )
                ].item()
            )
            if cardinality_log_probabilities is not None
            else 0.0
        )
        normalized = raw_score / (
            (cardinality + 1) ** length_normalization_alpha
        )
        scored.append(
            {
                "selected_indices": list(selected),
                "log_probability": float(raw_score),
                "proposal_score": float(
                    normalized
                    + cardinality_score_weight * cardinality_score
                ),
                "cardinality_score": cardinality_score,
            }
        )
    scored.sort(
        key=lambda value: (
            -float(value["proposal_score"]),
            tuple(value["selected_indices"]),
        )
    )
    best_by_cardinality: dict[int, dict[str, Any]] = {}
    for value in scored:
        cardinality = len(value["selected_indices"])
        best_by_cardinality.setdefault(cardinality, value)
    diverse = sorted(
        best_by_cardinality.values(),
        key=lambda value: (
            -float(value["cardinality_score"]),
            -float(value["proposal_score"]),
            tuple(value["selected_indices"]),
        ),
    )
    result = []
    seen: set[tuple[int, ...]] = set()
    for value in [*(scored[:1]), *diverse, *scored]:
        key = tuple(value["selected_indices"])
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) == proposal_width:
            break
    return result


def _connected_ranked_order(
    ranked_allowed: list[int],
    endpoint_neighbors: Mapping[int, set[int]],
    *,
    seed: int,
) -> list[int]:
    selected = [seed]
    selected_set = {seed}
    connected = set(endpoint_neighbors.get(seed, set()))
    while len(selected) < len(ranked_allowed):
        next_index = next(
            (
                candidate
                for candidate in ranked_allowed
                if candidate not in selected_set
                and candidate in connected
            ),
            None,
        )
        if next_index is None:
            next_index = next(
                candidate
                for candidate in ranked_allowed
                if candidate not in selected_set
            )
        selected.append(next_index)
        selected_set.add(next_index)
        connected.update(
            endpoint_neighbors.get(next_index, set())
        )
    return selected
__all__ = [
    "beam_decode_ordinary_side",
    "diverse_beam_decode_ordinary_side",
    "ranked_subset_proposals",
    "slice_ordinary_encoded_outputs",
]
