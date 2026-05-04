from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403


ANCHOR2_OFFICIAL_BASELINE_PATH = (
    Path(__file__).with_name("data") / "anchor2_official_39case_baseline_20260504.json"
)
ANCHOR2_OFFICIAL_BASELINE = json.loads(ANCHOR2_OFFICIAL_BASELINE_PATH.read_text(encoding="utf-8"))
ANCHOR2_OFFICIAL_CASES_BY_ID = {
    str(row["case_id"]): row
    for row in ANCHOR2_OFFICIAL_BASELINE["cases"]
}
ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504: dict[str, tuple[str, str, str, str]] = {
    case_id: (
        str(row["final_state"]),
        str(row["surface_scenario_type"]),
        str(row["section_reference_source"]),
        str(row["surface_generation_mode"]),
    )
    for case_id, row in ANCHOR2_OFFICIAL_CASES_BY_ID.items()
}
ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260503 = ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504
ANCHOR2_LEGACY_23_SUBSET_20260426 = tuple(
    str(case_id)
    for case_id in ANCHOR2_OFFICIAL_BASELINE["legacy_subsets"]["legacy_23_20260426"]
)
ANCHOR2_LEGACY_30_SUBSET_20260501 = tuple(
    str(case_id)
    for case_id in ANCHOR2_OFFICIAL_BASELINE["legacy_subsets"]["legacy_30_20260501"]
)
ANCHOR2_FULL_BASELINE_20260426: dict[str, str] = {
    case_id: ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504[case_id][0]
    for case_id in ANCHOR2_LEGACY_23_SUBSET_20260426
}
ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501: dict[str, str] = {
    case_id: ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504[case_id][0]
    for case_id in ANCHOR2_LEGACY_30_SUBSET_20260501
}
ANCHOR2_30CASE_REJECTED_20260501 = {
    case_id
    for case_id, final_state in ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501.items()
    if final_state == "rejected"
}

ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502: dict[str, dict[str, object]] = {
    "785629": {
        "surface_scenario_type": "mixed",
        "section_reference_source": "mixed",
        "surface_generation_mode": "mixed",
        "unit_surface_scenario_type": "main_evidence_without_rcsd",
        "step4_evidence_source": "multibranch_event",
        "step4_main_evidence_type": "divstrip",
    },
    "785631": {
        "surface_scenario_type": "main_evidence_with_rcsd_junction",
        "section_reference_source": "reference_point_and_rcsd_junction",
        "surface_generation_mode": "main_evidence_driven",
        "step4_evidence_source": "divstrip_direct",
        "step4_main_evidence_type": "divstrip",
    },
    "785731": {
        "surface_scenario_type": "no_main_evidence_with_rcsdroad_fallback_and_swsd",
        "section_reference_source": "swsd_junction",
        "surface_generation_mode": "swsd_with_rcsdroad_fallback",
        "step4_evidence_source": "swsd_junction_window",
        "step4_main_evidence_type": "none",
    },
    "795682": {
        "surface_scenario_type": "no_main_evidence_with_swsd_only",
        "section_reference_source": "swsd_junction",
        "surface_generation_mode": "swsd_junction_window",
        "step4_evidence_source": "swsd_junction_window",
        "step4_main_evidence_type": "none",
    },
    "807908": {
        "surface_scenario_type": "main_evidence_with_rcsd_junction",
        "section_reference_source": "reference_point_and_rcsd_junction",
        "surface_generation_mode": "main_evidence_driven",
        "step4_evidence_source": "rcsd_anchored_reverse",
        "step4_main_evidence_type": "divstrip",
    },
    "823826": {
        "surface_scenario_type": "main_evidence_with_rcsd_junction",
        "section_reference_source": "reference_point_and_rcsd_junction",
        "surface_generation_mode": "main_evidence_driven",
        "step4_evidence_source": "multibranch_event",
        "step4_main_evidence_type": "divstrip",
    },
}

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_provenance(doc: dict, *, input_dataset_id_prefix: str) -> None:
    assert doc["produced_at"]
    assert doc["git_sha"]
    assert str(doc["input_dataset_id"]).startswith(input_dataset_id_prefix)


def _assert_gpkg_crs_and_valid_features(path: Path, *, min_feature_count: int = 1) -> None:
    fiona = pytest.importorskip("fiona")
    from shapely.geometry import shape

    assert path.is_file()
    with fiona.open(path) as src:
        assert str(src.crs).upper() == "EPSG:3857"
        assert len(src) >= min_feature_count
        for row in src:
            geometry_payload = row.get("geometry")
            assert geometry_payload is not None
            geometry = shape(geometry_payload)
            assert not geometry.is_empty
            assert geometry.is_valid


def _assert_case_package_performance_summary(doc: dict, *, expected_completed_cases: int) -> None:
    performance = doc["performance"]
    assert performance["performance_audit_version"] == "t04-case-package-performance-v1"
    assert performance["elapsed_seconds_total"] >= 0.0
    assert performance["case_build_elapsed_seconds_total"] >= 0.0
    assert performance["completed_case_count"] == expected_completed_cases
    assert performance["runtime_failed_case_count"] == 0
    assert performance["avg_completed_case_seconds"] is not None
    assert performance["avg_completed_case_seconds"] >= 0.0
    assert 1 <= len(performance["slowest_cases"]) <= 5
    assert performance["threshold_seconds_total"] == pytest.approx(240.0)
    assert performance["threshold_avg_completed_case_seconds"] == pytest.approx(6.5)
    assert performance["threshold_status"] in {"within_threshold", "exceeded_threshold"}
    assert performance["threshold_source"] == "module_quality_requirement_default_or_env_override"


def _assert_no_main_evidence_has_no_virtual_reference_point(step4_doc: dict) -> None:
    for unit in step4_doc["event_units"]:
        if unit.get("has_main_evidence") is False or unit.get("main_evidence_type") == "none":
            assert unit["reference_point_present"] is False
            assert unit.get("reference_point_source") in {None, "", "none"}


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

    step4_698380 = json.loads(
        (run_root / "cases" / "698380" / "step4_event_interpretation.json").read_text(encoding="utf-8")
    )
    unit_698380 = step4_698380["event_units"][0]
    assert unit_698380["surface_scenario_type"] == "main_evidence_with_rcsd_junction"
    assert unit_698380["required_rcsd_node"] == "5396472305684358"
    assert set(unit_698380["selected_rcsdnode_ids"]) == {
        "5396472305684357",
        "5396472305684358",
    }
    assert set(unit_698380["selected_rcsdroad_ids"]) == {
        "5396472305684664",
        "5396472305684674",
        "5396472305684679",
    }
    assert "5396472305684588" not in set(unit_698380["selected_rcsdnode_ids"])
    assert "5396482943156286" not in set(unit_698380["selected_rcsdroad_ids"])
    assert "5396482943156330" not in set(unit_698380["selected_rcsdroad_ids"])
    audit_698380 = unit_698380["positive_rcsd_audit"]
    assert audit_698380["aggregated_rcsd_unit_ids"] == ["event_unit_01:node:5396472305684358"]
    selected_aggregate_698380 = next(
        entry
        for entry in audit_698380["aggregated_rcsd_units"]
        if entry["unit_id"] == audit_698380["aggregated_rcsd_unit_id"]
    )
    assert selected_aggregate_698380["semantic_group_ids"] == ["5396472305684358"]

    surface_binding_payload = json.loads(
        (run_root / "step4_road_surface_fork_binding.json").read_text(encoding="utf-8")
    )
    surface_binding_by_case = {record["case_id"]: record for record in surface_binding_payload["records"]}
    assert surface_binding_by_case["698389"]["action"] == "divstrip_primary_over_wide_road_surface_fork"
    assert surface_binding_by_case["698389"]["post_state"] == "found"
    assert surface_binding_by_case["698389"]["required_rcsd_node"] == "5396318492905216"
    assert surface_binding_by_case["698389"]["positive_rcsd_consistency_level"] == "A"
    suppressed_binding_698389 = surface_binding_by_case["698389"]["detail"]["suppressed_road_surface_fork_binding"]
    assert suppressed_binding_698389["action"] == "bound_forward_rcsd_to_road_surface_fork"
    assert suppressed_binding_698389["required_rcsd_node"] == "5396318492905216"

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
    assert unit_699870["junction_full_road_fill_domain"]["area_m2"] == pytest.approx(
        1491.1413286356383,
        abs=1e-6,
    )
    assert (
        unit_699870["junction_full_road_fill_domain"]["area_m2"]
        > unit_699870["terminal_support_corridor_geometry"]["area_m2"] * 1.9
    )

    step4_698389 = json.loads(
        (run_root / "cases" / "698389" / "step4_event_interpretation.json").read_text(encoding="utf-8")
    )
    unit_698389 = step4_698389["event_units"][0]
    assert unit_698389["selected_evidence_state"] == "found"
    assert unit_698389["evidence_source"] == "reverse_tip_retry"
    assert unit_698389["position_source"] == "divstrip_ref"
    assert unit_698389["main_evidence_type"] == "divstrip"
    assert unit_698389["selected_evidence"]["candidate_id"] == "event_unit_01:divstrip:1:01"
    assert unit_698389["selected_evidence"]["candidate_scope"] == "divstrip_component"
    assert unit_698389["selected_evidence"]["upper_evidence_kind"] == "divstrip"
    assert unit_698389["selected_evidence"]["node_fallback_only"] is False
    assert unit_698389["positive_rcsd_present"] is True
    assert unit_698389["positive_rcsd_consistency_level"] == "A"
    assert unit_698389["required_rcsd_node"] == "5396318492905216"
    assert unit_698389["required_rcsd_node_source"] == "road_surface_fork_forward_rcsd"
    assert unit_698389["rcsd_selection_mode"] == "road_surface_fork_forward_rcsd_binding"
    assert "divstrip_primary_over_wide_road_surface_fork" in set(unit_698389["review_reasons"])
    assert unit_698389["selected_rcsdnode_ids"] == ["5396318492905216"]
    assert "5396318492905249" not in set(unit_698389["selected_rcsdnode_ids"])
    audit_698389 = unit_698389["positive_rcsd_audit"]
    assert audit_698389["published_rcsdnode_ids"] == ["5396318492905216"]
    assert audit_698389["published_member_unit_ids"] == ["event_unit_01:node:5396318492905216"]
    rcsd_junction_698389 = audit_698389["rcsd_semantic_junction"]
    assert rcsd_junction_698389["member_rcsdnode_ids"] == ["5396318492905216"]
    assert rcsd_junction_698389["intra_junction_rcsdroad_ids"] == []
    arms_698389 = {
        tuple(arm["first_rcsdroad_ids"]): arm
        for arm in rcsd_junction_698389["semantic_arms"]
    }
    connector_arm_698389 = arms_698389[("5396319095619771",)]
    assert connector_arm_698389["terminal_rcsdnode_id"] == "5396318492905249"
    assert connector_arm_698389["terminal_kind"] == "semantic_neighbor"

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
    assert fact_reference.x == pytest.approx(12724336.311, abs=1e-3)
    assert fact_reference.y == pytest.approx(2605452.472, abs=1e-3)
    assert selected_surface.area == pytest.approx(899.887, abs=1e-3)

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

    assert unit_698389["selected_evidence"]["primary_eligible"] is True


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
    reference_detail_724067 = surface_binding_by_case["724067"]["detail"]["reference_point"]
    assert reference_detail_724067["road_surface_fork_reference_point_mode"] == "road_surface_fork_boundary_apex"
    assert reference_detail_724067["boundary_pair_road_ids"] == ["611600880", "18386573"]
    assert reference_detail_724067["road_surface_fork_reference_distance_m"] == pytest.approx(87.922, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_reference_sample_s_m"] == pytest.approx(87.028, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_branch_separation_m"] == pytest.approx(13.717, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_apex_midline_distance_m"] == pytest.approx(1.397, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_apex_transverse_alignment"] == pytest.approx(0.954, abs=1e-3)
    assert reference_detail_724067["road_surface_fork_apex_segment_index"] == 61
    assert surface_binding_by_case["760598"]["action"] == "cleared_unbound_road_surface_fork"
    assert surface_binding_by_case["760598"]["post_state"] == "none"
    assert surface_binding_by_case["760598"]["required_rcsd_node"] is None
    assert surface_binding_by_case["760984"]["action"] == "bound_selected_surface_to_rcsd_junction_window"
    assert surface_binding_by_case["760984"]["required_rcsd_node"] == "5384392508834203"
    assert surface_binding_by_case["788824"]["action"] == "bound_selected_surface_to_rcsd_junction_window"
    assert surface_binding_by_case["788824"]["required_rcsd_node"] == "5395664851308727"
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
    assert unit_status["junction_full_road_fill_domain"]["area_m2"] < road_surface_fork_area * 0.7
    assert unit_status["junction_full_road_fill_domain"]["area_m2"] == pytest.approx(1695.840, abs=1e-3)
    assert (
        unit_status["junction_full_road_fill_domain"]["area_m2"]
        > unit_status["terminal_support_corridor_geometry"]["area_m2"] * 1.1
    )

    step6_status = json.loads((case_dir / "step6_status.json").read_text(encoding="utf-8"))
    assert step6_status["assembly_state"] == "assembled"
    assert step6_status["component_count"] == 1
    assert step6_status["hard_must_cover_ok"] is True
    assert (
        step6_status["final_case_polygon"]["area_m2"]
        >= unit_status["junction_full_road_fill_domain"]["area_m2"] * 0.9
    )
    assert step6_status["final_case_polygon"]["area_m2"] < road_surface_fork_area * 0.75
    assert step6_status["final_case_polygon"]["area_m2"] == pytest.approx(1666.546, abs=1e-3)
    assert (
        step6_status["final_case_polygon"]["area_m2"]
        > unit_status["terminal_support_corridor_geometry"]["area_m2"] * 1.1
    )
    geopandas = pytest.importorskip("geopandas")
    step4_geometries = geopandas.read_file(case_dir / "step4_event_evidence.gpkg")
    final_geometries = geopandas.read_file(case_dir / "final_case_polygon.gpkg")
    geometry_by_role = {row.geometry_role: row.geometry for _, row in step4_geometries.iterrows()}
    reference_point = geometry_by_role["fact_reference_point"]
    rcsd_node_point = geometry_by_role["required_rcsd_node_geometry"]
    throat_core_geometry = geometry_by_role["pair_local_throat_core_geometry"]
    selected_candidate_region_geometry = geometry_by_role["selected_candidate_region_geometry"]
    final_geometry = final_geometries.geometry.iloc[0]
    assert reference_point.x == pytest.approx(12737746.898, abs=1e-3)
    assert reference_point.y == pytest.approx(2586260.366, abs=1e-3)
    assert selected_candidate_region_geometry.buffer(1e-6).covers(reference_point)
    assert reference_point.distance(selected_candidate_region_geometry.boundary) <= 1e-6
    assert not throat_core_geometry.buffer(1e-6).covers(reference_point)
    assert throat_core_geometry.representative_point().distance(reference_point) > 80.0
    axis_dx = float(rcsd_node_point.x) - float(reference_point.x)
    axis_dy = float(rcsd_node_point.y) - float(reference_point.y)
    axis_length = (axis_dx * axis_dx + axis_dy * axis_dy) ** 0.5
    unit_x = axis_dx / axis_length
    unit_y = axis_dy / axis_length

    def signed_axis_range(geometry: object) -> tuple[float, float]:
        coords = []
        if geometry.geom_type == "Polygon":
            coords = list(geometry.exterior.coords)
        elif geometry.geom_type == "MultiPolygon":
            coords = [coord for part in geometry.geoms for coord in part.exterior.coords]
        values = [
            ((float(x) - float(reference_point.x)) * unit_x)
            + ((float(y) - float(reference_point.y)) * unit_y)
            for x, y, *_ in coords
        ]
        return min(values), max(values)

    min_axis_s, max_axis_s = signed_axis_range(final_geometry)
    assert min_axis_s >= -22.0
    assert max_axis_s <= axis_length + 22.0

    for accepted_surface_case in ("760984", "788824"):
        step4_surface = json.loads(
            (run_root / "cases" / accepted_surface_case / "step4_event_interpretation.json").read_text(
                encoding="utf-8"
            )
        )
        unit_surface = step4_surface["event_units"][0]
        assert unit_surface["selected_evidence_state"] == "found"
        assert unit_surface["evidence_source"] == "rcsd_junction_window"
        assert unit_surface["required_rcsd_node"]
        assert unit_surface["positive_rcsd_present"] is True
        assert unit_surface["rcsd_selection_mode"] == "rcsd_junction_window"
        assert "rcsd_junction_window_used" in "|".join(unit_surface["review_reasons"])

        step5_surface = json.loads(
            (run_root / "cases" / accepted_surface_case / "step5_status.json").read_text(
                encoding="utf-8"
            )
        )
        unit_step5_surface = step5_surface["unit_results"][0]
        assert unit_step5_surface["surface_fill_mode"] == "junction_window"
        assert unit_step5_surface["junction_full_road_fill_domain"]["present"] is True
        assert unit_step5_surface["required_rcsd_node_patch_geometry"]["present"] is True

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
    assert "no_surface_reference" in set(status_760598["reject_reasons"])
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

    step5_824002 = json.loads(
        (run_root / "cases" / "824002" / "step5_status.json").read_text(encoding="utf-8")
    )
    step6_824002 = json.loads(
        (run_root / "cases" / "824002" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step5_824002["case_bridge_zone_geometry"]["present"] is True
    assert step5_824002["case_bridge_zone_geometry"]["area_m2"] == pytest.approx(640.165, abs=1e-3)
    assert step6_824002["assembly_state"] == "assembled"
    assert step6_824002["component_count"] == 1
    assert step6_824002["hole_count"] == 0
    assert step6_824002["hard_must_cover_ok"] is True
    assert step6_824002["final_case_polygon"]["area_m2"] == pytest.approx(2741.967, abs=1e-3)
    assert step6_824002["final_case_polygon"]["length_m"] == pytest.approx(322.802, abs=1e-3)

    geopandas = pytest.importorskip("geopandas")
    step5_domains_824002 = geopandas.read_file(run_root / "cases" / "824002" / "step5_domains.gpkg")
    final_824002 = geopandas.read_file(run_root / "cases" / "824002" / "final_case_polygon.gpkg").geometry.iloc[0]
    bridge_824002 = step5_domains_824002[
        (step5_domains_824002.event_unit_id == "")
        & (step5_domains_824002.component_role == "case_bridge_zone_geometry")
    ].geometry.iloc[0]
    assert bridge_824002.intersection(final_824002).area / bridge_824002.area > 0.97
    for unit_id in ("node_824002", "node_824003"):
        localized_core = step5_domains_824002[
            (step5_domains_824002.event_unit_id == unit_id)
            & (step5_domains_824002.component_role == "localized_evidence_core_geometry")
        ].geometry.iloc[0]
        assert localized_core.difference(final_824002.buffer(1e-6)).area <= 1e-6

    surface_binding_payload = json.loads(
        (run_root / "step4_road_surface_fork_binding.json").read_text(encoding="utf-8")
    )
    surface_binding_by_case = {record["case_id"]: record for record in surface_binding_payload["records"]}
    record_706629 = surface_binding_by_case["706629"]
    assert record_706629["action"] == "kept_swsd_junction_window_no_rcsd"
    assert record_706629["post_state"] == "found"
    assert record_706629["positive_rcsd_consistency_level"] == "C"

    step4_706629 = json.loads(
        (run_root / "cases" / "706629" / "step4_event_interpretation.json").read_text(
            encoding="utf-8"
        )
    )
    unit_706629 = step4_706629["event_units"][0]
    assert unit_706629["selected_evidence_state"] == "found"
    assert unit_706629["evidence_source"] == "swsd_junction_window"
    assert unit_706629["required_rcsd_node"] is None
    assert unit_706629["rcsd_selection_mode"] == ""
    assert unit_706629["selected_evidence"]["rcsd_selection_mode"] == "swsd_junction_window_no_rcsd"
    assert "swsd_junction_window_no_rcsd_used" in set(unit_706629["review_reasons"])

    step5_706629 = json.loads(
        (run_root / "cases" / "706629" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_step5_706629 = step5_706629["unit_results"][0]
    assert step5_706629["case_bridge_zone_geometry"]["present"] is False
    assert step5_706629["case_terminal_window_domain"]["present"] is False
    assert unit_step5_706629["surface_fill_mode"] == "junction_window"
    assert unit_step5_706629["single_component_surface_seed"] is False
    assert unit_step5_706629["junction_full_road_fill_domain"]["present"] is True
    assert unit_step5_706629["required_rcsd_node_patch_geometry"]["present"] is False

    step6_706629 = json.loads(
        (run_root / "cases" / "706629" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_706629["assembly_state"] == "assembled"
    assert step6_706629["component_count"] == 1
    assert step6_706629["hole_count"] == 0
    assert step6_706629["section_reference_window_covered"] is True
    assert step6_706629["post_cleanup_must_cover_ok"] is True
    assert step6_706629["final_case_polygon"]["area_m2"] == pytest.approx(560.184, abs=1e-3)

    record_724081 = surface_binding_by_case["724081"]
    assert record_724081["action"] == "kept_swsd_junction_window_no_rcsd"
    assert record_724081["post_state"] == "found"
    assert record_724081["positive_rcsd_consistency_level"] == "C"
    assert record_724081["detail"]["multi_semantic_rcsd_context"] is True

    step4_724081 = json.loads(
        (run_root / "cases" / "724081" / "step4_event_interpretation.json").read_text(
            encoding="utf-8"
        )
    )
    unit_724081 = step4_724081["event_units"][0]
    assert unit_724081["selected_evidence_state"] == "found"
    assert unit_724081["evidence_source"] == "swsd_junction_window"
    assert unit_724081["main_evidence_type"] == "none"
    assert unit_724081["required_rcsd_node"] is None
    assert unit_724081["surface_scenario_type"] == "no_main_evidence_with_swsd_only"
    assert unit_724081["section_reference_source"] == "swsd_junction"
    assert unit_724081["surface_generation_mode"] == "swsd_junction_window"
    assert unit_724081["rcsd_selection_mode"] == ""
    assert unit_724081["selected_evidence"]["rcsd_selection_mode"] == "swsd_junction_window_no_rcsd"
    assert unit_724081["fallback_rcsdroad_ids"] == []
    assert "swsd_junction_window_no_rcsd_used" in set(unit_724081["review_reasons"])

    step5_724081 = json.loads(
        (run_root / "cases" / "724081" / "step5_status.json").read_text(encoding="utf-8")
    )
    unit_step5_724081 = step5_724081["unit_results"][0]
    assert step5_724081["case_bridge_zone_geometry"]["present"] is False
    assert step5_724081["case_terminal_window_domain"]["present"] is False
    assert unit_step5_724081["surface_fill_mode"] == "junction_window"
    assert set(unit_step5_724081["fallback_rcsdroad_ids"]) == set(unit_724081["fallback_rcsdroad_ids"])
    unrelated_rcsd_724081 = set(step5_724081["negative_mask_channels"]["unrelated_rcsd"]["road_ids"])
    assert unrelated_rcsd_724081.isdisjoint(unit_724081["fallback_rcsdroad_ids"])
    assert unit_step5_724081["single_component_surface_seed"] is False
    assert unit_step5_724081["junction_full_road_fill_domain"]["present"] is True
    assert unit_step5_724081["unit_terminal_cut_constraints"]["present"] is False
    assert unit_step5_724081["required_rcsd_node_patch_geometry"]["present"] is False

    step6_724081 = json.loads(
        (run_root / "cases" / "724081" / "step6_status.json").read_text(encoding="utf-8")
    )
    assert step6_724081["assembly_state"] == "assembled"
    assert step6_724081["component_count"] == 1
    assert step6_724081["barrier_separated_case_surface_ok"] is False
    assert step6_724081["post_cleanup_negative_mask_ok"] is True
    assert step6_724081["hole_count"] == 0
    assert step6_724081["section_reference_window_covered"] is True
    assert step6_724081["post_cleanup_must_cover_ok"] is True
    assert step5_724081["case_must_cover_domain"]["area_m2"] == pytest.approx(717.019, abs=1e-3)
    assert step6_724081["final_case_polygon"]["area_m2"] == pytest.approx(717.019, abs=1e-3)
    assert step6_724081["final_case_polygon"]["length_m"] == pytest.approx(132.091, abs=1e-3)

    assert surface_binding_by_case["760598"]["action"] == "cleared_unbound_road_surface_fork"


@pytest.mark.smoke
def test_anchor2_full_20260426_baseline_gate() -> None:
    official_case_ids = set(ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504)
    legacy_case_ids = set(ANCHOR2_LEGACY_23_SUBSET_20260426)

    assert len(legacy_case_ids) == 23
    assert legacy_case_ids < official_case_ids
    assert ANCHOR2_FULL_BASELINE_20260426 == {
        case_id: ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504[case_id][0]
        for case_id in ANCHOR2_LEGACY_23_SUBSET_20260426
    }
    assert sorted(
        case_id
        for case_id, final_state in ANCHOR2_FULL_BASELINE_20260426.items()
        if final_state == "accepted"
    ) == sorted(
        case_id
        for case_id in legacy_case_ids
        if ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504[case_id][0] == "accepted"
    )
    assert sum(1 for state in ANCHOR2_FULL_BASELINE_20260426.values() if state == "accepted") == 20
    assert sum(1 for state in ANCHOR2_FULL_BASELINE_20260426.values() if state == "rejected") == 3
    assert ANCHOR2_FULL_BASELINE_20260426["857993"] == "rejected"
    assert ANCHOR2_FULL_BASELINE_20260426["699870"] == "accepted"


@pytest.mark.smoke
def test_anchor2_30case_surface_scenario_baseline_gate() -> None:
    official_case_ids = set(ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504)
    legacy_case_ids = set(ANCHOR2_LEGACY_30_SUBSET_20260501)

    assert len(legacy_case_ids) == 30
    assert legacy_case_ids < official_case_ids
    assert ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501 == {
        case_id: ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504[case_id][0]
        for case_id in ANCHOR2_LEGACY_30_SUBSET_20260501
    }
    assert sum(
        1
        for state in ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501.values()
        if state == "accepted"
    ) == 26
    assert sum(
        1
        for state in ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501.values()
        if state == "rejected"
    ) == 4
    assert ANCHOR2_30CASE_REJECTED_20260501 == {
        "607602562",
        "760598",
        "760936",
        "857993",
    }
    assert {
        case_id
        for case_id in legacy_case_ids
        if ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260504[case_id][1] == "no_surface_reference"
    } == {"607602562", "760598"}
    for case_id in [
        "706629",
        "706347",
        "760984",
        "788824",
        "760230",
        "760277",
        "765170",
        "768680",
        "699870",
        "698389",
    ]:
        assert ANCHOR2_30CASE_SURFACE_SCENARIO_BASELINE_20260501[case_id] == "accepted"


@pytest.mark.smoke
def test_anchor2_39case_official_surface_scenario_gate(tmp_path: Path) -> None:
    if not REAL_ANCHOR_2_ROOT.is_dir():
        pytest.skip(f"missing real Anchor_2 case root: {REAL_ANCHOR_2_ROOT}")
    actual_case_ids = sorted(
        path.name
        for path in REAL_ANCHOR_2_ROOT.iterdir()
        if path.is_dir() and path.name.isdigit()
    )
    expected_case_ids = sorted(ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260503)
    assert actual_case_ids == expected_case_ids

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=expected_case_ids,
        out_root=tmp_path / "anchor2_39case_official_surface_scenario",
        run_id="anchor2_39case_official_surface_scenario",
    )

    summary_payload = _load_json(run_root / "divmerge_virtual_anchor_surface_summary.json")
    batch_summary = _load_json(run_root / "summary.json")
    consistency_payload = _load_json(run_root / "step7_consistency_report.json")
    nodes_audit_payload = _load_json(run_root / "nodes_anchor_update_audit.json")
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}

    assert batch_summary["failed_case_ids"] == []
    assert summary_payload["row_count"] == 39
    assert summary_payload["accepted_count"] == 35
    assert summary_payload["rejected_count"] == 4
    assert batch_summary["step7_accepted_count"] == 35
    assert batch_summary["step7_rejected_count"] == 4
    _assert_case_package_performance_summary(batch_summary, expected_completed_cases=39)
    assert consistency_payload["passed"] is True
    assert consistency_payload["total_case_count"] == 39
    assert consistency_payload["accepted_count"] == 35
    assert consistency_payload["rejected_count"] == 4
    assert consistency_payload["review_png_present_count"] == 39
    assert consistency_payload["missing_review_png_case_ids"] == []
    assert consistency_payload["nodes_consistency_passed"] is True
    assert consistency_payload["nodes_total_update_count"] == 39
    assert consistency_payload["nodes_updated_to_yes_count"] == 35
    assert consistency_payload["nodes_updated_to_fail4_count"] == 4
    assert nodes_audit_payload["total_update_count"] == 39
    assert nodes_audit_payload["updated_to_yes_count"] == 35
    assert nodes_audit_payload["updated_to_fail4_count"] == 4
    nodes_audit_by_case = {row["case_id"]: row for row in nodes_audit_payload["rows"]}
    for rejected_case_id in ANCHOR2_30CASE_REJECTED_20260501:
        assert rows_by_case[rejected_case_id]["final_state"] == "rejected"
        assert nodes_audit_by_case[rejected_case_id]["new_is_anchor"] == "fail4"
    assert set(summary_payload["no_surface_reference_case_ids"]) == {"607602562", "760598"}
    assert consistency_payload["no_surface_reference_accepted_case_ids"] == []

    for case_id, expected in ANCHOR2_39CASE_OFFICIAL_EXPECTED_20260503.items():
        row = rows_by_case[case_id]
        case_dir = run_root / "cases" / case_id
        step5_audit = _load_json(case_dir / "step5_audit.json")
        step4_doc = _load_json(case_dir / "step4_event_interpretation.json")
        expected_state, expected_scenario, expected_section, expected_mode = expected
        assert row["final_state"] == expected_state
        assert row["surface_scenario_type"] == expected_scenario
        assert row["section_reference_source"] == expected_section
        assert row["surface_generation_mode"] == expected_mode
        assert Path(row["review_png_path"]).is_file()
        _assert_gpkg_crs_and_valid_features(case_dir / "step5_domains.gpkg")
        mask_channels = step5_audit["negative_mask_channels"]
        for channel_name in [
            "unrelated_swsd",
            "unrelated_rcsd",
            "divstrip_body",
            "divstrip_void",
            "forbidden_domain",
            "terminal_cut",
        ]:
            assert channel_name in mask_channels
            assert "geometry" in mask_channels[channel_name]
            assert "applied_to_forbidden_domain" in mask_channels[channel_name]
        assert "unrelated_swsd_road_ids" in step5_audit
        assert "unrelated_swsd_node_ids" in step5_audit
        assert "unrelated_rcsd_road_ids" in step5_audit
        assert "unrelated_rcsd_node_ids" in step5_audit
        aggregate = step4_doc["case_alignment_aggregate"]
        assert aggregate["case_id"] == case_id
        assert aggregate["scope"] == "case"
        assert aggregate["unit_count"] == len(step4_doc["event_units"])
        assert len(aggregate["unit_alignment_results"]) == len(step4_doc["event_units"])
        for unit in step4_doc["event_units"]:
            alignment_result = unit["rcsd_alignment_result"]
            assert alignment_result["scope"] == "event_unit"
            assert alignment_result["scope_id"] == unit["event_unit_id"]
            assert alignment_result["rcsd_alignment_type"] == unit["rcsd_alignment_type"]
            assert "positive_rcsdroad_ids" in alignment_result
            assert "candidate_rcsdroad_ids" in alignment_result
            assert "ambiguity_reasons" in alignment_result
        if expected_state == "accepted":
            assert row["surface_scenario_type"] != "no_surface_reference"
            assert row["no_surface_reference_guard"] is False
            step6_status = _load_json(case_dir / "step6_status.json")
            assert step6_status["component_count"] == 1
            assert step6_status["final_case_polygon_component_count"] == 1
            assert step6_status["single_connected_case_surface_ok"] is True
            assert step6_status["barrier_separated_case_surface_ok"] is False
            _assert_gpkg_crs_and_valid_features(case_dir / "final_case_polygon.gpkg")


@pytest.mark.smoke
def test_anchor2_new6_user_audit_surface_scenario_gate(tmp_path: Path) -> None:
    missing_cases = [
        case_id
        for case_id in ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502
        if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing_cases:
        pytest.skip(f"missing real case package(s): {', '.join(sorted(missing_cases))}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502),
        out_root=tmp_path / "anchor2_new6_user_audit_surface_scenario",
        run_id="anchor2_new6_user_audit_surface_scenario",
    )

    batch_summary = _load_json(run_root / "summary.json")
    summary_payload = _load_json(run_root / "divmerge_virtual_anchor_surface_summary.json")
    consistency_payload = _load_json(run_root / "step7_consistency_report.json")
    nodes_audit_payload = _load_json(run_root / "nodes_anchor_update_audit.json")
    rows_by_case = {row["case_id"]: row for row in summary_payload["rows"]}
    expected_case_ids = set(ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502)

    assert batch_summary["failed_case_ids"] == []
    assert batch_summary["step7_accepted_count"] == 6
    assert batch_summary["step7_rejected_count"] == 0
    assert summary_payload["row_count"] == 6
    assert summary_payload["accepted_count"] == 6
    assert summary_payload["rejected_count"] == 0
    assert set(rows_by_case) == expected_case_ids
    assert summary_payload["no_surface_reference_case_ids"] == []
    assert consistency_payload["passed"] is True
    assert consistency_payload["nodes_updated_to_yes_count"] == 6
    assert consistency_payload["nodes_updated_to_fail4_count"] == 0
    assert nodes_audit_payload["updated_to_yes_count"] == 6
    assert nodes_audit_payload["updated_to_fail4_count"] == 0

    for case_id, expected in ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502.items():
        case_dir = run_root / "cases" / case_id
        row = rows_by_case[case_id]
        step4_doc = _load_json(case_dir / "step4_event_interpretation.json")
        step6_status = _load_json(case_dir / "step6_status.json")
        step7_status = _load_json(case_dir / "step7_status.json")
        unit = step4_doc["event_units"][0]

        expected_final_state = str(expected.get("final_state") or "accepted")
        assert row["final_state"] == expected_final_state
        assert row["surface_scenario_type"] == expected["surface_scenario_type"]
        assert row["section_reference_source"] == expected["section_reference_source"]
        assert row["surface_generation_mode"] == expected["surface_generation_mode"]
        assert row["no_surface_reference_guard"] is False
        assert step7_status["final_state"] == expected_final_state
        assert unit["evidence_source"] == expected["step4_evidence_source"]
        assert unit["main_evidence_type"] == expected["step4_main_evidence_type"]
        assert unit["surface_scenario_type"] == expected.get(
            "unit_surface_scenario_type",
            expected["surface_scenario_type"],
        )
        _assert_no_main_evidence_has_no_virtual_reference_point(step4_doc)

        if expected_final_state == "accepted":
            assert step6_status["assembly_state"] == "assembled"
            assert step6_status["component_count"] == 1
            assert step6_status["final_case_polygon_component_count"] == 1
            assert step6_status["single_connected_case_surface_ok"] is True
            assert step6_status["barrier_separated_case_surface_ok"] is False
        else:
            assert step6_status["assembly_state"] == "assembly_failed"
            assert step6_status["component_count"] > 1
            assert step6_status["final_case_polygon_component_count"] > 1
            assert step6_status["single_connected_case_surface_ok"] is False
            assert step6_status["barrier_separated_case_surface_ok"] is True
            assert "multi_component_result" in step7_status["reject_reasons"]
        assert step6_status["post_cleanup_allowed_growth_ok"] is True
        assert step6_status["post_cleanup_forbidden_ok"] is True
        assert step6_status["post_cleanup_terminal_cut_ok"] is True
        assert step6_status["post_cleanup_lateral_limit_ok"] is True
        assert (case_dir / "final_case_polygon.gpkg").is_file()
        assert Path(row["review_png_path"]).is_file()

    assert rows_by_case["807908"]["surface_scenario_type"] == "main_evidence_with_rcsd_junction"
    step4_807908 = _load_json(run_root / "cases" / "807908" / "step4_event_interpretation.json")
    unit_807908 = step4_807908["event_units"][0]
    assert unit_807908["selected_rcsdroad_ids"] == [
        "5395523385822744",
        "5395541068551328",
        "5395541068551367",
    ]
    step4_785629 = _load_json(run_root / "cases" / "785629" / "step4_event_interpretation.json")
    assert {
        unit["positive_rcsd_present"] for unit in step4_785629["event_units"]
    } == {False}
    assert {
        tuple(unit["selected_rcsdroad_ids"]) for unit in step4_785629["event_units"]
    } == {()}

    assert rows_by_case["823826"]["surface_scenario_type"] == "main_evidence_with_rcsd_junction"
    step6_823826 = _load_json(run_root / "cases" / "823826" / "step6_status.json")
    assert step6_823826["hole_count"] == 0
    assert step6_823826["business_hole_count"] == 0
    assert step6_823826["unexpected_hole_count"] == 0
