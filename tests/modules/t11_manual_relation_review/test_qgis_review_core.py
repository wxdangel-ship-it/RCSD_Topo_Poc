from __future__ import annotations

import json
import zipfile
from configparser import ConfigParser
from pathlib import Path

from rcsd_topo_poc.modules.t11_manual_relation_review.qgis_review.excel_sync import (
    read_xlsx_rows,
    update_manual_fields,
)
from rcsd_topo_poc.modules.t11_manual_relation_review.qgis_review.ids import (
    extract_rcsdnode_selected_ids,
    extract_rcsdroad_selected_ids,
    join_selected_ids,
    parse_selected_ids,
)
from rcsd_topo_poc.modules.t11_manual_relation_review.qgis_review.layer_validation import (
    LayerDescriptor,
    LayerExpectation,
    expectations_for_bound_layers,
    validate_layer_bindings,
)
from rcsd_topo_poc.modules.t11_manual_relation_review.qgis_review.task_index import (
    load_review_tasks,
    write_task_index_json,
)
from rcsd_topo_poc.modules.t11_manual_relation_review.xlsx_writer import write_text_xlsx


FIELDS = [
    "segment_priority_rank",
    "segment_priority_bucket",
    "case_id",
    "swsd_segment_id",
    "segment_length_m",
    "target_id",
    "manual_row_consumable",
    "manual_relation_type",
    "selected_ids",
    "comment",
]


def test_loads_sorts_and_deduplicates_review_tasks(tmp_path: Path) -> None:
    all_evidence, no_evidence = _write_review_workbooks(tmp_path)

    tasks = load_review_tasks(
        {
            "all_evidence_relation_gaps": all_evidence,
            "no_evidence_relation_gaps": no_evidence,
        }
    )

    assert [task.target_id for task in tasks] == ["T_DUP", "T_NULL", "T_ROAD"]
    assert tasks[0].workbook_path == all_evidence
    assert tasks[0].excel_row == 2
    assert tasks[1].status == "NULL"
    assert tasks[2].status == "filled"


def test_updates_only_first_deduped_excel_row_and_keeps_validation(tmp_path: Path) -> None:
    all_evidence, no_evidence = _write_review_workbooks(tmp_path)
    task = load_review_tasks([all_evidence, no_evidence])[0]

    result = update_manual_fields(
        workbook_path=task.workbook_path,
        excel_row=task.excel_row,
        values={
            "manual_relation_type": "1vN_rcsd_junction",
            "selected_ids": "M1|M2",
            "comment": "manual checked",
        },
        backup=True,
    )

    rows = [row.values for row in read_xlsx_rows(all_evidence)]
    assert rows[0]["target_id"] == "T_DUP"
    assert rows[0]["manual_relation_type"] == "1vN_rcsd_junction"
    assert rows[0]["selected_ids"] == "M1|M2"
    assert rows[0]["comment"] == "manual checked"
    assert rows[1]["target_id"] == "T_DUP"
    assert rows[1]["manual_relation_type"] == ""
    assert result.backup_path is not None and result.backup_path.is_file()
    with zipfile.ZipFile(all_evidence) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "dataValidation" in sheet_xml


def test_selected_id_helpers_use_semantic_node_id_and_dedupe() -> None:
    assert parse_selected_ids(" A |B|A|| ") == ["A", "B"]
    assert parse_selected_ids("NULL") == []
    assert join_selected_ids(["A", "B", "A", "", None]) == "A|B"
    assert (
        extract_rcsdnode_selected_ids(
            [
                {"id": "n1", "mainnodeid": "m1"},
                {"id": "n2", "mainnodeid": "0"},
                {"id": "n2", "mainnodeid": "NULL"},
            ]
        )
        == "m1|n2"
    )
    assert extract_rcsdroad_selected_ids([{"id": "r1"}, {"id": "r2"}, {"id": "r1"}]) == "r1|r2"


def test_layer_validation_reports_fields_sources_and_crs() -> None:
    layers = {
        "task_helper": LayerDescriptor(
            name="task",
            source_path="/tmp/task.gpkg",
            crs_authid="EPSG:3857",
            fields=frozenset({"workbook_path", "sheet_name", "excel_row", "target_id", "swsd_segment_id"}),
        ),
        "rcsdnode": LayerDescriptor(
            name="node",
            source_path="/tmp/rcsdnode.gpkg",
            crs_authid="EPSG:4326",
            fields=frozenset({"id"}),
        ),
    }
    expectations = {
        "task_helper": LayerExpectation(
            frozenset({"workbook_path", "sheet_name", "excel_row", "target_id", "swsd_segment_id"}),
            expected_source_path="/tmp/task.gpkg",
            expected_crs_authid="EPSG:3857",
        ),
        "rcsdnode": LayerExpectation(
            frozenset({"id", "mainnodeid"}),
            expected_source_path="/tmp/expected_rcsdnode.gpkg",
            expected_crs_authid="EPSG:3857",
        ),
    }

    result = validate_layer_bindings(layers, expectations)

    assert not result.ok
    assert any("mainnodeid" in error for error in result.errors)
    assert any("source mismatch" in error for error in result.errors)
    assert any("CRS differs" in warning for warning in result.warnings)
    assert any("multiple CRS" in warning for warning in result.warnings)


def test_task_helper_layer_is_optional_until_bound() -> None:
    layers = {
        "swsd_segment": LayerDescriptor(
            name="segment",
            source_path="/tmp/segment.gpkg",
            crs_authid="EPSG:3857",
            fields=frozenset({"id"}),
        ),
        "swsd_semantic_junction": LayerDescriptor(
            name="junction",
            source_path="/tmp/junction.gpkg",
            crs_authid="EPSG:3857",
            fields=frozenset({"id"}),
        ),
        "rcsdroad": LayerDescriptor(
            name="road",
            source_path="/tmp/road.gpkg",
            crs_authid="EPSG:3857",
            fields=frozenset({"id"}),
        ),
        "rcsdnode": LayerDescriptor(
            name="node",
            source_path="/tmp/node.gpkg",
            crs_authid="EPSG:3857",
            fields=frozenset({"id", "mainnodeid"}),
        ),
    }

    result = validate_layer_bindings(layers, expectations_for_bound_layers(layers))

    assert result.ok

    layers["task_helper"] = LayerDescriptor(
        name="wrong-helper",
        source_path="/tmp/wrong.gpkg",
        crs_authid="EPSG:3857",
        fields=frozenset({"id"}),
    )
    result = validate_layer_bindings(layers, expectations_for_bound_layers(layers))

    assert not result.ok
    assert any("task_helper missing required fields" in error for error in result.errors)


def test_writes_task_index_json(tmp_path: Path) -> None:
    all_evidence, no_evidence = _write_review_workbooks(tmp_path)
    tasks = load_review_tasks([all_evidence, no_evidence])
    out_json = tmp_path / "task_index.json"

    write_task_index_json(tasks, out_json)

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["task_count"] == 3
    assert payload["tasks"][0]["workbook_path"] == str(all_evidence)
    assert payload["tasks"][0]["excel_row"] == 2


def test_qgis_plugin_structure_and_metadata() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    plugin_root = repo_root / "qgis_plugins" / "t11_relation_review"

    for name in ["metadata.txt", "__init__.py", "plugin.py", "dock_widget.py", "path_bootstrap.py"]:
        assert (plugin_root / name).is_file()

    parser = ConfigParser()
    parser.read(plugin_root / "metadata.txt", encoding="utf-8")
    assert parser.get("general", "name") == "T11 Relation Review"
    assert parser.get("general", "qgisMinimumVersion")


def _write_review_workbooks(root: Path) -> tuple[Path, Path]:
    all_evidence = root / "t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.xlsx"
    no_evidence = root / "t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.xlsx"
    write_text_xlsx(
        all_evidence,
        [
            {
                "segment_priority_rank": "1",
                "segment_priority_bucket": "0",
                "case_id": "605415675",
                "swsd_segment_id": "seg-a",
                "segment_length_m": "200",
                "target_id": "T_DUP",
                "manual_row_consumable": "1",
            },
            {
                "segment_priority_rank": "2",
                "case_id": "605415675",
                "swsd_segment_id": "seg-b",
                "segment_length_m": "300",
                "target_id": "T_DUP",
                "manual_row_consumable": "1",
            },
            {
                "segment_priority_rank": "3",
                "case_id": "605415675",
                "swsd_segment_id": "seg-c",
                "segment_length_m": "100",
                "target_id": "T_SKIP",
                "manual_row_consumable": "0",
                "manual_relation_type": "1v1_rcsd_junction",
                "selected_ids": "SKIP",
            },
        ],
        FIELDS,
        sheet_name="all_evidence",
        validation_field="manual_relation_type",
        validation_values=("1v1_rcsd_junction", "1vN_rcsd_junction", "no_valid_relation", "uncertain"),
    )
    write_text_xlsx(
        no_evidence,
        [
            {
                "segment_priority_rank": "4",
                "segment_priority_bucket": "1",
                "case_id": "605415675",
                "swsd_segment_id": "seg-null",
                "segment_length_m": "50",
                "target_id": "T_NULL",
                "manual_row_consumable": "1",
                "manual_relation_type": "no_valid_relation",
                "selected_ids": "NULL",
            },
            {
                "segment_priority_rank": "5",
                "segment_priority_bucket": "2",
                "case_id": "605415675",
                "swsd_segment_id": "seg-road",
                "segment_length_m": "40",
                "target_id": "T_ROAD",
                "manual_row_consumable": "1",
                "manual_relation_type": "1v1_rcsd_road",
                "selected_ids": "R1",
            },
        ],
        FIELDS,
        sheet_name="no_evidence",
    )
    return all_evidence, no_evidence
