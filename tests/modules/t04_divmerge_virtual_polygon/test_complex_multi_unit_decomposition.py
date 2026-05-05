from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch
from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import REAL_ANCHOR_2_ROOT


def test_real_case_505078921_splits_complex_three_merge_and_keeps_internal_cuts_out(
    tmp_path: Path,
) -> None:
    if not (REAL_ANCHOR_2_ROOT / "505078921").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '505078921'}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["505078921"],
        out_root=tmp_path / "anchor2_505078921_complex_multi_unit",
        run_id="anchor2_505078921_complex_multi_unit",
    )

    step4_doc = json.loads(
        (run_root / "cases" / "505078921" / "step4_event_interpretation.json").read_text(
            encoding="utf-8"
        )
    )
    units = {unit["event_unit_id"]: unit for unit in step4_doc["event_units"]}
    assert set(units) == {
        "node_505078921",
        "node_510222629",
        "node_510222629__pair_02",
    }
    assert units["node_510222629"]["unit_envelope"]["boundary_branch_ids"] == ["road_1", "road_2"]
    assert units["node_510222629__pair_02"]["unit_envelope"]["boundary_branch_ids"] == [
        "road_2",
        "road_3",
    ]
    assert units["node_505078921"]["selected_evidence_state"] != "none"
    assert units["node_505078921"]["required_rcsd_node"] == "5385438602535104"
    assert units["node_505078921"]["local_rcsd_unit_id"] == "node_505078921:node:5385438602535104"
    assert set(units["node_505078921"]["selected_rcsdroad_ids"]) == {
        "5385458768741628",
        "5385458768741632",
        "5385458768741665",
    }
    rcsd_junction = units["node_505078921"]["rcsd_semantic_junction"]
    semantic_arm_roads = {
        road_id
        for arm in rcsd_junction["semantic_arms"]
        for road_id in (
            list(arm["first_rcsdroad_ids"])
            + list(arm["inter_junction_connector_rcsdroad_ids"])
        )
    }
    assert {"5385458768741661", "5385458768741681"} <= semantic_arm_roads
    assert units["node_510222629"]["selected_evidence_state"] == "found"
    assert set(units["node_510222629"]["selected_rcsdroad_ids"]) == {
        "5385438602535159",
        "5385438602535182",
        "5385438602535183",
        "5385458768741628",
        "5385458768741632",
        "5385458768741641",
        "5385458768741659",
        "5385458768741665",
        "5385458768741668",
        "5385458768741671",
        "5385458768741679",
    }
    assert (
        units["node_510222629"]["positive_rcsd_audit"]["published_rcsd_selection_mode"]
        == "aggregated_partial_relaxed_component"
    )
    assert units["node_510222629__pair_02"]["selected_evidence_state"] == "found"
    assert units["node_510222629__pair_02"]["evidence_source"] == "swsd_junction_window"
    assert units["node_510222629__pair_02"]["selected_evidence"]["candidate_scope"] == "road_surface_fork"
    assert units["node_510222629__pair_02"]["has_main_evidence"] is False
    assert units["node_510222629__pair_02"]["main_evidence_type"] == "none"
    assert units["node_510222629__pair_02"]["reference_point_present"] is False
    assert (
        units["node_510222629__pair_02"]["surface_scenario_type"]
        == "no_main_evidence_with_rcsdroad_fallback_and_swsd"
    )
    assert units["node_510222629__pair_02"]["positive_rcsd_present"] is False
    assert units["node_510222629__pair_02"]["positive_rcsd_consistency_level"] == "C"
    assert units["node_510222629__pair_02"]["selected_rcsdroad_ids"] == []
    assert units["node_510222629__pair_02"]["selected_rcsdnode_ids"] == []
    assert units["node_510222629__pair_02"]["fallback_rcsdroad_ids"] == ["5390015124868049"]
    assert (
        units["node_510222629__pair_02"]["selected_evidence"]["road_surface_fork_binding"]["action"]
        == "demoted_duplicate_point_road_surface_fork_to_swsd_rcsdroad"
    )
    assert (
        units["node_510222629__pair_02"]["selected_evidence"]["duplicate_point_owner_unit_id"]
        == "node_510222629"
    )

    step5_doc = json.loads(
        (run_root / "cases" / "505078921" / "step5_status.json").read_text(encoding="utf-8")
    )
    assert step5_doc["unit_count"] == 3
    assert step5_doc["case_terminal_cut_constraints"]["present"] is True
    assert step5_doc["case_terminal_cut_constraints"]["length_m"] < 70.0
    step5_audit_doc = json.loads(
        (run_root / "cases" / "505078921" / "step5_audit.json").read_text(encoding="utf-8")
    )
    gap_closing_rcsd_roads = {
        "5385438602535159",
        "5385438602535182",
        "5385458768741641",
        "5385458768741679",
    }
    opposite_rcsd_roads = {
        "5390050624274443",
        "5390050624274524",
        "5390050624274582",
        "5390050624274602",
    }
    related_rcsd_roads = set(step5_audit_doc["related_rcsd_road_ids"])
    protected_rcsd_roads = set(step5_audit_doc["rcsd_negative_mask_protected_road_ids"])
    unrelated_rcsd_roads = set(step5_audit_doc["unrelated_rcsd_road_ids"])
    assert gap_closing_rcsd_roads <= related_rcsd_roads
    assert gap_closing_rcsd_roads <= protected_rcsd_roads
    assert gap_closing_rcsd_roads.isdisjoint(unrelated_rcsd_roads)
    assert opposite_rcsd_roads <= unrelated_rcsd_roads
    assert opposite_rcsd_roads.isdisjoint(related_rcsd_roads)

    step6_doc = json.loads(
        (run_root / "cases" / "505078921" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_doc["hole_count"] == 0
    assert step6_doc["cut_violation"] is False
    assert step6_doc["component_count"] == 1
    assert step6_doc["final_case_polygon"]["area_m2"] > 2500.0

    step7_doc = json.loads(
        (run_root / "cases" / "505078921" / "step7_status.json").read_text(encoding="utf-8")
    )
    assert step7_doc["final_state"] == "accepted"

    render_audit_doc = json.loads(
        (run_root / "cases" / "505078921" / "final_review_render_audit.json").read_text(
            encoding="utf-8"
        )
    )
    visible_rcsd_roads = set(render_audit_doc["render_visible_rcsd_road_ids"])
    assert render_audit_doc["missing_rcsd_road_ids"] == []
    assert {
        "5385438602535183",
        "5385458768741641",
        "5385458768741661",
        "5385458768741668",
        "5385458768741679",
        "5385458768741681",
        "5390015124868049",
    } <= visible_rcsd_roads
    assert opposite_rcsd_roads.isdisjoint(visible_rcsd_roads)
    assert render_audit_doc["rcsd_entity_road_count"] == 14
    assert render_audit_doc["render_visible_rcsd_road_count"] == 14
