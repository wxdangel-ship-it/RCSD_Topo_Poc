from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_geometry_solve import (
    Stage3Step6GeometrySolveInputs,
    build_stage3_step6_geometry_solve_result,
)

_REGULARIZATION_REVIEW_REASON = (
    "nonstable_center_junction_extreme_geometry_anomaly"
)
_EROSION_FRACTION = 0.15
_MIN_EROSION_M = 0.3
_MAX_EROSION_M = 3.0
_TAIL_TRIM_FRACTIONS = (0.12, 0.16, 0.20, 0.24, 0.28, 0.32, 0.36, 0.40)
_TAIL_TRIM_MIN_AREA_RATIO = 0.70
_TAIL_TRIM_MAX_AREA_RATIO = 0.95
_TAIL_TRIM_MIN_ASPECT_IMPROVEMENT = 0.25
_TAIL_TRIM_MIN_COMPACTNESS_IMPROVEMENT = 0.01
_TAIL_TRIM_MIN_BBOX_FILL_IMPROVEMENT = 0.01
_TAIL_TRIM_RELEASE_ASPECT_RATIO = 3.0
_TAIL_TRIM_RELEASE_COMPACTNESS = 0.10
_TAIL_TRIM_RELEASE_BBOX_FILL_RATIO = 0.30


@dataclass(frozen=True)
class _RegularizationMetrics:
    area: float
    compactness: float | None
    bbox_fill_ratio: float | None
    aspect_ratio: float | None


def _compute_metrics(geom: Any) -> _RegularizationMetrics | None:
    """Compute shape metrics for a polygon geometry (shapely-compatible)."""
    if geom is None or geom.is_empty:
        return None
    area = float(geom.area)
    perimeter = float(geom.length)
    if area <= 0.0:
        return None
    compactness = (
        (4.0 * math.pi * area) / (perimeter * perimeter)
        if perimeter > 0.0
        else None
    )
    minx, miny, maxx, maxy = geom.bounds
    bbox_area = max(0.0, (maxx - minx) * (maxy - miny))
    bbox_fill_ratio = area / bbox_area if bbox_area > 0.0 else None
    aspect_ratio: float | None = None
    try:
        oriented = geom.minimum_rotated_rectangle
        if not oriented.is_empty and hasattr(oriented, "exterior"):
            coords = list(oriented.exterior.coords)
            if len(coords) >= 5:
                edges = sorted(
                    math.hypot(
                        coords[i + 1][0] - coords[i][0],
                        coords[i + 1][1] - coords[i][1],
                    )
                    for i in range(4)
                )
                if edges[0] > 0.0:
                    aspect_ratio = edges[-1] / edges[0]
    except Exception:
        pass
    return _RegularizationMetrics(
        area=area,
        compactness=compactness,
        bbox_fill_ratio=bbox_fill_ratio,
        aspect_ratio=aspect_ratio,
    )


def _estimate_min_half_width(geometry: Any) -> float:
    """Approximate half of the narrowest dimension via oriented bounding rect."""
    try:
        oriented = geometry.minimum_rotated_rectangle
        if oriented.is_empty or not hasattr(oriented, "exterior"):
            return 0.0
        coords = list(oriented.exterior.coords)
        if len(coords) < 5:
            return 0.0
        edges = sorted(
            math.hypot(
                coords[i + 1][0] - coords[i][0],
                coords[i + 1][1] - coords[i][1],
            )
            for i in range(4)
        )
        return edges[0] / 2.0
    except Exception:
        return 0.0


def _major_axis_unit_vector(geometry: Any) -> tuple[tuple[float, float], float] | None:
    try:
        oriented = geometry.minimum_rotated_rectangle
        if oriented.is_empty or not hasattr(oriented, "exterior"):
            return None
        coords = list(oriented.exterior.coords)
        if len(coords) < 5:
            return None
        edges = []
        for idx in range(4):
            dx = coords[idx + 1][0] - coords[idx][0]
            dy = coords[idx + 1][1] - coords[idx][1]
            length = math.hypot(dx, dy)
            if length > 0.0:
                edges.append((length, dx / length, dy / length))
        if not edges:
            return None
        length, ux, uy = max(edges, key=lambda item: item[0])
        return (ux, uy), length
    except Exception:
        return None


def _clip_geometry_along_major_axis(
    geometry: Any,
    *,
    tail_fraction: float,
    keep_positive_end: bool,
) -> Any | None:
    axis = _major_axis_unit_vector(geometry)
    if axis is None:
        return None
    (ux, uy), _axis_length = axis
    if geometry is None or geometry.is_empty or not hasattr(geometry, "exterior"):
        return None
    centroid = geometry.centroid
    cx = float(centroid.x)
    cy = float(centroid.y)
    try:
        coords = list(geometry.exterior.coords)
    except Exception:
        return None
    if not coords:
        return None
    projections = [
        ((float(x) - cx) * ux) + ((float(y) - cy) * uy)
        for x, y in coords
    ]
    min_projection = min(projections)
    max_projection = max(projections)
    span = max_projection - min_projection
    if span <= 0.0:
        return None
    clip_offset = span * float(tail_fraction)
    if clip_offset <= 0.0:
        return None
    if keep_positive_end:
        lower_bound = min_projection + clip_offset
        upper_bound = max_projection + span
    else:
        lower_bound = min_projection - span
        upper_bound = max_projection - clip_offset
    nx = -uy
    ny = ux
    minx, miny, maxx, maxy = geometry.bounds
    half_width = max(maxx - minx, maxy - miny, 1.0) * 10.0
    clip_polygon = (
        (
            cx + (ux * lower_bound) + (nx * -half_width),
            cy + (uy * lower_bound) + (ny * -half_width),
        ),
        (
            cx + (ux * lower_bound) + (nx * half_width),
            cy + (uy * lower_bound) + (ny * half_width),
        ),
        (
            cx + (ux * upper_bound) + (nx * half_width),
            cy + (uy * upper_bound) + (ny * half_width),
        ),
        (
            cx + (ux * upper_bound) + (nx * -half_width),
            cy + (uy * upper_bound) + (ny * -half_width),
        ),
    )
    try:
        candidate = geometry.intersection(type(geometry)(clip_polygon))
        if candidate.is_empty:
            return None
        candidate = candidate.buffer(0)
        if candidate.is_empty or not candidate.is_valid:
            return None
        if candidate.geom_type == "MultiPolygon":
            pieces = [piece for piece in candidate.geoms if not piece.is_empty]
            if len(pieces) != 1:
                return None
            candidate = pieces[0]
        if candidate.geom_type != "Polygon":
            return None
        return candidate
    except Exception:
        return None


def _attempt_bounded_regularization_candidate(
    geometry: Any,
) -> Any | None:
    """Morphological closing: erode then dilate to remove narrow protrusions.

    Erosion depth is adaptive: a fraction of the narrowest half-width,
    clamped to [_MIN_EROSION_M, _MAX_EROSION_M].  If the erosion collapses
    the polygon to empty we return ``None``.
    """
    if geometry is None or geometry.is_empty:
        return None
    try:
        half_w = _estimate_min_half_width(geometry)
        if half_w <= 0.0:
            return None
        erosion = min(
            _MAX_EROSION_M,
            max(_MIN_EROSION_M, half_w * _EROSION_FRACTION),
        )
        eroded = geometry.buffer(-erosion, join_style=2)
        if eroded.is_empty:
            return None
        candidate = eroded.buffer(erosion, join_style=2)
        if candidate.is_empty:
            return None
        candidate = candidate.buffer(0)
        if not candidate.is_valid or candidate.is_empty:
            return None
        return candidate
    except Exception:
        return None


def select_regularization_candidate(
    *,
    original_geometry: Any,
    candidate_geometry: Any | None,
    original_uncovered_endpoint_count: int,
    original_foreign_semantic_node_ids: frozenset[str],
    original_compactness: float | None,
    original_bbox_fill_ratio: float | None,
) -> tuple[bool, Any | None, _RegularizationMetrics | None]:
    """Return (accepted, final_geometry_or_None, metrics_or_None).

    Hard gates (any failure -> reject):
    - candidate non-degenerate
    - area <= original area
    - uncovered endpoints not increased (checked by caller via containment)
    - no new foreign residue (not checkable here – caller responsibility)

    Improvement condition:
    - compactness OR bbox_fill_ratio strictly improves
    """
    if candidate_geometry is None:
        return False, None, None

    orig_metrics = _compute_metrics(original_geometry)
    cand_metrics = _compute_metrics(candidate_geometry)
    if orig_metrics is None or cand_metrics is None:
        return False, None, None

    if cand_metrics.area > orig_metrics.area * 1.001:
        return False, None, None

    compactness_improved = (
        cand_metrics.compactness is not None
        and original_compactness is not None
        and cand_metrics.compactness > original_compactness
    )
    bbox_fill_improved = (
        cand_metrics.bbox_fill_ratio is not None
        and original_bbox_fill_ratio is not None
        and cand_metrics.bbox_fill_ratio > original_bbox_fill_ratio
    )
    if not (compactness_improved or bbox_fill_improved):
        return False, None, None

    return True, candidate_geometry, cand_metrics


def select_surplus_trunk_tail_trim_candidate(
    *,
    original_geometry: Any,
    original_aspect_ratio: float | None,
    original_compactness: float | None,
    original_bbox_fill_ratio: float | None,
) -> tuple[bool, Any | None, _RegularizationMetrics | None]:
    """Select a one-sided clip candidate that removes a surplus trunk tail.

    The candidate must reduce the long-axis elongation while keeping most of
    the polygon intact. We only accept conservative one-sided clips that
    noticeably improve shape metrics and keep at least 70% of the area.
    """
    orig_metrics = _compute_metrics(original_geometry)
    if orig_metrics is None or original_geometry is None or original_geometry.is_empty:
        return False, None, None

    best_score: float | None = None
    best_geometry: Any | None = None
    best_metrics: _RegularizationMetrics | None = None
    for tail_fraction in _TAIL_TRIM_FRACTIONS:
        for keep_positive_end in (True, False):
            candidate_geometry = _clip_geometry_along_major_axis(
                original_geometry,
                tail_fraction=tail_fraction,
                keep_positive_end=keep_positive_end,
            )
            if candidate_geometry is None:
                continue
            candidate_metrics = _compute_metrics(candidate_geometry)
            if candidate_metrics is None:
                continue
            area_ratio = candidate_metrics.area / orig_metrics.area
            if (
                area_ratio < _TAIL_TRIM_MIN_AREA_RATIO
                or area_ratio > _TAIL_TRIM_MAX_AREA_RATIO
            ):
                continue
            aspect_improved = (
                candidate_metrics.aspect_ratio is not None
                and original_aspect_ratio is not None
                and candidate_metrics.aspect_ratio
                <= (original_aspect_ratio - _TAIL_TRIM_MIN_ASPECT_IMPROVEMENT)
            )
            compactness_improved = (
                candidate_metrics.compactness is not None
                and original_compactness is not None
                and candidate_metrics.compactness
                >= (original_compactness + _TAIL_TRIM_MIN_COMPACTNESS_IMPROVEMENT)
            )
            bbox_fill_improved = (
                candidate_metrics.bbox_fill_ratio is not None
                and original_bbox_fill_ratio is not None
                and candidate_metrics.bbox_fill_ratio
                >= (original_bbox_fill_ratio + _TAIL_TRIM_MIN_BBOX_FILL_IMPROVEMENT)
            )
            if not aspect_improved:
                continue
            if not (compactness_improved or bbox_fill_improved):
                continue
            release_ready = bool(
                (
                    candidate_metrics.aspect_ratio is not None
                    and candidate_metrics.aspect_ratio <= _TAIL_TRIM_RELEASE_ASPECT_RATIO
                )
                or (
                    candidate_metrics.compactness is not None
                    and candidate_metrics.compactness >= _TAIL_TRIM_RELEASE_COMPACTNESS
                )
                or (
                    candidate_metrics.bbox_fill_ratio is not None
                    and candidate_metrics.bbox_fill_ratio >= _TAIL_TRIM_RELEASE_BBOX_FILL_RATIO
                )
            )
            if not release_ready:
                continue
            score = (
                ((original_aspect_ratio or 0.0) - (candidate_metrics.aspect_ratio or 0.0)) * 1.5
                + ((candidate_metrics.compactness or 0.0) - (original_compactness or 0.0)) * 8.0
                + (
                    (candidate_metrics.bbox_fill_ratio or 0.0)
                    - (original_bbox_fill_ratio or 0.0)
                )
                * 5.0
            )
            if best_score is None or score > best_score:
                best_score = score
                best_geometry = candidate_geometry
                best_metrics = candidate_metrics
    if best_geometry is None or best_metrics is None:
        return False, None, None
    return True, best_geometry, best_metrics


def build_stage3_step6_polygon_solver_result(
    inputs: Stage3Step6GeometrySolveInputs,
):
    return build_stage3_step6_geometry_solve_result(inputs)


__all__ = [
    "Stage3Step6GeometrySolveInputs",
    "build_stage3_step6_geometry_solve_result",
    "build_stage3_step6_polygon_solver_result",
    "select_surplus_trunk_tail_trim_candidate",
    "select_regularization_candidate",
]
