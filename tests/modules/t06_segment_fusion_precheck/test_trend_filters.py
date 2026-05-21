from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import Edge, PathCandidate
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.rcsd_candidate_extraction import RcsdCandidate
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.trend_filters import evaluate_candidate


def _candidate(line: LineString) -> RcsdCandidate:
    edge = Edge("e1", "r1", "10", "20", line, {})
    return RcsdCandidate("c1", "single", PathCandidate([edge]), None, True, False)


def _eval(candidate: RcsdCandidate, *, swsd_line=None, rcsd_nodes=None, max_angle=60.0, min_ratio=0.4, max_ratio=2.5):
    return evaluate_candidate(
        candidate=candidate,
        swsd_directionality="single",
        swsd_pair_nodes=["1", "2"],
        swsd_junc_nodes=[],
        rcsd_pair_nodes=["10", "20"],
        rcsd_junc_nodes=[],
        all_relation_base_ids={"10", "20"},
        swsd_geometry=swsd_line or LineString([(0, 0), (10, 0)]),
        swsd_node_geometries={"1": Point(0, 0), "2": Point(10, 0)},
        rcsd_node_geometries=rcsd_nodes or {"10": Point(0, 0), "20": Point(10, 0)},
        max_main_axis_angle_diff_deg=max_angle,
        min_coarse_length_ratio=min_ratio,
        max_coarse_length_ratio=max_ratio,
    )


def test_main_axis_and_length_ratio_pass() -> None:
    result = _eval(_candidate(LineString([(0, 0), (10, 0)])))

    assert result.passed
    assert result.metrics["main_axis_angle_diff_deg"] <= 60.0
    assert result.metrics["length_ratio"] == 1.0


def test_main_axis_and_length_ratio_rejects() -> None:
    angle = _eval(_candidate(LineString([(0, 0), (10, 0)])), rcsd_nodes={"10": Point(0, 0), "20": Point(0, 10)})
    short = _eval(_candidate(LineString([(0, 0), (2, 0)])))
    long = _eval(_candidate(LineString([(0, 0), (30, 0)])))

    assert angle.reason == "main_axis_trend_mismatch"
    assert short.reason == "coarse_length_trend_mismatch"
    assert long.reason == "coarse_length_trend_mismatch"
