from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_swsd_topology import (
    audit_swsd_access_direction_topology,
)


def test_reversed_oneway_chain_fails_both_swsd_access_roles() -> None:
    result = audit_swsd_access_direction_topology(
        _segments("2"),
        _swsd_roads(2),
        _swsd_nodes(),
        _accesses(),
        _published_roads(
            [
                _road("built", 20, 10, 2),
            ]
        ),
        _published_nodes(),
        run_id="test",
    )

    assert result.fallback_segment_ids == frozenset({"segment"})
    assert result.summary["failed_access_count"] == 2
    assert set(result.audit["reason_codes"]) == {
        "swsd_inbound_role_missing,unexpected_outbound_role",
        "swsd_outbound_role_missing,unexpected_inbound_role",
    }


def test_fine_directional_chain_preserves_swsd_access_topology() -> None:
    result = audit_swsd_access_direction_topology(
        _segments("1"),
        _swsd_roads(1),
        _swsd_nodes(),
        _accesses(),
        _published_roads(
            [
                _road("forward-a", 10, 30, 2),
                _road("forward-b", 30, 20, 2),
                _road("reverse-a", 20, 31, 2),
                _road("reverse-b", 31, 10, 2),
            ]
        ),
        _published_nodes(),
        run_id="test",
    )

    assert result.summary["gate_pass"]
    assert not result.fallback_segment_ids
    assert result.audit["topology_preserved"].all()


def test_extra_reverse_role_on_swsd_oneway_is_a_structure_change() -> None:
    result = audit_swsd_access_direction_topology(
        _segments("2"),
        _swsd_roads(2),
        _swsd_nodes(),
        _accesses(),
        _published_roads(
            [
                _road("forward", 10, 20, 2),
                _road("extra-reverse", 20, 10, 2),
            ]
        ),
        _published_nodes(),
        run_id="test",
    )

    assert result.summary["failed_segment_count"] == 1
    assert set(result.audit["reason_codes"]) == {
        "unexpected_inbound_role",
        "unexpected_outbound_role",
    }


def test_mainnode_without_junction_lineage_cannot_satisfy_access() -> None:
    nodes = _published_nodes()
    nodes["junction_group_ids"] = ""
    result = audit_swsd_access_direction_topology(
        _segments("2"),
        _swsd_roads(2),
        _swsd_nodes(),
        _accesses(),
        _published_roads(
            [
                _road("forward", 10, 20, 2),
            ]
        ),
        nodes,
        run_id="test",
    )

    assert result.fallback_segment_ids == frozenset({"segment"})
    assert result.summary["failed_access_count"] == 2
    assert set(result.audit["reason_codes"]) == {
        "swsd_outbound_role_missing",
        "swsd_inbound_role_missing",
    }


def _segments(direction: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "segment_id": "segment",
                "swsd_road_ids": "swsd",
                "direction": direction,
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        crs="EPSG:32650",
    )


def _swsd_roads(direction: int) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "id": "swsd",
                "segmentid": "segment",
                "snodeid": 10,
                "enodeid": 20,
                "direction": direction,
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        crs="EPSG:32650",
    )


def _swsd_nodes() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {"id": 10, "mainnodeid": 100, "geometry": Point(0, 0)},
            {"id": 20, "mainnodeid": 200, "geometry": Point(10, 0)},
        ],
        crs="EPSG:32650",
    )


def _accesses() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "access_id": "segment:start",
                "segment_id": "segment",
                "junction_group_id": 100,
                "access_type": "ENDPOINT",
                "geometry": Point(0, 0),
            },
            {
                "access_id": "segment:end",
                "segment_id": "segment",
                "junction_group_id": 200,
                "access_type": "ENDPOINT",
                "geometry": Point(10, 0),
            },
        ],
        crs="EPSG:32650",
    )


def _published_roads(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, crs="EPSG:32650")


def _road(
    road_id: str,
    start: int,
    end: int,
    direction: int,
) -> dict[str, object]:
    coordinates = {
        10: (0, 0),
        20: (10, 0),
        30: (5, 0),
        31: (5, 1),
    }
    return {
        "id": road_id,
        "segment_id": "segment",
        "snodeid": start,
        "enodeid": end,
        "direction": direction,
        "geometry": LineString([coordinates[start], coordinates[end]]),
    }


def _published_nodes() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "id": 10,
                "mainnodeid": 100,
                "junction_group_ids": "100",
                "geometry": Point(0, 0),
            },
            {
                "id": 20,
                "mainnodeid": 200,
                "junction_group_ids": "200",
                "geometry": Point(10, 0),
            },
            {
                "id": 30,
                "mainnodeid": 30,
                "junction_group_ids": "",
                "geometry": Point(5, 0),
            },
            {
                "id": 31,
                "mainnodeid": 31,
                "junction_group_ids": "",
                "geometry": Point(5, 1),
            },
        ],
        crs="EPSG:32650",
    )
