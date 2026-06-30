from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .buffer_segment_extraction import BufferSegmentResult


GEOMETRY_BUFFER_RETRY_REASONS = {
    "retained_geometry_outside_swsd_buffer_scope",
    "swsd_geometry_not_covered_by_retained_rcsd",
}
CONNECTIVITY_BUFFER_RETRY_REASONS = {
    "required_semantic_nodes_missing_from_buffer_graph",
    "required_semantic_nodes_not_connected_in_buffer",
    "rcsd_directed_path_missing",
}
DUAL_DIRECTION_BUFFER_RETRY_REASONS = {
    "rcsd_not_bidirectional_for_swsd_dual",
}


@dataclass(frozen=True)
class AdaptiveBufferRetryPlan:
    distances_m: tuple[float, ...]
    retry_reason: str


def high_grade_adaptive_buffer_retry_plan(
    *,
    sgrade: Any,
    directionality: str,
    buffer_result: BufferSegmentResult,
    diagnostic: dict[str, Any],
    base_buffer_distance_m: float,
) -> AdaptiveBufferRetryPlan | None:
    if not _is_high_grade_sgrade(sgrade):
        return None
    if directionality == "single":
        return _single_retry_plan(
            buffer_result=buffer_result,
            diagnostic=diagnostic,
            base_buffer_distance_m=base_buffer_distance_m,
        )
    if directionality == "dual":
        return _dual_retry_plan(
            buffer_result=buffer_result,
            diagnostic=diagnostic,
            base_buffer_distance_m=base_buffer_distance_m,
        )
    return None


def _single_retry_plan(
    *,
    buffer_result: BufferSegmentResult,
    diagnostic: dict[str, Any],
    base_buffer_distance_m: float,
) -> AdaptiveBufferRetryPlan | None:
    if buffer_result.reason in GEOMETRY_BUFFER_RETRY_REASONS:
        return _plan(
            base_buffer_distance_m=base_buffer_distance_m,
            distances=(75.0,),
            retry_reason="high_grade_single_geometry_buffer_scope_retry",
        )
    if buffer_result.reason in CONNECTIVITY_BUFFER_RETRY_REASONS and _full_graph_supports_retry(diagnostic):
        return _plan(
            base_buffer_distance_m=base_buffer_distance_m,
            distances=(75.0, 100.0),
            retry_reason="high_grade_single_connected_full_graph_buffer_retry",
        )
    return None


def _dual_retry_plan(
    *,
    buffer_result: BufferSegmentResult,
    diagnostic: dict[str, Any],
    base_buffer_distance_m: float,
) -> AdaptiveBufferRetryPlan | None:
    if buffer_result.reason in GEOMETRY_BUFFER_RETRY_REASONS and _full_graph_supports_dual_retry(diagnostic):
        return _plan(
            base_buffer_distance_m=base_buffer_distance_m,
            distances=(75.0, 100.0, 125.0),
            retry_reason="high_grade_dual_geometry_buffer_scope_retry",
        )
    if buffer_result.reason in DUAL_DIRECTION_BUFFER_RETRY_REASONS and _full_graph_supports_dual_retry(diagnostic):
        return _plan(
            base_buffer_distance_m=base_buffer_distance_m,
            distances=(75.0, 100.0, 125.0),
            retry_reason="high_grade_dual_bidirectional_buffer_retry",
        )
    if buffer_result.reason in CONNECTIVITY_BUFFER_RETRY_REASONS and _full_graph_supports_dual_retry(diagnostic):
        return _plan(
            base_buffer_distance_m=base_buffer_distance_m,
            distances=(75.0, 100.0, 125.0),
            retry_reason="high_grade_dual_connected_full_graph_buffer_retry",
        )
    return None


def _is_high_grade_sgrade(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith("0-0") or text.startswith("0-1")


def _full_graph_supports_retry(diagnostic: dict[str, Any]) -> bool:
    if diagnostic.get("full_graph_status") != "required_nodes_connected":
        return False
    directional_status = str(diagnostic.get("directional_status") or "")
    return "full=directed_path_present" in directional_status


def _full_graph_supports_dual_retry(diagnostic: dict[str, Any]) -> bool:
    if diagnostic.get("full_graph_status") != "required_nodes_connected":
        return False
    directional_status = str(diagnostic.get("directional_status") or "")
    return "full=bidirectional" in directional_status


def _plan(
    *,
    base_buffer_distance_m: float,
    distances: tuple[float, ...],
    retry_reason: str,
) -> AdaptiveBufferRetryPlan | None:
    eligible = tuple(distance for distance in distances if distance > base_buffer_distance_m)
    if not eligible:
        return None
    return AdaptiveBufferRetryPlan(distances_m=eligible, retry_reason=retry_reason)
