from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from rcsd_topo_poc.modules.p04_road_direct_generation.high_precision_config import (
    HighPrecisionRoadV3Config,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.high_precision_geometry import (
    instantiate_high_precision_geometries,
    reconcile_final_road_geometries,
)


CRS = "EPSG:32650"


def _config(tmp_path) -> HighPrecisionRoadV3Config:
    return HighPrecisionRoadV3Config(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "out",
        run_id="v3-geometry-test",
        fit_station_spacing_m=5.0,
        anchor_max_distance_m=8.0,
        max_lateral_slope=0.15,
        drivezone_tolerance_m=0.25,
    )


def _road_unit() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "v3_road_id": "r1",
                "parent_swsd_unit_id": "r1",
                "road_representation": "shared_physical",
                "travel_side": "shared",
                "direction": 1,
                "split_decision": "shared",
                "split_reason_codes": "single_physical_corridor",
                "source_patch_ids": "p1",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        geometry="geometry",
        crs=CRS,
    )


def _lane(start: float, end: float, y: float, lane_id: str = "lane-1") -> dict:
    return {
        "v3_road_id": "r1",
        "lane_id": lane_id,
        "source_patch_ids": "p1",
        "evidence_quality_state": "usable",
        "geometry_role": "hard_geometry",
        "geometry": LineString([(start, y), (end, y)]),
    }


def _lanes(*rows: dict) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(list(rows), geometry="geometry", crs=CRS)


def _drivezone(xmin: float, xmax: float, ymin: float, ymax: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [{"patch_id": "p1", "geometry": Polygon([(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)])}],
        geometry="geometry",
        crs=CRS,
    )


def test_direct_observation_and_constrained_extension_are_not_conflated(tmp_path) -> None:
    result = instantiate_high_precision_geometries(
        _road_unit(),
        _lanes(_lane(20, 80, 4)),
        _drivezone(-5, 105, 2, 6),
        config=_config(tmp_path),
    )

    sources = set(result.geometry_segments["geometry_source"])
    assert sources == {"hp_observed", "hp_constrained_interpolation"}
    road = result.road_candidates.iloc[0]
    assert road.observed_length_m < road.geometry.length
    assert road.constrained_length_m > 0
    assert road.swsd_fallback_length_m == pytest.approx(0.0, abs=1e-6)
    assert road.high_precision_control_ratio >= 0.8


def test_drivezone_failure_falls_back_only_outside_observed_span(tmp_path) -> None:
    result = instantiate_high_precision_geometries(
        _road_unit(),
        _lanes(_lane(20, 80, 4)),
        _drivezone(15, 85, 2, 6),
        config=_config(tmp_path),
    )

    road = result.road_candidates.iloc[0]
    assert road.observed_length_m > 0
    assert road.swsd_fallback_length_m > 0
    assert set(result.geometry_segments["geometry_source"]) == {
        "hp_observed",
        "swsd_fallback",
    }
    assert "drivezone" in ";".join(result.control_spans["reason_codes"])


def test_internal_gap_uses_two_sided_high_precision_interpolation(tmp_path) -> None:
    result = instantiate_high_precision_geometries(
        _road_unit(),
        _lanes(_lane(0, 30, 2, "lane-left"), _lane(70, 100, 4, "lane-right")),
        _drivezone(-5, 105, -1, 6),
        config=_config(tmp_path),
    )

    middle = result.fit_stations[
        result.fit_stations["station_offset_m"].between(40.0, 60.0)
    ]
    assert set(middle["geometry_source"]) == {"hp_constrained_interpolation"}
    assert middle.iloc[0].applied_lateral_shift_m < middle.iloc[-1].applied_lateral_shift_m


def test_geometry_source_segments_cover_whole_road_without_overlap(tmp_path) -> None:
    result = instantiate_high_precision_geometries(
        _road_unit(),
        _lanes(_lane(20, 80, 3)),
        _drivezone(15, 85, 1, 5),
        config=_config(tmp_path),
    )

    segments = result.geometry_segments.sort_values("start_fraction")
    assert segments.iloc[0].start_fraction == pytest.approx(0.0)
    assert segments.iloc[-1].end_fraction == pytest.approx(1.0)
    assert all(
        left == pytest.approx(right)
        for left, right in zip(segments["end_fraction"].iloc[:-1], segments["start_fraction"].iloc[1:])
    )
    assert result.road_candidates.iloc[0].geometry.is_valid
    assert result.road_candidates.iloc[0].geometry.is_simple


def test_endpoint_coordination_is_republished_as_constrained_not_observed(
    tmp_path,
) -> None:
    config = _config(tmp_path)
    result = instantiate_high_precision_geometries(
        _road_unit(),
        _lanes(_lane(0, 100, 3)),
        _drivezone(-5, 105, 1, 5),
        config=config,
    )
    final_roads = result.road_candidates.copy()
    final_roads.at[0, "geometry"] = LineString([(0, 1), (40, 3), (100, 3)])
    final_roads["start_endpoint_coordination_shift_m"] = 2.0
    final_roads["end_endpoint_coordination_shift_m"] = 0.0
    final_roads["start_endpoint_source"] = "physical_node_global_shared_portal"
    final_roads["end_endpoint_source"] = "road_geometry_retained"

    reconciled = reconcile_final_road_geometries(
        result,
        final_roads,
        config=config,
    )

    assert set(reconciled.geometry_segments["geometry_source"]) == {
        "hp_observed",
        "hp_constrained_interpolation",
    }
    union = unary_union(reconciled.geometry_segments.geometry)
    assert union.hausdorff_distance(final_roads.iloc[0].geometry) == pytest.approx(
        0.0, abs=1e-8
    )
    start = reconciled.fit_stations.sort_values("station_fraction").iloc[0]
    assert not bool(start.direct_observation)
    assert start.geometry_source == "hp_constrained_interpolation"
