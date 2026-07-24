from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.road_config import MilestoneTwoConfig
from rcsd_topo_poc.modules.p04_road_direct_generation.road_evidence import (
    build_road_evidence,
    build_support_intervals,
    classify_support_state,
)


def _config(tmp_path: Path) -> MilestoneTwoConfig:
    return MilestoneTwoConfig(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "out",
        run_id="m2-test",
        analysis_crs="EPSG:32650",
    )


def test_four_support_states_have_explicit_precedence() -> None:
    common = {
        "full_coverage_ratio": 0.95,
        "full_max_gap_m": 10.0,
    }
    assert classify_support_state(
        has_support=True,
        coverage_ratio=1.0,
        max_gap_m=0.0,
        credible_structure_conflict=False,
        **common,
    ) == "hp_supported"
    assert classify_support_state(
        has_support=True,
        coverage_ratio=0.80,
        max_gap_m=20.0,
        credible_structure_conflict=False,
        **common,
    ) == "partial_hp_supported"
    assert classify_support_state(
        has_support=False,
        coverage_ratio=0.0,
        max_gap_m=100.0,
        credible_structure_conflict=False,
        **common,
    ) == "sd_only"
    assert classify_support_state(
        has_support=True,
        coverage_ratio=1.0,
        max_gap_m=0.0,
        credible_structure_conflict=True,
        **common,
    ) == "conflict_retained"


def test_support_intervals_conserve_every_road_and_keep_quality_out_of_conflict() -> None:
    crs = "EPSG:32650"
    roads = gpd.GeoDataFrame(
        [
            {
                "swsd_unit_id": road_id,
                "all_patch_ids": "p1",
                "snode_id": f"n{index}",
                "enode_id": f"n{index + 1}",
                "geometry": LineString([(0, index * 10), (100, index * 10)]),
            }
            for index, road_id in enumerate(("full", "partial", "none", "conflict", "point_only"))
        ],
        crs=crs,
    )
    segments = gpd.GeoDataFrame(
        [
            _segment("l1", "full", 0, 100, 0),
            _segment("l2", "partial", 20, 80, 10),
            _segment("l3", "conflict", 0, 100, 30),
            _segment("l4", "point_only", 100, 100, 40),
        ],
        crs=crs,
    )

    intervals, audit = build_support_intervals(
        roads,
        segments,
        run_id="test",
        full_coverage_ratio=0.95,
        max_gap_m=10.0,
        credible_conflict_road_ids={"conflict"},
    )

    states = audit.set_index("swsd_unit_id")["support_state"].to_dict()
    assert states == {
        "full": "hp_supported",
        "partial": "partial_hp_supported",
        "none": "sd_only",
        "conflict": "conflict_retained",
        "point_only": "sd_only",
    }
    partition = intervals.groupby("swsd_unit_id")["interval_length_m"].sum()
    assert partition.to_dict() == {road_id: 100.0 for road_id in states}
    assert not ((intervals["interval_state"] == "hp_supported") & (intervals["interval_length_m"] == 0)).any()
    assert audit.loc[audit["swsd_unit_id"] == "partial", "evidence_quality_state"].item() == "clean"


def test_one_source_lane_can_form_unique_segments_on_adjacent_swsd_roads(tmp_path: Path) -> None:
    crs = "EPSG:32650"
    roads = gpd.GeoDataFrame(
        [
            {
                "swsd_unit_id": "r1",
                "all_patch_ids": "p1",
                "snode_id": "n1",
                "enode_id": "n2",
                "semantic_snode_id": "n1",
                "semantic_enode_id": "n2",
                "direction": 2,
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "swsd_unit_id": "r2",
                "all_patch_ids": "p1",
                "snode_id": "n2",
                "enode_id": "n3",
                "semantic_snode_id": "n2",
                "semantic_enode_id": "n3",
                "direction": 2,
                "geometry": LineString([(10, 0), (20, 0)]),
            },
        ],
        crs=crs,
    )
    lanes = gpd.GeoDataFrame(
        [
            {
                "lane_id": "lane-crossing-two-roads",
                "source_patch_ids": "p1",
                "swsd_unit_id": "r1",
                "decision": "accepted",
                "owner_state": "accepted",
                "width_state": "nominal",
                "drivezone_coverage": 1.0,
                "reason_codes": "owner_unique_supported;width_nominal",
                "geometry": LineString([(0, 1), (20, 1)]),
            }
        ],
        crs=crs,
    )
    topology = gpd.GeoDataFrame(
        columns=[
            "link_id",
            "source_patch_ids",
            "lane_topo_state",
            "source_owner",
            "target_owner",
            "geometry",
        ],
        geometry="geometry",
        crs=crs,
    )

    result = build_road_evidence(lanes, roads, topology, config=_config(tmp_path))

    assert result.lane_segments["lane_id"].nunique() == 1
    assert set(result.lane_segments["swsd_unit_id"]) == {"r1", "r2"}
    assert result.lane_segments.groupby(["lane_id", "source_start_m", "source_end_m"]).size().max() == 1
    assert result.summary["road_conservation_gate_pass"]
    assert result.summary["quality_flag_direct_road_conflict_count"] == 0


def _segment(lane_id: str, road_id: str, start: float, end: float, y: float) -> dict[str, object]:
    return {
        "lane_id": lane_id,
        "source_patch_ids": "p1",
        "swsd_unit_id": road_id,
        "road_start_m": start,
        "road_end_m": end,
        "fit_weight": 1.0,
        "evidence_quality_state": "usable",
        "geometry": LineString([(start, y), (end, y)]),
    }
