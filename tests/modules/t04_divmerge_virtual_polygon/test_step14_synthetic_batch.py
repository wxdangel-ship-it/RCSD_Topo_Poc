from __future__ import annotations

from tests.modules.t04_divmerge_virtual_polygon.test_step14_support import *  # noqa: F401,F403

@pytest.mark.smoke
def test_t04_step14_batch_outputs_synthetic_case(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "1001"
    _build_synthetic_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out",
        run_id="synthetic_t04",
    )

    summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    review_summary = json.loads((run_root / "step4_review_summary.json").read_text(encoding="utf-8"))
    second_pass = json.loads((run_root / "second_pass_conflict_resolution.json").read_text(encoding="utf-8"))

    assert summary["total_case_count"] == 1
    assert summary["failed_case_ids"] == []
    assert review_summary["total_event_unit_count"] >= 1
    assert {
        "same_case_evidence_components",
        "same_case_rcsd_components",
        "cross_case_components",
    }.issubset(second_pass)
    assert (run_root / "cases" / "1001" / "step4_review_overview.png").is_file()
    assert any((run_root / "step4_review_flat").glob("*.png"))
    assert any((run_root / "cases" / "1001" / "event_units").rglob("step4_review.png"))
    assert any((run_root / "cases" / "1001" / "event_units").rglob("step4_candidate_compare.png"))

@pytest.mark.smoke
def test_t04_step14_batch_writes_unit_level_step3_and_candidate_docs(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "1001"
    _build_synthetic_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_docs",
        run_id="synthetic_t04_docs",
    )

    result_case_dir = run_root / "cases" / "1001"
    case_step3 = json.loads((result_case_dir / "step3_status.json").read_text(encoding="utf-8"))
    case_step4 = json.loads((result_case_dir / "step4_event_interpretation.json").read_text(encoding="utf-8"))
    case_step4_audit = json.loads((result_case_dir / "step4_audit.json").read_text(encoding="utf-8"))
    unit_dir = next((result_case_dir / "event_units").iterdir())
    unit_step3 = json.loads((unit_dir / "step3_status.json").read_text(encoding="utf-8"))
    candidate_doc = json.loads((unit_dir / "step4_candidates.json").read_text(encoding="utf-8"))
    evidence_audit_doc = json.loads((unit_dir / "step4_evidence_audit.json").read_text(encoding="utf-8"))

    assert case_step3["topology_scope"] == "case_coordination"
    assert unit_step3["topology_scope"] == "case_coordination"
    assert unit_step3["event_branch_ids"] == ["road_3"]
    assert unit_step3["boundary_branch_ids"] == ["road_1", "road_2", "road_3"]
    assert unit_step3["preferred_axis_branch_id"] == "road_1"
    assert unit_step3["degraded_scope_reason"] == "pair_local_scope_roads_empty"

    selected_evidence = candidate_doc["selected_evidence"]
    assert candidate_doc["selected_evidence_state"] == "found"
    assert selected_evidence["candidate_id"].startswith("event_unit_01:divstrip:")
    assert selected_evidence["layer_label"] == "Layer 2"
    assert selected_evidence["selection_rank"] == 1
    expected_axis_signature = _stable_axis_signature(
        unit_step3["branch_road_memberships"],
        unit_step3["preferred_axis_branch_id"],
    )
    assert selected_evidence["point_signature"].startswith(f"{expected_axis_signature}:")
    assert candidate_doc["selected_candidate_region"] == case_step4["event_units"][0]["pair_local_summary"]["region_id"]
    assert candidate_doc["positive_rcsd_support_level"] in {"primary_support", "secondary_support", "no_support"}
    assert candidate_doc["positive_rcsd_consistency_level"] in {"A", "B", "C"}
    assert "pair_local_rcsd_empty" in candidate_doc
    assert "rcsd_selection_mode" in candidate_doc
    assert "local_rcsd_unit_kind" in candidate_doc
    assert "aggregated_rcsd_unit_id" in candidate_doc
    assert "aggregated_rcsd_unit_ids" in candidate_doc
    assert "first_hit_rcsdroad_ids" in candidate_doc
    assert "positive_rcsd_present" in candidate_doc
    assert "positive_rcsd_present_reason" in candidate_doc
    assert "axis_polarity_inverted" in candidate_doc
    assert "positive_rcsd_audit" in candidate_doc
    assert "evidence_conflict_component_id" in candidate_doc
    assert "rcsd_conflict_component_id" in candidate_doc
    assert "evidence_conflict_type" in candidate_doc
    assert "rcsd_conflict_type" in candidate_doc
    assert "conflict_resolution_action" in candidate_doc
    assert "pre_resolution_candidate_id" in candidate_doc
    assert "post_resolution_candidate_id" in candidate_doc
    assert "pre_required_rcsd_node" in candidate_doc
    assert "post_required_rcsd_node" in candidate_doc
    assert "resolution_reason" in candidate_doc
    assert "kept_by_baseline_guard" in candidate_doc
    assert "selected_rcsdroad_ids" in candidate_doc
    assert "selected_rcsdnode_ids" in candidate_doc
    assert "required_rcsd_node_source" in candidate_doc
    if (
        candidate_doc["local_rcsd_unit_kind"] == "node_centric"
        and candidate_doc["positive_rcsd_consistency_level"] in {"A", "B"}
    ):
        assert candidate_doc["required_rcsd_node"] not in {"", None}
    assert any(
        candidate["layer_label"] == "Layer 2"
        for candidate in candidate_doc["alternative_candidates"]
    )
    assert evidence_audit_doc["audit_summary"]["candidate_pool_size"] >= 2
    assert evidence_audit_doc["audit_summary"]["selected_reference_zone"] in {
        "throat",
        "middle",
        "edge",
        "outside",
        "missing",
    }
    assert evidence_audit_doc["candidate_shortlist"]
    assert set(item["candidate_id"] for item in evidence_audit_doc["candidate_shortlist"]).issubset(
        set(evidence_audit_doc["audit_summary"]["candidate_shortlist_ids"])
    )
    shortlist_entry = evidence_audit_doc["candidate_shortlist"][0]
    assert {
        "selection_status",
        "decision_reason",
        "review_state",
        "evidence_source",
        "position_source",
        "reverse_tip_used",
        "rcsd_consistency_result",
        "positive_rcsd_support_level",
        "positive_rcsd_consistency_level",
    }.issubset(shortlist_entry)

    assert case_step4["event_units"][0]["selected_evidence_state"] == "found"
    assert case_step4["event_units"][0]["selected_candidate_region"] == candidate_doc["selected_candidate_region"]
    assert case_step4["event_units"][0]["selected_evidence"]["candidate_id"] == selected_evidence["candidate_id"]
    assert case_step4["event_units"][0]["positive_rcsd_consistency_level"] in {"A", "B", "C"}
    assert isinstance(case_step4["event_units"][0]["positive_rcsd_present"], bool)
    assert "positive_rcsd_audit" in case_step4["event_units"][0]
    assert "evidence_conflict_component_id" in case_step4["event_units"][0]
    assert "rcsd_conflict_component_id" in case_step4["event_units"][0]
    assert case_step4["event_units"][0]["selected_rcsdroad_ids"] == candidate_doc["selected_rcsdroad_ids"]
    assert case_step4_audit["event_units"][0]["selected_evidence"]["candidate_id"] == selected_evidence["candidate_id"]

    fiona = pytest.importorskip("fiona")
    with fiona.open(result_case_dir / "step4_event_evidence.gpkg") as src:
        rows = list(src)
    assert any(item["properties"]["geometry_role"] == "selected_evidence_region_geometry" for item in rows)
    assert any(item["properties"]["candidate_id"] == selected_evidence["candidate_id"] for item in rows)

@pytest.mark.smoke
def test_t04_step14_batch_outputs_multi_event_case(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "2002"
    _build_multi_event_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_multi",
        run_id="synthetic_t04_multi",
    )

    review_summary = json.loads((run_root / "step4_review_summary.json").read_text(encoding="utf-8"))
    flat_pngs = sorted((run_root / "step4_review_flat").glob("*.png"))

    assert review_summary["total_event_unit_count"] == 3
    assert review_summary["cases_with_multiple_event_units"] == ["2002"]
    assert len(flat_pngs) == 10
    assert any(path.name.endswith("__main.png") for path in flat_pngs)
    assert any(path.name.endswith("__compare.png") for path in flat_pngs)
    assert any(path.name.endswith("__rcsd.png") for path in flat_pngs)
    assert any("overview" in path.name for path in flat_pngs)

@pytest.mark.smoke
def test_t04_step14_multi_event_case_exports_reselection_and_index_fields(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "2002"
    _build_multi_event_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_multi_docs",
        run_id="synthetic_t04_multi_docs",
    )

    review_summary = json.loads((run_root / "step4_review_summary.json").read_text(encoding="utf-8"))
    assert review_summary["selected_evidence_none_count"] == 2
    assert review_summary["selected_layer_1_count"] == 0
    assert review_summary["selected_layer_2_count"] == 1
    assert review_summary["selected_layer_3_count"] == 0
    assert "positive_rcsd_support_level_counts" in review_summary
    assert "positive_rcsd_consistency_level_counts" in review_summary
    assert "positive_rcsd_present_counts" in review_summary
    assert "axis_polarity_inverted_counts" in review_summary
    assert "selected_reference_zone_counts" in review_summary
    assert "conflict_signal_level_counts" in review_summary
    assert "top_focus_reasons" in review_summary

    event_unit_02_dir = run_root / "cases" / "2002" / "event_units" / "event_unit_02"
    event_unit_03_dir = run_root / "cases" / "2002" / "event_units" / "event_unit_03"
    unit_02_step3 = json.loads((event_unit_02_dir / "step3_status.json").read_text(encoding="utf-8"))
    unit_03_step3 = json.loads((event_unit_03_dir / "step3_status.json").read_text(encoding="utf-8"))
    unit_02_candidates = json.loads((event_unit_02_dir / "step4_candidates.json").read_text(encoding="utf-8"))
    unit_03_candidates = json.loads((event_unit_03_dir / "step4_candidates.json").read_text(encoding="utf-8"))

    assert unit_02_step3["topology_scope"] == "multi_divmerge_case_input"
    assert unit_02_candidates["selected_evidence_state"] == "none"
    assert unit_02_candidates["selected_evidence"]["selection_status"] == "none"
    assert unit_02_candidates["selected_evidence"]["decision_reason"] == "no_selected_evidence_after_reselection"
    assert any(
        candidate["candidate_id"] == "event_unit_02:structure:throat:01"
        for candidate in unit_02_candidates["alternative_candidates"]
    )
    assert any(candidate["reverse_tip_used"] is True for candidate in unit_02_candidates["alternative_candidates"])

    assert unit_03_candidates["selected_evidence_state"] == "found"
    assert unit_03_candidates["selected_evidence"]["selected_after_reselection"] is False
    assert unit_03_candidates["selected_evidence"]["selection_rank"] == 1
    assert unit_03_candidates["positive_rcsd_support_level"] in {"primary_support", "secondary_support", "no_support"}
    assert unit_03_candidates["positive_rcsd_consistency_level"] in {"A", "B", "C"}
    expected_unit_03_axis_signature = _stable_axis_signature(
        unit_03_step3["branch_road_memberships"],
        unit_03_step3["preferred_axis_branch_id"],
    )
    assert unit_03_candidates["selected_evidence"]["point_signature"].startswith(
        f"{expected_unit_03_axis_signature}:"
    )
    assert any(candidate["reverse_tip_used"] is True for candidate in unit_03_candidates["alternative_candidates"])

    with (run_root / "step4_review_index.csv").open("r", encoding="utf-8-sig", newline="") as fp:
        rows = {row["event_unit_id"]: row for row in csv.DictReader(fp)}

    assert rows["event_unit_01"]["selected_evidence_state"] == "none"
    assert rows["event_unit_02"]["selected_evidence_state"] == "none"
    assert rows["event_unit_03"]["selected_evidence_state"] == "found"
    assert rows["event_unit_03"]["primary_candidate_layer"] == "Layer 2"
    expected_unit_02_axis_signature = _stable_axis_signature(
        unit_02_step3["branch_road_memberships"],
        unit_02_step3["preferred_axis_branch_id"],
    )
    assert rows["event_unit_02"]["primary_candidate_id"] == ""
    assert rows["event_unit_02"]["point_signature"] == ""
    assert rows["event_unit_03"]["point_signature"].startswith(f"{expected_unit_03_axis_signature}:")
    assert rows["event_unit_02"]["ownership_signature"] == ""
    assert rows["event_unit_02"]["evidence_conflict_type"] != ""
    assert rows["event_unit_02"]["rcsd_conflict_type"] != ""
    assert rows["event_unit_02"]["conflict_resolution_action"] != ""
    assert rows["event_unit_02"]["resolution_reason"] != ""
    assert rows["event_unit_02"]["kept_by_baseline_guard"] in {"0", "1"}
    assert rows["event_unit_02"]["has_alternative_candidates"] == "1"
    assert rows["event_unit_02"]["selected_reference_zone"] in {"throat", "middle", "edge", "outside", "missing"}
    assert rows["event_unit_02"]["positive_rcsd_support_level"] in {"primary_support", "secondary_support", "no_support"}
    assert rows["event_unit_02"]["positive_rcsd_consistency_level"] in {"A", "B", "C"}
    assert rows["event_unit_02"]["positive_rcsd_present"] in {"0", "1"}
    assert rows["event_unit_02"]["axis_polarity_inverted"] in {"0", "1"}
    assert rows["event_unit_02"]["pair_local_rcsd_empty"] in {"0", "1"}
    assert rows["event_unit_02"]["rcsd_selection_mode"] != ""
    assert rows["event_unit_02"]["selected_candidate_region"] != ""
    assert rows["event_unit_02"]["selected_evidence_membership"] != ""
    assert rows["event_unit_02"]["needs_manual_review_focus"] == "1"
    assert rows["event_unit_02"]["compare_image_path"].endswith("__compare.png")
    assert rows["event_unit_02"]["positive_rcsd_image_path"].endswith("__rcsd.png")
    assert rows["event_unit_02"]["case_overview_path"].endswith("overview.png")

@pytest.mark.smoke
def test_t04_step14_pair_local_empty_rcsd_does_not_fallback_to_case_world(tmp_path: Path) -> None:
    case_root = tmp_path / "cases"
    case_dir = case_root / "1002"
    _build_pair_local_empty_rcsd_case_package(case_dir)

    run_root = run_t04_step14_batch(
        case_root=case_root,
        out_root=tmp_path / "out_pair_local_empty",
        run_id="synthetic_t04_pair_local_empty",
    )

    unit_dir = next((run_root / "cases" / "1002" / "event_units").iterdir())
    candidate_doc = json.loads((unit_dir / "step4_candidates.json").read_text(encoding="utf-8"))
    evidence_doc = json.loads((unit_dir / "step4_evidence_audit.json").read_text(encoding="utf-8"))
    review_summary = json.loads((run_root / "step4_review_summary.json").read_text(encoding="utf-8"))

    assert candidate_doc["pair_local_rcsd_empty"] is True
    assert candidate_doc["positive_rcsd_support_level"] == "no_support"
    assert candidate_doc["positive_rcsd_consistency_level"] == "C"
    assert candidate_doc["positive_rcsd_present"] is False
    assert candidate_doc["required_rcsd_node"] in {"", None}
    assert candidate_doc["selected_rcsdroad_ids"] == []
    assert candidate_doc["selected_rcsdnode_ids"] == []
    assert candidate_doc["rcsd_selection_mode"] == "pair_local_empty"
    assert evidence_doc["positive_rcsd_audit"]["rcsd_decision_reason"] == "pair_local_rcsd_empty"
    assert review_summary["pair_local_rcsd_empty_count"] >= 1
