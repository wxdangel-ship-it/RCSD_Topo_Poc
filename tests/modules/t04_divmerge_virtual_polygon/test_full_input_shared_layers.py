from __future__ import annotations

from pyproj import CRS
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import LoadedFeature, LoadedLayer
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import ParsedNode, ParsedRoad
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.full_input_shared_layers import (
    STEP6_SAFE_LOCAL_POLYGON_WINDOW_MAX_SIDE_M,
    T04SharedFullInputLayers,
    _build_road_adjacency,
    _build_spatial_index,
    collect_case_features,
)


def _node(node_id: str, x: float, y: float) -> ParsedNode:
    return ParsedNode(
        feature_index=0,
        properties={"id": node_id, "mainnodeid": node_id},
        geometry=Point(x, y),
        node_id=node_id,
        mainnodeid=node_id,
        has_evd="yes",
        is_anchor="no",
        kind_2=128,
        grade_2=0,
    )


def _road(road_id: str, coords: list[tuple[float, float]], *, snodeid: str, enodeid: str) -> ParsedRoad:
    return ParsedRoad(
        feature_index=0,
        properties={"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": 2},
        geometry=LineString(coords),
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        direction=2,
    )


def _feature(index: int, geometry):
    return LoadedFeature(feature_index=index, properties={"id": str(index)}, geometry=geometry)


def _layer(features: tuple[LoadedFeature, ...]) -> LoadedLayer:
    return LoadedLayer(features=list(features), source_crs=CRS.from_epsg(3857), crs_source="test")


def _layers(
    *,
    nodes: tuple[ParsedNode, ...],
    roads: tuple[ParsedRoad, ...],
    drivezones: tuple[LoadedFeature, ...],
    divstrips: tuple[LoadedFeature, ...],
) -> T04SharedFullInputLayers:
    rcsd_nodes = ()
    rcsd_roads = ()
    return T04SharedFullInputLayers(
        node_layer=_layer(()),
        road_layer=_layer(()),
        drivezone_layer=_layer(drivezones),
        divstripzone_layer=_layer(divstrips),
        rcsdroad_layer=_layer(()),
        rcsdnode_layer=_layer(()),
        nodes=nodes,
        roads=roads,
        drivezone_features=drivezones,
        divstrip_features=divstrips,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        node_index=_build_spatial_index(nodes),
        road_index=_build_spatial_index(roads),
        drivezone_index=_build_spatial_index(drivezones),
        divstrip_index=_build_spatial_index(divstrips),
        rcsdroad_index=_build_spatial_index(rcsd_roads),
        rcsdnode_index=_build_spatial_index(rcsd_nodes),
        node_id_to_roads=_build_road_adjacency(roads),
        rcsd_node_id_to_roads=_build_road_adjacency(rcsd_roads),
    )


def test_collect_case_features_clips_full_input_polygon_layers_to_step6_safe_window() -> None:
    representative = _node("607602562", 500.0, 0.0)
    seed_road = _road("607938895", [(0.0, 0.0), (500.0, 0.0)], snodeid="a", enodeid="607602562")
    large_drivezone = _feature(926, box(-2000.0, -800.0, 600.0, 800.0))
    large_divstrip = _feature(782, box(-1800.0, -10.0, 550.0, 10.0))

    selected = collect_case_features(
        layers=_layers(
            nodes=(representative,),
            roads=(seed_road,),
            drivezones=(large_drivezone,),
            divstrips=(large_divstrip,),
        ),
        case_id="607602562",
        local_query_buffer_m=360.0,
    )

    assert selected["selected_counts"]["drivezone"] == 1
    assert selected["selected_counts"]["divstripzone"] == 1
    assert selected["roads"][0].geometry.equals(seed_road.geometry)

    for key in ["polygon_clip_window", "drivezone_features", "divstrip_features"]:
        geometry = selected[key][0].geometry if key.endswith("_features") else selected[key]
        min_x, min_y, max_x, max_y = geometry.bounds
        assert max(max_x - min_x, max_y - min_y) <= STEP6_SAFE_LOCAL_POLYGON_WINDOW_MAX_SIDE_M + 1e-6

    assert selected["drivezone_features"][0].geometry.area < large_drivezone.geometry.area
    assert selected["divstrip_features"][0].geometry.area < large_divstrip.geometry.area


def test_collect_case_features_keeps_node_local_divstrip_for_long_seed_roads() -> None:
    representative = _node("706247", 0.0, 0.0)
    long_seed_road = _road("962976", [(0.0, 0.0), (0.0, 2600.0)], snodeid="706247", enodeid="tail")
    local_drivezone = _feature(1, box(-200.0, -120.0, 200.0, 160.0))
    local_divstrip = _feature(2, box(-20.0, 10.0, 20.0, 80.0))

    selected = collect_case_features(
        layers=_layers(
            nodes=(representative,),
            roads=(long_seed_road,),
            drivezones=(local_drivezone,),
            divstrips=(local_divstrip,),
        ),
        case_id="706247",
        local_query_buffer_m=360.0,
    )

    assert selected["selected_counts"]["divstripzone"] == 1
    assert selected["selected_counts"]["drivezone"] == 1
    assert selected["polygon_clip_window"].covers(representative.geometry)
    assert selected["divstrip_features"][0].geometry.intersects(local_divstrip.geometry)
