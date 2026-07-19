from __future__ import annotations

from dataclasses import replace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.candidate_audit import (
    audit_frcsd_candidates,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.inputs import LoadedInputs
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import AuditConfig


def _loaded(*, reverse_main: bool, drivezone: bool, crop_inner: object | None = None) -> LoadedInputs:
    segment_geometry = LineString([(0, 0), (100, 0)])
    segments = gpd.GeoDataFrame(
        {
            "id": ["p0_p1"],
            "pair_nodes": ["p0|p1"],
            "roads": ["sw"],
            "geometry": [segment_geometry],
        },
        crs="EPSG:3857",
    )
    swsd_nodes = gpd.GeoDataFrame(
        {"id": ["p0", "p1"], "geometry": [Point(0, 0), Point(100, 0)]},
        crs="EPSG:3857",
    )
    swsd_roads = gpd.GeoDataFrame(
        {
            "id": ["sw"],
            "snodeid": ["p0"],
            "enodeid": ["p1"],
            "direction": [2],
            "source": [1],
            "geometry": [segment_geometry],
        },
        crs="EPSG:3857",
    )
    frcsd_nodes = gpd.GeoDataFrame(
        {
            "id": ["a", "b", "x", "y"],
            "geometry": [
                Point(0, 0),
                Point(100, 0),
                Point(0, -10),
                Point(100, -10),
            ],
        },
        crs="EPSG:3857",
    )
    road_rows = [
        {
            "id": "outgoing_at_start",
            "snodeid": "a",
            "enodeid": "x",
            "direction": 2,
            "source": 99,
            "geometry": LineString([(0, 0), (0, -10)]),
        },
        {
            "id": "incoming_at_end",
            "snodeid": "y",
            "enodeid": "b",
            "direction": 2,
            "source": 99,
            "geometry": LineString([(100, -10), (100, 0)]),
        },
    ]
    if reverse_main:
        road_rows.append(
            {
                "id": "reverse_only_main",
                "snodeid": "a",
                "enodeid": "b",
                "direction": 3,
                "source": 99,
                "geometry": segment_geometry,
            }
        )
    frcsd_roads = gpd.GeoDataFrame(road_rows, crs="EPSG:3857")
    anchors = pd.DataFrame(
        [
            {
                "target_id": "p0",
                "base_id": "a",
                "source_module": "T07",
                "status": "0",
            },
            {
                "target_id": "p1",
                "base_id": "b",
                "source_module": "T07",
                "status": "0",
            },
        ]
    )
    truth = gpd.GeoDataFrame(
        {
            "id": ["truth0", "truth1"],
            "geometry": [box(-2, -2, 2, 2), box(98, -2, 102, 2)],
        },
        crs="EPSG:3857",
    )
    drivezone_frame = (
        gpd.GeoDataFrame(
            {"id": ["dz"], "geometry": [box(-5, -5, 105, 5)]},
            crs="EPSG:3857",
        )
        if drivezone
        else None
    )
    return LoadedInputs(
        segments=segments,
        swsd_roads=swsd_roads,
        swsd_nodes=swsd_nodes,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        rcsd_intersections=truth,
        drivezone=drivezone_frame,
        t05_anchor_audit=anchors,
        t06_cross_evidence={},
        processing_crs="EPSG:3857",
        crop_inner_geometry=crop_inner,
        input_audit={},
        topology_audit={"silent_fix": False},
        evidence_audit={},
    )


@pytest.mark.parametrize(
    ("reverse_main", "expected_issue"),
    [
        (True, "directed_carrier_missing"),
        (False, "required_local_connectivity_missing"),
    ],
)
def test_candidate_issue_type_uses_direction_and_local_connectivity(
    reverse_main: bool,
    expected_issue: str,
) -> None:
    candidates, _, audit = audit_frcsd_candidates(
        _loaded(reverse_main=reverse_main, drivezone=False), AuditConfig()
    )

    assert len(candidates) == 1
    assert candidates[0]["suggested_issue_type"] == expected_issue
    assert candidates[0]["failed_directions"] == ["pair0_to_pair1"]
    assert candidates[0]["anchor_confidence"] == "t07_standard_surface"
    assert audit["t07_truth_audit"]["status"] == "pass"
    assert audit["t07_surface_audit"]["status"] == "pass"


def test_drivezone_is_evidence_only_and_does_not_change_verdict() -> None:
    without, _, without_audit = audit_frcsd_candidates(
        _loaded(reverse_main=True, drivezone=False), AuditConfig()
    )
    with_drivezone, _, with_audit = audit_frcsd_candidates(
        _loaded(reverse_main=True, drivezone=True), AuditConfig()
    )

    assert without[0]["suggested_issue_type"] == with_drivezone[0][
        "suggested_issue_type"
    ]
    assert without[0]["drivezone_in_road_ratio"] is None
    assert with_drivezone[0]["drivezone_in_road_ratio"] == 1.0
    assert without_audit["drivezone_affects_verdict"] is False
    assert with_audit["drivezone_affects_verdict"] is False


def test_crop_edge_candidate_is_excluded_not_silently_repaired() -> None:
    candidates, _, audit = audit_frcsd_candidates(
        _loaded(
            reverse_main=True,
            drivezone=False,
            crop_inner=box(20, -20, 80, 20),
        ),
        AuditConfig(),
    )

    assert candidates == []
    assert audit["counts"]["crop_edge_excluded_count"] == 1


def test_candidate_verdict_uses_raw_endpoints_not_mainnode_alias() -> None:
    loaded = _loaded(reverse_main=False, drivezone=False)
    loaded.swsd_roads["direction"] = [1]
    loaded.frcsd_nodes["mainNodeId"] = ["a", "b", "a", "b"]
    loaded.frcsd_nodes["subNodeId"] = ["a|x", "b|y", "", ""]
    loaded = replace(
        loaded,
        frcsd_roads=gpd.GeoDataFrame(
            [
                {
                    "id": "alias_only_path",
                    "snodeid": "x",
                    "enodeid": "y",
                    "direction": 2,
                    "source": 1,
                    "geometry": LineString([(0, -10), (100, -10)]),
                }
            ],
            crs="EPSG:3857",
        ),
    )

    candidates, _, _ = audit_frcsd_candidates(loaded, AuditConfig())

    assert len(candidates) == 1
    assert candidates[0]["suggested_issue_type"] == (
        "required_local_connectivity_missing"
    )
    assert candidates[0]["automatic_all_directions_equivalent"] is False
