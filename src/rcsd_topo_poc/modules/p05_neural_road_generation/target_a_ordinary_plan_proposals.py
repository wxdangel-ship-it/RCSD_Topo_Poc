from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    DECISIONS,
    OrdinaryRoadSetExample,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


STATIC_PLAN_FEATURE_DIM = 64
PLAN_PROPOSAL_SUMMARY_FEATURE_DIM = 25
PLAN_PROPOSAL_FEATURE_DIM = (
    PLAN_PROPOSAL_SUMMARY_FEATURE_DIM + STATIC_PLAN_FEATURE_DIM * 2
)


@dataclass(frozen=True)
class StaticOrdinaryPlan:
    plan_id: str
    decision: str
    road_ids: tuple[str, ...]
    features: tuple[float, ...]


@dataclass(frozen=True)
class OrdinaryPlanProposalExample:
    case_key: str
    segment_id: str
    fold: int
    proposal_ids: tuple[str, ...]
    proposal_decisions: tuple[str, ...]
    proposal_road_ids: tuple[tuple[str, ...], ...]
    proposal_features: tuple[tuple[float, ...], ...]
    acceptable_indices: tuple[int, ...]
    target_decision: str
    target_road_ids: tuple[str, ...]
    sample_weight: float
    release_eligible: bool
    target_reachable: bool

    def __post_init__(self) -> None:
        count = len(self.proposal_ids)
        if (
            count < 1
            or len(self.proposal_decisions) != count
            or len(self.proposal_road_ids) != count
            or len(self.proposal_features) != count
        ):
            raise ValueError("ordinary plan proposal alignment differs")
        if any(
            len(values) != PLAN_PROPOSAL_FEATURE_DIM
            for values in self.proposal_features
        ):
            raise ValueError("ordinary plan proposal feature dimension differs")
        if (
            not self.acceptable_indices
            or min(self.acceptable_indices) < 0
            or max(self.acceptable_indices) >= count
        ):
            raise ValueError("ordinary plan proposal label is invalid")


def read_static_ordinary_plans(
    root: Path,
    *,
    required_keys: set[tuple[str, str]] | None = None,
) -> dict[tuple[str, str], tuple[StaticOrdinaryPlan, ...]]:
    store = normalize_runtime_path(root).resolve(strict=True)
    path = store / "inference_plan_groups.jsonl"
    result: dict[tuple[str, str], tuple[StaticOrdinaryPlan, ...]] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (str(row["case_key"]), str(row["segment_id"]))
            if required_keys is not None and key not in required_keys:
                continue
            plans = []
            for value in row.get("candidates") or ():
                decision = str(value.get("decision") or "")
                if decision not in DECISIONS or not bool(
                    value.get("hard_valid")
                ):
                    continue
                features = tuple(
                    float(item) for item in value.get("features") or ()
                )
                if len(features) != STATIC_PLAN_FEATURE_DIM:
                    raise ValueError(
                        "ordinary static plan feature dimension differs"
                    )
                plans.append(
                    StaticOrdinaryPlan(
                        plan_id=str(value["plan_id"]),
                        decision=decision,
                        road_ids=tuple(
                            sorted(
                                str(item)
                                for item in value.get("road_ids") or ()
                            )
                        ),
                        features=features,
                    )
                )
            result[key] = tuple(plans)
    if required_keys is not None and set(result) != required_keys:
        missing = sorted(required_keys - set(result))
        raise ValueError(
            "ordinary static plan groups are missing: "
            + ", ".join(f"{case}/{segment}" for case, segment in missing[:5])
        )
    return result


def build_ordinary_plan_proposal_example(
    *,
    row: OrdinaryRoadSetExample,
    base_prediction: Mapping[str, Any],
    static_plans: Sequence[StaticOrdinaryPlan],
    maximum_prefix_cardinality: int,
) -> OrdinaryPlanProposalExample:
    if maximum_prefix_cardinality < 1:
        raise ValueError("ordinary plan prefix capacity is invalid")
    road_ids = tuple(str(value) for value in base_prediction["candidate_road_ids"])
    sources = tuple(
        str(value) for value in base_prediction["candidate_sources"]
    )
    probabilities = tuple(
        float(value)
        for value in base_prediction["candidate_member_probabilities"]
    )
    if (
        road_ids != row.road_ids
        or sources != row.sources
        or len(probabilities) != len(road_ids)
    ):
        raise ValueError("ordinary base prediction candidate order differs")
    predicted_decision = str(base_prediction["predicted_decision"])
    if predicted_decision not in DECISIONS:
        raise ValueError("ordinary base prediction decision differs")
    predicted_cardinality = int(base_prediction["predicted_cardinality"])
    decision_confidence = float(base_prediction["decision_confidence"])
    proposal_map: dict[
        tuple[str, tuple[str, ...]],
        dict[str, Any],
    ] = {}
    for plan in static_plans:
        key = (plan.decision, tuple(sorted(plan.road_ids)))
        value = proposal_map.setdefault(
            key,
            {
                "static_features": [],
                "static_plan_ids": [],
                "prefix": False,
            },
        )
        value["static_features"].append(plan.features)
        value["static_plan_ids"].append(plan.plan_id)
    for decision, source in (("KEEP_SWSD", "SWSD"), ("USE_RCSD", "RCSD")):
        ranked = sorted(
            (
                index
                for index, candidate_source in enumerate(sources)
                if candidate_source == source
            ),
            key=lambda index: (-probabilities[index], road_ids[index]),
        )
        for cardinality in range(
            1,
            min(len(ranked), maximum_prefix_cardinality) + 1,
        ):
            selected = tuple(
                sorted(road_ids[index] for index in ranked[:cardinality])
            )
            value = proposal_map.setdefault(
                (decision, selected),
                {
                    "static_features": [],
                    "static_plan_ids": [],
                    "prefix": False,
                },
            )
            value["prefix"] = True
    proposals = [
        (
            "ABSTAIN",
            tuple(),
            {
                "static_features": [],
                "static_plan_ids": [],
                "prefix": False,
            },
        )
    ]
    proposals.extend(
        (decision, selected, evidence)
        for (decision, selected), evidence in sorted(
            proposal_map.items(),
            key=lambda item: (
                DECISIONS.index(item[0][0]),
                len(item[0][1]),
                item[0][1],
            ),
        )
    )
    index_by_road = {
        road_id: index for index, road_id in enumerate(road_ids)
    }
    proposal_ids = []
    proposal_decisions = []
    proposal_road_ids = []
    proposal_features = []
    for decision, selected, evidence in proposals:
        proposal_ids.append(
            _proposal_id(decision=decision, road_ids=selected)
        )
        proposal_decisions.append(decision)
        proposal_road_ids.append(selected)
        proposal_features.append(
            _proposal_features(
                decision=decision,
                selected=selected,
                static_features=evidence["static_features"],
                is_prefix=bool(evidence["prefix"]),
                road_ids=road_ids,
                sources=sources,
                probabilities=probabilities,
                index_by_road=index_by_road,
                predicted_decision=predicted_decision,
                predicted_cardinality=predicted_cardinality,
                decision_confidence=decision_confidence,
            )
        )
    target_decision = DECISIONS[row.decision]
    target_road_ids = tuple(sorted(row.road_ids[index] for index in row.target_indices))
    acceptable = tuple(
        index
        for index, (decision, selected) in enumerate(
            zip(proposal_decisions, proposal_road_ids, strict=True)
        )
        if decision == target_decision and selected == target_road_ids
    )
    reachable = bool(acceptable)
    if not acceptable:
        acceptable = (0,)
    return OrdinaryPlanProposalExample(
        case_key=row.case_key,
        segment_id=row.segment_id,
        fold=row.fold,
        proposal_ids=tuple(proposal_ids),
        proposal_decisions=tuple(proposal_decisions),
        proposal_road_ids=tuple(proposal_road_ids),
        proposal_features=tuple(proposal_features),
        acceptable_indices=acceptable,
        target_decision=target_decision,
        target_road_ids=target_road_ids,
        sample_weight=float(row.sample_weight),
        release_eligible=bool(row.oof_anchor_release_ready),
        target_reachable=reachable,
    )


def _proposal_features(
    *,
    decision: str,
    selected: tuple[str, ...],
    static_features: Sequence[Sequence[float]],
    is_prefix: bool,
    road_ids: Sequence[str],
    sources: Sequence[str],
    probabilities: Sequence[float],
    index_by_road: Mapping[str, int],
    predicted_decision: str,
    predicted_cardinality: int,
    decision_confidence: float,
) -> tuple[float, ...]:
    is_abstain = decision == "ABSTAIN"
    has_static = bool(static_features)
    generator_values = (
        float(is_abstain),
        float(has_static and not is_prefix),
        float(is_prefix and not has_static),
        float(has_static and is_prefix),
    )
    decision_values = (
        float(decision == "KEEP_SWSD"),
        float(decision == "USE_RCSD"),
        float(is_abstain),
    )
    selected_indices = [
        index_by_road[road_id]
        for road_id in selected
        if road_id in index_by_road
    ]
    missing_count = len(selected) - len(selected_indices)
    source = (
        "SWSD"
        if decision == "KEEP_SWSD"
        else "RCSD"
        if decision == "USE_RCSD"
        else ""
    )
    source_indices = [
        index for index, value in enumerate(sources) if value == source
    ]
    selected_probabilities = [
        probabilities[index] for index in selected_indices
    ]
    selected_set = set(selected_indices)
    excluded_probabilities = [
        probabilities[index]
        for index in source_indices
        if index not in selected_set
    ]
    member_mean = _mean(selected_probabilities)
    member_min = min(selected_probabilities, default=0.0)
    member_max = max(selected_probabilities, default=0.0)
    excluded_max = max(excluded_probabilities, default=0.0)
    member_log_mean = _mean(
        math.log(max(min(value, 1.0 - 1e-7), 1e-7))
        for value in selected_probabilities
    )
    excluded_log_mean = _mean(
        math.log(max(1.0 - min(max(value, 0.0), 1.0 - 1e-7), 1e-7))
        for value in excluded_probabilities
    )
    plan_decision_probability = (
        decision_confidence
        if decision == predicted_decision
        else 1.0 - decision_confidence
        if decision in DECISIONS
        else 0.0
    )
    static_mean = _column_reduce(static_features, maximum=False)
    static_maximum = _column_reduce(static_features, maximum=True)
    summary = (
        *generator_values,
        *decision_values,
        plan_decision_probability,
        float(decision == predicted_decision),
        math.tanh(len(selected) / 8.0),
        math.tanh(len(source_indices) / 32.0),
        math.tanh((len(selected) - predicted_cardinality) / 8.0),
        math.tanh(abs(len(selected) - predicted_cardinality) / 8.0),
        float(len(selected) == predicted_cardinality and not is_abstain),
        member_mean,
        member_min,
        member_max,
        excluded_max,
        member_min - excluded_max,
        math.tanh((sum(selected_probabilities) - len(selected)) / 8.0),
        member_log_mean,
        excluded_log_mean,
        math.tanh(len(static_features) / 4.0),
        math.tanh(missing_count / 4.0),
        float(has_static),
    )
    if len(summary) != PLAN_PROPOSAL_SUMMARY_FEATURE_DIM:
        raise AssertionError("ordinary plan proposal summary dimension differs")
    values = (*summary, *static_mean, *static_maximum)
    if len(values) != PLAN_PROPOSAL_FEATURE_DIM:
        raise AssertionError("ordinary plan proposal feature dimension differs")
    return tuple(float(value) for value in values)


def _column_reduce(
    rows: Sequence[Sequence[float]],
    *,
    maximum: bool,
) -> tuple[float, ...]:
    if not rows:
        return (0.0,) * STATIC_PLAN_FEATURE_DIM
    if any(len(row) != STATIC_PLAN_FEATURE_DIM for row in rows):
        raise ValueError("ordinary static plan evidence dimension differs")
    reducer = max if maximum else _mean
    return tuple(
        float(reducer(row[index] for row in rows))
        for index in range(STATIC_PLAN_FEATURE_DIM)
    )


def _mean(values: Iterable[float]) -> float:
    materialized = [float(value) for value in values]
    return (
        sum(materialized) / len(materialized)
        if materialized
        else 0.0
    )


def _proposal_id(*, decision: str, road_ids: Sequence[str]) -> str:
    if decision == "ABSTAIN":
        return "proposal:abstain"
    payload = decision + "\0" + "\0".join(road_ids)
    return "proposal:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "OrdinaryPlanProposalExample",
    "PLAN_PROPOSAL_FEATURE_DIM",
    "PLAN_PROPOSAL_SUMMARY_FEATURE_DIM",
    "STATIC_PLAN_FEATURE_DIM",
    "StaticOrdinaryPlan",
    "build_ordinary_plan_proposal_example",
    "read_static_ordinary_plans",
]
