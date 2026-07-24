from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.high_precision_config import (
    HighPrecisionRoadV3Config,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.high_precision_corridor import (
    build_high_precision_corridors,
)


CRS = "EPSG:32650"


def _config(tmp_path) -> HighPrecisionRoadV3Config:
    return HighPrecisionRoadV3Config(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "out",
        run_id="v3-test",
        physical_split_min_shared_coverage_ratio=0.5,
    )


def _parents(*, direction: int = 1) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "swsd_unit_id": "r1",
                "snode_id": "n1",
                "enode_id": "n2",
                "direction": direction,
                "source_patch_ids": "p1",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        geometry="geometry",
        crs=CRS,
    )


def _lanes(*offsets: float) -> gpd.GeoDataFrame:
    rows = []
    for index, offset in enumerate(offsets):
        reverse = offset > 0
        coordinates = [(100, offset), (0, offset)] if reverse else [(0, offset), (100, offset)]
        rows.append(
            {
                "lane_id": f"lane-{index}",
                "swsd_unit_id": "r1",
                "source_patch_ids": "p1",
                "evidence_quality_state": "usable",
                "fit_weight": 1.0,
                "width_median_m": 3.5,
                "geometry": LineString(coordinates),
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=CRS)


def _empty_boundaries() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"Id": [], "patch_id": [], "geometry": []}, geometry="geometry", crs=CRS
    )


def test_distinct_bidirectional_corridors_are_conditionally_split(tmp_path) -> None:
    result = build_high_precision_corridors(
        _parents(), _lanes(-3.0, 3.0), _empty_boundaries(), config=_config(tmp_path)
    )

    decision = result.corridor_decisions.iloc[0]
    assert decision.decision == "split"
    assert bool(decision.separation_gate_pass)
    assert bool(decision.continuity_gate_pass)
    assert set(result.road_units["travel_side"]) == {"forward", "reverse"}
    assert set(result.road_units["road_representation"]) == {
        "directional_carriageway"
    }
    assert set(result.road_units["snode_id"]) == {
        "n1:corridor:forward",
        "n2:corridor:reverse",
    }
    assert set(result.road_units["enode_id"]) == {
        "n2:corridor:forward",
        "n1:corridor:reverse",
    }


def test_single_sided_evidence_stays_one_shared_physical_road(tmp_path) -> None:
    result = build_high_precision_corridors(
        _parents(), _lanes(-3.0), _empty_boundaries(), config=_config(tmp_path)
    )

    assert result.corridor_decisions.iloc[0].decision == "shared"
    assert list(result.road_units["travel_side"]) == ["shared"]
    assert list(result.road_units["road_representation"]) == ["shared_physical"]
    assert result.summary["automatic_bidirectional_split_count"] == 0


def test_collapsed_directional_anchors_do_not_create_two_roads(tmp_path) -> None:
    result = build_high_precision_corridors(
        _parents(), _lanes(-0.1, 0.1), _empty_boundaries(), config=_config(tmp_path)
    )

    decision = result.corridor_decisions.iloc[0]
    assert decision.decision == "shared"
    assert not bool(decision.separation_gate_pass)
    assert len(result.road_units) == 1
    assert "separation" in decision.reason_codes


def test_one_way_parent_is_never_duplicated(tmp_path) -> None:
    result = build_high_precision_corridors(
        _parents(direction=2), _lanes(-2.0), _empty_boundaries(), config=_config(tmp_path)
    )

    assert len(result.road_units) == 1
    road = result.road_units.iloc[0]
    assert road.travel_side == "forward"
    assert road.road_representation == "shared_physical"
    assert int(road.direction) == 2
