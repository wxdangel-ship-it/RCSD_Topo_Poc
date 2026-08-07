from __future__ import annotations

from pathlib import Path

import fiona
import pytest
from shapely.geometry import LineString, Point, Polygon, mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    CRSMismatchError,
    CityEvidenceStoreError,
    CityEvidenceStoreRegistry,
    CityStoreConflictError,
    DependencyField,
    EvidenceLayerSpec,
    EvidenceRole,
    JunctionQuery,
    ObjectRef,
    build_city_evidence_store,
    read_fiona_layer,
)


def _write_layer(
    path: Path,
    *,
    geometry_type: str,
    features: list[tuple[object, dict[str, object]]],
    crs: str = "EPSG:3857",
) -> None:
    properties: dict[str, str] = {}
    for _, values in features:
        for name, value in values.items():
            if isinstance(value, int):
                properties.setdefault(name, "int")
            elif isinstance(value, float):
                properties.setdefault(name, "float")
            else:
                properties.setdefault(name, "str")
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer=path.stem,
        schema={"geometry": geometry_type, "properties": properties},
        crs=crs,
    ) as sink:
        for geometry, values in features:
            sink.write(
                {
                    "type": "Feature",
                    "geometry": mapping(geometry),
                    "properties": values,
                }
            )


def _city_specs(tmp_path: Path) -> tuple[EvidenceLayerSpec, ...]:
    swsd = tmp_path / "swsd_junction.gpkg"
    drivezone = tmp_path / "drivezone.gpkg"
    rcsd_road = tmp_path / "rcsd_road.gpkg"
    rcsd_node = tmp_path / "rcsd_node.gpkg"
    _write_layer(
        swsd,
        geometry_type="Point",
        features=[(Point(0, 0), {"id": "J1", "kind": 4})],
    )
    _write_layer(
        drivezone,
        geometry_type="Polygon",
        features=[
            (
                Polygon([(-8, -8), (8, -8), (8, 8), (-8, 8), (-8, -8)]),
                {"id": "D1"},
            )
        ],
    )
    _write_layer(
        rcsd_road,
        geometry_type="LineString",
        features=[
            (
                LineString([(-5, 0), (5, 0)]),
                {"id": "R1", "end_node": "N1", "direction": 2},
            )
        ],
    )
    _write_layer(
        rcsd_node,
        geometry_type="Point",
        features=[(Point(100, 0), {"id": "N1", "kind": 1})],
    )
    return (
        EvidenceLayerSpec(
            path=swsd,
            role=EvidenceRole.SWSD_JUNCTION,
            attribute_fields=("kind",),
        ),
        EvidenceLayerSpec(path=drivezone, role=EvidenceRole.DRIVEZONE),
        EvidenceLayerSpec(
            path=rcsd_road,
            role=EvidenceRole.RCSD_ROAD,
            attribute_fields=("direction",),
            dependency_fields=(
                DependencyField("end_node", EvidenceRole.RCSD_NODE),
            ),
        ),
        EvidenceLayerSpec(
            path=rcsd_node,
            role=EvidenceRole.RCSD_NODE,
            attribute_fields=("kind",),
        ),
    )


def test_city_store_reads_each_layer_once_and_reuses_same_city(tmp_path: Path) -> None:
    specs = _city_specs(tmp_path)
    read_count = 0

    def counting_reader(spec: EvidenceLayerSpec):
        nonlocal read_count
        read_count += 1
        return read_fiona_layer(spec)

    registry = CityEvidenceStoreRegistry()
    first = registry.get_or_load(
        city_key="city:fixture",
        layer_specs=tuple(reversed(specs)),
        layer_reader=counting_reader,
    )
    second = registry.get_or_load(
        city_key="city:fixture",
        layer_specs=specs,
        layer_reader=counting_reader,
    )

    assert first is second
    assert registry.load_count("city:fixture") == 1
    assert read_count == 4
    assert first.manifest.gis_layer_read_count == 4
    assert first.manifest.input_source_file_count == 4
    assert first.object_count == 4


def test_spatial_window_does_not_truncate_directed_business_dependencies(
    tmp_path: Path,
) -> None:
    store = build_city_evidence_store(
        city_key="city:fixture",
        layer_specs=_city_specs(tmp_path),
    )
    query = JunctionQuery(
        case_key="T03:fixture",
        semantic_junction_id="J1",
        root_refs=(ObjectRef(EvidenceRole.SWSD_JUNCTION, "J1"),),
        search_bounds=(-10.0, -10.0, 10.0, 10.0),
        spatial_candidate_roles=(EvidenceRole.RCSD_ROAD, EvidenceRole.DRIVEZONE),
    )
    result = store.query(query)

    road_ref = ObjectRef(EvidenceRole.RCSD_ROAD, "R1")
    outside_node_ref = ObjectRef(EvidenceRole.RCSD_NODE, "N1")
    assert road_ref in result.spatial_seed_refs
    assert outside_node_ref not in result.spatial_seed_refs
    assert outside_node_ref in result.dynamic_dependency_refs
    assert result.object_refs == tuple(
        sorted(result.object_refs, key=lambda ref: (ref.role.value, ref.object_id))
    )
    assert result.objects[result.object_refs.index(outside_node_ref)] is store.get(
        outside_node_ref
    )
    assert result.objects_for_role(EvidenceRole.RCSD_NODE) == (
        store.get(outside_node_ref),
    )


def test_query_result_is_deterministic_for_role_order(tmp_path: Path) -> None:
    store = build_city_evidence_store(
        city_key="city:fixture",
        layer_specs=_city_specs(tmp_path),
    )
    common = {
        "case_key": "T03:fixture",
        "semantic_junction_id": "J1",
        "root_refs": (ObjectRef(EvidenceRole.SWSD_JUNCTION, "J1"),),
        "search_bounds": (-10.0, -10.0, 10.0, 10.0),
    }
    first = store.query(
        JunctionQuery(
            **common,
            spatial_candidate_roles=(
                EvidenceRole.RCSD_ROAD,
                EvidenceRole.DRIVEZONE,
            ),
        )
    )
    second = store.query(
        JunctionQuery(
            **common,
            spatial_candidate_roles=(
                EvidenceRole.DRIVEZONE,
                EvidenceRole.RCSD_ROAD,
            ),
        )
    )
    assert first.object_refs == second.object_refs
    assert first.spatial_seed_refs == second.spatial_seed_refs
    assert first.role_spans == second.role_spans


def test_city_store_blocks_crs_mismatch_without_reprojection(tmp_path: Path) -> None:
    path = tmp_path / "wgs84.gpkg"
    _write_layer(
        path,
        geometry_type="Point",
        features=[(Point(114.0, 30.0), {"id": "J1"})],
        crs="EPSG:4326",
    )
    with pytest.raises(CRSMismatchError, match="CRS mismatch"):
        build_city_evidence_store(
            city_key="city:wgs84",
            layer_specs=(
                EvidenceLayerSpec(path=path, role=EvidenceRole.SWSD_JUNCTION),
            ),
            expected_crs="EPSG:3857",
        )


def test_invalid_geometry_is_recorded_but_never_silently_fixed(tmp_path: Path) -> None:
    path = tmp_path / "invalid_drivezone.gpkg"
    invalid = Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])
    assert not invalid.is_valid
    _write_layer(
        path,
        geometry_type="Polygon",
        features=[(invalid, {"id": "D1"})],
    )
    store = build_city_evidence_store(
        city_key="city:invalid",
        layer_specs=(
            EvidenceLayerSpec(path=path, role=EvidenceRole.DRIVEZONE),
        ),
    )
    stored = store.get(ObjectRef(EvidenceRole.DRIVEZONE, "D1"))
    assert stored.geometry is not None and not stored.geometry.is_valid
    assert store.manifest.layers[0].invalid_geometry_count == 1


def test_required_missing_dependency_and_terminal_attribute_are_blocked(
    tmp_path: Path,
) -> None:
    road = tmp_path / "road.gpkg"
    _write_layer(
        road,
        geometry_type="LineString",
        features=[
            (
                LineString([(0, 0), (1, 0)]),
                {"id": "R1", "end_node": "MISSING", "final_status": "SUCCESS"},
            )
        ],
    )
    with pytest.raises(CityEvidenceStoreError, match="target is missing"):
        build_city_evidence_store(
            city_key="city:missing",
            layer_specs=(
                EvidenceLayerSpec(
                    path=road,
                    role=EvidenceRole.RCSD_ROAD,
                    dependency_fields=(
                        DependencyField("end_node", EvidenceRole.RCSD_NODE),
                    ),
                ),
            ),
        )
    with pytest.raises(CityEvidenceStoreError, match="terminal/label"):
        build_city_evidence_store(
            city_key="city:leak",
            layer_specs=(
                EvidenceLayerSpec(
                    path=road,
                    role=EvidenceRole.RCSD_ROAD,
                    attribute_fields=("final_status",),
                ),
            ),
        )


def test_registry_blocks_changed_contract_for_loaded_city(tmp_path: Path) -> None:
    specs = _city_specs(tmp_path)
    registry = CityEvidenceStoreRegistry()
    registry.get_or_load(city_key="city:fixture", layer_specs=specs)
    with pytest.raises(CityStoreConflictError, match="already loaded"):
        registry.get_or_load(
            city_key="city:fixture",
            layer_specs=specs,
            expected_crs="EPSG:4326",
        )
