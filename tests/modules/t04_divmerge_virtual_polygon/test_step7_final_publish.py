from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403


@pytest.mark.smoke
def test_t04_step7_batch_publishes_accepted_and_rejected_layers(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    _build_synthetic_case_package(case_root / "1001")
    _build_multi_event_case_package(case_root / "2002")

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step7",
        run_id="synthetic_t04_step7_publish",
    )

    accepted_layer = run_root / "divmerge_virtual_anchor_surface.gpkg"
    rejected_layer = run_root / "divmerge_virtual_anchor_surface_rejected.geojson"
    summary_csv = run_root / "divmerge_virtual_anchor_surface_summary.csv"
    summary_json = run_root / "divmerge_virtual_anchor_surface_summary.json"
    audit_layer = run_root / "divmerge_virtual_anchor_surface_audit.gpkg"
    rejected_index_csv = run_root / "step7_rejected_index.csv"
    rejected_index_json = run_root / "step7_rejected_index.json"
    consistency_report = run_root / "step7_consistency_report.json"
    final_review_1001 = run_root / "cases" / "1001" / "final_review.png"
    final_review_2002 = run_root / "cases" / "2002" / "final_review.png"
    flat_review_1001 = run_root / "step4_review_flat" / "case__1001__final_review.png"
    flat_review_2002 = run_root / "step4_review_flat" / "case__2002__final_review.png"

    assert accepted_layer.is_file()
    assert rejected_layer.is_file()
    assert summary_csv.is_file()
    assert summary_json.is_file()
    assert audit_layer.is_file()
    assert rejected_index_csv.is_file()
    assert rejected_index_json.is_file()
    assert consistency_report.is_file()
    assert final_review_1001.is_file()
    assert final_review_2002.is_file()
    assert flat_review_1001.is_file()
    assert flat_review_2002.is_file()

    status_1001 = json.loads((run_root / "cases" / "1001" / "step7_status.json").read_text(encoding="utf-8"))
    status_2002 = json.loads((run_root / "cases" / "2002" / "step7_status.json").read_text(encoding="utf-8"))
    assert status_1001["final_state"] == "accepted"
    assert status_1001["published_layer_target"] == "accepted_layer"
    assert status_2002["final_state"] == "rejected"
    assert status_2002["published_layer_target"] == "rejected_index"

    summary_payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary_payload["accepted_count"] == 1
    assert summary_payload["rejected_count"] == 1
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}
    assert rows_by_case["1001"]["publish_target"] == "accepted_layer"
    assert rows_by_case["2002"]["publish_target"] == "rejected_index"
    assert rows_by_case["1001"]["review_png_path"] == str(flat_review_1001)
    assert rows_by_case["2002"]["review_png_path"] == str(flat_review_2002)

    rejected_index_payload = json.loads(rejected_index_json.read_text(encoding="utf-8"))
    assert rejected_index_payload["row_count"] == 1
    assert rejected_index_payload["rows"][0]["case_id"] == "2002"
    assert rejected_index_payload["rows"][0]["review_png_path"] == str(flat_review_2002)

    consistency_payload = json.loads(consistency_report.read_text(encoding="utf-8"))
    assert consistency_payload["passed"] is True
    assert consistency_payload["accepted_count"] == 1
    assert consistency_payload["rejected_count"] == 1
    assert consistency_payload["rejected_index_row_count"] == 1
    assert consistency_payload["review_png_present_count"] == 2

    fiona = pytest.importorskip("fiona")
    with fiona.open(accepted_layer) as src:
        accepted_rows = list(src)
    assert len(accepted_rows) == 1
    assert accepted_rows[0]["properties"]["case_id"] == "1001"
    assert accepted_rows[0]["properties"]["final_state"] == "accepted"

    with fiona.open(audit_layer) as src:
        audit_rows = list(src)
    assert {row["properties"]["case_id"] for row in audit_rows} == {"1001", "2002"}

    rejected_payload = json.loads(rejected_layer.read_text(encoding="utf-8"))
    rejected_rows = rejected_payload["features"]
    assert len(rejected_rows) == 1
    assert rejected_rows[0]["properties"]["case_id"] == "2002"
    assert rejected_rows[0]["properties"]["final_state"] == "rejected"


@pytest.mark.smoke
def test_t04_step7_rejected_case_writes_reject_stub_without_final_review_state(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    _build_multi_event_case_package(case_root / "2002")

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_step7_rejected",
        run_id="synthetic_t04_step7_rejected",
    )

    case_dir = run_root / "cases" / "2002"
    step7_status = json.loads((case_dir / "step7_status.json").read_text(encoding="utf-8"))
    step7_audit = json.loads((case_dir / "step7_audit.json").read_text(encoding="utf-8"))
    reject_index = json.loads((case_dir / "reject_index.json").read_text(encoding="utf-8"))

    assert step7_status["final_state"] == "rejected"
    assert "review" not in step7_status["final_state"]
    assert step7_status["published_layer_target"] == "rejected_index"
    assert "multi_component_result" in set(step7_status["reject_reasons"])
    assert step7_audit["publish_target"] == "rejected_index"
    assert step7_audit["final_publish_outputs"]["case_final_review_png_path"] == str(case_dir / "final_review.png")
    assert reject_index["final_state"] == "rejected"
    assert (case_dir / "reject_stub.geojson").is_file()
    assert (case_dir / "final_review.png").is_file()


@pytest.mark.smoke
def test_anchor2_step7_freezes_857993_as_expected_rejected(tmp_path: Path) -> None:
    if not REAL_ANCHOR_2_ROOT.is_dir():
        pytest.skip(f"missing real Anchor_2 case root: {REAL_ANCHOR_2_ROOT}")

    anchor2_case_ids = [
        "760213",
        "785671",
        "785675",
        "857993",
        "987998",
        "17943587",
        "30434673",
        "73462878",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_step7",
        run_id="anchor2_expected_857993_rejected",
    )

    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}

    assert summary_payload["accepted_count"] == 7
    assert summary_payload["rejected_count"] == 1
    assert rows_by_case["857993"]["final_state"] == "rejected"
    assert rows_by_case["857993"]["publish_target"] == "rejected_index"
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}

    rejected_status = json.loads(
        (run_root / "cases" / "857993" / "step7_status.json").read_text(encoding="utf-8")
    )
    assert rejected_status["final_state"] == "rejected"
    assert "review" not in rejected_status["final_state"]
    assert (run_root / "cases" / "857993" / "reject_stub.geojson").is_file()

    step5_760213 = json.loads(
        (run_root / "cases" / "760213" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_760213 = step5_760213["unit_results"][0]
    assert unit_760213["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_760213["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    assert unit_760213["single_component_surface_seed"] is False
    step6_760213 = json.loads(
        (run_root / "cases" / "760213" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_760213["component_count"] == 1
    assert step6_760213["review_reasons"] == []


@pytest.mark.smoke
def test_anchor2_added_cases_recover_698389_road_surface_without_wrong_rcsd(tmp_path: Path) -> None:
    anchor2_case_ids = [
        "698380",
        "698389",
        "699870",
        "857993",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_added_cases_step7",
        run_id="anchor2_added_cases_698380_698389",
    )

    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}

    assert summary_payload["accepted_count"] == 3
    assert summary_payload["rejected_count"] == 1
    assert rows_by_case["698380"]["final_state"] == "accepted"
    assert rows_by_case["698389"]["final_state"] == "accepted"
    assert rows_by_case["699870"]["final_state"] == "accepted"
    assert rows_by_case["857993"]["final_state"] == "rejected"
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}

    surface_binding_payload = json.loads(
        (run_root / "step4_road_surface_fork_binding.json").read_text(encoding="utf-8")
    )
    surface_binding_by_case = {record["case_id"]: record for record in surface_binding_payload["records"]}
    assert surface_binding_by_case["698389"]["action"] == "recovered_road_surface_fork_with_relaxed_primary_rcsd"
    assert surface_binding_by_case["698389"]["post_state"] == "found"
    assert surface_binding_by_case["698389"]["required_rcsd_node"] == "5396318492905216"
    assert surface_binding_by_case["698389"]["positive_rcsd_consistency_level"] == "B"
    assert surface_binding_by_case["698389"]["detail"]["relaxed_rcsd_dropped"] is False
    assert surface_binding_by_case["698389"]["detail"]["relaxed_primary_rcsd_promoted"] is True
    assert surface_binding_by_case["698389"]["detail"]["representative_distance_m"] == pytest.approx(6.58, abs=1e-3)

    reverse_payload = json.loads((run_root / "step4_rcsd_anchored_reverse.json").read_text(encoding="utf-8"))
    reverse_by_case = {record["case_id"]: record for record in reverse_payload["records"]}
    assert reverse_by_case["698389"]["skip_reason"] == "skipped_selected_evidence_present"
    assert reverse_by_case["698389"]["post_state"] == "found"
    reverse_699870 = [
        record for record in reverse_payload["records"] if record["case_id"] == "699870"
    ][0]
    assert reverse_699870["post_reverse_conflict_recheck"] == "passed"
    assert reverse_699870["post_state"] == "found"
    assert reverse_699870["reference_point_mode"] == "selected_divstrip_branch_tip"
    assert reverse_699870["reference_point_axis_s"] == pytest.approx(33.72, abs=1e-3)

    step5_699870 = json.loads(
        (run_root / "cases" / "699870" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_699870 = step5_699870["unit_results"][0]
    assert unit_699870["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_699870["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    assert unit_699870["junction_full_road_fill_domain"]["present"] is True
    assert (
        unit_699870["junction_full_road_fill_domain"]["area_m2"]
        > unit_699870["terminal_support_corridor_geometry"]["area_m2"] * 2.0
    )

    step4_698389 = json.loads(
        (run_root / "cases" / "698389" / "step4_event_interpretation.json").read_text(encoding="utf-8")
    )
    unit_698389 = step4_698389["event_units"][0]
    assert unit_698389["selected_evidence_state"] == "found"
    assert unit_698389["evidence_source"] == "road_surface_fork"
    assert unit_698389["position_source"] == "road_surface_fork"
    assert unit_698389["selected_evidence"]["candidate_id"] == (
        "event_unit_01:structure:road_surface_fork:recovered"
    )
    assert unit_698389["selected_evidence"]["candidate_scope"] == "road_surface_fork"
    assert unit_698389["selected_evidence"]["node_fallback_only"] is False
    assert unit_698389["positive_rcsd_present"] is True
    assert unit_698389["positive_rcsd_consistency_level"] == "B"
    assert unit_698389["required_rcsd_node"] == "5396318492905216"
    assert unit_698389["required_rcsd_node_source"] == "road_surface_fork_relaxed_primary_rcsd"
    assert unit_698389["rcsd_selection_mode"] == "road_surface_fork_relaxed_primary_rcsd_binding"
    assert "road_surface_fork_binding_used" in set(unit_698389["review_reasons"])

    fiona = pytest.importorskip("fiona")
    from shapely.geometry import shape

    with fiona.open(run_root / "cases" / "698389" / "step4_event_evidence.gpkg") as src:
        evidence_features = list(src)
    fact_reference = next(
        shape(feature["geometry"])
        for feature in evidence_features
        if feature["properties"]["geometry_role"] == "fact_reference_point"
    )
    selected_surface = next(
        shape(feature["geometry"])
        for feature in evidence_features
        if feature["properties"]["geometry_role"] == "selected_evidence_region_geometry"
    )
    assert fact_reference.x == pytest.approx(12724323.350, abs=1e-3)
    assert fact_reference.y == pytest.approx(2605444.015, abs=1e-3)
    assert selected_surface.area == pytest.approx(1781.058, abs=1e-3)

    step5_698389 = json.loads(
        (run_root / "cases" / "698389" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_698389_step5 = step5_698389["unit_results"][0]
    assert unit_698389_step5["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_698389_step5["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    assert unit_698389_step5["single_component_surface_seed"] is False
    assert unit_698389_step5["must_cover_components"]["required_rcsd_node_patch_geometry"] is True
    assert unit_698389_step5["must_cover_components"]["junction_full_road_fill_domain"] is True
    step6_698389 = json.loads(
        (run_root / "cases" / "698389" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_698389["component_count"] == 1
    assert step6_698389["review_reasons"] == []

    candidates_698389 = json.loads(
        (
            run_root
            / "cases"
            / "698389"
            / "event_units"
            / "event_unit_01"
            / "step4_candidates.json"
        ).read_text(encoding="utf-8")
    )
    wrong_divstrip = next(
        entry
        for entry in candidates_698389["candidate_audit_entries"]
        if entry["candidate_id"] == "event_unit_01:divstrip:0:01"
    )
    wrong_summary = wrong_divstrip["candidate_summary"]
    assert wrong_summary["primary_eligible"] is False
    assert wrong_summary["degraded_reverse_divstrip_far_from_throat"] is True
    assert wrong_summary["positive_rcsd_consistency_level"] == "B"
    assert wrong_summary["rcsd_decision_reason"] == "role_mapping_partial_relaxed_aggregated"


@pytest.mark.smoke
def test_anchor2_724067_road_surface_fork_primary_evidence_keeps_known_rejects(tmp_path: Path) -> None:
    anchor2_case_ids = [
        "699870",
        "724067",
        "760598",
        "760936",
        "760984",
        "788824",
        "857993",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_724067_road_surface_fork",
        run_id="anchor2_724067_road_surface_fork",
    )

    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}
    assert summary_payload["accepted_count"] == 4
    assert summary_payload["rejected_count"] == 3
    assert rows_by_case["699870"]["final_state"] == "accepted"
    assert rows_by_case["724067"]["final_state"] == "accepted"
    assert rows_by_case["760598"]["final_state"] == "rejected"
    assert rows_by_case["760936"]["final_state"] == "rejected"
    assert rows_by_case["760984"]["final_state"] == "accepted"
    assert rows_by_case["788824"]["final_state"] == "accepted"
    assert rows_by_case["857993"]["final_state"] == "rejected"
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}

    reverse_payload = json.loads((run_root / "step4_rcsd_anchored_reverse.json").read_text(encoding="utf-8"))
    reverse_by_case = {record["case_id"]: record for record in reverse_payload["records"]}
    assert reverse_by_case["699870"]["post_reverse_conflict_recheck"] == "passed"
    assert reverse_by_case["699870"]["post_state"] == "found"
    assert reverse_by_case["699870"]["reference_point_mode"] == "selected_divstrip_branch_tip"
    assert reverse_by_case["699870"]["reference_point_axis_s"] == pytest.approx(33.72, abs=1e-3)
    step5_699870 = json.loads(
        (run_root / "cases" / "699870" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_699870 = step5_699870["unit_results"][0]
    assert unit_699870["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_699870["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    surface_binding_payload = json.loads(
        (run_root / "step4_road_surface_fork_binding.json").read_text(encoding="utf-8")
    )
    surface_binding_by_case = {record["case_id"]: record for record in surface_binding_payload["records"]}
    assert surface_binding_by_case["724067"]["action"] == "bound_forward_rcsd_to_road_surface_fork"
    assert surface_binding_by_case["724067"]["required_rcsd_node"] == "5395137610783733"
    assert surface_binding_by_case["760598"]["action"] == "cleared_unbound_road_surface_fork"
    assert surface_binding_by_case["760598"]["post_state"] == "none"
    assert surface_binding_by_case["760598"]["required_rcsd_node"] is None
    assert surface_binding_by_case["760984"]["skip_reason"] == "skipped_no_surface_binding_candidate"
    assert surface_binding_by_case["788824"]["skip_reason"] == "skipped_no_surface_binding_candidate"
    assert reverse_by_case["724067"]["skip_reason"] == "skipped_selected_evidence_present"
    assert reverse_by_case["724067"]["post_state"] == "found"
    assert reverse_by_case["724067"]["mother_candidate_id"] is None

    case_dir = run_root / "cases" / "724067"
    step4_status = json.loads((case_dir / "step4_event_interpretation.json").read_text(encoding="utf-8"))
    step4_unit = step4_status["event_units"][0]
    selected_evidence = step4_unit["selected_evidence"]
    assert step4_unit["evidence_source"] == "road_surface_fork"
    assert step4_unit["position_source"] == "road_surface_fork"
    assert step4_unit["event_chosen_s_m"] == 0.0
    assert step4_unit["required_rcsd_node"] == "5395137610783733"
    assert step4_unit["positive_rcsd_present"] is True
    assert step4_unit["positive_rcsd_consistency_level"] == "A"
    assert step4_unit["rcsd_selection_mode"] == "road_surface_fork_forward_rcsd_binding"
    assert selected_evidence["candidate_id"] == "event_unit_01:structure:road_surface_fork:01"
    assert selected_evidence["candidate_scope"] == "road_surface_fork"
    assert selected_evidence["primary_eligible"] is True
    assert selected_evidence["node_fallback_only"] is False
    road_surface_fork_area = float(step4_unit["pair_local_summary"]["pair_local_region_area_m2"])

    step5_status = json.loads((case_dir / "step5_status.json").read_text(encoding="utf-8"))
    unit_status = step5_status["unit_results"][0]
    assert unit_status["surface_fill_mode"] == "junction_full_road_fill"
    assert unit_status["surface_fill_axis_half_width_m"] == pytest.approx(20.0, abs=1e-6)
    assert unit_status["single_component_surface_seed"] is False
    assert step5_status["case_must_cover_domain"]["present"] is True
    assert unit_status["must_cover_components"]["localized_evidence_core_geometry"] is True
    assert unit_status["must_cover_components"]["required_rcsd_node_patch_geometry"] is True
    assert unit_status["must_cover_components"]["junction_full_road_fill_domain"] is True
    assert unit_status["must_cover_components"]["fallback_support_strip_geometry"] is False
    assert unit_status["junction_full_road_fill_domain"]["area_m2"] >= road_surface_fork_area * 0.95
    assert (
        unit_status["junction_full_road_fill_domain"]["area_m2"]
        > unit_status["terminal_support_corridor_geometry"]["area_m2"] * 2.5
    )

    step6_status = json.loads((case_dir / "step6_status.json").read_text(encoding="utf-8"))
    assert step6_status["assembly_state"] == "assembled"
    assert step6_status["component_count"] == 1
    assert step6_status["hard_must_cover_ok"] is True
    assert step6_status["final_case_polygon"]["area_m2"] >= road_surface_fork_area * 0.9
    assert (
        step6_status["final_case_polygon"]["area_m2"]
        > unit_status["terminal_support_corridor_geometry"]["area_m2"] * 2.4
    )

    for accepted_surface_case in ("760984", "788824"):
        step4_surface = json.loads(
            (run_root / "cases" / accepted_surface_case / "step4_event_interpretation.json").read_text(
                encoding="utf-8"
            )
        )
        unit_surface = step4_surface["event_units"][0]
        assert unit_surface["selected_evidence_state"] == "found"
        assert unit_surface["evidence_source"] == "road_surface_fork"
        assert unit_surface["positive_rcsd_consistency_level"] == "C"
        assert "positive_rcsd_partial_consistent" in "|".join(unit_surface["review_reasons"])

    status_760936 = json.loads(
        (run_root / "cases" / "760936" / "step7_status.json").read_text(encoding="utf-8")
    )
    status_760598 = json.loads(
        (run_root / "cases" / "760598" / "step7_status.json").read_text(encoding="utf-8")
    )
    status_857993 = json.loads(
        (run_root / "cases" / "857993" / "step7_status.json").read_text(encoding="utf-8")
    )
    assert status_760598["final_state"] == "rejected"
    assert "assembly_failed" in set(status_760598["reject_reasons"])
    assert status_760936["final_state"] == "rejected"
    assert "multi_component_result" in set(status_760936["reject_reasons"])
    assert status_857993["final_state"] == "rejected"


@pytest.mark.smoke
def test_anchor2_rcsdnode_pair_local_drivezone_filter_keeps_cross_patch_cases_publishable(tmp_path: Path) -> None:
    anchor2_case_ids = [
        "723276",
        "758784",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_cross_patch_rcsdnode_filter",
        run_id="anchor2_cross_patch_rcsdnode_filter",
    )

    batch_summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}

    assert batch_summary["failed_case_ids"] == []
    assert summary_payload["row_count"] == 2
    assert set(rows_by_case) == set(anchor2_case_ids)
    assert {row["final_state"] for row in summary_payload["rows"]} <= {"accepted", "rejected"}


@pytest.mark.smoke
def test_anchor2_new_structure_only_road_surface_forks_keep_760598_rejected(tmp_path: Path) -> None:
    anchor2_case_ids = [
        "706629",
        "724081",
        "824002",
        "760598",
    ]
    missing_cases = [
        case_id for case_id in anchor2_case_ids if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=anchor2_case_ids,
        out_root=tmp_path / "anchor2_new_structure_only_surface_forks",
        run_id="anchor2_new_structure_only_surface_forks",
    )

    summary_payload = json.loads(
        (run_root / "divmerge_virtual_anchor_surface_summary.json").read_text(encoding="utf-8")
    )
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}

    assert rows_by_case["706629"]["final_state"] == "accepted"
    assert rows_by_case["724081"]["final_state"] == "accepted"
    assert rows_by_case["824002"]["final_state"] == "accepted"
    assert rows_by_case["760598"]["final_state"] == "rejected"

    surface_binding_payload = json.loads(
        (run_root / "step4_road_surface_fork_binding.json").read_text(encoding="utf-8")
    )
    surface_binding_by_case = {record["case_id"]: record for record in surface_binding_payload["records"]}
    for case_id in ("706629", "724081"):
        record = surface_binding_by_case[case_id]
        assert record["action"] == "kept_structure_only_road_surface_fork"
        assert record["post_state"] == "found"
        assert record["positive_rcsd_consistency_level"] == "C"

        step4_status = json.loads(
            (run_root / "cases" / case_id / "step4_event_interpretation.json").read_text(
                encoding="utf-8"
            )
        )
        unit = step4_status["event_units"][0]
        assert unit["selected_evidence_state"] == "found"
        assert unit["evidence_source"] == "road_surface_fork"
        assert unit["rcsd_selection_mode"] == "road_surface_fork_structure_only_no_rcsd"
        assert "road_surface_fork_structure_only_used" in set(unit["review_reasons"])

        step6_status = json.loads(
            (run_root / "cases" / case_id / "step6_status.json").read_text(encoding="utf-8")
        )
        assert step6_status["assembly_state"] == "assembled"
        assert step6_status["component_count"] == 1

    assert surface_binding_by_case["760598"]["action"] == "cleared_unbound_road_surface_fork"
