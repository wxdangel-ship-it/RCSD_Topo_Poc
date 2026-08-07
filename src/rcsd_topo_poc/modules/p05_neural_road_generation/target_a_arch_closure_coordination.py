from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_data import (
    ArchClosureReferenceStores,
)


COORDINATION_ACCEPT = "ACCEPT"
COORDINATION_FALLBACK = "FALLBACK"


@dataclass(frozen=True)
class ArchClosureSegmentPlan:
    key: tuple[str, str]
    plan_id: str
    decision: str
    road_ids: tuple[str, ...]
    owned_road_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("Segment plan lacks plan identity")
        if self.decision not in {"KEEP_SWSD", "USE_RCSD", "ABSTAIN"}:
            raise ValueError("Segment plan source decision is unsupported")
        if self.decision != "ABSTAIN" and not self.road_ids:
            raise ValueError("positive Segment plan lacks an independent Road")
        if len(set(self.road_ids)) != len(self.road_ids):
            raise ValueError("Segment plan repeats a Road")
        if len(set(self.owned_road_ids)) != len(self.owned_road_ids):
            raise ValueError("Segment plan repeats an owned Road")
        if not set(self.owned_road_ids).issubset(self.road_ids):
            raise ValueError("Segment plan owns a Road outside its complete list")


@dataclass(frozen=True)
class ArchClosureCoordinationResult:
    status_by_segment: Mapping[tuple[str, str], str]
    duplicate_owner_roads: Mapping[
        tuple[str, str], tuple[tuple[str, str], ...]
    ]
    fallback_segment_keys: tuple[tuple[str, str], ...]
    maximum_fallback_expansion_hops: int

    def __post_init__(self) -> None:
        if self.maximum_fallback_expansion_hops > 1:
            raise ValueError("Junction fallback expanded recursively")


def coordinate_arch_closure_plans(
    stores: ArchClosureReferenceStores,
    plans: Sequence[ArchClosureSegmentPlan],
) -> ArchClosureCoordinationResult:
    """Reject ownership conflicts within frozen direct Junction scope only."""

    by_key: dict[tuple[str, str], ArchClosureSegmentPlan] = {}
    road_owners: dict[
        tuple[str, str], list[tuple[str, str]]
    ] = defaultdict(list)
    fallback: set[tuple[str, str]] = set()
    for plan in plans:
        if plan.key not in stores.segments:
            raise ValueError(f"Segment plan is outside frozen skeleton: {plan.key}")
        if plan.key in by_key:
            raise ValueError(f"Segment has multiple complete outputs: {plan.key}")
        by_key[plan.key] = plan
        if plan.decision == "ABSTAIN":
            fallback.add(plan.key)
            continue
        for road_id in plan.owned_road_ids:
            road_owners[(plan.key[0], road_id)].append(plan.key)

    duplicate = {
        road_key: tuple(sorted(owners))
        for road_key, owners in road_owners.items()
        if len(owners) > 1
    }
    for owners in duplicate.values():
        shared_junctions = set(
            stores.segments[owners[0]].required_junction_keys
        )
        for owner in owners[1:]:
            shared_junctions.intersection_update(
                stores.segments[owner].required_junction_keys
            )
        if shared_junctions:
            for junction_key in shared_junctions:
                fallback.update(
                    stores.junctions[junction_key].direct_segment_keys
                )
        else:
            fallback.update(owners)

    status = {
        key: (
            COORDINATION_FALLBACK
            if key in fallback
            else COORDINATION_ACCEPT
        )
        for key in by_key
    }
    accepted_owners: dict[tuple[str, str], tuple[str, str]] = {}
    for key, plan in by_key.items():
        if status[key] != COORDINATION_ACCEPT:
            continue
        for road_id in plan.owned_road_ids:
            road_key = (key[0], road_id)
            if road_key in accepted_owners:
                raise ValueError("accepted coordination retains duplicate Road owner")
            accepted_owners[road_key] = key
    return ArchClosureCoordinationResult(
        status_by_segment=status,
        duplicate_owner_roads=duplicate,
        fallback_segment_keys=tuple(sorted(fallback)),
        maximum_fallback_expansion_hops=1 if duplicate else 0,
    )


__all__ = [
    "ArchClosureCoordinationResult",
    "ArchClosureSegmentPlan",
    "COORDINATION_ACCEPT",
    "COORDINATION_FALLBACK",
    "coordinate_arch_closure_plans",
]
