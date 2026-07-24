from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SegmentState(str, Enum):
    HP_FULL = "hp_full"
    HP_PARTIAL = "hp_partial"
    SWSD_RETAINED = "swsd_retained"
    CONFLICT_RETAINED = "conflict_retained"


class CarrierRealization(str, Enum):
    BUILT = "built"
    RETAINED = "retained"


class ReplacementScope(str, Enum):
    ALL = "all"
    SUBSET = "subset"
    NONE = "none"


class JunctionSource(str, Enum):
    T04_ACCEPTED = "t04_accepted"
    T07_ACCEPTED = "t07_accepted"
    T03_ACCEPTED = "t03_accepted"
    FULL_RCSD_VERIFIED = "full_rcsd_verified"
    SWSD_RETAINED = "swsd_retained"


class JunctionKind(str, Enum):
    ORDINARY = "ordinary"
    COMPLEX_DIVMERGE = "complex_divmerge"
    ROUNDABOUT = "roundabout"
    AUXILIARY = "auxiliary"
    RETAINED = "retained"


HARD_REASON_CODES = frozenset(
    {
        "segment_without_road",
        "required_carrier_missing",
        "overlapping_direction_representation",
        "built_road_contains_swsd_coordinates",
        "road_node_reference_missing",
        "junction_mainnode_mismatch",
        "junc_node_dropped",
        "roadnextroad_not_shared_node",
        "completion_outside_road_domain",
        "confirmed_lanetopo_conflict",
        "crs_invalid",
        "independent_qa_failed",
    }
)

SOFT_REASON_CODES = frozenset(
    {
        "one_direction_inferred",
        "long_constrained_completion",
        "low_center_corridor_confidence",
        "full_rcsd_geometry_difference",
        "lane_width_quality_isolated",
        "local_movement_evidence_insufficient",
        "t07_t03_surface_difference",
        "patch_road_fragmentation",
    }
)


@dataclass(frozen=True)
class SegmentFirstResult:
    run_id: str
    output_dir: Path
    formal_gpkg: Path
    audit_gpkg: Path
    relations_gpkg: Path
    summary_path: Path
    report_path: Path
    independent_quality_path: Path
    qgis_project_path: Path | None
    terminal_status: str
    core_gate_pass: bool


def validate_publication_state(
    state: SegmentState,
    replacement_scope: ReplacementScope,
    built_count: int,
    retained_count: int,
) -> None:
    if built_count < 0 or retained_count < 0 or built_count + retained_count == 0:
        raise ValueError("a publishable Segment must own at least one Road carrier")
    if state is SegmentState.HP_FULL:
        if replacement_scope is not ReplacementScope.ALL or built_count == 0 or retained_count:
            raise ValueError("hp_full requires all-built carriers and replacement_scope=all")
    elif state is SegmentState.HP_PARTIAL:
        if replacement_scope is not ReplacementScope.SUBSET or not built_count or not retained_count:
            raise ValueError("hp_partial requires built and retained complete Road carriers")
    elif state in {SegmentState.SWSD_RETAINED, SegmentState.CONFLICT_RETAINED}:
        if replacement_scope is not ReplacementScope.NONE or built_count or not retained_count:
            raise ValueError(f"{state.value} requires retained carriers only")


__all__ = [
    "CarrierRealization",
    "HARD_REASON_CODES",
    "JunctionKind",
    "JunctionSource",
    "ReplacementScope",
    "SOFT_REASON_CODES",
    "SegmentFirstResult",
    "SegmentState",
    "validate_publication_state",
]
