from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_t10_complete_gold import (
    read_t10_complete_junction_gold,
)


def test_reads_complete_t10_t05_relation_plans(tmp_path: Path) -> None:
    phase2 = tmp_path / "t05/t05_phase2"
    phase2.mkdir(parents=True)
    rows = [
        _row("1", "direct_relation", 0, selected="11"),
        _row("2", "group_existing_rcsd_nodes", 0, selected="21", grouped="21|22"),
        _row("3", "split_rcsdroad_generate_rcsdnode", 0, selected="31", roads="41|42"),
        _row("4", "failure_relation", 1),
    ]
    (phase2 / "rcsd_junctionization_audit.json").write_text(
        json.dumps({"row_count": len(rows), "rows": rows}),
        encoding="utf-8",
    )
    (phase2 / "intersection_match_all.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "target_id": row["target_id"],
                            "status": row["status"],
                            "base_id": row["selected_main_rcsdnode_id"] or 0,
                        },
                        "geometry": None,
                    }
                    for row in rows
                ],
            }
        ),
        encoding="utf-8",
    )
    (phase2 / "rcsdnode_out.gpkg").write_bytes(b"placeholder")

    gold, sources = read_t10_complete_junction_gold(tmp_path)

    assert gold["1"].complete_object_ids == ("NODE:11",)
    assert gold["2"].complete_object_ids == ("NODE:21", "NODE:22")
    assert gold["3"].complete_object_ids == ("ROAD:41", "ROAD:42")
    assert gold["4"].complete_object_ids == ()
    assert gold["3"].topology_label()["t05_original_rcsdroad_ids"] == ["41", "42"]
    assert len(sources) == 3


def _row(
    target: str,
    action: str,
    status: int,
    *,
    selected: str = "",
    grouped: str = "",
    roads: str = "",
) -> dict[str, object]:
    return {
        "target_id": target,
        "action": action,
        "status": status,
        "selected_main_rcsdnode_id": selected,
        "grouped_rcsdnode_ids": grouped,
        "original_rcsdroad_ids": roads,
        "original_rcsdnode_ids": grouped,
        "new_rcsdnode_ids": "31" if action.startswith("split_") else "",
    }
