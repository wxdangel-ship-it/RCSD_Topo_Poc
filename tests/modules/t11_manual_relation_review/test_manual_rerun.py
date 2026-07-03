from __future__ import annotations

import csv
import json
from pathlib import Path

from rcsd_topo_poc.modules.t11_manual_relation_review.manual_rerun import (
    build_t05_manual_relation_final_rejected_reports,
    compare_t06_run_metrics,
    import_t11_manual_review_xlsx_to_csv,
    read_t11_manual_review_xlsx_rows,
    resolve_t11_manual_review_xlsx_paths,
)
from rcsd_topo_poc.modules.t11_manual_relation_review.xlsx_writer import write_text_xlsx


def test_imports_actionable_manual_rows_from_three_review_xlsx_files(tmp_path: Path) -> None:
    paths = _write_three_manual_xlsx(tmp_path)

    rows, summary = read_t11_manual_review_xlsx_rows(xlsx_paths=paths, case_id="605415675")

    assert [row["target_id"] for row in rows] == ["A", "B", "C"]
    assert [row["source_manual_table"] for row in rows] == [
        "all_1v1_not_replaced",
        "all_evidence_relation_gaps",
        "no_evidence_relation_gaps",
    ]
    assert rows[0]["selected_ids"] == "RCA"
    assert rows[2]["manual_relation_type"] == "1v1_rcsd_road"
    assert summary["accepted_row_count"] == 3
    assert summary["ignored_manual_row_not_consumable_count"] == 1
    assert summary["ignored_duplicate_target_count"] == 1
    assert summary["ignored_selected_ids_null_or_empty_count"] == 1


def test_writes_merged_manual_relation_csv_and_summary(tmp_path: Path) -> None:
    paths = _write_three_manual_xlsx(tmp_path)
    out_csv = tmp_path / "manual" / "t11_manual_relation_merged.csv"

    artifacts = import_t11_manual_review_xlsx_to_csv(xlsx_paths=paths, out_csv=out_csv, case_id="605415675")

    with artifacts.manual_relation_csv.open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert len(csv_rows) == 3
    assert csv_rows[1]["target_id"] == "B"
    assert csv_rows[1]["source_manual_table"] == "all_evidence_relation_gaps"
    assert summary["manual_relation_csv"] == str(out_csv)
    assert summary["source_table_stats"]["no_evidence_relation_gaps"]["accepted_row_count"] == 1


def test_builds_t05_manual_final_rejected_and_graph_reference_reports(tmp_path: Path) -> None:
    manual_csv = tmp_path / "t11_manual_relation_merged.csv"
    t05_root = tmp_path / "t05_phase2"
    t05_root.mkdir()
    _write_csv(
        manual_csv,
        [
            {"case_id": "case", "swsd_segment_id": "seg-a", "target_id": "A", "manual_relation_type": "1v1_rcsd_junction", "selected_ids": "100"},
            {"case_id": "case", "swsd_segment_id": "seg-b", "target_id": "B", "manual_relation_type": "1v1_rcsd_road", "selected_ids": "200"},
            {"case_id": "case", "swsd_segment_id": "seg-c", "target_id": "C", "manual_relation_type": "1v1_rcsd_junction", "selected_ids": "300"},
            {"case_id": "case", "swsd_segment_id": "seg-d", "target_id": "D", "manual_relation_type": "1v1_rcsd_junction", "selected_ids": "400"},
            {"case_id": "case", "swsd_segment_id": "seg-e", "target_id": "E", "manual_relation_type": "1v1_rcsd_road", "selected_ids": "500"},
            {"case_id": "case", "swsd_segment_id": "seg-f", "target_id": "F", "manual_relation_type": "1vN_rcsd_junction", "selected_ids": "600|601"},
            {"case_id": "case", "swsd_segment_id": "seg-n", "target_id": "N", "manual_relation_type": "no_valid_relation", "selected_ids": "NULL"},
        ],
        ["case_id", "swsd_segment_id", "target_id", "manual_relation_type", "selected_ids"],
    )
    (t05_root / "intersection_match_all.geojson").write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    _write_csv(
        t05_root / "rcsd_junctionization_audit.csv",
        [
            _audit_row("A", status="0", base_id="1000", reason="t11_manual_1v1_rcsd_junction"),
            _audit_row("B", status="1", base_id="0", scene="road_only_split", reason="rcsdroad_split_failed", skipped_reason="missing_rcsdroad_id:200"),
            _audit_row("C", status="0", base_id="3000", reason="t11_manual_1v1_rcsd_junction"),
            _audit_row("D", status="0", base_id="4000", reason="t11_manual_1v1_rcsd_junction"),
            _audit_row("E", status="0", base_id="5000", scene="road_only_split", reason="road_only_projection_near_endpoint_reuse_rcsdnode"),
            _audit_row("F", status="1", base_id="0", scene="group_existing_rcsd_nodes", reason="missing_rcsdnode_ids:[601]", skipped_reason="rcsdnode_grouping_failed"),
        ],
        _AUDIT_FIELDS,
    )
    _write_csv(
        t05_root / "relation_graph_consumability_audit.csv",
        [
            {
                "target_id": "C",
                "base_id": "3000",
                "relation_status": "0",
                "graph_consumable": "0",
                "graph_consumability_status": "base_node_not_incident_to_rcsdroad",
                "recommended_action": "graph_qc",
            }
        ],
        ["target_id", "base_id", "relation_status", "graph_consumable", "graph_consumability_status", "recommended_action"],
    )
    _write_csv(t05_root / "blocking_errors.csv", [], ["target_id", "reason", "source_modules"])
    _write_csv(
        t05_root / "relation_cardinality_errors.csv",
        [
            {
                "error_type": "one_target_to_many_base",
                "target_id": "D",
                "base_id": "4000|4001",
                "related_target_ids": "D",
                "source_modules": "T11_MANUAL",
                "scenes": "direct_existing_rcsd_junction",
                "reasons": "target has multiple bases",
            },
            {
                "error_type": "many_target_to_one_base",
                "target_id": "E|Z",
                "base_id": "5000",
                "related_target_ids": "E|Z",
                "source_modules": "T11_MANUAL|T07",
                "scenes": "road_only_split",
                "reasons": "audit only",
            },
        ],
        ["error_type", "target_id", "base_id", "related_target_ids", "source_modules", "scenes", "reasons"],
    )

    artifacts = build_t05_manual_relation_final_rejected_reports(
        manual_relation_csv=manual_csv,
        t05_phase2_root=t05_root,
    )

    rejected = _read_csv(artifacts.rejected_csv)
    graph_reference = _read_csv(artifacts.graph_unconsumable_reference_csv)
    assert [row["target_id"] for row in rejected] == ["B", "D", "F"]
    assert {row["target_id"]: row["reject_category"] for row in rejected} == {
        "B": "selected_rcsdroad_missing",
        "D": "cardinality_blocked",
        "F": "selected_rcsdnode_missing",
    }
    assert [row["target_id"] for row in graph_reference] == ["C"]
    assert graph_reference[0]["reject_category"] == "graph_unconsumable_reference"
    assert artifacts.summary["manual_actionable_target_count"] == 6
    assert artifacts.summary["t05_manual_consumed_success_count"] == 3
    assert artifacts.summary["t05_final_rejected_count"] == 3
    assert artifacts.summary["graph_unconsumable_reference_count"] == 1


def test_resolves_default_three_review_workbooks(tmp_path: Path) -> None:
    paths = _write_three_manual_xlsx(tmp_path)

    resolved = resolve_t11_manual_review_xlsx_paths(manual_audit_root=tmp_path)

    assert resolved == paths


def test_compares_t06_metrics(tmp_path: Path) -> None:
    before = _write_t06_summary_tree(tmp_path / "before", final=10, replaceable=6, success=5, unreplaced=4, length=40.0)
    after = _write_t06_summary_tree(tmp_path / "after", final=12, replaceable=8, success=7, unreplaced=2, length=20.0)
    out = tmp_path / "compare.json"

    report = compare_t06_run_metrics(before_t06_root=before, after_t06_root=after, out_json=out)

    assert report["delta"]["step1_final_fusion_unit_count"] == 2
    assert report["delta"]["step3_replacement_success_count"] == 2
    assert report["delta"]["unreplaced_rcsd_road_count"] == -2
    assert report["before"]["rcsd_replaced_length_rate_percent"] == 60.0
    assert report["after"]["rcsd_replaced_length_rate_percent"] == 80.0
    assert out.is_file()


def _write_three_manual_xlsx(root: Path) -> dict[str, Path]:
    all_1v1 = root / "t11_segments_all_1v1_relation_success_but_not_replaced.xlsx"
    all_evidence = root / "t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.xlsx"
    no_evidence = root / "t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.xlsx"
    fields = [
        "case_id",
        "swsd_segment_id",
        "target_id",
        "manual_row_consumable",
        "manual_relation_type",
        "selected_ids",
        "comment",
    ]
    write_text_xlsx(
        all_1v1,
        [
            {
                "case_id": "605415675",
                "swsd_segment_id": "seg-a",
                "target_id": "A",
                "manual_row_consumable": "1",
                "manual_relation_type": "1v1_rcsd_junction",
                "selected_ids": "RCA",
                "comment": "all 1v1 diagnostic manual override",
            }
        ],
        fields,
        sheet_name="all_1v1_not_replaced",
    )
    write_text_xlsx(
        all_evidence,
        [
            {
                "case_id": "605415675",
                "swsd_segment_id": "seg-b",
                "target_id": "B",
                "manual_row_consumable": "1",
                "manual_relation_type": "1vN_rcsd_junction",
                "selected_ids": "RCB1|RCB2",
                "comment": "accepted",
            },
            {
                "case_id": "605415675",
                "swsd_segment_id": "seg-b2",
                "target_id": "B",
                "manual_row_consumable": "1",
                "manual_relation_type": "1v1_rcsd_junction",
                "selected_ids": "RCB3",
                "comment": "duplicate ignored",
            },
            {
                "case_id": "605415675",
                "swsd_segment_id": "seg-d",
                "target_id": "D",
                "manual_row_consumable": "0",
                "manual_relation_type": "1v1_rcsd_junction",
                "selected_ids": "RCD",
                "comment": "duplicate_of_segment:seg-x;do_not_consume_duplicate_row",
            },
        ],
        fields,
        sheet_name="all_evidence",
        validation_field="manual_relation_type",
        validation_values=("1v1_rcsd_junction", "1vN_rcsd_junction"),
    )
    write_text_xlsx(
        no_evidence,
        [
            {
                "case_id": "605415675",
                "swsd_segment_id": "seg-c",
                "target_id": "C",
                "manual_row_consumable": "1",
                "manual_relation_type": "1v1_rcsd_road",
                "selected_ids": "RCC",
                "comment": "",
            },
            {
                "case_id": "605415675",
                "swsd_segment_id": "seg-null",
                "target_id": "N",
                "manual_row_consumable": "1",
                "manual_relation_type": "1v1_rcsd_junction",
                "selected_ids": "NULL",
                "comment": "manual no rcsd",
            },
        ],
        fields,
        sheet_name="no_evidence",
    )
    return {
        "all_1v1_not_replaced": all_1v1,
        "all_evidence_relation_gaps": all_evidence,
        "no_evidence_relation_gaps": no_evidence,
    }


_AUDIT_FIELDS = [
    "target_id",
    "surface_id",
    "source_module",
    "source_case_id",
    "scene",
    "action",
    "status",
    "base_id",
    "reason",
    "original_rcsdroad_ids",
    "new_rcsdroad_ids",
    "original_rcsdnode_ids",
    "new_rcsdnode_ids",
    "grouped_rcsdnode_ids",
    "selected_main_rcsdnode_id",
    "projection_point_count",
    "split_point_count",
    "skipped_reason",
    "geometry_mode",
    "multi_base_relation",
    "blocking_error",
]


def _audit_row(
    target_id: str,
    *,
    status: str,
    base_id: str,
    scene: str = "direct_existing_rcsd_junction",
    action: str = "direct_relation",
    reason: str,
    skipped_reason: str = "",
) -> dict[str, str]:
    return {
        "target_id": target_id,
        "surface_id": f"T11_MANUAL:{target_id}",
        "source_module": "T11_MANUAL",
        "source_case_id": "case",
        "scene": scene,
        "action": action,
        "status": status,
        "base_id": base_id,
        "reason": reason,
        "original_rcsdroad_ids": "",
        "new_rcsdroad_ids": "",
        "original_rcsdnode_ids": "",
        "new_rcsdnode_ids": "",
        "grouped_rcsdnode_ids": "",
        "selected_main_rcsdnode_id": base_id if status == "0" else "0",
        "projection_point_count": "0",
        "split_point_count": "0",
        "skipped_reason": skipped_reason,
        "geometry_mode": "success_line" if status == "0" else "zero_length_no_rcsd",
        "multi_base_relation": "0",
        "blocking_error": "0",
    }


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_t06_summary_tree(root: Path, *, final: int, replaceable: int, success: int, unreplaced: int, length: float) -> Path:
    step1 = root / "step1_identify_fusion_units"
    step2 = root / "step2_extract_rcsd_segments"
    step3 = root / "step3_segment_replacement"
    step1.mkdir(parents=True)
    step2.mkdir(parents=True)
    step3.mkdir(parents=True)
    (step1 / "t06_step1_summary.json").write_text(
        json.dumps(
            {
                "final_fusion_unit_count": final,
                "manual_relation_anchor_override_segment_count": 1,
                "manual_relation_evd_override_segment_count": 2,
            }
        ),
        encoding="utf-8",
    )
    (step2 / "t06_step2_summary.json").write_text(
        json.dumps({"replaceable_count": replaceable, "replacement_plan_ready_count": replaceable + 1}),
        encoding="utf-8",
    )
    (step3 / "t06_step3_summary.json").write_text(
        json.dumps(
            {
                "replacement_unit_success_count": success,
                "removed_swsd_road_count": success * 2,
                "added_rcsd_road_count": success * 3,
                "frcsd_road_count": 100 + success,
            }
        ),
        encoding="utf-8",
    )
    (step3 / "t06_step3_unreplaced_rcsd_attribution_summary.json").write_text(
        json.dumps(
            {
                "unreplaced_rcsd_road_count": unreplaced,
                "unreplaced_rcsd_road_length_m": length,
                "by_attribution_class": [
                    {
                        "value": "5_replaceable_scope_unreplaced",
                        "count": unreplaced,
                        "length_m": length,
                        "total_length_rate": length / 100.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root
