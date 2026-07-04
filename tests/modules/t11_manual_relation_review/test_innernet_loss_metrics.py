from __future__ import annotations

import csv
import json

from rcsd_topo_poc.modules.t11_manual_relation_review.innernet_loss_metrics import main


def test_innernet_loss_metrics_outputs_benefit_ranked_tables(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    out_dir = tmp_path / "out"

    _write_csv(
        run_root / "t11_manual_relation_merged.csv",
        [
            {
                "case_id": "case_a",
                "target_id": "100",
                "swsd_segment_id": "seg_a",
                "manual_relation_type": "1v1_rcsd_junction",
                "selected_ids": "500",
            },
            {
                "case_id": "case_a",
                "target_id": "200",
                "swsd_segment_id": "seg_b",
                "manual_relation_type": "1v1_rcsd_junction",
                "selected_ids": "600",
            },
        ],
    )
    _write_csv(
        run_root / "t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.csv",
        [
            {"target_id": "100", "swsd_segment_id": "seg_a", "segment_length_m": "120.5"},
            {"target_id": "200", "swsd_segment_id": "seg_b", "segment_length_m": "40"},
        ],
    )
    (run_root / "intersection_match_all.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"target_id": "100", "status": "1", "base_id": "0"}},
                    {
                        "type": "Feature",
                        "properties": {
                            "target_id": "200",
                            "status": "0",
                            "base_id": "600",
                            "source_modules": "T07",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_csv(
        run_root / "relation_graph_consumability_audit.csv",
        [
            {"target_id": "200", "graph_consumable": "1", "graph_consumability_status": "base_node_graph_incident"}
        ],
    )
    _write_csv(
        run_root / "t06_step3_unreplaced_rcsd_attribution.csv",
        [
            {
                "rcsd_road_id": "r1",
                "length_m": "12",
                "final_attribution_class": "5_replaceable_scope_unreplaced",
                "final_primary_segment_id": "seg_a",
                "final_attribution_subclass": "5_replaceable_scope_not_consumed",
            },
            {
                "rcsd_road_id": "r2",
                "length_m": "30",
                "final_attribution_class": "5_replaceable_scope_unreplaced",
                "final_primary_segment_id": "seg_b",
                "final_attribution_subclass": "5_replaceable_scope_not_consumed",
            },
        ],
    )
    _write_csv(
        run_root / "t06_segment_replacement_plan.csv",
        [
            {"swsd_segment_id": "seg_a", "plan_status": "ready", "execution_scope": "standard_segment"},
            {"swsd_segment_id": "seg_b", "plan_status": "ready", "execution_scope": "standard_segment"},
        ],
    )
    _write_csv(
        run_root / "t06_step3_swsd_frcsd_segment_relation.csv",
        [
            {"swsd_segment_id": "seg_a", "relation_status": "retained_swsd", "source_mix": "source_2"},
            {"swsd_segment_id": "seg_b", "relation_status": "replaced", "source_mix": "source_1"},
        ],
    )

    assert main(["--run-root", str(run_root), "--out-dir", str(out_dir), "--top-n", "20", "--pack-top-n", "10"]) == 0

    relation_rows = _read_csv(out_dir / "relation_gain_priority.csv")
    assert relation_rows[0]["target_id"] == "100"
    assert relation_rows[0]["relation_gap_class"] == "manual_can_fix_machine_relation_failure"

    root5_segments = _read_csv(out_dir / "root5_strategy_by_segment.csv")
    assert root5_segments[0]["swsd_segment_id"] == "seg_b"
    assert root5_segments[0]["sort_benefit_m"] == "30.0"

    pack_rows = _read_csv(out_dir / "case_pack_request.csv")
    assert pack_rows[0]["swsd_segment_id"] == "seg_a"
    assert all(path.stat().st_size <= 240_000 for path in out_dir.iterdir() if path.is_file())


def _write_csv(path, rows):
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
