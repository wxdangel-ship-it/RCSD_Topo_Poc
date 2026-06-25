from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import (
    build_problem_registry_rows,
    build_replacement_plan_rows,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_aware_plan_release import (
    _points_by_id,
    _release_allowed,
    _rollback_plan_ids_for_failed_segments,
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


def test_replacement_plan_blocks_group_when_member_standard_plan_is_blocked() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_member",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": [1, 2],
                    "rcsd_road_ids": ["rr_member"],
                    "adaptive_buffer_distance_m": [100.0],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_group",
                    "group_probe_status": "passed",
                    "group_probe_repair_owner": "T06_path_corridor_group_replacement",
                    "group_probe_reason": "passed",
                    "group_probe_buffer_distance_m": 50.0,
                    "path_corridor_group_segment_ids": ["s_member", "s_group"],
                    "group_probe_rcsd_road_ids": ["rr_group"],
                    "swsd_pair_nodes": ["a", "c"],
                    "rcsd_pair_nodes": [1, 3],
                }
            )
        ],
        rcsd_roads=[_road("rr_member", 1, 2), _road("rr_group", 1, 3)],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"1", "2", "3"})),
    )

    by_id = {row["properties"]["replacement_plan_id"]: row["properties"] for row in rows}
    standard = by_id["standard:s_member"]
    group = by_id["group_path_corridor:s_group"]
    assert standard["plan_status"] == "blocked"
    assert group["plan_status"] == "blocked"
    assert group["execution_action"] == "hold"
    assert group["source_reason"] == "group_member_replacement_plan_blocked"
    assert "group_member_replacement_plan_blocked" in group["risk_flags"]
    assert "adaptive_buffer_exceeds_topology_connectivity_gate" in group["risk_flags"]
    assert "blocked_group_member_segments=['s_member']" in group["notes"]


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
        rcsd_roads=[_road("rr_visual", 1, 2, [(0, 30), (100, 30)])],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[_feature({"id": "s_visual_gap"}, LineString([(0, 0), (100, 0)]))],
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
                    "reject_reason": "swsd_visual_continuity_not_covered_by_retained_rcsd",
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


def test_replacement_plan_controlled_releases_retained_visual_outside_for_dual_segment() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[],
        rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual_dual",
                    "swsd_sgrade": "0-2双",
                    "swsd_directionality": "dual",
                }
            )
        ],
        buffer_rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual_dual",
                    "reject_reason": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "full_graph_status": "required_nodes_connected",
                    "candidate_graph_status": "required_nodes_connected",
                    "directional_status": "full=bidirectional;candidate=bidirectional",
                    "missing_required_node_ids": [],
                    "unexpected_endpoint_node_ids": [],
                    "unexpected_mapped_semantic_node_ids": [],
                    "retained_road_count": 1,
                    "retained_rcsd_road_ids": ["rr_visual"],
                    "retained_node_ids": ["r1", "r2"],
                    "required_rcsd_nodes": ["r1", "r2"],
                    "swsd_uncovered_by_rcsd_length_m": 0.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.0,
                }
            )
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual_dual",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["r1", "r2"],
                    "repair_recommendation": "manual_review_required",
                    "manual_review_required": True,
                    "candidate_score": 0.5,
                    "directionality_score": 0.5,
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

    assert len(rows) == 1
    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert props["replacement_strategy"] == "visual_consistency_controlled_release"
    assert props["rcsd_road_ids"] == ["rr_visual"]
    assert props["risk_flags"] == [
        "visual_consistency_controlled_release",
        "retained_geometry_outside_swsd_visual_consistency_scope",
        "manual_review_required",
    ]


def test_replacement_plan_does_not_control_release_when_swsd_remains_uncovered() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[],
        rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_gap",
                    "swsd_directionality": "dual",
                }
            )
        ],
        buffer_rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_gap",
                    "reject_reason": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "full_graph_status": "required_nodes_connected",
                    "candidate_graph_status": "required_nodes_connected",
                    "directional_status": "full=bidirectional;candidate=bidirectional",
                    "missing_required_node_ids": [],
                    "unexpected_endpoint_node_ids": [],
                    "unexpected_mapped_semantic_node_ids": [],
                    "retained_road_count": 2,
                    "retained_rcsd_road_ids": ["rr1", "rr2"],
                    "retained_node_ids": ["r1", "r2"],
                    "swsd_uncovered_by_rcsd_length_m": 25.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.25,
                }
            )
        ],
        failure_business_audit_rows=[],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    assert rows == []


def test_replacement_plan_releases_visual_outside_when_anchors_and_connectivity_pass() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[],
        rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_gap_release",
                    "swsd_directionality": "dual",
                }
            )
        ],
        buffer_rejected_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_gap_release",
                    "reject_reason": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "full_graph_status": "required_nodes_connected",
                    "candidate_graph_status": "required_nodes_connected",
                    "directional_status": "full=bidirectional;candidate=bidirectional",
                    "missing_required_node_ids": [],
                    "unexpected_endpoint_node_ids": [],
                    "unexpected_mapped_semantic_node_ids": [],
                    "retained_road_count": 2,
                    "retained_rcsd_road_ids": ["rr1", "rr2"],
                    "retained_node_ids": ["r1", "r2"],
                    "required_rcsd_nodes": ["r1", "r2"],
                    "swsd_uncovered_by_rcsd_length_m": 25.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.25,
                }
            )
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_gap_release",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["r1", "r2"],
                    "manual_review_required": False,
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    assert len(rows) == 1
    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert props["source_reason"] == "visual_consistency_manual_audit_release"
    assert "visual_consistency_outside_manual_audit" in props["risk_flags"]
    assert "manual_review_required" in props["risk_flags"]
    assert "no_formal_trunk_road_conflict" in props["risk_flags"]


def test_visual_consistency_controlled_release_does_not_compete_with_primary_road_plan() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "primary",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["p1", "p2"],
                    "rcsd_pair_nodes": ["r1", "r2"],
                    "rcsd_road_ids": ["rr_shared"],
                    "retained_node_ids": ["r1", "r2"],
                }
            )
        ],
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
                    "retained_rcsd_road_ids": ["rr_shared", "rr_visual"],
                    "retained_node_ids": ["r2", "r3"],
                    "swsd_uncovered_by_rcsd_length_m": 0.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.0,
                }
            )
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["r2", "r3"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[_road("rr_visual", 1, 2, [(0, 30), (100, 30)])],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[_feature({"id": "s_visual_gap"}, LineString([(0, 0), (100, 0)]))],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["primary"]["plan_status"] == "ready"
    assert by_segment["s_visual"]["plan_status"] == "blocked"
    assert by_segment["s_visual"]["execution_action"] == "hold"
    assert by_segment["s_visual"]["source_reason"] == "visual_consistency_road_conflict_with_primary_replacement_plan"
    assert "visual_consistency_road_conflict_with_primary_replacement_plan" in by_segment["s_visual"]["risk_flags"]
    assert "conflict_rcsd_road_ids=['rr_shared']" in by_segment["s_visual"]["notes"]


def test_visual_consistency_member_does_not_conflict_with_own_path_group_plan() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_member",
                    "replacement_strategy": "buffer_segment_extraction",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "swsd_uncovered_by_rcsd_length_m": 0.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.0,
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["10", "20"],
                    "rcsd_road_ids": ["rr_member"],
                    "retained_node_ids": ["10", "20"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_group",
                    "group_probe_status": "passed",
                    "group_probe_repair_owner": "T06_path_corridor_group_replacement",
                    "group_probe_reason": "passed",
                    "group_probe_buffer_distance_m": 50.0,
                    "path_corridor_group_segment_ids": ["s_group", "s_member"],
                    "group_probe_rcsd_road_ids": ["rr_member"],
                    "swsd_pair_nodes": ["g1", "g2"],
                    "rcsd_pair_nodes": ["10", "20"],
                }
            )
        ],
        rcsd_roads=[_road("rr_member", 10, 20, [(0, 0), (100, 0)])],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20"})),
        swsd_segments=[_feature({"id": "s_member"}, LineString([(0, 0), (100, 0)]))],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s_member"]["plan_status"] == "ready"
    assert by_segment["s_member"]["execution_action"] == "replace"
    assert by_segment["s_group"]["plan_status"] == "ready"
    assert "visual_consistency_same_path_group_member_conflict_accepted" in by_segment["s_member"]["risk_flags"]
    assert "accepted_same_path_group_member_rcsd_road_ids=['rr_member']" in by_segment["s_member"]["notes"]
    assert "visual_consistency_road_conflict_with_primary_replacement_plan" not in by_segment["s_member"]["risk_flags"]


def test_visual_consistency_prunes_junction_local_connector_conflict() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "primary",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["p1", "p2"],
                    "rcsd_pair_nodes": ["10", "11"],
                    "rcsd_road_ids": ["rr_connector"],
                    "retained_node_ids": ["10", "11"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "visual",
                    "replacement_strategy": "buffer_segment_extraction",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "swsd_uncovered_by_rcsd_length_m": 0.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.0,
                    "swsd_pair_nodes": ["a", "b"],
                    "swsd_junc_nodes": ["j1"],
                    "rcsd_pair_nodes": ["20", "21"],
                    "rcsd_junc_nodes": ["10"],
                    "rcsd_road_ids": ["rr_body", "rr_connector"],
                    "retained_node_ids": ["20", "21", "10"],
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[_road("rr_connector", 10, 11), _road("rr_body", 20, 21)],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "11", "20", "21"})),
        swsd_segments=[_feature({"id": "visual", "pair_nodes": ["a", "b"], "junc_nodes": ["j1"]})],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["visual"]["plan_status"] == "ready"
    assert by_segment["visual"]["rcsd_road_ids"] == ["rr_body"]
    assert "visual_consistency_junction_connector_conflict_pruned" in by_segment["visual"]["risk_flags"]
    assert "pruned_junction_local_conflict_rcsd_road_ids=['rr_connector']" in by_segment["visual"]["notes"]


def test_visual_consistency_prunes_primary_body_conflict_when_junction_context_still_connected() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "primary",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["p1", "p2"],
                    "rcsd_pair_nodes": ["301", "302"],
                    "rcsd_road_ids": ["rr_primary_body"],
                    "retained_node_ids": ["301", "302"],
                },
                LineString([(60, 20), (100, 20)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "visual",
                    "replacement_strategy": "buffer_segment_extraction",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "swsd_uncovered_by_rcsd_length_m": 0.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.0,
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["101", "102"],
                    "rcsd_road_ids": ["rr_visual_a", "rr_visual_b", "rr_primary_body"],
                    "retained_node_ids": ["101", "150", "102", "301", "302"],
                },
                LineString([(0, 0), (100, 0)]),
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[
            _road("rr_visual_a", 101, 150, [(0, 0), (50, 0)]),
            _road("rr_visual_b", 150, 102, [(50, 0), (100, 0)]),
            _road("rr_primary_body", 301, 302, [(60, 20), (100, 20)]),
        ],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"101", "102", "150", "301", "302"})),
        swsd_segments=[
            _feature({"id": "primary"}, LineString([(60, 20), (100, 20)])),
            _feature({"id": "visual"}, LineString([(0, 0), (100, 0)])),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["primary"]["plan_status"] == "ready"
    assert by_segment["visual"]["plan_status"] == "ready"
    assert by_segment["visual"]["execution_action"] == "replace"
    assert by_segment["visual"]["rcsd_road_ids"] == ["rr_visual_a", "rr_visual_b"]
    assert "301" not in by_segment["visual"]["retained_node_ids"]
    assert "302" not in by_segment["visual"]["retained_node_ids"]
    assert "visual_consistency_primary_body_conflict_pruned_to_junction_context" in by_segment["visual"]["risk_flags"]
    assert "pruned_primary_body_conflict_rcsd_road_ids=['rr_primary_body']" in by_segment["visual"]["notes"]
    assert "visual_consistency_road_conflict_with_primary_replacement_plan" not in by_segment["visual"]["risk_flags"]


def test_standard_visual_consistency_high_deviation_requires_manual_review() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual_high",
                    "replacement_strategy": "buffer_segment_extraction",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "rcsd_outside_swsd_buffer_ratio": 0.62,
                    "swsd_uncovered_by_rcsd_ratio": 0.7,
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["r1", "r2"],
                    "rcsd_road_ids": ["rr_visual"],
                    "retained_node_ids": ["r1", "r2"],
                }
            )
        ],
        rejected_rows=[],
        buffer_rejected_rows=[],
        failure_business_audit_rows=[],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert props["source_reason"] == "visual_consistency_manual_audit_release"
    assert props["replacement_strategy"] == "visual_consistency_controlled_release"
    assert "visual_consistency_high_deviation" in props["risk_flags"]
    assert "visual_consistency_outside_manual_audit" in props["risk_flags"]
    assert "manual_review_required" in props["risk_flags"]
    assert "no_formal_trunk_road_conflict" in props["risk_flags"]


def test_standard_visual_consistency_release_manual_audits_when_swsd_coverage_gap_exceeds_gate() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_visual_gap",
                    "replacement_strategy": "buffer_segment_extraction",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "rcsd_outside_swsd_buffer_ratio": 0.05,
                    "swsd_uncovered_by_rcsd_length_m": 25.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.2,
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["r1", "r2"],
                    "rcsd_road_ids": ["rr_visual"],
                    "retained_node_ids": ["r1", "r2"],
                }
            )
        ],
        rejected_rows=[],
        buffer_rejected_rows=[],
        failure_business_audit_rows=[],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[_road("rr_visual", 1, 2, [(0, 30), (100, 30)])],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[_feature({"id": "s_visual_gap"}, LineString([(0, 0), (100, 0)]))],
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert props["source_reason"] == "visual_consistency_manual_audit_release"
    assert props["replacement_strategy"] == "visual_consistency_controlled_release"
    assert "retained_geometry_outside_swsd_visual_consistency_scope" in props["risk_flags"]
    assert "visual_consistency_outside_manual_audit" in props["risk_flags"]
    assert "manual_review_required" in props["risk_flags"]
    assert "no_formal_trunk_road_conflict" in props["risk_flags"]
    assert "visual_outside_swsd_buffer_road_ids=['rr_visual']" in props["notes"]


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
    assert props["plan_status"] == "blocked"
    assert props["execution_action"] == "hold"
    assert props["source_reason"] == "junction_alignment_to_retained_swsd_exceeds_topology_gate"
    assert props["risk_flags"] == ["junction_alignment_to_retained_swsd_exceeds_topology_gate"]
    assert "blocked by junction_alignment_to_retained_swsd_exceeds_topology_gate" in props["notes"]


def test_surface_aware_release_requires_passed_surface_closure() -> None:
    props = {
        "swsd_pair_nodes": ["n1", "n2"],
        "rcsd_pair_nodes": ["r1", "r2"],
        "risk_flags": ["junction_alignment_to_retained_swsd_exceeds_topology_gate"],
    }
    swsd_points = {"n1": Point(0, 0), "n2": Point(5, 0)}
    rcsd_points = {"r1": Point(25, 0), "r2": Point(5, 0)}
    incident = {"n1": ["s_replace", "s_retained"], "n2": ["s_replace"]}
    ready_segments = {"s_replace"}

    allowed, triggers = _release_allowed(
        props,
        {"n1": ("pass", "auto_closed_surface_1v1", 25.0)},
        swsd_points,
        rcsd_points,
        incident,
        ready_segments,
    )
    assert allowed
    assert triggers[0]["swsd_node_id"] == "n1"

    generic_allowed, generic_triggers = _release_allowed(
        props,
        {"n1": ("pass", "auto_closed", 25.0)},
        swsd_points,
        rcsd_points,
        incident,
        ready_segments,
    )
    assert generic_allowed
    assert generic_triggers[0]["surface_status"][1] == "auto_closed"

    blocked, blocked_triggers = _release_allowed(
        props,
        {"n1": ("fail", "blocked_by_patch_conflict", 25.0)},
        swsd_points,
        rcsd_points,
        incident,
        ready_segments,
    )
    assert not blocked
    assert blocked_triggers[0]["ok"] is False


def test_surface_aware_release_does_not_release_visual_only_risk() -> None:
    props = {
        "swsd_pair_nodes": ["n1", "n2"],
        "rcsd_pair_nodes": ["r1", "r2"],
        "risk_flags": ["visual_consistency_outside_manual_audit"],
    }
    swsd_points = {"n1": Point(0, 0), "n2": Point(5, 0)}
    rcsd_points = {"r1": Point(25, 0), "r2": Point(5, 0)}

    allowed, triggers = _release_allowed(
        props,
        {"n1": ("pass", "auto_closed_surface_1v1", 25.0)},
        swsd_points,
        rcsd_points,
        {"n1": ["s_replace", "s_retained"], "n2": ["s_replace"]},
        {"s_replace"},
    )

    assert not allowed
    assert triggers == []


def test_surface_aware_release_accepts_original_pair_endpoint_without_surface_row() -> None:
    props = {
        "swsd_pair_nodes": ["n1", "n2"],
        "rcsd_pair_nodes": ["r1", "r2"],
        "original_rcsd_pair_nodes": ["r1", "r2"],
        "risk_flags": ["junction_alignment_to_retained_swsd_exceeds_topology_gate"],
    }
    swsd_points = {"n1": Point(0, 0), "n2": Point(5, 0)}
    rcsd_points = {"r1": Point(25, 0), "r2": Point(5, 0)}

    allowed, triggers = _release_allowed(
        props,
        {},
        swsd_points,
        rcsd_points,
        {"n1": ["s_replace"], "n2": ["s_replace"]},
        set(),
    )

    assert allowed
    assert triggers == [
        {
            "swsd_node_id": "n1",
            "rcsd_node_id": "r1",
            "distance_m": 25.0,
            "surface_status": ["pass", "auto_closed_selected_replacement_endpoint", 25.0],
            "ok": True,
        }
    ]


def test_surface_aware_release_accepts_optional_junc_anchor_mapping_without_surface_row() -> None:
    props = {
        "swsd_pair_nodes": ["n1", "n2"],
        "rcsd_pair_nodes": ["r1", "r2"],
        "optional_junc_nodes": ["j1"],
        "optional_junc_rcsd_nodes": ["rj1"],
        "risk_flags": ["junction_alignment_to_retained_swsd_exceeds_topology_gate"],
    }
    swsd_points = {"n1": Point(0, 0), "n2": Point(10, 0), "j1": Point(4, 0)}
    rcsd_points = {"r1": Point(0, 0), "r2": Point(10, 0), "rj1": Point(30, 0)}
    incident = {"j1": ["s_replace", "s_retained"], "n1": ["s_replace"], "n2": ["s_replace"]}

    allowed, triggers = _release_allowed(
        props,
        {},
        swsd_points,
        rcsd_points,
        incident,
        {"s_replace"},
        {"j1"},
    )

    assert allowed
    assert triggers == [
        {
            "swsd_node_id": "j1",
            "rcsd_node_id": "rj1",
            "distance_m": 26.0,
            "surface_status": ["pass", "auto_closed_step2_optional_junc_anchor", 26.0],
            "ok": True,
        }
    ]

    blocked, blocked_triggers = _release_allowed(
        props,
        {},
        swsd_points,
        rcsd_points,
        incident,
        {"s_replace"},
        set(),
    )

    assert not blocked
    assert blocked_triggers[0]["ok"] is False


def test_surface_aware_point_index_uses_mainnodeid() -> None:
    points = _points_by_id(
        [
            {"properties": {"id": "sub1", "mainnodeid": "main1"}, "geometry": Point(1, 2)},
            {"properties": {"node_id": "node2"}, "geometry": Point(3, 4)},
        ]
    )

    assert points["sub1"].equals(Point(1, 2))
    assert points["main1"].equals(Point(1, 2))
    assert points["node2"].equals(Point(3, 4))


def test_surface_aware_release_rolls_back_plans_that_add_topology_failures() -> None:
    added_fail_keys = {
        ("segment_internal_connectivity", "s_group_member", "", "", "segment_corridor_coverage_dropped_after_replacement"),
        ("segment_junction_connectivity", "", "n1", "", "junction_incident_segment_mapping_missing"),
    }
    released = [
        {"plan_id": "standard:s_ok", "segment_id": "s_ok", "group_segment_ids": []},
        {"plan_id": "standard:s_direct", "segment_id": "s_direct", "group_segment_ids": []},
        {"plan_id": "group_path_corridor:s_group", "segment_id": "s_group", "group_segment_ids": ["s_group", "s_group_member"]},
    ]
    incident = {"n1": ["s_direct"], "n2": ["s_direct"], "n3": ["s_ok"]}

    assert _rollback_plan_ids_for_failed_segments(added_fail_keys, released, incident) == {
        "standard:s_direct",
        "group_path_corridor:s_group",
    }


def test_surface_aware_release_rollback_prefers_explicit_junction_segments() -> None:
    added_fail_keys = {
        (
            "segment_junction_connectivity",
            '["s_direct"]',
            "n1",
            "",
            "junction_incident_segment_mapping_missing",
        )
    }
    released = [
        {"plan_id": "standard:s_direct", "segment_id": "s_direct", "group_segment_ids": []},
        {"plan_id": "standard:s_neighbor", "segment_id": "s_neighbor", "group_segment_ids": []},
    ]
    incident = {"n1": ["s_direct", "s_neighbor"]}

    assert _rollback_plan_ids_for_failed_segments(added_fail_keys, released, incident) == {"standard:s_direct"}


def test_visual_manual_release_allows_small_pair_attachment_gap_to_retained_incident_segment() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_replace",
                    "replacement_strategy": "buffer_segment_extraction",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "swsd_uncovered_by_rcsd_length_m": 25.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.2,
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r_near", "r2"],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": ["r_near", "r2"],
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
        rcsd_nodes=[_node("r_near", 22, 0), _node("r2", 10, 0)],
    )

    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert "visual_manual_release_pair_attachment_gap_accepted" in props["risk_flags"]
    assert "junction_alignment_to_retained_swsd_exceeds_topology_gate" not in props["risk_flags"]


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


def test_replacement_plan_does_not_block_valid_peer_for_pair_anchor_mismatch_candidate() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "valid_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r_good", "r2"],
                    "rcsd_road_ids": ["rr_valid"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "mismatch_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "original_rcsd_pair_nodes": ["r_good", "r3"],
                    "rcsd_pair_nodes": ["r_bad", "r3"],
                    "rcsd_road_ids": ["rr_mismatch"],
                }
            ),
        ],
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "mismatch_segment",
                    "failure_business_category": "pair_anchor_mismatch",
                    "pair_anchor_error_swsd_nodes": ["n1"],
                    "pair_anchor_error_original_rcsd_nodes": ["r_good"],
                    "pair_anchor_error_candidate_rcsd_nodes": ["r_bad"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "valid_segment", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "mismatch_segment", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 10, 0), _node("n3", 0, 10)],
        rcsd_nodes=[
            _node("r_good", 0, 0),
            _node("r_bad", 20, 0),
            _node("r2", 10, 0),
            _node("r3", 0, 10),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["valid_segment"]["plan_status"] == "ready"
    assert by_segment["valid_segment"]["execution_action"] == "replace"
    assert "junction_alignment_peer_pair_anchor_mismatch_ignored" in by_segment["valid_segment"]["risk_flags"]
    assert by_segment["mismatch_segment"]["plan_status"] == "blocked"
    assert by_segment["mismatch_segment"]["execution_action"] == "hold"
    assert by_segment["mismatch_segment"]["source_reason"] == "pair_anchor_mismatch_replacement_plan_anchor_not_authoritative"
    assert "pair_anchor_mismatch_replacement_plan_anchor_not_authoritative" in by_segment["mismatch_segment"]["risk_flags"]


def test_replacement_plan_uses_optional_junction_nodes_after_dropped_junction() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "cross_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n_shared", "n2"],
                    "rcsd_pair_nodes": ["r_shared", "r2"],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "main_segment",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["m1", "m2"],
                    "swsd_junc_nodes": ["dropped", "n_shared", "n_other"],
                    "optional_junc_nodes": ["n_shared", "n_other"],
                    "dropped_junc_nodes": ["dropped"],
                    "rcsd_pair_nodes": ["rm1", "rm2"],
                    "rcsd_junc_nodes": ["r_shared", "r_other"],
                    "optional_junc_rcsd_nodes": ["r_shared", "r_other"],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "cross_segment", "pair_nodes": ["n_shared", "n2"]}),
            _feature({"id": "main_segment", "pair_nodes": ["m1", "m2"], "junc_nodes": ["dropped", "n_shared", "n_other"]}),
        ],
        swsd_nodes=[
            _node("n_shared", 0, 0),
            _node("n2", 0, 10),
            _node("m1", 20, 0),
            _node("m2", 20, 10),
            _node("dropped", 50, 0),
            _node("n_other", 100, 0),
        ],
        rcsd_nodes=[
            _node("r_shared", 0, 0),
            _node("r2", 0, 10),
            _node("rm1", 20, 0),
            _node("rm2", 20, 10),
            _node("r_other", 100, 0),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["cross_segment"]["plan_status"] == "ready"
    assert by_segment["main_segment"]["plan_status"] == "ready"
    assert "junction_alignment_between_replacement_plans_diverged" not in by_segment["cross_segment"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_diverged" not in by_segment["main_segment"]["risk_flags"]


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


def _feature(properties: dict, geometry: LineString | None = None) -> dict:
    return {"properties": properties, "geometry": geometry or LineString([(0, 0), (1, 0)])}


def _road(road_id: str, snode: int | str, enode: int | str, coords: list[tuple[float, float]] | None = None) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snode, "enodeid": enode},
        "geometry": LineString(coords or [(float(snode), 0), (float(enode), 0)]),
    }


def _node(node_id: str, x: float, y: float) -> dict:
    return {"properties": {"id": node_id}, "geometry": Point(x, y)}
