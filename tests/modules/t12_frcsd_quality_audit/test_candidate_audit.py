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


def test_t07_alias_outside_standard_surface_does_not_override_raw_failure() -> None:
    loaded = _loaded(reverse_main=False, drivezone=False)
    loaded.swsd_roads["direction"] = [2]
    loaded = replace(
        loaded,
        frcsd_nodes=gpd.GeoDataFrame(
            {
                "id": ["a", "b", "p", "q", "s", "e", "r", "t"],
                "mainNodeId": [
                    "",
                    "",
                    "100",
                    "200",
                    "100",
                    "200",
                    "",
                    "",
                ],
                "subNodeId": ["", "", "", "", "", "", "", ""],
                "geometry": [
                    Point(0, 0),
                    Point(100, 0),
                    Point(0, 1),
                    Point(100, 1),
                    Point(0, -10),
                    Point(100, -10),
                    Point(0, 5),
                    Point(100, 5),
                ],
            },
            crs="EPSG:3857",
        ),
        frcsd_roads=gpd.GeoDataFrame(
            [
                {
                    "id": "alias_only_path",
                    "snodeid": "s",
                    "enodeid": "e",
                    "direction": 2,
                    "source": 1,
                    "geometry": LineString([(0, -10), (100, -10)]),
                },
                {
                    "id": "start_portal_spur",
                    "snodeid": "p",
                    "enodeid": "r",
                    "direction": 2,
                    "source": 1,
                    "geometry": LineString([(0, 1), (0, 5)]),
                },
                {
                    "id": "end_portal_spur",
                    "snodeid": "q",
                    "enodeid": "t",
                    "direction": 2,
                    "source": 1,
                    "geometry": LineString([(100, 1), (100, 5)]),
                },
            ],
            crs="EPSG:3857",
        ),
    )

    candidates, _, _ = audit_frcsd_candidates(loaded, AuditConfig())

    assert len(candidates) == 1
    assert candidates[0]["suggested_issue_type"] == (
        "required_local_connectivity_missing"
    )
    assert candidates[0]["raw_failed_directions"] == ["pair0_to_pair1"]
    assert candidates[0]["failed_directions"] == ["pair0_to_pair1"]
    assert candidates[0]["automatic_all_directions_equivalent"] is False
    evidence = candidates[0]["directions"][0][
        "portal_constrained_semantic_directed"
    ]
    assert evidence["accepted_equivalent_carrier"] is False
    assert evidence["start_endpoint_reason"] == "t07_alias_outside_standard_surface"
    assert evidence["end_endpoint_reason"] == "t07_alias_outside_standard_surface"


def _loaded_with_internal_alias(*, alias_gap_m: float) -> LoadedInputs:
    loaded = _loaded(reverse_main=False, drivezone=False)
    loaded.swsd_roads["direction"] = [2]
    loaded = replace(
        loaded,
        frcsd_nodes=gpd.GeoDataFrame(
            {
                "id": ["a", "b", "s", "e", "x", "y"],
                "mainNodeId": ["", "", "", "", "100", "100"],
                "subNodeId": ["", "", "", "", "", ""],
                "geometry": [
                    Point(0, 0),
                    Point(100, 0),
                    Point(0, 1),
                    Point(100, 1),
                    Point(50, 1),
                    Point(50 + alias_gap_m, 1),
                ],
            },
            crs="EPSG:3857",
        ),
        frcsd_roads=gpd.GeoDataFrame(
            [
                {
                    "id": "left",
                    "snodeid": "s",
                    "enodeid": "x",
                    "direction": 2,
                    "source": 1,
                    "geometry": LineString([(0, 1), (50, 1)]),
                },
                {
                    "id": "right",
                    "snodeid": "y",
                    "enodeid": "e",
                    "direction": 2,
                    "source": 1,
                    "geometry": LineString(
                        [(50 + alias_gap_m, 1), (100, 1)]
                    ),
                },
            ],
            crs="EPSG:3857",
        ),
    )
    return loaded


def test_portal_constrained_semantic_carrier_excludes_raw_alias_false_positive() -> None:
    candidates, _, audit = audit_frcsd_candidates(
        _loaded_with_internal_alias(alias_gap_m=1.0),
        AuditConfig(),
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["raw_failed_directions"] == ["pair0_to_pair1"]
    assert candidate["failed_directions"] == []
    assert candidate["suggested_issue_type"] == ""
    assert candidate["automatic_all_directions_equivalent"] is True
    assert candidate["automatic_equivalence_basis"] == (
        "portal_constrained_semantic_carrier"
    )
    evidence = candidate["directions"][0][
        "portal_constrained_semantic_directed"
    ]
    assert evidence["accepted_equivalent_carrier"] is True
    assert evidence["start_endpoint_reason"] == "exact_raw_portal"
    assert evidence["end_endpoint_reason"] == "exact_raw_portal"
    assert evidence["max_internal_alias_gap_m"] == pytest.approx(1.0)
    assert audit["semantic_carrier_policy"] == {
        "role": "raw_failure_exclusion_only",
        "physical_road_required": True,
        "standard_surface_tolerance_m": 1.0,
        "non_t07_endpoint_max_gap_m": 50.0,
        "internal_alias_max_gap_m": 50.0,
        "path_thresholds": {
            "max_length_ratio": 1.5,
            "max_additive_m": 100.0,
            "max_corridor_distance_m": 50.0,
        },
    }


def test_semantic_alias_gap_beyond_portal_radius_keeps_quality_issue() -> None:
    candidates, _, _ = audit_frcsd_candidates(
        _loaded_with_internal_alias(alias_gap_m=60.0),
        AuditConfig(),
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["raw_failed_directions"] == ["pair0_to_pair1"]
    assert candidate["failed_directions"] == ["pair0_to_pair1"]
    evidence = candidate["directions"][0][
        "portal_constrained_semantic_directed"
    ]
    assert evidence["accepted_equivalent_carrier"] is False
    assert evidence["internal_aliases_trusted"] is False
