from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_safety import (
    _apply_fold_excluded_safety_gate,
    _safety_summary,
    apply_inner_calibrated_anchor_safety_gate,
)


def test_fold_excluded_anchor_safety_threshold_uses_other_folds() -> None:
    rows = [
        {
            "sample_id": "safe-0",
            "fold": 0,
            "candidate_type": "NODE",
            "predicted": "SUCCESS",
            "candidate_confidence_score": 0.90,
            "proven_safe_anchor": True,
        },
        {
            "sample_id": "unsafe-0",
            "fold": 0,
            "candidate_type": "NODE",
            "predicted": "SUCCESS",
            "candidate_confidence_score": 0.65,
            "proven_safe_anchor": False,
        },
        {
            "sample_id": "safe-1",
            "fold": 1,
            "candidate_type": "NODE",
            "predicted": "SUCCESS",
            "candidate_confidence_score": 0.80,
            "proven_safe_anchor": True,
        },
        {
            "sample_id": "unsafe-1",
            "fold": 1,
            "candidate_type": "NODE",
            "predicted": "SUCCESS",
            "candidate_confidence_score": 0.70,
            "proven_safe_anchor": False,
        },
    ]

    gated, thresholds = _apply_fold_excluded_safety_gate(rows)

    assert thresholds["0"]["NODE"] == 0.70
    assert thresholds["1"]["NODE"] == 0.65
    by_id = {row["sample_id"]: row for row in gated}
    assert by_id["safe-0"]["safety_accepted"] is True
    assert by_id["unsafe-0"]["safety_accepted"] is False
    assert by_id["safe-1"]["safety_accepted"] is True
    assert by_id["unsafe-1"]["safety_accepted"] is True
    assert by_id["unsafe-1"]["safety_unsafe_auto"] is True


def test_fold_excluded_anchor_safety_rejects_non_success() -> None:
    rows = [
        {
            "sample_id": "row-0",
            "fold": 0,
            "candidate_type": "ROAD",
            "predicted": "ABSTAIN",
            "candidate_confidence_score": 0.99,
            "proven_safe_anchor": False,
        },
        {
            "sample_id": "row-1",
            "fold": 1,
            "candidate_type": "ROAD",
            "predicted": "ABSTAIN",
            "candidate_confidence_score": 0.99,
            "proven_safe_anchor": False,
        },
    ]

    gated, _ = _apply_fold_excluded_safety_gate(rows)

    assert all(row["safety_accepted"] is False for row in gated)


def test_fold_excluded_anchor_safety_rejects_type_without_proven_safe_examples() -> None:
    rows = [
        {
            "sample_id": "row-0",
            "fold": 0,
            "candidate_type": "SINGLE_POINT",
            "predicted": "SUCCESS",
            "candidate_confidence_score": 0.99,
            "proven_safe_anchor": False,
        },
        {
            "sample_id": "row-1",
            "fold": 1,
            "candidate_type": "SINGLE_POINT",
            "predicted": "SUCCESS",
            "candidate_confidence_score": 0.99,
            "proven_safe_anchor": False,
        },
    ]

    gated, thresholds = _apply_fold_excluded_safety_gate(rows)

    assert thresholds["0"]["SINGLE_POINT"] == 1.0
    assert thresholds["1"]["SINGLE_POINT"] == 1.0
    assert all(row["safety_accepted"] is False for row in gated)


def test_inner_calibrated_safety_uses_matching_outer_fold_only() -> None:
    calibration = [
        {
            "sample_id": "inner-0-unsafe",
            "outer_fold": 0,
            "candidate_type": "NODE",
            "candidate_confidence_score": 0.80,
            "proven_safe_anchor": False,
            "raw_unsafe_success": True,
        },
        {
            "sample_id": "inner-0-safe",
            "outer_fold": 0,
            "candidate_type": "NODE",
            "candidate_confidence_score": 0.90,
            "proven_safe_anchor": True,
            "raw_unsafe_success": False,
        },
        {
            "sample_id": "inner-1-unsafe",
            "outer_fold": 1,
            "candidate_type": "NODE",
            "candidate_confidence_score": 0.60,
            "proven_safe_anchor": False,
            "raw_unsafe_success": True,
        },
        {
            "sample_id": "inner-1-safe",
            "outer_fold": 1,
            "candidate_type": "NODE",
            "candidate_confidence_score": 0.70,
            "proven_safe_anchor": True,
            "raw_unsafe_success": False,
        },
    ]
    oof = [
        {
            "sample_id": "outer-0",
            "fold": 0,
            "candidate_type": "NODE",
            "predicted": "SUCCESS",
            "candidate_confidence_score": 0.70,
            "proven_safe_anchor": True,
        },
        {
            "sample_id": "outer-1",
            "fold": 1,
            "candidate_type": "NODE",
            "predicted": "SUCCESS",
            "candidate_confidence_score": 0.70,
            "proven_safe_anchor": False,
        },
    ]

    gated, thresholds = apply_inner_calibrated_anchor_safety_gate(
        calibration,
        oof,
    )

    assert thresholds == {"0": {"NODE": 0.80}, "1": {"NODE": 0.60}}
    by_id = {row["sample_id"]: row for row in gated}
    assert by_id["outer-0"]["safety_accepted"] is False
    assert by_id["outer-1"]["safety_accepted"] is True
    assert by_id["outer-1"]["safety_unsafe_auto"] is True


def test_inner_calibrated_safety_rejects_type_without_safe_calibration() -> None:
    calibration = [
        {
            "sample_id": "inner",
            "outer_fold": 0,
            "candidate_type": "ROAD",
            "candidate_confidence_score": 0.10,
            "proven_safe_anchor": False,
            "raw_unsafe_success": False,
        }
    ]
    oof = [
        {
            "sample_id": "outer",
            "fold": 0,
            "candidate_type": "ROAD",
            "predicted": "SUCCESS",
            "candidate_confidence_score": 0.99,
            "proven_safe_anchor": False,
        }
    ]

    gated, thresholds = apply_inner_calibrated_anchor_safety_gate(
        calibration,
        oof,
    )

    assert thresholds == {"0": {"ROAD": 1.0}}
    assert gated[0]["safety_accepted"] is False


def test_safety_summary_splits_supervised_errors_from_unverifiable_auto() -> None:
    rows = [
        {
            "fold": 0,
            "candidate_type": "ROAD",
            "predicted": "SUCCESS",
            "label": "SUCCESS",
            "status_supervised": True,
            "candidate_supervised": True,
            "candidate_acceptable_exact": True,
            "proven_safe_anchor": True,
            "raw_unsafe_success": False,
            "safety_accepted": True,
        },
        {
            "fold": 0,
            "candidate_type": "ROAD",
            "predicted": "SUCCESS",
            "label": "SUCCESS",
            "status_supervised": True,
            "candidate_supervised": True,
            "candidate_acceptable_exact": False,
            "proven_safe_anchor": False,
            "raw_unsafe_success": True,
            "safety_accepted": True,
        },
        {
            "fold": 1,
            "candidate_type": "NODE",
            "predicted": "SUCCESS",
            "label": "ABSTAIN",
            "status_supervised": True,
            "candidate_supervised": False,
            "candidate_acceptable_exact": None,
            "proven_safe_anchor": False,
            "raw_unsafe_success": True,
            "safety_accepted": True,
        },
        {
            "fold": 1,
            "candidate_type": "NODE",
            "predicted": "SUCCESS",
            "label": "ABSTAIN",
            "status_supervised": False,
            "candidate_supervised": False,
            "candidate_acceptable_exact": None,
            "proven_safe_anchor": False,
            "raw_unsafe_success": True,
            "safety_accepted": True,
        },
    ]

    summary = _safety_summary(rows)

    assert summary["counts"]["safety_accepted"] == 4
    assert summary["counts"]["safety_safe_auto"] == 1
    assert summary["counts"]["safety_unsafe_auto"] == 3
    assert summary["counts"]["safety_supervised_error_auto"] == 2
    assert summary["counts"]["safety_unverifiable_auto"] == 1
    assert summary["per_candidate_type"]["ROAD"][
        "safety_supervised_error_auto"
    ] == 1
    assert summary["per_candidate_type"]["NODE"][
        "safety_unverifiable_auto"
    ] == 1
    assert summary["safety_gate_pass"] is False
