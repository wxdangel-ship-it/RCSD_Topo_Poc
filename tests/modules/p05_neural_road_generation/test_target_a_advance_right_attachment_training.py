from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_attachment_training import (
    CONDITION_FEATURE_DIM,
    attachment_metrics,
    condition_feature_values,
)


def test_condition_features_separate_teacher_and_oof_business_state() -> None:
    values = condition_feature_values(
        {
            "access_source": "RCSD",
            "selected_decision": "USE_RCSD",
            "selected_road_ids": ["r1", "r2"],
            "access_road_ids": ["r2"],
            "carrier_probability": 0.8,
            "access_source_resolved": True,
            "access_road_resolved": True,
            "ordinary_release_ready": True,
            "access_release_ready": False,
            "complete_release_ready": False,
            "resolution": "OOF_LOCKED",
        }
    )

    assert len(values) == CONDITION_FEATURE_DIM
    assert values[1] == 1.0
    assert values[4] == 1.0
    assert values[11] == 1.0
    assert values[12] == 0.0


def test_attachment_metrics_keep_raw_and_release_safety_separate() -> None:
    metrics = attachment_metrics(
        [
            {
                "case_key": "case",
                "side": "SOURCE",
                "raw_exact": True,
                "teacher_exact": True,
                "release_eligible": False,
                "automatic": False,
                "unsafe_automatic": False,
            },
            {
                "case_key": "case",
                "side": "TARGET",
                "raw_exact": False,
                "teacher_exact": True,
                "release_eligible": True,
                "automatic": True,
                "unsafe_automatic": True,
            },
        ]
    )

    assert metrics["oof_raw_exact"] == 0.5
    assert metrics["teacher_raw_exact"] == 1.0
    assert metrics["automatic_count"] == 1
    assert metrics["unsafe_automatic_count"] == 1
