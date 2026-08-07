from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorDecision,
    FallbackScope,
    PlanCandidate,
    RoadRole,
    RoadSource,
    ScoredPlan,
    SegmentDecision,
    SegmentPlanDecision,
)


@dataclass(frozen=True)
class DecodeResult:
    ordinary: tuple[SegmentPlanDecision, ...]
    advance_right: tuple[SegmentPlanDecision, ...]
    used_ownership_keys: tuple[str, ...]
    fallback_segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class FallbackDirective:
    """Model-confirmed bounded fallback without transitive propagation."""

    directive_id: str
    scope: FallbackScope
    affected_segment_ids: tuple[str, ...]
    junction_id: str = ""
    reason: str = ""

    def validate(
        self,
        *,
        known_segment_ids: set[str],
        junction_direct_segments: Mapping[str, Sequence[str]],
    ) -> None:
        if not self.directive_id:
            raise ValueError("fallback directive id must not be empty")
        affected = tuple(dict.fromkeys(self.affected_segment_ids))
        if affected != self.affected_segment_ids or not affected:
            raise ValueError(
                "fallback directive affected Segments must be nonempty and unique"
            )
        unknown = set(affected) - known_segment_ids
        if unknown:
            raise ValueError(
                f"fallback directive references unknown Segments: {sorted(unknown)}"
            )
        if self.scope is FallbackScope.SEGMENT:
            if len(affected) != 1 or self.junction_id:
                raise ValueError(
                    "Segment fallback must contain exactly one Segment and no Junction"
                )
            return
        if self.scope is not FallbackScope.JUNCTION or not self.junction_id:
            raise ValueError(
                "fallback directive must declare Segment or Junction scope"
            )
        direct = set(junction_direct_segments.get(self.junction_id, ()))
        if not direct:
            raise ValueError(
                "Junction fallback lacks frozen T01 direct Segment relations"
            )
        non_direct = set(affected) - direct
        if non_direct:
            raise ValueError(
                "Junction fallback crosses its frozen T01 direct Segment boundary: "
                f"{sorted(non_direct)}"
            )


class StructuredRoadGraphDecoder:
    """Choose complete plans without changing model evidence or the T01 skeleton."""

    def __init__(self, *, max_search_states: int = 50_000) -> None:
        if max_search_states < 1:
            raise ValueError("max_search_states must be positive")
        self.max_search_states = max_search_states

    def decode(
        self,
        *,
        ordinary_candidates: Mapping[str, Sequence[ScoredPlan]],
        advance_right_candidates: Mapping[str, Sequence[ScoredPlan]],
        anchor_decisions: Mapping[str, AnchorDecision],
        fallback_directives: Iterable[FallbackDirective] = (),
        junction_direct_segments: Mapping[str, Sequence[str]] | None = None,
    ) -> DecodeResult:
        known_segment_ids = set(ordinary_candidates) | set(
            advance_right_candidates
        )
        fallback_by_segment = self._bounded_fallbacks(
            fallback_directives,
            known_segment_ids=known_segment_ids,
            junction_direct_segments=junction_direct_segments or {},
        )
        ordinary: dict[str, SegmentPlanDecision] = {}
        selected = self._solve_ordinary(
            ordinary_candidates,
            anchor_decisions,
            fallback_by_segment,
        )
        used: set[str] = set()
        for decision in selected:
            ordinary[decision.segment_id] = decision
            used.update(self._owned_keys(decision.selected_plan))

        advance_right: dict[str, SegmentPlanDecision] = {}
        access_sources = {
            segment_id: self._access_source(decision.selected_plan)
            for segment_id, decision in ordinary.items()
        }
        for segment_id, candidates in sorted(advance_right_candidates.items()):
            allowed: list[ScoredPlan] = []
            condition_error = ""
            for candidate in candidates:
                candidate.plan.validate(advance_right=True)
                condition = candidate.plan.source_condition
                if condition is None:
                    continue
                adjacent = self._adjacent_segments(candidate.plan)
                if adjacent is None:
                    condition_error = "ADVANCE_RIGHT_ADJACENT_ACCESS_MISSING"
                    continue
                source_segment, target_segment = adjacent
                observed = (
                    access_sources.get(source_segment),
                    access_sources.get(target_segment),
                )
                if observed != condition:
                    continue
                if self._owned_keys(candidate.plan) & used:
                    continue
                if self._owns_adjacent_access(candidate.plan, ordinary):
                    continue
                allowed.append(candidate)
            directive = fallback_by_segment.get(segment_id)
            if directive is not None:
                allowed = []
                condition_error = directive.reason or (
                    "JUNCTION_FALLBACK"
                    if directive.scope is FallbackScope.JUNCTION
                    else "SEGMENT_FALLBACK"
                )
            if allowed:
                selected = max(allowed, key=lambda row: (row.score, row.plan.plan_id))
                decision = SegmentPlanDecision(segment_id, selected.plan, selected.score)
                used.update(self._owned_keys(selected.plan))
            else:
                decision = self._fallback_decision(
                    segment_id,
                    candidates,
                    scope=(
                        directive.scope
                        if directive is not None
                        else FallbackScope.SEGMENT
                    ),
                    reason=condition_error or "NO_VALID_CONDITIONAL_PLAN",
                )
            advance_right[segment_id] = decision

        return DecodeResult(
            ordinary=tuple(ordinary[key] for key in sorted(ordinary)),
            advance_right=tuple(advance_right[key] for key in sorted(advance_right)),
            used_ownership_keys=tuple(sorted(used)),
            fallback_segment_ids=tuple(
                sorted(
                    decision.segment_id
                    for decision in (*ordinary.values(), *advance_right.values())
                    if decision.fallback_scope is not FallbackScope.NONE
                )
            ),
        )

    def _solve_ordinary(
        self,
        candidates_by_segment: Mapping[str, Sequence[ScoredPlan]],
        anchor_decisions: Mapping[str, AnchorDecision],
        fallback_by_segment: Mapping[str, FallbackDirective],
    ) -> list[SegmentPlanDecision]:
        ordered = sorted(
            candidates_by_segment,
            key=lambda segment_id: (
                len(candidates_by_segment.get(segment_id, ())),
                segment_id,
            ),
        )
        best_score = float("-inf")
        best: list[ScoredPlan] | None = None
        states = 0

        def search(index: int, used: set[str], score: float, rows: list[ScoredPlan]) -> None:
            nonlocal best, best_score, states
            states += 1
            if states > self.max_search_states:
                return
            if index == len(ordered):
                if score > best_score:
                    best_score = score
                    best = list(rows)
                return
            segment_id = ordered[index]
            if segment_id in fallback_by_segment:
                search(index + 1, used, score, rows)
                return
            # A Segment may abstain without changing any other Segment's
            # fallback scope. Fallback is not a fake Road plan and consumes no
            # ownership.
            search(index + 1, used, score, rows)
            for scored in sorted(
                candidates_by_segment.get(segment_id, ()),
                key=lambda row: (row.score, row.plan.plan_id),
                reverse=True,
            ):
                plan = scored.plan
                plan.validate()
                if not plan.hard_valid:
                    continue
                if any(
                    not anchor_decisions.get(anchor_id, AnchorDecision(
                        anchor_id, status=self._abstain_status()
                    )).locked_success
                    for anchor_id in plan.required_anchor_ids
                ):
                    continue
                owned = self._owned_keys(plan)
                if owned & used:
                    continue
                search(index + 1, used | owned, score + scored.score, [*rows, scored])

        search(0, set(), 0.0, [])
        selected_by_id = {row.plan.segment_id: row for row in best or []}
        decisions: list[SegmentPlanDecision] = []
        for segment_id in sorted(candidates_by_segment):
            selected = selected_by_id.get(segment_id)
            if selected is not None:
                decisions.append(
                    SegmentPlanDecision(segment_id, selected.plan, selected.score)
                )
                continue
            directive = fallback_by_segment.get(segment_id)
            scope = (
                directive.scope
                if directive is not None
                else FallbackScope.SEGMENT
            )
            decisions.append(
                self._fallback_decision(
                    segment_id,
                    candidates_by_segment.get(segment_id, ()),
                    scope=scope,
                    reason=(
                        directive.reason
                        if directive is not None and directive.reason
                        else "JUNCTION_FALLBACK"
                        if directive is not None
                        and directive.scope is FallbackScope.JUNCTION
                        else "SEGMENT_FALLBACK"
                        if directive is not None
                        else "NO_CONFLICT_FREE_COMPLETE_PLAN"
                    ),
                )
            )
        return decisions

    @staticmethod
    def _bounded_fallbacks(
        directives: Iterable[FallbackDirective],
        *,
        known_segment_ids: set[str],
        junction_direct_segments: Mapping[str, Sequence[str]],
    ) -> dict[str, FallbackDirective]:
        result: dict[str, FallbackDirective] = {}
        directive_ids: set[str] = set()
        for directive in directives:
            if directive.directive_id in directive_ids:
                raise ValueError("fallback directive ids must be unique")
            directive_ids.add(directive.directive_id)
            directive.validate(
                known_segment_ids=known_segment_ids,
                junction_direct_segments=junction_direct_segments,
            )
            for segment_id in directive.affected_segment_ids:
                current = result.get(segment_id)
                if current is None:
                    result[segment_id] = directive
                    continue
                if (
                    current.scope is FallbackScope.JUNCTION
                    and directive.scope is FallbackScope.SEGMENT
                ):
                    continue
                if (
                    current.scope is FallbackScope.SEGMENT
                    and directive.scope is FallbackScope.JUNCTION
                ):
                    result[segment_id] = directive
                    continue
                if current != directive:
                    raise ValueError(
                        "a Segment has multiple fallback directives at the same scope"
                    )
        return result

    @staticmethod
    def _fallback_decision(
        segment_id: str,
        candidates: Sequence[ScoredPlan],
        *,
        scope: FallbackScope,
        reason: str,
    ) -> SegmentPlanDecision:
        abstain = next(
            (
                row
                for row in candidates
                if row.plan.decision is SegmentDecision.ABSTAIN
            ),
            None,
        )
        if abstain is None:
            plan = PlanCandidate(
                plan_id=f"abstain:{segment_id}",
                segment_id=segment_id,
                decision=SegmentDecision.ABSTAIN,
                roads=(),
                source_access_road_id="",
                target_access_road_id="",
            )
            score = float("-inf")
        else:
            plan = abstain.plan
            score = abstain.score
        return SegmentPlanDecision(segment_id, plan, score, scope, reason)

    @staticmethod
    def _owned_keys(plan: PlanCandidate) -> set[str]:
        return {
            road.ownership_key
            for road in plan.roads
            if road.owner_segment_id
            and road.role is not RoadRole.JUNCTION_CONNECTIVITY
        }

    @staticmethod
    def _access_source(plan: PlanCandidate) -> RoadSource | None:
        access_ids = {plan.source_access_road_id, plan.target_access_road_id} - {""}
        sources = {
            road.source_kind
            for road in plan.roads
            if road.ownership_key in access_ids or road.source_road_id in access_ids
        }
        return next(iter(sources)) if len(sources) == 1 else None

    @staticmethod
    def _adjacent_segments(plan: PlanCandidate) -> tuple[str, str] | None:
        for recipe in plan.node_recipes:
            source = str(recipe.get("source_segment_id") or "")
            target = str(recipe.get("target_segment_id") or "")
            if source and target:
                return source, target
        return None

    @staticmethod
    def _owns_adjacent_access(
        plan: PlanCandidate,
        ordinary: Mapping[str, SegmentPlanDecision],
    ) -> bool:
        adjacent = StructuredRoadGraphDecoder._adjacent_segments(plan)
        if adjacent is None:
            return True
        ordinary_access = {
            access_id
            for segment_id in adjacent
            if segment_id in ordinary
            for access_id in (
                ordinary[segment_id].selected_plan.source_access_road_id,
                ordinary[segment_id].selected_plan.target_access_road_id,
            )
            if access_id
        }
        return any(
            road.owner_segment_id == plan.segment_id
            and road.ownership_key in ordinary_access
            for road in plan.roads
        )

    @staticmethod
    def _abstain_status():
        from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
            AnchorStatus,
        )

        return AnchorStatus.ABSTAIN


__all__ = [
    "DecodeResult",
    "FallbackDirective",
    "StructuredRoadGraphDecoder",
]
