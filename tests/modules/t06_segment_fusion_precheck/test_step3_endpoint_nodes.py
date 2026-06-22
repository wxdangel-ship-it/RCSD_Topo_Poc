from __future__ import annotations

from shapely.geometry import LineString, MultiLineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_endpoint_nodes import (
    ensure_retained_swsd_road_endpoint_nodes,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_segment_replacement import (
    _sync_generated_rcsd_endpoint_node_geometries,
)


def test_ensure_retained_swsd_road_endpoint_nodes_generates_missing_non_advance_endpoint() -> None:
    swsd_nodes = [
        {
            "properties": {"id": "1", "source": 2, "mainnodeid": "1"},
            "geometry": Point(0, 0),
        }
    ]
    swsd_node_by_id = {"1": swsd_nodes[0]}

    stats = ensure_retained_swsd_road_endpoint_nodes(
        swsd_roads=[
            {
                "properties": {"id": "road1", "source": 2, "snodeid": "1", "enodeid": "2", "formway": 0},
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        swsd_nodes=swsd_nodes,
        swsd_node_by_id=swsd_node_by_id,
    )

    assert stats["generated_node_count"] == 1
    assert swsd_node_by_id["2"]["properties"]["source"] == 2
    assert swsd_node_by_id["2"]["properties"]["mainnodeid"] == 2
    assert (
        swsd_node_by_id["2"]["properties"]["t06_generated_reason"]
        == "retained_swsd_road_missing_endpoint_node"
    )
    assert swsd_node_by_id["2"]["geometry"].equals(Point(10, 0))


def test_ensure_retained_swsd_road_endpoint_nodes_handles_multiline_geometry() -> None:
    swsd_nodes: list[dict] = []
    swsd_node_by_id: dict[str, dict] = {}

    stats = ensure_retained_swsd_road_endpoint_nodes(
        swsd_roads=[
            {
                "properties": {"id": "road1", "source": 2, "snodeid": "1", "enodeid": "2", "formway": 0},
                "geometry": MultiLineString([[(0, 0), (5, 0)], [(5, 0), (10, 0)]]),
            }
        ],
        swsd_nodes=swsd_nodes,
        swsd_node_by_id=swsd_node_by_id,
    )

    assert stats["generated_node_count"] == 2
    assert swsd_node_by_id["1"]["geometry"].equals(Point(0, 0))
    assert swsd_node_by_id["2"]["geometry"].equals(Point(10, 0))


def test_sync_generated_rcsd_endpoint_node_snaps_conflicting_road_endpoint_to_topology_node() -> None:
    roads = [
        {
            "properties": {"id": "r1", "source": 1, "snodeid": "a", "enodeid": "n"},
            "geometry": LineString([(0, 0), (10, 0)]),
        },
        {
            "properties": {"id": "r2", "source": 1, "snodeid": "b", "enodeid": "n"},
            "geometry": LineString([(0, 10), (10, 10)]),
        },
    ]
    nodes = [
        {
            "properties": {
                "id": "n",
                "source": 1,
                "mainnodeid": "n",
                "t06_generated_reason": "selected_rcsd_road_missing_endpoint_node",
            },
            "geometry": Point(10, 0),
        }
    ]

    stats = _sync_generated_rcsd_endpoint_node_geometries(
        frcsd_roads=roads,
        frcsd_nodes=nodes,
        source_field_name="source",
        rcsd_source_value=1,
    )

    assert stats["snapped_road_endpoint_count"] == 1
    assert stats["conflict_node_count"] == 0
    assert list(roads[1]["geometry"].coords)[-1][:2] == (10.0, 0.0)
