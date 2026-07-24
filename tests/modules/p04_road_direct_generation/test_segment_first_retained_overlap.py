from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_retained_overlap import (
    audit_redundant_retained_roads,
)


def test_retained_carrier_is_redundant_only_with_connected_built_main_graph() -> None:
    roads = gpd.GeoDataFrame(
        [
            _road(1, "retained", "semantic_carrier", 10, 20, [(0, 0), (10, 0)]),
            _road(2, "built", "main_forward", 10, 30, [(0, 0.5), (5, 0.5)]),
            _road(3, "built", "main_reverse", 30, 20, [(5, 0.5), (10, 0.5)]),
        ],
        crs="EPSG:32650",
    )
    nodes = _nodes()
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "retained:1",
                "through_function_retained": False,
                "geometry": roads.iloc[0].geometry,
            }
        ],
        crs=roads.crs,
    )

    result = audit_redundant_retained_roads(
        roads,
        nodes,
        carriers,
        run_id="run",
    )

    assert result.suppressed_road_ids == {"1"}
    assert result.suppressed_segment_ids == {"s"}
    row = result.audit.iloc[0]
    assert bool(row["built_path_spans_retained_accesses"])
    assert float(row["overlap_ratio"]) == 1.0


def test_through_function_retained_carrier_is_never_suppressed() -> None:
    roads = gpd.GeoDataFrame(
        [
            _road(1, "retained", "semantic_carrier", 10, 20, [(0, 0), (10, 0)]),
            _road(2, "built", "main_forward", 10, 30, [(0, 0.5), (5, 0.5)]),
            _road(3, "built", "main_reverse", 30, 20, [(5, 0.5), (10, 0.5)]),
        ],
        crs="EPSG:32650",
    )
    carriers = gpd.GeoDataFrame(
        [
            {
                "carrier_id": "retained:1",
                "through_function_retained": True,
                "geometry": roads.iloc[0].geometry,
            }
        ],
        crs=roads.crs,
    )

    result = audit_redundant_retained_roads(
        roads,
        _nodes(),
        carriers,
        run_id="run",
    )

    assert not result.suppressed_road_ids
    assert result.audit.iloc[0]["reason_codes"] == "protected_through_function"


def test_overlap_without_built_graph_connection_is_not_enough() -> None:
    roads = gpd.GeoDataFrame(
        [
            _road(1, "retained", "semantic_carrier", 10, 20, [(0, 0), (10, 0)]),
            _road(2, "built", "main_forward", 10, 30, [(0, 0.5), (5, 0.5)]),
            _road(3, "built", "main_reverse", 40, 20, [(5, 0.5), (10, 0.5)]),
        ],
        crs="EPSG:32650",
    )

    result = audit_redundant_retained_roads(
        roads,
        _nodes(),
        gpd.GeoDataFrame(
            columns=["carrier_id", "through_function_retained", "geometry"],
            geometry="geometry",
            crs=roads.crs,
        ),
        run_id="run",
    )

    assert not result.suppressed_road_ids
    assert (
        result.audit.iloc[0]["reason_codes"]
        == "built_path_does_not_span_retained_accesses"
    )


def test_complex_segment_with_multiple_through_accesses_is_not_auto_suppressed() -> None:
    roads = gpd.GeoDataFrame(
        [
            _road(1, "retained", "semantic_carrier", 10, 20, [(0, 0), (10, 0)]),
            _road(2, "built", "main_forward", 10, 30, [(0, 0.5), (5, 0.5)]),
            _road(3, "built", "main_reverse", 30, 20, [(5, 0.5), (10, 0.5)]),
        ],
        crs="EPSG:32650",
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s",
                "access_type": "THROUGH",
                "geometry": Point(3, 0),
            },
            {
                "segment_id": "s",
                "access_type": "THROUGH",
                "geometry": Point(7, 0),
            },
        ],
        crs=roads.crs,
    )

    result = audit_redundant_retained_roads(
        roads,
        _nodes(),
        gpd.GeoDataFrame(
            columns=["carrier_id", "through_function_retained", "geometry"],
            geometry="geometry",
            crs=roads.crs,
        ),
        run_id="run",
        segment_accesses=accesses,
    )

    assert not result.suppressed_road_ids
    assert result.audit.iloc[0]["reason_codes"] == "complex_segment_access_contract"


def _road(
    road_id: int,
    realization: str,
    carrier_role: str,
    snodeid: int,
    enodeid: int,
    coordinates: list[tuple[float, float]],
) -> dict[str, object]:
    return {
        "id": road_id,
        "segment_id": "s",
        "carrier_id": f"retained:{road_id}",
        "realization": realization,
        "carrier_role": carrier_role,
        "snodeid": snodeid,
        "enodeid": enodeid,
        "geometry": LineString(coordinates),
    }


def _nodes() -> gpd.GeoDataFrame:
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
                "mainnodeid": 0,
                "junction_group_ids": "",
                "geometry": Point(5, 0),
            },
            {
                "id": 40,
                "mainnodeid": 0,
                "junction_group_ids": "",
                "geometry": Point(5, 1),
            },
        ],
        crs="EPSG:32650",
    )
