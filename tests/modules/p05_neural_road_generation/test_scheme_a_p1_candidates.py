from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_candidates import (
    classify_segment_candidate,
)


def test_segment_candidate_classification_is_payload_based() -> None:
    assert classify_segment_candidate(("s1",), ()) == "REVIEW_FALLBACK"
    assert classify_segment_candidate(("s1",), ("s1",)) == "KEEP_SWSD"
    assert classify_segment_candidate(("s1",), ("r1",)) == "USE_RCSD"
    assert classify_segment_candidate(("s1", "s2"), ("s2", "r1")) == "MIXED_CARRIER"
