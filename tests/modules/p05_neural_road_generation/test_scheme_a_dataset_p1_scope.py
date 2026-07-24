from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_dataset_p1_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_GO,
    DECISION_MAPPING_NO_GO,
    DECISION_SCOPE_NO_GO,
    SchemeADatasetP1Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_dataset_p1_scope import (
    _build_label_scope,
    _decision,
    _expected_failure_gate,
    map_segment_package,
)


def _segment(segment_id: str, *road_ids: str) -> dict[str, object]:
    return {"segment_id": segment_id, "swsd_road_ids": list(road_ids)}


def test_direct_mapping_requires_exact_id_and_road_set() -> None:
    mapped = map_segment_package(
        target_segment_id="1_2",
        target_road_ids=("10", "11"),
        current_segments=(_segment("1_2", "10", "11"),),
    )
    assert mapped["mapping_status"] == "MAPPED"
    assert mapped["mapping_method"] == "DIRECT_ID_AND_ROAD_SET"
    drift = map_segment_package(
        target_segment_id="1_2",
        target_road_ids=("10", "11"),
        current_segments=(_segment("1_2", "10", "12"),),
    )
    assert drift["mapping_status"] == "MAPPED"
    assert drift["mapping_method"] == "DIRECT_ID_WITH_ROAD_DRIFT"
    assert drift["road_drift_observed"] is True
    assert drift["missing_road_ids"] == ["11"]
    assert drift["extra_road_ids"] == ["12"]


def test_partition_mapping_requires_complete_unique_road_ownership() -> None:
    mapped = map_segment_package(
        target_segment_id="old",
        target_road_ids=("10", "11", "12"),
        current_segments=(
            _segment("a", "10"),
            _segment("b", "11"),
            _segment("c", "12"),
            _segment("context", "99"),
        ),
    )
    assert mapped["mapping_status"] == "MAPPED"
    assert mapped["mapping_method"] == "ROAD_PARTITION_LINEAGE"
    assert mapped["current_segment_ids"] == ["a", "b", "c"]
    assert mapped["geometry_inference_used"] is False


def test_partition_mapping_rejects_missing_and_duplicate_road() -> None:
    missing = map_segment_package(
        target_segment_id="old",
        target_road_ids=("10", "11"),
        current_segments=(_segment("a", "10"),),
    )
    assert missing["mapping_status"] == "ROAD_PARTITION_INCOMPLETE_OR_AMBIGUOUS"
    assert missing["missing_road_ids"] == ["11"]
    duplicate = map_segment_package(
        target_segment_id="old",
        target_road_ids=("10", "11"),
        current_segments=(
            _segment("a", "10"),
            _segment("b", "10"),
            _segment("c", "11"),
        ),
    )
    assert duplicate["mapping_status"] == "ROAD_PARTITION_INCOMPLETE_OR_AMBIGUOUS"
    assert duplicate["duplicate_road_ids"] == ["10"]


def test_label_scope_masks_non_target_context_without_weak_label() -> None:
    cases = {
        "T10-Error:old": {
            "case_key": "T10-Error:old",
            "family": "T10-Error",
            "fold": 2,
            "crs": "EPSG:3857",
        }
    }
    segment_index = {
        "T10-Error:old": [_segment("target", "10"), _segment("context", "99")]
    }
    lineage = [
        {
            "case_key": "T10-Error:old",
            "target_segment_id": "old",
            "current_segment_ids": ["target"],
            "mapping_method": "ROAD_PARTITION_LINEAGE",
            "mapping_status": "MAPPED",
        }
    ]
    rows = _build_label_scope(
        cases=cases,
        segment_index=segment_index,
        lineage_rows=lineage,
        failure_groups={},
    )
    by_id = {row["object_id"]: row for row in rows}
    assert by_id["target"]["label_eligible"] is True
    assert by_id["target"]["label_weight"] == 0.7
    assert by_id["context"]["scope_class"] == "CONTEXT_ONLY_MASKED"
    assert by_id["context"]["label_eligible"] is False
    assert by_id["context"]["label_weight"] is None
    assert by_id["context"]["context_input_weight"] == 0.3


def test_expected_failure_gate_separates_case_and_object_scope(tmp_path: Path) -> None:
    config = SchemeADatasetP1Config(
        dataset_p0_run_root=tmp_path,
        scheme_a_baseline_run_root=tmp_path,
        p2_p3_p0_run_root=tmp_path,
        poc_data_root=tmp_path,
        output_root=tmp_path,
        run_id="unit",
        expected_failure_case_count=1,
        expected_seed_count=1,
    )
    rows = [
        {
            "case_key": "T10:609214532",
            "seed": 311,
            "terminal_state": "EXPECTED_FAIL",
            "publish": False,
            "expected_failure_match": True,
            "localized_failure_segment_count": 1,
            "case_segment_count": 1795,
            "historical_case_cascade_mask_count": 1795,
            "corrected_case_cascade_mask_count": 0,
        }
    ]
    assert _expected_failure_gate(rows, config)
    rows[0]["corrected_case_cascade_mask_count"] = 1795
    assert not _expected_failure_gate(rows, config)


def test_decision_prioritizes_audit_mapping_and_scope_failures() -> None:
    assert _decision(True, True, True, True, True, True) == DECISION_GO
    assert _decision(False, True, True, True, True, True) == DECISION_AUDIT_NO_GO
    assert _decision(True, False, True, True, True, True) == DECISION_MAPPING_NO_GO
    assert _decision(True, True, False, True, True, True) == DECISION_SCOPE_NO_GO
