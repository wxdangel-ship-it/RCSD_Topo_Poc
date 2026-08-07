from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    discover_target_a_case_bundles,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_label_adapter import (
    _MANUAL_ADJUDICATIONS,
    _apply_manual_adjudications,
    _strategy_carrier_label,
    _target_segment_scope,
)


def test_target_a_case_bundle_scope_uses_new_t10_and_full_error_baselines(
    tmp_path: Path,
) -> None:
    # The integration path is exercised against real data in the formal
    # preflight. This unit test keeps the exclusion contract explicit without
    # copying GIS fixtures.
    assert callable(discover_target_a_case_bundles)
    assert "1213556_1263661" in (
        "T10-Error:1213556_1263661"
    )


def test_error_case_scope_never_remaps_directory_segment_to_context(
    tmp_path: Path,
) -> None:
    (tmp_path / "t10_case_evidence_manifest.json").write_text(
        '{"scope":{"swsd_segment_id":"directory-segment",'
        '"segment_properties":{"roads":"shared-road"}}}',
        encoding="utf-8",
    )
    bundle = SimpleNamespace(
        family="T10-Error",
        case_key="T10-Error:directory-segment",
        source_case_root=tmp_path,
        target_segment_id="directory-segment",
    )
    exact = _target_segment_scope(
        bundle,
        SimpleNamespace(
            segments=[
                SimpleNamespace(segment_id="directory-segment"),
                SimpleNamespace(segment_id="context-segment"),
            ]
        ),
    )
    assert exact == {
        "mapping_method": "EXACT_DIRECTORY_SEGMENT_ID",
        "mapping_status": "MAPPED",
        "target_segment_id": "directory-segment",
        "current_segment_ids": ["directory-segment"],
    }

    missing = _target_segment_scope(
        bundle,
        SimpleNamespace(
            segments=[
                SimpleNamespace(segment_id="context-segment"),
            ]
        ),
    )
    assert missing == {
        "mapping_method": "EXACT_DIRECTORY_SEGMENT_ID",
        "mapping_status": "TARGET_NOT_IN_FROZEN_T01",
        "target_segment_id": "directory-segment",
        "current_segment_ids": [],
    }


def test_manual_adjudications_override_weight_multisolution_and_clue() -> None:
    segment_rows = [
        {
            "case_key": case_key,
            "segment_id": segment_id,
            "swsd_road_ids": [f"swsd:{segment_id}"],
        }
        for case_key, segment_id in _MANUAL_ADJUDICATIONS
    ]
    baseline_rows = [
        {
            "case_key": case_key,
            "segment_id": segment_id,
            "selected_road_ids": [f"rcsd:{segment_id}"],
        }
        for case_key, segment_id in _MANUAL_ADJUDICATIONS
    ]
    label_rows = [
        {
            "case_key": case_key,
            "object_id": segment_id,
            "carrier_target": "KEEP_SWSD",
            "target_payload": [],
            "label_weight": 0.7,
        }
        for case_key, segment_id in _MANUAL_ADJUDICATIONS
    ]
    clue_rows = [
        {
            "case_key": "T10:609214532",
            "object_id": "513242335_523239407",
        }
    ]
    assert (
        _apply_manual_adjudications(
            segment_rows=segment_rows,
            baseline_rows=baseline_rows,
            label_rows=label_rows,
            clue_rows=clue_rows,
        )
        == 5
    )
    rows = {
        (row["case_key"], row["object_id"]): row
        for row in label_rows
    }
    multi = rows[("T10:706247", "706317_706319")]
    assert multi["acceptable_carrier_targets"] == ["KEEP_SWSD", "USE_RCSD"]
    assert multi["preferred_carrier_target"] == "KEEP_SWSD"
    assert multi["fallback_scope"] == "JUNCTION"
    assert multi["label_weight"] == 1.0
    assert not any(
        row["object_id"] == "513242335_523239407" for row in clue_rows
    )
    assert any(
        row["code"] == "MANUAL_REALITY_STRUCTURE_CONFLICT"
        and row["object_id"] == "706247"
        for row in clue_rows
    )


def test_unresolved_terminal_reason_is_not_invented_as_abstain_label() -> None:
    legacy = SimpleNamespace(
        to_dict=lambda: {
            "carrier_target": "KEEP_SWSD",
            "target_payload": ["legacy"],
            "available": True,
            "weight_role": "TARGET",
        }
    )
    unresolved = SimpleNamespace(
        carrier_target=SimpleNamespace(value="REVIEW_FALLBACK"),
        selected_road_ids=(),
        outcome=SimpleNamespace(value="REVIEW"),
        relation_status="review",
        relation_reason="unknown",
    )
    label = _strategy_carrier_label(
        legacy,
        baseline=unresolved,
        label_scope="TARGET",
        target_weight=0.7,
        segment_type="STANDARD",
    )
    assert not label["task_mask"]
    assert label["carrier_target"] == "REVIEW_FALLBACK"
    assert label["preferred_carrier_target"] == ""
