from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t02_junction_anchor.shared import LoadedFeature
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import _explode_component_geometries
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    BranchEvidence,
    ParsedNode,
    ParsedRoad,
)

from .case_models import (
    T04CaseBundle,
    T04EventUnitResult,
    T04UnitContext,
)


CANDIDATE_MIN_AREA_M2 = 2.0


@dataclass(frozen=True)
class _PreparedUnitInputs:
    case_bundle: T04CaseBundle
    unit_context: T04UnitContext
    event_unit_spec: Any
    effective_representative_node: Any
    effective_source_kind_2: int | None
    scoped_branches: tuple[Any, ...]
    scoped_roads: tuple[ParsedRoad, ...]
    scoped_rcsd_roads: tuple[ParsedRoad, ...]
    scoped_rcsd_nodes: tuple[ParsedNode, ...]
    scoped_divstrip_features: tuple[LoadedFeature, ...]
    scoped_main_branch_ids: frozenset[str]
    scoped_input_branch_ids: tuple[str, ...]
    scoped_output_branch_ids: tuple[str, ...]
    unit_population_node_ids: tuple[str, ...]
    context_augmented_node_ids: tuple[str, ...]
    explicit_event_branch_ids: tuple[str, ...]
    boundary_branch_ids: tuple[str, ...]
    boundary_pair_signature: str | None
    branch_road_memberships: dict[str, tuple[str, ...]]
    branch_bridge_node_ids: dict[str, tuple[str, ...]]
    degraded_scope_reason: str | None
    pair_local_summary: dict[str, Any]
    pair_local_region_geometry: BaseGeometry | None
    pair_local_structure_face_geometry: BaseGeometry | None
    pair_local_middle_geometry: BaseGeometry | None
    pair_local_throat_core_geometry: BaseGeometry | None
    pair_local_drivezone_union: BaseGeometry | None
    pair_local_scope_roads: tuple[ParsedRoad, ...]
    pair_local_scope_rcsd_roads: tuple[ParsedRoad, ...]
    pair_local_scope_rcsd_nodes: tuple[ParsedNode, ...]
    pair_local_scope_divstrip_features: tuple[LoadedFeature, ...]
    pair_local_patch_size_m: float
    preferred_axis_branch_id: str | None
    pair_local_axis_origin_point: BaseGeometry | None
    pair_local_axis_unit_vector: tuple[float, float] | None
    operational_kind_hint: int | None


@dataclass(frozen=True)
class _ExecutableBranchSet:
    road_branches: tuple[BranchEvidence, ...]
    branch_ids: tuple[str, ...]
    main_branch_ids: tuple[str, ...]
    input_branch_ids: tuple[str, ...]
    output_branch_ids: tuple[str, ...]
    event_branch_ids: tuple[str, ...]
    boundary_branch_ids: tuple[str, ...]
    branch_road_memberships: dict[str, tuple[str, ...]]
    branch_bridge_node_ids: dict[str, tuple[str, ...]]
    operational_kind_hint: int | None


@dataclass(frozen=True)
class _CandidateEvaluation:
    result: T04EventUnitResult
    priority_score: int


def _geometry_present(geometry: BaseGeometry | None) -> bool:
    return bool(geometry is not None and not geometry.is_empty)


def _safe_normalize_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    try:
        normalized = geometry.buffer(0)
    except Exception:
        normalized = geometry
    if normalized is None or normalized.is_empty:
        return None
    return normalized


def _clip_geometry_to_scope(
    geometry: BaseGeometry | None,
    *,
    scope_geometry: BaseGeometry | None,
    pad_m: float = 0.0,
) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if scope_geometry is None or scope_geometry.is_empty:
        return geometry
    try:
        clip_geometry = scope_geometry.buffer(float(max(0.0, pad_m)), join_style=2)
    except Exception:
        clip_geometry = scope_geometry
    clipped = geometry.intersection(clip_geometry)
    return _safe_normalize_geometry(clipped)


def _area_ratio(numerator: BaseGeometry | None, denominator: BaseGeometry | None) -> float:
    if not _geometry_present(numerator) or not _geometry_present(denominator):
        return 0.0
    denominator_area = float(getattr(denominator, "area", 0.0) or 0.0)
    if denominator_area <= 1e-6:
        return 0.0
    overlap = numerator.intersection(denominator)
    overlap_area = float(getattr(overlap, "area", 0.0) or 0.0)
    return 0.0 if overlap_area <= 1e-6 else overlap_area / denominator_area


def _explode_polygon_geometries(geometry: BaseGeometry | None) -> list[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return []
    polygons: list[BaseGeometry] = []
    for component in _explode_component_geometries(geometry):
        if getattr(component, "geom_type", None) != "Polygon" or component.is_empty:
            continue
        normalized = _safe_normalize_geometry(component)
        if normalized is None:
            continue
        area = float(getattr(normalized, "area", 0.0) or 0.0)
        if area < CANDIDATE_MIN_AREA_M2:
            continue
        polygons.append(normalized)
    return polygons


def _road_lookup(roads: Iterable[ParsedRoad]) -> dict[str, ParsedRoad]:
    return {str(road.road_id): road for road in roads}


def _stable_axis_signature(
    branch_id: str | None,
    branch_road_memberships: dict[str, tuple[str, ...]] | dict[str, list[str]] | None,
) -> str | None:
    if branch_id is None:
        return None
    memberships = branch_road_memberships or {}
    road_ids = tuple(
        sorted(
            {
                str(road_id)
                for road_id in memberships.get(str(branch_id), ())
                if str(road_id)
            }
        )
    )
    if not road_ids:
        return str(branch_id)
    if len(road_ids) == 1:
        return road_ids[0]
    return "+".join(road_ids)


def _stable_branch_signature(
    branch_id: str | None,
    branch_road_memberships: dict[str, tuple[str, ...]] | dict[str, list[str]] | None,
) -> str | None:
    return _stable_axis_signature(branch_id, branch_road_memberships)


def _stable_boundary_pair_signature(
    boundary_branch_ids: Iterable[str] | tuple[str, ...],
    branch_road_memberships: dict[str, tuple[str, ...]] | dict[str, list[str]] | None,
) -> str | None:
    branch_signatures = tuple(
        signature
        for signature in (
            _stable_branch_signature(str(branch_id), branch_road_memberships)
            for branch_id in boundary_branch_ids
        )
        if signature
    )
    if not branch_signatures:
        return None
    return "__".join(branch_signatures)


def _stable_axis_position(
    *,
    point_geometry: BaseGeometry | None,
    branch_id: str | None,
    branch_road_memberships: dict[str, tuple[str, ...]] | dict[str, list[str]] | None,
    road_lookup: dict[str, ParsedRoad],
) -> tuple[str | None, float | None]:
    if point_geometry is None or point_geometry.is_empty or branch_id is None:
        return None, None
    point = point_geometry
    if getattr(point, "geom_type", None) != "Point":
        representative_point = point.representative_point()
        if representative_point is None or representative_point.is_empty:
            return None, None
        point = representative_point
    memberships = branch_road_memberships or {}
    candidate_road_ids = tuple(
        sorted(
            {
                str(road_id)
                for road_id in memberships.get(str(branch_id), ())
                if str(road_id) in road_lookup
            }
        )
    )
    best_basis: str | None = None
    best_position_m: float | None = None
    best_distance: float | None = None
    for road_id in candidate_road_ids:
        road = road_lookup.get(road_id)
        if road is None or road.geometry is None or road.geometry.is_empty:
            continue
        try:
            projected_m = float(road.geometry.project(point))
            projected_point = road.geometry.interpolate(projected_m)
        except Exception:
            continue
        distance_m = float(projected_point.distance(point))
        if (
            best_distance is None
            or distance_m < best_distance - 1e-9
            or (abs(distance_m - best_distance) <= 1e-9 and str(road_id) < str(best_basis))
        ):
            best_basis = str(road_id)
            best_position_m = round(projected_m, 1)
            best_distance = distance_m
    return best_basis, best_position_m


def _filter_roads_to_scope(
    roads: Iterable[ParsedRoad],
    *,
    scope_geometry: BaseGeometry | None,
    pad_m: float,
) -> tuple[ParsedRoad, ...]:
    if scope_geometry is None or scope_geometry.is_empty:
        return tuple(roads)
    scoped_roads: list[ParsedRoad] = []
    for road in roads:
        clipped_geometry = _clip_geometry_to_scope(
            road.geometry,
            scope_geometry=scope_geometry,
            pad_m=pad_m,
        )
        if clipped_geometry is None:
            continue
        scoped_roads.append(replace(road, geometry=clipped_geometry))
    return tuple(scoped_roads)


def _filter_nodes_to_scope(
    nodes: Iterable[ParsedNode],
    *,
    scope_geometry: BaseGeometry | None,
    pad_m: float,
) -> tuple[ParsedNode, ...]:
    if scope_geometry is None or scope_geometry.is_empty:
        return tuple(nodes)
    scoped_nodes: list[ParsedNode] = []
    try:
        padded_scope = scope_geometry.buffer(float(max(0.0, pad_m)), join_style=2)
    except Exception:
        padded_scope = scope_geometry
    for node in nodes:
        if node.geometry is None or node.geometry.is_empty:
            continue
        if not padded_scope.intersects(node.geometry):
            continue
        scoped_nodes.append(node)
    return tuple(scoped_nodes)


def _filter_divstrip_features_to_scope(
    features: Iterable[LoadedFeature],
    *,
    scope_geometry: BaseGeometry | None,
    pad_m: float = 0.0,
) -> tuple[LoadedFeature, ...]:
    if scope_geometry is None or scope_geometry.is_empty:
        return tuple(features)
    scoped_features: list[LoadedFeature] = []
    for feature in features:
        clipped_geometry = _clip_geometry_to_scope(
            feature.geometry,
            scope_geometry=scope_geometry,
            pad_m=pad_m,
        )
        if clipped_geometry is None:
            continue
        scoped_features.append(
            LoadedFeature(
                feature_index=feature.feature_index,
                properties=dict(feature.properties),
                geometry=clipped_geometry,
            )
        )
    return tuple(scoped_features)


def _empty_geometry_collection() -> GeometryCollection:
    return GeometryCollection()
