from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t11_manual_relation_review import extract_t11_relation_repair_candidates


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _fixture_case_root(tmp_path: Path) -> Path:
    root = tmp_path / "cases" / "605415675"
    nodes = gpd.GeoDataFrame(
        [
            {"id": "A", "mainnodeid": None, "kind_2": 4, "has_evd": "yes", "is_anchor": "no", "geometry": Point(0, 0)},
            {"id": "B", "mainnodeid": None, "kind_2": 8, "has_evd": "yes", "is_anchor": "yes", "geometry": Point(10, 0)},
            {"id": "C", "mainnodeid": None, "kind_2": 16, "has_evd": "no", "is_anchor": "no", "geometry": Point(20, 0)},
            {"id": "D", "mainnodeid": None, "kind_2": 2048, "has_evd": "yes", "is_anchor": "no", "geometry": Point(30, 0)},
            {"id": "E_ALIAS", "mainnodeid": "E", "kind_2": 0, "has_evd": "", "is_anchor": "", "geometry": Point(35, 0)},
            {"id": "E", "mainnodeid": None, "kind_2": 4, "has_evd": "yes", "is_anchor": "yes", "geometry": Point(40, 0)},
            {"id": "P", "mainnodeid": None, "kind_2": 4, "has_evd": "yes", "is_anchor": "yes", "geometry": Point(50, 0)},
            {"id": "Q", "mainnodeid": None, "kind_2": 4, "has_evd": "yes", "is_anchor": "yes", "geometry": Point(60, 0)},
            {"id": "F", "mainnodeid": None, "kind_2": 4, "has_evd": "no", "is_anchor": "no", "geometry": Point(55, 0)},
        ],
        crs="EPSG:3857",
    )
    (root / "t04" / "t04").mkdir(parents=True)
    nodes.to_file(root / "t04" / "t04" / "nodes.gpkg", driver="GPKG", layer="nodes")

    segments = gpd.GeoDataFrame(
        [
            {"id": "seg1", "pair_nodes": "A,B", "junc_nodes": "", "geometry": LineString([(0, 0), (100, 0)])},
            {"id": "seg2", "pair_nodes": "C,D", "junc_nodes": "", "geometry": LineString([(0, 0), (60, 0)])},
            {"id": "seg3", "pair_nodes": "A,C", "junc_nodes": "", "geometry": LineString([(0, 0), (10, 0)])},
            {"id": "seg4", "pair_nodes": "E", "junc_nodes": "", "geometry": LineString([(0, 0), (40, 0)])},
            {"id": "seg5", "pair_nodes": "P,Q", "junc_nodes": "F", "geometry": LineString([(0, 0), (200, 0)])},
            {"id": "seg6", "pair_nodes": "P,Q", "junc_nodes": "", "sgrade": "0-0双", "geometry": LineString([(0, 0), (150, 0)])},
        ],
        crs="EPSG:3857",
    )
    (root / "t01").mkdir(parents=True)
    segments.to_file(root / "t01" / "segment.gpkg", driver="GPKG", layer="segment")
    roads = gpd.GeoDataFrame(
        [
            {"id": "r_pf", "snodeid": "P", "enodeid": "F", "formway": 0, "geometry": LineString([(50, 0), (55, 0)])},
            {"id": "r_fq", "snodeid": "F", "enodeid": "Q", "formway": 0, "geometry": LineString([(55, 0), (60, 0)])},
            {"id": "r_right", "snodeid": "F", "enodeid": "X", "formway": 128, "geometry": LineString([(55, 0), (55, 10)])},
        ],
        crs="EPSG:3857",
    )
    roads.to_file(root / "t01" / "roads.gpkg", driver="GPKG", layer="roads")

    step1 = root / "t06_step12" / "t06" / "step1_identify_fusion_units"
    _write_csv(
        step1 / "t06_swsd_segment_final_fusion_units.csv",
        [
            {"swsd_segment_id": "seg1", "pair_nodes": "['A','B']", "junc_nodes": "[]", "semantic_node_set": "['A','B']"},
            {"swsd_segment_id": "seg2", "pair_nodes": "['C','D']", "junc_nodes": "[]", "semantic_node_set": "['C','D']"},
            {"swsd_segment_id": "seg3", "pair_nodes": "['A','C']", "junc_nodes": "[]", "semantic_node_set": "['A','C']"},
            {"swsd_segment_id": "seg4", "pair_nodes": "['E']", "junc_nodes": "[]", "semantic_node_set": "['E']"},
            {"swsd_segment_id": "seg5", "pair_nodes": "['P','Q']", "junc_nodes": "['F']", "semantic_node_set": "['P','Q','F']"},
            {"swsd_segment_id": "seg6", "pair_nodes": "['P','Q']", "junc_nodes": "[]", "semantic_node_set": "['P','Q']"},
        ],
        ["swsd_segment_id", "pair_nodes", "junc_nodes", "semantic_node_set"],
    )

    t05 = root / "t05" / "t05_phase2"
    _write_csv(
        t05 / "relation_graph_consumability_audit.csv",
        [
            {
                "target_id": "A",
                "base_id": "RCA",
                "relation_status": "0",
                "graph_consumable": "1",
                "graph_consumability_status": "base_node_graph_incident",
                "matched_rcsdnode_ids": "RCA",
                "incident_rcsdnode_ids": "RCA",
                "source_modules": "T05",
                "reasons": "success",
            },
            {
                "target_id": "B",
                "base_id": "RCB",
                "relation_status": "0",
                "graph_consumable": "0",
                "graph_consumability_status": "base_node_not_incident_to_rcsdroad",
                "matched_rcsdnode_ids": "RCB",
                "incident_rcsdnode_ids": "",
                "source_modules": "T05",
                "reasons": "not consumable",
            },
            {
                "target_id": "E",
                "base_id": "RCE",
                "relation_status": "0",
                "graph_consumable": "1",
                "graph_consumability_status": "base_node_graph_incident",
                "matched_rcsdnode_ids": "RCE",
                "incident_rcsdnode_ids": "RCE",
                "source_modules": "T05",
                "reasons": "success",
            },
            {
                "target_id": "P",
                "base_id": "RCP",
                "relation_status": "0",
                "graph_consumable": "1",
                "graph_consumability_status": "base_node_graph_incident",
                "matched_rcsdnode_ids": "RCP",
                "incident_rcsdnode_ids": "RCP",
                "source_modules": "T05",
                "reasons": "success",
            },
            {
                "target_id": "Q",
                "base_id": "RCQ",
                "relation_status": "0",
                "graph_consumable": "1",
                "graph_consumability_status": "base_node_graph_incident",
                "matched_rcsdnode_ids": "RCQ",
                "incident_rcsdnode_ids": "RCQ",
                "source_modules": "T05",
                "reasons": "success",
            },
        ],
        [
            "target_id",
            "base_id",
            "relation_status",
            "graph_consumable",
            "graph_consumability_status",
            "matched_rcsdnode_ids",
            "incident_rcsdnode_ids",
            "source_modules",
            "reasons",
        ],
    )
    _write_csv(
        t05 / "rcsd_junctionization_audit.csv",
        [
            {
                "target_id": "C",
                "status": "1",
                "reason": "no_evidence_junctionization_skipped",
                "original_rcsdroad_ids": "",
                "new_rcsdroad_ids": "",
                "original_rcsdnode_ids": "",
                "new_rcsdnode_ids": "RCC",
                "grouped_rcsdnode_ids": "",
                "selected_main_rcsdnode_id": "",
            }
        ],
        [
            "target_id",
            "status",
            "reason",
            "original_rcsdroad_ids",
            "new_rcsdroad_ids",
            "original_rcsdnode_ids",
            "new_rcsdnode_ids",
            "grouped_rcsdnode_ids",
            "selected_main_rcsdnode_id",
        ],
    )

    step2 = root / "t06_step12" / "t06" / "step2_extract_rcsd_segments"
    _write_csv(
        step2 / "t06_segment_replacement_problem_registry.csv",
        [
            {
                "swsd_segment_id": "seg1",
                "problem_status": "requires_upstream_iteration",
                "root_cause_category": "pair_anchor_mismatch",
                "failure_business_category": "pair_anchor_mismatch",
                "reject_reason": "invalid_pair_relation_status",
                "swsd_pair_nodes": "['A','B']",
                "swsd_junc_nodes": "[]",
                "rcsd_pair_nodes": "['RCA','RCB']",
                "candidate_rcsd_pair_node_sets": "[['RCA','RCB']]",
                "pair_anchor_error_swsd_nodes": "['B']",
            }
        ],
        [
            "swsd_segment_id",
            "problem_status",
            "root_cause_category",
            "failure_business_category",
            "reject_reason",
            "swsd_pair_nodes",
            "swsd_junc_nodes",
            "rcsd_pair_nodes",
            "candidate_rcsd_pair_node_sets",
            "pair_anchor_error_swsd_nodes",
        ],
    )
    _write_csv(
        step2 / "t06_rcsd_segment_rejected.csv",
        [
            {
                "swsd_segment_id": "seg2",
                "reject_stage": "relation_mapping",
                "reject_reason": "invalid_pair_relation_status",
                "root_cause_category": "",
                "failed_pair_nodes": "['C']",
                "failed_junc_nodes": "[]",
            },
            {
                "swsd_segment_id": "seg3",
                "reject_stage": "buffer_segment_extraction",
                "reject_reason": "required_semantic_nodes_not_connected_in_buffer",
                "root_cause_category": "buffer_candidate_required_nodes_disconnected",
                "failed_pair_nodes": "['A','C']",
                "failed_junc_nodes": "[]",
            },
        ],
        [
            "swsd_segment_id",
            "reject_stage",
            "reject_reason",
            "root_cause_category",
            "failed_pair_nodes",
            "failed_junc_nodes",
        ],
    )
    _write_csv(
        step2 / "t06_rcsd_buffer_segment_rejected.csv",
        [
            {
                "swsd_segment_id": "seg2",
                "reject_reason": "required_semantic_nodes_not_connected_in_buffer",
                "root_cause_category": "buffer_candidate_required_nodes_disconnected",
                "required_rcsd_nodes": "['RCC']",
                "candidate_rcsd_road_ids": "['roadC']",
                "candidate_rcsd_node_ids": "['RCC']",
            }
        ],
        [
            "swsd_segment_id",
            "reject_reason",
            "root_cause_category",
            "required_rcsd_nodes",
            "candidate_rcsd_road_ids",
            "candidate_rcsd_node_ids",
        ],
    )
    _write_csv(
        step2 / "t06_segment_replacement_plan.csv",
        [
            {
                "swsd_segment_id": "seg3",
                "plan_status": "blocked",
                "execution_action": "hold",
                "source_reason": "junction_alignment_to_retained_swsd_exceeds_topology_gate",
                "swsd_pair_nodes": "['A','C']",
                "swsd_junc_nodes": "[]",
                "rcsd_road_ids": "['roadA']",
                "rcsd_pair_nodes": "['RCA','RCC']",
            }
            ,
            {
                "swsd_segment_id": "seg4",
                "plan_status": "blocked",
                "execution_action": "hold",
                "source_reason": "junction_alignment_to_retained_swsd_exceeds_topology_gate",
                "swsd_pair_nodes": "['E']",
                "swsd_junc_nodes": "[]",
                "rcsd_road_ids": "['roadE']",
                "rcsd_pair_nodes": "['RCE']",
            },
        ],
        [
            "swsd_segment_id",
            "plan_status",
            "execution_action",
            "source_reason",
            "swsd_pair_nodes",
            "swsd_junc_nodes",
            "rcsd_road_ids",
            "rcsd_pair_nodes",
        ],
    )
    _write_csv(
        step2 / "t06_rcsd_repair_candidates.csv",
        [
            {
                "swsd_segment_id": "seg1",
                "candidate_rcsd_road_ids": "['roadAB']",
                "candidate_rcsd_node_ids": "['RCA','RCB']",
                "candidate_rcsd_pair_node_sets": "[['RCA','RCB']]",
            }
        ],
        ["swsd_segment_id", "candidate_rcsd_road_ids", "candidate_rcsd_node_ids", "candidate_rcsd_pair_node_sets"],
    )
    step3 = root / "t06_step12" / "t06" / "step3_segment_replacement"
    _write_csv(
        step3 / "t06_step3_swsd_frcsd_segment_relation.csv",
        [
            {
                "swsd_segment_id": "seg6",
                "relation_status": "retained_swsd",
                "relation_reason": "retained_swsd_segment",
            }
        ],
        ["swsd_segment_id", "relation_status", "relation_reason"],
    )
    return root


def _read_candidates(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"target_id": str})


def test_extract_aggregates_t06_rows_and_classifies_candidates(tmp_path: Path) -> None:
    artifacts = extract_t11_relation_repair_candidates(
        t10_case_root=_fixture_case_root(tmp_path),
        out_root=tmp_path / "out",
        case_id="605415675",
    )
    rows = _read_candidates(artifacts.candidates_csv)

    assert set(rows["target_id"]) == {"A", "B", "C", "D"}
    row_a = rows.set_index("target_id").loc["A"]
    row_b = rows.set_index("target_id").loc["B"]
    row_c = rows.set_index("target_id").loc["C"]

    assert row_a["affected_segment_count"] == 2
    assert "relation_missing_or_invalid" in row_a["candidate_category"]
    assert "required_nodes_disconnected_or_pair_anchor_issue" in row_a["candidate_category"]
    assert "relation_graph_unconsumable" in row_b["candidate_category"]
    assert "no_evidence_but_rcsd_present_in_segment_scope" in row_c["candidate_category"]
    assert row_c["has_rcsd_in_segment_scope"]
    assert "roadC" in row_c["machine_candidate_rcsdroad_ids"]


def test_priority_sorts_by_segment_count_then_length(tmp_path: Path) -> None:
    artifacts = extract_t11_relation_repair_candidates(
        t10_case_root=_fixture_case_root(tmp_path),
        out_root=tmp_path / "out",
        case_id="605415675",
    )
    rows = _read_candidates(artifacts.candidates_csv)

    assert list(rows["target_id"])[:2] == ["A", "C"]
    assert rows.iloc[0]["affected_segment_total_length_m"] == 110.0
    assert rows.iloc[1]["affected_segment_total_length_m"] == 70.0


def test_manual_template_contains_only_candidates_without_prefill(tmp_path: Path) -> None:
    artifacts = extract_t11_relation_repair_candidates(
        t10_case_root=_fixture_case_root(tmp_path),
        out_root=tmp_path / "out",
        case_id="605415675",
    )

    with artifacts.manual_template_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert {row["target_id"] for row in rows} == {"A", "B", "C", "D"}
    assert all(row["manual_relation_type"] == "" for row in rows)
    assert all(row["selected_ids"] == "" for row in rows)


def test_outputs_summary_and_qgis_readable_gpkg(tmp_path: Path) -> None:
    artifacts = extract_t11_relation_repair_candidates(
        t10_case_root=_fixture_case_root(tmp_path),
        out_root=tmp_path / "out",
        case_id="605415675",
    )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    gpkg = gpd.read_file(artifacts.candidates_gpkg)

    assert summary["candidate_count"] == 4
    assert summary["quality_checks"]["topology"]["status"] == "audit_only"
    assert gpkg.crs.to_string() == "EPSG:3857"
    assert len(gpkg) == 4


def test_segment_anchor_audit_is_lean_sorted_and_prefilled(tmp_path: Path) -> None:
    manual_csv = tmp_path / "manual.csv"
    _write_csv(
        manual_csv,
        [
            {
                "case_id": "605415675",
                "target_id": "C",
                "manual_relation_type": "1v1_rcsd_junction",
                "selected_ids": "RCC",
                "comment": "keep",
            }
        ],
        ["case_id", "target_id", "manual_relation_type", "selected_ids", "comment"],
    )
    artifacts = extract_t11_relation_repair_candidates(
        t10_case_root=_fixture_case_root(tmp_path),
        out_root=tmp_path / "out",
        case_id="605415675",
        existing_manual_csv_path=manual_csv,
    )

    rows = pd.read_csv(artifacts.anchor_audit_csv, dtype={"target_id": str})

    assert "candidate_reason" not in rows.columns
    assert "source_modules" not in rows.columns
    assert "E" not in set(rows["target_id"])
    assert "F" not in set(rows["target_id"])
    assert set(rows["target_id"]) >= {"A", "B", "C", "D"}
    assert rows.iloc[0]["has_rcsd_in_segment_scope"]
    assert rows.iloc[0]["highest_priority_segment_length_m"] >= rows.iloc[1]["highest_priority_segment_length_m"]

    row_c = rows.set_index("target_id").loc["C"]
    assert row_c["manual_relation_type"] == "1v1_rcsd_junction"
    assert row_c["selected_ids"] == "RCC"
    assert row_c["comment"] == "keep"


def test_outputs_all_1v1_relation_success_but_not_replaced_segments(tmp_path: Path) -> None:
    artifacts = extract_t11_relation_repair_candidates(
        t10_case_root=_fixture_case_root(tmp_path),
        out_root=tmp_path / "out",
        case_id="605415675",
    )

    rows = pd.read_csv(artifacts.all_1v1_not_replaced_csv, dtype=str)
    gpkg = gpd.read_file(artifacts.all_1v1_not_replaced_gpkg)
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    with zipfile.ZipFile(artifacts.all_1v1_not_replaced_xlsx) as workbook:
        assert "xl/worksheets/sheet1.xml" in workbook.namelist()

    assert list(rows["swsd_segment_id"]) == ["seg5", "seg6", "seg4"]
    row = rows.set_index("swsd_segment_id").loc["seg5"]
    assert row["relation_target_ids"] == "P|Q"
    assert row["relation_base_ids"] == "RCP|RCQ"
    assert row["t06_step3_relation_status"] == "missing_step3_relation"
    assert rows.set_index("swsd_segment_id").loc["seg6"]["t06_step3_relation_status"] == "retained_swsd"
    assert rows.set_index("swsd_segment_id").loc["seg4"]["t06_step3_relation_status"] == "missing_step3_relation"
    assert summary["segments_all_1v1_relation_success_but_not_replaced"]["row_count"] == 3
    assert len(gpkg) == 3


def test_outputs_unreplaced_segment_relation_gap_rows(tmp_path: Path) -> None:
    artifacts = extract_t11_relation_repair_candidates(
        t10_case_root=_fixture_case_root(tmp_path),
        out_root=tmp_path / "out",
        case_id="605415675",
    )

    rows = pd.read_csv(artifacts.unreplaced_relation_gap_csv, dtype=str).fillna("")
    gpkg = gpd.read_file(artifacts.unreplaced_relation_gap_gpkg)
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    with zipfile.ZipFile(artifacts.unreplaced_relation_gap_xlsx) as workbook:
        assert "xl/worksheets/sheet1.xml" in workbook.namelist()

    assert "seg6" not in set(rows["swsd_segment_id"])
    assert "seg4" not in set(rows["swsd_segment_id"])
    assert set(rows.loc[rows["swsd_segment_id"] == "seg1", "target_id"]) == {"B"}
    row_b = rows.set_index(["swsd_segment_id", "target_id"]).loc[("seg1", "B")]
    assert row_b["relation_gap_category"] == "relation_graph_unconsumable"
    assert row_b["node_role"] == "pair_node"
    assert summary["unreplaced_segment_relation_gap_audit"]["row_count"] == len(rows)
    assert len(gpkg) == len(rows)


def test_outputs_three_segment_review_tables_with_dropdown_and_duplicates(tmp_path: Path) -> None:
    artifacts = extract_t11_relation_repair_candidates(
        t10_case_root=_fixture_case_root(tmp_path),
        out_root=tmp_path / "out",
        case_id="605415675",
    )

    all_evidence = pd.read_csv(artifacts.all_evidence_relation_gap_csv, dtype=str).fillna("")
    no_evidence = pd.read_csv(artifacts.no_evidence_relation_gap_csv, dtype=str).fillna("")
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    with zipfile.ZipFile(artifacts.all_evidence_relation_gap_xlsx) as workbook:
        sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
    with zipfile.ZipFile(artifacts.no_evidence_relation_gap_xlsx) as workbook:
        no_evidence_sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert list(all_evidence.columns) == list(no_evidence.columns)
    assert set(all_evidence["swsd_segment_id"]) == {"seg1"}
    assert set(all_evidence["target_id"]) == {"B"}
    assert set(no_evidence["swsd_segment_id"]) == {"seg2", "seg3"}
    assert set(no_evidence.loc[no_evidence["swsd_segment_id"] == "seg2", "target_id"]) == {"C", "D"}

    duplicate_c = no_evidence.set_index(["swsd_segment_id", "target_id"]).loc[("seg3", "C")]
    assert duplicate_c["duplicate_target_first_segment_id"] == "seg2"
    assert duplicate_c["manual_row_consumable"] == "0"
    assert "do_not_consume_duplicate_row" in duplicate_c["comment"]
    assert "dataValidations" in sheet_xml
    assert "NULL" in sheet_xml
    assert "dataValidations" in no_evidence_sheet_xml
    assert summary["segment_relation_review_tables"]["table_2_all_junctions_have_evidence_relation_gaps"]["row_count"] == len(all_evidence)
    assert summary["segment_relation_review_tables"]["table_3_has_no_evidence_junction_relation_gaps"]["row_count"] == len(no_evidence)
