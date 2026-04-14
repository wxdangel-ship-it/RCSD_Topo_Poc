from __future__ import annotations

import rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_full_input_poc as full_input_module


def test_build_review_index_preserves_explicit_review_triad_with_late_cleanup_noise() -> None:
    row = {
        "case_id": "100",
        "case_dir": "E:/tmp/cases/100",
        "success": False,
        "flow_success": False,
        "acceptance_class": "review_required",
        "acceptance_reason": "selected_node_cover_partial_branch",
        "status": "stable",
        "root_cause_layer": "step4",
        "root_cause_type": "selected_node_cover_partial_branch",
        "visual_review_class": "V2 业务正确但几何待修",
        "representative_node_id": "100",
        "resolved_kind": 800,
        "kind_source": "kind",
        "kind_2": 2048,
        "official_review_eligible": True,
        "blocking_reason": None,
        "failure_bucket": None,
        "status_path": "E:/tmp/cases/100/t02_virtual_intersection_poc_status.json",
        "audit_path": "E:/tmp/cases/100/t02_virtual_intersection_poc_audit.json",
        "virtual_polygon_path": "E:/tmp/cases/100/virtual_intersection_polygon.gpkg",
        "rendered_map_png": "E:/tmp/cases/100/100.png",
        "counts": {
            "max_target_group_foreign_semantic_road_overlap_m": 0.0,
            "covered_extra_local_node_count": 2,
            "covered_extra_local_road_count": 1,
        },
        "late_single_sided_corridor_mask_cleanup_applied": True,
        "late_final_foreign_residue_trim_applied": True,
    }

    review_index = full_input_module._build_review_index(
        run_id="run",
        rows=[row],
        input_mode="full-input",
        input_paths={"nodes": "E:/tmp/nodes.gpkg"},
    )

    assert len(review_index) == 1
    assert review_index[0]["root_cause_layer"] == "step4"
    assert review_index[0]["root_cause_type"] == "selected_node_cover_partial_branch"
    assert review_index[0]["visual_review_class"] == "V2 业务正确但几何待修"
