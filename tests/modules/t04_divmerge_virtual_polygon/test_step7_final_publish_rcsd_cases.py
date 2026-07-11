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
        "final_state": "rejected",
        "surface_scenario_type": "mixed",
        "section_reference_source": "mixed",
        "surface_generation_mode": "mixed",
        "unit_surface_scenario_type": "main_evidence_without_rcsd",
        "step4_evidence_source": "multibranch_event",
        "step4_main_evidence_type": "divstrip",
        "step6_assembly_state": "assembled",
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
        "surface_scenario_type": "no_main_evidence_with_rcsdroad_fallback_and_swsd",
        "section_reference_source": "swsd_junction",
        "surface_generation_mode": "swsd_with_rcsdroad_fallback",
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
    expected_accepted_count = sum(
        1
        for expected in ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502.values()
        if str(expected.get("final_state") or "accepted") == "accepted"
    )
    expected_rejected_count = len(ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502) - expected_accepted_count

    assert batch_summary["failed_case_ids"] == []
    assert batch_summary["step7_accepted_count"] == expected_accepted_count
    assert batch_summary["step7_rejected_count"] == expected_rejected_count
    assert summary_payload["row_count"] == 6
    assert summary_payload["accepted_count"] == expected_accepted_count
    assert summary_payload["rejected_count"] == expected_rejected_count
    assert set(rows_by_case) == expected_case_ids
    assert summary_payload["no_surface_reference_case_ids"] == []
    assert consistency_payload["passed"] is True
    assert consistency_payload["nodes_updated_to_yes_count"] == expected_accepted_count
    assert consistency_payload["nodes_updated_to_fail4_count"] == expected_rejected_count
    assert nodes_audit_payload["updated_to_yes_count"] == expected_accepted_count
    assert nodes_audit_payload["updated_to_fail4_count"] == expected_rejected_count

    for case_id, expected in ANCHOR2_NEW6_USER_AUDIT_EXPECTED_20260502.items():
        case_dir = run_root / "cases" / case_id
        row = rows_by_case[case_id]
        step4_doc = _load_json(case_dir / "step4_event_interpretation.json")
        step6_status = _load_json(case_dir / "step6_status.json")
        step7_status = _load_json(case_dir / "step7_status.json")
        unit = next(
            (
                candidate
                for candidate in step4_doc["event_units"]
                if candidate["evidence_source"] == expected["step4_evidence_source"]
                and candidate["main_evidence_type"] == expected["step4_main_evidence_type"]
            ),
            step4_doc["event_units"][0],
        )

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
            assert step6_status["assembly_state"] == expected.get("step6_assembly_state", "assembly_failed")
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
    expected_rcsd_807908 = {
        "5395523385822740",
        "5395523385822742",
        "5395541068551367",
    }
    assert set(unit_807908["selected_rcsdroad_ids"]) == expected_rcsd_807908
    step5_807908 = _load_json(run_root / "cases" / "807908" / "step5_audit.json")
    related_rcsd_807908 = set(step5_807908["related_rcsd_road_ids"])
    unrelated_rcsd_807908 = set(
        step5_807908["negative_mask_channels"]["unrelated_rcsd"]["road_ids"]
    )
    for road_id in expected_rcsd_807908:
        assert road_id in related_rcsd_807908
        assert road_id not in unrelated_rcsd_807908
    for road_id in ("5395523385822744", "5395523385822746", "5395541068551328"):
        assert road_id not in related_rcsd_807908
        assert road_id in unrelated_rcsd_807908
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


@pytest.mark.smoke
def test_real_760256_road_surface_fork_binds_correct_rcsd_junction(
    tmp_path: Path,
) -> None:
    if not (REAL_ANCHOR_2_ROOT / "760256").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '760256'}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["760256"],
        out_root=tmp_path / "anchor2_760256_road_surface_fork_rcsd",
        run_id="anchor2_760256_road_surface_fork_rcsd",
    )

    case_dir = run_root / "cases" / "760256"
    step4_doc = _load_json(case_dir / "step4_event_interpretation.json")
    step6_status = _load_json(case_dir / "step6_status.json")
    step7_status = _load_json(case_dir / "step7_status.json")
    unit = step4_doc["event_units"][0]

    assert step7_status["final_state"] == "accepted"
    assert step6_status["assembly_state"] == "assembled"
    assert step6_status["component_count"] == 1
    assert unit["surface_scenario_type"] == "main_evidence_with_rcsd_junction"
    assert unit["evidence_source"] == "road_surface_fork"
    assert unit["position_source"] == "road_surface_fork"
    assert unit["main_evidence_type"] == "road_surface_fork"
    assert unit["selected_evidence"]["candidate_scope"] == "road_surface_fork"
    assert (
        unit["selected_evidence"]["road_surface_fork_reference_point_mode"]
        == "road_surface_fork_boundary_apex"
    )
    assert unit["required_rcsd_node"] == "5395166300816825"
    assert unit["selected_rcsdnode_ids"] == ["5395166300816825"]
    assert unit["selected_rcsdroad_ids"] == [
        "5395167139463556",
        "5395167139463560",
        "5395167139463565",
    ]
    assert unit["rcsd_alignment_type"] == "rcsd_semantic_junction"
    assert unit["positive_rcsd_consistency_level"] == "A"
    assert unit["rcsd_semantic_junction"]["member_rcsdnode_ids"] == [
        "5395166300816825"
    ]


@pytest.mark.smoke
def test_real_new_anchor2_rcsd_junction_cases_keep_required_node(
    tmp_path: Path,
) -> None:
    expected_required_nodes = {
        "699952": "5389859095909003",
        "724743": "5395796452837745",
        "758704": "5395099124659921",
    }
    missing = [
        case_id
        for case_id in expected_required_nodes
        if not (REAL_ANCHOR_2_ROOT / case_id).is_dir()
    ]
    if missing:
        pytest.skip(f"missing real case packages under {REAL_ANCHOR_2_ROOT}: {missing}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=list(expected_required_nodes),
        out_root=tmp_path / "anchor2_new_rcsd_required_nodes",
        run_id="anchor2_new_rcsd_required_nodes",
    )

    for case_id, expected_node in expected_required_nodes.items():
        case_dir = run_root / "cases" / case_id
        step4_doc = _load_json(case_dir / "step4_event_interpretation.json")
        step7_status = _load_json(case_dir / "step7_status.json")
        unit = step4_doc["event_units"][0]

        assert step7_status["final_state"] == "accepted"
        assert unit["required_rcsd_node"] == expected_node
        assert expected_node in unit["selected_rcsdnode_ids"]
        assert unit["positive_rcsd_present"] is True
        assert unit["rcsd_alignment_type"] == "rcsd_semantic_junction"

    for case_id in ("724743", "758704"):
        unit = _load_json(
            run_root / "cases" / case_id / "step4_event_interpretation.json"
        )["event_units"][0]
        assert unit["surface_scenario_type"] == "main_evidence_with_rcsd_junction"
        assert unit["evidence_source"] == "road_surface_fork"
        assert unit["main_evidence_type"] == "road_surface_fork"
        assert "road_surface_fork_direct_rcsdroad_fallback_only" not in unit["review_reasons"]

    unit_699952 = _load_json(
        run_root / "cases" / "699952" / "step4_event_interpretation.json"
    )["event_units"][0]
    assert unit_699952["surface_scenario_type"] == "no_main_evidence_with_rcsd_junction"
    assert unit_699952["selected_evidence"]["candidate_id"] == "event_unit_01:structure:throat:01"


@pytest.mark.smoke
def test_real_807908_rcsd_semantic_junction_roads_are_not_negative_mask(
    tmp_path: Path,
) -> None:
    if not (REAL_ANCHOR_2_ROOT / "807908").is_dir():
        pytest.skip(f"missing real case package: {REAL_ANCHOR_2_ROOT / '807908'}")

    run_root = run_t04_step14_batch(
        case_root=REAL_ANCHOR_2_ROOT,
        case_ids=["807908"],
        out_root=tmp_path / "anchor2_807908_rcsd_semantic_junction_mask",
        run_id="anchor2_807908_rcsd_semantic_junction_mask",
    )

    case_dir = run_root / "cases" / "807908"
    step4_doc = _load_json(case_dir / "step4_event_interpretation.json")
    step5_audit = _load_json(case_dir / "step5_audit.json")
    step6_status = _load_json(case_dir / "step6_status.json")
    step7_status = _load_json(case_dir / "step7_status.json")
    render_audit = _load_json(case_dir / "final_review_render_audit.json")
    unit = step4_doc["event_units"][0]

    assert unit["surface_scenario_type"] == "main_evidence_with_rcsd_junction"
    assert unit["section_reference_source"] == "reference_point_and_rcsd_junction"
    assert unit["required_rcsd_node"] == "5395523385822712"
    assert unit["rcsd_alignment_type"] == "rcsd_semantic_junction"

    expected_rcsd = {
        "5395523385822740",
        "5395523385822742",
        "5395541068551367",
    }
    assert set(unit["selected_rcsdroad_ids"]) == expected_rcsd
    assert unit["selected_evidence"]["rcsd_anchored_reverse_prune"]["mode"] == (
        "required_node_semantic_junction_direct_arms"
    )
    related_rcsd = set(step5_audit["related_rcsd_road_ids"])
    unrelated_rcsd = set(step5_audit["negative_mask_channels"]["unrelated_rcsd"]["road_ids"])
    for road_id in expected_rcsd:
        assert road_id in related_rcsd
        assert road_id not in unrelated_rcsd
    for road_id in ("5395523385822744", "5395523385822746", "5395541068551328"):
        assert road_id not in related_rcsd
        assert road_id in unrelated_rcsd
    assert set(render_audit["rcsd_entity_road_ids"]) == expected_rcsd
    assert set(render_audit["render_visible_rcsd_road_ids"]) == expected_rcsd
    assert render_audit["missing_rcsd_road_ids"] == []

    assert step6_status["assembly_state"] == "assembled"
    assert step6_status["component_count"] == 1
    assert step7_status["final_state"] == "accepted"
