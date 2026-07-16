from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import build_replacement_plan_rows


def test_replacement_plan_marks_standard_adaptive_buffer_risk_without_holding() -> None:
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
    assert props["plan_status"] == "ready"
    assert props["execution_action"] == "replace"
    assert props["upstream_owner"] == "T05_relation_consumed"
    assert props["source_reason"] == "single_graph_retry:swsd_geometry_not_covered_by_retained_rcsd"
    assert props["risk_flags"] == ["adaptive_buffer_exceeds_topology_connectivity_audit_threshold"]
    assert "released as risk audit only" in props["notes"]


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
    assert props["source_reason"] == "postplan_anchor_gate_deferred_to_step3_topology"
    assert props["postplan_anchor_gate_original_reason"] == "junction_alignment_to_retained_swsd_exceeds_topology_gate"
    assert props["postplan_anchor_gate_evidence"] == "retained_junction_complete_anchor_no_ready_road_conflict"
    assert "postplan_anchor_gate_deferred_to_step3_topology" in props["risk_flags"]
    assert "blocked by junction_alignment_to_retained_swsd_exceeds_topology_gate" not in props["notes"]


def _feature(properties: dict, geometry: LineString | None = None) -> dict:
    return {"properties": properties, "geometry": geometry or LineString([(0, 0), (1, 0)])}


def _node(node_id: str, x: float, y: float) -> dict:
    return {"properties": {"id": node_id}, "geometry": Point(x, y)}
