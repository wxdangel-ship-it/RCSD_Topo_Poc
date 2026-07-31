from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from numbers import Integral
from typing import Any

import geopandas as gpd
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.rcsd_road_ownership import (
    OWNERSHIP_MATCH_BUFFER_M,
    OWNERSHIP_QUERY_EPSILON_M,
    OWNERSHIP_TIGHT_BUFFER_M,
)

from .carrier_graph import GraphBundle, PathResult, field_name, normalize_id
from .surface_portal_carrier import ROAD_SURFACE_TOPOLOGY_TOLERANCE_M


_COVERAGE_TIE_EPSILON = 1e-9
_DISTANCE_TIE_EPSILON_M = OWNERSHIP_QUERY_EPSILON_M


@dataclass(frozen=True)
class SegmentCoverageScore:
    segment_id: str
    tight_coverage_ratio: float
    broad_coverage_ratio: float
    distance_m: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "tight_coverage_ratio": self.tight_coverage_ratio,
            "broad_coverage_ratio": self.broad_coverage_ratio,
            "distance_m": self.distance_m,
        }


class SegmentScopeIndex:
    """Read-only spatial owner candidates for T12 reverse-path evidence."""

    _MAX_BUFFER_CACHE = 512

    def __init__(self, segments: gpd.GeoDataFrame) -> None:
        segment_id_field = field_name(segments, "id")
        self.segment_ids: list[str] = []
        self.geometries: list[Any] = []
        self._geometry_index_by_identity: dict[int, int] = {}
        self._buffer_cache: OrderedDict[tuple[int, float], Any] = OrderedDict()
        for _, row in segments.iterrows():
            segment_id = normalize_id(row[segment_id_field])
            geometry = row.geometry
            if (
                not segment_id
                or geometry is None
                or geometry.is_empty
                or float(geometry.length) <= 0.0
            ):
                continue
            self._geometry_index_by_identity[id(geometry)] = len(self.geometries)
            self.segment_ids.append(segment_id)
            self.geometries.append(geometry)
        self._tree = STRtree(self.geometries) if self.geometries else None

    def scored_candidates(self, geometry: Any) -> list[SegmentCoverageScore]:
        if (
            self._tree is None
            or geometry is None
            or geometry.is_empty
            or float(geometry.length) <= 0.0
        ):
            return []
        try:
            query_result = self._tree.query(
                geometry,
                predicate="dwithin",
                distance=OWNERSHIP_MATCH_BUFFER_M + OWNERSHIP_QUERY_EPSILON_M,
            )
        except TypeError:
            query_result = self._tree.query(
                geometry.buffer(OWNERSHIP_MATCH_BUFFER_M)
            )
        indexes: list[int] = []
        for value in query_result:
            if isinstance(value, Integral):
                indexes.append(int(value))
            else:
                index = self._geometry_index_by_identity.get(id(value))
                if index is not None:
                    indexes.append(index)
        scores: list[SegmentCoverageScore] = []
        for index in indexes:
            segment_geometry = self.geometries[index]
            distance_m = float(geometry.distance(segment_geometry))
            if distance_m > OWNERSHIP_MATCH_BUFFER_M:
                continue
            scores.append(
                SegmentCoverageScore(
                    segment_id=self.segment_ids[index],
                    tight_coverage_ratio=_coverage_ratio(
                        geometry,
                        self._buffered(index, OWNERSHIP_TIGHT_BUFFER_M),
                    ),
                    broad_coverage_ratio=_coverage_ratio(
                        geometry,
                        self._buffered(index, OWNERSHIP_MATCH_BUFFER_M),
                    ),
                    distance_m=distance_m,
                )
            )
        return sorted(
            scores,
            key=lambda item: (
                -item.tight_coverage_ratio,
                -item.broad_coverage_ratio,
                item.distance_m,
                item.segment_id,
            ),
        )

    def _buffered(self, index: int, distance_m: float) -> Any:
        key = (index, float(distance_m))
        cached = self._buffer_cache.get(key)
        if cached is not None:
            self._buffer_cache.move_to_end(key)
            return cached
        buffered = self.geometries[index].buffer(distance_m)
        self._buffer_cache[key] = buffered
        if len(self._buffer_cache) > self._MAX_BUFFER_CACHE:
            self._buffer_cache.popitem(last=False)
        return buffered


def evaluate_reverse_segment_scope(
    *,
    candidate_id: str,
    current_segment_id: str,
    direction: str,
    path: PathResult,
    graph: GraphBundle,
    source_surface: Any | None,
    target_surface: Any | None,
    segment_index: SegmentScopeIndex,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    first_edge = graph.edges[path.road_ids[0]]
    last_edge = graph.edges[path.road_ids[-1]]
    source_gap_m = _surface_gap(first_edge.geometry, source_surface)
    target_gap_m = _surface_gap(last_edge.geometry, target_surface)
    source_contact = (
        source_gap_m is not None
        and source_gap_m <= ROAD_SURFACE_TOPOLOGY_TOLERANCE_M
    )
    target_contact = (
        target_gap_m is not None
        and target_gap_m <= ROAD_SURFACE_TOPOLOGY_TOLERANCE_M
    )
    excluded_surface_geometry = _surface_exclusion(
        source_surface,
        target_surface,
    )
    road_results: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    evaluated_road_ids: list[str] = []
    for sequence, road_id in enumerate(path.road_ids, start=1):
        edge = graph.edges[road_id]
        scoped_geometry = (
            edge.geometry.difference(excluded_surface_geometry)
            if excluded_surface_geometry is not None
            else edge.geometry
        )
        if (
            scoped_geometry is None
            or scoped_geometry.is_empty
            or float(scoped_geometry.length) <= 0.0
        ):
            road_results.append(
                {
                    "road_id": road_id,
                    "sequence": sequence,
                    "scope_status": "anchor_surface_internal",
                    "scoped_length_m": 0.0,
                    "owner_segment_id": "",
                    "competing_segment_ids": [],
                }
            )
            continue
        evaluated_road_ids.append(road_id)
        scores = segment_index.scored_candidates(scoped_geometry)
        result = _road_owner_result(
            road_id=road_id,
            sequence=sequence,
            current_segment_id=current_segment_id,
            scoped_length_m=float(scoped_geometry.length),
            scores=scores,
        )
        road_results.append(result)
        evidence_rows.append(
            {
                "candidate_id": candidate_id,
                "segment_id": current_segment_id,
                "direction": direction,
                **result,
                "geometry": scoped_geometry,
            }
        )
    anchor_interval = {
        "accepted_anchor_interval": bool(
            source_contact and target_contact and evaluated_road_ids
        ),
        "source_surface_available": source_surface is not None,
        "target_surface_available": target_surface is not None,
        "source_road_id": path.road_ids[0],
        "target_road_id": path.road_ids[-1],
        "source_road_surface_gap_m": source_gap_m,
        "target_road_surface_gap_m": target_gap_m,
        "surface_topology_tolerance_m": ROAD_SURFACE_TOPOLOGY_TOLERANCE_M,
        "evaluated_road_ids": evaluated_road_ids,
        "rejection_reason": _anchor_interval_rejection(
            source_surface=source_surface,
            target_surface=target_surface,
            source_contact=source_contact,
            target_contact=target_contact,
            evaluated_road_ids=evaluated_road_ids,
        ),
    }
    other_segment_ids = sorted(
        {
            str(row["owner_segment_id"])
            for row in road_results
            if row.get("scope_status") == "owned_by_other_segment"
            and row.get("owner_segment_id")
        }
    )
    ambiguous_road_ids = [
        str(row["road_id"])
        for row in road_results
        if row.get("scope_status") == "ambiguous_segment_ownership"
    ]
    current_owned_road_ids = [
        str(row["road_id"])
        for row in road_results
        if row.get("scope_status") == "owned_by_current_segment"
    ]
    ownership_accepted = bool(evaluated_road_ids) and len(
        current_owned_road_ids
    ) == len(evaluated_road_ids)
    ownership = {
        "accepted_current_segment_owner": ownership_accepted,
        "current_segment_id": current_segment_id,
        "evaluated_road_ids": evaluated_road_ids,
        "current_owned_road_ids": current_owned_road_ids,
        "other_segment_ids": other_segment_ids,
        "ambiguous_road_ids": ambiguous_road_ids,
        "road_results": road_results,
        "tight_buffer_m": OWNERSHIP_TIGHT_BUFFER_M,
        "broad_buffer_m": OWNERSHIP_MATCH_BUFFER_M,
        "ranking": "tight_coverage_then_broad_coverage_then_distance",
        "rejection_reason": (
            ""
            if ownership_accepted
            else "other_segment_covered"
            if other_segment_ids
            else "segment_ownership_ambiguous"
        ),
    }
    return anchor_interval, ownership, evidence_rows


def _road_owner_result(
    *,
    road_id: str,
    sequence: int,
    current_segment_id: str,
    scoped_length_m: float,
    scores: list[SegmentCoverageScore],
) -> dict[str, Any]:
    current = next(
        (score for score in scores if score.segment_id == current_segment_id),
        None,
    )
    best = scores[0] if scores else None
    tied_best = (
        [
            score.segment_id
            for score in scores[1:]
            if best is not None and _same_score(best, score)
        ]
        if best is not None
        else []
    )
    competing = [
        score.segment_id
        for score in scores
        if score.segment_id != current_segment_id
    ][:8]
    if best is None or current is None or tied_best:
        status = "ambiguous_segment_ownership"
        owner_segment_id = ""
    elif best.segment_id == current_segment_id:
        status = "owned_by_current_segment"
        owner_segment_id = current_segment_id
    else:
        status = "owned_by_other_segment"
        owner_segment_id = best.segment_id
    return {
        "road_id": road_id,
        "sequence": sequence,
        "scope_status": status,
        "scoped_length_m": scoped_length_m,
        "owner_segment_id": owner_segment_id,
        "current_tight_coverage_ratio": (
            current.tight_coverage_ratio if current is not None else None
        ),
        "current_broad_coverage_ratio": (
            current.broad_coverage_ratio if current is not None else None
        ),
        "current_distance_m": current.distance_m if current is not None else None,
        "best_tight_coverage_ratio": (
            best.tight_coverage_ratio if best is not None else None
        ),
        "best_broad_coverage_ratio": (
            best.broad_coverage_ratio if best is not None else None
        ),
        "best_distance_m": best.distance_m if best is not None else None,
        "tied_best_segment_ids": tied_best,
        "competing_segment_ids": competing,
        "owner_candidates": [score.as_dict() for score in scores[:8]],
    }


def _anchor_interval_rejection(
    *,
    source_surface: Any | None,
    target_surface: Any | None,
    source_contact: bool,
    target_contact: bool,
    evaluated_road_ids: list[str],
) -> str:
    if source_surface is None or target_surface is None:
        return "dual_t07_surface_required"
    if not source_contact or not target_contact:
        return "endpoint_road_surface_contact_missing"
    if not evaluated_road_ids:
        return "inter_anchor_physical_road_required"
    return ""


def _surface_exclusion(source_surface: Any | None, target_surface: Any | None) -> Any:
    surfaces = [
        surface.buffer(ROAD_SURFACE_TOPOLOGY_TOLERANCE_M)
        for surface in (source_surface, target_surface)
        if surface is not None and not surface.is_empty
    ]
    if not surfaces:
        return None
    result = surfaces[0]
    for surface in surfaces[1:]:
        result = result.union(surface)
    return result


def _surface_gap(geometry: Any, surface: Any | None) -> float | None:
    if surface is None or surface.is_empty:
        return None
    return float(geometry.distance(surface))


def _coverage_ratio(geometry: Any, buffered_segment: Any) -> float:
    length_m = float(geometry.length)
    if length_m <= 0.0:
        return 0.0
    covered_m = float(geometry.intersection(buffered_segment).length)
    return min(1.0, max(0.0, covered_m / length_m))


def _same_score(left: SegmentCoverageScore, right: SegmentCoverageScore) -> bool:
    return (
        abs(left.tight_coverage_ratio - right.tight_coverage_ratio)
        <= _COVERAGE_TIE_EPSILON
        and abs(left.broad_coverage_ratio - right.broad_coverage_ratio)
        <= _COVERAGE_TIE_EPSILON
        and abs(left.distance_m - right.distance_m)
        <= _DISTANCE_TIE_EPSILON_M
    )
