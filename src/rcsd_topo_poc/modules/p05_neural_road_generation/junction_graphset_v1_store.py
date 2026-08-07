from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import fiona
from pyproj import CRS
from shapely import STRtree
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry


class CityEvidenceStoreError(ValueError):
    """Base error for an invalid or inconsistent city evidence store."""


class CRSMismatchError(CityEvidenceStoreError):
    """Raised when a GIS layer is missing the required CRS or uses another CRS."""


class CityStoreConflictError(CityEvidenceStoreError):
    """Raised when one city key is reused with a different immutable input set."""


class EvidenceRole(str, Enum):
    SWSD_JUNCTION = "SWSD_JUNCTION"
    SWSD_NODE = "SWSD_NODE"
    SWSD_ROAD = "SWSD_ROAD"
    DRIVEZONE = "DRIVEZONE"
    RCSD_INTERSECTION = "RCSD_INTERSECTION"
    RCSD_NODE = "RCSD_NODE"
    RCSD_ROAD = "RCSD_ROAD"
    ROAD_SURFACE = "ROAD_SURFACE"
    DIVSTRIP = "DIVSTRIP"


@dataclass(frozen=True, order=True)
class ObjectRef:
    role: EvidenceRole
    object_id: str

    def __post_init__(self) -> None:
        if not self.object_id.strip():
            raise CityEvidenceStoreError("ObjectRef.object_id must not be blank")

    @property
    def key(self) -> str:
        return f"{self.role.value}:{self.object_id}"


@dataclass(frozen=True)
class DependencyField:
    field_name: str
    target_role: EvidenceRole
    many: bool = False
    separator: str = "|"
    required: bool = True

    def __post_init__(self) -> None:
        if not self.field_name.strip():
            raise CityEvidenceStoreError("dependency field_name must not be blank")
        if self.many and not self.separator:
            raise CityEvidenceStoreError("multi-value dependency requires a separator")


@dataclass(frozen=True)
class EvidenceLayerSpec:
    path: Path
    role: EvidenceRole
    id_field: str = "id"
    layer: str | None = None
    attribute_fields: tuple[str, ...] = ()
    dependency_fields: tuple[DependencyField, ...] = ()

    def __post_init__(self) -> None:
        if not self.id_field.strip():
            raise CityEvidenceStoreError("id_field must not be blank")
        if len(set(self.attribute_fields)) != len(self.attribute_fields):
            raise CityEvidenceStoreError("attribute_fields contains duplicates")
        dependency_names = tuple(field.field_name for field in self.dependency_fields)
        if len(set(dependency_names)) != len(dependency_names):
            raise CityEvidenceStoreError("dependency_fields contains duplicates")


@dataclass(frozen=True)
class DependencyLink:
    source: ObjectRef
    target: ObjectRef
    relation: str

    def __post_init__(self) -> None:
        if not self.relation.strip():
            raise CityEvidenceStoreError("dependency relation must not be blank")


@dataclass(frozen=True)
class EvidenceObject:
    ref: ObjectRef
    geometry: BaseGeometry | None
    attributes: tuple[tuple[str, Any], ...]
    source_path: str
    source_layer: str
    source_feature_index: int

    def attribute(self, name: str, default: Any = None) -> Any:
        return dict(self.attributes).get(name, default)


@dataclass(frozen=True)
class LayerReadResult:
    crs: CRS
    layer_name: str
    objects: tuple[EvidenceObject, ...]
    dependency_links: tuple[DependencyLink, ...]
    evidence_sha256: str


@dataclass(frozen=True)
class LayerManifest:
    role: str
    source_path: str
    source_layer: str
    evidence_sha256: str
    id_field: str
    crs: str
    feature_count: int
    invalid_geometry_count: int
    empty_geometry_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "source_path": self.source_path,
            "source_layer": self.source_layer,
            "evidence_sha256": self.evidence_sha256,
            "id_field": self.id_field,
            "crs": self.crs,
            "feature_count": self.feature_count,
            "invalid_geometry_count": self.invalid_geometry_count,
            "empty_geometry_count": self.empty_geometry_count,
        }


@dataclass(frozen=True)
class CityEvidenceManifest:
    schema_version: str
    city_key: str
    crs: str
    layers: tuple[LayerManifest, ...]
    object_count: int
    dependency_count: int
    unresolved_optional_dependency_count: int
    gis_layer_read_count: int
    input_source_file_count: int
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "city_key": self.city_key,
            "crs": self.crs,
            "layers": [layer.to_dict() for layer in self.layers],
            "object_count": self.object_count,
            "dependency_count": self.dependency_count,
            "unresolved_optional_dependency_count": (
                self.unresolved_optional_dependency_count
            ),
            "gis_layer_read_count": self.gis_layer_read_count,
            "input_source_file_count": self.input_source_file_count,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class JunctionQuery:
    case_key: str
    semantic_junction_id: str
    root_refs: tuple[ObjectRef, ...]
    search_bounds: tuple[float, float, float, float] | None = None
    spatial_candidate_roles: tuple[EvidenceRole, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_key.strip() or not self.semantic_junction_id.strip():
            raise CityEvidenceStoreError(
                "JunctionQuery requires case_key and semantic_junction_id"
            )
        if not self.root_refs:
            raise CityEvidenceStoreError("JunctionQuery requires at least one root ref")
        if len(set(self.root_refs)) != len(self.root_refs):
            raise CityEvidenceStoreError("JunctionQuery root_refs contains duplicates")
        if self.search_bounds is not None:
            if len(self.search_bounds) != 4 or not all(
                math.isfinite(value) for value in self.search_bounds
            ):
                raise CityEvidenceStoreError("search_bounds must contain four finite values")
            min_x, min_y, max_x, max_y = self.search_bounds
            if min_x > max_x or min_y > max_y:
                raise CityEvidenceStoreError("search_bounds is inverted")

    @property
    def junction_key(self) -> str:
        return f"{self.case_key}|{self.semantic_junction_id}"


@dataclass(frozen=True)
class JunctionQuerySlice:
    junction_key: str
    case_key: str
    semantic_junction_id: str
    manifest_fingerprint: str
    root_refs: tuple[ObjectRef, ...]
    spatial_seed_refs: tuple[ObjectRef, ...]
    dynamic_dependency_refs: tuple[ObjectRef, ...]
    objects: tuple[EvidenceObject, ...]
    role_spans: tuple[tuple[EvidenceRole, int, int], ...]

    @property
    def object_refs(self) -> tuple[ObjectRef, ...]:
        return tuple(obj.ref for obj in self.objects)

    def objects_for_role(self, role: EvidenceRole) -> tuple[EvidenceObject, ...]:
        for span_role, start, end in self.role_spans:
            if span_role == role:
                return self.objects[start:end]
        return ()


@dataclass(frozen=True)
class _RoleSpatialIndex:
    refs: tuple[ObjectRef, ...]
    tree: STRtree


class CityEvidenceStore:
    """Immutable city store whose query slices reference, rather than copy, objects."""

    def __init__(
        self,
        *,
        manifest: CityEvidenceManifest,
        objects: Mapping[ObjectRef, EvidenceObject],
        outgoing_dependencies: Mapping[ObjectRef, Sequence[ObjectRef]],
    ) -> None:
        self._manifest = manifest
        self._objects = dict(objects)
        self._outgoing_dependencies = {
            source: tuple(sorted(set(targets)))
            for source, targets in outgoing_dependencies.items()
        }
        spatial_indices: dict[EvidenceRole, _RoleSpatialIndex] = {}
        for role in EvidenceRole:
            role_objects = tuple(
                obj
                for ref, obj in sorted(self._objects.items())
                if ref.role == role
                and obj.geometry is not None
                and not obj.geometry.is_empty
            )
            if role_objects:
                spatial_indices[role] = _RoleSpatialIndex(
                    refs=tuple(obj.ref for obj in role_objects),
                    tree=STRtree(tuple(obj.geometry for obj in role_objects)),
                )
        self._spatial_indices = spatial_indices

    @property
    def manifest(self) -> CityEvidenceManifest:
        return self._manifest

    @property
    def object_count(self) -> int:
        return len(self._objects)

    def get(self, ref: ObjectRef) -> EvidenceObject:
        try:
            return self._objects[ref]
        except KeyError as error:
            raise CityEvidenceStoreError(f"unknown object ref: {ref.key}") from error

    def query(self, query: JunctionQuery) -> JunctionQuerySlice:
        missing_roots = tuple(ref for ref in query.root_refs if ref not in self._objects)
        if missing_roots:
            raise CityEvidenceStoreError(
                "query root refs are missing: "
                + ", ".join(ref.key for ref in missing_roots)
            )

        spatial_seed_refs: set[ObjectRef] = set()
        if query.search_bounds is not None:
            window = box(*query.search_bounds)
            for role in sorted(set(query.spatial_candidate_roles), key=lambda item: item.value):
                role_index = self._spatial_indices.get(role)
                if role_index is None:
                    continue
                for index in role_index.tree.query(window):
                    spatial_seed_refs.add(role_index.refs[int(index)])

        seen: set[ObjectRef] = set(query.root_refs) | spatial_seed_refs
        frontier = sorted(seen)
        while frontier:
            current = frontier.pop(0)
            for target in self._outgoing_dependencies.get(current, ()):
                if target not in seen:
                    seen.add(target)
                    frontier.append(target)
            frontier.sort()

        ordered_refs = tuple(sorted(seen, key=lambda ref: (ref.role.value, ref.object_id)))
        objects = tuple(self._objects[ref] for ref in ordered_refs)
        role_spans: list[tuple[EvidenceRole, int, int]] = []
        start = 0
        while start < len(objects):
            role = objects[start].ref.role
            end = start + 1
            while end < len(objects) and objects[end].ref.role == role:
                end += 1
            role_spans.append((role, start, end))
            start = end
        return JunctionQuerySlice(
            junction_key=query.junction_key,
            case_key=query.case_key,
            semantic_junction_id=query.semantic_junction_id,
            manifest_fingerprint=self._manifest.fingerprint,
            root_refs=tuple(sorted(query.root_refs)),
            spatial_seed_refs=tuple(
                sorted(spatial_seed_refs, key=lambda ref: (ref.role.value, ref.object_id))
            ),
            dynamic_dependency_refs=ordered_refs,
            objects=objects,
            role_spans=tuple(role_spans),
        )


LayerReader = Callable[[EvidenceLayerSpec], LayerReadResult]

_FORBIDDEN_ATTRIBUTE_TOKENS = (
    "label",
    "truth",
    "preferred",
    "acceptable",
    "selected",
    "status",
    "split",
    "fold",
    "family",
    "route",
    "t03",
    "t04",
    "t05",
)


def _normalize_object_id(value: Any) -> str:
    if value is None or isinstance(value, bool):
        raise CityEvidenceStoreError(f"invalid object ID: {value!r}")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise CityEvidenceStoreError(f"invalid floating object ID: {value!r}")
        value = int(value)
    normalized = str(value).strip()
    if not normalized:
        raise CityEvidenceStoreError("object ID must not be blank")
    return normalized


def _dependency_values(value: Any, field: DependencyField) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if field.many:
        raw_values: Iterable[Any]
        if isinstance(value, str):
            raw_values = value.split(field.separator)
        elif isinstance(value, (list, tuple)):
            raw_values = value
        else:
            raw_values = (value,)
    else:
        raw_values = (value,)
    normalized = tuple(
        _normalize_object_id(item)
        for item in raw_values
        if str(item).strip()
    )
    return tuple(dict.fromkeys(normalized))


def read_fiona_layer(spec: EvidenceLayerSpec) -> LayerReadResult:
    path = Path(spec.path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    unsafe_attribute_fields = tuple(
        field_name
        for field_name in spec.attribute_fields
        if any(token in field_name.lower() for token in _FORBIDDEN_ATTRIBUTE_TOKENS)
    )
    if unsafe_attribute_fields:
        raise CityEvidenceStoreError(
            f"terminal/label fields cannot enter inference store: {unsafe_attribute_fields}"
        )
    objects: list[EvidenceObject] = []
    dependencies: list[DependencyLink] = []
    open_kwargs: dict[str, Any] = {}
    if spec.layer is not None:
        open_kwargs["layer"] = spec.layer
    with fiona.open(path, **open_kwargs) as source:
        if source.crs_wkt:
            layer_crs = CRS.from_wkt(source.crs_wkt)
        elif source.crs:
            layer_crs = CRS.from_user_input(source.crs)
        else:
            raise CRSMismatchError(f"GIS layer has no CRS: {path}")
        source_layer = str(source.name)
        for feature_index, feature in enumerate(source):
            properties = dict(feature.get("properties") or {})
            if spec.id_field not in properties:
                raise CityEvidenceStoreError(
                    f"missing {spec.id_field!r} in {path}:{source_layer} row {feature_index}"
                )
            ref = ObjectRef(
                role=spec.role,
                object_id=_normalize_object_id(properties[spec.id_field]),
            )
            raw_geometry = feature.get("geometry")
            geometry = shape(raw_geometry) if raw_geometry else None
            attributes = tuple(
                (field_name, properties.get(field_name))
                for field_name in sorted(spec.attribute_fields)
            )
            objects.append(
                EvidenceObject(
                    ref=ref,
                    geometry=geometry,
                    attributes=attributes,
                    source_path=str(path),
                    source_layer=source_layer,
                    source_feature_index=feature_index,
                )
            )
            for dependency_field in spec.dependency_fields:
                for object_id in _dependency_values(
                    properties.get(dependency_field.field_name), dependency_field
                ):
                    dependencies.append(
                        DependencyLink(
                            source=ref,
                            target=ObjectRef(dependency_field.target_role, object_id),
                            relation=dependency_field.field_name,
                        )
                    )
    normalized_objects = tuple(objects)
    normalized_dependencies = tuple(dependencies)
    evidence_digest = hashlib.sha256()
    evidence_digest.update(_crs_identifier(layer_crs).encode("utf-8"))
    evidence_digest.update(b"\n")
    evidence_digest.update(source_layer.encode("utf-8"))
    evidence_digest.update(b"\n")
    for obj in sorted(normalized_objects, key=lambda item: item.ref):
        geometry_wkb = obj.geometry.wkb_hex if obj.geometry is not None else None
        row_payload = {
            "ref": obj.ref.key,
            "geometry_wkb": geometry_wkb,
            "attributes": list(obj.attributes),
        }
        evidence_digest.update(
            json.dumps(
                row_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        evidence_digest.update(b"\n")
    for dependency in sorted(
        normalized_dependencies,
        key=lambda item: (item.source, item.target, item.relation),
    ):
        evidence_digest.update(
            f"{dependency.source.key}|{dependency.relation}|{dependency.target.key}\n".encode(
                "utf-8"
            )
        )
    return LayerReadResult(
        crs=layer_crs,
        layer_name=source_layer,
        objects=normalized_objects,
        dependency_links=normalized_dependencies,
        evidence_sha256=evidence_digest.hexdigest(),
    )


def _crs_identifier(crs: CRS) -> str:
    authority = crs.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_wkt()


def _manifest_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_city_evidence_store(
    *,
    city_key: str,
    layer_specs: Sequence[EvidenceLayerSpec],
    expected_crs: str | CRS = "EPSG:3857",
    static_dependency_links: Sequence[DependencyLink] = (),
    layer_reader: LayerReader = read_fiona_layer,
) -> CityEvidenceStore:
    if not city_key.strip():
        raise CityEvidenceStoreError("city_key must not be blank")
    if not layer_specs:
        raise CityEvidenceStoreError("at least one GIS layer is required")
    target_crs = CRS.from_user_input(expected_crs)
    sorted_specs = tuple(
        sorted(
            layer_specs,
            key=lambda spec: (
                spec.role.value,
                str(Path(spec.path).resolve()),
                spec.layer or "",
            ),
        )
    )
    spec_keys = tuple(
        (spec.role, str(Path(spec.path).resolve()), spec.layer or "")
        for spec in sorted_specs
    )
    if len(set(spec_keys)) != len(spec_keys):
        raise CityEvidenceStoreError("duplicate layer specification")

    source_paths: set[Path] = set()
    objects: dict[ObjectRef, EvidenceObject] = {}
    links: list[DependencyLink] = list(static_dependency_links)
    layer_manifests: list[LayerManifest] = []
    dependency_required: dict[tuple[ObjectRef, ObjectRef, str], bool] = {}
    for spec in sorted_specs:
        path = Path(spec.path).resolve()
        source_paths.add(path)
        result = layer_reader(spec)
        if not result.crs.equals(target_crs):
            raise CRSMismatchError(
                f"CRS mismatch for {path}:{result.layer_name}: "
                f"expected {_crs_identifier(target_crs)}, got {_crs_identifier(result.crs)}"
            )
        for obj in result.objects:
            if obj.ref in objects:
                raise CityEvidenceStoreError(f"duplicate object ref: {obj.ref.key}")
            objects[obj.ref] = obj
        links.extend(result.dependency_links)
        required_by_field = {
            field.field_name: field.required for field in spec.dependency_fields
        }
        for link in result.dependency_links:
            dependency_required[(link.source, link.target, link.relation)] = (
                required_by_field[link.relation]
            )
        invalid_count = sum(
            obj.geometry is not None
            and not obj.geometry.is_empty
            and not obj.geometry.is_valid
            for obj in result.objects
        )
        empty_count = sum(
            obj.geometry is None or obj.geometry.is_empty for obj in result.objects
        )
        layer_manifests.append(
            LayerManifest(
                role=spec.role.value,
                source_path=str(path),
                source_layer=result.layer_name,
                evidence_sha256=result.evidence_sha256,
                id_field=spec.id_field,
                crs=_crs_identifier(result.crs),
                feature_count=len(result.objects),
                invalid_geometry_count=invalid_count,
                empty_geometry_count=empty_count,
            )
        )

    outgoing: dict[ObjectRef, list[ObjectRef]] = {}
    unresolved_optional = 0
    for link in sorted(set(links), key=lambda item: (item.source, item.target, item.relation)):
        if link.source not in objects:
            raise CityEvidenceStoreError(
                f"dependency source is missing: {link.source.key}"
            )
        if link.target not in objects:
            required = dependency_required.get(
                (link.source, link.target, link.relation), True
            )
            if required:
                raise CityEvidenceStoreError(
                    f"required dependency target is missing: {link.target.key}"
                )
            unresolved_optional += 1
            continue
        outgoing.setdefault(link.source, []).append(link.target)

    manifest_payload = {
        "schema_version": "p05-junction-graphset-v1-city-store-v1",
        "city_key": city_key,
        "crs": _crs_identifier(target_crs),
        "layers": [manifest.to_dict() for manifest in layer_manifests],
        "object_count": len(objects),
        "dependency_count": sum(len(targets) for targets in outgoing.values()),
        "unresolved_optional_dependency_count": unresolved_optional,
        "gis_layer_read_count": len(sorted_specs),
        "input_source_file_count": len(source_paths),
    }
    manifest = CityEvidenceManifest(
        schema_version=str(manifest_payload["schema_version"]),
        city_key=city_key,
        crs=_crs_identifier(target_crs),
        layers=tuple(layer_manifests),
        object_count=len(objects),
        dependency_count=sum(len(targets) for targets in outgoing.values()),
        unresolved_optional_dependency_count=unresolved_optional,
        gis_layer_read_count=len(sorted_specs),
        input_source_file_count=len(source_paths),
        fingerprint=_manifest_fingerprint(manifest_payload),
    )
    return CityEvidenceStore(
        manifest=manifest,
        objects=objects,
        outgoing_dependencies=outgoing,
    )


def _layer_spec_request_payload(spec: EvidenceLayerSpec) -> dict[str, Any]:
    path = Path(spec.path).resolve()
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "role": spec.role.value,
        "id_field": spec.id_field,
        "layer": spec.layer,
        "attribute_fields": sorted(spec.attribute_fields),
        "dependency_fields": [
            {
                "field_name": field.field_name,
                "target_role": field.target_role.value,
                "many": field.many,
                "separator": field.separator,
                "required": field.required,
            }
            for field in sorted(
                spec.dependency_fields,
                key=lambda item: (item.field_name, item.target_role.value),
            )
        ],
    }


class CityEvidenceStoreRegistry:
    """Per-process immutable cache that prevents reparsing one city."""

    def __init__(self) -> None:
        self._stores: dict[str, tuple[str, CityEvidenceStore]] = {}
        self._load_counts: dict[str, int] = {}

    def get_or_load(
        self,
        *,
        city_key: str,
        layer_specs: Sequence[EvidenceLayerSpec],
        expected_crs: str | CRS = "EPSG:3857",
        static_dependency_links: Sequence[DependencyLink] = (),
        layer_reader: LayerReader = read_fiona_layer,
    ) -> CityEvidenceStore:
        request_payload = {
            "city_key": city_key,
            "expected_crs": _crs_identifier(CRS.from_user_input(expected_crs)),
            "layers": sorted(
                (_layer_spec_request_payload(spec) for spec in layer_specs),
                key=lambda item: (item["role"], item["path"], item["layer"] or ""),
            ),
            "static_dependency_links": [
                {
                    "source": link.source.key,
                    "target": link.target.key,
                    "relation": link.relation,
                }
                for link in sorted(
                    static_dependency_links,
                    key=lambda item: (item.source, item.target, item.relation),
                )
            ],
        }
        request_signature = _manifest_fingerprint(request_payload)
        existing = self._stores.get(city_key)
        if existing is not None:
            existing_signature, store = existing
            if existing_signature != request_signature:
                raise CityStoreConflictError(
                    f"city {city_key!r} was already loaded from another immutable input set"
                )
            return store
        store = build_city_evidence_store(
            city_key=city_key,
            layer_specs=layer_specs,
            expected_crs=expected_crs,
            static_dependency_links=static_dependency_links,
            layer_reader=layer_reader,
        )
        self._stores[city_key] = (request_signature, store)
        self._load_counts[city_key] = self._load_counts.get(city_key, 0) + 1
        return store

    def load_count(self, city_key: str) -> int:
        return self._load_counts.get(city_key, 0)
