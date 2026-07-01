from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import build_replacement_plan_rows


def test_buffer_corridor_release_allows_inside_buffer_coverage_gap() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[],
        rejected_rows=[_rejected_segment("s_buffer")],
        buffer_rejected_rows=[
            _buffer_rejected(
                "s_buffer",
                rcsd_outside_swsd_buffer_length_m=0.0,
                rcsd_outside_swsd_buffer_ratio=0.0,
            )
        ],
        failure_business_audit_rows=[_high_confidence_audit("s_buffer")],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    assert len(rows) == 1
    props = rows[0]["properties"]
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert props["source_reason"] == "swsd_geometry_not_covered_by_retained_rcsd"
    assert props["replacement_strategy"] == "swsd_buffer_corridor_controlled_release"
    assert props["rcsd_road_ids"] == ["rr1", "rr2"]
    assert props["risk_flags"] == [
        "swsd_buffer_corridor_controlled_release",
        "swsd_geometry_not_covered_by_retained_rcsd",
    ]


def test_buffer_corridor_release_rejects_rcsd_outside_swsd_buffer() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[],
        rejected_rows=[_rejected_segment("s_buffer")],
        buffer_rejected_rows=[
            _buffer_rejected(
                "s_buffer",
                rcsd_outside_swsd_buffer_length_m=5.0,
                rcsd_outside_swsd_buffer_ratio=0.03,
            )
        ],
        failure_business_audit_rows=[_high_confidence_audit("s_buffer")],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
    )

    assert rows == []


def _rejected_segment(segment_id: str) -> dict:
    return _feature(
        {
            "swsd_segment_id": segment_id,
            "swsd_sgrade": "0-1单",
            "swsd_directionality": "single",
        }
    )


def _buffer_rejected(
    segment_id: str,
    *,
    rcsd_outside_swsd_buffer_length_m: float,
    rcsd_outside_swsd_buffer_ratio: float,
) -> dict:
    return _feature(
        {
            "swsd_segment_id": segment_id,
            "reject_reason": "swsd_geometry_not_covered_by_retained_rcsd",
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
            "rcsd_outside_swsd_buffer_length_m": rcsd_outside_swsd_buffer_length_m,
            "rcsd_outside_swsd_buffer_ratio": rcsd_outside_swsd_buffer_ratio,
            "swsd_uncovered_by_rcsd_length_m": 395.0,
            "swsd_uncovered_by_rcsd_ratio": 0.27,
        }
    )


def _high_confidence_audit(segment_id: str) -> dict:
    return _feature(
        {
            "swsd_segment_id": segment_id,
            "swsd_pair_nodes": ["a", "b"],
            "swsd_junc_nodes": ["j1"],
            "rcsd_pair_nodes": ["r1", "r3"],
            "rcsd_junc_nodes": ["r2"],
            "repair_recommendation": "high_confidence_pair_anchor_candidate",
            "manual_review_required": False,
            "geometry_overlap_ratio": 0.75,
            "candidate_score": 0.91,
            "directionality_score": 1.0,
            "connectivity_score": 1.0,
            "shape_similarity_score": 1.0,
        }
    )


def _feature(properties: dict) -> dict:
    return {"properties": properties, "geometry": LineString([(0, 0), (1, 0)])}
