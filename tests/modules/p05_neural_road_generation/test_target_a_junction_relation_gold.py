from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_relation_gold import (
    build_strong_junction_relation_gold,
)


def test_relation_gold_maps_complete_t05_plans(tmp_path: Path) -> None:
    direct_relation_path = tmp_path / "direct.geojson"
    other_relation_path = tmp_path / "other.geojson"
    _relation(direct_relation_path, status=0, base_id="10")
    _relation(other_relation_path, status=0, base_id="20")
    rows = [
        _source(
            sample_id="direct",
            action="direct_relation",
            main="10",
            relation_path=direct_relation_path,
        ),
        _source(
            sample_id="group",
            action="group_existing_rcsd_nodes",
            main="20",
            original_nodes=["20", "21"],
            grouped_nodes=["20", "21", "22"],
            relation_path=other_relation_path,
        ),
        _source(
            sample_id="split",
            action="split_rcsdroad_generate_rcsdnode",
            main="20",
            original_roads=["30", "31"],
            new_nodes=["20"],
            relation_path=other_relation_path,
        ),
    ]
    gold = build_strong_junction_relation_gold(
        rows,
        split_by_sample={row["sample_id"]: "train" for row in rows},
    )
    by_id = {row.sample_id: row for row in gold}
    assert by_id["direct"].acceptable_object_id_sets == (("NODE:10",),)
    assert by_id["group"].acceptable_object_id_sets == (
        ("NODE:20", "NODE:21", "NODE:22"),
    )
    assert by_id["split"].acceptable_object_id_sets == (
        ("ROAD:30", "ROAD:31"),
    )
    assert by_id["split"].final_relation_base_mode == "GENERATED_RCSD_NODE"
    assert by_id["split"].final_relation_base_id == ""


def test_relation_gold_keeps_action_only_and_state_only_masked(
    tmp_path: Path,
) -> None:
    relation_path = tmp_path / "intersection_match_all.geojson"
    _relation(relation_path, status=1, base_id="0")
    action_only = _source(
        sample_id="action-only",
        action="split_rcsdroad_generate_rcsdnode",
        main="40",
        original_roads=["30"],
        new_nodes=["40"],
        relation_path=relation_path,
    )
    action_only["junctionization_action_gold_status"] = "ACTION_ONLY"
    action_only["complete_junction_gold_status"] = "SAFETY_ONLY"
    state_only = _source(
        sample_id="state-only",
        action="",
        main="",
        relation_path="",
    )
    state_only["junctionization_action_gold_status"] = "NOT_APPLICABLE"
    rows = (action_only, state_only)
    gold = build_strong_junction_relation_gold(
        rows,
        split_by_sample={row["sample_id"]: "validation" for row in rows},
    )
    assert gold[0].action_supervised
    assert not gold[0].object_set_exact_supervised
    assert not gold[0].final_relation_supervised
    assert not gold[1].action_supervised
    assert gold[1].supervision_scope == "STATE_ONLY"


def test_relation_gold_accepts_confirmed_empty_relation(tmp_path: Path) -> None:
    relation_path = tmp_path / "intersection_match_all.geojson"
    _relation(relation_path, status=1, base_id="0")
    source = _source(
        sample_id="none",
        action="failure_relation",
        main="",
        relation_path=relation_path,
    )
    gold = build_strong_junction_relation_gold(
        (source,),
        split_by_sample={"none": "test"},
    )[0]
    assert gold.acceptable_object_id_sets == ((),)
    assert gold.final_relation_supervised
    assert not gold.final_relation_expected


def _source(
    *,
    sample_id: str,
    action: str,
    main: str,
    relation_path: Path | str,
    original_nodes=(),
    grouped_nodes=(),
    original_roads=(),
    new_nodes=(),
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "case_id": sample_id,
        "source_scope": "POC_Data",
        "family": "T03",
        "label_weight": 1.0,
        "anchor_business_state": (
            "NO_RCSD_EVIDENCE" if action == "failure_relation" else "SUCCESS"
        ),
        "junctionization_action": action,
        "junctionization_action_gold_status": "READY",
        "complete_junction_gold_status": "READY",
        "selected_main_rcsdnode_id": main,
        "t05_original_rcsdnode_ids": list(original_nodes),
        "t05_grouped_rcsdnode_ids": list(grouped_nodes),
        "t05_original_rcsdroad_ids": list(original_roads),
        "t05_new_rcsdnode_ids": list(new_nodes),
        "t05_phase2_relation_path": str(relation_path),
        "terminal_business_signature": sample_id,
    }


def _relation(path: Path, *, status: int, base_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "target_id": "1",
                            "base_id": base_id,
                            "status": status,
                        },
                        "geometry": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
