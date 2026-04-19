from __future__ import annotations

from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_loader import (
    load_step45_case_specs,
    load_step45_context,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step4_association import (
    build_step45_case_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step7_acceptance import (
    VISUAL_V1,
    VISUAL_V4,
    build_step7_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step6_geometry import (
    build_step6_result,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import Step67Context


REAL_ANCHOR_ROOT = Path("/mnt/e/TestData/POC_Data/T02/Anchor")
REAL_STEP3_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t03_step3_phase_a/20260418_t03_step3_rulee_rcsd_fallback_v003")


def _selected_road_covered_length(step67_context: Step67Context, step6_result: object, road_id: str) -> float:
    road = next(
        road
        for road in step67_context.step45_context.step1_context.roads
        if road.road_id == road_id
    )
    polygon = step6_result.output_geometries.polygon_final_geometry
    if polygon is None:
        return 0.0
    return road.geometry.intersection(polygon).length


def _selected_road_seed_length(step67_context: Step67Context, step6_result: object, road_id: str) -> float:
    road = next(
        road
        for road in step67_context.step45_context.step1_context.roads
        if road.road_id == road_id
    )
    polygon = step6_result.output_geometries.polygon_seed_geometry
    if polygon is None:
        return 0.0
    return road.geometry.intersection(polygon).length


@pytest.mark.parametrize("case_id", ["706389", "707476", "709431"])
def test_real_cases_706389_707476_and_709431_remain_accepted_after_boundary_first_and_u_turn_filter(case_id: str) -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)

    assert step6_result.geometry_established is True
    assert step6_result.extra_status_fields["foreign_overlap_area_m2"] == 0.0
    assert step6_result.extra_status_fields["within_direction_boundary_ok"] is True
    assert step6_result.audit_doc["assembly"]["foreign_mask_mode"] == "road_like_1m_mask"
    assert step6_result.audit_doc["assembly"]["foreign_mask_sources"] == ["excluded_rcsdroad_geometry"]
    assert (
        step6_result.audit_doc["validation"]["required_rc_cover_mode"]
        == "local_required_rc_within_direction_boundary"
    )
    assert step7_result.step7_state == "accepted"
    assert step7_result.visual_review_class == VISUAL_V1


def test_real_case_706389_uses_trace_based_single_sided_horizontal_mouth_cut() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["706389"],
        exclude_case_ids=[],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)

    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }

    assert step7_result.step7_state == "accepted"
    assert step45_case_result.extra_status_fields["u_turn_rcsdroad_ids"] == [
        "5395781419598881",
        "5395781419598961",
        "5395781419599024",
    ]
    assert branches["629431331"]["window_mode"] == "single_sided_semantic_plus_5m"
    assert branches["629431331"]["special_rule_applied"] is True
    assert branches["629431331"]["cut_length_m"] == pytest.approx(22.863822)
    assert branches["629431331"]["trace_status"] == "trace_selected_semantic_plus_5m"
    assert branches["629431331"]["trace_traced_rcsdnode_ids"] == ["5395732498090139"]
    assert branches["58163436"]["window_mode"] == "single_sided_semantic_plus_5m"
    assert branches["58163436"]["special_rule_applied"] is True
    assert branches["58163436"]["cut_length_m"] == pytest.approx(45.417283)
    assert branches["58163436"]["trace_status"] == "trace_selected_semantic_plus_5m"
    assert branches["58163436"]["trace_traced_rcsdnode_ids"] == ["5395732498090127"]
    assert branches["617732646"]["window_mode"] == "cut_at_20m"
    assert branches["617732646"]["cut_length_m"] == 20.0
    assert _selected_road_covered_length(step67_context, step6_result, "58163436") == pytest.approx(
        branches["58163436"]["cut_length_m"],
    )
    assert _selected_road_covered_length(step67_context, step6_result, "617732646") == pytest.approx(20.0)
    assert _selected_road_covered_length(step67_context, step6_result, "629431331") == pytest.approx(
        branches["629431331"]["cut_length_m"],
    )


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

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)

    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }

    for road_id in expected_road_ids:
        assert branches[road_id]["window_mode"] == "cut_at_20m"
        assert branches[road_id]["cut_length_m"] == 20.0
        assert _selected_road_covered_length(step67_context, step6_result, road_id) == pytest.approx(
            _selected_road_seed_length(step67_context, step6_result, road_id),
            abs=1e-6,
        )
    if case_id == "709431":
        assert branches["507428675"]["trace_status"] == "trace_pair_incomplete"
        assert branches["517729921"]["trace_status"] == "trace_pair_incomplete"


def test_real_case_724123_keeps_all_selected_arms_at_generic_20m_without_rcsd_semantic_mouth() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["724123"],
        exclude_case_ids=[],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)

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
        assert _selected_road_covered_length(step67_context, step6_result, road_id) == pytest.approx(20.0)


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

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)

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
        assert branches["30180138"]["window_mode"] == "single_sided_semantic_plus_5m"
        assert branches["30180138"]["trace_status"] == "trace_selected_semantic_plus_5m"
        assert branches["30180138"]["cut_length_m"] == pytest.approx(38.003971)
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
        assert _selected_road_covered_length(step67_context, step6_result, road_id) == pytest.approx(
            _selected_road_seed_length(step67_context, step6_result, road_id),
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

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=[case_id],
        exclude_case_ids=[],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)

    branches = {
        row["road_id"]: row
        for row in step6_result.audit_doc["assembly"]["directional_cut_branches"]
    }

    assert step6_result.geometry_established is True
    assert step7_result.step7_state == "accepted"
    assert step6_result.audit_doc["assembly"]["target_connected_boundary_fallback_applied"] is False
    for road_id, expected_length in expected_lengths.items():
        assert branches[road_id]["cut_length_m"] == pytest.approx(expected_length)
        assert _selected_road_covered_length(step67_context, step6_result, road_id) == pytest.approx(
            _selected_road_seed_length(step67_context, step6_result, road_id),
            abs=1e-2,
        )
    if case_id == "761318":
        assert _selected_road_covered_length(step67_context, step6_result, "518898861") > 16.0
        assert step6_result.audit_doc["assembly"]["step3_two_node_t_bridge_inherited"] is True
        assert step6_result.audit_doc["assembly"]["polygon_final_metrics"]["component_count"] == 1
    else:
        assert _selected_road_covered_length(step67_context, step6_result, "527108106") > 16.0


def test_real_case_765003_inherits_step3_two_node_bridge_and_keeps_center_connected() -> None:
    if not REAL_ANCHOR_ROOT.is_dir():
        pytest.skip(f"missing real Anchor case root: {REAL_ANCHOR_ROOT}")
    if not REAL_STEP3_ROOT.is_dir():
        pytest.skip(f"missing real Step3 root: {REAL_STEP3_ROOT}")

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["765003"],
        exclude_case_ids=[],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)

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

    specs, _ = load_step45_case_specs(
        case_root=REAL_ANCHOR_ROOT,
        case_ids=["520394575"],
        exclude_case_ids=[],
    )
    step45_context = load_step45_context(case_spec=specs[0], step3_root=REAL_STEP3_ROOT)
    step45_case_result = build_step45_case_result(step45_context)
    step67_context = Step67Context(
        step45_context=step45_context,
        step45_case_result=step45_case_result,
    )
    step6_result = build_step6_result(step67_context)
    step7_result = build_step7_result(step67_context, step6_result)

    assert step6_result.geometry_established is False
    assert step6_result.reason == "step6_foreign_intrusion_remains"
    assert step7_result.step7_state == "rejected"
    assert step7_result.visual_review_class == VISUAL_V4
