from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.high_precision_config import (
    HighPrecisionRoadV3Config,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.high_precision_movement import (
    build_high_precision_movements,
)


CRS = "EPSG:32650"


def _config(tmp_path: Path) -> HighPrecisionRoadV3Config:
    return HighPrecisionRoadV3Config(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "out",
        run_id="v3-movement-test",
        endpoint_transition_length_m=10.0,
    )

def test_shared_physical_roads_keep_lane_topo_and_close_physical_node(
    tmp_path: Path,
) -> None:
    result = build_high_precision_movements(
        _roads(), _members(), _links(), _fit_stations(), _parents(), config=_config(tmp_path)
    )

    by_id = result.road_candidates.set_index("v3_road_id")
    first_end = Point(by_id.loc["r1"].geometry.coords[-1])
    second_start = Point(by_id.loc["r2"].geometry.coords[0])
    assert first_end.distance(second_start) == 0.0
    assert result.summary["confirmed_lane_topo_link_count"] == 1
    assert result.summary["movement_gate_pass"]
    assert len(result.road_movements) == 1


def test_review_lane_topo_is_preserved_without_endpoint_coordination(
    tmp_path: Path,
) -> None:
    links = _links()
    links.loc[0, "lane_topo_state"] = "cross_owner_shared_node_review"
    result = build_high_precision_movements(
        _roads(), _members(), links, _fit_stations(), _parents(), config=_config(tmp_path)
    )

    assert list(result.evidence_links["projection_state"]) == ["review"]
    assert result.road_movements.empty
    assert result.summary["review_lane_topo_link_count"] == 1


def _roads() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            _road("r1", "n1", "n2", "j1", "j2", LineString([(0, 2), (50, 2)])),
            _road("r2", "n2", "n3", "j2", "j3", LineString([(50, -2), (100, -2)])),
        ],
        geometry="geometry",
        crs=CRS,
    )


def _road(
    road_id: str,
    snode_id: str,
    enode_id: str,
    semantic_start: str,
    semantic_end: str,
    geometry: LineString,
) -> dict[str, object]:
    return {
        "v3_road_id": road_id,
        "parent_swsd_unit_id": road_id,
        "road_representation": "shared_physical",
        "travel_side": "shared",
        "direction": 1,
        "snode_id": snode_id,
        "enode_id": enode_id,
        "semantic_snode_id": semantic_start,
        "semantic_enode_id": semantic_end,
        "candidate_length_ratio": 1.0,
        "geometry_valid": True,
        "geometry_simple": True,
        "geometry": geometry,
    }


def _parents() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {"swsd_unit_id": "r1", "snode_id": "n1", "enode_id": "n2", "geometry": LineString([(0, 0), (50, 0)])},
            {"swsd_unit_id": "r2", "snode_id": "n2", "enode_id": "n3", "geometry": LineString([(50, 0), (100, 0)])},
        ],
        geometry="geometry",
        crs=CRS,
    )


def _members() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {"lane_id": "l1", "parent_swsd_unit_id": "r1", "v3_road_id": "r1", "travel_side": "forward", "evidence_quality_state": "usable", "geometry": LineString([(0, 2), (50, 2)])},
            {"lane_id": "l2", "parent_swsd_unit_id": "r2", "v3_road_id": "r2", "travel_side": "forward", "evidence_quality_state": "usable", "geometry": LineString([(50, -2), (100, -2)])},
        ],
        geometry="geometry",
        crs=CRS,
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
        geometry="geometry",
        crs=CRS,
    )


def _fit_stations() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "v3_road_id": road_id,
                "station_fraction": fraction,
                "geometry_source": "hp_observed",
                "geometry": Point(x, y),
            }
            for road_id, y, x in (("r1", 2.0, 0.0), ("r2", -2.0, 50.0))
            for fraction in (0.0, 1.0)
        ],
        geometry="geometry",
        crs=CRS,
    )
