from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_carriers import (
    plan_segment_carriers,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_evidence import (
    _explicit_road_pairs,
    build_patch_road_centers,
    orient_patch_road_centers,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_junctions import (
    build_junction_units,
    endpoint_surface_geometry,
)


def test_center_lane_is_not_mechanically_leftmost() -> None:
    roads = gpd.GeoDataFrame(
        [{"Id": 10, "source_patch_id": "p", "geometry": LineString([(0, 0), (100, 0)])}],
        crs="EPSG:32650",
    )
    lanes = gpd.GeoDataFrame(
        [
            {"Id": 1, "RoadId": 10, "Width": 3.5, "IsLeftmost": True, "source_patch_id": "p", "geometry": LineString([(0, 0), (100, 0)])},
            {"Id": 2, "RoadId": 10, "Width": 3.5, "IsLeftmost": False, "source_patch_id": "p", "geometry": LineString([(0, 3.5), (100, 3.5)])},
            {"Id": 3, "RoadId": 10, "Width": 3.5, "IsLeftmost": False, "source_patch_id": "p", "geometry": LineString([(0, 7), (100, 7)])},
        ],
        crs="EPSG:32650",
    )
    centers, relations = build_patch_road_centers(roads, lanes, run_id="run")
    assert centers.iloc[0]["center_lane_id"] == "2"
    assert centers.iloc[0]["centerline_method"] == "patch_road_lane_median_offset"
    assert abs(centers.iloc[0].geometry.interpolate(0.5, normalized=True).y - 3.5) < 0.1
    assert set(relations["lane_id"]) == {"1", "2", "3"}


def test_centered_patch_road_keeps_full_longitudinal_span_when_medoid_lane_is_short() -> None:
    roads = gpd.GeoDataFrame(
        [{"Id": 10, "source_patch_id": "p", "geometry": LineString([(0, 0), (100, 0)])}],
        crs="EPSG:32650",
    )
    lanes = gpd.GeoDataFrame(
        [
            {"Id": 1, "RoadId": 10, "Width": 3.5, "IsLeftmost": True, "source_patch_id": "p", "geometry": LineString([(0, 0), (100, 0)])},
            {"Id": 2, "RoadId": 10, "Width": 3.5, "IsLeftmost": False, "source_patch_id": "p", "geometry": LineString([(40, 3), (60, 3)])},
            {"Id": 3, "RoadId": 10, "Width": 3.5, "IsLeftmost": False, "source_patch_id": "p", "geometry": LineString([(0, 6), (100, 6)])},
        ],
        crs="EPSG:32650",
    )
    centers, _ = build_patch_road_centers(roads, lanes, run_id="run")
    center = centers.iloc[0]
    assert center["center_lane_id"] == "2"
    assert center["center_lane_span_ratio"] == 0.2
    assert center.geometry.length > 99.0
    assert abs(center.geometry.interpolate(0.5, normalized=True).y - 3.0) < 0.1


def test_t04_topology_uses_t07_human_surface_for_same_mainnode() -> None:
    polygon = Point(0, 0).buffer(10)
    t07 = gpd.GeoDataFrame([{"mainnodeid": "m", "geometry": polygon}], crs="EPSG:32650")
    t03 = gpd.GeoDataFrame([{"mainnodeid": "m", "geometry": polygon.buffer(1)}], crs="EPSG:32650")
    t04 = gpd.GeoDataFrame([{"mainnodeid": "m", "anchor_id": "a", "geometry": polygon.buffer(2)}], crs="EPSG:32650")
    accesses = gpd.GeoDataFrame(
        [{"access_id": "a1", "junction_group_id": "m", "geometry": Point(0, 0)}],
        crs="EPSG:32650",
    )
    result = build_junction_units(t07, t03, t04, accesses, run_id="run")
    assert result.junction_units.iloc[0]["junction_source"] == "t04_accepted"
    assert result.junction_units.iloc[0]["junction_kind"] == "complex_divmerge"
    assert result.junction_units.iloc[0]["surface_source"] == "t07_accepted"
    assert result.junction_units.iloc[0].geometry.equals(polygon.buffer(2))
    assert endpoint_surface_geometry(
        result.junction_units.iloc[0]
    ).equals(polygon)


def test_retained_kind2_128_group_stays_explicit_physical_complex() -> None:
    empty_surfaces = gpd.GeoDataFrame(
        geometry=[],
        crs="EPSG:32650",
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "a1",
                "junction_group_id": "100",
                "geometry": Point(0, 0),
            }
        ],
        crs="EPSG:32650",
    )
    t01_nodes = gpd.GeoDataFrame(
        [
            {
                "id": 101,
                "mainnodeid": 100,
                "kind_2": 128,
                "geometry": Point(0, 0),
            }
        ],
        crs="EPSG:32650",
    )

    result = build_junction_units(
        empty_surfaces,
        empty_surfaces,
        empty_surfaces,
        accesses,
        t01_nodes=t01_nodes,
        run_id="run",
    )

    junction = result.junction_units.iloc[0]
    assert junction["junction_source"] == "swsd_retained"
    assert junction["junction_kind"] == "complex_divmerge"
    assert junction["topology_mode"] == "explicit_physical"


def test_partial_plan_is_complete_road_level_built_and_retained() -> None:
    segments = gpd.GeoDataFrame(
        [{"segment_id": "s", "swsd_road_ids": "r1,r2", "geometry": LineString([(0, 0), (10, 0)])}],
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {"id": "r1", "segmentid": "s", "direction": 2, "geometry": LineString([(0, 0), (10, 0)])},
            {"id": "r2", "segmentid": "s", "direction": 2, "geometry": LineString([(10, 0), (20, 0)])},
        ],
        crs="EPSG:32650",
    )
    evidence = gpd.GeoDataFrame(
        [{"patch_road_key": "p:1", "assigned_segment_id": "s", "target_swsd_road_id": "r1", "takeover_eligible": True, "geometry": LineString([(0, 1), (10, 1)])}],
        crs="EPSG:32650",
    )
    result = plan_segment_carriers(segments, swsd, evidence, run_id="run")
    plan = result.segment_plans.iloc[0]
    assert plan["segment_state"] == "hp_partial"
    assert plan["replacement_scope"] == "subset"
    assert set(result.carriers["realization"]) == {"built", "retained"}

    fallback = plan_segment_carriers(
        segments,
        swsd,
        evidence,
        run_id="run",
        forced_retained_segment_ids={"s"},
    )
    assert fallback.segment_plans.iloc[0]["segment_state"] == "conflict_retained"
    assert set(fallback.carriers["realization"]) == {"retained"}


def test_lane_topo_is_explicit_physical_road_pair_evidence() -> None:
    assignments = gpd.GeoDataFrame(
        [
            {"patch_road_key": "p:1", "geometry": Point(0, 0)},
            {"patch_road_key": "p:2", "geometry": Point(1, 0)},
        ],
        crs="EPSG:32650",
    )
    patch_road_next_road = gpd.GeoDataFrame(
        columns=["source_patch_id", "RoadId", "NextRoadId", "Id", "geometry"],
        geometry="geometry",
        crs="EPSG:32650",
    )
    lane_topo = gpd.GeoDataFrame(
        [
            {
                "lane_topo_id": "p:101",
                "source_patch_road_key": "p:1",
                "target_patch_road_key": "p:2",
                "geometry": Point(0.5, 0),
            }
        ],
        crs="EPSG:32650",
    )
    result = _explicit_road_pairs(
        patch_road_next_road,
        assignments,
        lane_topo,
    )
    assert result.iloc[0]["pair_source"] == "lane_topo"
    assert result.iloc[0]["source_patch_road_key"] == "p:1"
    assert result.iloc[0]["target_patch_road_key"] == "p:2"


def test_lane_topo_preserves_direct_lane_pair_for_lane_carrier_paths() -> None:
    assignments = gpd.GeoDataFrame(
        [
            {"patch_road_key": "p:lane:11", "geometry": Point(0, 0)},
            {"patch_road_key": "p:lane:12", "geometry": Point(1, 0)},
        ],
        crs="EPSG:32650",
    )
    patch_road_next_road = gpd.GeoDataFrame(
        columns=["source_patch_id", "RoadId", "NextRoadId", "Id", "geometry"],
        geometry="geometry",
        crs="EPSG:32650",
    )
    lane_topo = gpd.GeoDataFrame(
        [
            {
                "lane_topo_id": "p:101",
                "source_lane_carrier_key": "p:lane:11",
                "target_lane_carrier_key": "p:lane:12",
                "source_patch_road_key": "p:1",
                "target_patch_road_key": "p:1",
                "geometry": Point(0.5, 0),
            }
        ],
        crs="EPSG:32650",
    )

    result = _explicit_road_pairs(
        patch_road_next_road,
        assignments,
        lane_topo,
    )

    assert len(result) == 1
    assert result.iloc[0]["pair_source"] == "lane_topo_lane"
    assert result.iloc[0]["source_patch_road_key"] == "p:lane:11"
    assert result.iloc[0]["target_patch_road_key"] == "p:lane:12"


def test_lane_topo_keeps_raw_keys_before_publication_mapping() -> None:
    assignments = gpd.GeoDataFrame(
        [{"patch_road_key": "p:other", "geometry": Point(0, 0)}],
        crs="EPSG:32650",
    )
    patch_road_next_road = gpd.GeoDataFrame(
        columns=["source_patch_id", "RoadId", "NextRoadId", "Id", "geometry"],
        geometry="geometry",
        crs="EPSG:32650",
    )
    lane_topo = gpd.GeoDataFrame(
        [
            {
                "lane_topo_id": "p:101",
                "source_lane_carrier_key": "p:lane:11",
                "target_lane_carrier_key": "p:lane:12",
                "source_patch_road_key": "p:1",
                "target_patch_road_key": "p:2",
                "geometry": Point(0.5, 0),
            }
        ],
        crs="EPSG:32650",
    )

    result = _explicit_road_pairs(
        patch_road_next_road,
        assignments,
        lane_topo,
    )

    assert set(result["pair_source"]) == {
        "lane_topo",
        "lane_topo_lane",
    }


def test_patch_road_center_orientation_follows_road_next_road() -> None:
    centers = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "p:1",
                "source_patch_id": "p",
                "road_id": "1",
                "geometry": LineString([(10, 0), (0, 0)]),
            },
            {
                "patch_road_key": "p:2",
                "source_patch_id": "p",
                "road_id": "2",
                "geometry": LineString([(10, 0), (20, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    road_next_road = gpd.GeoDataFrame(
        [
            {
                "source_patch_id": "p",
                "RoadId": 1,
                "NextRoadId": 2,
                "geometry": Point(10, 0),
            }
        ],
        crs=centers.crs,
    )

    result = orient_patch_road_centers(centers, road_next_road)

    first = result.set_index("patch_road_key").loc["p:1"]
    assert first["orientation_state"] == "reversed_by_road_topology"
    assert tuple(first.geometry.coords[0]) == (0.0, 0.0)
    assert tuple(first.geometry.coords[-1]) == (10.0, 0.0)
