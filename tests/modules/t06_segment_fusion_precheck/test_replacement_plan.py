from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import (
    build_problem_registry_rows,
    build_replacement_plan_rows,
)


def test_replacement_plan_combines_standard_group_and_special_rows() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": [1, 2],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                }
            )
        ],
        special_group_rows=[
            _feature(
                {
                    "special_junction_id": "j128",
                    "special_junction_type": "complex",
                    "gate_status": "passed",
                    "associated_segment_ids": ["s1", "s2"],
                    "replaceable_segment_ids": ["s1", "s2"],
                    "rcsd_junction_id": 900,
                    "rcsd_junction_node_ids": [900, 901],
                    "rcsd_junction_road_ids": ["rj"],
                }
            )
        ],
        group_replacement_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "group_probe_status": "passed",
                    "group_probe_repair_owner": "T06_path_corridor_group_replacement",
                    "group_probe_reason": "passed",
                    "group_probe_buffer_distance_m": 50.0,
                    "path_corridor_group_segment_ids": ["s1", "s2"],
                    "group_probe_rcsd_road_ids": ["rr1", "rr2"],
                    "swsd_pair_nodes": [2, 3],
                    "rcsd_pair_nodes": [20, 30],
                }
            )
        ],
        rcsd_roads=[
            _road("rr1", 10, 20),
            _road("rr2", 20, 30),
            _road("rj", 900, 901),
        ],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20", "30", "900", "901"})),
    )

    scopes = [row["properties"]["execution_scope"] for row in rows]
    assert scopes == ["standard_segment", "path_corridor_group", "special_junction_group_internal"]
    group = [row for row in rows if row["properties"]["execution_scope"] == "path_corridor_group"][0]["properties"]
    assert group["rcsd_road_ids"] == ["rr1", "rr2"]
    assert group["retained_node_ids"] == ["10", "20", "30"]


def test_replacement_plan_adds_pair_anchor_bridge_roads_to_standard_plan() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_bridge",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["10", "20"],
                    "rcsd_road_ids": ["rr_main"],
                    "retained_node_ids": ["10", "20"],
                }
            )
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_bridge",
                    "failure_business_category": "pair_anchor_mismatch",
                    "pair_anchor_bridge_road_ids": ["rr_bridge"],
                    "pair_anchor_bridge_length_m": 27.8,
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[
            _road("rr_main", 10, 20),
            _road("rr_bridge", 30, 10),
        ],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20", "30"})),
    )

    props = rows[0]["properties"]
    assert props["rcsd_road_ids"] == ["rr_main", "rr_bridge"]
    assert props["retained_node_ids"] == ["10", "20", "30"]
    assert props["pair_anchor_bridge_road_ids"] == ["rr_bridge"]
    assert props["pair_anchor_bridge_length_m"] == 27.8
    assert props["risk_flags"] == ["pair_anchor_bridge_roads_added"]


def test_replacement_plan_excludes_blocked_path_corridor_segments() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[],
        special_group_rows=[],
        group_replacement_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "group_probe_status": "passed",
                    "group_probe_repair_owner": "T06_path_corridor_group_replacement",
                    "group_probe_reason": "passed",
                    "group_probe_buffer_distance_m": 50.0,
                    "path_corridor_group_segment_ids": ["s1", "s2", "s3"],
                    "path_corridor_blocked_segment_ids": ["s1", "s3"],
                    "group_probe_rcsd_road_ids": ["rr1", "rr2"],
                    "swsd_pair_nodes": [1, 2],
                    "rcsd_pair_nodes": [10, 20],
                }
            )
        ],
        rcsd_roads=[_road("rr1", 10, 15), _road("rr2", 15, 20)],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "15", "20"})),
    )

    assert len(rows) == 1
    props = rows[0]["properties"]
    assert props["execution_scope"] == "path_corridor_group"
    assert props["group_segment_ids"] == ["s2"]


def test_replacement_plan_blocks_group_when_probe_buffer_is_too_wide() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[],
        special_group_rows=[],
        group_replacement_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_wide",
                    "group_probe_status": "passed",
                    "group_probe_repair_owner": "T06_path_corridor_group_replacement",
                    "group_probe_reason": "passed",
                    "group_probe_buffer_distance_m": 150.0,
                    "path_corridor_group_segment_ids": ["s_wide", "s_peer"],
                    "group_probe_rcsd_road_ids": ["rr1", "rr2"],
                    "swsd_pair_nodes": [1, 2],
                    "rcsd_pair_nodes": [10, 20],
                }
            )
        ],
        rcsd_roads=[_road("rr1", 10, 15), _road("rr2", 15, 20)],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "15", "20"})),
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "blocked"
    assert props["execution_action"] == "hold"
    assert props["source_reason"] == "group_probe_buffer_exceeds_topology_connectivity_gate"
    assert props["risk_flags"] == [
        "group_path_corridor_replacement",
        "group_probe_buffer_exceeds_topology_connectivity_gate",
    ]


def test_replacement_plan_adds_high_confidence_single_visual_repair() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[],
        rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual",
                    "swsd_sgrade": "0-1单",
                    "swsd_directionality": "single",
                    "junc_kind2_exempt_nodes": ["j1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s_manual",
                    "swsd_sgrade": "0-1单",
                    "swsd_directionality": "single",
                }
            ),
        ],
        buffer_rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual",
                    "reject_reason": "swsd_visual_continuity_not_covered_by_retained_rcsd",
                    "full_graph_status": "required_nodes_connected",
                    "candidate_graph_status": "required_nodes_connected",
                    "directional_status": "full=directed_path_present;candidate=directed_path_present",
                    "missing_required_node_ids": [],
                    "unexpected_endpoint_node_ids": [],
                    "unexpected_mapped_semantic_node_ids": [],
                    "retained_road_count": 2,
                    "retained_rcsd_road_ids": ["rr1", "rr2"],
                    "retained_node_ids": ["r1", "r2", "r3"],
                    "required_rcsd_nodes": ["r1", "r3"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s_manual",
                    "reject_reason": "swsd_visual_continuity_not_covered_by_retained_rcsd",
                    "full_graph_status": "required_nodes_connected",
                    "candidate_graph_status": "required_nodes_connected",
                    "directional_status": "full=directed_path_present;candidate=directed_path_present",
                    "retained_road_count": 2,
                    "retained_rcsd_road_ids": ["rr3", "rr4"],
                    "retained_node_ids": ["r3", "r4"],
                }
            ),
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual",
                    "swsd_pair_nodes": ["a", "b"],
                    "swsd_junc_nodes": ["j1"],
                    "rcsd_pair_nodes": ["r1", "r3"],
                    "repair_recommendation": "high_confidence_pair_anchor_candidate",
                    "manual_review_required": False,
                    "candidate_score": 0.9,
                    "directionality_score": 1.0,
                    "connectivity_score": 1.0,
                    "shape_similarity_score": 1.0,
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s_manual",
                    "repair_recommendation": "manual_review_required",
                    "manual_review_required": True,
                    "candidate_score": 0.95,
                    "directionality_score": 1.0,
                    "connectivity_score": 1.0,
                    "shape_similarity_score": 1.0,
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    assert len(rows) == 1
    props = rows[0]["properties"]
    assert props["replacement_plan_id"] == "visual_consistency:s_visual"
    assert props["replacement_strategy"] == "visual_consistency_high_confidence_repair"
    assert props["rcsd_road_ids"] == ["rr1", "rr2"]
    assert props["swsd_pair_nodes"] == ["a", "b"]
    assert props["junc_kind2_exempt_nodes"] == ["j1"]


def test_replacement_plan_rejects_low_overlap_visual_repair() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[],
        rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual",
                    "swsd_directionality": "single",
                }
            )
        ],
        buffer_rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual",
                    "reject_reason": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "full_graph_status": "required_nodes_connected",
                    "candidate_graph_status": "required_nodes_connected",
                    "directional_status": "full=directed_path_present;candidate=directed_path_present",
                    "missing_required_node_ids": [],
                    "unexpected_endpoint_node_ids": [],
                    "unexpected_mapped_semantic_node_ids": [],
                    "retained_road_count": 2,
                    "retained_rcsd_road_ids": ["rr1", "rr2"],
                    "retained_node_ids": ["r1", "r2"],
                }
            )
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual",
                    "repair_recommendation": "high_confidence_pair_anchor_candidate",
                    "manual_review_required": False,
                    "geometry_overlap_ratio": 0.64,
                    "candidate_score": 0.95,
                    "directionality_score": 1.0,
                    "connectivity_score": 1.0,
                    "shape_similarity_score": 1.0,
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    assert rows == []


def test_replacement_plan_blocks_reverse_of_rejected_swsd_pair() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "a_b",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["ra", "rb"],
                    "rcsd_road_ids": ["rr_forward"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "b_a",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["b", "a"],
                    "rcsd_pair_nodes": ["rb", "ra"],
                    "rcsd_road_ids": ["rr_reverse"],
                }
            ),
        ],
        rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "a_b_rejected",
                    "reject_reason": "retained_geometry_buffer_coverage_mismatch",
                    "failed_pair_nodes": ["a", "b"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["a_b"]["plan_status"] == "ready"
    assert by_segment["a_b"]["execution_action"] == "replace"
    assert by_segment["b_a"]["plan_status"] == "blocked"
    assert by_segment["b_a"]["execution_action"] == "hold"
    assert by_segment["b_a"]["risk_flags"] == ["reverse_retained_swsd_pair_blocked"]
    assert by_segment["b_a"]["upstream_owner"] == "T06_reverse_pair_consistency"
    assert by_segment["b_a"]["source_reason"] == "retained_geometry_buffer_coverage_mismatch"


def test_replacement_plan_does_not_block_reverse_of_covered_replaceable_audit() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "a_b",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["ra", "rb"],
                    "rcsd_road_ids": ["rr_forward"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "b_a",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["b", "a"],
                    "rcsd_pair_nodes": ["rb", "ra"],
                    "rcsd_road_ids": ["rr_reverse"],
                }
            ),
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "a_b",
                    "segment_outcome": "replaceable",
                    "auto_fix_candidate": True,
                    "reject_reason": "required_semantic_nodes_not_connected_in_buffer",
                    "swsd_pair_nodes": ["a", "b"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["a_b"]["plan_status"] == "ready"
    assert by_segment["b_a"]["plan_status"] == "ready"
    assert by_segment["b_a"]["execution_action"] == "replace"


def test_replacement_plan_blocks_standard_segment_when_adaptive_buffer_is_too_wide() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_wide",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["ra", "rb"],
                    "rcsd_road_ids": ["rr_wide"],
                    "adaptive_buffer_distance_m": 100.0,
                    "adaptive_buffer_source_reason": "single_graph_retry:swsd_geometry_not_covered_by_retained_rcsd",
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "blocked"
    assert props["execution_action"] == "hold"
    assert props["source_reason"] == "adaptive_buffer_exceeds_topology_connectivity_gate"
    assert props["risk_flags"] == ["adaptive_buffer_exceeds_topology_connectivity_gate"]


def test_replacement_plan_marks_mapping_far_from_retained_incident_segment() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_replace",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r_far", "r2"],
                    "rcsd_road_ids": ["rr1"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "s_replace", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s_retained", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[_node("r_far", 30, 0), _node("r2", 10, 0)],
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert props["risk_flags"] == ["junction_alignment_to_retained_swsd_exceeds_topology_gate"]
    assert "risk: junction_alignment_to_retained_swsd_exceeds_topology_gate" in props["notes"]


def test_replacement_plan_blocks_replacement_plans_mapping_same_junction_to_diverged_rcsd_nodes() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r1", "r2"],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "rcsd_pair_nodes": ["r3", "r4"],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "s1", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s2", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[_node("r1", 0, 0), _node("r2", 10, 0), _node("r3", 10, 0), _node("r4", 0, 10)],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s1"]["plan_status"] == "blocked"
    assert by_segment["s2"]["plan_status"] == "blocked"
    assert by_segment["s1"]["source_reason"] == "junction_alignment_between_replacement_plans_diverged"
    assert by_segment["s2"]["source_reason"] == "junction_alignment_between_replacement_plans_diverged"


def test_replacement_plan_keeps_diverged_junction_ready_when_pair_anchor_bridge_connects_nodes() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "rcsd_pair_nodes": [30, 40],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "failure_business_category": "pair_anchor_mismatch",
                    "pair_anchor_bridge_road_ids": ["rr_bridge"],
                    "pair_anchor_bridge_length_m": 12.0,
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[
            _road("rr1", 10, 20),
            _road("rr2", 30, 40),
            _road("rr_bridge", 10, 30),
        ],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20", "30", "40"})),
        swsd_segments=[
            _feature({"id": "s1", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s2", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[_node("10", 0, 0), _node("20", 10, 0), _node("30", 10, 0), _node("40", 0, 10)],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s1"]["plan_status"] == "ready"
    assert by_segment["s2"]["plan_status"] == "ready"
    assert "junction_alignment_between_replacement_plans_connected_by_pair_anchor_bridge" in by_segment["s1"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_connected_by_pair_anchor_bridge" in by_segment["s2"]["risk_flags"]


def test_problem_registry_marks_plan_covered_and_upstream_required_segments() -> None:
    plan_rows = [
        _feature(
            {
                "plan_status": "ready",
                "execution_action": "replace",
                "execution_scope": "path_corridor_group",
                "source_artifact": "t06_segment_replacement_plan",
                "group_segment_ids": ["s1", "s2"],
            }
        )
    ]
    rows = build_problem_registry_rows(
        rejected_rows=[
            _feature({"swsd_segment_id": "s3", "reject_reason": "missing_pair_relation", "failed_pair_nodes": [3, 4]})
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "segment_outcome": "rejected",
                    "reject_reason": "rcsd_directed_path_missing",
                    "failure_business_category": "directionality_mismatch_fixable",
                    "upstream_issue_owner": "T03/T04/T05_or_T06_group_replacement",
                    "swsd_pair_nodes": [2, 3],
                    "rcsd_pair_nodes": [20, 30],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s4",
                    "segment_outcome": "rejected",
                    "reject_reason": "rcsd_pair_nodes_not_distinct",
                    "failure_business_category": "multi_anchor_ambiguous",
                    "upstream_issue_owner": "T05",
                    "manual_review_required": True,
                    "swsd_pair_nodes": [4, 5],
                    "rcsd_pair_nodes": [40, 40],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s5",
                    "segment_outcome": "rejected",
                    "reject_reason": "rcsd_not_bidirectional_for_swsd_dual",
                    "root_cause_category": "full_rcsd_graph_one_direction_only",
                    "failure_business_category": "directionality_mismatch_fixable",
                    "upstream_issue_owner": "T03/T04/T05_or_T06_group_replacement",
                    "manual_review_required": True,
                    "swsd_pair_nodes": [5, 6],
                    "rcsd_pair_nodes": [50, 60],
                    "candidate_rcsd_pair_node_sets": [[50, 60], [51, 61]],
                    "pair_anchor_error_swsd_nodes": [6],
                    "pair_anchor_error_original_rcsd_nodes": [60],
                    "pair_anchor_error_candidate_rcsd_nodes": [61],
                    "pair_anchor_endpoint_cluster_nodes": [[50], [61]],
                    "pair_anchor_bridge_road_ids": ["rr_bridge"],
                    "pair_anchor_bridge_length_m": 6.5,
                    "pair_anchor_diagnostic_source": "buffer_only_candidate_pair",
                    "pair_anchor_diagnostic_reason": "candidate_anchor_mismatch",
                }
            )
        ],
        replacement_plan_rows=plan_rows,
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s2"]["problem_status"] == "covered_by_replacement_plan"
    assert by_segment["s2"]["recommended_module"] == "T03/T04/T05"
    assert by_segment["s3"]["problem_status"] == "requires_upstream_iteration"
    assert by_segment["s3"]["recommended_module"] == "T03/T04/T05"
    assert by_segment["s4"]["problem_status"] == "accepted_non_replaceable"
    assert by_segment["s4"]["recommended_module"] == "T06"
    assert by_segment["s4"]["feedback_action"] == "record_as_t06_non_replaceable_no_upstream_rerun"
    assert by_segment["s4"]["replan_trigger"] == "no_current_rerun_required"
    assert by_segment["s4"]["manual_review_required"] is False
    assert by_segment["s5"]["problem_status"] == "requires_upstream_side_group_or_rcsd_directionality_review"
    assert by_segment["s5"]["upstream_issue_owner"] == "T03/T04/T05_or_RCSD_directionality_review"
    assert by_segment["s5"]["recommended_module"] == "T03/T04/T05_or_RCSD_source_review"
    assert by_segment["s5"]["feedback_action"] == "evaluate_T03_T04_T05_side_grouping_before_rcsd_directionality_data_review"
    assert by_segment["s5"]["replan_trigger"] == "upstream_module_rerun_required"
    assert by_segment["s5"]["manual_review_required"] is True
    assert by_segment["s5"]["pair_anchor_endpoint_cluster_nodes"] == [[50], [61]]
    assert by_segment["s5"]["pair_anchor_error_swsd_nodes"] == ["6"]
    assert by_segment["s5"]["pair_anchor_error_candidate_rcsd_nodes"] == ["61"]
    assert by_segment["s5"]["pair_anchor_bridge_road_ids"] == ["rr_bridge"]
    assert by_segment["s5"]["pair_anchor_bridge_length_m"] == 6.5
    assert by_segment["s5"]["pair_anchor_diagnostic_source"] == "buffer_only_candidate_pair"
    assert by_segment["s5"]["pair_anchor_diagnostic_reason"] == "candidate_anchor_mismatch"


def _feature(properties: dict) -> dict:
    return {"properties": properties, "geometry": LineString([(0, 0), (1, 0)])}


def _road(road_id: str, snode: int, enode: int) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snode, "enodeid": enode},
        "geometry": LineString([(snode, 0), (enode, 0)]),
    }


def _node(node_id: str, x: float, y: float) -> dict:
    return {"properties": {"id": node_id}, "geometry": Point(x, y)}
