from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.directional_config import (
    DirectionalRoadV2Config,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.directional_evidence import (
    build_directional_evidence,
)


def _config(tmp_path: Path) -> DirectionalRoadV2Config:
    return DirectionalRoadV2Config(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "out",
        run_id="directional-evidence-test",
    )


def test_bidirectional_parent_is_split_and_uses_only_same_direction_usable_evidence(
    tmp_path: Path,
) -> None:
    crs = "EPSG:32650"
    roads = gpd.GeoDataFrame(
        [
            {
                "swsd_unit_id": "r1",
                "direction": 1,
                "snode_id": "n1",
                "enode_id": "n2",
                "semantic_snode_id": "j1",
                "semantic_enode_id": "j2",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs=crs,
    )
    segments = gpd.GeoDataFrame(
        [
            _segment("f1", "usable", LineString([(0, 2), (100, 2)])),
            _segment("f2", "usable", LineString([(0, 4), (100, 4)])),
            _segment("r1", "usable", LineString([(100, -2), (0, -2)])),
            _segment("review", "review", LineString([(0, 12), (100, 12)])),
        ],
        crs=crs,
    )
    decisions = gpd.GeoDataFrame(
        [
            _decision("f1", "b0", "shared"),
            _decision("f2", "shared", "b2"),
            _decision("r1", "b3", "b4"),
            _decision("review", "b5", "b6"),
        ],
        geometry=[
            LineString([(0, 2), (100, 2)]),
            LineString([(0, 4), (100, 4)]),
            LineString([(100, -2), (0, -2)]),
            LineString([(0, 12), (100, 12)]),
        ],
        crs=crs,
    )
    boundaries = gpd.GeoDataFrame(
        [{"Id": "shared", "geometry": LineString([(0, 3), (100, 3)])}],
        crs=crs,
    )
    m2 = gpd.GeoDataFrame(
        [{"swsd_unit_id": "r1", "support_state": "hp_supported", "geometry": roads.iloc[0].geometry}],
        crs=crs,
    )

    result = build_directional_evidence(
        roads,
        segments,
        decisions,
        boundaries,
        m2,
        config=_config(tmp_path),
    )

    units = result.directional_units.set_index("travel_side")
    assert set(units.index) == {"forward", "reverse"}
    assert set(units["direction"]) == {2}
    assert units.loc["reverse", "snode_id"] == "n2"
    assert units.loc["reverse", "enode_id"] == "n1"
    assert set(units["directional_support_state"]) == {"hp_supported"}
    anchors = result.anchors.set_index("travel_side")
    assert anchors.loc["forward", "anchor_kind"] == "lane_boundary"
    assert anchors.loc["forward", "anchor_source_id"] == "shared"
    assert anchors.loc["reverse", "anchor_source_id"] == "r1"
    review = result.lane_group_members[
        result.lane_group_members["lane_id"] == "review"
    ].iloc[0]
    assert review.geometry_role == "soft_review"
    assert result.summary["hard_anchor_non_usable_count"] == 0
    assert result.summary["non_sd_bidirectional_object_count"] == 0


def test_cross_direction_collapsed_usable_evidence_reverts_to_swsd_parent(
    tmp_path: Path,
) -> None:
    crs = "EPSG:32650"
    roads = gpd.GeoDataFrame(
        [{"swsd_unit_id": "r1", "direction": 1, "snode_id": "n1", "enode_id": "n2", "geometry": LineString([(0, 0), (100, 0)])}],
        crs=crs,
    )
    segments = gpd.GeoDataFrame(
        [
            _segment("f1", "usable", LineString([(0, 0.0), (100, 0.0)])),
            _segment("r1", "usable", LineString([(100, 0.2), (0, 0.2)])),
        ],
        crs=crs,
    )
    decisions = gpd.GeoDataFrame(
        [
            {**_decision("f1", "b1", "b2"), "width_median_m": 3.5},
            {**_decision("r1", "b3", "b4"), "width_median_m": 3.4},
        ],
        geometry=[LineString([(0, 0), (100, 0)]), LineString([(100, 0.2), (0, 0.2)])],
        crs=crs,
    )
    m2 = gpd.GeoDataFrame(
        [{"swsd_unit_id": "r1", "support_state": "hp_supported", "geometry": roads.iloc[0].geometry}],
        crs=crs,
    )

    result = build_directional_evidence(
        roads,
        segments,
        decisions,
        gpd.GeoDataFrame(columns=["Id", "geometry"], geometry="geometry", crs=crs),
        m2,
        config=_config(tmp_path),
    )

    assert list(result.directional_units["travel_side"]) == ["sd_parent"]
    assert result.directional_units.iloc[0].high_precision_claim_scope == "none"
    assert result.summary["cross_direction_collapse_parent_count"] == 1
    assert result.summary["cross_direction_downgraded_lane_segment_count"] == 2
    assert result.summary["published_cross_direction_collapse_count"] == 0
    assert not result.cross_direction_quality_audit["anchor_gate_pass"].any()
    assert set(result.lane_segments["evidence_quality_state"]) == {"usable"}
    assert not result.lane_segments["hard_geometry_eligible"].any()
    assert set(result.lane_group_members["geometry_role"]) == {"topology_only_review"}
    assert set(result.lane_group_members["directional_road_id"]) == {"r1"}


def _segment(lane_id: str, quality: str, geometry: LineString) -> dict[str, object]:
    return {
        "lane_id": lane_id,
        "swsd_unit_id": "r1",
        "source_patch_ids": "p1",
        "road_start_m": 0.0,
        "road_end_m": 100.0,
        "evidence_quality_state": quality,
        "geometry": geometry,
    }


def _decision(lane_id: str, left: str, right: str) -> dict[str, object]:
    return {
        "lane_id": lane_id,
        "left_boundary_ids": left,
        "right_boundary_ids": right,
        "left_boundary_id": left,
        "right_boundary_id": right,
    }
