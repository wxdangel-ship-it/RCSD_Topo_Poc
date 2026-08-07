from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_decoder import (
    DecodeResult,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_materializer import (
    AttachmentEndpoint,
    SegmentMaterializationInstruction,
    SegmentMaterializationType,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    PlanCandidate,
    RoadSource,
    SegmentDecision,
    SegmentPlanDecision,
)


@dataclass(frozen=True)
class PreparedAutomaticInstruction:
    """Deterministic execution recipe bound to one selected model plan."""

    plan_id: str
    instruction: SegmentMaterializationInstruction


@dataclass(frozen=True)
class FullChainMaterializationLedger:
    """Complete executable ledger for one dependency-complete frozen subgraph."""

    segment_instructions: tuple[SegmentMaterializationInstruction, ...]
    automatic_segment_ids: tuple[str, ...]
    positive_keep_segment_ids: tuple[str, ...]
    fallback_segment_ids: tuple[str, ...]
    preflight_rejected_segment_ids: tuple[str, ...] = ()
    preflight_fallback_reasons: tuple[tuple[str, str], ...] = ()
    skeleton_mutation_count: int = 0
    silent_fix: bool = False
    content_repair: bool = False


def assemble_full_chain_materialization_ledger(
    *,
    frozen_segment_ids: Sequence[str],
    decode_result: DecodeResult,
    fallback_instructions: Mapping[str, SegmentMaterializationInstruction],
    automatic_instructions: Mapping[str, PreparedAutomaticInstruction],
    preflight_fallback_reasons: Mapping[str, str] | None = None,
) -> FullChainMaterializationLedger:
    """Bind model decisions to deterministic execution without new business choices.

    Positive KEEP is converted from the already validated T01 fallback recipe.
    USE_RCSD and the explicit T06 mixed decision require a prepared recipe that
    is bound to the exact selected plan id. Any missing or mismatched recipe is
    a hard failure; this function never selects another candidate or invents
    Node, split, splice or attachment decisions.
    """

    frozen = tuple(str(value) for value in frozen_segment_ids)
    if not frozen or len(frozen) != len(set(frozen)):
        raise ValueError("frozen Segment ids must be nonempty and unique")
    frozen_set = set(frozen)
    decisions = _index_decisions(decode_result)
    if set(decisions) != frozen_set:
        raise ValueError(
            "decoded decisions differ from the frozen Segment skeleton: "
            f"missing={sorted(frozen_set - set(decisions))}, "
            f"extra={sorted(set(decisions) - frozen_set)}"
        )
    if set(fallback_instructions) != frozen_set:
        raise ValueError(
            "fallback instructions differ from the frozen Segment skeleton: "
            f"missing={sorted(frozen_set - set(fallback_instructions))}, "
            f"extra={sorted(set(fallback_instructions) - frozen_set)}"
        )
    extra_automatic = set(automatic_instructions) - frozen_set
    if extra_automatic:
        raise ValueError(
            "automatic instructions reference unknown Segments: "
            f"{sorted(extra_automatic)}"
        )
    preflight_reasons = {
        str(segment_id): str(reason)
        for segment_id, reason in (preflight_fallback_reasons or {}).items()
    }
    extra_preflight = set(preflight_reasons) - frozen_set
    if extra_preflight:
        raise ValueError(
            "preflight fallback references unknown Segments: "
            f"{sorted(extra_preflight)}"
        )
    empty_preflight = [
        segment_id
        for segment_id, reason in preflight_reasons.items()
        if not reason
    ]
    if empty_preflight:
        raise ValueError("preflight fallback reasons must not be empty")

    instructions = []
    automatic_ids = []
    positive_keep_ids = []
    fallback_ids = []
    preflight_rejected_ids = []
    consumed_automatic: set[str] = set()
    for segment_id in sorted(frozen_set):
        decision = decisions[segment_id]
        fallback = fallback_instructions[segment_id]
        _validate_fallback_instruction(segment_id, fallback)
        preflight_reason = preflight_reasons.get(segment_id)
        if preflight_reason is not None:
            if not decision.automatic:
                raise ValueError(
                    "preflight fallback must reject an automatic model decision"
                )
            if segment_id in automatic_instructions:
                raise ValueError(
                    "preflight-rejected Segment must not retain an executable recipe"
                )
            instructions.append(fallback)
            fallback_ids.append(segment_id)
            preflight_rejected_ids.append(segment_id)
            continue
        if not decision.automatic:
            instructions.append(fallback)
            fallback_ids.append(segment_id)
            continue

        selected = decision.selected_plan
        if selected.decision is SegmentDecision.KEEP_SWSD:
            prepared = automatic_instructions.get(segment_id)
            if prepared is None:
                if fallback.segment_type is SegmentMaterializationType.ADVANCE_RIGHT:
                    raise ValueError(
                        "automatic AdvanceRight KEEP requires a conditional "
                        "executable recipe"
                    )
                instruction = replace(
                    fallback,
                    decision=SegmentDecision.KEEP_SWSD,
                    fallback_applied=False,
                )
            else:
                consumed_automatic.add(segment_id)
                instruction = _validated_automatic_instruction(
                    decision,
                    prepared,
                    expected_type=fallback.segment_type,
                )
            positive_keep_ids.append(segment_id)
        else:
            prepared = automatic_instructions.get(segment_id)
            if prepared is None:
                raise ValueError(
                    f"automatic Segment lacks an executable recipe: {segment_id}"
                )
            consumed_automatic.add(segment_id)
            instruction = _validated_automatic_instruction(
                decision,
                prepared,
                expected_type=fallback.segment_type,
            )
        instructions.append(instruction)
        automatic_ids.append(segment_id)

    unused_automatic = set(automatic_instructions) - consumed_automatic
    if unused_automatic:
        raise ValueError(
            "automatic recipes exist for non-automatic decisions: "
            f"{sorted(unused_automatic)}"
        )
    return FullChainMaterializationLedger(
        segment_instructions=tuple(instructions),
        automatic_segment_ids=tuple(automatic_ids),
        positive_keep_segment_ids=tuple(positive_keep_ids),
        fallback_segment_ids=tuple(fallback_ids),
        preflight_rejected_segment_ids=tuple(preflight_rejected_ids),
        preflight_fallback_reasons=tuple(
            (segment_id, preflight_reasons[segment_id])
            for segment_id in sorted(preflight_rejected_ids)
        ),
    )


def _index_decisions(
    decode_result: DecodeResult,
) -> dict[str, SegmentPlanDecision]:
    decisions: dict[str, SegmentPlanDecision] = {}
    for decision in (*decode_result.ordinary, *decode_result.advance_right):
        if decision.segment_id in decisions:
            raise ValueError("decoded Segment decisions are duplicated")
        decisions[decision.segment_id] = decision
    return decisions


def _validate_fallback_instruction(
    segment_id: str,
    instruction: SegmentMaterializationInstruction,
) -> None:
    if instruction.segment_id != segment_id:
        raise ValueError("fallback instruction belongs to another Segment")
    if (
        not instruction.fallback_applied
        or instruction.decision is not SegmentDecision.ABSTAIN
    ):
        raise ValueError("fallback instruction is not an executed fallback")
    owned_sources = {
        geometry_slice.source_kind
        for road in instruction.roads
        if road.owner_segment_id == segment_id
        for geometry_slice in road.geometry_slices
    }
    if owned_sources != {RoadSource.SWSD}:
        raise ValueError("fallback instruction is not a complete SWSD plan")
    _validate_instruction_shape(instruction)


def _validated_automatic_instruction(
    decision: SegmentPlanDecision,
    prepared: PreparedAutomaticInstruction,
    *,
    expected_type: SegmentMaterializationType,
) -> SegmentMaterializationInstruction:
    plan = decision.selected_plan
    instruction = prepared.instruction
    if prepared.plan_id != plan.plan_id:
        raise ValueError("automatic recipe is bound to another model plan")
    if instruction.segment_id != decision.segment_id:
        raise ValueError("automatic recipe belongs to another Segment")
    if instruction.segment_type is not expected_type:
        raise ValueError("automatic recipe changes the frozen Segment type")
    if instruction.fallback_applied:
        raise ValueError("automatic recipe is incorrectly marked as fallback")
    if instruction.decision is not plan.decision:
        raise ValueError("automatic recipe changes the selected business decision")
    _validate_instruction_shape(instruction)
    _validate_road_semantics(plan, instruction)
    return instruction


def _validate_instruction_shape(
    instruction: SegmentMaterializationInstruction,
) -> None:
    if not instruction.roads:
        raise ValueError("materialization instruction lacks a complete Road plan")
    if instruction.segment_type is SegmentMaterializationType.STANDARD:
        if not instruction.access_bindings:
            raise ValueError("ordinary instruction lacks frozen access bindings")
        if instruction.attachments:
            raise ValueError("ordinary instruction cannot contain side attachments")
        return
    if instruction.access_bindings:
        raise ValueError("AdvanceRight cannot own ordinary access bindings")
    sides = Counter(row.side for row in instruction.attachments)
    if sides != Counter(
        {
            AttachmentEndpoint.SOURCE: 1,
            AttachmentEndpoint.TARGET: 1,
        }
    ):
        raise ValueError(
            "AdvanceRight instruction must contain one attachment per side"
        )


def _validate_road_semantics(
    plan: PlanCandidate,
    instruction: SegmentMaterializationInstruction,
) -> None:
    planned = Counter(
        (
            road.source_kind,
            road.source_road_id,
            road.role,
            road.owner_segment_id,
        )
        for road in plan.roads
    )
    executable = Counter(
        (
            geometry_slice.source_kind,
            geometry_slice.source_road_id,
            road.role,
            road.owner_segment_id,
        )
        for road in instruction.roads
        for geometry_slice in road.geometry_slices
    )
    if (
        set(planned) != set(executable)
        if instruction.segment_type is SegmentMaterializationType.STANDARD
        else planned != executable
    ):
        raise ValueError(
            "automatic recipe changes the selected Road source/role/ownership set"
        )
    aliases = {
        alias
        for road in instruction.roads
        for alias in (
            road.instruction_id,
            road.output_road_id,
            *(row.source_road_id for row in road.geometry_slices),
        )
        if alias
    }
    if instruction.segment_type is SegmentMaterializationType.STANDARD:
        for access_id in (
            plan.source_access_road_id,
            plan.target_access_road_id,
        ):
            if access_id and access_id not in aliases:
                raise ValueError(
                    "automatic recipe does not contain the selected access Road"
                )


__all__ = [
    "FullChainMaterializationLedger",
    "PreparedAutomaticInstruction",
    "assemble_full_chain_materialization_ledger",
]
