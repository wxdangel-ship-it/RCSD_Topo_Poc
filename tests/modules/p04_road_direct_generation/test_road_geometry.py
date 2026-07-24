from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.road_config import MilestoneTwoConfig
from rcsd_topo_poc.modules.p04_road_direct_generation.road_geometry import (
    instantiate_road_geometries,
    weighted_median,
)


def _config(tmp_path: Path) -> MilestoneTwoConfig:
    return MilestoneTwoConfig(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "out",
        run_id="geometry-test",
        analysis_crs="EPSG:32650",
        fit_station_spacing_m=10.0,
        fit_transition_length_m=10.0,
    )


def test_weighted_median_is_centered_for_two_equal_lane_weights() -> None:
    assert weighted_median([2.0, 4.0], [1.0, 1.0]) == pytest.approx(3.0)
    assert weighted_median([2.0, 4.0, 20.0], [1.0, 1.0, 0.1]) == pytest.approx(4.0)


def test_road_geometry_fits_supported_range_and_retains_sd_gap(tmp_path: Path) -> None:
    crs = "EPSG:32650"
    roads = gpd.GeoDataFrame(
        [
            {"swsd_unit_id": "full", "geometry": LineString([(0, 0), (100, 0)])},
            {"swsd_unit_id": "partial", "geometry": LineString([(0, 10), (100, 10)])},
            {"swsd_unit_id": "sd", "geometry": LineString([(0, 20), (100, 20)])},
        ],
        crs=crs,
    )
    lane_segments = gpd.GeoDataFrame(
        [
            _lane_segment("f1", "full", 0, 100, 2),
            _lane_segment("f2", "full", 0, 100, 4),
            _lane_segment("p1", "partial", 20, 80, 14),
        ],
        crs=crs,
    )
    intervals = gpd.GeoDataFrame(
        [
            _interval("full", 0, 0, 100, "hp_supported", 0),
            _interval("partial", 0, 0, 20, "sd_gap", 10),
            _interval("partial", 1, 20, 80, "hp_supported", 10),
            _interval("partial", 2, 80, 100, "sd_gap", 10),
            _interval("sd", 0, 0, 100, "sd_gap", 20),
        ],
        crs=crs,
    )
    audit = pd.DataFrame(
        [
            _audit("full", "hp_supported", 1.0, 100, 0, 0, 2, 2),
            _audit("partial", "partial_hp_supported", 0.6, 60, 40, 20, 1, 1),
            _audit("sd", "sd_only", 0.0, 0, 100, 100, 0, 0),
        ]
    )

    result = instantiate_road_geometries(
        roads,
        lane_segments,
        intervals,
        audit,
        config=_config(tmp_path),
    )
    candidates = result.road_candidates.set_index("swsd_unit_id")

    full = candidates.loc["full"].geometry
    assert full.coords[0][1] == pytest.approx(0.0)
    assert full.coords[-1][1] == pytest.approx(0.0)
    assert max(y for _, y in full.coords) == pytest.approx(3.0)
    partial = candidates.loc["partial"].geometry
    assert partial.coords[0][1] == pytest.approx(10.0)
    assert partial.coords[-1][1] == pytest.approx(10.0)
    assert max(y for _, y in partial.coords) == pytest.approx(14.0)
    assert candidates.loc["sd"].geometry.hausdorff_distance(roads.iloc[2].geometry) == pytest.approx(0.0)
    assert result.summary["road_geometry_gate_pass"]
    assert result.summary["endpoint_anchor_gate_pass"]
    assert result.summary["endpoint_anchor_max_delta_m"] == pytest.approx(0.0)
    assert result.summary["sd_only_zero_shift_gate_pass"]


def _lane_segment(lane_id: str, road_id: str, start: float, end: float, y: float) -> dict[str, object]:
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


def _interval(
    road_id: str,
    index: int,
    start: float,
    end: float,
    state: str,
    y: float,
) -> dict[str, object]:
    return {
        "swsd_unit_id": road_id,
        "interval_id": f"{road_id}:{index}",
        "interval_index": index,
        "interval_state": state,
        "start_m": start,
        "end_m": end,
        "start_fraction": start / 100,
        "end_fraction": end / 100,
        "source_lane_ids": "" if state == "sd_gap" else "lane",
        "source_patch_ids": "" if state == "sd_gap" else "p1",
        "geometry": LineString([(start, y), (end, y)]),
    }


def _audit(
    road_id: str,
    state: str,
    coverage: float,
    support: float,
    gap: float,
    max_gap: float,
    source_lanes: int,
    segment_count: int,
) -> dict[str, object]:
    return {
        "swsd_unit_id": road_id,
        "source_lane_ids": "lane" if source_lanes else "",
        "support_state": state,
        "support_reason": state,
        "evidence_quality_state": "clean" if source_lanes else "insufficient",
        "support_coverage_ratio": coverage,
        "support_length_m": support,
        "gap_length_m": gap,
        "max_gap_m": max_gap,
        "source_lane_count": source_lanes,
        "lane_segment_count": segment_count,
    }
