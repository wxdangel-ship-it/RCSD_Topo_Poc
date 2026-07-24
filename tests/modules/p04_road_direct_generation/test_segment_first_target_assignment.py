from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_target_assignment import (
    apply_target_segment_anchors,
)


def _centers() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "p1:r1",
                "source_patch_id": "p1",
                "road_id": "r1",
                "center_lane_id": "l1",
                "geometry": LineString([(0, 1), (20, 1)]),
            },
            {
                "patch_road_key": "p1:r2",
                "source_patch_id": "p1",
                "road_id": "r2",
                "center_lane_id": "l2",
                "geometry": LineString([(30, 1), (50, 1)]),
            },
        ],
        crs="EPSG:32650",
    )


def _baseline_assignments(centers: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    first = centers.iloc[0].to_dict()
    first.update(
        {
            "assigned_segment_id": "wrong_segment",
            "target_swsd_road_id": "wrong_member",
            "assignment_distance_m": 1.0,
            "assignment_angle_deg": 0.0,
            "assignment_score": 1.0,
            "assignment_margin": 4.0,
            "carrier_role": "directional_corridor",
            "takeover_eligible": True,
            "assignment_state": "assigned",
            "reason_codes": "segment_member_search_primitive",
        }
    )
    return gpd.GeoDataFrame([first], geometry="geometry", crs=centers.crs)


def _rejections(centers: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    second = centers.iloc[1].to_dict()
    second.update(
        {
            "decision": "rejected",
            "reason_codes": "no_segment_candidate",
        }
    )
    return gpd.GeoDataFrame([second], geometry="geometry", crs=centers.crs)


def _swsd_roads() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "id": "target_member",
                "segmentid": "target_segment",
                "geometry": LineString([(0, 0), (50, 0)]),
            },
            {
                "id": "wrong_member",
                "segmentid": "wrong_segment",
                "geometry": LineString([(0, 2), (20, 2)]),
            },
        ],
        crs="EPSG:32650",
    )


def test_target_anchor_reassigns_and_promotes_patch_evidence_without_copying_geometry() -> None:
    centers = _centers()
    anchors = gpd.GeoDataFrame(
        [
            {
                "segment_id": "target_segment",
                "anchor_source": "t06_replaceability_geometry",
                "geometry": LineString([(0, 0), (50, 0)]),
            }
        ],
        crs=centers.crs,
    )

    result = apply_target_segment_anchors(
        centers,
        _baseline_assignments(centers),
        _rejections(centers),
        _swsd_roads(),
        anchors,
        max_distance_m=10.0,
        max_angle_deg=45.0,
        run_id="target-assignment",
    )

    assigned = result.assignments.set_index("patch_road_key")
    assert set(assigned.index) == {"p1:r1", "p1:r2"}
    assert set(assigned["assigned_segment_id"]) == {"target_segment"}
    assert set(assigned["target_swsd_road_id"]) == {"target_member"}
    assert assigned.loc["p1:r1", "assignment_state"] == (
        "target_anchor_reassigned"
    )
    assert assigned.loc["p1:r2", "assignment_state"] == (
        "target_anchor_promoted"
    )
    assert assigned.loc["p1:r1"].geometry.equals(centers.iloc[0].geometry)
    assert assigned.loc["p1:r2"].geometry.equals(centers.iloc[1].geometry)
    assert result.rejections.empty
    assert result.summary["reassigned_count"] == 1
    assert result.summary["promoted_count"] == 1


def test_empty_target_anchor_set_preserves_baseline_decisions() -> None:
    centers = _centers()
    empty = gpd.GeoDataFrame(
        {
            "segment_id": [],
            "anchor_source": [],
            "geometry": gpd.GeoSeries([], crs=centers.crs),
        },
        geometry="geometry",
        crs=centers.crs,
    )
    baseline = _baseline_assignments(centers)
    rejections = _rejections(centers)

    result = apply_target_segment_anchors(
        centers,
        baseline,
        rejections,
        _swsd_roads(),
        empty,
        max_distance_m=10.0,
        max_angle_deg=45.0,
        run_id="target-assignment-disabled",
    )

    assert result.assignments["patch_road_key"].tolist() == ["p1:r1"]
    assert result.rejections["patch_road_key"].tolist() == ["p1:r2"]
    assert not result.summary["anchor_enabled"]


def test_target_anchor_does_not_steal_evidence_from_another_required_segment() -> None:
    centers = _centers().iloc[[0]].copy()
    baseline = _baseline_assignments(centers)
    anchors = gpd.GeoDataFrame(
        [
            {
                "segment_id": "target_segment",
                "anchor_source": "t06_replaceability_geometry",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs=centers.crs,
    )

    result = apply_target_segment_anchors(
        centers,
        baseline,
        _rejections(_centers()),
        _swsd_roads(),
        anchors,
        max_distance_m=10.0,
        max_angle_deg=45.0,
        run_id="target-protected",
        protected_segment_ids={"wrong_segment", "target_segment"},
    )

    assert result.assignments.iloc[0]["assigned_segment_id"] == "wrong_segment"
    assert result.summary["protected_assignment_count"] == 1
