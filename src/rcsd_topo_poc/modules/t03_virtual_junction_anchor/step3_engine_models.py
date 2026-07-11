from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry.base import BaseGeometry

from .case_models import RoadRecord


@dataclass(frozen=True)
class _ReachableRoadPreparedRecord:
    road: RoadRecord
    drivezone_line: BaseGeometry | None
    source_distance_start_m: float
    source_distance_end_m: float
    cap_hit: bool
    incoming_support: bool
    outgoing_support: bool

@dataclass(frozen=True)
class _ReachableRoadPreparedSupport:
    prepared_records: tuple[_ReachableRoadPreparedRecord, ...]
    base_target_core: BaseGeometry | None
    template_road_filter_applied: bool

@dataclass
class _ReachableRoadSupportCaseCache:
    prepared_supports: dict[tuple[Any, ...], _ReachableRoadPreparedSupport] = field(default_factory=dict)
    result_cache: dict[tuple[Any, ...], tuple[BaseGeometry | None, tuple[dict[str, Any], ...], frozenset[str], tuple[str, ...]]] = field(
        default_factory=dict
    )
