from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_target_coverage import (
    build_target_coverage_contract,
)


def _segments() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "segment_id": "core_closed",
                "segment_type": "normal",
                "pair_node_ids": "n1,n2",
                "swsd_road_ids": "r1",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "segment_id": "core_boundary",
                "segment_type": "normal",
                "pair_node_ids": "n3,n4",
                "swsd_road_ids": "r2",
                "geometry": LineString([(20, 0), (30, 0)]),
            },
            {
                "segment_id": "not_replaceable",
                "segment_type": "normal",
                "pair_node_ids": "n5,n6",
                "swsd_road_ids": "r3",
                "geometry": LineString([(40, 0), (50, 0)]),
            },
            {
                "segment_id": "advance_right_closed",
                "segment_type": "advance_right",
                "pair_node_ids": "",
                "swsd_road_ids": "r4",
                "geometry": LineString([(60, 0), (70, 0)]),
            },
            {
                "segment_id": "missing_endpoint_membership",
                "segment_type": "normal",
                "pair_node_ids": "n9,n10",
                "swsd_road_ids": "r5",
                "geometry": LineString([(80, 0), (90, 0)]),
            },
        ],
        crs="EPSG:32650",
    )


def _roads() -> gpd.GeoDataFrame:
    rows = [
        ("r1", "core_closed", "n1", "n2", "p1"),
        ("r2", "core_boundary", "n3", "n4", "p1,p_missing"),
        ("r3", "not_replaceable", "n5", "n6", "p1"),
        ("r4", "advance_right_closed", "n7", "n8", "p2"),
        ("r5", "missing_endpoint_membership", "n9", "n10", ""),
    ]
    return gpd.GeoDataFrame(
        [
            {
                "id": road_id,
                "segmentid": segment_id,
                "snodeid": snodeid,
                "enodeid": enodeid,
                "patch_id": patch_id,
                "geometry": LineString([(index * 20, 0), (index * 20 + 10, 0)]),
            }
            for index, (road_id, segment_id, snodeid, enodeid, patch_id) in enumerate(rows)
        ],
        crs="EPSG:32650",
    )


def _replaceability() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "swsd_segment_id": "core_closed",
                "replacement_ready": True,
                "hard_filter_passed": True,
                "rcsd_road_ids": "['hp1', 'hp2']",
                "excluded_advance_right_turn_road_ids": "['ar1']",
            },
            {
                "swsd_segment_id": "core_boundary",
                "replacement_ready": True,
                "hard_filter_passed": True,
                "rcsd_road_ids": "['hp3']",
                "excluded_advance_right_turn_road_ids": "[]",
            },
            {
                "swsd_segment_id": "not_replaceable",
                "replacement_ready": False,
                "hard_filter_passed": True,
                "rcsd_road_ids": "['hp4']",
                "excluded_advance_right_turn_road_ids": "[]",
            },
            {
                "swsd_segment_id": "missing_endpoint_membership",
                "replacement_ready": True,
                "hard_filter_passed": True,
                "rcsd_road_ids": "['hp5']",
                "excluded_advance_right_turn_road_ids": "[]",
            },
        ]
    )


def test_target_contract_separates_closed_core_advance_right_and_boundary() -> None:
    result = build_target_coverage_contract(
        _segments(),
        _roads(),
        _replaceability(),
        patch_ids=("p1", "p2"),
        run_id="target-test",
    )

    rows = result.segments.set_index("segment_id")
    assert rows.loc["core_closed", "target_class"] == "core_trunk"
    assert bool(rows.loc["core_closed", "target_required"])
    assert rows.loc["core_closed", "t06_rcsd_road_ids"] == "hp1,hp2"
    assert rows.loc["core_closed", "t06_excluded_advance_right_road_ids"] == "ar1"

    assert rows.loc["advance_right_closed", "target_class"] == "advance_right"
    assert bool(rows.loc["advance_right_closed", "target_required"])
    assert rows.loc["advance_right_closed", "target_endpoint_source"] == (
        "single_member_road_endpoints"
    )

    assert rows.loc["core_boundary", "target_class"] == "boundary_review"
    assert not bool(rows.loc["core_boundary", "target_required"])
    assert rows.loc["core_boundary", "endpoint_0_patch_ids"] == "p1,p_missing"

    assert rows.loc["not_replaceable", "target_class"] == "not_target"
    assert rows.loc["missing_endpoint_membership", "target_reason"] == (
        "endpoint_patch_membership_missing"
    )
    assert result.summary == {
        "contract_enabled": True,
        "segment_count": 5,
        "core_target_count": 1,
        "advance_right_target_count": 1,
        "anchor_segment_count": 0,
            "boundary_review_count": 1,
            "not_target_count": 2,
            "baseline_target_count": 2,
            "direct_build_required_count": 2,
            "patch_data_insufficient_count": 0,
            "reality_change_count": 0,
            "target_disposition_manifest_applied": False,
            "target_disposition_manifest_sha256": "",
            "target_disposition_contract_version": "",
            "run_id": "target-test",
        }


def test_target_contract_is_disabled_without_t06_baseline() -> None:
    result = build_target_coverage_contract(
        _segments(),
        _roads(),
        pd.DataFrame(),
        patch_ids=("p1", "p2"),
        run_id="target-disabled",
    )

    assert not result.summary["contract_enabled"]
    assert not result.segments["target_required"].any()
    assert set(result.segments["target_class"]) == {"not_target"}


def test_target_contract_keeps_t06_geometry_as_non_output_anchor() -> None:
    replaceability = gpd.GeoDataFrame(
        _replaceability(),
        geometry=[
            LineString([(0, 1), (10, 1)]),
            LineString([(20, 1), (30, 1)]),
            LineString([(40, 1), (50, 1)]),
            LineString([(80, 1), (90, 1)]),
        ],
        crs="EPSG:32650",
    )
    result = build_target_coverage_contract(
        _segments(),
        _roads(),
        replaceability,
        patch_ids=("p1", "p2"),
        run_id="target-anchor",
    )

    assert result.summary["anchor_segment_count"] == 1
    assert result.anchors["segment_id"].tolist() == ["core_closed"]
    assert result.anchors.iloc[0].geometry.equals(
        LineString([(0, 1), (10, 1)])
    )
