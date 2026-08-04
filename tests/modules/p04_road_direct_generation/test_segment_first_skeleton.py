from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_skeleton import (
    build_segment_skeleton,
    canonical_id,
    parse_id_list,
)


def test_parse_id_list_is_stable_for_csv_and_json() -> None:
    assert parse_id_list("3,1,2,1") == ("3", "1", "2")
    assert parse_id_list('["3", "1"]') == ("3", "1")
    assert parse_id_list(None) == ()


def test_canonical_id_does_not_parse_segment_underscore_as_float() -> None:
    assert canonical_id("511870213_611868953") == "511870213_611868953"
    assert canonical_id("123.0") == "123"


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, ""),
        (float("nan"), ""),
        ("", ""),
        ("'00123'", "123"),
        ("+00123", "123"),
        ("-00123", "-123"),
        ("-0.000", "0"),
        ("１２３.０", "１２３.０"),
        ("１２３", "123"),
        ("123.50", "123.50"),
        ("123.", "123."),
        (".0", ".0"),
        ("1.0.0", "1.0.0"),
        ("511870213_611868953", "511870213_611868953"),
    ),
)
def test_canonical_id_fast_path_preserves_normalization_contract(
    value: object,
    expected: str,
) -> None:
    assert canonical_id(value) == expected


def test_segment_is_top_level_owner_and_keeps_through_nodes() -> None:
    segments = gpd.GeoDataFrame(
        [{"id": "s1", "segment_type": "normal", "sgrade": "0-0双", "pair_nodes": "n1,n2", "junc_nodes": "j1", "roads": "r1,r2", "geometry": LineString([(0, 0), (10, 0)])}],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {"id": "r1", "segmentid": "s1", "patch_id": "p1", "geometry": LineString([(0, 0), (5, 0)])},
            {"id": "r2", "segmentid": "s1", "patch_id": "p2", "geometry": LineString([(5, 0), (10, 0)])},
        ],
        crs="EPSG:32650",
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": "n1", "mainnodeid": "m1", "geometry": Point(0, 0)},
            {"id": "n2", "mainnodeid": "m2", "geometry": Point(10, 0)},
            {"id": "j1", "mainnodeid": "mj", "geometry": Point(5, 0)},
        ],
        crs="EPSG:32650",
    )
    result = build_segment_skeleton(segments, roads, nodes, patch_ids=("p1",), run_id="run")
    assert result.segment_units["segment_id"].tolist() == ["s1"]
    assert set(result.scoped_roads["id"]) == {"r1", "r2"}
    assert set(result.accesses["access_type"]) == {"ENDPOINT", "THROUGH"}
    assert result.accesses[result.accesses["access_type"] == "THROUGH"]["source_node_id"].tolist() == ["j1"]


def test_advance_right_without_pair_nodes_uses_indexed_road_endpoints() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "id": "advance_right",
                "segment_type": "advance_right",
                "sgrade": "普通单",
                "pair_nodes": "",
                "junc_nodes": "",
                "roads": "r2,r1",
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": "r1",
                "segmentid": "advance_right",
                "patch_id": "p1",
                "snodeid": "n1",
                "enodeid": "n_mid",
                "geometry": LineString([(0, 0), (5, 0)]),
            },
            {
                "id": "r2",
                "segmentid": "advance_right",
                "patch_id": "p1",
                "snodeid": "n_mid",
                "enodeid": "n2",
                "geometry": LineString([(5, 0), (10, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": "n1", "mainnodeid": "m1", "geometry": Point(0, 0)},
            {"id": "n2", "mainnodeid": "m2", "geometry": Point(10, 0)},
            {
                "id": "n_mid",
                "mainnodeid": "m_mid",
                "geometry": Point(5, 0),
            },
        ],
        crs="EPSG:32650",
    )

    result = build_segment_skeleton(
        segments,
        roads,
        nodes,
        patch_ids=("p1",),
        run_id="run",
    )

    assert result.accesses["source_node_id"].tolist() == ["n1", "n2"]
    assert set(result.accesses["access_type"]) == {"ENDPOINT"}
