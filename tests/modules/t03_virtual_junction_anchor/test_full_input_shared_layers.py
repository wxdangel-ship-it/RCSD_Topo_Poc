from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_shared_layers import (
    SharedFullInputLayers,
    collect_case_features,
    feature_enodeid,
    feature_id,
    feature_mainnodeid,
    feature_snodeid,
    has_geometry,
    intersects,
    load_shared_layers,
    load_shared_nodes,
    resolve_representative_feature,
    selection_window,
)


def _write_shared_layer_fixture(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    nodes_path = root / "nodes.gpkg"
    roads_path = root / "roads.gpkg"
    drivezone_path = root / "drivezones.gpkg"
    rcsdroad_path = root / "rcsd_roads.gpkg"
    rcsdnode_path = root / "rcsd_nodes.gpkg"

    write_vector(
        nodes_path,
        [
            {
                "properties": {
                    "id": "100001",
                    "mainnodeid": "100001",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": "100001_aux",
                    "mainnodeid": "100001",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(5.0, 0.0),
            },
            {
                "properties": {
                    "id": "100002_aux",
                    "mainnodeid": "100002",
                    "has_evd": "yes",
                    "is_anchor": "no",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(100.0, 0.0),
            },
            {
                "properties": {
                    "id": "window_node",
                    "mainnodeid": "window_group",
                    "has_evd": "no",
                    "is_anchor": "keep",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(18.0, 18.0),
            },
            {
                "properties": {
                    "id": "far_node",
                    "mainnodeid": "far_group",
                    "has_evd": "no",
                    "is_anchor": "keep",
                    "kind_2": 4,
                    "grade_2": 1,
                },
                "geometry": Point(400.0, 400.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "road_target", "snodeid": "100001", "enodeid": "road_target_end", "direction": 2},
                "geometry": LineString([(-20.0, 0.0), (20.0, 0.0)]),
            },
            {
                "properties": {"id": "road_aux", "snodeid": "100001_aux", "enodeid": "road_aux_end", "direction": 2},
                "geometry": LineString([(5.0, -20.0), (5.0, 20.0)]),
            },
            {
                "properties": {"id": "road_window", "snodeid": "window_s", "enodeid": "window_e", "direction": 2},
                "geometry": LineString([(10.0, 10.0), (26.0, 26.0)]),
            },
            {
                "properties": {"id": "road_100002", "snodeid": "100002_aux", "enodeid": "road_100002_end", "direction": 2},
                "geometry": LineString([(80.0, 0.0), (120.0, 0.0)]),
            },
            {
                "properties": {"id": "road_far", "snodeid": "far_s", "enodeid": "far_e", "direction": 2},
                "geometry": LineString([(380.0, 380.0), (420.0, 420.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        drivezone_path,
        [
            {"properties": {"name": "drivezone_near"}, "geometry": box(-40.0, -40.0, 40.0, 40.0)},
            {"properties": {"name": "drivezone_100002"}, "geometry": box(70.0, -40.0, 130.0, 40.0)},
            {"properties": {"name": "drivezone_far"}, "geometry": box(360.0, 360.0, 440.0, 440.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdnode_path,
        [
            {
                "properties": {"id": "100001", "mainnodeid": "100001"},
                "geometry": Point(2.0, 2.0),
            },
            {
                "properties": {"id": "rcsd_group_1", "mainnodeid": "100001"},
                "geometry": Point(6.0, 6.0),
            },
            {
                "properties": {"id": "rcsd_window", "mainnodeid": "rcsd_window_group"},
                "geometry": Point(20.0, 20.0),
            },
            {
                "properties": {"id": "rcsd_100002_aux", "mainnodeid": "100002"},
                "geometry": Point(102.0, 2.0),
            },
            {
                "properties": {"id": "rcsd_far", "mainnodeid": "rcsd_far_group"},
                "geometry": Point(420.0, 420.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        rcsdroad_path,
        [
            {
                "properties": {"id": "rcsd_road_group", "snodeid": "100001", "enodeid": "rcsd_group_1", "direction": 2},
                "geometry": LineString([(2.0, 2.0), (6.0, 6.0)]),
            },
            {
                "properties": {"id": "rcsd_road_window", "snodeid": "rcsd_window", "enodeid": "rcsd_window_end", "direction": 2},
                "geometry": LineString([(14.0, 14.0), (28.0, 28.0)]),
            },
            {
                "properties": {"id": "rcsd_road_100002", "snodeid": "rcsd_100002_aux", "enodeid": "rcsd_100002_end", "direction": 2},
                "geometry": LineString([(90.0, 2.0), (114.0, 2.0)]),
            },
            {
                "properties": {"id": "rcsd_road_far", "snodeid": "rcsd_far", "enodeid": "rcsd_far_end", "direction": 2},
                "geometry": LineString([(400.0, 400.0), (430.0, 430.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    return nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path


def _build_shared_layers(tmp_path: Path) -> SharedFullInputLayers:
    nodes_path, roads_path, drivezone_path, rcsdroad_path, rcsdnode_path = _write_shared_layer_fixture(tmp_path)
    nodes = load_shared_nodes(nodes_path=nodes_path)
    return load_shared_layers(
        nodes=nodes,
        roads_path=roads_path,
        drivezone_path=drivezone_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
    )


def _linear_resolve_representative_feature(shared_layers: SharedFullInputLayers, case_id: str):
    for feature in shared_layers.nodes:
        if feature_id(feature) == case_id and has_geometry(feature):
            return feature
    for feature in shared_layers.nodes:
        if feature_mainnodeid(feature) == case_id and has_geometry(feature):
            return feature
    raise ValueError(case_id)


def _linear_collect_case_features(
    *,
    shared_layers: SharedFullInputLayers,
    case_id: str,
    buffer_m: float,
    patch_size_m: float,
):
    representative_feature = _linear_resolve_representative_feature(shared_layers, case_id)
    window = selection_window(
        representative_feature,
        buffer_m=buffer_m,
        patch_size_m=patch_size_m,
    )
    target_group_id = feature_mainnodeid(representative_feature) or case_id
    target_group_nodes = [
        feature
        for feature in shared_layers.nodes
        if (feature_mainnodeid(feature) or feature_id(feature)) == target_group_id and has_geometry(feature)
    ]
    if not target_group_nodes:
        target_group_nodes = [representative_feature]

    target_node_ids = {
        feature_id(feature)
        for feature in target_group_nodes
        if feature_id(feature) is not None
    }
    selected_roads = [
        feature
        for feature in shared_layers.roads
        if (
            feature_snodeid(feature) in target_node_ids
            or feature_enodeid(feature) in target_node_ids
            or intersects(feature, window)
        )
    ]
    referenced_node_ids = {
        value
        for feature in selected_roads
        for value in (feature_snodeid(feature), feature_enodeid(feature))
        if value is not None
    }

    selected_nodes = []
    for feature in shared_layers.nodes:
        node_id = feature_id(feature)
        if node_id is None or not has_geometry(feature):
            continue
        if (
            node_id in referenced_node_ids
            or node_id in target_node_ids
            or feature_mainnodeid(feature) == target_group_id
            or intersects(feature, window)
        ):
            selected_nodes.append(feature)

    selected_rcsd_nodes = [
        feature
        for feature in shared_layers.rcsd_nodes
        if (
            has_geometry(feature)
            and (
                intersects(feature, window)
                or feature_mainnodeid(feature) == target_group_id
                or feature_id(feature) == case_id
            )
        )
    ]
    selected_rcsd_node_ids = {
        feature_id(feature)
        for feature in selected_rcsd_nodes
        if feature_id(feature) is not None
    }
    selected_rcsd_roads = [
        feature
        for feature in shared_layers.rcsd_roads
        if (
            feature_snodeid(feature) in selected_rcsd_node_ids
            or feature_enodeid(feature) in selected_rcsd_node_ids
            or intersects(feature, window)
        )
    ]
    selected_drivezones = [
        feature
        for feature in shared_layers.drivezones
        if intersects(feature, window)
    ]
    if not selected_drivezones:
        drivezone_candidates = [feature for feature in shared_layers.drivezones if has_geometry(feature)]
        representative_geometry = representative_feature.geometry
        assert representative_geometry is not None
        selected_drivezones = [
            min(
                drivezone_candidates,
                key=lambda feature: float(feature.geometry.distance(representative_geometry)),
            )
        ]

    return {
        "selection_window": window,
        "nodes": selected_nodes,
        "roads": selected_roads,
        "drivezones": selected_drivezones,
        "rcsd_roads": selected_rcsd_roads,
        "rcsd_nodes": selected_rcsd_nodes,
    }


def _feature_labels(features) -> list[str]:
    labels: list[str] = []
    for feature in features:
        labels.append(
            str(
                feature.properties.get("id")
                or feature.properties.get("name")
                or feature.properties.get("mainnodeid")
            )
        )
    return labels


def test_collect_case_features_matches_linear_semantics(tmp_path: Path) -> None:
    shared_layers = _build_shared_layers(tmp_path)

    for case_id in ("100001", "100002"):
        expected = _linear_collect_case_features(
            shared_layers=shared_layers,
            case_id=case_id,
            buffer_m=30.0,
            patch_size_m=60.0,
        )
        actual = collect_case_features(
            shared_layers=shared_layers,
            case_id=case_id,
            buffer_m=30.0,
            patch_size_m=60.0,
        )

        assert expected["selection_window"].equals(actual["selection_window"])
        for layer_name in ("nodes", "roads", "drivezones", "rcsd_roads", "rcsd_nodes"):
            assert _feature_labels(actual[layer_name]) == _feature_labels(expected[layer_name])


def test_resolve_representative_feature_matches_linear_resolution(tmp_path: Path) -> None:
    shared_layers = _build_shared_layers(tmp_path)

    assert feature_id(resolve_representative_feature(shared_layers, "100001")) == feature_id(
        _linear_resolve_representative_feature(shared_layers, "100001")
    )
    assert feature_id(resolve_representative_feature(shared_layers, "100002")) == feature_id(
        _linear_resolve_representative_feature(shared_layers, "100002")
    )
    assert feature_id(resolve_representative_feature(shared_layers, "100002")) == "100002_aux"


def test_target_group_and_rcsd_group_caches_match_linear_group_members(tmp_path: Path) -> None:
    shared_layers = _build_shared_layers(tmp_path)

    linear_target_group_nodes = [
        feature
        for feature in shared_layers.nodes
        if (feature_mainnodeid(feature) or feature_id(feature)) == "100001" and has_geometry(feature)
    ]
    linear_rcsd_group_nodes = [
        feature
        for feature in shared_layers.rcsd_nodes
        if feature_mainnodeid(feature) == "100001" and has_geometry(feature)
    ]

    assert _feature_labels(shared_layers.target_group_nodes_by_group_id["100001"]) == _feature_labels(
        linear_target_group_nodes
    )
    assert _feature_labels(shared_layers.rcsd_mainnodeid_to_member_features["100001"]) == _feature_labels(
        linear_rcsd_group_nodes
    )
