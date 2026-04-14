from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import fiona
import pytest
from shapely.geometry import GeometryCollection, LineString, Point, box, shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_divmerge_virtual_polygon import (
    _analyze_divstrip_context,
    _build_local_surface_clip_geometry,
    _clip_simple_event_span_window_by_divstrip_context,
    _cover_check,
    _chain_candidates_from_topology,
    _evaluate_primary_rcsdnode_tolerance,
    _refine_complex_event_span_window_by_divstrip_context,
    _pick_reference_s,
    _resolve_parallel_centerline,
    _resolve_operational_kind_2,
    run_t02_stage4_divmerge_virtual_polygon,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import ParsedNode, ParsedRoad


def _load_vector_doc(path: Path) -> dict:
    with fiona.open(path) as src:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": dict(feature["properties"]),
                    "geometry": feature["geometry"],
                }
                for feature in src
            ],
        }


def _write_fixture(
    tmp_path: Path,
    *,
    kind_2: int,
    kind: int | None = None,
    divstrip_mode: str = "nearby_single",
    rcsdroad_outside_drivezone: bool = False,
    rcsdnode_outside_drivezone: bool = False,
    main_rcsdnode_geometry: Point | None = None,
    main_rcsdnode_id: str = "100",
    main_rcsdnode_mainnodeid: str | None = "100",
    extra_node_features: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    node_features = [
            {
                "properties": {
                    "id": "100",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind": kind,
                    "kind_2": kind_2,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "101",
                    "mainnodeid": "100",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind": kind,
                    "kind_2": kind_2,
                    "grade_2": 1,
                },
                "geometry": Point(6.0, 2.0),
            },
    ]
    if extra_node_features:
        node_features.extend(extra_node_features)
    write_vector(nodes_path, node_features, crs_text="EPSG:3857")
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east", "snodeid": "100", "enodeid": "400", "direction": 2}, "geometry": LineString([(0.0, 0.0), (55.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {
                "properties": {"name": "dz"},
                "geometry": unary_union([box(-12.0, -70.0, 12.0, 70.0), box(0.0, -12.0, 75.0, 12.0), box(-25.0, -8.0, 0.0, 8.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )

    if divstrip_mode == "nearby_single":
        divstrip_geometries = [box(18.0, -4.0, 30.0, 4.0)]
    elif divstrip_mode == "road_near_seed_far":
        divstrip_geometries = [box(36.0, -4.0, 48.0, 4.0)]
    elif divstrip_mode == "not_nearby":
        divstrip_geometries = [box(68.0, 42.0, 78.0, 52.0)]
    elif divstrip_mode == "ambiguous_two_nearby":
        divstrip_geometries = [box(14.0, -8.0, 20.0, -2.0), box(24.0, 2.0, 30.0, 8.0)]
    else:
        raise ValueError(f"Unsupported divstrip_mode: {divstrip_mode}")
    write_vector(
        divstripzone_path,
        [{"properties": {"id": f"dz_{index}"}, "geometry": geometry} for index, geometry in enumerate(divstrip_geometries)],
        crs_text="EPSG:3857",
    )

    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
            {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    rcsdnode_features = [
        {
            "properties": {"id": main_rcsdnode_id, "mainnodeid": main_rcsdnode_mainnodeid},
            "geometry": main_rcsdnode_geometry or Point(0.0, 0.0),
        },
        {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
        {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
        {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(45.0, 0.0)},
    ]
    if rcsdroad_outside_drivezone:
        rcsdroad_path = tmp_path / "rcsdroad_outside.gpkg"
        write_vector(
            rcsdroad_path,
            [
                {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 155.0)])},
                {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
                {"properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
            ],
            crs_text="EPSG:3857",
        )
        rcsdnode_features[1] = {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 155.0)}
    elif rcsdnode_outside_drivezone:
        rcsdnode_features[1] = {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 155.0)}
    write_vector(rcsdnode_path, rcsdnode_features, crs_text="EPSG:3857")

    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "divstripzone_path": divstripzone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
        "divstrip_union": unary_union(divstrip_geometries),
    }


def _write_multibranch_fixture(tmp_path: Path, *, kind_2: int) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"

    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": kind_2, "grade_2": 1}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "101", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": kind_2, "grade_2": 1}, "geometry": Point(6.0, 2.0)},
        ],
        crs_text="EPSG:3857",
    )
    side_specs = [
        ("branch_east", (0.0, 0.0), (50.0, 0.0), "100", "401"),
        ("branch_northeast", (0.0, 0.0), (30.0, 52.0), "100", "402"),
        ("branch_southeast", (0.0, 0.0), (30.0, -52.0), "100", "403"),
    ]
    roads = [
        {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
        {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
    ]
    rcsd_roads = [
        {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
        {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
    ]
    rcsd_nodes = [
        {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
        {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
        {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
    ]
    for branch_id, start, end, start_node, end_node in side_specs:
        road_id = branch_id
        if kind_2 == 16:
            road_props = {"id": road_id, "snodeid": start_node, "enodeid": end_node, "direction": 2}
            rc_props = {"id": f"rc_{road_id}", "snodeid": start_node, "enodeid": f"9{end_node}", "direction": 2}
            rc_end = end
        else:
            road_props = {"id": road_id, "snodeid": end_node, "enodeid": start_node, "direction": 2}
            rc_props = {"id": f"rc_{road_id}", "snodeid": f"9{end_node}", "enodeid": start_node, "direction": 2}
            rc_end = end
        roads.append({"properties": road_props, "geometry": LineString([start, end])})
        rcsd_roads.append({"properties": rc_props, "geometry": LineString([start, rc_end])})
        rcsd_nodes.append({"properties": {"id": f"9{end_node}", "mainnodeid": None}, "geometry": Point(*end)})
    write_vector(roads_path, roads, crs_text="EPSG:3857")
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": unary_union([box(-12.0, -75.0, 12.0, 75.0), box(0.0, -20.0, 70.0, 20.0), box(0.0, 0.0, 45.0, 65.0), box(0.0, -65.0, 45.0, 0.0)])}],
        crs_text="EPSG:3857",
    )
    write_vector(
        divstripzone_path,
        [
            {
                "properties": {"id": "divstrip_multi"},
                "geometry": box(10.0, -34.0, 36.0, 4.0) if kind_2 == 8 else box(10.0, -4.0, 36.0, 34.0),
            }
        ],
        crs_text="EPSG:3857",
    )
    write_vector(rcsdroad_path, rcsd_roads, crs_text="EPSG:3857")
    write_vector(rcsdnode_path, rcsd_nodes, crs_text="EPSG:3857")
    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "divstripzone_path": divstripzone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def _write_reverse_tip_fixture(tmp_path: Path) -> dict[str, Path]:
    nodes_path = tmp_path / "nodes.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    drivezone_path = tmp_path / "drivezone.gpkg"
    divstripzone_path = tmp_path / "divstripzone.gpkg"
    rcsdroad_path = tmp_path / "rcsdroad.gpkg"
    rcsdnode_path = tmp_path / "rcsdnode.gpkg"
    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "101", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1}, "geometry": Point(6.0, 2.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "road_north", "snodeid": "100", "enodeid": "200", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 60.0)])},
            {"properties": {"id": "road_south", "snodeid": "300", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -60.0), (0.0, 0.0)])},
            {"properties": {"id": "road_west", "snodeid": "401", "enodeid": "100", "direction": 2}, "geometry": LineString([(-40.0, 0.0), (0.0, 0.0)])},
            {"properties": {"id": "road_east", "snodeid": "100", "enodeid": "402", "direction": 2}, "geometry": LineString([(0.0, 0.0), (45.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [{"properties": {"name": "dz"}, "geometry": unary_union([box(-50.0, -12.0, 60.0, 12.0), box(-12.0, -70.0, 12.0, 70.0)])}],
        crs_text="EPSG:3857",
    )
    write_vector(
        divstripzone_path,
        [{"properties": {"id": "divstrip_east"}, "geometry": box(18.0, -4.0, 30.0, 4.0)}],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {"properties": {"id": "rc_north", "snodeid": "100", "enodeid": "901", "direction": 2}, "geometry": LineString([(0.0, 0.0), (0.0, 55.0)])},
            {"properties": {"id": "rc_south", "snodeid": "902", "enodeid": "100", "direction": 2}, "geometry": LineString([(0.0, -55.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_west", "snodeid": "904", "enodeid": "100", "direction": 2}, "geometry": LineString([(-35.0, 0.0), (0.0, 0.0)])},
            {"properties": {"id": "rc_east", "snodeid": "100", "enodeid": "903", "direction": 2}, "geometry": LineString([(0.0, 0.0), (42.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "901", "mainnodeid": None}, "geometry": Point(0.0, 55.0)},
            {"properties": {"id": "902", "mainnodeid": None}, "geometry": Point(0.0, -55.0)},
            {"properties": {"id": "903", "mainnodeid": None}, "geometry": Point(42.0, 0.0)},
            {"properties": {"id": "904", "mainnodeid": None}, "geometry": Point(-35.0, 0.0)},
        ],
        crs_text="EPSG:3857",
    )
    return {
        "nodes_path": nodes_path,
        "roads_path": roads_path,
        "drivezone_path": drivezone_path,
        "divstripzone_path": divstripzone_path,
        "rcsdroad_path": rcsdroad_path,
        "rcsdnode_path": rcsdnode_path,
    }


def _write_continuous_chain_fixture(
    tmp_path: Path,
    *,
    representative_kind_2: int = 8,
    representative_kind: int | None = None,
) -> dict[str, Path]:
    fixture = _write_fixture(
        tmp_path,
        kind_2=representative_kind_2,
        kind=representative_kind,
        divstrip_mode="nearby_single",
    )
    nodes_path = fixture["nodes_path"]
    existing_features = _load_vector_doc(nodes_path)["features"]
    write_vector(
        nodes_path,
        [
            {
                "properties": feature["properties"],
                "geometry": shape(feature["geometry"]),
            }
            for feature in existing_features
        ]
        + [
            {"properties": {"id": "200", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1}, "geometry": Point(24.0, 0.0)},
            {"properties": {"id": "201", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1}, "geometry": Point(29.0, 2.0)},
        ],
        crs_text="EPSG:3857",
    )
    return {
        "nodes_path": fixture["nodes_path"],
        "roads_path": fixture["roads_path"],
        "drivezone_path": fixture["drivezone_path"],
        "divstripzone_path": fixture["divstripzone_path"],
        "rcsdroad_path": fixture["rcsdroad_path"],
        "rcsdnode_path": fixture["rcsdnode_path"],
    }


@pytest.mark.parametrize("kind_2", [8, 16])
def test_stage4_accepts_kind_8_and_16_with_nearby_divstrip(tmp_path: Path, kind_2: int) -> None:
    fixture = _write_fixture(tmp_path, kind_2=kind_2, divstrip_mode="nearby_single")
    original_nodes = _load_vector_doc(fixture["nodes_path"])
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id=f"kind_{kind_2}",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    polygon_doc = _load_vector_doc(artifacts.virtual_polygon_path)
    polygon_feature = polygon_doc["features"][0]
    polygon_geometry = shape(polygon_feature["geometry"])
    assert polygon_feature["properties"]["acceptance_class"] == "accepted"
    assert polygon_feature["properties"]["divstrip_present"] == 1
    assert polygon_feature["properties"]["divstrip_nearby"] == 1
    assert polygon_feature["properties"]["divstrip_component_count"] == 1
    assert polygon_feature["properties"]["selection_mode"] == "divstrip_primary"
    assert polygon_feature["properties"]["evidence_source"] == "drivezone+divstrip+roads+rcsd+seed"
    assert polygon_geometry.intersection(fixture["divstrip_union"]).area == pytest.approx(0.0)
    min_x, min_y, max_x, max_y = polygon_geometry.bounds
    assert max_y - min_y <= 120.0

    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert status_doc["divstrip"]["divstrip_present"] is True
    assert status_doc["divstrip"]["divstrip_nearby"] is True
    assert status_doc["divstrip"]["divstrip_component_count"] == 1
    assert status_doc["divstrip"]["divstrip_component_selected"] == ["divstrip_component_0"]
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"
    assert status_doc["event_shape"]["event_span_start_m"] >= -25.0
    assert status_doc["event_shape"]["event_span_end_m"] <= 25.0
    assert status_doc["review_reasons"] == []
    assert audit_doc["rows"][0]["evidence_source"] == "drivezone+divstrip+roads+rcsd+seed"
    assert _load_vector_doc(fixture["nodes_path"]) == original_nodes


def test_stage4_prefers_tip_projection_when_tip_and_first_hit_both_exist(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=16, divstrip_mode="nearby_single")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="prefer_tip_projection",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["event_shape"]["event_tip_s_m"] is not None
    assert status_doc["event_shape"]["event_split_pick_source"] == "divstrip_tip_projection_window"


def test_stage4_uses_adjacent_semantic_junction_boundary_even_when_neighbor_is_not_stage4_candidate(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        extra_node_features=[
            {
                "properties": {
                    "id": "500",
                    "mainnodeid": "500",
                    "has_evd": "yes",
                    "is_anchor": "yes",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 34.0),
            },
            {
                "properties": {
                    "id": "501",
                    "mainnodeid": "500",
                    "has_evd": "yes",
                    "is_anchor": "yes",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(2.0, 38.0),
            },
        ],
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="semantic_boundary_neighbor",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    previous_boundary_offset = status_doc["event_shape"]["semantic_prev_boundary_offset_m"]
    next_boundary_offset = status_doc["event_shape"]["semantic_next_boundary_offset_m"]
    assert previous_boundary_offset is not None or next_boundary_offset is not None
    if previous_boundary_offset is not None:
        assert status_doc["event_shape"]["event_span_start_m"] > float(previous_boundary_offset)
    if next_boundary_offset is not None:
        assert status_doc["event_shape"]["event_span_end_m"] < float(next_boundary_offset)


def test_pick_reference_s_prefers_tip_projection_over_drivezone_split() -> None:
    chosen_s, position_source, split_pick_source = _pick_reference_s(
        divstrip_ref_s=12.0,
        divstrip_ref_source="tip_projection",
        drivezone_split_s=8.0,
        max_offset_m=30.0,
    )

    assert chosen_s == pytest.approx(12.0)
    assert position_source == "divstrip_ref"
    assert split_pick_source == "divstrip_tip_projection_window"


def test_primary_rcsdnode_exact_cover_overrides_off_trunk_when_offset_is_valid() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=8,
        grade_2=1,
    )
    primary_main_rc_node = ParsedNode(
        feature_index=1,
        properties={"id": "200", "mainnodeid": "0"},
        geometry=Point(10.0, 25.0),
        node_id="200",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    local_roads = [
        ParsedRoad(
            feature_index=0,
            properties={"id": "road_a", "snodeid": "100", "enodeid": "300", "direction": 2},
            geometry=LineString([(0.0, 0.0), (20.0, 0.0)]),
            road_id="road_a",
            snodeid="100",
            enodeid="300",
            direction=2,
        )
    ]
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=False,
            has_outgoing_support=True,
        )
    ]

    result = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=box(5.0, 20.0, 15.0, 30.0),
        primary_main_rc_node=primary_main_rc_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=local_roads,
        selected_roads=local_roads,
        kind_2=8,
        drivezone_union=box(-10.0, -10.0, 30.0, 40.0),
    )

    assert result["reason"] is None
    assert result["rcsdnode_coverage_mode"] == "exact_cover"
    assert result["covered"] is True
    assert result["rcsdnode_lateral_dist_m"] == pytest.approx(25.0)


def test_primary_rcsdnode_selected_road_corridor_tolerance_extends_polygon() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=8,
        grade_2=1,
    )
    primary_main_rc_node = ParsedNode(
        feature_index=1,
        properties={"id": "200", "mainnodeid": "0"},
        geometry=Point(10.0, 8.0),
        node_id="200",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    trunk_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_a", "snodeid": "100", "enodeid": "300", "direction": 2},
        geometry=LineString([(0.0, 0.0), (20.0, 0.0)]),
        road_id="road_a",
        snodeid="100",
        enodeid="300",
        direction=2,
    )
    selected_side_road = ParsedRoad(
        feature_index=1,
        properties={"id": "road_b", "snodeid": "100", "enodeid": "301", "direction": 2},
        geometry=LineString([(0.0, 8.0), (20.0, 8.0)]),
        road_id="road_b",
        snodeid="100",
        enodeid="301",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=False,
            has_outgoing_support=True,
        )
    ]

    result = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=box(5.0, -2.0, 15.0, 2.0),
        primary_main_rc_node=primary_main_rc_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=[trunk_road, selected_side_road],
        selected_roads=[selected_side_road],
        kind_2=8,
        drivezone_union=box(-10.0, -10.0, 30.0, 20.0),
    )

    assert result["reason"] is None
    assert result["rcsdnode_coverage_mode"] == "selected_road_corridor_tolerated"
    assert result["covered"] is True
    assert result["extended_polygon_geometry"].buffer(0).covers(primary_main_rc_node.geometry)


def test_primary_rcsdnode_selected_road_corridor_tolerance_respects_support_clip() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 8, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=8,
        grade_2=1,
    )
    primary_main_rc_node = ParsedNode(
        feature_index=1,
        properties={"id": "200", "mainnodeid": "0"},
        geometry=Point(10.0, 8.0),
        node_id="200",
        mainnodeid="0",
        has_evd=None,
        is_anchor=None,
        kind_2=None,
        grade_2=None,
    )
    trunk_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_a", "snodeid": "100", "enodeid": "300", "direction": 2},
        geometry=LineString([(0.0, 0.0), (20.0, 0.0)]),
        road_id="road_a",
        snodeid="100",
        enodeid="300",
        direction=2,
    )
    selected_side_road = ParsedRoad(
        feature_index=1,
        properties={"id": "road_b", "snodeid": "100", "enodeid": "301", "direction": 2},
        geometry=LineString([(0.0, 8.0), (20.0, 8.0)]),
        road_id="road_b",
        snodeid="100",
        enodeid="301",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=False,
            has_outgoing_support=True,
        )
    ]

    result = _evaluate_primary_rcsdnode_tolerance(
        polygon_geometry=box(5.0, -2.0, 15.0, 2.0),
        primary_main_rc_node=primary_main_rc_node,
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1"},
        local_roads=[trunk_road, selected_side_road],
        selected_roads=[selected_side_road],
        kind_2=8,
        drivezone_union=box(-10.0, -10.0, 30.0, 20.0),
        support_clip_geometry=box(-10.0, -3.0, 30.0, 3.0),
    )

    assert result["reason"] == "rcsdnode_main_off_trunk"
    assert result["rcsdnode_coverage_mode"] != "selected_road_corridor_tolerated"
    assert result["covered"] is False


def test_resolve_parallel_centerline_ignores_excluded_current_junction_roads() -> None:
    axis_centerline = LineString([(0.0, 0.0), (30.0, 0.0)])
    local_roads = [
        ParsedRoad(
            feature_index=0,
            properties={"id": "road_selected", "snodeid": "100", "enodeid": "101", "direction": 2},
            geometry=LineString([(0.0, 0.0), (30.0, 0.0)]),
            road_id="road_selected",
            snodeid="100",
            enodeid="101",
            direction=2,
        ),
        ParsedRoad(
            feature_index=1,
            properties={"id": "road_current_junction", "snodeid": "100", "enodeid": "102", "direction": 2},
            geometry=LineString([(0.0, 6.0), (30.0, 6.0)]),
            road_id="road_current_junction",
            snodeid="100",
            enodeid="102",
            direction=2,
        ),
        ParsedRoad(
            feature_index=2,
            properties={"id": "road_other_corridor", "snodeid": "500", "enodeid": "501", "direction": 2},
            geometry=LineString([(0.0, -18.0), (30.0, -18.0)]),
            road_id="road_other_corridor",
            snodeid="500",
            enodeid="501",
            direction=2,
        ),
    ]

    result = _resolve_parallel_centerline(
        local_roads=local_roads,
        selected_road_ids={"road_selected"},
        excluded_road_ids={"road_current_junction"},
        axis_centerline=axis_centerline,
        axis_unit_vector=(1.0, 0.0),
        reference_point=Point(15.0, 0.0),
        parallel_side_sign=-1,
    )

    assert result is not None
    assert result.equals(local_roads[2].geometry)


def test_analyze_divstrip_context_simple_prefers_seed_nearest_component() -> None:
    main_road = ParsedRoad(
        feature_index=0,
        properties={"id": "road_main", "snodeid": "100", "enodeid": "200", "direction": 2},
        geometry=LineString([(0.0, 0.0), (50.0, 0.0)]),
        road_id="road_main",
        snodeid="100",
        enodeid="200",
        direction=2,
    )
    side_road = ParsedRoad(
        feature_index=1,
        properties={"id": "road_side", "snodeid": "100", "enodeid": "300", "direction": 2},
        geometry=LineString([(0.0, 0.0), (30.0, 20.0)]),
        road_id="road_side",
        snodeid="100",
        enodeid="300",
        direction=2,
    )
    road_branches = [
        SimpleNamespace(branch_id="road_1", road_ids=["road_main"]),
        SimpleNamespace(branch_id="road_2", road_ids=["road_side"]),
    ]
    result = _analyze_divstrip_context(
        local_divstrip_features=[
            SimpleNamespace(geometry=box(6.0, -1.5, 11.0, 1.5)),
            SimpleNamespace(geometry=box(20.0, -1.5, 25.0, 1.5)),
        ],
        seed_union=Point(0.0, 0.0),
        road_branches=road_branches,
        local_roads=[main_road, side_road],
        main_branch_ids={"road_1"},
        drivezone_union=box(-5.0, -10.0, 60.0, 30.0),
        event_branch_ids={"road_2"},
        allow_compound_pair_merge=False,
    )

    assert result["nearby"] is True
    assert result["selected_component_ids"] == ["divstrip_component_0"]


def test_clip_simple_event_span_window_first_hit_keeps_wider_default_pad_without_direct_targets() -> None:
    base_window = {
        "start_offset_m": -20.0,
        "end_offset_m": 20.0,
        "semantic_protected_start_m": -1.5,
        "semantic_protected_end_m": 1.5,
    }
    divstrip_geometry = box(6.0, -1.0, 9.0, 1.0)

    clipped_tip = _clip_simple_event_span_window_by_divstrip_context(
        event_span_window=base_window,
        divstrip_constraint_geometry=divstrip_geometry,
        direct_target_rc_nodes=[],
        selected_roads=None,
        origin_point=Point(0.0, 0.0),
        axis_unit_vector=(1.0, 0.0),
        selected_component_count=1,
        is_complex_junction=False,
        event_split_pick_source="divstrip_tip_projection_window",
    )
    clipped_first_hit = _clip_simple_event_span_window_by_divstrip_context(
        event_span_window=base_window,
        divstrip_constraint_geometry=divstrip_geometry,
        direct_target_rc_nodes=[],
        selected_roads=None,
        origin_point=Point(0.0, 0.0),
        axis_unit_vector=(1.0, 0.0),
        selected_component_count=1,
        is_complex_junction=False,
        event_split_pick_source="divstrip_first_hit_window",
    )

    assert clipped_tip["end_offset_m"] == pytest.approx(18.5)
    assert clipped_first_hit["end_offset_m"] == pytest.approx(20.0)
    assert clipped_first_hit["start_offset_m"] <= clipped_tip["start_offset_m"]


def test_build_local_surface_clip_geometry_localizes_full_fill_simple_case_by_divstrip_window() -> None:
    drivezone = box(-30.0, -10.0, 30.0, 10.0)
    axis_window = box(-12.0, -8.0, 12.0, 8.0)
    cross_section_surface = box(-6.0, -4.0, 6.0, 4.0)
    divstrip_event_window = box(-8.0, -5.0, 8.0, 5.0)
    divstrip_constraint_geometry = box(-2.0, -1.0, 2.0, 1.0)

    clip_geometry = _build_local_surface_clip_geometry(
        cross_section_surface_geometry=cross_section_surface,
        divstrip_event_window=divstrip_event_window,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        axis_window_geometry=axis_window,
        drivezone_union=drivezone,
        is_complex_junction=False,
        multibranch_enabled=False,
        selected_component_count=1,
        allow_full_axis_drivezone_fill=True,
    )

    assert not clip_geometry.is_empty
    assert clip_geometry.within(axis_window)
    assert clip_geometry.intersects(divstrip_event_window)


def test_build_local_surface_clip_geometry_uses_divstrip_and_surface_intersection_for_complex_case() -> None:
    drivezone = box(-40.0, -20.0, 40.0, 20.0)
    axis_window = box(-30.0, -15.0, 30.0, 15.0)
    cross_section_surface = box(-18.0, -6.0, 18.0, 6.0)
    divstrip_event_window = box(-10.0, -10.0, 10.0, 10.0)
    divstrip_constraint_geometry = box(-4.0, -2.0, 4.0, 2.0)

    clip_geometry = _build_local_surface_clip_geometry(
        cross_section_surface_geometry=cross_section_surface,
        divstrip_event_window=divstrip_event_window,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        axis_window_geometry=axis_window,
        drivezone_union=drivezone,
        is_complex_junction=True,
        multibranch_enabled=True,
        selected_component_count=2,
        allow_full_axis_drivezone_fill=False,
    )

    assert not clip_geometry.is_empty
    assert clip_geometry.within(drivezone)
    assert clip_geometry.intersects(divstrip_event_window)
    assert clip_geometry.intersects(cross_section_surface)


def test_refine_complex_event_span_window_by_divstrip_context_uses_component_span() -> None:
    base_window = {
        "start_offset_m": -12.0,
        "end_offset_m": 48.0,
        "semantic_protected_start_m": -12.0,
        "semantic_protected_end_m": 48.0,
        "candidate_offset_count": 10,
        "expansion_source": "semantic_context_refined",
    }
    divstrip_geometry = unary_union([box(-18.0, -2.0, -10.0, 2.0), box(12.0, -2.0, 24.0, 2.0)])
    selected_event_roads_geometry = unary_union(
        [
            LineString([(-20.0, 0.0), (0.0, 0.0)]).buffer(1.0, cap_style=2, join_style=2),
            LineString([(0.0, 0.0), (26.0, 0.0)]).buffer(1.0, cap_style=2, join_style=2),
        ]
    )

    refined = _refine_complex_event_span_window_by_divstrip_context(
        event_span_window=base_window,
        divstrip_constraint_geometry=divstrip_geometry,
        selected_roads_geometry=selected_event_roads_geometry,
        selected_event_roads_geometry=selected_event_roads_geometry,
        selected_rcsd_roads_geometry=GeometryCollection(),
        origin_point=Point(0.0, 0.0),
        axis_unit_vector=(1.0, 0.0),
        selected_component_count=2,
        is_complex_junction=True,
    )

    assert refined["start_offset_m"] < -12.0
    assert refined["end_offset_m"] < 48.0
    assert refined["expansion_source"] == "complex_divstrip_component_context"


def test_resolve_operational_kind_2_accepts_complex_multibranch_event_without_side_branches() -> None:
    representative_node = ParsedNode(
        feature_index=0,
        properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 128, "grade_2": 1},
        geometry=Point(0.0, 0.0),
        node_id="100",
        mainnodeid="100",
        has_evd="yes",
        is_anchor="no",
        kind_2=128,
        grade_2=1,
    )
    road_branches = [
        SimpleNamespace(
            branch_id="road_1",
            road_ids=["road_a"],
            angle_deg=0.0,
            has_incoming_support=False,
            has_outgoing_support=True,
        ),
        SimpleNamespace(
            branch_id="road_2",
            road_ids=["road_b"],
            angle_deg=180.0,
            has_incoming_support=True,
            has_outgoing_support=False,
        ),
    ]

    result = _resolve_operational_kind_2(
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids={"road_1", "road_2"},
        preferred_branch_ids={"road_1", "road_2"},
        local_roads=[],
        divstrip_context={
            "constraint_geometry": None,
            "nearby": False,
            "ambiguous": False,
        },
        chain_context={
            "is_in_continuous_chain": False,
            "sequential_ok": False,
        },
        multibranch_context={
            "enabled": True,
            "selected_event_index": 0,
            "ambiguous": False,
        },
    )

    assert result["complex_junction"] is True
    assert result["ambiguous"] is False
    assert result["operational_kind_2"] == 16
    assert result["kind_resolution_mode"] == "complex_multibranch_event"


def test_chain_candidates_continue_through_degree_3_node_when_trunk_direction_is_clear() -> None:
    local_nodes = [
        ParsedNode(
            feature_index=0,
            properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
        ParsedNode(
            feature_index=1,
            properties={"id": "200", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(20.0, 0.0),
            node_id="200",
            mainnodeid="200",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
    ]
    local_roads = [
        ParsedRoad(
            feature_index=0,
            properties={"id": "road_a", "snodeid": "100", "enodeid": "150", "direction": 2},
            geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
            road_id="road_a",
            snodeid="100",
            enodeid="150",
            direction=2,
        ),
        ParsedRoad(
            feature_index=1,
            properties={"id": "road_b", "snodeid": "150", "enodeid": "200", "direction": 2},
            geometry=LineString([(10.0, 0.0), (20.0, 0.0)]),
            road_id="road_b",
            snodeid="150",
            enodeid="200",
            direction=2,
        ),
        ParsedRoad(
            feature_index=2,
            properties={"id": "road_side", "snodeid": "150", "enodeid": "250", "direction": 2},
            geometry=LineString([(10.0, 0.0), (10.0, 10.0)]),
            road_id="road_side",
            snodeid="150",
            enodeid="250",
            direction=2,
        ),
    ]

    chain_candidates, diag = _chain_candidates_from_topology(
        representative_node_id="100",
        representative_chain_kind_2=16,
        local_nodes=local_nodes,
        local_roads=local_roads,
        chain_span_limit_m=50.0,
    )

    assert [node.node_id for node, _distance in chain_candidates] == ["200"]
    assert diag["chain_graph_node_count"] >= 4


def test_chain_candidates_stop_when_degree_3_continuation_is_ambiguous() -> None:
    local_nodes = [
        ParsedNode(
            feature_index=0,
            properties={"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(0.0, 0.0),
            node_id="100",
            mainnodeid="100",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
        ParsedNode(
            feature_index=1,
            properties={"id": "200", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(20.0, 1.75),
            node_id="200",
            mainnodeid="200",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
        ParsedNode(
            feature_index=2,
            properties={"id": "300", "mainnodeid": "300", "has_evd": "yes", "is_anchor": "no", "kind_2": 16, "grade_2": 1},
            geometry=Point(20.0, -1.75),
            node_id="300",
            mainnodeid="300",
            has_evd="yes",
            is_anchor="no",
            kind_2=16,
            grade_2=1,
        ),
    ]
    local_roads = [
        ParsedRoad(
            feature_index=0,
            properties={"id": "road_a", "snodeid": "100", "enodeid": "150", "direction": 2},
            geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
            road_id="road_a",
            snodeid="100",
            enodeid="150",
            direction=2,
        ),
        ParsedRoad(
            feature_index=1,
            properties={"id": "road_b", "snodeid": "150", "enodeid": "200", "direction": 2},
            geometry=LineString([(10.0, 0.0), (20.0, 1.75)]),
            road_id="road_b",
            snodeid="150",
            enodeid="200",
            direction=2,
        ),
        ParsedRoad(
            feature_index=2,
            properties={"id": "road_c", "snodeid": "150", "enodeid": "300", "direction": 2},
            geometry=LineString([(10.0, 0.0), (20.0, -1.75)]),
            road_id="road_c",
            snodeid="150",
            enodeid="300",
            direction=2,
        ),
    ]

    chain_candidates, diag = _chain_candidates_from_topology(
        representative_node_id="100",
        representative_chain_kind_2=16,
        local_nodes=local_nodes,
        local_roads=local_roads,
        chain_span_limit_m=50.0,
    )

    assert chain_candidates == []
    assert diag["chain_graph_node_count"] >= 4


def test_stage4_falls_back_to_roads_when_divstrip_not_nearby(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=8, divstrip_mode="not_nearby")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="divstrip_not_nearby",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["acceptance_reason"] == "stable"
    assert status_doc["divstrip"]["divstrip_present"] is True
    assert status_doc["divstrip"]["divstrip_nearby"] is False
    assert status_doc["divstrip"]["divstrip_component_count"] == 1
    assert status_doc["divstrip"]["divstrip_component_selected"] == []
    assert status_doc["divstrip"]["selection_mode"] == "roads_fallback"
    assert status_doc["review_reasons"] == []
    assert audit_doc["rows"][0]["evidence_source"] == "drivezone+roads+rcsd+seed"
    assert artifacts.virtual_polygon_path.is_file()


def test_stage4_accepts_without_divstrip_input_by_falling_back_to_roads(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=16, divstrip_mode="nearby_single")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="no_divstrip_input",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["divstrip"]["divstrip_present"] is False
    assert status_doc["divstrip"]["divstrip_nearby"] is False
    assert status_doc["divstrip"]["selection_mode"] == "roads_fallback"
    assert status_doc["divstrip"]["evidence_source"] == "drivezone+roads+rcsd+seed"


def test_stage4_accepts_complex_kind_128_and_writes_rendered_map(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=128, kind=128, divstrip_mode="nearby_single")
    rendered_root = tmp_path / "renders"
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="complex_kind_128",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
        debug=True,
        debug_render_root=rendered_root,
    )

    assert artifacts.success is True
    assert artifacts.rendered_map_path == rendered_root / "100.png"
    assert artifacts.rendered_map_path.is_file()
    assert (artifacts.out_root / "stage4_debug" / "100.png").is_file()
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["kind"] == 128
    assert status_doc["source_kind"] == 128
    assert status_doc["source_kind_2"] == 128
    assert status_doc["kind_2"] == 16
    assert status_doc["kind_resolution"]["complex_junction"] is True
    assert status_doc["kind_resolution"]["kind_resolution_mode"] == "divstrip_event_position"
    assert status_doc["kind_resolution"]["kind_resolution_ambiguous"] is False
    assert status_doc["continuous_chain"]["is_in_continuous_chain"] is False
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"
    assert status_doc["output_files"]["rendered_map"] == str(rendered_root / "100.png")


def test_stage4_prefers_event_anchor_when_divstrip_has_two_seed_nearby_components(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=16, divstrip_mode="ambiguous_two_nearby")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="divstrip_ambiguous",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["acceptance_reason"] == "stable"
    assert status_doc["divstrip"]["divstrip_present"] is True
    assert status_doc["divstrip"]["divstrip_nearby"] is True
    assert status_doc["divstrip"]["divstrip_component_count"] == 2
    assert len(status_doc["divstrip"]["divstrip_component_selected"]) == 1
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"


def test_stage4_accepts_diverge_main_rcsdnode_within_pre_trunk_window(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, -18.0),
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="diverge_pre_trunk_window",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["rcsdnode_tolerance"]["trunk_branch_id"] == "road_2"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_rule"] == "diverge_main_seed_on_pre_trunk_le_20m"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_applied"] in {False, True}
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_coverage_mode"] in {"exact_cover", "trunk_window_tolerated"}
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_offset_m"] == pytest.approx(18.0, abs=1.0)


def test_stage4_accepts_merge_main_rcsdnode_within_post_trunk_window(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=8,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, 18.0),
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="merge_post_trunk_window",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["rcsdnode_tolerance"]["trunk_branch_id"] == "road_1"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_rule"] == "merge_main_seed_on_post_trunk_le_20m"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_applied"] in {False, True}
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_coverage_mode"] in {"exact_cover", "trunk_window_tolerated"}
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_offset_m"] == pytest.approx(18.0, abs=1.0)


def test_stage4_marks_main_rcsdnode_out_of_window_as_review_required(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, -28.0),
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="main_rcsdnode_out_of_window",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "review_required"
    assert status_doc["acceptance_reason"] == "rcsdnode_main_out_of_window"
    assert status_doc["rcsdnode_tolerance"]["trunk_branch_id"] == "road_2"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_tolerance_applied"] is False
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_coverage_mode"] == "out_of_window"
    assert status_doc["coverage_missing_ids"] == []


def test_stage4_infers_primary_rcsdnode_when_direct_mainnodeid_group_is_missing(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, -18.0),
        main_rcsdnode_id="910",
        main_rcsdnode_mainnodeid=None,
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="infer_local_rcsdnode",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    rcsdnode_link_doc = json.loads(artifacts.rcsdnode_link_json_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["rcsdnode_seed_mode"] == "inferred_local_trunk_window"
    assert status_doc["rcsdnode_tolerance"]["rcsdnode_seed_mode"] == "inferred_local_trunk_window"
    assert status_doc["rcsdnode_tolerance"]["trunk_branch_id"] == "road_2"
    assert rcsdnode_link_doc["target_node_ids"] == ["910"]
    assert "910" in rcsdnode_link_doc["linked_node_ids"]


def test_stage4_does_not_reject_when_direct_mainnodeid_group_is_missing_and_local_rcsdnode_is_weak(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=8,
        divstrip_mode="not_nearby",
        main_rcsdnode_geometry=Point(0.0, 30.0),
        main_rcsdnode_id="910",
        main_rcsdnode_mainnodeid=None,
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="infer_local_rcsdnode_review",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    rcsdnode_link_doc = json.loads(artifacts.rcsdnode_link_json_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["acceptance_reason"] == "stable"
    assert status_doc["rcsdnode_seed_mode"] == "inferred_local_trunk_window"
    assert status_doc["flow_success"] is True
    assert rcsdnode_link_doc["target_node_ids"] == []
    assert rcsdnode_link_doc["coverage_missing_ids"] == []


def test_stage4_ignores_unselected_outside_rcsd_features_in_case_package(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=8, divstrip_mode="nearby_single")
    rcsdroad_doc = _load_vector_doc(fixture["rcsdroad_path"])
    write_vector(
        fixture["rcsdroad_path"],
        [
            {"properties": feature["properties"], "geometry": shape(feature["geometry"])}
            for feature in rcsdroad_doc["features"]
        ]
        + [
            {
                "properties": {"id": "rc_far_outside", "snodeid": "990", "enodeid": "991", "direction": 2},
                "geometry": LineString([(120.0, 120.0), (160.0, 160.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )
    rcsdnode_doc = _load_vector_doc(fixture["rcsdnode_path"])
    write_vector(
        fixture["rcsdnode_path"],
        [
            {"properties": feature["properties"], "geometry": shape(feature["geometry"])}
            for feature in rcsdnode_doc["features"]
        ]
        + [
            {"properties": {"id": "990", "mainnodeid": None}, "geometry": Point(120.0, 120.0)},
            {"properties": {"id": "991", "mainnodeid": None}, "geometry": Point(160.0, 160.0)},
        ],
        crs_text="EPSG:3857",
    )

    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="ignore_outside_unselected_rcs",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"


@pytest.mark.parametrize("kind_2", [8, 16])
def test_stage4_accepts_multibranch_event_with_clear_selected_pair(tmp_path: Path, kind_2: int) -> None:
    fixture = _write_multibranch_fixture(tmp_path, kind_2=kind_2)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id=f"multibranch_{kind_2}",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["multibranch"]["multibranch_enabled"] is True
    assert status_doc["multibranch"]["multibranch_n"] >= 3
    assert status_doc["multibranch"]["event_candidate_count"] >= 3
    assert status_doc["multibranch"]["selected_event_index"] == 0
    assert status_doc["multibranch"]["selected_event_branch_ids"] == (
        ["branch_east", "branch_southeast"] if kind_2 == 8 else ["branch_east", "branch_northeast"]
    )
    assert status_doc["multibranch"]["branches_used_count"] == 2


def test_stage4_uses_reverse_tip_when_reverse_retry_improves_branch_positioning(tmp_path: Path) -> None:
    fixture = _write_reverse_tip_fixture(tmp_path)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="reverse_tip",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    node_link_doc = json.loads(artifacts.node_link_json_path.read_text(encoding="utf-8"))
    assert status_doc["reverse_tip"]["reverse_tip_attempted"] is True
    assert status_doc["reverse_tip"]["reverse_tip_used"] is True
    assert status_doc["reverse_tip"]["reverse_trigger"] == "forward_divstrip_mismatch"
    assert status_doc["reverse_tip"]["position_source_forward"] == "divstrip_primary"
    assert status_doc["reverse_tip"]["position_source_reverse"] == "reverse_tip_divstrip"
    assert status_doc["reverse_tip"]["position_source_final"] == "reverse_tip_divstrip"
    assert "road_east" in node_link_doc["selected_road_ids"]
    assert "road_west" not in node_link_doc["selected_road_ids"]


def test_stage4_accepts_continuous_chain_when_only_single_side_matched(tmp_path: Path) -> None:
    fixture = _write_continuous_chain_fixture(tmp_path)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="continuous_chain",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["acceptance_reason"] == "stable"
    assert status_doc["continuous_chain"]["is_in_continuous_chain"] is True
    assert status_doc["continuous_chain"]["chain_component_id"] == "100__200"
    assert status_doc["continuous_chain"]["related_mainnodeids"] == ["200"]
    assert status_doc["continuous_chain"]["chain_node_count"] == 2
    assert status_doc["continuous_chain"]["sequential_ok"] is True


def test_stage4_accepts_complex_kind_128_with_continuous_chain_and_divstrip_priority(tmp_path: Path) -> None:
    fixture = _write_continuous_chain_fixture(
        tmp_path,
        representative_kind_2=128,
        representative_kind=128,
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="complex_continuous_chain",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["kind"] == 128
    assert status_doc["kind_2"] == 16
    assert status_doc["kind_resolution"]["complex_junction"] is True
    assert status_doc["kind_resolution"]["kind_resolution_mode"] == "continuous_chain_divstrip_event"
    assert status_doc["continuous_chain"]["is_in_continuous_chain"] is True
    assert status_doc["continuous_chain"]["sequential_ok"] is True
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"


def test_stage4_prioritizes_divstrip_near_road_even_when_far_from_seed(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=16, divstrip_mode="road_near_seed_far")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="divstrip_road_priority",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is True
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "accepted"
    assert status_doc["divstrip"]["divstrip_present"] is True
    assert status_doc["divstrip"]["divstrip_nearby"] is True
    assert status_doc["divstrip"]["selection_mode"] == "divstrip_primary"


def test_stage4_rejects_when_divstrip_crs_override_is_invalid(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=8, divstrip_mode="nearby_single")
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="divstrip_invalid_crs",
        divstripzone_crs="EPSG:not-a-crs",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "invalid_crs_or_unprojectable"


def test_stage4_rejects_when_rcsdnode_or_rcsdroad_leaves_drivezone(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, kind_2=8, divstrip_mode="nearby_single", rcsdroad_outside_drivezone=True)
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="outside_drivezone",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "rcsd_outside_drivezone"


def test_stage4_rejects_when_rcsdnode_leaves_drivezone(tmp_path: Path) -> None:
    fixture = _write_fixture(
        tmp_path,
        kind_2=16,
        divstrip_mode="nearby_single",
        main_rcsdnode_geometry=Point(0.0, -155.0),
    )
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        mainnodeid="100",
        out_root=tmp_path / "out",
        run_id="rcsdnode_outside_drivezone",
        nodes_path=fixture["nodes_path"],
        roads_path=fixture["roads_path"],
        drivezone_path=fixture["drivezone_path"],
        divstripzone_path=fixture["divstripzone_path"],
        rcsdroad_path=fixture["rcsdroad_path"],
        rcsdnode_path=fixture["rcsdnode_path"],
    )

    assert artifacts.success is False
    status_doc = json.loads(artifacts.status_path.read_text(encoding="utf-8"))
    assert status_doc["acceptance_class"] == "rejected"
    assert status_doc["acceptance_reason"] == "rcsd_outside_drivezone"


def test_cover_check_requires_true_geometric_coverage() -> None:
    missing_ids = _cover_check(
        box(0.0, 0.0, 1.0, 1.0),
        [
            ParsedNode(
                feature_index=0,
                properties={},
                geometry=Point(0.5, 0.5),
                node_id="inside",
                mainnodeid="100",
                has_evd="yes",
                is_anchor="no",
                kind_2=8,
                grade_2=1,
            ),
            ParsedNode(
                feature_index=1,
                properties={},
                geometry=Point(1.2, 0.5),
                node_id="near_outside",
                mainnodeid=None,
                has_evd=None,
                is_anchor=None,
                kind_2=None,
                grade_2=None,
            ),
        ],
    )

    assert missing_ids == ["near_outside"]
