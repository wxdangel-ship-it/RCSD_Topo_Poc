from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Context,
    build_stage3_context,
)


@dataclass(frozen=True)
class Stage3LegacyContextInputs:
    representative_node_id: str
    normalized_mainnodeid: str
    template_class: str
    representative_kind: Any | None = None
    representative_kind_2: int | None = None
    representative_grade_2: int | None = None
    semantic_junction_set: Iterable[str] = ()
    analysis_member_node_ids: Iterable[str] = ()
    group_node_ids: Iterable[str] = ()
    local_node_ids: Iterable[str] = ()
    local_road_ids: Iterable[str] = ()
    local_rc_node_ids: Iterable[str] = ()
    local_rc_road_ids: Iterable[str] = ()
    road_branch_ids: Iterable[str] = ()
    analysis_center_xy: tuple[float, float] | None = None


def build_stage3_context_from_legacy_inputs(
    inputs: Stage3LegacyContextInputs,
) -> Stage3Context:
    return build_stage3_context(
        representative_node_id=inputs.representative_node_id,
        normalized_mainnodeid=inputs.normalized_mainnodeid,
        template_class=inputs.template_class,
        representative_kind=inputs.representative_kind,
        representative_kind_2=inputs.representative_kind_2,
        representative_grade_2=inputs.representative_grade_2,
        semantic_junction_set=inputs.semantic_junction_set,
        analysis_member_node_ids=inputs.analysis_member_node_ids,
        group_node_ids=inputs.group_node_ids,
        local_node_ids=inputs.local_node_ids,
        local_road_ids=inputs.local_road_ids,
        local_rc_node_ids=inputs.local_rc_node_ids,
        local_rc_road_ids=inputs.local_rc_road_ids,
        road_branch_ids=inputs.road_branch_ids,
        analysis_center_xy=inputs.analysis_center_xy,
    )


def build_minimal_stage3_context(
    *,
    representative_node_id: str,
    normalized_mainnodeid: str,
    template_class: str,
    representative_kind_2: int | None = None,
) -> Stage3Context:
    return build_stage3_context_from_legacy_inputs(
        Stage3LegacyContextInputs(
            representative_node_id=representative_node_id,
            normalized_mainnodeid=normalized_mainnodeid,
            template_class=template_class,
            representative_kind_2=representative_kind_2,
        )
    )
