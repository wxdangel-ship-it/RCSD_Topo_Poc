from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import Edge, PathCandidate
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.rcsd_candidate_extraction import RcsdCandidate
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.trend_filters import evaluate_candidate


def _edge(edge_id: str, road_id: str, source: str, target: str):
    return Edge(edge_id, road_id, source, target, LineString([(int(source), 0), (int(target), 0)]), {})


def _candidate(edges: list[Edge]) -> RcsdCandidate:
    return RcsdCandidate("c1", "single", PathCandidate(edges), None, True, False)


def _eval(candidate: RcsdCandidate, *, junc_nodes=None, all_base_ids=None):
    return evaluate_candidate(
        candidate=candidate,
        swsd_directionality="single",
        swsd_pair_nodes=["1", "2"],
        swsd_junc_nodes=junc_nodes or ["3"],
        rcsd_pair_nodes=["10", "20"],
        rcsd_junc_nodes=["30"] if junc_nodes is None else junc_nodes,
        all_relation_base_ids=all_base_ids or {"10", "20", "30"},
        swsd_geometry=LineString([(0, 0), (10, 0)]),
        swsd_node_geometries={"1": Point(0, 0), "2": Point(10, 0)},
        rcsd_node_geometries={"10": Point(0, 0), "20": Point(10, 0), "30": Point(5, 0)},
        max_main_axis_angle_diff_deg=60.0,
        min_coarse_length_ratio=0.1,
        max_coarse_length_ratio=10.0,
    )


def test_junc_internal_passage_passes() -> None:
    result = _eval(_candidate([_edge("e1", "r1", "10", "30"), _edge("e2", "r2", "30", "20")]))

    assert result.passed


def test_junc_missing_broken_side_branch_and_unexpected_semantic_junction_reject() -> None:
    missing = _eval(_candidate([_edge("e1", "r1", "10", "20")]))
    broken = _eval(_candidate([_edge("e1", "r1", "10", "30")]))
    side = _eval(_candidate([_edge("e1", "r1", "10", "30"), _edge("e2", "r2", "30", "20"), _edge("e3", "r3", "30", "40")]))
    crossed = _eval(_candidate([_edge("e1", "r1", "10", "30"), _edge("e2", "r2", "30", "40"), _edge("e3", "r3", "40", "20")]), all_base_ids={"10", "20", "30", "40"})

    assert missing.reason == "mapped_junc_not_covered"
    assert broken.reason == "junc_internal_passage_broken"
    assert side.reason == "junc_side_branch_leakage"
    assert crossed.reason == "unexpected_semantic_junction_crossed"
