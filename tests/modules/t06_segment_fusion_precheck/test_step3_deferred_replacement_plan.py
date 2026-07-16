from __future__ import annotations

import json

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_output_slimming import (
    retire_intermediate_step3_plan,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_replacement_plan_reader import (
    defer_replacement_plan_writes,
    materialize_deferred_replacement_plan,
    read_replacement_plan_rows,
    write_replacement_plan_json,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_replacement_unit_support import (
    _resolve_replacement_plan_path,
)


def _rows() -> list[dict[str, object]]:
    return [
        {
            "type": "Feature",
            "properties": {"replacement_plan_id": "plan-1", "plan_status": "ready"},
            "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
        }
    ]


def test_deferred_plan_is_read_in_memory_and_only_final_plan_is_materialized(tmp_path) -> None:
    candidate = tmp_path / "candidate.json"
    final = tmp_path / "final.json"
    rows = _rows()

    with defer_replacement_plan_writes():
        write_replacement_plan_json(candidate, rows)
        assert not candidate.exists()
        assert _resolve_replacement_plan_path(
            step2_replaceable_path=tmp_path / "replaceable.gpkg",
            explicit_path=candidate,
        ) == candidate
        first_read = read_replacement_plan_rows(candidate)
        first_read[0]["properties"]["plan_status"] = "mutated"
        assert read_replacement_plan_rows(candidate)[0]["properties"]["plan_status"] == "ready"

        write_replacement_plan_json(final, rows)
        assert retire_intermediate_step3_plan(candidate, final)
        assert not materialize_deferred_replacement_plan(candidate)
        assert materialize_deferred_replacement_plan(final)

    payload = json.loads(final.read_text(encoding="utf-8"))
    assert payload == {"row_count": 1, "features": rows}


def test_plan_write_remains_immediate_outside_deferred_scope(tmp_path) -> None:
    path = tmp_path / "plan.json"
    write_replacement_plan_json(path, _rows())
    assert path.is_file()
    assert read_replacement_plan_rows(path)[0]["properties"]["replacement_plan_id"] == "plan-1"
