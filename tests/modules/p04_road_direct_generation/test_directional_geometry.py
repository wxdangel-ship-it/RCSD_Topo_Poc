from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.directional_config import (
    DirectionalRoadV2Config,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.directional_geometry import (
    instantiate_directional_geometries,
)


def _config(tmp_path: Path) -> DirectionalRoadV2Config:
    return DirectionalRoadV2Config(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "out",
        run_id="directional-geometry-test",
        fit_station_spacing_m=10.0,
        max_adjacent_lateral_shift_m=1.5,
    )


def test_directional_geometry_uses_stable_anchor_without_returning_to_swsd_portal(
    tmp_path: Path,
) -> None:
    crs = "EPSG:32650"
    reference = LineString([(0, 0), (100, 0)])
    units = gpd.GeoDataFrame(
        [
            _unit("r1:forward", "forward", "a1", reference),
            _unit("r1:reverse", "reverse", "a2", reference),
        ],
        crs=crs,
    )
    lane_segments = gpd.GeoDataFrame(
        [
            _segment("r1:forward", "f1", 4.0),
            _segment("r1:forward", "f2", 6.0),
            _segment("r1:reverse", "r1", -4.0, reverse=True),
            _segment("r1:reverse", "r2", -6.0, reverse=True),
        ],
        crs=crs,
    )
    anchors = gpd.GeoDataFrame(
        [
            _anchor("r1:forward", "forward", "a1", 5.0),
            _anchor("r1:reverse", "reverse", "a2", -5.0, reverse=True),
        ],
        crs=crs,
    )
    intervals = gpd.GeoDataFrame(
        [
            _interval("r1:forward", "forward", 0.0, 1.0, reference),
            _interval("r1:reverse", "reverse", 0.0, 1.0, reference),
        ],
        crs=crs,
    )

    result = instantiate_directional_geometries(
        units,
        lane_segments,
        anchors,
        intervals,
        config=_config(tmp_path),
    )
    roads = result.road_candidates.set_index("travel_side")

    assert roads.loc["forward"].geometry.coords[0][1] == 5.0
    assert roads.loc["forward"].geometry.coords[-1][1] == 5.0
    assert roads.loc["reverse"].geometry.coords[0][0] == 100.0
    assert roads.loc["reverse"].geometry.coords[-1][0] == 0.0
    assert roads.loc["reverse"].geometry.coords[0][1] == -5.0
    assert roads.loc["forward", "start_parent_swsd_portal_delta_m"] == 5.0
    assert result.summary["lane_group_envelope_violation_count"] == 0
    assert result.summary["max_adjacent_lateral_shift_m"] == 0.0
    assert result.summary["road_geometry_gate_pass"]


def test_partial_support_retains_swsd_gap_and_unsupported_endpoints(
    tmp_path: Path,
) -> None:
    crs = "EPSG:32650"
    reference = LineString([(0, 0), (100, 0)])
    unit = _unit("r1:forward", "forward", "a1", reference)
    unit.update(
        {
            "directional_support_state": "partial_hp_supported",
            "support_reason": "directional_support_has_gap",
            "support_coverage_ratio": 0.6,
            "support_length_m": 60.0,
            "gap_length_m": 40.0,
            "max_gap_m": 20.0,
        }
    )
    units = gpd.GeoDataFrame([unit], crs=crs)
    lane_segments = gpd.GeoDataFrame(
        [
            {
                **_segment("r1:forward", "f1", 4.0),
                "road_start_m": 20.0,
                "road_end_m": 80.0,
                "geometry": LineString([(20, 4), (80, 4)]),
            },
            {
                **_segment("r1:forward", "f2", 6.0),
                "road_start_m": 20.0,
                "road_end_m": 80.0,
                "geometry": LineString([(20, 6), (80, 6)]),
            },
        ],
        crs=crs,
    )
    anchors = gpd.GeoDataFrame(
        [
            {
                **_anchor("r1:forward", "forward", "a1", 5.0),
                "geometry": LineString([(20, 5), (80, 5)]),
            }
        ],
        crs=crs,
    )
    intervals = gpd.GeoDataFrame(
        [
            _interval_state("r1:forward", "forward", 0, 0.0, 20.0, "sd_gap", reference),
            _interval_state(
                "r1:forward", "forward", 1, 20.0, 80.0, "hp_supported", reference
            ),
            _interval_state("r1:forward", "forward", 2, 80.0, 100.0, "sd_gap", reference),
        ],
        crs=crs,
    )

    result = instantiate_directional_geometries(
        units,
        lane_segments,
        anchors,
        intervals,
        config=_config(tmp_path),
    )
    road = result.road_candidates.iloc[0]
    gaps = result.fit_stations[~result.fit_stations["support_at_station"]]
    ordered = result.fit_stations.sort_values("parent_station_offset_m")
    station_distances = ordered["parent_station_offset_m"].diff().dropna()
    applied_change = ordered["applied_lateral_shift_m"].diff().abs().dropna()

    assert road.geometry.coords[0][1] == 0.0
    assert road.geometry.coords[-1][1] == 0.0
    assert gaps["applied_lateral_shift_m"].abs().max() == 0.0
    assert set(gaps["station_geometry_source"]) == {"swsd_gap_retained"}
    assert result.summary["unsupported_station_shift_count"] == 0
    assert result.summary["unsupported_endpoint_shift_count"] == 0
    assert station_distances.min() == 10.0
    assert (applied_change <= station_distances * _config(tmp_path).max_lateral_slope + 1e-9).all()
    assert "directional_sd_gap_swsd_retained" in set(
        result.geometry_segments["geometry_source"]
    )
    assert result.summary["road_geometry_gate_pass"]


def _unit(child_id: str, side: str, anchor_id: str, geometry: LineString) -> dict[str, object]:
    return {
        "directional_road_id": child_id,
        "parent_swsd_unit_id": "r1",
        "travel_side": side,
        "road_representation": "directional_child",
        "original_direction": 1,
        "direction": 2,
        "snode_id": "n1" if side == "forward" else "n2",
        "enode_id": "n2" if side == "forward" else "n1",
        "semantic_snode_id": "j1" if side == "forward" else "j2",
        "semantic_enode_id": "j2" if side == "forward" else "j1",
        "directional_support_state": "hp_supported",
        "support_reason": "directional_full_longitudinal_support",
        "support_coverage_ratio": 1.0,
        "support_length_m": 100.0,
        "gap_length_m": 0.0,
        "max_gap_m": 0.0,
        "source_lane_ids": "lane",
        "anchor_kind": "lane_boundary",
        "anchor_source_id": anchor_id,
        "geometry": geometry,
    }


def _segment(child_id: str, lane_id: str, y: float, reverse: bool = False) -> dict[str, object]:
    coordinates = [(100, y), (0, y)] if reverse else [(0, y), (100, y)]
    return {
        "directional_road_id": child_id,
        "lane_id": lane_id,
        "road_start_m": 0.0,
        "road_end_m": 100.0,
        "hard_geometry_eligible": True,
        "geometry": LineString(coordinates),
    }


def _anchor(child_id: str, side: str, anchor_id: str, y: float, reverse: bool = False) -> dict[str, object]:
    coordinates = [(100, y), (0, y)] if reverse else [(0, y), (100, y)]
    return {
        "directional_road_id": child_id,
        "parent_swsd_unit_id": "r1",
        "travel_side": side,
        "anchor_kind": "lane_boundary",
        "anchor_source_id": anchor_id,
        "anchor_lane_count": 2,
        "anchor_switch_count": 0,
        "selection_reason": "test",
        "geometry": LineString(coordinates),
    }


def _interval(child_id: str, side: str, start: float, end: float, geometry: LineString) -> dict[str, object]:
    return {
        "directional_road_id": child_id,
        "parent_swsd_unit_id": "r1",
        "travel_side": side,
        "interval_id": child_id + ":0",
        "interval_index": 0,
        "interval_state": "hp_supported",
        "parent_start_m": 0.0,
        "parent_end_m": 100.0,
        "parent_start_fraction": start,
        "parent_end_fraction": end,
        "travel_start_fraction": start,
        "travel_end_fraction": end,
        "source_lane_ids": "lane",
        "source_patch_ids": "p1",
        "geometry": geometry,
    }


def _interval_state(
    child_id: str,
    side: str,
    index: int,
    start_m: float,
    end_m: float,
    state: str,
    geometry: LineString,
) -> dict[str, object]:
    length = float(geometry.length)
    start = start_m / length
    end = end_m / length
    return {
        "directional_road_id": child_id,
        "parent_swsd_unit_id": "r1",
        "travel_side": side,
        "interval_id": f"{child_id}:{index}",
        "interval_index": index,
        "interval_state": state,
        "parent_start_m": start_m,
        "parent_end_m": end_m,
        "parent_start_fraction": start,
        "parent_end_fraction": end,
        "travel_start_fraction": start,
        "travel_end_fraction": end,
        "source_lane_ids": "lane" if state == "hp_supported" else "",
        "source_patch_ids": "p1" if state == "hp_supported" else "",
        "geometry": LineString([(start_m, 0), (end_m, 0)]),
    }
