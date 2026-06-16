from __future__ import annotations

from shapely.geometry import LineString

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
