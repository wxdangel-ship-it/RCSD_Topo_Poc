from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_dataset import (
    candidate_matches_label,
    forbidden_feature_hits,
)


def test_candidate_match_requires_target_kind_and_exact_payload() -> None:
    label = {
        "carrier_target": "USE_RCSD",
        "target_kind": "ROAD",
        "target_payload": ["r2", "r1"],
    }
    assert candidate_matches_label(
        {"candidate_target": "USE_RCSD", "target_kind": "ROAD", "target_payload": ["r1", "r2"]},
        label,
    )
    assert not candidate_matches_label(
        {"candidate_target": "USE_RCSD", "target_kind": "ROAD", "target_payload": ["r1"]},
        label,
    )


def test_forbidden_feature_audit_detects_ids_and_truth_flags() -> None:
    label = {"case_key": "T10:1885118", "object_id": "segment_12345", "target_payload": ["road_98765"]}
    feature = {
        "object_tokens": ["OBJECT:SEGMENT", "OBJECT_ID:segment_12345"],
        "candidate_tokens": ["OPTION:KEEP_SWSD"],
        "context_tokens": [],
        "feature_uses_truth": True,
        "absolute_coordinate_feature_count": 1,
    }
    hits = forbidden_feature_hits(feature, label)
    assert "feature_uses_truth" in hits
    assert "absolute_coordinate" in hits
    assert any(hit.startswith("dynamic_id:") for hit in hits)
