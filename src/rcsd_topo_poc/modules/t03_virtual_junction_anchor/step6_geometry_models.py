from __future__ import annotations

from collections import defaultdict, deque

from collections.abc import Iterable

from dataclasses import dataclass, field

from time import perf_counter

from typing import Any

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from shapely.geometry.base import BaseGeometry

from shapely.ops import nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import NodeRecord, RoadRecord

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    Step6OutputGeometries,
    Step6Result,
    FinalizationContext,
)

TARGET_NODE_BUFFER_M = 5.5

SUPPORT_ONLY_SEAM_BRIDGE_BUFFER_M = 9.0

SUPPORT_ONLY_TINY_FRAGMENT_MAX_AREA_M2 = 12.0

SUPPORT_ONLY_DOMINANT_COMPONENT_MIN_RATIO = 0.95

REQUIRED_NODE_BUFFER_M = 5.5

REQUIRED_ROAD_BUFFER_M = 6.0

SEMANTIC_INTRA_LINE_BUFFER_M = 5.5

FOREIGN_MASK_BUFFER_M = 1.0

LEGAL_SPACE_TOLERANCE_M = 0.6

NODE_COVER_TOLERANCE_M = 1.0

TARGET_NODE_INCIDENT_ROAD_COVER_TOLERANCE_M = 10.0

LINE_COVER_BUFFER_M = 2.0

LINE_COVER_MIN_RATIO = 0.68

SELECTED_ROAD_CORE_MIN_RATIO = 0.45

TARGET_NODE_CONNECTION_MIN_RATIO = 0.98

FOREIGN_OVERLAP_TOLERANCE_M2 = 0.05

FINAL_CLOSE_M = 1.6

DIRECTIONAL_CUT_DISTANCE_M = 20.0

DIRECTIONAL_WINDOW_MIN_HALF_WIDTH_M = 60.0

DIRECTIONAL_WINDOW_EXTENSION_FACTOR = 2.0

STEP3_TWO_NODE_T_BRIDGE_BUFFER_M = 8.0

CENTER_TWO_NODE_T_BRIDGE_MAX_LENGTH_M = 90.0

BRANCH_CLIP_HALF_WIDTH_M = 10.0

BRANCH_SPECIAL_CLIP_HALF_WIDTH_M = 6.0

BRANCH_CLIP_CENTER_RADIUS_M = 14.0

BRANCH_TRIM_HALF_WIDTH_M = 6.0

BRANCH_SPECIAL_TRIM_HALF_WIDTH_M = 4.0

SINGLE_SIDED_HORIZONTAL_EXTENSION_M = 5.0

SINGLE_SIDED_HORIZONTAL_ALIGNMENT_TOLERANCE_M = 8.0

SINGLE_SIDED_HORIZONTAL_MIN_REQUIRED_NODE_COUNT = 2

PRIMARY_INFEASIBLE = "infeasible_under_frozen_constraints"

PRIMARY_SOLVER_FAILED = "geometry_solver_failed"

SECONDARY_STEP1_STEP3_CONFLICT = "step1_step3_conflict"

SECONDARY_STAGE3_RC_GAP = "stage3_rc_gap"

SECONDARY_FOREIGN_CONFLICT = "foreign_exclusion_conflict"

SECONDARY_TEMPLATE_MISFIT = "template_misfit"

SECONDARY_CLOSURE_FAILURE = "geometry_closure_failure"

SECONDARY_CLEANUP_OVERTRIM = "cleanup_overtrim"

SECONDARY_CLEANUP_UNDERTRIM = "cleanup_undertrim"

SECONDARY_FOREIGN_REINTRODUCED = "foreign_reintroduced_by_cleanup"

SECONDARY_SHAPE_ARTIFACT = "shape_artifact_failure"

@dataclass(frozen=True)
class _DirectionalBranchWindow:
    road_id: str
    branch_index: int
    anchor_distance_m: float
    available_length_m: float
    cut_length_m: float
    preserve_candidate_boundary: bool
    special_rule_applied: bool
    semantic_extent_m: float | None
    core_geometry: BaseGeometry | None
    clip_geometry: BaseGeometry | None

@dataclass(frozen=True)
class _SingleSidedHorizontalTraceDecision:
    road_id: str
    branch_index: int
    trace_status: str
    vertical_seed_rcsdroad_ids: tuple[str, ...]
    traced_rcsdroad_ids: tuple[str, ...]
    traced_rcsdnode_ids: tuple[str, ...]
    semantic_extent_m: float | None
    requested_cut_length_m: float | None
    apply_special_rule: bool

@dataclass
class _Step6GeometryCache:
    line_buffer_cache: dict[tuple[bytes | None, float], BaseGeometry | None] = field(default_factory=dict)
    boundary_buffer_cache: dict[tuple[bytes | None, float], BaseGeometry | None] = field(default_factory=dict)
    shape_metrics_cache: dict[bytes | None, dict[str, Any]] = field(default_factory=dict)
    directional_cut_cache: dict[
        tuple[bool, bool],
        tuple[BaseGeometry | None, BaseGeometry | None, list[dict[str, Any]]],
    ] = field(default_factory=dict)
    allowed_space_tolerance_geometry: BaseGeometry | None = None
    allowed_space_tolerance_ready: bool = False
    target_anchor_geometry: BaseGeometry | None = None
    target_anchor_geometry_ready: bool = False
    single_sided_vertical_exit_geometry: BaseGeometry | None = None
    single_sided_vertical_exit_geometry_ready: bool = False
    single_sided_trace_decisions: dict[tuple[str, int], _SingleSidedHorizontalTraceDecision] = field(default_factory=dict)
    single_sided_trace_decisions_ready: bool = False
