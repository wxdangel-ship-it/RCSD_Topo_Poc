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


def _road(road_id: str, x0: float, y: float = 1.0) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": f"{road_id}_s",
            "enodeid": f"{road_id}_e",
            "direction": 0,
            "source": 1,
            "length_m": 10.0,
        },
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
        [_segment_row("s5", replacement_ready=True)],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_rejected.gpkg",
        [
            _segment_row("s4", reject_reason="required_semantic_nodes_not_connected_in_buffer"),
            _segment_row("s3", reject_reason="invalid_pair_relation_status"),
        ],
    )
    _write(
        run_root / "step2_extract_rcsd_segments" / "t06_segment_replacement_plan.gpkg",
        [
            _segment_row("s5", plan_status="ready", rcsd_road_ids='["rr5"]'),
            _segment_row("s4", plan_status="blocked", rcsd_road_ids='["rr4"]'),
        ],
    )
    _write(
        run_root / "step3_segment_replacement" / "t06_step3_replacement_units.gpkg",
        [_segment_row("s5", unit_status="failed", rcsd_road_ids='["rr5"]')],
    )
    _write(
        run_root / "step3_segment_replacement" / "t06_step3_swsd_frcsd_segment_relation.gpkg",
        [_segment_row("s5", relation_status="failed")],
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
    assert by_id["rr3"]["ppt_attribution_class"] == "2_segment_relation_not_satisfied"
    assert by_id["rr2"]["attribution_class"] == "2_swsd_scope_no_t06_evidence"
    assert by_id["rr2"]["final_attribution_class"] == "2_swsd_scope_no_t06_evidence"
    assert by_id["rr1"]["attribution_class"] == "1_outside_swsd_segment_scope"
    assert by_id["rr1"]["final_attribution_class"] == "1_outside_swsd_segment_scope"
    assert by_id["rr1"]["ppt_attribution_class"] == "3_rcsd_outside_segment_scope"
    assert by_id["rr_geo2"]["attribution_class"] == "4_relation_scope_not_replaceable"
    assert by_id["rr_geo2"]["final_attribution_class"] == "2_swsd_scope_no_t06_evidence"
    assert by_id["rr_geo2"]["final_primary_segment_id"] == "s2g"
    assert by_id["rr_mix"]["final_attribution_class"] == "2_swsd_scope_no_t06_evidence"
    assert by_id["rr_mix"]["final_attribution_subclass"] == "2_no_step1_effective_evidence"
    assert by_id["rr_mix"]["final_attribution_confidence"] == "low"
    assert by_id["rr_mix"]["ppt_attribution_class"] == "1_segment_rcsd_quality_unreplaceable"
    assert by_id["rr_mix"]["ppt_review_flag"] == "mixed_partial_segment_coverage"

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["total_rcsd_road_count"] == 7
    assert summary["unreplaced_rcsd_road_count"] == 7
    assert {item["value"]: item["count"] for item in summary["by_attribution_class"]} == {
        "1_outside_swsd_segment_scope": 1,
        "2_swsd_scope_no_t06_evidence": 1,
        "3_evidence_scope_relation_incomplete": 1,
        "4_relation_scope_not_replaceable": 2,
        "5_replaceable_scope_unreplaced": 2,
    }
    assert {item["value"]: item["count"] for item in summary["by_final_attribution_class"]} == {
        "1_outside_swsd_segment_scope": 1,
        "2_swsd_scope_no_t06_evidence": 3,
        "3_evidence_scope_relation_incomplete": 1,
        "4_relation_scope_not_replaceable": 1,
        "5_replaceable_scope_unreplaced": 1,
    }
    assert {item["value"]: item["count"] for item in summary["by_ppt_attribution_class"]} == {
        "1_segment_rcsd_quality_unreplaceable": 5,
        "2_segment_relation_not_satisfied": 1,
        "3_rcsd_outside_segment_scope": 1,
    }
    patched_summary = json.loads(
        (run_root / "step3_segment_replacement" / "t06_step3_summary.json").read_text(encoding="utf-8")
    )
    assert "unreplaced_rcsd_attribution_gpkg" in patched_summary["outputs"]
    assert "rcsd_unreplaced_ppt_attribution_by_class" in patched_summary
