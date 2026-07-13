from __future__ import annotations


import ast


import csv


import json


import time


import zipfile


from collections import Counter, defaultdict


from dataclasses import dataclass


from datetime import datetime, timezone


from pathlib import Path


from typing import Any, Iterable


from xml.sax.saxutils import escape


import geopandas as gpd


import pandas as pd


from .segment_tables import (
    SEGMENT_RELATION_GAP_REVIEW_FIELDS,
    build_segment_relation_review_tables,
    write_review_xlsx,
)


from .xlsx_writer import write_text_xlsx


MANUAL_RELATION_TYPES = (
    "1v1_rcsd_junction",
    "1vN_rcsd_junction",
    "1v1_rcsd_road",
    "1vN_rcsd_road",
    "no_valid_relation",
    "uncertain",
)


CANDIDATE_FIELDS = (
    "case_id",
    "target_id",
    "kind_2",
    "has_evd",
    "is_anchor",
    "candidate_category",
    "candidate_reason",
    "source_modules",
    "t05_status",
    "t05_reason",
    "graph_consumable",
    "graph_consumability_status",
    "has_rcsd_in_segment_scope",
    "machine_candidate_rcsdnode_ids",
    "machine_candidate_rcsdroad_ids",
    "affected_segment_count",
    "affected_segment_total_length_m",
    "affected_segment_ids",
    "rejected_segment_count",
    "t06_reject_reasons",
    "root_cause_categories",
    "priority_rank",
    "priority_score",
    "recommended_manual_relation_types",
)


MANUAL_TEMPLATE_FIELDS = (
    "case_id",
    "target_id",
    "manual_relation_type",
    "selected_ids",
    "comment",
)


ANCHOR_AUDIT_FIELDS = (
    "anchor_priority_rank",
    "case_id",
    "target_id",
    "anchor_gap_category",
    "review_focus",
    "highest_priority_segment_id",
    "highest_priority_segment_length_m",
    "affected_segment_count",
    "affected_segment_total_length_m",
    "affected_segment_ids",
    "node_roles",
    "segment_pair_nodes",
    "segment_junc_nodes",
    "kind_2",
    "has_evd",
    "is_anchor",
    "t05_status",
    "t05_reason",
    "graph_consumable",
    "graph_consumability_status",
    "has_rcsd_in_segment_scope",
    "machine_candidate_rcsdnode_ids",
    "machine_candidate_rcsdroad_ids",
    "t06_reject_reasons",
    "review_hint",
    "recommended_manual_relation_types",
    "manual_relation_type",
    "selected_ids",
    "comment",
)


SEGMENT_ALL_1V1_NOT_REPLACED_FIELDS = (
    "segment_rank_by_length",
    "case_id",
    "swsd_segment_id",
    "segment_length_m",
    "sgrade",
    "segment_pair_nodes",
    "segment_junc_nodes",
    "relation_target_ids",
    "relation_base_ids",
    "all_junction_relation_success_1v1_consumable",
    "segment_has_t06_rcsd_scope",
    "t06_step2_plan_status",
    "t06_step2_reject_reasons",
    "t06_root_cause_categories",
    "t06_step3_relation_status",
    "t06_step3_relation_reason",
    "audit_comment",
)


UNREPLACED_SEGMENT_RELATION_GAP_FIELDS = (
    "segment_rank_by_length",
    "case_id",
    "swsd_segment_id",
    "segment_length_m",
    "sgrade",
    "segment_pair_nodes",
    "segment_junc_nodes",
    "node_role",
    "target_id",
    "relation_gap_category",
    "relation_gap_reason",
    "t05_status",
    "t05_base_id",
    "graph_consumable",
    "graph_consumability_status",
    "has_rcsd_in_segment_scope",
    "machine_candidate_rcsdnode_ids",
    "machine_candidate_rcsdroad_ids",
    "t06_step2_plan_status",
    "t06_step2_reject_reasons",
    "t06_root_cause_categories",
    "t06_step3_relation_status",
    "t06_step3_relation_reason",
    "manual_relation_type",
    "selected_ids",
    "comment",
)


from . import extract as _facade


def T11RelationRepairArtifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T11RelationRepairArtifacts(*args, **kwargs)


def _apply_node_context(*args: Any, **kwargs: Any) -> Any:
    return _facade._apply_node_context(*args, **kwargs)


def _apply_t05_context(*args: Any, **kwargs: Any) -> Any:
    return _facade._apply_t05_context(*args, **kwargs)


def _apply_t06_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._apply_t06_row(*args, **kwargs)


def _build_all_1v1_not_replaced_rows(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_all_1v1_not_replaced_rows(*args, **kwargs)


def _build_segment_anchor_audit_rows(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_segment_anchor_audit_rows(*args, **kwargs)


def _build_unreplaced_relation_gap_rows(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_unreplaced_relation_gap_rows(*args, **kwargs)


def _default_run_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._default_run_id(*args, **kwargs)


def _finalize_categories(*args: Any, **kwargs: Any) -> Any:
    return _facade._finalize_categories(*args, **kwargs)


def _index_by(*args: Any, **kwargs: Any) -> Any:
    return _facade._index_by(*args, **kwargs)


def _is_t06_plan_only_successful_t05_relation(*args: Any, **kwargs: Any) -> Any:
    return _facade._is_t06_plan_only_successful_t05_relation(*args, **kwargs)


def _join_sorted(*args: Any, **kwargs: Any) -> Any:
    return _facade._join_sorted(*args, **kwargs)


def _parse_id_set(*args: Any, **kwargs: Any) -> Any:
    return _facade._parse_id_set(*args, **kwargs)


def _public_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._public_row(*args, **kwargs)


def _read_existing_manual_rows(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_existing_manual_rows(*args, **kwargs)


def _rows_by(*args: Any, **kwargs: Any) -> Any:
    return _facade._rows_by(*args, **kwargs)


def _summary(*args: Any, **kwargs: Any) -> Any:
    return _facade._summary(*args, **kwargs)


def _target_ids_from_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._target_ids_from_row(*args, **kwargs)


def _text(*args: Any, **kwargs: Any) -> Any:
    return _facade._text(*args, **kwargs)


def _unreplaced_step3_segment_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._unreplaced_step3_segment_ids(*args, **kwargs)


def _write_csv(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_csv(*args, **kwargs)


def _write_gpkg(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_gpkg(*args, **kwargs)


def _write_manual_template(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_manual_template(*args, **kwargs)


def _write_rows_gpkg(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_rows_gpkg(*args, **kwargs)


def _write_text_xlsx(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_text_xlsx(*args, **kwargs)


def T11RelationRepairArtifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T11RelationRepairArtifacts(*args, **kwargs)


def extract_t11_relation_repair_candidates(
    *,
    t10_case_root: Path,
    out_root: Path,
    case_id: str = "605415675",
    existing_manual_csv_path: Path | None = None,
) -> T11RelationRepairArtifacts:
    started = time.perf_counter()
    t10_case_root = Path(t10_case_root).expanduser().resolve()
    if not t10_case_root.is_dir():
        raise FileNotFoundError(f"t10_case_root is not a directory: {t10_case_root}")

    run_id = _default_run_id()
    run_root = Path(out_root).expanduser().resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    inputs = _discover_inputs(t10_case_root)
    final_nodes = _read_gdf(inputs["final_nodes"])
    segment_gdf = _read_gdf(inputs["t01_segment"])
    swsd_roads = _read_gdf(inputs["t01_roads"])
    rcsd_nodes = _read_gdf(inputs["rcsdnode_out"])
    rcsd_roads = _read_gdf(inputs["rcsdroad_out"])
    graph_rows = _read_csv(inputs["relation_graph_consumability_audit"])
    junction_rows = _read_csv(inputs["rcsd_junctionization_audit"])
    t03_relation_rows = _read_csv(inputs["t03_relation_evidence"])
    t03_anchor_rows = _read_csv(inputs["t03_anchor_audit"])
    t04_relation_rows = _read_csv(inputs["t04_relation_evidence"])
    t04_anchor_rows = _read_csv(inputs["t04_anchor_audit"])
    t04_fallback_rows = _read_csv(inputs["t04_relation_fallback_audit"])
    problem_rows = _read_csv(inputs["t06_problem_registry"])
    rejected_rows = _read_csv(inputs["t06_rejected"])
    buffer_rejected_rows = _read_csv(inputs["t06_buffer_rejected"])
    plan_rows = _read_csv(inputs["t06_replacement_plan"])
    repair_rows = _read_csv(inputs["t06_repair_candidates"])
    final_units = _read_csv(inputs["t06_final_fusion_units"])
    step1_rejected_rows = _read_csv(inputs["t06_step1_rejected"])
    step3_relation_rows = _read_csv(inputs["t06_step3_segment_relation"])
    segment_build_rows = _read_csv(inputs["t01_segment_build_table"])
    existing_manual_rows = _read_existing_manual_rows(existing_manual_csv_path)

    node_index = _build_node_index(final_nodes)
    segment_lengths = _segment_lengths(segment_gdf)
    segment_nodes = _segment_node_index(final_units)
    graph_index = _index_by(graph_rows, "target_id")
    junction_index = _index_by(junction_rows, "target_id")
    repair_index = _rows_by(repair_rows, "swsd_segment_id")

    accum: dict[str, dict[str, Any]] = {}
    evidence_rows = _iter_t06_evidence_rows(problem_rows, rejected_rows, buffer_rejected_rows, plan_rows)
    for source_name, row in evidence_rows:
        segment_id = _text(row.get("swsd_segment_id"))
        if not segment_id:
            continue
        target_ids = _target_ids_from_row(row) | segment_nodes.get(segment_id, set())
        if not target_ids:
            continue
        for target_id in target_ids:
            item = accum.setdefault(target_id, _new_accumulator(case_id, target_id))
            _apply_t06_row(item, source_name, row, segment_id, repair_index.get(segment_id, []))

    for target_id, item in accum.items():
        _apply_node_context(item, node_index.get(target_id, {}))
        _apply_t05_context(item, graph_index.get(target_id, {}), junction_index.get(target_id, {}))
        if _is_t06_plan_only_successful_t05_relation(item):
            continue
        _finalize_categories(item)
        item["affected_segment_total_length_m"] = round(
            sum(segment_lengths.get(segment_id, 0.0) for segment_id in item["_segment_ids"]),
            3,
        )
        item["affected_segment_count"] = len(item["_segment_ids"])
        item["rejected_segment_count"] = len(item["_rejected_segment_ids"])
        item["has_rcsd_in_segment_scope"] = bool(item["_rcsd_nodes"] or item["_rcsd_roads"])
        item["machine_candidate_rcsdnode_ids"] = _join_sorted(item["_rcsd_nodes"])
        item["machine_candidate_rcsdroad_ids"] = _join_sorted(item["_rcsd_roads"])
        item["affected_segment_ids"] = _join_sorted(item["_segment_ids"])
        item["t06_reject_reasons"] = _join_sorted(item["_reject_reasons"])
        item["root_cause_categories"] = _join_sorted(item["_root_causes"])
        item["source_modules"] = _join_sorted(item["_source_modules"])
        item["candidate_reason"] = _join_sorted(item["_candidate_reasons"])
        item["recommended_manual_relation_types"] = "|".join(MANUAL_RELATION_TYPES)

    rows_source = [item for item in accum.values() if item.get("candidate_category")]
    rows = sorted(
        (_public_row(item) for item in rows_source),
        key=lambda row: (
            -int(row["affected_segment_count"]),
            -float(row["affected_segment_total_length_m"]),
            -int(bool(row["has_rcsd_in_segment_scope"])),
            -int(bool(row["machine_candidate_rcsdnode_ids"] or row["machine_candidate_rcsdroad_ids"])),
            str(row["target_id"]),
        ),
    )
    for idx, row in enumerate(rows, start=1):
        row["priority_rank"] = idx
        row["priority_score"] = round(
            int(row["affected_segment_count"]) * 1000.0
            + float(row["affected_segment_total_length_m"])
            + (100.0 if row["has_rcsd_in_segment_scope"] else 0.0)
            + (10.0 if row["machine_candidate_rcsdnode_ids"] or row["machine_candidate_rcsdroad_ids"] else 0.0),
            3,
        )

    candidates_csv = run_root / "t11_relation_repair_candidates.csv"
    candidates_gpkg = run_root / "t11_relation_repair_candidates.gpkg"
    manual_template_csv = run_root / "t11_manual_relation_template.csv"
    summary_json = run_root / "t11_relation_repair_candidate_summary.json"
    anchor_audit_csv = run_root / "t11_segment_anchor_manual_audit.csv"
    anchor_manual_template_csv = run_root / "t11_segment_anchor_manual_template.csv"
    all_1v1_not_replaced_csv = run_root / "t11_segments_all_1v1_relation_success_but_not_replaced.csv"
    all_1v1_not_replaced_gpkg = run_root / "t11_segments_all_1v1_relation_success_but_not_replaced.gpkg"
    all_1v1_not_replaced_xlsx = run_root / "t11_segments_all_1v1_relation_success_but_not_replaced.xlsx"
    unreplaced_relation_gap_csv = run_root / "t11_unreplaced_segment_junctions_without_1v1_relation_success.csv"
    unreplaced_relation_gap_gpkg = run_root / "t11_unreplaced_segment_junctions_without_1v1_relation_success.gpkg"
    unreplaced_relation_gap_xlsx = run_root / "t11_unreplaced_segment_junctions_without_1v1_relation_success.xlsx"
    all_evidence_relation_gap_csv = run_root / "t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.csv"
    all_evidence_relation_gap_gpkg = run_root / "t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.gpkg"
    all_evidence_relation_gap_xlsx = run_root / "t11_unreplaced_segments_all_junctions_have_evidence_relation_gaps.xlsx"
    no_evidence_relation_gap_csv = run_root / "t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.csv"
    no_evidence_relation_gap_gpkg = run_root / "t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.gpkg"
    no_evidence_relation_gap_xlsx = run_root / "t11_unreplaced_segments_with_no_evidence_junction_relation_gaps.xlsx"

    _write_csv(candidates_csv, rows, CANDIDATE_FIELDS)
    _write_manual_template(manual_template_csv, rows)
    _write_gpkg(candidates_gpkg, rows, final_nodes)
    anchor_rows = _build_segment_anchor_audit_rows(
        case_id=case_id,
        final_nodes=final_nodes,
        swsd_roads=swsd_roads,
        segment_lengths=segment_lengths,
        graph_rows=graph_rows,
        junction_rows=junction_rows,
        repair_rows=repair_rows,
        problem_rows=problem_rows,
        rejected_rows=rejected_rows,
        buffer_rejected_rows=buffer_rejected_rows,
        plan_rows=plan_rows,
        final_units=final_units,
        step1_rejected_rows=step1_rejected_rows,
        segment_build_rows=segment_build_rows,
        existing_manual_rows=existing_manual_rows,
    )
    _write_csv(anchor_audit_csv, anchor_rows, ANCHOR_AUDIT_FIELDS)
    _write_csv(anchor_manual_template_csv, anchor_rows, ANCHOR_AUDIT_FIELDS)
    all_1v1_not_replaced_rows = _build_all_1v1_not_replaced_rows(
        case_id=case_id,
        segment_gdf=segment_gdf,
        swsd_roads=swsd_roads,
        segment_lengths=segment_lengths,
        graph_rows=graph_rows,
        junction_rows=junction_rows,
        problem_rows=problem_rows,
        rejected_rows=rejected_rows,
        buffer_rejected_rows=buffer_rejected_rows,
        plan_rows=plan_rows,
        final_units=final_units,
        step3_relation_rows=step3_relation_rows,
    )
    unreplaced_relation_gap_rows = _build_unreplaced_relation_gap_rows(
        case_id=case_id,
        segment_gdf=segment_gdf,
        swsd_roads=swsd_roads,
        segment_lengths=segment_lengths,
        graph_rows=graph_rows,
        junction_rows=junction_rows,
        problem_rows=problem_rows,
        rejected_rows=rejected_rows,
        buffer_rejected_rows=buffer_rejected_rows,
        plan_rows=plan_rows,
        step3_relation_rows=step3_relation_rows,
        existing_manual_rows=existing_manual_rows,
    )
    _write_csv(unreplaced_relation_gap_csv, unreplaced_relation_gap_rows, UNREPLACED_SEGMENT_RELATION_GAP_FIELDS)
    _write_rows_gpkg(
        unreplaced_relation_gap_gpkg,
        unreplaced_relation_gap_rows,
        segment_gdf,
        id_field="swsd_segment_id",
        layer="t11_unreplaced_relation_gap",
        fields=UNREPLACED_SEGMENT_RELATION_GAP_FIELDS,
    )
    _write_text_xlsx(
        unreplaced_relation_gap_xlsx,
        unreplaced_relation_gap_rows,
        UNREPLACED_SEGMENT_RELATION_GAP_FIELDS,
        sheet_name="unreplaced_relation_gap",
    )
    _write_csv(all_1v1_not_replaced_csv, all_1v1_not_replaced_rows, SEGMENT_ALL_1V1_NOT_REPLACED_FIELDS)
    _write_rows_gpkg(
        all_1v1_not_replaced_gpkg,
        all_1v1_not_replaced_rows,
        segment_gdf,
        id_field="swsd_segment_id",
        layer="t11_segments_all_1v1_success_not_replaced",
        fields=SEGMENT_ALL_1V1_NOT_REPLACED_FIELDS,
    )
    _write_text_xlsx(
        all_1v1_not_replaced_xlsx,
        all_1v1_not_replaced_rows,
        SEGMENT_ALL_1V1_NOT_REPLACED_FIELDS,
        sheet_name="all_1v1_not_replaced",
    )
    segment_review_tables = build_segment_relation_review_tables(
        case_id=case_id,
        segment_gdf=segment_gdf,
        final_nodes=final_nodes,
        rcsd_nodes=rcsd_nodes,
        rcsd_roads=rcsd_roads,
        swsd_roads=swsd_roads,
        segment_lengths=segment_lengths,
        graph_rows=graph_rows,
        junction_rows=junction_rows,
        problem_rows=problem_rows,
        rejected_rows=rejected_rows,
        buffer_rejected_rows=buffer_rejected_rows,
        plan_rows=plan_rows,
        step3_relation_rows=step3_relation_rows,
        existing_manual_rows=existing_manual_rows,
        t03_relation_rows=t03_relation_rows,
        t03_anchor_rows=t03_anchor_rows,
        t04_relation_rows=t04_relation_rows,
        t04_anchor_rows=t04_anchor_rows,
        t04_fallback_rows=t04_fallback_rows,
    )
    all_evidence_relation_gap_rows = segment_review_tables.all_evidence_relation_gap_rows
    no_evidence_relation_gap_rows = segment_review_tables.no_evidence_relation_gap_rows
    _write_csv(all_evidence_relation_gap_csv, all_evidence_relation_gap_rows, SEGMENT_RELATION_GAP_REVIEW_FIELDS)
    _write_rows_gpkg(
        all_evidence_relation_gap_gpkg,
        all_evidence_relation_gap_rows,
        segment_gdf,
        id_field="swsd_segment_id",
        layer="t11_all_evidence_relation_gaps",
        fields=SEGMENT_RELATION_GAP_REVIEW_FIELDS,
    )
    write_review_xlsx(
        all_evidence_relation_gap_xlsx,
        all_evidence_relation_gap_rows,
        sheet_name="all_evidence_relation_gaps",
    )
    _write_csv(no_evidence_relation_gap_csv, no_evidence_relation_gap_rows, SEGMENT_RELATION_GAP_REVIEW_FIELDS)
    _write_rows_gpkg(
        no_evidence_relation_gap_gpkg,
        no_evidence_relation_gap_rows,
        segment_gdf,
        id_field="swsd_segment_id",
        layer="t11_no_evidence_relation_gaps",
        fields=SEGMENT_RELATION_GAP_REVIEW_FIELDS,
    )
    write_review_xlsx(
        no_evidence_relation_gap_xlsx,
        no_evidence_relation_gap_rows,
        sheet_name="no_evidence_relation_gaps",
    )

    duration = round(time.perf_counter() - started, 6)
    summary = _summary(
        case_id=case_id,
        t10_case_root=t10_case_root,
        run_root=run_root,
        inputs=inputs,
        rows=rows,
        duration_seconds=duration,
        final_nodes=final_nodes,
        segment_gdf=segment_gdf,
        source_counts={
            "problem_registry": len(problem_rows),
            "rejected": len(rejected_rows),
            "buffer_rejected": len(buffer_rejected_rows),
            "replacement_plan": len(plan_rows),
            "repair_candidates": len(repair_rows),
            "final_fusion_units": len(final_units),
            "step1_rejected": len(step1_rejected_rows),
            "step3_segment_relation": len(step3_relation_rows),
            "segment_build_table": len(segment_build_rows),
            "t01_roads": int(len(swsd_roads)),
            "rcsdnode_out": int(len(rcsd_nodes)),
            "rcsdroad_out": int(len(rcsd_roads)),
            "t03_relation_evidence": len(t03_relation_rows),
            "t03_anchor_audit": len(t03_anchor_rows),
            "t04_relation_evidence": len(t04_relation_rows),
            "t04_anchor_audit": len(t04_anchor_rows),
            "t04_relation_fallback_audit": len(t04_fallback_rows),
        },
    )
    summary["segment_anchor_audit"] = {
        "csv": str(anchor_audit_csv),
        "manual_template_csv": str(anchor_manual_template_csv),
        "row_count": len(anchor_rows),
        "manual_prefilled_count": sum(1 for row in anchor_rows if row.get("manual_relation_type")),
        "sort_order": [
            "manual_reviewed asc",
            "has_rcsd_in_segment_scope desc",
            "highest_priority_segment_length_m desc",
            "affected_segment_count desc",
            "anchor_gap_severity",
            "target_id asc",
        ],
        "top_candidates": anchor_rows[:20],
    }
    summary["segments_all_1v1_relation_success_but_not_replaced"] = {
        "csv": str(all_1v1_not_replaced_csv),
        "gpkg": str(all_1v1_not_replaced_gpkg),
        "xlsx": str(all_1v1_not_replaced_xlsx),
        "row_count": len(all_1v1_not_replaced_rows),
        "definition": (
            "Every Segment semantic node has T05 status=0, nonzero base_id, graph_consumable=1, "
            "and multi_base_relation!=1, but T06 Step3 relation_status is not replaced."
        ),
        "sort_order": ["segment_length_m desc", "swsd_segment_id asc"],
        "top_segments": all_1v1_not_replaced_rows[:20],
    }
    gap_segments = {_text(row.get("swsd_segment_id")) for row in unreplaced_relation_gap_rows if _text(row.get("swsd_segment_id"))}
    all_1v1_segments = {_text(row.get("swsd_segment_id")) for row in all_1v1_not_replaced_rows if _text(row.get("swsd_segment_id"))}
    all_evidence_gap_segments = {
        _text(row.get("swsd_segment_id")) for row in all_evidence_relation_gap_rows if _text(row.get("swsd_segment_id"))
    }
    no_evidence_gap_segments = {
        _text(row.get("swsd_segment_id")) for row in no_evidence_relation_gap_rows if _text(row.get("swsd_segment_id"))
    }
    step3_unreplaced_segments = _unreplaced_step3_segment_ids(step3_relation_rows)
    summary["unreplaced_segment_relation_gap_audit"] = {
        "csv": str(unreplaced_relation_gap_csv),
        "gpkg": str(unreplaced_relation_gap_gpkg),
        "xlsx": str(unreplaced_relation_gap_xlsx),
        "row_count": len(unreplaced_relation_gap_rows),
        "segment_count": len(gap_segments),
        "definition": (
            "Rows are only from T06 Step3 non-replaced Segments whose effective pair/junc nodes "
            "do not all have consumable 1v1 T05 relation."
        ),
        "sort_order": ["segment_length_m desc", "swsd_segment_id asc", "node_role asc", "target_id asc"],
        "top_rows": unreplaced_relation_gap_rows[:20],
        "completeness_with_all_1v1_output": {
            "step3_unreplaced_segment_count": len(step3_unreplaced_segments),
            "gap_segment_count": len(gap_segments),
            "all_1v1_not_replaced_segment_count": len(all_1v1_segments),
            "union_segment_count": len(gap_segments | all_1v1_segments),
            "union_matches_step3_unreplaced": (gap_segments | all_1v1_segments) == step3_unreplaced_segments,
        },
    }
    three_table_union = all_1v1_segments | all_evidence_gap_segments | no_evidence_gap_segments
    summary["segment_relation_review_tables"] = {
        "table_1_all_junctions_have_relation": {
            "csv": str(all_1v1_not_replaced_csv),
            "gpkg": str(all_1v1_not_replaced_gpkg),
            "xlsx": str(all_1v1_not_replaced_xlsx),
            "row_count": len(all_1v1_not_replaced_rows),
            "segment_count": len(all_1v1_segments),
        },
        "table_2_all_junctions_have_evidence_relation_gaps": {
            "csv": str(all_evidence_relation_gap_csv),
            "gpkg": str(all_evidence_relation_gap_gpkg),
            "xlsx": str(all_evidence_relation_gap_xlsx),
            "row_count": len(all_evidence_relation_gap_rows),
            "segment_count": len(all_evidence_gap_segments),
            "manual_prefilled_count": sum(1 for row in all_evidence_relation_gap_rows if row.get("manual_relation_type") or row.get("selected_ids")),
            "duplicate_do_not_consume_count": sum(1 for row in all_evidence_relation_gap_rows if row.get("manual_row_consumable") == 0),
        },
        "table_3_has_no_evidence_junction_relation_gaps": {
            "csv": str(no_evidence_relation_gap_csv),
            "gpkg": str(no_evidence_relation_gap_gpkg),
            "xlsx": str(no_evidence_relation_gap_xlsx),
            "row_count": len(no_evidence_relation_gap_rows),
            "segment_count": len(no_evidence_gap_segments),
            "manual_prefilled_count": sum(1 for row in no_evidence_relation_gap_rows if row.get("manual_relation_type") or row.get("selected_ids")),
            "duplicate_do_not_consume_count": sum(1 for row in no_evidence_relation_gap_rows if row.get("manual_row_consumable") == 0),
            "no_rcsd_50m_row_count": sum(1 for row in no_evidence_relation_gap_rows if row.get("rcsd_50m_hint") == "��RCSD"),
        },
        "completeness": {
            "step3_unreplaced_segment_count": len(step3_unreplaced_segments),
            "union_segment_count": len(three_table_union),
            "union_matches_step3_unreplaced": three_table_union == step3_unreplaced_segments,
            "missing_segments": _join_sorted(step3_unreplaced_segments - three_table_union),
            "extra_segments": _join_sorted(three_table_union - step3_unreplaced_segments),
        },
        "manual_relation_type_dropdown_values": [
            "1v1_rcsd_junction",
            "1vN_rcsd_junction",
            "1v1_rcsd_road",
            "1vN_rcsd_road",
            "no_valid_relation",
            "uncertain",
            "NULL",
        ],
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return T11RelationRepairArtifacts(
        run_root=run_root,
        candidates_csv=candidates_csv,
        candidates_gpkg=candidates_gpkg,
        manual_template_csv=manual_template_csv,
        summary_json=summary_json,
        candidate_count=len(rows),
        run_id=run_id,
        anchor_audit_csv=anchor_audit_csv,
        anchor_manual_template_csv=anchor_manual_template_csv,
        all_1v1_not_replaced_csv=all_1v1_not_replaced_csv,
        all_1v1_not_replaced_gpkg=all_1v1_not_replaced_gpkg,
        all_1v1_not_replaced_xlsx=all_1v1_not_replaced_xlsx,
        unreplaced_relation_gap_csv=unreplaced_relation_gap_csv,
        unreplaced_relation_gap_gpkg=unreplaced_relation_gap_gpkg,
        unreplaced_relation_gap_xlsx=unreplaced_relation_gap_xlsx,
        all_evidence_relation_gap_csv=all_evidence_relation_gap_csv,
        all_evidence_relation_gap_gpkg=all_evidence_relation_gap_gpkg,
        all_evidence_relation_gap_xlsx=all_evidence_relation_gap_xlsx,
        no_evidence_relation_gap_csv=no_evidence_relation_gap_csv,
        no_evidence_relation_gap_gpkg=no_evidence_relation_gap_gpkg,
        no_evidence_relation_gap_xlsx=no_evidence_relation_gap_xlsx,
    )


def _discover_inputs(root: Path) -> dict[str, Path | None]:
    return {
        "final_nodes": _first_existing(
            root,
            (
                "t04/t04/nodes.gpkg",
                "t04_internal_full_input/t04_full/nodes.gpkg",
                "t07/t07/step2_anchor_recognition/nodes.gpkg",
                "t01/nodes.gpkg",
                "t01_full_data/nodes.gpkg",
            ),
            "nodes.gpkg",
        ),
        "t01_segment": _first_existing(root, ("t01/segment.gpkg", "t01_full_data/segment.gpkg"), "segment.gpkg"),
        "t01_roads": _first_existing(root, ("t01/roads.gpkg", "t01_full_data/roads.gpkg"), "roads.gpkg"),
        "t01_segment_build_table": _first_existing(
            root,
            ("t01/segment_build_table.csv", "t01_full_data/segment_build_table.csv"),
            "segment_build_table.csv",
        ),
        "rcsdnode_out": _first_existing(
            root,
            ("t05/t05_phase2/rcsdnode_out.gpkg", "t05_innernet_experiment/t05_phase2_innernet/rcsdnode_out.gpkg"),
            "rcsdnode_out.gpkg",
        ),
        "rcsdroad_out": _first_existing(
            root,
            ("t05/t05_phase2/rcsdroad_out.gpkg", "t05_innernet_experiment/t05_phase2_innernet/rcsdroad_out.gpkg"),
            "rcsdroad_out.gpkg",
        ),
        "relation_graph_consumability_audit": _first_existing(
            root,
            (
                "t05/t05_phase2/relation_graph_consumability_audit.csv",
                "t05_innernet_experiment/t05_phase2_innernet/relation_graph_consumability_audit.csv",
            ),
            "relation_graph_consumability_audit.csv",
        ),
        "rcsd_junctionization_audit": _first_existing(
            root,
            (
                "t05/t05_phase2/rcsd_junctionization_audit.csv",
                "t05_innernet_experiment/t05_phase2_innernet/rcsd_junctionization_audit.csv",
            ),
            "rcsd_junctionization_audit.csv",
        ),
        "t03_relation_evidence": _first_existing(
            root,
            (
                "t03/t03/t03_swsd_rcsd_relation_evidence.csv",
                "t03_internal_full_input/t03_full/t03_swsd_rcsd_relation_evidence.csv",
            ),
            "t03_swsd_rcsd_relation_evidence.csv",
        ),
        "t03_anchor_audit": _first_existing(
            root,
            ("t03/t03/nodes_anchor_update_audit.csv", "t03_internal_full_input/t03_full/nodes_anchor_update_audit.csv"),
            "nodes_anchor_update_audit.csv",
        ),
        "t04_relation_evidence": _first_existing(
            root,
            (
                "t04/t04/t04_swsd_rcsd_relation_evidence.csv",
                "t04_internal_full_input/t04_full/t04_swsd_rcsd_relation_evidence.csv",
            ),
            "t04_swsd_rcsd_relation_evidence.csv",
        ),
        "t04_anchor_audit": _first_existing(
            root,
            ("t04/t04/nodes_anchor_update_audit.csv", "t04_internal_full_input/t04_full/nodes_anchor_update_audit.csv"),
            "nodes_anchor_update_audit.csv",
        ),
        "t04_relation_fallback_audit": _first_existing(
            root,
            (
                "t04/t04/t04_relation_fallback_audit.csv",
                "t04_internal_full_input/t04_full/t04_relation_fallback_audit.csv",
            ),
            "t04_relation_fallback_audit.csv",
        ),
        "t06_problem_registry": _first_existing(
            root,
            (
                "t06_step12/t06/step2_extract_rcsd_segments/t06_segment_replacement_problem_registry.csv",
                "t06_segment_fusion_precheck/t06_innernet_precheck/step2_extract_rcsd_segments/t06_segment_replacement_problem_registry.csv",
            ),
            "t06_segment_replacement_problem_registry.csv",
        ),
        "t06_rejected": _first_existing(
            root,
            (
                "t06_step12/t06/step2_extract_rcsd_segments/t06_rcsd_segment_rejected.csv",
                "t06_segment_fusion_precheck/t06_innernet_precheck/step2_extract_rcsd_segments/t06_rcsd_segment_rejected.csv",
            ),
            "t06_rcsd_segment_rejected.csv",
        ),
        "t06_buffer_rejected": _first_existing(
            root,
            (
                "t06_step12/t06/step2_extract_rcsd_segments/t06_rcsd_buffer_segment_rejected.csv",
                "t06_segment_fusion_precheck/t06_innernet_precheck/step2_extract_rcsd_segments/t06_rcsd_buffer_segment_rejected.csv",
            ),
            "t06_rcsd_buffer_segment_rejected.csv",
        ),
        "t06_replacement_plan": _first_existing(
            root,
            (
                "t06_step12/t06/step2_extract_rcsd_segments/t06_segment_replacement_plan.csv",
                "t06_segment_fusion_precheck/t06_innernet_precheck/step2_extract_rcsd_segments/t06_segment_replacement_plan.csv",
            ),
            "t06_segment_replacement_plan.csv",
        ),
        "t06_repair_candidates": _first_existing(
            root,
            (
                "t06_step12/t06/step2_extract_rcsd_segments/t06_rcsd_repair_candidates.csv",
                "t06_segment_fusion_precheck/t06_innernet_precheck/step2_extract_rcsd_segments/t06_rcsd_repair_candidates.csv",
            ),
            "t06_rcsd_repair_candidates.csv",
        ),
        "t06_final_fusion_units": _first_existing(
            root,
            (
                "t06_step12/t06/step1_identify_fusion_units/t06_swsd_segment_final_fusion_units.csv",
                "t06_segment_fusion_precheck/t06_innernet_precheck/step1_identify_fusion_units/t06_swsd_segment_final_fusion_units.csv",
            ),
            "t06_swsd_segment_final_fusion_units.csv",
        ),
        "t06_step1_rejected": _first_existing(
            root,
            (
                "t06_step12/t06/step1_identify_fusion_units/t06_swsd_segment_rejected.csv",
                "t06_segment_fusion_precheck/t06_innernet_precheck/step1_identify_fusion_units/t06_swsd_segment_rejected.csv",
            ),
            "t06_swsd_segment_rejected.csv",
        ),
        "t06_step3_segment_relation": _first_existing(
            root,
            (
                "t06_step12/t06/step3_segment_replacement/t06_step3_swsd_frcsd_segment_relation.csv",
                "t06_segment_fusion_precheck/t06_innernet_precheck/step3_segment_replacement/t06_step3_swsd_frcsd_segment_relation.csv",
            ),
            "t06_step3_swsd_frcsd_segment_relation.csv",
        ),
    }


def _first_existing(root: Path, relatives: Iterable[str], name: str) -> Path | None:
    for rel in relatives:
        path = root / rel
        if path.is_file():
            return path
    matches = sorted(root.rglob(name))
    return matches[0] if matches else None


def _read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_gdf(path: Path | None) -> gpd.GeoDataFrame:
    if path is None or not path.is_file():
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:3857")
    return gpd.read_file(path)


def _build_node_index(nodes: gpd.GeoDataFrame) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    records = [row.to_dict() for _, row in nodes.iterrows()]
    for data in records:
        value = _text(data.get("id"))
        if value and value not in {"0", "0.0", "-1"}:
            index[value] = data
    # Mainnode aliases are useful for grouped semantic nodes, but they must not
    # shadow an exact SWSD node id.
    for data in records:
        value = _text(data.get("mainnodeid"))
        if value and value not in {"0", "0.0", "-1"}:
            index.setdefault(value, data)
    return index


def _segment_lengths(segments: gpd.GeoDataFrame) -> dict[str, float]:
    if segments.empty or "geometry" not in segments:
        return {}
    return {
        _text(row.get("id") or row.get("swsd_segment_id")): float(row.geometry.length if row.geometry is not None else 0.0)
        for _, row in segments.iterrows()
        if _text(row.get("id") or row.get("swsd_segment_id"))
    }


def _segment_node_index(rows: list[dict[str, str]]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for row in rows:
        segment_id = _text(row.get("swsd_segment_id"))
        if not segment_id:
            continue
        ids = set()
        for field in ("pair_nodes", "junc_nodes", "semantic_node_set"):
            ids |= _parse_id_set(row.get(field))
        index[segment_id] = ids
    return index


def _iter_t06_evidence_rows(
    problem_rows: list[dict[str, str]],
    rejected_rows: list[dict[str, str]],
    buffer_rejected_rows: list[dict[str, str]],
    plan_rows: list[dict[str, str]],
) -> Iterable[tuple[str, dict[str, str]]]:
    for row in problem_rows:
        yield "T06_problem_registry", row
    for row in rejected_rows:
        yield "T06_rejected", row
    for row in buffer_rejected_rows:
        yield "T06_buffer_rejected", row
    for row in plan_rows:
        status = _text(row.get("plan_status")).lower()
        action = _text(row.get("execution_action")).lower()
        if status and status != "ready" or action in {"hold", "skip", "blocked"}:
            yield "T06_replacement_plan", row


def _new_accumulator(case_id: str, target_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "target_id": target_id,
        "kind_2": "",
        "has_evd": "",
        "is_anchor": "",
        "candidate_category": "",
        "candidate_reason": "",
        "source_modules": "",
        "t05_status": "",
        "t05_reason": "",
        "graph_consumable": False,
        "graph_consumability_status": "",
        "has_rcsd_in_segment_scope": False,
        "machine_candidate_rcsdnode_ids": "",
        "machine_candidate_rcsdroad_ids": "",
        "affected_segment_count": 0,
        "affected_segment_total_length_m": 0.0,
        "affected_segment_ids": "",
        "rejected_segment_count": 0,
        "t06_reject_reasons": "",
        "root_cause_categories": "",
        "priority_rank": 0,
        "priority_score": 0.0,
        "recommended_manual_relation_types": "",
        "_segment_ids": set(),
        "_rejected_segment_ids": set(),
        "_reject_reasons": set(),
        "_root_causes": set(),
        "_source_modules": set(),
        "_candidate_reasons": set(),
        "_rcsd_nodes": set(),
        "_rcsd_roads": set(),
        "_category_evidence": set(),
    }
