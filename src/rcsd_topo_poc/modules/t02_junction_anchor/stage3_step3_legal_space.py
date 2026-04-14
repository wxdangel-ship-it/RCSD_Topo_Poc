from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step3LegalSpaceResult,
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
class Stage3Step3LegalSpaceInputs:
    template_class: str
    legal_activity_space_geometry: Any | None
    allowed_drivezone_geometry: Any | None
    must_cover_group_node_ids: Iterable[str]
    single_sided_corridor_road_ids: Iterable[str]
    hard_boundary_road_ids: Iterable[str] = ()
    step3_blockers: Iterable[str] = ()


def build_stage3_step3_legal_space_result(
    inputs: Stage3Step3LegalSpaceInputs,
) -> Stage3Step3LegalSpaceResult:
    must_cover_group_node_ids = _frozen_ids(inputs.must_cover_group_node_ids)
    single_sided_corridor_road_ids = _frozen_ids(inputs.single_sided_corridor_road_ids)
    hard_boundary_road_ids = _frozen_ids(inputs.hard_boundary_road_ids)
    step3_blockers = _sorted_unique(inputs.step3_blockers)
    return Stage3Step3LegalSpaceResult(
        template_class=str(inputs.template_class or ""),
        legal_activity_space_geometry=inputs.legal_activity_space_geometry,
        allowed_drivezone_geometry=inputs.allowed_drivezone_geometry,
        must_cover_group_node_ids=must_cover_group_node_ids,
        hard_boundary_road_ids=hard_boundary_road_ids,
        single_sided_corridor_road_ids=single_sided_corridor_road_ids,
        step3_blockers=step3_blockers,
    )
