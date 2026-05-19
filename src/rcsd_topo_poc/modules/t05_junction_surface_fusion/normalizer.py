from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature

from .models import (
    JUNCTION_TYPE_BY_SOURCE_KIND,
    SOURCE_T02_INPUT,
    SOURCE_T03,
    SOURCE_T04,
    SourceSurface,
)


NULL_TEXT_VALUES = {"", "0", "none", "null", "nan"}


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    mainnodeid: str | None
    kind_2: int | None
    patch_id: str | None


class NodeLookup:
    def __init__(self, records: Iterable[NodeRecord]) -> None:
        self.by_node_id: dict[str, NodeRecord] = {}
        self.by_mainnodeid: dict[str, NodeRecord] = {}
        for record in records:
            self.by_node_id.setdefault(record.node_id, record)
            if record.mainnodeid:
                self.by_mainnodeid.setdefault(record.mainnodeid, record)

    @classmethod
    def from_features(cls, features: Iterable[LayerFeature]) -> "NodeLookup":
        records: list[NodeRecord] = []
        for feature in features:
            props = feature.properties
            node_id = _normalize_id(_field(props, "id"))
            if node_id is None:
                continue
            mainnodeid = _normalize_id(_field(props, "mainnodeid"))
            records.append(
                NodeRecord(
                    node_id=node_id,
                    mainnodeid=mainnodeid,
                    kind_2=_coerce_int(_field(props, "kind_2")),
                    patch_id=_normalize_id(_first_field(props, ("patch_id", "patchid"))),
                )
            )
        return cls(records)

    @classmethod
    def empty(cls) -> "NodeLookup":
        return cls(())

    def resolve_mainnodeid(self, values: Iterable[Any]) -> str | None:
        for value in values:
            text = _normalize_id(value)
            if text is None:
                continue
            if text in self.by_mainnodeid:
                return text
            record = self.by_node_id.get(text)
            if record is not None:
                return record.mainnodeid or record.node_id
        return None

    def kind_2_for(self, mainnodeid: str | None) -> int | None:
        if mainnodeid is None:
            return None
        record = self.by_mainnodeid.get(mainnodeid) or self.by_node_id.get(mainnodeid)
        return None if record is None else record.kind_2

    def patch_id_for(self, mainnodeid: str | None) -> str | None:
        if mainnodeid is None:
            return None
        record = self.by_mainnodeid.get(mainnodeid) or self.by_node_id.get(mainnodeid)
        return None if record is None else record.patch_id


def normalize_t02_input(
    features: Iterable[LayerFeature],
    *,
    nodes: NodeLookup,
) -> tuple[list[SourceSurface], list[dict[str, Any]]]:
    surfaces: list[SourceSurface] = []
    skipped: list[dict[str, Any]] = []
    for index, feature in enumerate(features, start=1):
        props = feature.properties
        source_feature_id = _source_feature_id(props, index=index, source=SOURCE_T02_INPUT)
        geometry, cleaned, reason = _clean_polygonal_geometry(feature.geometry)
        if geometry is None:
            skipped.append(_skip_row(SOURCE_T02_INPUT, source_feature_id, None, reason))
            continue
        mainnodeid = _normalize_id(_field(props, "mainnodeid")) or nodes.resolve_mainnodeid(
            (_field(props, "mainnodeid"), _field(props, "nodeid"), _field(props, "node_id"))
        )
        if mainnodeid is None:
            skipped.append(
                _skip_row(SOURCE_T02_INPUT, source_feature_id, None, "semantic_junction_unanchored")
            )
            continue
        patch_id = _normalize_id(_first_field(props, ("patch_id", "patchid"))) or nodes.patch_id_for(mainnodeid)
        kind_2 = _coerce_int(_field(props, "kind_2")) or nodes.kind_2_for(mainnodeid)
        notes = _field_notes(
            geometry_cleaned=cleaned,
            mainnodeid=mainnodeid,
            patch_id=patch_id,
            kind_2=kind_2,
            junction_type="rcsd_intersection",
        )
        surfaces.append(
            SourceSurface(
                source=SOURCE_T02_INPUT,
                source_feature_id=source_feature_id,
                source_case_id=None,
                geometry=geometry,
                mainnodeid=mainnodeid,
                patch_id=patch_id,
                kind_2=kind_2,
                junction_type="rcsd_intersection",
                properties=dict(props),
                source_index=index,
                geometry_cleaned=cleaned,
                notes=tuple(notes),
            )
        )
    return surfaces, skipped


def normalize_t03_surfaces(
    features: Iterable[LayerFeature],
    *,
    nodes: NodeLookup,
) -> tuple[list[SourceSurface], list[dict[str, Any]]]:
    return _normalize_generated_surfaces(features, nodes=nodes, source=SOURCE_T03)


def normalize_t04_surfaces(
    features: Iterable[LayerFeature],
    *,
    nodes: NodeLookup,
) -> tuple[list[SourceSurface], list[dict[str, Any]]]:
    return _normalize_generated_surfaces(features, nodes=nodes, source=SOURCE_T04)


def _normalize_generated_surfaces(
    features: Iterable[LayerFeature],
    *,
    nodes: NodeLookup,
    source: str,
) -> tuple[list[SourceSurface], list[dict[str, Any]]]:
    surfaces: list[SourceSurface] = []
    skipped: list[dict[str, Any]] = []
    for index, feature in enumerate(features, start=1):
        props = feature.properties
        source_feature_id = _source_feature_id(props, index=index, source=source)
        source_case_id = _normalize_id(_first_field(props, ("case_id", "anchor_id", "mainnodeid")))
        accepted, reason = _formal_acceptance(source, props)
        if not accepted:
            skipped.append(_skip_row(source, source_feature_id, source_case_id, reason))
            continue
        geometry, cleaned, geometry_reason = _clean_polygonal_geometry(feature.geometry)
        if geometry is None:
            skipped.append(_skip_row(source, source_feature_id, source_case_id, geometry_reason))
            continue
        mainnodeid = _normalize_id(_field(props, "mainnodeid")) or nodes.resolve_mainnodeid(
            (
                _field(props, "mainnodeid"),
                _field(props, "case_id"),
                _field(props, "anchor_id"),
                _field(props, "representative_node_id"),
            )
        )
        if mainnodeid is None:
            skipped.append(_skip_row(source, source_feature_id, source_case_id, "semantic_junction_unanchored"))
            continue
        patch_id = _normalize_id(_first_field(props, ("patch_id", "patchid"))) or nodes.patch_id_for(mainnodeid)
        kind_2 = _coerce_int(_field(props, "kind_2")) or nodes.kind_2_for(mainnodeid)
        junction_type = JUNCTION_TYPE_BY_SOURCE_KIND.get((source, kind_2), "unknown")
        notes = _field_notes(
            geometry_cleaned=cleaned,
            mainnodeid=mainnodeid,
            patch_id=patch_id,
            kind_2=kind_2,
            junction_type=junction_type,
        )
        surfaces.append(
            SourceSurface(
                source=source,
                source_feature_id=source_feature_id,
                source_case_id=source_case_id,
                geometry=geometry,
                mainnodeid=mainnodeid,
                patch_id=patch_id,
                kind_2=kind_2,
                junction_type=junction_type,
                properties=dict(props),
                source_index=index,
                geometry_cleaned=cleaned,
                notes=tuple(notes),
            )
        )
    return surfaces, skipped


def _formal_acceptance(source: str, props: dict[str, Any]) -> tuple[bool, str]:
    if source == SOURCE_T03:
        for key in ("step7_state", "final_state", "acceptance_class"):
            value = _lower_text(_field(props, key))
            if value:
                return value == "accepted", f"{key}={value}"
        success = _field(props, "success")
        if success is not None:
            return _truthy(success), f"success={success}"
        return True, "t03_aggregate_contract_accepted"

    final_state = _lower_text(_first_field(props, ("final_state", "step7_state")))
    if final_state:
        return final_state == "accepted", f"final_state={final_state}"
    return False, "missing_t04_final_state"


def _clean_polygonal_geometry(geometry: BaseGeometry | None) -> tuple[BaseGeometry | None, bool, str]:
    if geometry is None or geometry.is_empty:
        return None, False, "empty_geometry"
    cleaned = False
    candidate = geometry
    if not candidate.is_valid:
        candidate = make_valid(candidate)
        cleaned = True
    polygonal = _polygonal_only(candidate)
    if polygonal is None or polygonal.is_empty:
        return None, cleaned, "non_polygon_geometry"
    if not polygonal.is_valid:
        polygonal = polygonal.buffer(0)
        cleaned = True
    polygonal = _polygonal_only(polygonal)
    if polygonal is None or polygonal.is_empty:
        return None, cleaned, "invalid_polygon_geometry"
    return polygonal, cleaned, "ok"


def _polygonal_only(geometry: BaseGeometry) -> BaseGeometry | None:
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = [
            item
            for item in geometry.geoms
            if isinstance(item, (Polygon, MultiPolygon)) and not item.is_empty
        ]
        if not polygons:
            return None
        return unary_union(polygons)
    return None


def _source_feature_id(props: dict[str, Any], *, index: int, source: str) -> str:
    keys = (
        "id",
        "intersection_id",
        "intersectionid",
        "fid",
        "objectid",
        "OBJECTID",
        "case_id",
        "anchor_id",
        "mainnodeid",
    )
    value = _first_field(props, keys)
    return _normalize_id(value) or f"{source}_{index}"


def _skip_row(source: str, source_feature_id: str, source_case_id: str | None, reason: str) -> dict[str, Any]:
    return {
        "source": source,
        "source_feature_id": source_feature_id,
        "source_case_id": source_case_id,
        "skip_reason": reason,
        "notes": reason,
    }


def _field(props: dict[str, Any], key: str) -> Any:
    if key in props:
        return props[key]
    lower_key = key.lower()
    for existing, value in props.items():
        if str(existing).lower() == lower_key:
            return value
    return None


def _first_field(props: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = _field(props, key)
        if _normalize_id(value) is not None:
            return value
    return None


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if text.lower() in NULL_TEXT_VALUES:
        return None
    return text


def _lower_text(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    return "" if text in NULL_TEXT_VALUES else text


def _coerce_int(value: Any) -> int | None:
    text = _normalize_id(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "accepted"}


def _field_notes(
    *,
    geometry_cleaned: bool,
    mainnodeid: str | None,
    patch_id: str | None,
    kind_2: int | None,
    junction_type: str,
) -> list[str]:
    notes: list[str] = []
    if geometry_cleaned:
        notes.append("geometry_cleaned")
    if mainnodeid is None:
        notes.append("mainnodeid_unresolved")
    if patch_id is None:
        notes.append("patch_id_unresolved")
    if kind_2 is None:
        notes.append("kind_2_unresolved")
    if junction_type == "unknown":
        notes.append("junction_type_unknown")
    return notes
