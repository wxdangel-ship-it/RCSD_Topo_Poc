from __future__ import annotations

import json

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_labels import (
    _acceptable_targets,
    _t05_split_road_source_map,
)


def test_plan_label_normalizes_split_rcsd_and_preserves_keep_alternative() -> None:
    label = {
        "acceptable_complete_road_targets": [
            {"carrier_target": "USE_RCSD", "road_ids": ["piece1", "r2"]},
            {"carrier_target": "KEEP_SWSD", "road_ids": ["swsd1"]},
        ]
    }
    targets = _acceptable_targets(
        label,
        {
            "piece1": ("raw1", 1),
            "r2": ("r2", 1),
        },
    )
    assert targets == [
        {"decision": "USE_RCSD", "road_ids": ["r2", "raw1"]},
        {"decision": "KEEP_SWSD", "road_ids": ["swsd1"]},
    ]


def test_unresolved_review_is_not_converted_to_abstain() -> None:
    targets = _acceptable_targets(
        {
            "carrier_target": "REVIEW_FALLBACK",
            "target_payload": [],
        },
        {},
    )
    assert targets == [{"decision": "REVIEW_FALLBACK", "road_ids": []}]


def test_t05_single_source_split_maps_generated_roads_to_input_road(
    tmp_path,
) -> None:
    path = tmp_path / "rcsd_junctionization_audit.json"
    path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "original_rcsdroad_ids": "raw1",
                        "new_rcsdroad_ids": "piece1|piece2",
                    },
                    {
                        "original_rcsdroad_ids": "raw2|raw3",
                        "new_rcsdroad_ids": "ambiguous1|ambiguous2",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    source_map, counts = _t05_split_road_source_map(path)
    assert source_map == {"piece1": "raw1", "piece2": "raw1"}
    assert counts == {
        "row_with_new_road_ids": 2,
        "single_source_row_count": 1,
        "ambiguous_source_row_count": 1,
        "ambiguous_new_road_id_count": 2,
    }


def test_t05_split_rejects_conflicting_source_road(tmp_path) -> None:
    path = tmp_path / "rcsd_junctionization_audit.json"
    path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "original_rcsdroad_ids": "raw1",
                        "new_rcsdroad_ids": "piece1",
                    },
                    {
                        "original_rcsdroad_ids": "raw2",
                        "new_rcsdroad_ids": "piece1",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="conflicting source Roads"):
        _t05_split_road_source_map(path)
