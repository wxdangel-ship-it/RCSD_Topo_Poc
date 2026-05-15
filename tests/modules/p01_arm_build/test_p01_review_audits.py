from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p01_arm_build.final_road_next_road import (
    FrcsdGenerationAudit,
    FrcsdRoadNextRoadFinalResult,
)
from rcsd_topo_poc.modules.p01_arm_build.models import (
    ArmMovement,
    DatasetBuildResult,
    InitialArm,
    IssueReport,
    JunctionContext,
    LoadedDataset,
    NodeRecord,
    RoadRecord,
    VectorLayer,
)
from rcsd_topo_poc.modules.p01_arm_build.review import (
    render_movement_turn_audit_png,
    render_pass_capability_audit_png,
)


def _layer(tmp_path: Path) -> VectorLayer:
    return VectorLayer(path=tmp_path / "fixture.gpkg", crs="EPSG:3857", crs_wkt=None, schema_properties=(), feature_count=0)


def _loaded(tmp_path: Path) -> LoadedDataset:
    return LoadedDataset(
        dataset="FRCSD",
        nodes={
            "j": NodeRecord("j", "j", "4", Point(0, 0)),
            "e": NodeRecord("e", "", "1", Point(60, 0)),
            "n": NodeRecord("n", "", "1", Point(0, 60)),
        },
        roads={
            "r_e": RoadRecord("r_e", "j", "e", 2, "0", LineString([(0, 0), (60, 0)])),
            "r_n": RoadRecord("r_n", "j", "n", 2, "0", LineString([(0, 0), (0, 60)])),
        },
        node_layer=_layer(tmp_path),
        road_layer=_layer(tmp_path),
    )


def _result() -> DatasetBuildResult:
    arm_e = InitialArm(
        dataset="FRCSD",
        current_junction_id="j",
        initial_arm_id="F1",
        terminal_type="semantic_boundary",
        terminal_junction_id="e",
        terminal_member_node_ids=("e",),
        member_road_ids=("r_e",),
        seed_road_ids=("r_e",),
        connector_road_ids=(),
        inbound_member_road_ids=("r_e",),
        outbound_member_road_ids=(),
        bidirectional_member_road_ids=(),
        build_status="stable",
        risk_flags=(),
        trunk_road_ids=("r_e",),
        trunk_status="partial",
    )
    arm_n = InitialArm(
        dataset="FRCSD",
        current_junction_id="j",
        initial_arm_id="F2",
        terminal_type="semantic_boundary",
        terminal_junction_id="n",
        terminal_member_node_ids=("n",),
        member_road_ids=("r_n",),
        seed_road_ids=("r_n",),
        connector_road_ids=(),
        inbound_member_road_ids=(),
        outbound_member_road_ids=("r_n",),
        bidirectional_member_road_ids=(),
        build_status="stable",
        risk_flags=(),
        trunk_road_ids=("r_n",),
        trunk_status="partial",
    )
    movement = ArmMovement(
        movement_id="m1",
        dataset="FRCSD",
        current_junction_id="j",
        from_arm_id="F1",
        to_arm_id="F2",
        movement_type="left",
        movement_type_source="fixture",
        movement_type_confidence="high",
        movement_type_reason="fixture",
        permission_evidence_status="allowed_supported",
        road_movement_evidence_ids=("e1",),
        from_road_ids=("r_e",),
        to_road_ids=("r_n",),
        evidence_count=1,
        turn_type_summary={},
        has_advance_left_road_evidence=False,
        related_advance_right_relation_ids=(),
    )
    return DatasetBuildResult(
        dataset="FRCSD",
        junction_id="j",
        context=JunctionContext(
            dataset="FRCSD",
            junction_id="j",
            member_node_ids=("j",),
            internal_road_ids=(),
            inbound_seed_road_ids=("r_e",),
            outbound_seed_road_ids=("r_n",),
            bidirectional_seed_road_ids=(),
            excluded_right_turn_road_ids=(),
            advance_left_turn_road_ids=(),
            advance_right_turn_road_ids=(),
            formway_missing_road_ids=(),
            formway_unparseable_road_ids=(),
            special_formway_issue_flags=(),
            input_issue_flags=(),
        ),
        initial_arms=(arm_e, arm_n),
        final_arms=(),
        final_arm_validation=(),
        arm_corridor_evidence=(),
        corrected_final_arms=(),
        advance_right_turn_relations=(),
        road_movement_evidence=(),
        arm_movements=(movement,),
        arm_receiving_road_roles=(),
        trunk_corrections=(),
        local_arm_candidates=(),
        traces=(),
        decisions=(),
        issue_report=IssueReport(dataset="FRCSD", current_junction_id="j", issues=(), issue_counts={}),
        review_priority="P2",
        metrics={"arm_movement_count": 1},
    )


def _final_result() -> FrcsdRoadNextRoadFinalResult:
    audit = FrcsdGenerationAudit(
        f_road_id="r_e",
        f_next_road_id="r_n",
        from_arm_id="F1",
        to_arm_id="F2",
        movement_type="left",
        from_road_role="trunk",
        to_road_role="trunk",
        from_road_source="1",
        to_road_source="1",
        primary_source="RCSD",
        reference_source="RCSD",
        generation_rule="fixture",
        permission_status="allowed",
        source_evidence_ids=("e1",),
        confidence="high",
        issue_flags=(),
    )
    return FrcsdRoadNextRoadFinalResult(
        features=(),
        source_road_map=(),
        source_movement_policy_swsd=(),
        source_movement_policy_rcsd=(),
        arm_source_profiles=(),
        source_arm_pass_rules_swsd=(),
        source_arm_pass_rules_rcsd=(),
        final_generation_decisions=(),
        parallel_branch_alignment=(),
        audit=(audit,),
        issue_report={"issues": [], "issue_counts": {}},
        metrics={"frcsd_generated_road_next_road_count": 1},
    )


def test_review_audit_pngs_are_rendered(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    result = _result()
    movement_path = tmp_path / "movement.png"
    pass_path = tmp_path / "pass.png"

    render_movement_turn_audit_png(movement_path, loaded, result)
    render_pass_capability_audit_png(pass_path, loaded, result, _final_result())

    assert movement_path.stat().st_size > 0
    assert pass_path.stat().st_size > 0
