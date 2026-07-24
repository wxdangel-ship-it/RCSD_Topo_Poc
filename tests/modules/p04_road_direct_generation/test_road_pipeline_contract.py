from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    MilestoneTwoConfig,
    run_milestone_two,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.road_pipeline import (
    _core_gates,
    _road_topology_summary,
)


def test_milestone_two_reuses_milestone_one_in_an_isolated_subdirectory(tmp_path: Path) -> None:
    config = MilestoneTwoConfig(
        patch_root=tmp_path / "patches",
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "m2",
        run_id="run-m2",
    )

    milestone_one = config.milestone_one_config()

    assert milestone_one.output_dir == tmp_path / "m2" / "_milestone1"
    assert milestone_one.run_id == "run-m2_m1"
    assert callable(run_milestone_two)


def test_road_topology_requires_one_anchored_arm_per_road_endpoint() -> None:
    roads = gpd.GeoDataFrame(
        [{"swsd_unit_id": "r1", "geometry": LineString([(0, 0), (10, 0)])}],
        crs="EPSG:32650",
    )
    junctions = gpd.GeoDataFrame(
        [{"junction_id": "j1", "geometry": Point(0, 0)}],
        crs=roads.crs,
    )
    arms = gpd.GeoDataFrame(
        [
            {"swsd_unit_id": "r1", "endpoint": "s", "junction_id": "j1", "geometry": LineString([(0, 0), (0, 1)])},
            {"swsd_unit_id": "r1", "endpoint": "e", "junction_id": None, "geometry": LineString([(10, 0), (10, 1)])},
        ],
        crs=roads.crs,
    )

    result = _road_topology_summary(roads, junctions, arms)

    assert result["road_topology_gate_pass"]
    assert result["road_arm_portal_max_delta_m"] == pytest.approx(0.0)

    arms.loc[1, "geometry"] = LineString([(11, 0), (11, 1)])
    result = _road_topology_summary(roads, junctions, arms)
    assert not result["road_topology_gate_pass"]
    assert result["road_arm_portal_max_delta_m"] == pytest.approx(1.0)


def test_core_gates_return_a_complete_mapping(tmp_path: Path) -> None:
    config = MilestoneTwoConfig(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "out",
        run_id="gate-test",
        expected_road_count=1,
    )
    roads = gpd.GeoDataFrame(
        [{"swsd_unit_id": "r1", "geometry": LineString([(0, 0), (1, 0)])}],
        crs="EPSG:32650",
    )
    gates = _core_gates(
        config,
        milestone_one_core_pass=True,
        evidence_summary={
            "known_quality_counts": {},
            "road_conservation_gate_pass": True,
            "interval_partition_gate_pass": True,
            "quality_flag_direct_road_conflict_count": 0,
            "road_count": 1,
        },
        geometry_summary={
            "road_geometry_gate_pass": True,
            "endpoint_anchor_gate_pass": True,
            "sd_only_zero_shift_gate_pass": True,
        },
        topology_summary={"road_topology_gate_pass": True},
        road_candidates=roads,
    )

    assert gates["road_arm_portal_topology"]
    assert gates["expected_road_count"]
    assert all(gates.values())
