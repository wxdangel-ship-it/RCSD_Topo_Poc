from __future__ import annotations

import csv
import json
from pathlib import Path

from rcsd_topo_poc.modules.t11_manual_relation_review.manual_rerun import (
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
