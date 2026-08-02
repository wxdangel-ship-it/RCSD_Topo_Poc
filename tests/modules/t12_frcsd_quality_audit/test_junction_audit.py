from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.inputs import LoadedInputs
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_audit import (
    audit_junction_quality,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_inputs import (
    JunctionSources,
    T03CaseEvidence,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_outputs import (
    write_junction_outputs,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import (
    AuditConfig,
    T12ContractError,
)


CRS = "EPSG:3857"


def _loaded(
    *,
    target_points: tuple[Point, Point] = (Point(10, 0), Point(10, 0.5)),
    frcsd_roads: gpd.GeoDataFrame | None = None,
    frcsd_nodes: gpd.GeoDataFrame | None = None,
    swsd_patch_id: str = "p1",
) -> LoadedInputs:
    swsd_nodes = gpd.GeoDataFrame(
        {
            "id": ["j", "t2"],
            "mainnodeid": ["j", "j"],
            "has_evd": ["yes", ""],
            "is_anchor": ["no", ""],
            "kind_2": [4, ""],
            "geometry": list(target_points),
        },
        crs=CRS,
    )
    swsd_roads = gpd.GeoDataFrame(
        {
            "id": ["s1"],
            "snodeid": ["j"],
            "enodeid": ["t2"],
            "direction": [0],
            "patch_id": [swsd_patch_id],
            "geometry": [LineString(target_points)],
        },
        crs=CRS,
    )
    if frcsd_nodes is None:
        frcsd_nodes = gpd.GeoDataFrame(
            {
                "id": ["n0", "n1"],
                "mainnodeid": ["", ""],
                "geometry": [Point(0, 0), Point(10, 0)],
            },
            crs=CRS,
        )
    if frcsd_roads is None:
        frcsd_roads = gpd.GeoDataFrame(
            {
                "id": ["r1"],
                "snodeid": ["n0"],
                "enodeid": ["n1"],
                "direction": [0],
                "geometry": [LineString([(0, 0), (10, 0)])],
            },
            crs=CRS,
        )
    return LoadedInputs(
        segments=gpd.GeoDataFrame(
            {"id": pd.Series(dtype=str), "geometry": gpd.GeoSeries([], crs=CRS)},
            geometry="geometry",
            crs=CRS,
        ),
        swsd_roads=swsd_roads,
        swsd_nodes=swsd_nodes,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        rcsd_intersections=gpd.GeoDataFrame(
            {"id": pd.Series(dtype=str), "geometry": gpd.GeoSeries([], crs=CRS)},
            geometry="geometry",
            crs=CRS,
        ),
        drivezone=None,
        t05_anchor_audit=pd.DataFrame(),
        t06_cross_evidence={},
        processing_crs=CRS,
        crop_inner_geometry=None,
        input_audit={},
        topology_audit={},
        evidence_audit={},
    )


def _case(
    *,
    association_state: str,
    association_class: str = "B",
    support_ids: list[str] | None = None,
    step6_reason: str = "step6_blocked_by_association",
    constraint_induced_split: bool | None = None,
    meaningful_component_count: int = 0,
    raw_topology_guard: dict | None = None,
) -> T03CaseEvidence:
    business_connectivity = {}
    if constraint_induced_split is not None:
        business_connectivity["constraint_induced_split"] = (
            constraint_induced_split
        )
    return T03CaseEvidence(
        case_id="j",
        case_dir=Path("case"),
        step3_status={
            "case_id": "j",
            "target_group_node_ids": ["j", "t2"],
            "selected_road_ids": ["s1"],
            "drivezone_input_invalid_feature_count": 0,
        },
        association_status={
            "association_class": association_class,
            "association_state": association_state,
            "required_rcsdnode_ids": [],
            "support_rcsdroad_ids": support_ids or [],
            "raw_topology_guard_audit": raw_topology_guard or {},
        },
        step6_status={
            "association_class": association_class,
            "association_state": association_state,
            "reason": step6_reason,
            "required_rcsdnode_ids": [],
            "support_rcsdroad_ids": support_ids or [],
            "raw_topology_guard_audit": raw_topology_guard or {},
        },
        step6_audit={
            "assembly": {
                "pre_business_cleanup_meaningful_component_count": (
                    meaningful_component_count
                )
            },
            "validation": {"business_connectivity": business_connectivity},
        },
        step7_status={"case_id": "j", "step7_state": "rejected"},
        step7_audit={},
        artifact_audit={},
    )


def _sources(
    *cases: T03CaseEvidence,
    t07_rows: tuple[dict[str, str], ...] = (),
) -> JunctionSources:
    return JunctionSources(
        t03_cases=tuple(cases),
        t07_rows=t07_rows,
        t03_eligibility_nodes_path=None,
        audit={"t03": {}, "t07": {}, "silent_fix": False},
    )


def _loaded_required_movement(*, outgoing_direction: int) -> LoadedInputs:
    swsd_nodes = gpd.GeoDataFrame(
        {
            "id": ["j", "t2", "sw_in", "sw_out"],
            "mainnodeid": ["j", "j", "", ""],
            "has_evd": ["yes", "", "", ""],
            "is_anchor": ["no", "", "", ""],
            "kind_2": [4, "", "", ""],
            "geometry": [
                Point(0, 0),
                Point(0, 1),
                Point(-10, 0),
                Point(10, 1),
            ],
        },
        crs=CRS,
    )
    swsd_roads = gpd.GeoDataFrame(
        {
            "id": ["s_in", "s_internal", "s_out"],
            "snodeid": ["sw_in", "j", "t2"],
            "enodeid": ["j", "t2", "sw_out"],
            "direction": [2, 0, 2],
            "patch_id": ["p1", "p1", "p1"],
            "geometry": [
                LineString([(-10, 0), (0, 0)]),
                LineString([(0, 0), (0, 1)]),
                LineString([(0, 1), (10, 1)]),
            ],
        },
        crs=CRS,
    )
    frcsd_nodes = gpd.GeoDataFrame(
        {
            "id": ["fr_in", "portal", "fr_out"],
            "mainnodeid": ["", "", ""],
            "geometry": [Point(-10, 0), Point(0, 0.5), Point(10, 1)],
        },
        crs=CRS,
    )
    frcsd_roads = gpd.GeoDataFrame(
        {
            "id": ["fr_in", "fr_out"],
            "snodeid": ["fr_in", "portal"],
            "enodeid": ["portal", "fr_out"],
            "direction": [2, outgoing_direction],
            "geometry": [
                LineString([(-10, 0), (0, 0.5)]),
                LineString([(0, 0.5), (10, 1)]),
            ],
        },
        crs=CRS,
    )
    loaded = _loaded(frcsd_roads=frcsd_roads, frcsd_nodes=frcsd_nodes)
    return LoadedInputs(
        segments=loaded.segments,
        swsd_roads=swsd_roads,
        swsd_nodes=swsd_nodes,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        rcsd_intersections=loaded.rcsd_intersections,
        drivezone=loaded.drivezone,
        t05_anchor_audit=loaded.t05_anchor_audit,
        t06_cross_evidence=loaded.t06_cross_evidence,
        processing_crs=loaded.processing_crs,
        crop_inner_geometry=loaded.crop_inner_geometry,
        input_audit=loaded.input_audit,
        topology_audit=loaded.topology_audit,
        evidence_audit=loaded.evidence_audit,
    )


def _required_movement_case() -> T03CaseEvidence:
    case = _case(association_state="not_established")
    case.step3_status["selected_road_ids"] = [
        "s_in",
        "s_internal",
        "s_out",
    ]
    return case


def test_shared_degree1_terminal_collapse_is_candidate_only() -> None:
    result = audit_junction_quality(
        _loaded(),
        _sources(_case(association_state="not_established")),
        AuditConfig(),
        run_id="run",
    )

    assert not result.confirmed
    row = result.exclusions[0]
    assert row["decision_rule"] == "no_swsd_required_junction_movements"
    assert row["t03_candidate_signals"]["legacy_rule_a"] is True
    assert row["shared_terminal_endpoint_id"] == "n1"
    assert row["shared_terminal_endpoint_degree"] == 1
    assert row["raw_frcsd_terminal_degree"] == 1
    assert row["silent_fix"] is False


def test_one_terminal_and_one_interior_is_excluded() -> None:
    roads = gpd.GeoDataFrame(
        {
            "id": ["r1"],
            "snodeid": ["n0"],
            "enodeid": ["n1"],
            "direction": [0],
            "geometry": [LineString([(0, 0), (30, 0)])],
        },
        crs=CRS,
    )
    nodes = gpd.GeoDataFrame(
        {
            "id": ["n0", "n1"],
            "geometry": [Point(0, 0), Point(30, 0)],
        },
        crs=CRS,
    )
    result = audit_junction_quality(
        _loaded(
            target_points=(Point(30, 0), Point(15, 0)),
            frcsd_roads=roads,
            frcsd_nodes=nodes,
        ),
        _sources(_case(association_state="not_established")),
        AuditConfig(),
        run_id="run",
    )

    assert not result.confirmed
    assert (
        result.exclusions[0]["decision_rule"]
        == "no_swsd_required_junction_movements"
    )


def test_mainnode_alias_signal_without_required_movement_is_excluded() -> None:
    nodes = gpd.GeoDataFrame(
        {
            "id": ["n0", "n1", "alias"],
            "mainnodeid": ["", "alias", "alias"],
            "geometry": [Point(0, 0), Point(10, 0), Point(10, 1)],
        },
        crs=CRS,
    )

    result = audit_junction_quality(
        _loaded(frcsd_nodes=nodes),
        _sources(_case(association_state="not_established")),
        AuditConfig(),
        run_id="run",
    )

    assert not result.confirmed
    assert result.exclusions[0]["raw_frcsd_terminal_degree"] == 1


def test_multi_component_unmatched_support_is_candidate_only() -> None:
    roads = gpd.GeoDataFrame(
        {
            "id": ["r1", "r2"],
            "snodeid": ["n0", "n2"],
            "enodeid": ["n1", "n3"],
            "direction": [2, 3],
            "geometry": [
                LineString([(0, 0), (10, 0)]),
                LineString([(0, 30), (10, 30)]),
            ],
        },
        crs=CRS,
    )
    nodes = gpd.GeoDataFrame(
        {
            "id": ["n0", "n1", "n2", "n3"],
            "mainnodeid": ["", "", "", ""],
            "geometry": [
                Point(0, 0),
                Point(10, 0),
                Point(0, 30),
                Point(10, 30),
            ],
        },
        crs=CRS,
    )
    case = _case(
        association_state="review",
        support_ids=["r1", "r2"],
        step6_reason="step6_support_only_multi_target_fragmented_surface",
        constraint_induced_split=False,
        meaningful_component_count=3,
    )

    result = audit_junction_quality(
        _loaded(frcsd_roads=roads, frcsd_nodes=nodes),
        _sources(case),
        AuditConfig(),
        run_id="run",
    )

    assert not result.confirmed
    row = result.exclusions[0]
    assert row["t03_candidate_signals"]["legacy_rule_b"] is True
    assert row["unmatched_support_component_ids"]


def test_formal_t03_unmatched_support_guard_remains_candidate_only() -> None:
    roads = gpd.GeoDataFrame(
        {
            "id": ["r1", "r2"],
            "snodeid": ["n0", "n2"],
            "enodeid": ["n1", "n3"],
            "direction": [2, 3],
            "geometry": [
                LineString([(0, 0), (10, 0)]),
                LineString([(0, 30), (10, 30)]),
            ],
        },
        crs=CRS,
    )
    nodes = gpd.GeoDataFrame(
        {
            "id": ["n0", "n1", "n2", "n3"],
            "geometry": [
                Point(0, 0),
                Point(10, 0),
                Point(0, 30),
                Point(10, 30),
            ],
        },
        crs=CRS,
    )
    guard = {
        "blocked": True,
        "reason": "association_raw_multi_component_unmatched_support",
        "unmatched_support": True,
    }
    case = _case(
        association_state="not_established",
        association_class="A",
        support_ids=["r1", "r2"],
        raw_topology_guard=guard,
    )

    result = audit_junction_quality(
        _loaded(frcsd_roads=roads, frcsd_nodes=nodes),
        _sources(case),
        AuditConfig(),
        run_id="run",
    )

    assert not result.confirmed
    row = result.exclusions[0]
    assert row["t03_candidate_signals"]["formal_unmatched_support"] is True
    assert row["decision_rule"] == "no_swsd_required_junction_movements"


@pytest.mark.parametrize(
    ("guard", "signal_field"),
    [
        (
            {
                "blocked": True,
                "reason": (
                    "association_raw_compact_alias_directional_terminal_mismatch"
                ),
                "compact_directional_terminal_mismatch": True,
                "target_group_span_m": 0.5,
                "source_incoming_count": 1,
                "source_outgoing_count": 1,
                "directional_terminal_rows": [
                    {"one_sided_terminal": True}
                ],
                "published_support_rcsdroad_ids": ["r1"],
            },
            "formal_directional_terminal",
        ),
        (
            {
                "blocked": True,
                "reason": "association_raw_connected_semantic_core_ambiguity",
                "connected_semantic_core_ambiguity": True,
                "connected_semantic_core_rows": [
                    {"connecting_rcsdroad_ids": ["r1"]}
                ],
            },
            "formal_connected_semantic_core",
        ),
    ],
)
def test_formal_t03_j01_topology_guards_are_reverified(
    guard: dict,
    signal_field: str,
) -> None:
    result = audit_junction_quality(
        _loaded(),
        _sources(
            _case(
                association_state="not_established",
                association_class="A",
                support_ids=["r1"],
                raw_topology_guard=guard,
            )
        ),
        AuditConfig(),
        run_id="run",
    )

    assert not result.confirmed
    row = result.exclusions[0]
    assert row["t03_candidate_signals"][signal_field] is True
    assert row["decision_rule"] == "no_swsd_required_junction_movements"


def test_required_swsd_movement_direction_deficit_is_confirmed() -> None:
    result = audit_junction_quality(
        _loaded_required_movement(outgoing_direction=3),
        _sources(_required_movement_case()),
        AuditConfig(),
        run_id="run",
    )

    assert len(result.confirmed) == 1
    row = result.confirmed[0]
    assert row["decision_rule"] == (
        "raw_frcsd_required_junction_movement_missing_confirmed"
    )
    movement = row["required_junction_movement_audit"][
        "required_movements"
    ][0]
    assert movement["status"] == "missing"
    assert movement["missing_reason"] == "boundary_direction_role_missing"


def test_equivalent_required_swsd_movement_excludes_t03_signal() -> None:
    result = audit_junction_quality(
        _loaded_required_movement(outgoing_direction=2),
        _sources(_required_movement_case()),
        AuditConfig(),
        run_id="run",
    )

    assert not result.confirmed
    row = result.exclusions[0]
    assert row["decision_rule"] == (
        "all_required_junction_movements_equivalent"
    )
    movement_audit = row["required_junction_movement_audit"]
    assert movement_audit["status"] == "equivalent"
    # Crossing Roads have zero geometric distance at the Junction. They must
    # still map only to the directionally aligned SWSD boundary arm.
    assert movement_audit["boundary_arm_audits"]["s_in"][
        "physical_candidate_count"
    ] == 1
    assert movement_audit["boundary_arm_audits"]["s_out"][
        "physical_candidate_count"
    ] == 1
    assert movement_audit["boundary_arm_audits"]["s_in"]["candidates"][0][
        "road_id"
    ] == "fr_in"
    assert movement_audit["boundary_arm_audits"]["s_out"]["candidates"][0][
        "road_id"
    ] == "fr_out"


def test_constraint_split_and_cross_layer_are_precision_first_exclusions() -> None:
    roads = gpd.GeoDataFrame(
        {
            "id": ["r1", "r2"],
            "snodeid": ["n0", "n2"],
            "enodeid": ["n1", "n3"],
            "direction": [0, 0],
            "geometry": [
                LineString([(0, 0), (10, 0)]),
                LineString([(0, 30), (10, 30)]),
            ],
        },
        crs=CRS,
    )
    nodes = gpd.GeoDataFrame(
        {
            "id": ["n0", "n1", "n2", "n3"],
            "geometry": [
                Point(0, 0),
                Point(10, 0),
                Point(0, 30),
                Point(10, 30),
            ],
        },
        crs=CRS,
    )
    case = _case(
        association_state="review",
        support_ids=["r1", "r2"],
        step6_reason="step6_support_only_multi_target_fragmented_surface",
        constraint_induced_split=True,
        meaningful_component_count=3,
    )

    split_result = audit_junction_quality(
        _loaded(frcsd_roads=roads, frcsd_nodes=nodes),
        _sources(case),
        AuditConfig(),
        run_id="run",
    )
    layer_case = _case(
        association_state="review",
        support_ids=["r1", "r2"],
        step6_reason="step6_support_only_multi_target_fragmented_surface",
        constraint_induced_split=False,
        meaningful_component_count=3,
    )
    layer_case.step6_audit["cross_layer_status"] = (
        "high_confidence_cross_layer"
    )
    layer_result = audit_junction_quality(
        _loaded(
            frcsd_roads=roads,
            frcsd_nodes=nodes,
            swsd_patch_id="p1,p2",
        ),
        _sources(layer_case),
        AuditConfig(),
        run_id="run",
    )

    assert split_result.exclusions[0]["decision_rule"] == "constraint_induced_split"
    assert (
        layer_result.exclusions[0]["decision_rule"]
        == "high_confidence_cross_layer_excluded"
    )


def test_t07_fail2_expands_per_junction_with_shared_conflict_group() -> None:
    rows = (
        {
            "failure_type": "fail2",
            "target_id": "j",
            "related_target_ids": ["j", "t2"],
            "base_ids": ["base"],
            "target_group_node_ids_by_target": {
                "j": ["j"],
                "t2": ["t2"],
            },
        },
    )

    result = audit_junction_quality(
        _loaded(),
        _sources(t07_rows=rows),
        AuditConfig(),
        run_id="run",
    )

    assert len(result.confirmed) == 2
    assert {row["junction_id"] for row in result.confirmed} == {"j", "t2"}
    assert {row["issue_type"] for row in result.confirmed} == {
        "junction_anchor_many_to_one"
    }
    assert {row["issue_code"] for row in result.confirmed} == {"J04"}
    assert {row["result_status"] for row in result.confirmed} == {"confirmed"}
    assert len({row["conflict_group_id"] for row in result.confirmed}) == 1
    assert result.audit["counts"]["t07_ignored_row_count"] == 0
    assert result.audit["counts"]["t07_step3_cardinality_import_count"] == 0


def test_duplicate_junction_candidate_id_is_blocked() -> None:
    row = {
        "failure_type": "fail1",
        "target_id": "j",
        "related_target_ids": ["j"],
        "base_ids": ["base"],
        "target_group_node_ids": ["j", "t2"],
    }

    with pytest.raises(T12ContractError, match="duplicate Junction candidate_id"):
        audit_junction_quality(
            _loaded(),
            _sources(t07_rows=(row, row)),
            AuditConfig(),
            run_id="run",
        )


def test_junction_outputs_are_point_layers_and_counts_conserve(
    tmp_path: Path,
) -> None:
    result = audit_junction_quality(
        _loaded_required_movement(outgoing_direction=3),
        _sources(_required_movement_case()),
        AuditConfig(),
        run_id="run",
    )

    paths = write_junction_outputs(
        run_root=tmp_path,
        processing_crs=CRS,
        result=result,
    )

    candidates = gpd.read_file(paths["junction_candidates_gpkg"])
    confirmed = gpd.read_file(paths["junction_confirmed_gpkg"])
    assert set(candidates.geometry.geom_type) == {"Point"}
    assert set(confirmed.geometry.geom_type) == {"Point"}
    assert len(result.candidates) == len(result.confirmed) + len(result.exclusions)
    assert paths["junction_evidence_gpkg"].is_file()
