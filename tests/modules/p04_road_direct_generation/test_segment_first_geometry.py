from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_config import (
    SegmentFirstConfig,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_geometry import (
    materialize_road_geometry,
)


def test_materialized_road_preserves_segment_semantic_type() -> None:
    paths = [Path(f"input-{index}") for index in range(11)]
    config = SegmentFirstConfig(
        patch_root=paths[0],
        swsd_road_path=paths[1],
        swsd_node_path=paths[2],
        t01_road_path=paths[3],
        t01_node_path=paths[4],
        t01_segment_path=paths[5],
        t07_surface_path=paths[6],
        t03_surface_path=paths[7],
        t04_surface_path=paths[8],
        full_rcsd_road_path=paths[9],
        full_rcsd_node_path=paths[10],
        output_dir=Path("output"),
        run_id="run",
    )
    carriers = gpd.GeoDataFrame(
        [
            {
                "segment_id": "advance-right-1",
                "segment_type": "advance_right",
                "target_class": "advance_right",
                "member_swsd_road_id": "",
                "carrier_role": "main_oneway",
                "carrier_id": "carrier-1",
                "direction_role": "forward",
                "movement_parent_carrier_id": "movement-parent-1",
                "realization": "built",
                "geometry_source": "hp_observed",
                "patch_road_key": "patch:road:1",
                "source_patch_road_keys": "patch:road:1",
                "access_support_access_ids": "segment:through:0",
                "constrained_completion_access_ids": "segment:through:1",
                "start_access_ids": "segment:endpoint:0",
                "end_access_ids": "segment:through:0",
                "start_junction_group_ids": "junction-start",
                "end_junction_group_ids": "junction-through",
                "source_patch_ids": "patch",
                "source_lane_ids": "lane-1",
                "evidence_quality_state": "usable",
                "geometry": LineString([(0.0, 0.0), (20.0, 0.0)]),
            }
        ],
        crs="EPSG:32650",
    )
    swsd_roads = gpd.GeoDataFrame(
        {"id": [], "geometry": []}, geometry="geometry", crs=carriers.crs
    )

    result = materialize_road_geometry(carriers, swsd_roads, config=config)

    assert result.roads.iloc[0]["segment_type"] == "advance_right"
    assert result.roads.iloc[0]["target_class"] == "advance_right"
    assert result.roads.iloc[0]["carrier_id"] == "carrier-1"
    assert result.roads.iloc[0]["direction_role"] == "forward"
    assert (
        result.roads.iloc[0]["movement_parent_carrier_id"]
        == "movement-parent-1"
    )
    assert (
        result.roads.iloc[0]["constrained_completion_access_ids"]
        == "segment:through:1"
    )
    assert (
        result.roads.iloc[0]["access_support_access_ids"]
        == "segment:through:0"
    )
    assert result.roads.iloc[0]["start_access_ids"] == "segment:endpoint:0"
    assert result.roads.iloc[0]["end_access_ids"] == "segment:through:0"
    assert (
        result.roads.iloc[0]["start_junction_group_ids"] == "junction-start"
    )
    assert (
        result.roads.iloc[0]["end_junction_group_ids"] == "junction-through"
    )


def test_retained_partial_gets_stable_new_id_and_only_outer_node_lineage() -> None:
    paths = [Path(f"input-{index}") for index in range(11)]
    config = SegmentFirstConfig(
        patch_root=paths[0],
        swsd_road_path=paths[1],
        swsd_node_path=paths[2],
        t01_road_path=paths[3],
        t01_node_path=paths[4],
        t01_segment_path=paths[5],
        t07_surface_path=paths[6],
        t03_surface_path=paths[7],
        t04_surface_path=paths[8],
        full_rcsd_road_path=paths[9],
        full_rcsd_node_path=paths[10],
        output_dir=Path("output"),
        run_id="run",
    )
    swsd_roads = gpd.GeoDataFrame(
        [
            {
                "id": 100,
                "snodeid": 10,
                "enodeid": 20,
                "direction": 2,
                "source": 2,
                "geometry": LineString([(0.0, 0.0), (20.0, 0.0)]),
            }
        ],
        crs="EPSG:32650",
    )
    carriers = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s",
                "segment_type": "normal",
                "target_class": "not_target",
                "member_swsd_road_id": "100",
                "carrier_role": "semantic_carrier",
                "carrier_id": "retained-part:100:prefix:0:10",
                "direction_role": "",
                "realization": "retained",
                "geometry_source": "swsd_retained_partial",
                "inherit_source_snodeid": True,
                "inherit_source_enodeid": False,
                "assembly_state": "retained_partial_after_hp_observation",
                "geometry": LineString([(0.0, 0.0), (10.0, 0.0)]),
            }
        ],
        crs=swsd_roads.crs,
    )

    first = materialize_road_geometry(carriers, swsd_roads, config=config)
    second = materialize_road_geometry(carriers, swsd_roads, config=config)
    road = first.roads.iloc[0]

    assert road["id"] != 100
    assert road["id"] == second.roads.iloc[0]["id"]
    assert road["source_snodeid"] == "10"
    assert road["source_enodeid"] == ""
    assert road["geometry_source"] == "swsd_retained_partial"
