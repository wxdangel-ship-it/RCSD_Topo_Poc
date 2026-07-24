from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.directional_quality import (
    run_directional_quality_audit,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.io import write_gpkg_layers


def test_independent_quality_accepts_closed_smooth_package(tmp_path: Path) -> None:
    _write_package(tmp_path, broken=False)

    result = run_directional_quality_audit(tmp_path)

    assert result["gate_pass"]
    assert result["physical_node"]["violation_count"] == 0
    assert result["road"]["turn_violation_count"] == 0
    assert result["movement"]["violation_count"] == 0
    assert result["long_sd_gap_review"]["declaration_mismatch_count"] == 0
    assert (tmp_path / "p04_directional_independent_quality.json").is_file()
    assert (tmp_path / "p04_directional_independent_quality.gpkg").is_file()


def test_independent_quality_rejects_gap_kink_and_bad_movement(tmp_path: Path) -> None:
    _write_package(tmp_path, broken=True)

    result = run_directional_quality_audit(tmp_path)

    assert not result["gate_pass"]
    assert result["physical_node"]["violation_count"] == 1
    assert result["road"]["turn_violation_count"] == 1
    assert result["movement"]["violation_count"] == 1
    assert set(result["fail_reasons"]) == {
        "all_physical_nodes_closed",
        "supported_road_smoothness",
        "movement_portal_and_tangent",
    }


def test_independent_quality_rejects_published_cross_direction_collapse(
    tmp_path: Path,
) -> None:
    _write_package(tmp_path, broken=False, direction_collapse=True)

    result = run_directional_quality_audit(tmp_path)

    assert not result["gate_pass"]
    assert result["direction_pair"]["violation_count"] == 1
    assert result["fail_reasons"] == ["cross_direction_high_precision_separation"]


def _write_package(
    root: Path,
    *,
    broken: bool,
    direction_collapse: bool = False,
) -> None:
    crs = "EPSG:32650"
    first_geometry = (
        LineString([(0, 0), (5, 0), (6, 4), (10, 0)])
        if broken
        else LineString([(0, 0), (10, 0)])
    )
    second_geometry = (
        LineString([(12, 0), (20, 0)])
        if broken
        else LineString([(10, 0), (20, 0)])
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "run_id": "quality-test",
                "directional_road_id": "r1:forward",
                "travel_side": "forward",
                "parent_swsd_unit_id": "r1",
                "snode_id": "n1",
                "enode_id": "n2",
                "support_state": "hp_supported",
                "geometry": first_geometry,
            },
            {
                "run_id": "quality-test",
                "directional_road_id": "r2:forward",
                "travel_side": "forward",
                "parent_swsd_unit_id": "r2",
                "snode_id": "n2",
                "enode_id": "n3",
                "support_state": "partial_hp_supported",
                "geometry": second_geometry,
            },
        ],
        crs=crs,
    )
    parents = gpd.GeoDataFrame(
        [
            {
                "swsd_unit_id": "r1",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "swsd_unit_id": "r2",
                "geometry": LineString([(10, 0), (20, 0)]),
            },
        ],
        crs=crs,
    )
    movement_geometry = (
        LineString([(10, 0), (8, 1), (12, 0)])
        if broken
        else LineString([(9.5, 0), (10, 0), (10.5, 0)])
    )
    movements = gpd.GeoDataFrame(
        [
            {
                "run_id": "quality-test",
                "directional_movement_id": "M000001",
                "source_directional_road_id": "r1:forward",
                "target_directional_road_id": "r2:forward",
                "junction_relation": "same_physical_node",
                "geometry_source": "test",
                "geometry": movement_geometry,
            }
        ],
        crs=crs,
    )
    cross_direction_rows = [
        {
            "parent_swsd_unit_id": "qa_parent",
            "travel_side": "forward",
            "required_min_separation_m": 1.5,
            "anchor_gate_pass": True,
            "geometry": LineString([(0, 30), (10, 30)]),
        },
        {
            "parent_swsd_unit_id": "qa_parent",
            "travel_side": "reverse",
            "required_min_separation_m": 1.5,
            "anchor_gate_pass": True,
            "geometry": LineString([(10, 33), (0, 33)]),
        },
    ]
    geometry_segment_rows = [
        {"directional_road_id": "r1:forward", "parent_swsd_unit_id": "r1", "travel_side": "forward", "interval_state": "hp_supported", "geometry": first_geometry},
        {"directional_road_id": "r2:forward", "parent_swsd_unit_id": "r2", "travel_side": "forward", "interval_state": "hp_supported", "geometry": second_geometry},
    ]
    support_interval_rows = [
        {"directional_road_id": "r1:forward", "interval_state": "hp_supported", "interval_length_m": float(first_geometry.length), "geometry": first_geometry},
        {"directional_road_id": "r2:forward", "interval_state": "hp_supported", "interval_length_m": float(second_geometry.length), "geometry": second_geometry},
    ]
    if direction_collapse:
        roads = gpd.GeoDataFrame(
            [
                *roads.to_dict("records"),
                {"run_id": "quality-test", "directional_road_id": "c:forward", "travel_side": "forward", "parent_swsd_unit_id": "c", "snode_id": "n1", "enode_id": "n2", "support_state": "hp_supported", "geometry": LineString([(0, 0), (10, 0)])},
                {"run_id": "quality-test", "directional_road_id": "c:reverse", "travel_side": "reverse", "parent_swsd_unit_id": "c", "snode_id": "n2", "enode_id": "n1", "support_state": "hp_supported", "geometry": LineString([(10, 0), (5, 0.2), (0, 0)])},
            ],
            crs=crs,
        )
        parents = gpd.GeoDataFrame(
            [*parents.to_dict("records"), {"swsd_unit_id": "c", "geometry": LineString([(0, 0), (10, 0)])}],
            crs=crs,
        )
        cross_direction_rows.extend(
            [
                {"parent_swsd_unit_id": "c", "travel_side": "forward", "required_min_separation_m": 1.5, "anchor_gate_pass": False, "geometry": LineString([(0, 0), (10, 0)])},
                {"parent_swsd_unit_id": "c", "travel_side": "reverse", "required_min_separation_m": 1.5, "anchor_gate_pass": False, "geometry": LineString([(10, 0.2), (0, 0.2)])},
            ]
        )
        geometry_segment_rows.extend(
            [
                {"directional_road_id": "c:forward", "parent_swsd_unit_id": "c", "travel_side": "forward", "interval_state": "hp_supported", "geometry": LineString([(0, 0.1), (10, 0.1)])},
                {"directional_road_id": "c:reverse", "parent_swsd_unit_id": "c", "travel_side": "reverse", "interval_state": "hp_supported", "geometry": LineString([(10, 0.2), (0, 0.2)])},
            ]
        )
    cross_direction = gpd.GeoDataFrame(cross_direction_rows, crs=crs)
    geometry_segments = gpd.GeoDataFrame(geometry_segment_rows, crs=crs)
    support_intervals = gpd.GeoDataFrame(support_interval_rows, crs=crs)
    write_gpkg_layers(
        root / "p04_directional_roads.gpkg",
        {"directional_roads": roads},
    )
    write_gpkg_layers(
        root / "p04_directional_movements.gpkg",
        {"directional_movements": movements},
    )
    write_gpkg_layers(
        root / "p04_directional_road_graph.gpkg",
        {"parent_swsd_roads": parents},
    )
    write_gpkg_layers(
        root / "p04_directional_lane_groups.gpkg",
        {"cross_direction_quality_audit": cross_direction},
    )
    write_gpkg_layers(
        root / "p04_directional_support_intervals.gpkg",
        {"support_intervals": support_intervals, "geometry_segments": geometry_segments},
    )
