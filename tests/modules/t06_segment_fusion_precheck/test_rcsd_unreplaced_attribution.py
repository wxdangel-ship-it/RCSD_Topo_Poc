from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import rcsd_unreplaced_attribution as attribution_module
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.rcsd_unreplaced_attribution import (
    run_t06_rcsd_unreplaced_attribution,
)


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _segment(segment_id: str, x0: float, y: float = 0.0) -> dict:
    return {
        "properties": {"id": segment_id},
        "geometry": LineString([(x0, y), (x0 + 10, y)]),
    }


def _road(road_id: str, x0: float, y: float = 1.0, **props) -> dict:
    payload = {
        "id": road_id,
        "snodeid": f"{road_id}_s",
        "enodeid": f"{road_id}_e",
        "direction": 0,
        "source": 1,
        "length_m": 10.0,
    }
    payload.update(props)
    return {
        "properties": payload,
        "geometry": LineString([(x0, y), (x0 + 10, y)]),
    }


def _segment_row(segment_id: str, **props) -> dict:
    payload = {"swsd_segment_id": segment_id}
    payload.update(props)
    return {
        "properties": payload,
        "geometry": LineString([(0, 0), (1, 0)]),
    }


def test_unreplaced_rcsd_attribution_uses_formal_funnel_priority(tmp_path: Path, monkeypatch) -> None:
    run_root = tmp_path / "t06_run"
    swsd_segment = _write(
        tmp_path / "segment.gpkg",
        [
            _segment("s5", 0),
            _segment("s4", 100),
            _segment("s3", 200),
            _segment("s2", 300),
            _segment("s2g", 400),
            _segment("s4g", 400, y=30),
            _segment("a_mix2", 500),
            _segment("b_mix4", 500),
            _segment("s5_plan_blocked_unreferenced", 600),
            _segment("s3_required_disconnected", 700),
            _segment("s4_directionality", 800),
            _segment("s4_required_ready", 900),
            _segment("s5_replaced_unreferenced", 1100),
        ],
    )
    rcsdroad = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            _road("rr5", 0),
            _road("rr4", 100),
            _road("rr3", 200),
            _road("rr2", 300),
            _road("rr1", 1000),
            _road("rr_geo2", 400),
            _road("rr_mix", 500),
            _road("rr_plan_blocked_unreferenced", 600),
            _road("rr_required_disconnected", 700),
            _road("rr_directionality", 800),
            _road("rr_required_ready", 900),
            _road("rr_replaced_unreferenced", 1100),
        ],
    )

    _write(
        run_root / "step1_identify_fusion_units" / "t06_swsd_segment_candidates.gpkg",
        [
            _segment_row("s5"),
            _segment_row("s4"),
            _segment_row("s3"),
            _segment_row("s4g"),
            _segment_row("b_mix4"),
            _segment_row("s5_plan_blocked_unreferenced"),
            _segment_row("s3_required_disconnected"),
            _segment_row("s4_directionality"),
            _segment_row("s4_required_ready"),
            _segment_row("s5_replaced_unreferenced"),
        ],
    )
    _write(
        run_root / "step1_identify_fusion_units" / "t06_swsd_segment_rejected.gpkg",
        [
            _segment_row("s2", reject_stage="before_evd", reject_reason="has_evd_not_yes"),
            _segment_row("s3", reject_stage="after_evd", reject_reason="is_anchor_not_eligible"),
        ],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_replaceable.gpkg",
        [
            _segment_row("s5", replacement_ready=True),
            _segment_row("s5_plan_blocked_unreferenced", replacement_ready=True),
            _segment_row("s5_replaced_unreferenced", replacement_ready=True),
        ],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_rejected.gpkg",
        [
            _segment_row("s4", reject_reason="required_semantic_nodes_not_connected_in_buffer"),
            _segment_row("s3", reject_reason="invalid_pair_relation_status"),
            _segment_row("s3_required_disconnected", reject_reason="required_semantic_nodes_not_connected_in_buffer"),
            _segment_row("s4_directionality", reject_reason="rcsd_not_bidirectional_for_swsd_dual"),
            _segment_row("s4_required_ready", reject_reason="required_semantic_nodes_not_connected_in_buffer"),
        ],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_segment_replacement_plan.gpkg",
        [
            _segment_row("s5", plan_status="ready", rcsd_road_ids='["rr5"]'),
            _segment_row("s4", plan_status="blocked", rcsd_road_ids='["rr4"]'),
            _segment_row(
                "s5_plan_blocked_unreferenced",
                plan_status="blocked",
                rcsd_road_ids='["different_road"]',
            ),
            _segment_row("s4_required_ready", plan_status="ready", rcsd_road_ids='["different_road"]'),
            _segment_row("s5_replaced_unreferenced", plan_status="ready", rcsd_road_ids='["different_road"]'),
        ],
    )
    _write(
        run_root / "step3_segment_replacement" / "t06_step3_replacement_units.gpkg",
        [_segment_row("s5", unit_status="failed", rcsd_road_ids='["rr5"]')],
    )
    _write(
        run_root / "step3_segment_replacement" / "t06_step3_swsd_frcsd_segment_relation.gpkg",
        [
            _segment_row("s5", relation_status="failed"),
            _segment_row("s5_replaced_unreferenced", relation_status="retained_swsd"),
        ],
    )
    _write(
        run_root / "step3_segment_replacement" / "t06_step3_unreplaced_rcsd_roads.gpkg",
        [
            _road("rr5", 0),
            _road("rr4", 100),
            _road("rr3", 200),
            _road("rr2", 300),
            _road("rr1", 1000),
            _road("rr_geo2", 400),
            _road("rr_mix", 500),
            _road("rr_plan_blocked_unreferenced", 600),
            _road("rr_required_disconnected", 700),
            _road("rr_directionality", 800),
            _road("rr_required_ready", 900),
            _road("rr_replaced_unreferenced", 1100),
        ],
    )
    (run_root / "step3_segment_replacement" / "t06_step3_summary.json").write_text(
        json.dumps({"outputs": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    match_call_count = 0
    original_match = attribution_module._match_roads_to_segment_metrics

    def counting_match(*args, **kwargs):
        nonlocal match_call_count
        match_call_count += 1
        return original_match(*args, **kwargs)

    monkeypatch.setattr(attribution_module, "_match_roads_to_segment_metrics", counting_match)

    artifacts = run_t06_rcsd_unreplaced_attribution(
        t06_run_root=run_root,
        swsd_segment_path=swsd_segment,
        rcsdroad_path=rcsdroad,
        audit_buffer_m=50.0,
    )

    assert match_call_count == 1
    rows = gpd.read_file(artifacts.attribution_gpkg_path)
    by_id = {row["id"]: row for _, row in rows.iterrows()}
    assert by_id["rr5"]["attribution_class"] == "5_replaceable_scope_unreplaced"
    assert by_id["rr5"]["attribution_subclass"] == "5_step3_failed"
    assert by_id["rr5"]["final_attribution_class"] == "5_replaceable_scope_unreplaced"
    assert by_id["rr5"]["final_attribution_subclass"] == "5_step3_failed"
    assert by_id["rr5"]["final_attribution_confidence"] == "exact"
    assert by_id["rr5"]["ppt_attribution_class"] == "1_segment_rcsd_quality_unreplaceable"
    assert by_id["rr4"]["attribution_class"] == "5_replaceable_scope_unreplaced"
    assert by_id["rr4"]["coarse_attribution_class"] == "5_replaceable_scope_unreplaced"
    assert by_id["rr4"]["final_attribution_class"] == "4_relation_scope_not_replaceable"
    assert by_id["rr4"]["final_attribution_confidence"] == "exact"
    assert by_id["rr3"]["attribution_class"] == "3_evidence_scope_relation_incomplete"
    assert by_id["rr3"]["attribution_subclass"] == "is_anchor_not_eligible"
    assert by_id["rr3"]["final_attribution_class"] == "3_evidence_scope_relation_incomplete"
    assert by_id["rr3"]["ppt_attribution_class"] == "2_segment_replacement_prerequisite_unsatisfied"
    assert by_id["rr2"]["attribution_class"] == "2_swsd_scope_no_t06_evidence"
    assert by_id["rr2"]["final_attribution_class"] == "2_swsd_scope_no_t06_evidence"
    assert by_id["rr2"]["ppt_attribution_class"] == "2_segment_replacement_prerequisite_unsatisfied"
    assert by_id["rr1"]["attribution_class"] == "1_outside_swsd_segment_scope"
    assert by_id["rr1"]["final_attribution_class"] == "1_outside_swsd_segment_scope"
    assert by_id["rr1"]["ppt_attribution_class"] == "3_rcsd_outside_segment_scope"
    assert by_id["rr_geo2"]["attribution_class"] == "4_relation_scope_not_replaceable"
    assert by_id["rr_geo2"]["final_attribution_class"] == "2_swsd_scope_no_t06_evidence"
    assert by_id["rr_geo2"]["final_primary_segment_id"] == "s2g"
    assert by_id["rr_mix"]["final_attribution_class"] == "2_swsd_scope_no_t06_evidence"
    assert by_id["rr_mix"]["final_attribution_subclass"] == "2_no_step1_effective_evidence"
    assert by_id["rr_mix"]["final_attribution_confidence"] == "low"
    assert by_id["rr_mix"]["ppt_attribution_class"] == "2_segment_replacement_prerequisite_unsatisfied"
    assert by_id["rr_mix"]["ppt_review_flag"] == "mixed_partial_segment_coverage"
    assert by_id["rr_plan_blocked_unreferenced"]["final_attribution_class"] == "5_replaceable_scope_unreplaced"
    assert by_id["rr_plan_blocked_unreferenced"]["final_attribution_subclass"] == "5_plan_blocked"
    assert by_id["rr_plan_blocked_unreferenced"]["final_attribution_confidence"] == "approximate"
    assert by_id["rr_replaced_unreferenced"]["final_attribution_class"] == (
        "6_unattributed_manual_audit_without_dominant_class"
    )
    assert by_id["rr_replaced_unreferenced"]["final_attribution_subclass"] == (
        "6_candidate_only_post_replacement_review"
    )
    assert by_id["rr_replaced_unreferenced"]["final_attribution_basis"] == "approx_candidate_only_after_segment_replaced"
    assert by_id["rr_replaced_unreferenced"]["ppt_attribution_class"] == "6_manual_audit"
    assert by_id["rr_replaced_unreferenced"]["ppt_review_flag"] == "candidate_only_post_replacement_review"
    assert by_id["rr_required_disconnected"]["final_attribution_class"] == "3_evidence_scope_relation_incomplete"
    assert by_id["rr_required_disconnected"]["final_attribution_subclass"] == "required_semantic_nodes_not_connected_in_buffer"
    assert by_id["rr_directionality"]["final_attribution_class"] == "4_relation_scope_not_replaceable"
    assert by_id["rr_directionality"]["final_attribution_subclass"] == "rcsd_not_bidirectional_for_swsd_dual"
    assert by_id["rr_required_ready"]["final_attribution_class"] == "4_relation_scope_not_replaceable"
    assert by_id["rr_required_ready"]["final_attribution_subclass"] == "required_semantic_nodes_not_connected_in_buffer"

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["total_rcsd_road_count"] == 12
    assert summary["raw_step3_unreplaced_rcsd_road_count"] == 12
    assert summary["unreplaced_rcsd_road_count"] == 12
    assert {item["value"]: item["count"] for item in summary["by_attribution_class"]} == {
        "1_outside_swsd_segment_scope": 1,
        "2_swsd_scope_no_t06_evidence": 1,
        "3_evidence_scope_relation_incomplete": 1,
        "4_relation_scope_not_replaceable": 4,
        "5_replaceable_scope_unreplaced": 5,
    }
    assert {item["value"]: item["count"] for item in summary["by_final_attribution_class"]} == {
        "1_outside_swsd_segment_scope": 1,
        "2_swsd_scope_no_t06_evidence": 3,
        "3_evidence_scope_relation_incomplete": 2,
        "4_relation_scope_not_replaceable": 3,
        "5_replaceable_scope_unreplaced": 2,
        "6_unattributed_manual_audit_without_dominant_class": 1,
    }
    assert {item["value"]: item["count"] for item in summary["by_ppt_attribution_class"]} == {
        "1_segment_rcsd_quality_unreplaceable": 5,
        "2_segment_replacement_prerequisite_unsatisfied": 5,
        "3_rcsd_outside_segment_scope": 1,
        "6_manual_audit": 1,
    }
    assert {item["value"]: item["count"] for item in summary["by_ppt_review_flag"]} == {
        "": 10,
        "candidate_only_post_replacement_review": 1,
        "mixed_partial_segment_coverage": 1,
    }
    patched_summary = json.loads(
        (run_root / "step3_segment_replacement" / "t06_step3_summary.json").read_text(encoding="utf-8")
    )
    assert "unreplaced_rcsd_attribution_gpkg" in patched_summary["outputs"]
    assert "rcsd_unreplaced_ppt_attribution_by_class" in patched_summary
    assert "rcsd_passed_review_count" not in patched_summary


def test_candidate_road_consumed_by_other_segment_is_not_unreplaced_for_target(tmp_path: Path) -> None:
    run_root = tmp_path / "t06_run"
    swsd_segment = _write(
        tmp_path / "segment.gpkg",
        [_segment("target", 0), _segment("other", 0, y=2)],
    )
    rcsdroad = _write(tmp_path / "rcsdroad_out.gpkg", [_road("rr_cross", 0)])

    _write(
        run_root / "step1_identify_fusion_units" / "t06_swsd_segment_candidates.gpkg",
        [_segment_row("target")],
    )
    _write(
        run_root / "step1_identify_fusion_units" / "t06_swsd_segment_final_fusion_units.gpkg",
        [_segment_row("target")],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_candidates.gpkg",
        [_segment_row("target", candidate_status="passed", candidate_rcsd_road_ids='["rr_cross"]')],
    )
    _write(
        run_root / "step3_segment_replacement" / "t06_step3_swsd_frcsd_segment_relation.gpkg",
        [_segment_row("target", relation_status="replaced")],
    )
    frcsd_road = _road("rr_cross", 0)
    frcsd_road["properties"]["t06_swsd_segment_ids"] = '["other"]'
    _write(run_root / "step3_segment_replacement" / "t06_frcsd_road.gpkg", [frcsd_road])
    (run_root / "step3_segment_replacement" / "t06_step3_summary.json").write_text(
        json.dumps({"outputs": {}}, ensure_ascii=False),
        encoding="utf-8",
    )

    artifacts = run_t06_rcsd_unreplaced_attribution(
        t06_run_root=run_root,
        swsd_segment_path=swsd_segment,
        rcsdroad_path=rcsdroad,
        audit_buffer_m=50.0,
    )

    rows = gpd.read_file(artifacts.attribution_gpkg_path)
    assert len(rows) == 0

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["raw_step3_unreplaced_rcsd_road_count"] == 0
    assert summary["unreplaced_rcsd_road_count"] == 0


def test_plan_road_missing_from_frcsd_is_added_to_unreplaced_attribution(tmp_path: Path) -> None:
    run_root = tmp_path / "t06_run"
    swsd_segment = _write(tmp_path / "segment.gpkg", [_segment("target", 0)])
    rcsdroad = _write(tmp_path / "rcsdroad_out.gpkg", [_road("rr_missing", 0)])

    _write(
        run_root / "step1_identify_fusion_units" / "t06_swsd_segment_candidates.gpkg",
        [_segment_row("target")],
    )
    _write(
        run_root / "step1_identify_fusion_units" / "t06_swsd_segment_final_fusion_units.gpkg",
        [_segment_row("target")],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_replaceable.gpkg",
        [_segment_row("target", replacement_ready=True)],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_segment_replacement_plan.gpkg",
        [_segment_row("target", plan_status="ready", rcsd_road_ids='["rr_missing"]')],
    )
    _write(
        run_root / "step3_segment_replacement" / "t06_step3_swsd_frcsd_segment_relation.gpkg",
        [_segment_row("target", relation_status="replaced")],
    )
    _write(run_root / "step3_segment_replacement" / "t06_frcsd_road.gpkg", [_road("rr_other", 100)])
    (run_root / "step3_segment_replacement" / "t06_step3_summary.json").write_text(
        json.dumps({"outputs": {}}, ensure_ascii=False),
        encoding="utf-8",
    )

    artifacts = run_t06_rcsd_unreplaced_attribution(
        t06_run_root=run_root,
        swsd_segment_path=swsd_segment,
        rcsdroad_path=rcsdroad,
        audit_buffer_m=50.0,
    )

    rows = gpd.read_file(artifacts.attribution_gpkg_path)
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["id"] == "rr_missing"
    assert row["final_attribution_subclass"] == "5_replaceable_scope_not_consumed"
    assert row["final_attribution_basis"] == "exact_plan_or_unit_road_missing_from_frcsd"


def test_plan_road_split_into_frcsd_is_not_added_to_unreplaced_attribution(tmp_path: Path) -> None:
    run_root = tmp_path / "t06_run"
    swsd_segment = _write(tmp_path / "segment.gpkg", [_segment("target", 0)])
    rcsdroad = _write(tmp_path / "rcsdroad_out.gpkg", [_road("rr_split_original", 0)])

    _write(
        run_root / "step1_identify_fusion_units" / "t06_swsd_segment_candidates.gpkg",
        [_segment_row("target")],
    )
    _write(
        run_root / "step1_identify_fusion_units" / "t06_swsd_segment_final_fusion_units.gpkg",
        [_segment_row("target")],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_replaceable.gpkg",
        [_segment_row("target", replacement_ready=True)],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_segment_replacement_plan.gpkg",
        [_segment_row("target", plan_status="ready", rcsd_road_ids='["rr_split_original"]')],
    )
    _write(
        run_root / "step3_segment_replacement" / "t06_step3_swsd_frcsd_segment_relation.gpkg",
        [_segment_row("target", relation_status="replaced")],
    )
    _write(
        run_root / "step3_segment_replacement" / "t06_frcsd_road.gpkg",
        [
            _road(
                "generated_split_1",
                0,
                t06_split_original_road_id="rr_split_original",
                t06_swsd_segment_ids='["target"]',
            )
        ],
    )
    (run_root / "step3_segment_replacement" / "t06_step3_summary.json").write_text(
        json.dumps({"outputs": {}}, ensure_ascii=False),
        encoding="utf-8",
    )

    artifacts = run_t06_rcsd_unreplaced_attribution(
        t06_run_root=run_root,
        swsd_segment_path=swsd_segment,
        rcsdroad_path=rcsdroad,
        audit_buffer_m=50.0,
    )

    rows = gpd.read_file(artifacts.attribution_gpkg_path)
    assert len(rows) == 0
