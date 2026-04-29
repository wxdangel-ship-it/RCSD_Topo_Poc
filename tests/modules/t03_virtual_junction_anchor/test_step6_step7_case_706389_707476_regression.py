from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    load_association_case_specs,
    load_association_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_association_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import (
    VISUAL_V1,
    VISUAL_V5,
    build_step7_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import FinalizationContext


REAL_ANCHOR_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor")
REAL_ANCHOR_F_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor_F")
REAL_STEP3_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003")
REAL_ANCHOR_F_STEP3_ROOT = Path(
    "/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_visual_audit/"
    "20260428_anchor_anchorf_required_support_split_v002/step3/anchor_f_step3_required_support_split_v002"
)


def _selected_road_covered_length(finalization_context: FinalizationContext, step6_result: object, road_id: str) -> float:
    road = next(
        road
        for road in finalization_context.association_context.step1_context.roads
        if road.road_id == road_id
    )
    polygon = step6_result.output_geometries.polygon_final_geometry
    if polygon is None:
        return 0.0
    return road.geometry.intersection(polygon).length


def _selected_road_seed_length(finalization_context: FinalizationContext, step6_result: object, road_id: str) -> float:
    road = next(
        road
        for road in finalization_context.association_context.step1_context.roads
        if road.road_id == road_id
    )
    polygon = step6_result.output_geometries.polygon_seed_geometry
    if polygon is None:
        return 0.0
    return road.geometry.intersection(polygon).length


def _load_real_association_context(case_id: str):
    if REAL_ANCHOR_ROOT.is_dir() and (REAL_ANCHOR_ROOT / case_id).is_dir():
        if not REAL_STEP3_ROOT.is_dir():
            pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")
        specs, _ = load_association_case_specs(
            case_root=REAL_ANCHOR_ROOT,
            case_ids=[case_id],
            exclude_case_ids=[],
        )
        return load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    if REAL_ANCHOR_F_ROOT.is_dir() and (REAL_ANCHOR_F_ROOT / case_id).is_dir():
        if not REAL_ANCHOR_F_STEP3_ROOT.is_dir():
            pytest.skip(f"missing real Anchor_F Step3 root: {REAL_ANCHOR_F_STEP3_ROOT}")
        specs, _ = load_association_case_specs(
            case_root=REAL_ANCHOR_F_ROOT,
            case_ids=[case_id],
            exclude_case_ids=[],
        )
        return load_association_context(case_spec=specs[0], step3_root=REAL_ANCHOR_F_STEP3_ROOT)
    pytest.skip(f"missing real Anchor/Anchor_F case: {case_id}")


@pytest.mark.parametrize("case_id", ["706389", "707476", "709431"])
def test_real_cases_706389_707476_and_709431_remain_accepted_after_boundary_first_and_u_turn_filter(case_id: str) -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert step6_result.geometry_established is True
    assert step6_result.extra_status_fields["foreign_overlap_area_m2"] == 0.0
    assert step6_result.extra_status_fields["within_direction_boundary_ok"] is True
    assert step6_result.audit_doc["assembly"]["foreign_mask_mode"] == "road_like_1m_mask"
    expected_foreign_sources = (
        ["excluded_rcsdroad_geometry"]
        if association_case_result.extra_status_fields["foreign_mask_source_rcsdroad_ids"]
        else []
    )
    assert step6_result.audit_doc["assembly"]["foreign_mask_sources"] == expected_foreign_sources
    assert (
        step6_result.audit_doc["validation"]["required_rc_cover_mode"]
        == "local_required_rc_within_direction_boundary"
    )
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1


@pytest.mark.parametrize(
    ("case_id", "expected_class", "expected_dropped_node_ids"),
    [
        ("724123", "B", ["5395796452837696"]),
        ("854878", "B", []),
        ("948228", "B", ["5384370798601867"]),
        ("74232960", "B", ["5387984476901824", "5387984476901825"]),
        ("74419702", "A", []),
        ("941714", "A", []),
        ("500669133", "B", ["5384380965848530"]),
        ("500860756", "B", ["5387931628737410"]),
        ("1226342", "B", ["5384383348150317", "5384383348150318"]),
        ("989550", "A", []),
        ("42342021", "B", []),
    ],
)
def test_real_cases_required_core_gate_matches_visual_audit_semantics(
    case_id: str,
    expected_class: str,
    expected_dropped_node_ids: list[str],
) -> None:
    association_context = _load_real_association_context(case_id)
    association_case_result = build_association_case_result(association_context)

    assert association_case_result.association_class == expected_class
    assert association_case_result.extra_status_fields["required_rcsdnode_gate_dropped_ids"] == expected_dropped_node_ids
    if expected_class == "B":
        assert association_case_result.extra_status_fields["required_rcsdnode_ids"] == []
        assert association_case_result.extra_status_fields["required_rcsdroad_ids"] == []
        assert association_case_result.extra_status_fields["support_rcsdroad_ids"]


def test_real_case_706389_uses_trace_based_single_sided_horizontal_mouth_cut() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["706389"],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }

    assert step7_result.step7_state == "accepted"
    assert association_case_result.extra_status_fields["u_turn_rcsdroad_ids"] == [
        "5395781419598971",
    ]
    assert association_case_result.extra_status_fields["u_turn_candidate_rcsdroad_ids"] == [
        "5395781419598971",
    ]
    u_turn_audit = association_case_result.extra_status_fields["u_turn_candidate_rcsdroad_audit"][
        "5395781419598971"
    ]
    assert u_turn_audit["decision"] == "qualified_u_turn"
    assert u_turn_audit["graph_fallback_applied"] is True
    assert u_turn_audit["active_scope_reason"] == "road_does_not_connect_two_semantic_groups"
    assert u_turn_audit["active_scope_missing_endpoint_node_ids"] == ["5395732498090121"]
    assert (
        u_turn_audit["rejected_by_same_path_terminal"]
        is False
    )
    assert association_case_result.extra_status_fields["u_turn_rejected_by_same_path_chain_ids"] == []
    assert association_case_result.extra_status_fields["same_path_chain_protected_rcsdroad_ids"] == [
        "5395781419598881",
        "5395781419598961",
    ]
    assert association_case_result.extra_status_fields["same_path_chain_terminal_rcsdnode_ids"] == [
        "5395732498090127",
        "5395732498090139",
    ]
    assert association_case_result.extra_status_fields["t_mouth_strong_related_rcsdnode_ids"] == [
        "5395732498090127",
        "5395732498090139",
    ]
    assert "5395781419599024" in association_case_result.extra_status_fields["related_rcsdroad_ids"]
    assert "5395781419598971" not in association_case_result.extra_status_fields["related_rcsdroad_ids"]
    assert association_case_result.output_geometries.u_turn_rcsdroad_geometry is not None
    assert "5395781419598924" in association_case_result.extra_status_fields["support_rcsdroad_ids"]
    assert "5395781419598924" not in association_case_result.extra_status_fields["related_local_rcsdroad_ids"]
    assert association_case_result.extra_status_fields["related_outside_scope_rcsdroad_ids"] == []
    assert "5395732498090175" not in association_case_result.extra_status_fields["related_rcsdroad_ids"]
    assert "5395732498090175" in association_case_result.extra_status_fields["foreign_mask_source_rcsdroad_ids"]
    assert "5395732498090175" not in step6_result.extra_status_fields["local_required_rcsdroad_ids"]
    assert step6_result.extra_status_fields["foreign_mask_source_rcsdroad_ids"] == [
        "5395732498090175",
        "5395732498090244",
    ]
    assert step6_result.extra_status_fields["support_rcsdroad_ids"] == ["5395781419598924"]
    assert branches["629431331"]["window_mode"] == "single_sided_semantic_plus_5m"
    assert branches["629431331"]["special_rule_applied"] is True
    assert branches["629431331"]["cut_length_m"] == pytest.approx(22.863822)
    assert branches["629431331"]["trace_status"] == "trace_selected_semantic_plus_5m"
    assert branches["629431331"]["trace_traced_rcsdnode_ids"] == [
        "5395732498090139",
    ]
    assert branches["58163436"]["window_mode"] == "single_sided_semantic_plus_5m"
    assert branches["58163436"]["special_rule_applied"] is True
    assert branches["58163436"]["cut_length_m"] == pytest.approx(45.417283)
    assert branches["58163436"]["trace_status"] == "trace_selected_semantic_plus_5m"
    assert branches["58163436"]["trace_traced_rcsdnode_ids"] == [
        "5395732498090127",
    ]
    assert branches["617732646"]["window_mode"] == "cut_at_20m"
    assert branches["617732646"]["cut_length_m"] == 20.0
    assert _selected_road_covered_length(finalization_context, step6_result, "58163436") == pytest.approx(
        branches["58163436"]["cut_length_m"],
    )
    assert _selected_road_covered_length(finalization_context, step6_result, "617732646") == pytest.approx(20.0)
    assert _selected_road_covered_length(finalization_context, step6_result, "629431331") == pytest.approx(
        branches["629431331"]["cut_length_m"],
    )


def test_real_case_705817_uses_group_level_rcsdnode_degree_for_composite_junction() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["705817"],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert step7_result.step7_state == "accepted"
    assert association_case_result.audit_doc["step4"]["raw_rcsdnode_degree_map"]["5387934112026681"] == 4
    assert association_case_result.audit_doc["step4"]["rcsdnode_degree_map"]["5387934112026681"] == 4
    assert "5387934112026681" not in association_case_result.extra_status_fields["nonsemantic_connector_rcsdnode_ids"]
    assert association_case_result.association_class == "B"
    assert association_case_result.extra_status_fields["required_rcsdroad_ids"] == []
    assert association_case_result.extra_status_fields["support_rcsdroad_ids"] == [
        "5387934112027003",
        "5387934112027048",
    ]
    assert association_case_result.extra_status_fields["related_rcsdnode_ids"] == []
    assert association_case_result.extra_status_fields["related_group_rcsdroad_ids"] == []
    assert association_case_result.extra_status_fields["related_rcsdroad_ids"] == []
    assert association_case_result.extra_status_fields["related_outside_scope_rcsdroad_ids"] == []
    assert association_case_result.extra_status_fields["foreign_mask_source_rcsdroad_ids"] == [
        "5387934112027002",
        "5387934112027016",
    ]
    assert step6_result.extra_status_fields["related_group_rcsdroad_ids"] == []
    assert step6_result.extra_status_fields["support_rcsdroad_ids"] == [
        "5387934112027003",
        "5387934112027048",
    ]
    assert step6_result.extra_status_fields["local_required_rcsdroad_ids"] == []
    assert step6_result.extra_status_fields["foreign_mask_source_rcsdroad_ids"] == [
        "5387934112027002",
        "5387934112027016",
    ]
    assert step6_result.extra_status_fields["foreign_overlap_area_m2"] == 0.0


def test_real_case_707476_stops_related_outside_scope_at_current_semantic_boundary() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["707476"],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert step7_result.step7_state == "accepted"
    assert association_case_result.association_class == "B"
    assert association_case_result.extra_status_fields["required_rcsdnode_ids"] == []
    assert association_case_result.extra_status_fields["required_rcsdroad_ids"] == []
    assert association_case_result.extra_status_fields["u_turn_rcsdroad_ids"] == [
        "5389859095908396",
        "5389859095908415",
        "5389859095908614",
    ]
    assert association_case_result.extra_status_fields["u_turn_candidate_rcsdroad_ids"] == [
        "5389859095908396",
        "5389859095908415",
        "5389859095908614",
        "5389861209843263",
        "5389861209843283",
    ]
    assert association_case_result.extra_status_fields["u_turn_rejected_by_same_path_chain_ids"] == [
        "5389861209843263",
        "5389861209843283",
    ]
    assert association_case_result.extra_status_fields["same_path_chain_protected_rcsdroad_ids"] == [
        "5389859095908396",
        "5389859095908415",
        "5389861209843263",
        "5389861209843283",
    ]
    assert (
        association_case_result.extra_status_fields["u_turn_candidate_rcsdroad_audit"]["5389859095908614"]["reason"]
        == "effective_degree3_parallel_trunks_opposite_flow"
    )
    assert (
        association_case_result.extra_status_fields["u_turn_candidate_rcsdroad_audit"]["5389859095908396"][
            "rejected_by_same_path_chain"
        ]
        is False
    )
    assert association_case_result.extra_status_fields["related_outside_scope_rcsdroad_ids"] == []
    assert association_case_result.extra_status_fields["related_local_rcsdroad_ids"] == []
    assert "5389861209843263" in association_case_result.extra_status_fields["support_rcsdroad_ids"]
    assert "5389861209843283" in association_case_result.extra_status_fields["support_rcsdroad_ids"]
    for road_id in ["5389859095908357", "5389859095908433", "5389859095908612", "5389859095908616"]:
        assert road_id not in association_case_result.extra_status_fields["related_rcsdroad_ids"]
        assert road_id in association_case_result.extra_status_fields["foreign_mask_source_rcsdroad_ids"]
    assert step6_result.geometry_established is True
    assert step6_result.extra_status_fields["foreign_overlap_area_m2"] == 0.0
    assert step6_result.extra_status_fields["related_outside_scope_rcsdroad_ids"] == []


def test_real_case_506658745_filters_single_self_induced_u_turn_candidate() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["506658745"],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    target_rcsdroad_id = "5396420564750070"
    target_audit = association_case_result.extra_status_fields["u_turn_candidate_rcsdroad_audit"][
        target_rcsdroad_id
    ]

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert association_case_result.extra_status_fields["u_turn_rcsdroad_ids"] == [target_rcsdroad_id]
    assert association_case_result.extra_status_fields["u_turn_rejected_by_same_path_chain_ids"] == []
    assert target_rcsdroad_id not in association_case_result.extra_status_fields["same_path_chain_protected_rcsdroad_ids"]
    assert target_audit["decision"] == "qualified_u_turn"
    assert target_audit["rejected_by_same_path_chain"] is False
    assert target_audit["rejected_by_same_path_terminal"] is False
    assert target_rcsdroad_id not in association_case_result.extra_status_fields["required_rcsdroad_ids"]
    assert target_rcsdroad_id not in association_case_result.extra_status_fields["related_rcsdroad_ids"]


def test_real_case_709632_stops_related_outside_scope_at_compact_mainnodeid_group_boundary() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["709632"],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert association_case_result.association_class == "B"
    assert association_case_result.extra_status_fields["support_rcsdroad_ids"] == [
        "5396159040979360",
    ]
    assert association_case_result.extra_status_fields["related_local_rcsdroad_ids"] == []
    assert step6_result.extra_status_fields["support_rcsdroad_ids"] == [
        "5396159040979360",
    ]
    assert association_case_result.extra_status_fields["related_outside_scope_rcsdroad_ids"] == []
    assert "5396159040979287" not in association_case_result.extra_status_fields["related_rcsdroad_ids"]
    assert "5396159040979126" not in association_case_result.extra_status_fields["related_rcsdroad_ids"]
    assert "5396159040979287" in association_case_result.extra_status_fields["foreign_mask_source_rcsdroad_ids"]
    assert "5396159040979126" in association_case_result.extra_status_fields["foreign_mask_source_rcsdroad_ids"]
    assert "5396136191663929" not in association_case_result.extra_status_fields["nonsemantic_connector_rcsdnode_ids"]
    assert "5396136191663929" in association_case_result.extra_status_fields["true_foreign_rcsdnode_ids"]
    assert association_case_result.audit_doc["step4"]["rcsdnode_degree_map"]["5396136191663929"] > 2
    assert association_case_result.audit_doc["step4"]["related_outside_scope_rcsdroad_audit"] == {}


def test_real_case_42342021_filters_short_geometry_u_turns_before_required_core() -> None:
    association_context = _load_real_association_context("42342021")
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert association_case_result.association_class == "B"
    assert association_case_result.extra_status_fields["required_rcsdnode_ids"] == []
    assert association_case_result.extra_status_fields["required_rcsdroad_ids"] == []
    assert association_case_result.extra_status_fields["u_turn_rcsdroad_ids"] == [
        "5384385998959947",
        "5384385998959949",
        "5384385998960080",
        "5384385998960115",
    ]
    assert association_case_result.extra_status_fields["u_turn_rejected_by_same_path_chain_ids"] == [
        "5384389925144412",
        "5384389925144446",
    ]
    assert association_case_result.extra_status_fields["support_rcsdroad_ids"]


@pytest.mark.parametrize(
    ("case_id", "outside_road_ids"),
    [
        (
            "709431",
            [
                "5387726409826740",
            ],
        ),
        (
            "724123",
            [
                "5395796452837773",
            ],
        ),
        (
            "724916",
            [
                "5396411908232752",
            ],
        ),
        (
            "758888",
            [
                "5384378751517869",
            ],
        ),
    ],
)
def test_real_cases_stop_support_or_remote_connector_roads_from_becoming_related(
    case_id: str,
    outside_road_ids: list[str],
) -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert association_case_result.extra_status_fields["related_outside_scope_rcsdroad_ids"] == []
    assert association_case_result.audit_doc["step4"]["related_outside_scope_rcsdroad_audit"] == {}
    for road_id in outside_road_ids:
        assert road_id not in association_case_result.extra_status_fields["related_rcsdroad_ids"]
        assert road_id in association_case_result.extra_status_fields["foreign_mask_source_rcsdroad_ids"]
    assert step6_result.extra_status_fields["foreign_overlap_area_m2"] == 0.0


@pytest.mark.parametrize(
    ("case_id", "expected_road_ids"),
    [
        ("707476", ["49232007", "49232019", "49232020", "966107", "966084"]),
        ("709431", ["507428675", "517729921", "601518228"]),
    ],
)
def test_real_cases_707476_and_709431_keep_final_geometry_within_20m_directional_boundary(
    case_id: str,
    expected_road_ids: list[str],
) -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)

    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }

    for road_id in expected_road_ids:
        assert branches[road_id]["window_mode"] == "cut_at_20m"
        assert branches[road_id]["cut_length_m"] == 20.0
        assert _selected_road_covered_length(finalization_context, step6_result, road_id) == pytest.approx(
            _selected_road_seed_length(finalization_context, step6_result, road_id),
            abs=1e-6,
        )
    if case_id == "709431":
        assert association_case_result.association_class == "B"
        assert branches["507428675"]["trace_status"] == "no_trace"
        assert branches["517729921"]["trace_status"] == "no_trace"


def test_real_case_724123_keeps_all_selected_arms_at_generic_20m_without_rcsd_semantic_mouth() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["724123"],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1
    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }
    assert step6_result.audit_doc["assembly"]["target_connected_boundary_fallback_applied"] is False
    for road_id in ["82197984", "46438267", "1024939"]:
        assert branches[road_id]["window_mode"] == "cut_at_20m"
        assert branches[road_id]["cut_length_m"] == 20.0
        assert _selected_road_covered_length(finalization_context, step6_result, road_id) == pytest.approx(20.0)


@pytest.mark.parametrize(
    ("case_id", "expected_visual_class"),
    [
        ("758888", VISUAL_V1),
        ("851884", VISUAL_V1),
    ],
)
def test_real_cases_758888_and_851884_use_trace_based_horizontal_mouth_cut_without_global_fallback(
    case_id: str,
    expected_visual_class: str,
) -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == expected_visual_class
    assert step6_result.audit_doc["assembly"]["target_connected_boundary_fallback_applied"] is False
    assert step6_result.audit_doc["assembly"]["step3_two_node_t_bridge_inherited"] is True
    assert step6_result.audit_doc["assembly"]["polygon_seed_metrics"]["component_count"] == 1
    assert step6_result.audit_doc["assembly"]["polygon_final_metrics"]["component_count"] == 1
    if case_id == "758888":
        assert association_case_result.extra_status_fields["required_rcsdnode_ids"] == [
            "5391487258664562",
        ]
        assert association_case_result.extra_status_fields["single_sided_terminal_required_rcsdnode_ids"] == [
            "5391487258664613",
        ]
        assert association_case_result.extra_status_fields["single_sided_terminal_pruned_rcsdroad_ids"] == [
            "5391486620140073",
            "5391487258664703",
        ]
        assert "5391487258664613" not in association_case_result.extra_status_fields["related_rcsdnode_ids"]
        assert "5391487258664703" not in association_case_result.extra_status_fields["related_rcsdroad_ids"]
        assert branches["30180138"]["window_mode"] == "cut_at_20m"
        assert branches["30180138"]["trace_status"] == "trace_pair_incomplete"
        assert branches["30180138"]["cut_length_m"] == 20.0
        assert branches["611608459"]["window_mode"] == "cut_at_20m"
        assert branches["611608459"]["cut_length_m"] == 20.0
        expected_roads = ["30180138", "611608459", "15593730", "71775031"]
    else:
        assert branches["58285198"]["window_mode"] == "single_sided_semantic_plus_5m"
        assert branches["58285198"]["trace_status"] == "trace_selected_semantic_plus_5m"
        assert branches["58285198"]["cut_length_m"] == pytest.approx(29.253883)
        assert branches["506188765"]["window_mode"] == "cut_at_20m"
        assert branches["506188765"]["cut_length_m"] == 20.0
        expected_roads = ["58285198", "506188765", "1103051", "67337978", "87963411"]
    for road_id in expected_roads:
        assert _selected_road_covered_length(finalization_context, step6_result, road_id) == pytest.approx(
            _selected_road_seed_length(finalization_context, step6_result, road_id),
            abs=1e-2,
        )


@pytest.mark.parametrize(
    ("case_id", "expected_lengths"),
    [
        (
            "761318",
            {
                "42677708": 23.424463,
                "62426952": 20.0,
                "18835523": 28.715327,
            },
        ),
        (
            "769081",
            {
                "49597776": 29.036822,
                "986260": 20.0,
                "627312741": 20.0,
            },
        ),
    ],
)
def test_real_cases_761318_and_769081_keep_each_branch_at_its_own_cap_without_sibling_diagonal_overcut(
    case_id: str,
    expected_lengths: dict[str, float],
) -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert step6_result.audit_doc["assembly"]["target_connected_boundary_fallback_applied"] is False
    for road_id, expected_length in expected_lengths.items():
        assert branches[road_id]["cut_length_m"] == pytest.approx(expected_length)
        assert _selected_road_covered_length(finalization_context, step6_result, road_id) == pytest.approx(
            _selected_road_seed_length(finalization_context, step6_result, road_id),
            abs=1e-2,
        )
    if case_id == "761318":
        assert _selected_road_covered_length(finalization_context, step6_result, "518898861") > 16.0
        assert step6_result.audit_doc["assembly"]["step3_two_node_t_bridge_inherited"] is True
        assert step6_result.audit_doc["assembly"]["polygon_final_metrics"]["component_count"] == 1
    else:
        assert _selected_road_covered_length(finalization_context, step6_result, "527108106") > 16.0


def test_real_case_765003_inherits_step3_two_node_bridge_and_keeps_center_connected() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["765003"],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1
    assert step6_result.audit_doc["assembly"]["target_connected_boundary_fallback_applied"] is False
    assert step6_result.audit_doc["assembly"]["step3_two_node_t_bridge_inherited"] is True
    assert step6_result.audit_doc["assembly"]["polygon_seed_metrics"]["component_count"] == 1
    assert step6_result.audit_doc["assembly"]["polygon_final_metrics"]["component_count"] == 1
    assert branches["998358"]["window_mode"] == "single_sided_semantic_plus_5m"
    assert branches["998358"]["cut_length_m"] == pytest.approx(26.287387)
    assert branches["505243773"]["window_mode"] == "single_sided_semantic_plus_5m"
    assert branches["505243773"]["cut_length_m"] == pytest.approx(28.128754)
    assert branches["600243756"]["cut_length_m"] == 20.0
    assert branches["518741482"]["cut_length_m"] == 20.0


def test_real_case_520394575_remains_rejected_after_u_turn_filter_and_boundary_first() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_association_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["520394575"],
        exclude_case_ids=[],
    )
    association_context = load_association_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    association_case_result = build_association_case_result(association_context)
    finalization_context = FinalizationContext(
        association_context=association_context,
        association_case_result=association_case_result,
    )
    step6_result = build_step6_result(finalization_context)
    step7_result = build_step7_result(finalization_context, step6_result)

    assert step6_result.geometry_established is False
    assert step6_result.reason == "step6_single_sided_shape_artifact"
    assert step7_result.step7_state == "rejected"
    assert step7_result.visual_review_class == VISUAL_V5
