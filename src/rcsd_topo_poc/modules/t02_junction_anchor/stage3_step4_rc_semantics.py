from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step4RCSemanticsResult,
)


def _frozen_ids(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        str(value)
        for value in values
        if value is not None and str(value).strip()
    )


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value)
                for value in values
                if value is not None and str(value).strip()
            }
        )
    )


@dataclass(frozen=True)
class Stage3Step4SemanticsInputs:
    required_rc_node_ids: Iterable[str]
    required_rc_road_ids: Iterable[str]
    support_rc_node_ids: Iterable[str]
    support_rc_road_ids: Iterable[str]
    excluded_rc_node_ids: Iterable[str]
    excluded_rc_road_ids: Iterable[str]
    selected_rc_endpoint_node_ids: Iterable[str]
    hard_selected_endpoint_node_ids: Iterable[str]
    business_match_reason: str | None
    single_sided_t_mouth_corridor_semantic_gap: bool
    uncovered_selected_endpoint_node_ids: Iterable[str]
    review_excluded_rc_node_ids: Iterable[str] = ()
    review_excluded_rc_road_ids: Iterable[str] = ()
    selected_node_cover_repair_discarded_due_to_extra_roads: bool = False
    multi_node_selected_cover_repair_applied: bool = False
    additional_stage3_rc_gap_records: Sequence[str] = ()


def build_stage3_step4_rc_semantics_result(
    inputs: Stage3Step4SemanticsInputs,
) -> Stage3Step4RCSemanticsResult:
    required_rc_node_ids = _frozen_ids(inputs.required_rc_node_ids)
    required_rc_road_ids = _frozen_ids(inputs.required_rc_road_ids)
    support_rc_node_ids = _frozen_ids(inputs.support_rc_node_ids)
    support_rc_road_ids = _frozen_ids(inputs.support_rc_road_ids)
    excluded_rc_node_ids = _frozen_ids(inputs.excluded_rc_node_ids)
    excluded_rc_road_ids = _frozen_ids(inputs.excluded_rc_road_ids)
    review_excluded_rc_node_ids = _frozen_ids(inputs.review_excluded_rc_node_ids)
    review_excluded_rc_road_ids = _frozen_ids(inputs.review_excluded_rc_road_ids)
    selected_rc_endpoint_node_ids = _frozen_ids(inputs.selected_rc_endpoint_node_ids)
    hard_selected_endpoint_node_ids = _frozen_ids(inputs.hard_selected_endpoint_node_ids)
    uncovered_selected_endpoint_node_ids = _frozen_ids(
        inputs.uncovered_selected_endpoint_node_ids
    )

    stage3_rc_gap_records = list(inputs.additional_stage3_rc_gap_records)
    if inputs.single_sided_t_mouth_corridor_semantic_gap:
        stage3_rc_gap_records.append("single_sided_t_mouth_corridor_semantic_gap")
    if uncovered_selected_endpoint_node_ids:
        stage3_rc_gap_records.append(
            "uncovered_selected_endpoint_node_ids="
            + ",".join(sorted(uncovered_selected_endpoint_node_ids))
        )
    if inputs.selected_node_cover_repair_discarded_due_to_extra_roads:
        stage3_rc_gap_records.append(
            "selected_node_cover_repair_discarded_due_to_extra_roads"
        )
    if inputs.multi_node_selected_cover_repair_applied:
        stage3_rc_gap_records.append("multi_node_selected_cover_repair_applied")
    if review_excluded_rc_road_ids:
        stage3_rc_gap_records.append(
            "review_excluded_rc_road_ids=" + ",".join(sorted(review_excluded_rc_road_ids))
        )
        stage3_rc_gap_records.append("review_rc_outside_drivezone_excluded")
    if review_excluded_rc_node_ids:
        stage3_rc_gap_records.append(
            "review_excluded_rc_node_ids=" + ",".join(sorted(review_excluded_rc_node_ids))
        )
        stage3_rc_gap_records.append("review_rc_outside_drivezone_excluded")

    audit_facts = _sorted_unique(
        [
            (
                f"business_match_reason={inputs.business_match_reason}"
                if inputs.business_match_reason
                else None
            ),
            (
                f"required_rc_node_count={len(required_rc_node_ids)}"
                if required_rc_node_ids
                else None
            ),
            (
                f"required_rc_road_count={len(required_rc_road_ids)}"
                if required_rc_road_ids
                else None
            ),
            (
                f"support_rc_node_count={len(support_rc_node_ids)}"
                if support_rc_node_ids
                else None
            ),
            (
                f"support_rc_road_count={len(support_rc_road_ids)}"
                if support_rc_road_ids
                else None
            ),
            (
                f"excluded_rc_node_count={len(excluded_rc_node_ids)}"
                if excluded_rc_node_ids
                else None
            ),
            (
                f"excluded_rc_road_count={len(excluded_rc_road_ids)}"
                if excluded_rc_road_ids
                else None
            ),
            (
                f"review_excluded_rc_node_count={len(review_excluded_rc_node_ids)}"
                if review_excluded_rc_node_ids
                else None
            ),
            (
                f"review_excluded_rc_road_count={len(review_excluded_rc_road_ids)}"
                if review_excluded_rc_road_ids
                else None
            ),
            (
                f"selected_rc_endpoint_node_count={len(selected_rc_endpoint_node_ids)}"
                if selected_rc_endpoint_node_ids
                else None
            ),
            (
                f"hard_selected_endpoint_node_count={len(hard_selected_endpoint_node_ids)}"
                if hard_selected_endpoint_node_ids
                else None
            ),
            (
                f"uncovered_selected_endpoint_node_count={len(uncovered_selected_endpoint_node_ids)}"
                if uncovered_selected_endpoint_node_ids
                else None
            ),
            *stage3_rc_gap_records,
        ]
    )

    return Stage3Step4RCSemanticsResult(
        required_rc_node_ids=required_rc_node_ids,
        required_rc_road_ids=required_rc_road_ids,
        support_rc_node_ids=support_rc_node_ids,
        support_rc_road_ids=support_rc_road_ids,
        excluded_rc_node_ids=excluded_rc_node_ids,
        excluded_rc_road_ids=excluded_rc_road_ids,
        review_excluded_rc_node_ids=review_excluded_rc_node_ids,
        review_excluded_rc_road_ids=review_excluded_rc_road_ids,
        selected_rc_endpoint_node_ids=selected_rc_endpoint_node_ids,
        hard_selected_endpoint_node_ids=hard_selected_endpoint_node_ids,
        uncovered_selected_endpoint_node_ids=uncovered_selected_endpoint_node_ids,
        selected_node_cover_repair_discarded_due_to_extra_roads=(
            inputs.selected_node_cover_repair_discarded_due_to_extra_roads
        ),
        multi_node_selected_cover_repair_applied=(
            inputs.multi_node_selected_cover_repair_applied
        ),
        stage3_rc_gap_records=_sorted_unique(stage3_rc_gap_records),
        audit_facts=audit_facts,
    )
