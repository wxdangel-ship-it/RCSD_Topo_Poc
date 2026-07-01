from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_output_slimming import (
    COMPACT_SCHEMA_VERSION,
    DETAIL_METRICS_NAME,
    OUTPUT_MANIFEST_NAME,
    compact_step3_outputs,
)


def test_compact_step3_outputs_keeps_core_summary_and_moves_details(tmp_path: Path) -> None:
    step_root = tmp_path / "step3_segment_replacement"
    step_root.mkdir()
    for name in (
        "t06_frcsd_road.gpkg",
        "t06_frcsd_road.csv",
        "t06_frcsd_road.json",
        "t06_step3_topology_connectivity_audit.gpkg",
        "t06_step3_topology_connectivity_audit.csv",
    ):
        (step_root / name).write_text("x", encoding="utf-8")
    summary_path = step_root / "t06_step3_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_id": "case1",
                "input_paths": {"step2_replaceable_path": "replaceable.gpkg"},
                "params": {"source_field_name": "source"},
                "input_replaceable_count": 10,
                "input_replacement_plan_count": 12,
                "replacement_plan_source": "step2_replacement_plan",
                "replacement_unit_count": 12,
                "replacement_unit_success_count": 11,
                "replacement_unit_failure_count": 1,
                "frcsd_road_count": 20,
                "segment_relation_replaced_count": 8,
                "topology_connectivity_fail_count": 2,
                "group_path_corridor_coverage_fallback_segments": ["s1", "s2"],
                "outputs": {
                    "frcsd_road_gpkg": str(step_root / "t06_frcsd_road.gpkg"),
                    "frcsd_road_csv": str(step_root / "t06_frcsd_road.csv"),
                    "frcsd_road_json": str(step_root / "t06_frcsd_road.json"),
                    "topology_connectivity_audit_gpkg": str(step_root / "t06_step3_topology_connectivity_audit.gpkg"),
                    "topology_connectivity_audit_csv": str(step_root / "t06_step3_topology_connectivity_audit.csv"),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    compact = compact_step3_outputs(step_root)

    assert compact["summary_schema"] == COMPACT_SCHEMA_VERSION
    assert compact["replacement_unit_success_count"] == 11
    assert compact["topology_connectivity_fail_count"] == 2
    assert "frcsd_road_json" not in compact["outputs"]
    assert compact["outputs"]["frcsd_road_gpkg"].endswith("t06_frcsd_road.gpkg")
    detail = json.loads((step_root / DETAIL_METRICS_NAME).read_text(encoding="utf-8"))
    assert detail["group_path_corridor_coverage_fallback_segments"] == ["s1", "s2"]
    manifest = json.loads((step_root / OUTPUT_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["file_count"] >= 5
    assert any(item["name"] == "t06_frcsd_road.json" for item in manifest["files"])
