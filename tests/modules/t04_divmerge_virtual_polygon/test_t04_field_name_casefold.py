from __future__ import annotations

import pytest
from pyproj import CRS
from shapely.geometry import LineString
from shapely.geometry import Point

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import LoadedFeature, LoadedLayer
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types import (
    REASON_MISSING_REQUIRED_FIELD,
    VirtualIntersectionPocError,
    _parse_rc_nodes,
    _parse_roads,
)


def _road_layer(properties: dict[str, object]) -> LoadedLayer:
    return LoadedLayer(
        features=[
            LoadedFeature(
                feature_index=7,
                properties=properties,
                geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
            )
        ],
        source_crs=CRS.from_epsg(3857),
        crs_source="test",
    )


def test_t04_parse_roads_accepts_frcsd_camel_case_required_fields() -> None:
    parsed = _parse_roads(
        _road_layer({"ID": "r1", "snodeId": "n1", "enodeId": "n2", "Direction": 2}),
        label="RCSDRoad",
    )

    assert len(parsed) == 1
    assert parsed[0].road_id == "r1"
    assert parsed[0].snodeid == "n1"
    assert parsed[0].enodeid == "n2"
    assert parsed[0].direction == 2


def test_t04_parse_roads_still_rejects_missing_logical_endpoint() -> None:
    with pytest.raises(VirtualIntersectionPocError) as exc_info:
        _parse_roads(
            _road_layer({"ID": "r1", "snodeId": "n1", "Direction": 2}),
            label="RCSDRoad",
        )

    assert exc_info.value.reason == REASON_MISSING_REQUIRED_FIELD
    assert "enodeid" in exc_info.value.detail


def test_t04_parse_rc_nodes_accepts_frcsd_camel_case_mainnodeid() -> None:
    layer = LoadedLayer(
        features=[
            LoadedFeature(
                feature_index=3,
                properties={"ID": "n1", "mainNodeId": "junction-1", "Kind": 4},
                geometry=Point(1.0, 2.0),
            )
        ],
        source_crs=CRS.from_epsg(3857),
        crs_source="test",
    )

    parsed = _parse_rc_nodes(layer)

    assert parsed[0].node_id == "n1"
    assert parsed[0].mainnodeid == "junction-1"
    assert parsed[0].kind == 4


def test_t04_case_variant_conflict_keeps_feature_context() -> None:
    with pytest.raises(VirtualIntersectionPocError) as exc_info:
        _parse_roads(
            _road_layer(
                {
                    "id": "r1",
                    "snodeid": "n1",
                    "snodeId": "different-n1",
                    "enodeid": "n2",
                    "direction": 2,
                }
            ),
            label="RCSDRoad",
        )

    assert exc_info.value.reason == REASON_MISSING_REQUIRED_FIELD
    assert "RCSDRoad feature[7]" in exc_info.value.detail
    assert "case-insensitive property conflict" in exc_info.value.detail
