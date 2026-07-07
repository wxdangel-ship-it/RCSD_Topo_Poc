from __future__ import annotations

from shapely.geometry import Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import NodeCanonicalizer
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.replacement_plan import build_replacement_plan_rows


def _feature(props, geom=None):
    return {"type": "Feature", "properties": props, "geometry": geom}


def _node(node_id: str, x: float, y: float):
    return _feature({"id": node_id}, Point(x, y))


def test_same_canonical_rcsd_nodes_do_not_block_replacement_plan_alignment() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "s1",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n2"],
                    "rcsd_pair_nodes": ["r_alias", "r2"],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "s2",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n1", "n3"],
                    "rcsd_pair_nodes": ["r_main", "r3"],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({"r_alias": "r_main", "r_main": "r_main"}, frozenset({"r_main"})),
        swsd_segments=[
            _feature({"id": "s1", "pair_nodes": ["n1", "n2"]}),
            _feature({"id": "s2", "pair_nodes": ["n1", "n3"]}),
        ],
        swsd_nodes=[_node("n1", 0, 0), _node("n2", 0, 10), _node("n3", 0, 20)],
        rcsd_nodes=[
            _node("r_alias", 0, 0),
            _node("r_main", 20, 0),
            _node("r2", 0, 10),
            _node("r3", 0, 20),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["s1"]["plan_status"] == "ready"
    assert by_segment["s2"]["plan_status"] == "ready"
    assert "junction_alignment_between_replacement_plans_diverged" not in by_segment["s1"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_diverged" not in by_segment["s2"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_semantic_group_aligned" in by_segment["s1"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_semantic_group_aligned" in by_segment["s2"]["risk_flags"]


def test_junction_alignment_blocks_buffer_corridor_outlier_when_majority_agrees() -> None:
    rows = build_replacement_plan_rows(
        replaceable_rows=[
            _feature(
                {
                    "swsd_segment_id": "main_a",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n_shared", "n2"],
                    "rcsd_pair_nodes": ["r_major", "r2"],
                    "rcsd_road_ids": ["rr1"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "main_b",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n_shared", "n3"],
                    "rcsd_pair_nodes": ["r_major", "r3"],
                    "rcsd_road_ids": ["rr2"],
                }
            ),
            _feature(
                {
                    "swsd_segment_id": "buffer_outlier",
                    "replacement_strategy": "buffer_segment_extraction",
                    "swsd_pair_nodes": ["n_shared", "n4"],
                    "rcsd_pair_nodes": ["r_outlier", "r4"],
                    "rcsd_road_ids": ["rr3"],
                    "geometry_buffer_coverage_issue": "retained_geometry_outside_swsd_buffer_scope",
                    "rcsd_outside_swsd_buffer_length_m": 120.0,
                    "rcsd_outside_swsd_buffer_ratio": 0.42,
                    "swsd_uncovered_by_rcsd_length_m": 0.0,
                    "swsd_uncovered_by_rcsd_ratio": 0.0,
                }
            ),
        ],
        special_group_rows=[],
        group_replacement_audit_rows=[],
        rcsd_roads=[],
        rcsd_node_canonicalizer=NodeCanonicalizer({}, frozenset()),
        swsd_segments=[
            _feature({"id": "main_a", "pair_nodes": ["n_shared", "n2"]}),
            _feature({"id": "main_b", "pair_nodes": ["n_shared", "n3"]}),
            _feature({"id": "buffer_outlier", "pair_nodes": ["n_shared", "n4"]}),
        ],
        swsd_nodes=[
            _node("n_shared", 0, 0),
            _node("n2", 0, 10),
            _node("n3", 10, 10),
            _node("n4", 20, 10),
        ],
        rcsd_nodes=[
            _node("r_major", 0, 0),
            _node("r_outlier", 100, 0),
            _node("r2", 0, 10),
            _node("r3", 10, 10),
            _node("r4", 20, 10),
        ],
    )

    by_segment = {row["properties"]["swsd_segment_id"]: row["properties"] for row in rows}
    assert by_segment["main_a"]["plan_status"] == "ready"
    assert by_segment["main_b"]["plan_status"] == "ready"
    assert "junction_alignment_buffer_corridor_outlier_ignored" in by_segment["main_a"]["risk_flags"]
    assert "junction_alignment_buffer_corridor_outlier_ignored" in by_segment["main_b"]["risk_flags"]
    assert "junction_alignment_between_replacement_plans_diverged" not in by_segment["main_a"]["risk_flags"]
    assert by_segment["buffer_outlier"]["plan_status"] == "blocked"
    assert by_segment["buffer_outlier"]["source_reason"] == "junction_alignment_outlier_buffer_corridor_plan"
