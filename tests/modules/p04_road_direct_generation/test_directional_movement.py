from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.directional_config import (
    DirectionalRoadV2Config,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.directional_movement import (
    build_directional_movements,
)


def _config(tmp_path: Path) -> DirectionalRoadV2Config:
    return DirectionalRoadV2Config(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "out",
        run_id="movement-test",
        endpoint_transition_length_m=10.0,
    )


def test_lane_topo_physical_transition_coordinates_shared_road_endpoints(
    tmp_path: Path,
) -> None:
    roads, parents = _roads(physical_shared=True)
    result = build_directional_movements(
        roads,
        _members(),
        _links(),
        _fit_stations(),
        parents,
        config=_config(tmp_path),
    )
    by_id = result.road_candidates.set_index("directional_road_id")
    first_end = Point(by_id.loc["r1:forward"].geometry.coords[-1])
    second_start = Point(by_id.loc["r2:forward"].geometry.coords[0])

    assert first_end.distance(second_start) == 0.0
    assert len(result.road_movements) == 1
    assert result.summary["confirmed_lane_topo_link_count"] == 1
    assert result.summary["confirmed_physical_movement_max_gap_m"] == 0.0
    assert result.summary["movement_gate_pass"]


def test_lane_topo_semantic_junction_keeps_distinct_portals_and_adds_connector(
    tmp_path: Path,
) -> None:
    roads, parents = _roads(physical_shared=False)
    result = build_directional_movements(
        roads,
        _members(),
        _links(),
        _fit_stations(),
        parents,
        config=_config(tmp_path),
    )
    movement = result.road_movements.iloc[0]
    by_id = result.road_candidates.set_index("directional_road_id")
    source = Point(by_id.loc["r1:forward"].geometry.coords[-1])
    target = Point(by_id.loc["r2:forward"].geometry.coords[0])

    assert source.distance(target) > 0.0
    assert source.distance(movement.geometry) == 0.0
    assert target.distance(movement.geometry) == 0.0
    assert movement.junction_relation == "same_semantic_junction"
    assert movement.geometry_source == "lane_topo_geometry_tangent_fallback"
    assert result.summary["movement_join_angle_max_deg"] <= 10.0
    assert result.summary["semantic_junction_movement_count"] == 1
    assert result.summary["movement_gate_pass"]


def test_all_roads_at_same_physical_node_are_coordinated_without_lane_topo(
    tmp_path: Path,
) -> None:
    roads, parents = _roads(physical_shared=True)
    roads = gpd.GeoDataFrame(
        pd.concat(
            [
                roads,
                gpd.GeoDataFrame(
                    [
                        _road(
                            "r3:forward",
                            "r3",
                            "n2",
                            "n5",
                            "j2",
                            "j4",
                            LineString([(50, 6), (100, 6)]),
                        )
                    ],
                    crs=roads.crs,
                ),
            ],
            ignore_index=True,
        ),
        crs=roads.crs,
    )
    parents = gpd.GeoDataFrame(
        pd.concat(
            [
                parents,
                gpd.GeoDataFrame(
                    [
                        {
                            "swsd_unit_id": "r3",
                            "snode_id": "n2",
                            "enode_id": "n5",
                            "geometry": LineString([(50, 0), (100, 0)]),
                        }
                    ],
                    crs=parents.crs,
                ),
            ],
            ignore_index=True,
        ),
        crs=parents.crs,
    )
    result = build_directional_movements(
        roads,
        _members(),
        _links(),
        _fit_stations(),
        parents,
        config=_config(tmp_path),
    )
    by_id = result.road_candidates.set_index("directional_road_id")
    points = [
        Point(by_id.loc["r1:forward"].geometry.coords[-1]),
        Point(by_id.loc["r2:forward"].geometry.coords[0]),
        Point(by_id.loc["r3:forward"].geometry.coords[0]),
    ]

    assert max(first.distance(second) for first in points for second in points) == 0.0
    assert result.summary["all_physical_node_max_gap_m"] == 0.0
    assert result.summary["gates"]["all_physical_nodes_closed"]


def _roads(physical_shared: bool) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    second_start_node = "n2" if physical_shared else "n3"
    second_start_x = 50.0 if physical_shared else 60.0
    roads = gpd.GeoDataFrame(
        [
            _road(
                "r1:forward",
                "r1",
                "n1",
                "n2",
                "j1",
                "j2",
                LineString([(0, 2), (50, 2)]),
            ),
            _road(
                "r2:forward",
                "r2",
                second_start_node,
                "n4",
                "j2",
                "j3",
                LineString([(second_start_x, -2), (100, -2)]),
            ),
        ],
        crs="EPSG:32650",
    )
    parents = gpd.GeoDataFrame(
        [
            {
                "swsd_unit_id": "r1",
                "snode_id": "n1",
                "enode_id": "n2",
                "geometry": LineString([(0, 0), (50, 0)]),
            },
            {
                "swsd_unit_id": "r2",
                "snode_id": second_start_node,
                "enode_id": "n4",
                "geometry": LineString([(second_start_x, 0), (100, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    return roads, parents


def _road(
    road_id: str,
    parent_id: str,
    snode_id: str,
    enode_id: str,
    semantic_start: str,
    semantic_end: str,
    geometry: LineString,
) -> dict[str, object]:
    return {
        "directional_road_id": road_id,
        "parent_swsd_unit_id": parent_id,
        "travel_side": "forward",
        "direction": 2,
        "snode_id": snode_id,
        "enode_id": enode_id,
        "semantic_snode_id": semantic_start,
        "semantic_enode_id": semantic_end,
        "swsd_reference_length_m": float(geometry.length),
        "candidate_length_m": float(geometry.length),
        "candidate_length_ratio": 1.0,
        "geometry_valid": True,
        "geometry_simple": True,
        "geometry": geometry,
    }


def _members() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "lane_id": "l1",
                "parent_swsd_unit_id": "r1",
                "directional_road_id": "r1:forward",
                "travel_side": "forward",
                "evidence_quality_state": "usable",
                "geometry": LineString([(0, 2), (50, 2)]),
            },
            {
                "lane_id": "l2",
                "parent_swsd_unit_id": "r2",
                "directional_road_id": "r2:forward",
                "travel_side": "forward",
                "evidence_quality_state": "usable",
                "geometry": LineString([(50, -2), (100, -2)]),
            },
        ],
        crs="EPSG:32650",
    )


def _links() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "link_id": "t1",
                "lane_id": "l1",
                "next_lane_id": "l2",
                "source_owner": "r1",
                "target_owner": "r2",
                "source_patch_ids": "p1",
                "lane_topo_state": "cross_owner_directed_node_supported",
                "geometry": LineString([(48, 2), (50, 2), (50, -2), (52, -2)]),
            }
        ],
        crs="EPSG:32650",
    )


def _fit_stations() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "directional_road_id": road_id,
                "travel_station_fraction": fraction,
                "support_at_station": True,
                "geometry": Point(x, y),
            }
            for road_id, y, x in (
                ("r1:forward", 2.0, 0.0),
                ("r2:forward", -2.0, 50.0),
            )
            for fraction in (0.0, 1.0)
        ],
        crs="EPSG:32650",
    )
