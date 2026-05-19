from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from .models import (
    ALLOWED_SURFACE_SOURCES,
    JUNCTION_TYPE_BY_SOURCE_KIND,
    SOURCE_ORDER,
    SOURCE_T02_INPUT,
    SOURCE_T03,
    SOURCE_T04,
    T03_KIND_VALUES,
    T04_KIND_VALUES,
    FusionResult,
    SourceSurface,
)


MULTI_SOURCE_UNION_MAX_GAP_M = 2.0


def fuse_surfaces(surfaces: Iterable[SourceSurface]) -> list[FusionResult]:
    grouped: dict[tuple[str, ...], list[SourceSurface]] = defaultdict(list)
    for surface in surfaces:
        grouped[_group_key(surface)].append(surface)
    return [
        _fuse_group(group_id=_group_id(key), surfaces=items)
        for key, items in sorted(grouped.items(), key=lambda item: _group_id(item[0]))
    ]


def _fuse_group(*, group_id: str, surfaces: list[SourceSurface]) -> FusionResult:
    ordered = sorted(surfaces, key=_surface_sort_key)
    primary = _select_primary(ordered)
    sources_all = _ordered_sources(surface.source for surface in ordered)
    source_count = len(ordered)
    source_modules = "|".join(sources_all)
    source_patch_ids = _pipe_join(surface.patch_id for surface in ordered)
    source_feature_ids = _pipe_join(f"{surface.source}:{surface.source_feature_id}" for surface in ordered)
    source_case_ids = _pipe_join(surface.source_case_id for surface in ordered)
    conflict_reasons: list[str] = []
    notes = _ordered_text(note for surface in ordered for note in surface.notes)

    if {SOURCE_T03, SOURCE_T04}.issubset(set(sources_all)):
        conflict_reasons.append("t03_t04_same_mainnodeid")

    kind_values = {surface.kind_2 for surface in ordered if surface.kind_2 is not None}
    if len(kind_values) > 1:
        conflict_reasons.append("kind_2_conflict")

    patch_values = {surface.patch_id for surface in ordered if surface.patch_id}
    if len(patch_values) > 1:
        conflict_reasons.append("patch_id_conflict")

    geometry_cleaned = any(surface.geometry_cleaned for surface in ordered)
    geometry_action = "keep_source"
    fusion_action = "single_source"
    selected_surfaces = [primary]
    final_geometry = primary.geometry

    if len(set(sources_all)) > 1:
        if _geometries_within_union_gap(ordered):
            union_geometry, union_cleaned = _clean_polygonal(unary_union([surface.geometry for surface in ordered]))
            if union_geometry is not None and _components_reasonable(union_geometry):
                final_geometry = union_geometry
                geometry_cleaned = geometry_cleaned or union_cleaned
                selected_surfaces = ordered
                geometry_action = "union"
                fusion_action = "multi_source_union"
            else:
                conflict_reasons.append("union_result_component_distance_exceeded")
                geometry_action = "select_primary"
                fusion_action = "primary_selected"
        else:
            conflict_reasons.append("source_geometry_gap_exceeded")
            geometry_action = "select_primary"
            fusion_action = "primary_selected"
    elif len(ordered) > 1 and _geometries_within_union_gap(ordered):
        union_geometry, union_cleaned = _clean_polygonal(unary_union([surface.geometry for surface in ordered]))
        if union_geometry is not None:
            final_geometry = union_geometry
            geometry_cleaned = geometry_cleaned or union_cleaned
            selected_surfaces = ordered
            geometry_action = "union_same_source"
            fusion_action = "single_source"

    final_sources = _ordered_sources(surface.source for surface in selected_surfaces)
    surface_sources = "|".join(final_sources)
    is_multi_source_merged = int(len(set(final_sources)) > 1 and geometry_action == "union")
    if surface_sources not in ALLOWED_SURFACE_SOURCES:
        conflict_reasons.append("surface_sources_out_of_domain")

    if primary.junction_type == "unknown":
        conflict_reasons.append("junction_type_unknown")

    conflict_state = "none"
    if conflict_reasons:
        conflict_state = "review_required"
    if primary.junction_type == "unknown" and len(set(sources_all)) > 1 and geometry_action != "union":
        conflict_state = "unresolved_review"

    if conflict_state == "unresolved_review":
        audit_row = _audit_row(
            surface_id="",
            group_id=group_id,
            mainnodeid=primary.mainnodeid,
            patch_id=primary.patch_id,
            kind_2=primary.kind_2,
            junction_type=primary.junction_type,
            surface_sources="",
            is_multi_source_merged=0,
            source_count=source_count,
            source_feature_ids=source_feature_ids,
            source_case_ids=source_case_ids,
            source_modules=source_modules,
            source_patch_ids=source_patch_ids,
            geometry_action="conflict_unpublished",
            fusion_action="conflict_unresolved",
            conflict_state=conflict_state,
            conflict_reason="|".join(_ordered_text(conflict_reasons)),
            selected_primary_source=primary.source,
            dropped_source_ids=_pipe_join(_source_id(surface) for surface in ordered),
            geometry_cleaned=geometry_cleaned,
            notes=_pipe_join(notes),
        )
        return FusionResult(
            surface_feature=None,
            audit_row=audit_row,
            conflict_feature={"properties": dict(audit_row), "geometry": final_geometry},
        )

    surface_id = _surface_id(primary)
    dropped_source_ids = _pipe_join(
        _source_id(surface)
        for surface in ordered
        if surface not in selected_surfaces
    )
    feature = {
        "properties": {
            "surface_id": surface_id,
            "mainnodeid": primary.mainnodeid,
            "patch_id": primary.patch_id,
            "junction_type": primary.junction_type,
            "kind_2": primary.kind_2,
            "surface_sources": surface_sources,
            "is_multi_source_merged": is_multi_source_merged,
        },
        "geometry": final_geometry,
    }
    audit_row = _audit_row(
        surface_id=surface_id,
        group_id=group_id,
        mainnodeid=primary.mainnodeid,
        patch_id=primary.patch_id,
        kind_2=primary.kind_2,
        junction_type=primary.junction_type,
        surface_sources=surface_sources,
        is_multi_source_merged=is_multi_source_merged,
        source_count=source_count,
        source_feature_ids=source_feature_ids,
        source_case_ids=source_case_ids,
        source_modules=source_modules,
        source_patch_ids=source_patch_ids,
        geometry_action=geometry_action,
        fusion_action=fusion_action,
        conflict_state=conflict_state,
        conflict_reason="|".join(_ordered_text(conflict_reasons)),
        selected_primary_source=primary.source,
        dropped_source_ids=dropped_source_ids,
        geometry_cleaned=geometry_cleaned,
        notes=_pipe_join(notes),
    )
    return FusionResult(surface_feature=feature, audit_row=audit_row)


def _group_key(surface: SourceSurface) -> tuple[str, ...]:
    if surface.mainnodeid:
        return ("mainnodeid", surface.mainnodeid)
    return ("source", surface.source, surface.source_feature_id)


def _group_id(key: tuple[str, ...]) -> str:
    return ":".join(key)


def _surface_id(surface: SourceSurface) -> str:
    if surface.mainnodeid:
        return f"JAS:{surface.mainnodeid}"
    return f"JAS:{surface.source}:{surface.source_feature_id}"


def _source_id(surface: SourceSurface) -> str:
    return f"{surface.source}:{surface.source_feature_id}"


def _surface_sort_key(surface: SourceSurface) -> tuple[int, int]:
    return (SOURCE_ORDER.index(surface.source), surface.source_index)


def _select_primary(surfaces: list[SourceSurface]) -> SourceSurface:
    source_set = {surface.source for surface in surfaces}
    kind_values = [surface.kind_2 for surface in surfaces if surface.kind_2 is not None]
    primary_kind = kind_values[0] if kind_values else None
    if SOURCE_T03 in source_set and SOURCE_T04 in source_set:
        if primary_kind in T03_KIND_VALUES:
            return _first_source(surfaces, SOURCE_T03)
        if primary_kind in T04_KIND_VALUES:
            return _first_source(surfaces, SOURCE_T04)
    for source in (SOURCE_T03, SOURCE_T04, SOURCE_T02_INPUT):
        if source in source_set:
            return _first_source(surfaces, source)
    return surfaces[0]


def _first_source(surfaces: list[SourceSurface], source: str) -> SourceSurface:
    return next(surface for surface in surfaces if surface.source == source)


def _geometries_within_union_gap(surfaces: list[SourceSurface]) -> bool:
    for index, left in enumerate(surfaces):
        for right in surfaces[index + 1 :]:
            if left.geometry.distance(right.geometry) > MULTI_SOURCE_UNION_MAX_GAP_M:
                return False
    return True


def _components_reasonable(geometry: BaseGeometry) -> bool:
    if not isinstance(geometry, MultiPolygon):
        return True
    components = list(geometry.geoms)
    for index, left in enumerate(components):
        for right in components[index + 1 :]:
            if left.distance(right) > MULTI_SOURCE_UNION_MAX_GAP_M:
                return False
    return True


def _clean_polygonal(geometry: BaseGeometry | None) -> tuple[BaseGeometry | None, bool]:
    if geometry is None or geometry.is_empty:
        return None, False
    cleaned = False
    candidate = geometry
    if not candidate.is_valid:
        candidate = make_valid(candidate)
        cleaned = True
    if isinstance(candidate, (Polygon, MultiPolygon)):
        return candidate, cleaned
    if isinstance(candidate, GeometryCollection):
        polygons = [
            item
            for item in candidate.geoms
            if isinstance(item, (Polygon, MultiPolygon)) and not item.is_empty
        ]
        if polygons:
            return unary_union(polygons), True
    return None, cleaned


def _ordered_sources(values: Iterable[str]) -> list[str]:
    present = set(values)
    return [source for source in SOURCE_ORDER if source in present]


def _ordered_text(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _pipe_join(values: Iterable[Any]) -> str:
    return "|".join(_ordered_text(values))


def _audit_row(**kwargs: Any) -> dict[str, Any]:
    return kwargs


def expected_junction_type_for_feature(properties: dict[str, Any]) -> str | None:
    source_text = str(properties.get("surface_sources") or "")
    kind_2 = properties.get("kind_2")
    try:
        kind_value = int(kind_2) if kind_2 not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if source_text == SOURCE_T02_INPUT:
        return "rcsd_intersection"
    for source in (SOURCE_T03, SOURCE_T04):
        if source in source_text:
            expected = JUNCTION_TYPE_BY_SOURCE_KIND.get((source, kind_value))
            if expected is not None:
                return expected
    return None
