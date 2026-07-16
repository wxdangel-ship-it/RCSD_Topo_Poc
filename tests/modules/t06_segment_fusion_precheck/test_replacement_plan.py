from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import (
    _blocked_standard_member_absorbable_by_path_group,
    build_problem_registry_rows,
    build_replacement_plan_rows,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.schemas import T06Step3Artifacts
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_surface_aware_plan_release as release_module
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_aware_plan_release import (
    _points_by_id,
    _release_allowed,
    _rollback_items_for_plan_rows,
    _rollback_plan_ids,
    _rollback_plan_ids_for_failed_segments,
    _rollback_visual_conflict_release_rows,
    _visual_conflict_non_replaced_plan_ids,
    _visual_conflict_release_plan_rows,
    _visual_conflict_rollback_plan_ids,
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
            ),
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": [2, 3],
                    "rcsd_pair_nodes": [20, 30],
                    "rcsd_road_ids": ["rr2"],
                    "retained_node_ids": [20, 30],
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
        failure_business_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "optional_junc_nodes": ["j_mid"],
                    "optional_junc_rcsd_nodes": ["r_mid"],
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
    assert scopes == ["standard_segment", "standard_segment", "path_corridor_group", "special_junction_group_internal"]
    group = [row for row in rows if row["properties"]["execution_scope"] == "path_corridor_group"][0]["properties"]
    assert group["rcsd_road_ids"] == ["rr1", "rr2"]
    assert group["retained_node_ids"] == ["10", "20", "30"]
    assert group["optional_junc_nodes"] == ["j_mid"]
    assert group["optional_junc_rcsd_nodes"] == ["r_mid"]
    assert group["rcsd_junc_nodes"] == ["r_mid"]


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
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": [1, 2],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": [2, 3],
                    "rcsd_pair_nodes": [20, 30],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
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

    props = [row["properties"] for row in rows if row["properties"]["execution_scope"] == "path_corridor_group"][0]
    assert props["plan_status"] == "blocked"
    assert props["execution_action"] == "hold"
    assert props["execution_scope"] == "path_corridor_group"
    assert props["source_reason"] == "path_corridor_group_not_segment_replacement_scope"
    assert props["group_segment_ids"] == ["s2"]
    assert "path_corridor_source_segment_blocked" in props["risk_flags"]
    assert "excluded from group action" in props["notes"]


def test_replacement_plan_marks_path_corridor_group_when_source_not_formal_replaceable() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_peer",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": [2, 3],
                    "rcsd_pair_nodes": [20, 30],
                    "rcsd_road_ids": ["rr2"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_rejected",
                    "group_probe_status": "passed",
                    "group_probe_repair_owner": "T06_path_corridor_group_replacement",
                    "group_probe_reason": "passed",
                    "group_probe_buffer_distance_m": 50.0,
                    "path_corridor_group_segment_ids": ["s_rejected", "s_peer"],
                    "group_probe_rcsd_road_ids": ["rr1", "rr2"],
                    "swsd_pair_nodes": [1, 2],
                    "rcsd_pair_nodes": [10, 20],
                }
            )
        ],
        rcsd_roads=[_road("rr1", 10, 15), _road("rr2", 15, 20)],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "15", "20"})),
    )

    props = [row["properties"] for row in rows if row["properties"]["execution_scope"] == "path_corridor_group"][0]
    assert props["plan_status"] == "blocked"
    assert props["execution_action"] == "hold"
    assert props["source_reason"] == "path_corridor_group_not_segment_replacement_scope"
    assert props["group_segment_ids"] == ["s_rejected", "s_peer"]
    assert "path_corridor_source_segment_not_formal_replaceable" in props["risk_flags"]
    assert "did not pass formal single-segment RCSD extraction" in props["notes"]


def test_replacement_plan_marks_group_probe_buffer_risk_without_holding() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_wide",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": [1, 2],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s_peer",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": [2, 3],
                    "rcsd_pair_nodes": [20, 30],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
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

    props = [row["properties"] for row in rows if row["properties"]["execution_scope"] == "path_corridor_group"][0]
    assert props["plan_status"] == "blocked"
    assert props["execution_action"] == "hold"
    assert props["source_reason"] == "path_corridor_group_not_segment_replacement_scope"
    assert props["group_segment_ids"] == ["s_wide", "s_peer"]
    assert props["risk_flags"] == [
        "group_path_corridor_replacement",
        "group_probe_buffer_exceeds_topology_connectivity_audit_threshold",
    ]
    assert "released as risk audit only" in props["notes"]


def test_replacement_plan_holds_source_blocked_group_when_no_members_remain() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_wide",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": [1, 2],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_road_ids": ["rr1"],
                }
            )
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_wide",
                    "group_probe_status": "passed",
                    "group_probe_repair_owner": "T06_path_corridor_group_replacement",
                    "group_probe_reason": "passed",
                    "group_probe_buffer_distance_m": 50.0,
                    "path_corridor_group_segment_ids": ["s_wide"],
                    "path_corridor_blocked_segment_ids": ["s_wide"],
                    "group_probe_rcsd_road_ids": ["rr1", "rr2"],
                    "swsd_pair_nodes": [1, 2],
                    "rcsd_pair_nodes": [10, 20],
                }
            )
        ],
        rcsd_roads=[_road("rr1", 10, 15), _road("rr2", 15, 20)],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "15", "20"})),
    )

    props = [row["properties"] for row in rows if row["properties"]["execution_scope"] == "path_corridor_group"][0]
    assert props["plan_status"] == "blocked"
    assert props["execution_action"] == "hold"
    assert props["source_reason"] == "path_corridor_group_not_segment_replacement_scope"
    assert props["group_segment_ids"] == []
    assert "no eligible path-corridor group members remain" in props["notes"]


def test_replacement_plan_does_not_block_group_for_member_adaptive_buffer_risk() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_group",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "c"],
                    "rcsd_pair_nodes": [1, 3],
                    "rcsd_road_ids": ["rr_group"],
                    "retained_node_ids": [1, 3],
                }
            ),
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
    assert standard["plan_status"] == "ready"
    assert standard["execution_action"] == "replace"
    assert group["plan_status"] == "blocked"
    assert group["execution_action"] == "hold"
    assert standard["risk_flags"] == ["adaptive_buffer_exceeds_topology_connectivity_audit_threshold"]
    assert group["risk_flags"] == ["group_path_corridor_replacement"]


def test_group_plan_absorbs_internal_member_visual_road_conflict() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s_group",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "c"],
                    "rcsd_pair_nodes": [1, 3],
                    "rcsd_road_ids": ["rr_group"],
                    "retained_node_ids": [1, 3],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s_owner",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": [1, 2],
                    "rcsd_road_ids": ["rr_shared"],
                    "retained_node_ids": [1, 2],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s_owner2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["d", "e"],
                    "rcsd_pair_nodes": [4, 5],
                    "rcsd_road_ids": ["rr_internal_owned"],
                    "retained_node_ids": [4, 5],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s_member",
                    "replacement_strategy": "visual_consistency_controlled_release",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "swsd_uncovered_by_rcsd_length_m": 0.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.0,
                    "swsd_pair_nodes": ["b", "c"],
                    "rcsd_pair_nodes": [2, 3],
                    "rcsd_road_ids": ["rr_shared", "rr_internal_owned"],
                    "retained_node_ids": [2, 3],
                }
            ),
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
                    "path_corridor_group_segment_ids": ["s_group", "s_owner", "s_owner2", "s_member"],
                    "group_probe_rcsd_road_ids": ["rr_shared", "rr_group"],
                    "swsd_pair_nodes": ["a", "c"],
                    "rcsd_pair_nodes": [1, 3],
                }
            )
        ],
        rcsd_roads=[
            _road("rr_shared", 1, 2, [(0, 0), (100, 0)]),
            _road("rr_internal_owned", 4, 5, [(0, 10), (100, 10)]),
            _road("rr_group", 2, 3),
        ],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"1", "2", "3", "4", "5"})),
    )

    by_id = {row["properties"]["replacement_plan_id"]: row["properties"] for row in rows}
    member = by_id["standard:s_member"]
    group = by_id["group_path_corridor:s_group"]
    assert member["plan_status"] == "blocked"
    assert member["source_reason"] == "visual_consistency_road_conflict_with_primary_replacement_plan"
    assert group["plan_status"] == "blocked"
    assert group["execution_action"] == "hold"
    assert group["source_reason"] == "path_corridor_group_not_segment_replacement_scope"
    assert "group_member_visual_conflict_absorbed_by_path_corridor_group" not in group["risk_flags"]
    assert "absorbed_group_member_visual_conflict_segments" not in group["notes"]


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
                    "swsd_segment_id": "s_group",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["g1", "g2"],
                    "rcsd_pair_nodes": ["30", "40"],
                    "rcsd_road_ids": ["rr_group"],
                    "retained_node_ids": ["30", "40"],
                }
            ),
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
        rcsd_roads=[_road("rr_member", 10, 20, [(0, 0), (100, 0)]), _road("rr_group", 30, 40)],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset({"10", "20", "30", "40"})),
        swsd_segments=[_feature({"id": "s_member"}, LineString([(0, 0), (100, 0)]))],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s_member"]["plan_status"] == "ready"
    assert by_segment["s_member"]["execution_action"] == "replace"
    assert by_segment["s_group"]["plan_status"] == "blocked"
    assert "visual_consistency_same_path_group_member_conflict_accepted" not in by_segment["s_member"]["risk_flags"]
    assert "accepted_same_path_group_member_rcsd_road_ids" not in by_segment["s_member"]["notes"]
    assert "visual_consistency_road_conflict_with_primary_replacement_plan" not in by_segment["s_member"]["risk_flags"]


def test_group_member_gate_absorbs_same_path_pair_anchor_mismatch_member() -> None:
    assert _blocked_standard_member_absorbable_by_path_group(
        {
            "swsd_segment_id": "s_member",
            "source_reason": "pair_anchor_mismatch_replacement_plan_anchor_not_authoritative",
            "replacement_strategy": "visual_consistency_controlled_release",
            "rcsd_road_ids": ["rr_member"],
            "risk_flags": [
                "visual_consistency_same_path_group_member_conflict_accepted",
                "no_formal_trunk_road_conflict",
            ],
        },
        group_segment_ids={"s_group", "s_member"},
        group_road_ids={"rr_group", "rr_member"},
        ready_standard_owner_segments_by_road={},
    )


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


def test_visual_consistency_reassigns_parallel_corridor_when_it_preserves_primary_geometry() -> None:
    roads = [
        _road("primary_left", "p1", "p_mid", [(0, 0), (80, 0)]),
        _road("primary_right", "p_mid", "p2", [(120, 0), (200, 0)]),
        _road("current_visual", "v1", "v2", [(80, 0), (120, 0)]),
        _road("parallel_a", "v1", "v_mid", [(80, 20), (100, 20)]),
        _road("parallel_b", "v_mid", "v2", [(100, 20), (120, 20)]),
    ]
    for road in roads:
        road["properties"]["direction"] = 2

    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "primary",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["a", "b"],
                    "rcsd_pair_nodes": ["p1", "p2"],
                    "rcsd_road_ids": [
                        "primary_left",
                        "primary_right",
                        "current_visual",
                        "parallel_a",
                        "parallel_b",
                    ],
                    "retained_node_ids": ["p1", "p_mid", "p2", "v1", "v_mid", "v2"],
                },
                LineString([(0, 0), (200, 0)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "visual",
                    "replacement_strategy": "buffer_segment_extraction",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "swsd_uncovered_by_rcsd_length_m": 0.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.0,
                    "swsd_directionality": "single",
                    "swsd_pair_nodes": ["c", "d"],
                    "rcsd_pair_nodes": ["v1", "v2"],
                    "rcsd_road_ids": ["current_visual"],
                    "retained_node_ids": ["v1", "v2"],
                },
                LineString([(80, 20), (120, 20)]),
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=roads,
        rcsd_node_canonicalizer=NodeCanonicalizer(
            {},
            frozenset({"p1", "p_mid", "p2", "v1", "v_mid", "v2"}),
        ),
        swsd_segments=[
            _feature({"id": "primary"}, LineString([(0, 0), (200, 0)])),
            _feature({"id": "visual"}, LineString([(80, 20), (120, 20)])),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["primary"]["plan_status"] == "ready"
    assert by_segment["primary"]["rcsd_road_ids"] == ["primary_left", "primary_right", "current_visual"]
    assert "primary_parallel_corridor_transferred_to_visual_segment" in by_segment["primary"]["risk_flags"]
    assert by_segment["visual"]["plan_status"] == "ready"
    assert by_segment["visual"]["rcsd_road_ids"] == ["parallel_a", "parallel_b"]
    assert "visual_consistency_parallel_corridor_reassigned_from_primary" in by_segment["visual"]["risk_flags"]
    assert "visual_consistency_road_conflict_with_primary_replacement_plan" not in by_segment["visual"]["risk_flags"]


def test_visual_consistency_keeps_ordered_anchor_corridor_before_relative_position_and_distance() -> None:
    roads = [
        _road("primary_left", "p1", "v1", [(0, 0), (80, 0)]),
        _road("primary_right", "v2", "p2", [(120, 0), (200, 0)]),
        _road("anchored_a", "v1", "j1", [(80, 0), (92, 0)]),
        _road("anchored_b", "j1", "j2", [(92, 0), (108, 0)]),
        _road("anchored_c", "j2", "v2", [(108, 0), (120, 0)]),
        _road("near_a", "v1", "near_mid", [(80, 20), (100, 20)]),
        _road("near_b", "near_mid", "v2", [(100, 20), (120, 20)]),
    ]
    for road in roads:
        road["properties"]["direction"] = 2

    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "primary",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_directionality": "single",
                    "swsd_pair_nodes": ["pa", "pb"],
                    "rcsd_pair_nodes": ["p1", "p2"],
                    "rcsd_road_ids": [
                        "primary_left",
                        "primary_right",
                        "anchored_a",
                        "anchored_b",
                        "anchored_c",
                        "near_a",
                        "near_b",
                    ],
                    "retained_node_ids": ["p1", "v1", "j1", "j2", "v2", "near_mid", "p2"],
                },
                LineString([(0, 0), (200, 0)]),
            ),
            _feature(
                {
                    "swsd_segment_id": "anchored_visual",
                    "replacement_strategy": "buffer_segment_extraction",
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_visual_consistency_scope",
                    "swsd_uncovered_by_rcsd_length_m": 0.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.0,
                    "swsd_directionality": "single",
                    "swsd_pair_nodes": ["a", "b"],
                    "swsd_junc_nodes": ["sw_j1", "sw_j2"],
                    "rcsd_pair_nodes": ["v1", "v2"],
                    "rcsd_junc_nodes": ["j1", "j2"],
                    "rcsd_road_ids": ["anchored_a", "anchored_b", "anchored_c"],
                    "retained_node_ids": ["v1", "j1", "j2", "v2"],
                },
                LineString([(80, 20), (120, 20)]),
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=roads,
        rcsd_node_canonicalizer=NodeCanonicalizer(
            {},
            frozenset({"p1", "v1", "j1", "j2", "v2", "near_mid", "p2"}),
        ),
        swsd_segments=[
            _feature({"id": "primary"}, LineString([(0, 0), (200, 0)])),
            _feature({"id": "anchored_visual"}, LineString([(80, 20), (120, 20)])),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["primary"]["plan_status"] == "ready"
    assert by_segment["primary"]["rcsd_road_ids"] == [
        "primary_left",
        "primary_right",
        "near_a",
        "near_b",
    ]
    assert by_segment["anchored_visual"]["plan_status"] == "ready"
    assert by_segment["anchored_visual"]["rcsd_road_ids"] == ["anchored_a", "anchored_b", "anchored_c"]
    assert by_segment["anchored_visual"].get("parallel_corridor_peer_road_ids", []) == []
    assert "anchor_priority_parallel_corridor_retained" in by_segment["anchored_visual"]["risk_flags"]
    assert "priority=anchor_relation>relative_position>distance" in by_segment["anchored_visual"]["notes"]


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


def _feature(properties: dict, geometry: LineString | None = None) -> dict:
    return {"properties": properties, "geometry": geometry or LineString([(0, 0), (1, 0)])}


def _road(road_id: str, snode: int | str, enode: int | str, coords: list[tuple[float, float]] | None = None) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snode, "enodeid": enode},
        "geometry": LineString(coords or [(float(snode), 0), (float(enode), 0)]),
    }


def _node(node_id: str, x: float, y: float) -> dict:
    return {"properties": {"id": node_id}, "geometry": Point(x, y)}
