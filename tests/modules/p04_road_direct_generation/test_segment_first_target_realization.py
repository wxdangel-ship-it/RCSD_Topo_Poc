from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_target_realization import (
    audit_target_realization,
)


def test_target_realization_requires_two_directional_main_roads_for_dual_segment() -> None:
    targets = gpd.GeoDataFrame(
        [
            {
                "segment_id": "dual",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0双",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "segment_id": "single",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-1单",
                "geometry": LineString([(20, 0), (30, 0)]),
            },
            {
                "segment_id": "ar",
                "target_class": "advance_right",
                "target_required": True,
                "sgrade": "",
                "geometry": LineString([(40, 0), (50, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            _road("dual", "main_forward", "built", 0),
            _road("dual", "semantic_carrier", "retained", 1),
            _road("single", "main_oneway", "built", 20),
            _road("ar", "main_oneway", "built", 40),
        ],
        crs=targets.crs,
    )

    result = audit_target_realization(targets, roads, run_id="target-realization")

    rows = result.audit.set_index("segment_id")
    assert not bool(rows.loc["dual", "target_realized"])
    assert rows.loc["dual", "missing_roles"] == "main_reverse"
    assert bool(rows.loc["single", "target_realized"])
    assert bool(rows.loc["ar", "target_realized"])
    assert result.summary["required_segment_count"] == 3
    assert result.summary["realized_segment_count"] == 2
    assert not result.summary["target_gate_pass"]


def test_target_realization_audits_full_baseline_but_gates_only_direct_build() -> None:
    targets = gpd.GeoDataFrame(
        [
            {
                "segment_id": "direct",
                "target_class": "core_trunk",
                "baseline_target": True,
                "direct_build_eligibility": "direct_build_required",
                "direct_build_required": True,
                "target_required": True,
                "sgrade": "0-1单",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "segment_id": "insufficient",
                "target_class": "core_trunk",
                "baseline_target": True,
                "direct_build_eligibility": "patch_data_insufficient",
                "direct_build_required": False,
                "target_required": False,
                "sgrade": "0-1单",
                "classification_reason_codes": "no_valid_main_corridor",
                "classification_evidence_ids": "audit:insufficient",
                "geometry": LineString([(20, 0), (30, 0)]),
            },
            {
                "segment_id": "change",
                "target_class": "advance_right",
                "baseline_target": True,
                "direct_build_eligibility": "reality_change",
                "direct_build_required": False,
                "target_required": False,
                "sgrade": "",
                "reality_change_clue_id": "p04:reality_change:change",
                "geometry": LineString([(40, 0), (50, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [_road("direct", "main_oneway", "built", 0)],
        crs=targets.crs,
    )

    result = audit_target_realization(targets, roads, run_id="three-layer")

    rows = result.audit.set_index("segment_id")
    assert len(rows) == 3
    assert rows.loc["insufficient", "direct_build_outcome"] == "not_applicable"
    assert (
        rows.loc["insufficient", "publish_disposition"]
        == "swsd_retained_data_insufficient"
    )
    assert (
        rows.loc["change", "publish_disposition"]
        == "swsd_retained_reality_change_pending"
    )
    assert result.summary["baseline_target_count"] == 3
    assert result.summary["baseline_realized_count"] == 1
    assert result.summary["direct_build_required_count"] == 1
    assert result.summary["direct_build_realized_count"] == 1
    assert result.summary["target_gate_pass"]


def test_target_realization_uses_segment_state_for_unresolved_business_class() -> None:
    targets = gpd.GeoDataFrame(
        [
            {
                "segment_id": "conflict",
                "target_class": "core_trunk",
                "baseline_target": True,
                "direct_build_eligibility": "direct_build_required",
                "direct_build_required": True,
                "target_required": True,
                "sgrade": "0-0双",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "segment_id": "partial",
                "target_class": "core_trunk",
                "baseline_target": True,
                "direct_build_eligibility": "direct_build_required",
                "direct_build_required": True,
                "target_required": True,
                "sgrade": "0-0双",
                "geometry": LineString([(20, 0), (30, 0)]),
            },
        ],
        crs="EPSG:32650",
    )
    plans = gpd.GeoDataFrame(
        [
            {
                "segment_id": "conflict",
                "segment_state": "conflict_retained",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "segment_id": "partial",
                "segment_state": "swsd_retained",
                "geometry": LineString([(20, 0), (30, 0)]),
            },
        ],
        crs=targets.crs,
    )
    roads = gpd.GeoDataFrame(
        [
            _road("conflict", "semantic_carrier", "retained", 0),
            _road("partial", "semantic_carrier", "retained", 20),
        ],
        crs=targets.crs,
    )

    result = audit_target_realization(
        targets,
        roads,
        segment_plans=plans,
        run_id="business-class",
    )

    rows = result.audit.set_index("segment_id")
    assert rows.loc["conflict", "direct_build_outcome"] == "hard_conflict"
    assert rows.loc["conflict", "publish_disposition"] == "conflict_retained"
    assert (
        rows.loc["partial", "direct_build_outcome"]
        == "partial_evidence_unresolved"
    )
    assert (
        rows.loc["partial", "publish_disposition"]
        == "swsd_retained_partial_evidence"
    )


def test_target_realization_accepts_multi_road_directional_trunk_chains() -> None:
    targets = _single_dual_target()
    roads = gpd.GeoDataFrame(
        [
            _chain_road(1, "main_forward", 10, 11),
            _chain_road(2, "main_forward", 11, 20),
            _chain_road(3, "main_reverse", 20, 21),
            _chain_road(4, "main_reverse", 21, 10),
        ],
        crs=targets.crs,
    )
    nodes = _chain_nodes()
    accesses = _chain_accesses()

    result = audit_target_realization(
        targets,
        roads,
        nodes=nodes,
        segment_accesses=accesses,
        run_id="chain-pass",
    )

    row = result.audit.iloc[0]
    assert bool(row["target_realized"])
    assert bool(row["directional_chain_complete"])
    assert row["chain_failure_reasons"] == ""
    assert row["built_main_road_count"] == 4
    assert result.summary["directional_chain_complete_count"] == 1


def test_target_realization_accepts_path_across_distributed_junction_portals() -> None:
    targets = _single_dual_target()
    roads = gpd.GeoDataFrame(
        [
            _chain_road(1, "main_forward", 10, 11),
            _chain_road(2, "main_forward", 12, 20),
            _chain_road(3, "main_reverse", 20, 13),
            _chain_road(4, "main_reverse", 14, 10),
        ],
        crs=targets.crs,
    )
    nodes = gpd.GeoDataFrame(
        [
            {
                "id": 10,
                "junction_group_ids": "100",
                "geometry": Point(0, 0),
            },
            {
                "id": 11,
                "junction_group_ids": "300",
                "geometry": Point(9, 0),
            },
            {
                "id": 12,
                "junction_group_ids": "300",
                "geometry": Point(11, 0),
            },
            {
                "id": 13,
                "junction_group_ids": "300",
                "geometry": Point(11, 1),
            },
            {
                "id": 14,
                "junction_group_ids": "300",
                "geometry": Point(9, 1),
            },
            {
                "id": 20,
                "junction_group_ids": "200",
                "geometry": Point(20, 0),
            },
        ],
        crs=targets.crs,
    )
    topology = gpd.GeoDataFrame(
        [
            {
                "RoadId": 1,
                "NextRoadId": 2,
                "compile_source": "ordinary_junction_semantic",
                "geometry": Point(10, 0),
            },
            {
                "RoadId": 3,
                "NextRoadId": 4,
                "compile_source": "ordinary_junction_semantic",
                "geometry": Point(10, 1),
            },
        ],
        crs=targets.crs,
    )

    result = audit_target_realization(
        targets,
        roads,
        nodes=nodes,
        segment_accesses=_chain_accesses(),
        road_next_road=topology,
        run_id="distributed-portal-chain",
    )

    assert bool(result.audit.iloc[0]["target_realized"])
    assert result.audit.iloc[0]["chain_failure_reasons"] == ""


def test_target_realization_ignores_semantic_shortcuts_within_one_member() -> None:
    targets = _single_dual_target()
    roads = gpd.GeoDataFrame(
        [
            _chain_road(1, "main_forward", 10, 11),
            _chain_road(2, "main_forward", 11, 12),
            _chain_road(3, "main_forward", 12, 20),
            _chain_road(4, "main_reverse", 20, 21),
            _chain_road(5, "main_reverse", 21, 10),
        ],
        crs=targets.crs,
    )
    roads["member_swsd_road_id"] = "same-member"
    topology = gpd.GeoDataFrame(
        [
            {
                "RoadId": 1,
                "NextRoadId": 3,
                "compile_source": "ordinary_junction_semantic",
                "geometry": Point(10, 0),
            }
        ],
        crs=targets.crs,
    )
    nodes = _chain_nodes()
    nodes = gpd.GeoDataFrame(
        [
            *nodes.to_dict("records"),
            {
                "id": 12,
                "mainnodeid": 12,
                "junction_group_ids": "",
                "geometry": Point(10.0, 0.0),
            },
        ],
        crs=targets.crs,
    ).drop_duplicates("id", keep="last")

    result = audit_target_realization(
        targets,
        roads,
        nodes=nodes,
        segment_accesses=_chain_accesses(),
        road_next_road=topology,
        run_id="same-member-shortcut",
    )

    assert bool(result.audit.iloc[0]["target_realized"])
    assert result.audit.iloc[0]["chain_failure_reasons"] == ""


def test_target_realization_rejects_disconnected_or_wrong_terminal_chain() -> None:
    targets = _single_dual_target()
    roads = gpd.GeoDataFrame(
        [
            _chain_road(1, "main_forward", 10, 11),
            _chain_road(2, "main_forward", 12, 20),
            _chain_road(3, "main_reverse", 20, 21),
            _chain_road(4, "main_reverse", 21, 30),
        ],
        crs=targets.crs,
    )
    nodes = _chain_nodes(extra_wrong_terminal=True)
    accesses = _chain_accesses()

    result = audit_target_realization(
        targets,
        roads,
        nodes=nodes,
        segment_accesses=accesses,
        run_id="chain-fail",
    )

    row = result.audit.iloc[0]
    assert not bool(row["target_realized"])
    assert not bool(row["directional_chain_complete"])
    assert {
        "main_forward:disconnected",
        "main_reverse:terminal_mismatch",
    }.issubset(set(str(row["chain_failure_reasons"]).split(",")))
    assert not result.summary["target_gate_pass"]


def test_target_realization_requires_physical_arrival_at_accepted_surfaces() -> None:
    targets = _single_dual_target()
    roads = gpd.GeoDataFrame(
        [
            _chain_road(1, "main_forward", 10, 11),
            _chain_road(2, "main_forward", 11, 20),
            _chain_road(3, "main_reverse", 20, 21),
            _chain_road(4, "main_reverse", 21, 10),
        ],
        crs=targets.crs,
    )
    nodes = _chain_nodes()
    nodes.loc[nodes["id"].eq(10), "geometry"] = Point(10.0, 0.0)
    nodes.loc[nodes["id"].eq(20), "geometry"] = Point(30.0, 0.0)

    failed = audit_target_realization(
        targets,
        roads,
        nodes=nodes,
        segment_accesses=_chain_accesses(),
        junction_units=_chain_junction_units(),
        run_id="surface-fail",
    )

    assert not bool(failed.audit.iloc[0]["target_realized"])
    assert "terminal_surface_mismatch" in str(
        failed.audit.iloc[0]["chain_failure_reasons"]
    )

    nodes.loc[nodes["id"].eq(10), "geometry"] = Point(-1.0, 0.0)
    nodes.loc[nodes["id"].eq(20), "geometry"] = Point(21.0, 0.0)
    boundary_failed = audit_target_realization(
        targets,
        roads,
        nodes=nodes,
        segment_accesses=_chain_accesses(),
        junction_units=_chain_junction_units(),
        run_id="surface-boundary-fail",
    )

    assert not bool(boundary_failed.audit.iloc[0]["target_realized"])
    assert "terminal_surface_mismatch" in str(
        boundary_failed.audit.iloc[0]["chain_failure_reasons"]
    )

    nodes.loc[nodes["id"].eq(10), "geometry"] = Point(0.0, 0.0)
    nodes.loc[nodes["id"].eq(20), "geometry"] = Point(20.0, 0.0)
    passed = audit_target_realization(
        targets,
        roads,
        nodes=nodes,
        segment_accesses=_chain_accesses(),
        junction_units=_chain_junction_units(),
        run_id="surface-pass",
    )

    assert bool(passed.audit.iloc[0]["target_realized"])
    assert passed.audit.iloc[0]["chain_failure_reasons"] == ""


def _road(
    segment_id: str,
    role: str,
    realization: str,
    start: float,
) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "carrier_role": role,
        "realization": realization,
        "geometry_source": (
            "hp_observed" if realization == "built" else "swsd_retained_whole"
        ),
        "geometry": LineString([(start, 1), (start + 10, 1)]),
    }


def _single_dual_target() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "segment_id": "dual",
                "target_class": "core_trunk",
                "target_required": True,
                "sgrade": "0-0双",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs="EPSG:32650",
    )


def _chain_road(
    road_id: int,
    role: str,
    snodeid: int,
    enodeid: int,
) -> dict[str, object]:
    return {
        "id": road_id,
        "segment_id": "dual",
        "carrier_role": role,
        "realization": "built",
        "geometry_source": "hp_observed",
        "direction": 2,
        "snodeid": snodeid,
        "enodeid": enodeid,
        "source_patch_road_keys": f"patch:{road_id}",
        "source_lane_ids": f"lane:{road_id}",
        "geometry": LineString([(road_id * 2.0, 0.0), (road_id * 2.0 + 1.0, 0.0)]),
    }


def _chain_nodes(*, extra_wrong_terminal: bool = False) -> gpd.GeoDataFrame:
    rows = [
        {
            "id": 10,
            "mainnodeid": 100,
            "junction_group_ids": "100",
            "geometry": Point(0.0, 0.0),
        },
        {
            "id": 11,
            "mainnodeid": 11,
            "junction_group_ids": "",
            "geometry": Point(5.0, 0.0),
        },
        {
            "id": 12,
            "mainnodeid": 12,
            "junction_group_ids": "",
            "geometry": Point(6.0, 0.0),
        },
        {
            "id": 20,
            "mainnodeid": 200,
            "junction_group_ids": "200",
            "geometry": Point(20.0, 0.0),
        },
        {
            "id": 21,
            "mainnodeid": 21,
            "junction_group_ids": "",
            "geometry": Point(15.0, 0.0),
        },
    ]
    if extra_wrong_terminal:
        rows.append(
            {
                "id": 30,
                "mainnodeid": 300,
                "junction_group_ids": "300",
                "geometry": Point(30.0, 0.0),
            }
        )
    return gpd.GeoDataFrame(rows, crs="EPSG:32650")


def _chain_accesses() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "segment_id": "dual",
                "access_type": "ENDPOINT",
                "junction_group_id": "100",
                "geometry": Point(0.0, 0.0),
            },
            {
                "segment_id": "dual",
                "access_type": "ENDPOINT",
                "junction_group_id": "200",
                "geometry": Point(20.0, 0.0),
            },
        ],
        crs="EPSG:32650",
    )


def _chain_junction_units() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "geometry": box(-1.0, -1.0, 1.0, 1.0),
            },
            {
                "junction_group_id": "200",
                "junction_source": "t03_accepted",
                "geometry": box(19.0, -1.0, 21.0, 1.0),
            },
        ],
        crs="EPSG:32650",
    )
