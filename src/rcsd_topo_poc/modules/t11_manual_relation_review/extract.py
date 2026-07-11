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


@dataclass(frozen=True)
class T11RelationRepairArtifacts:
    run_root: Path
    candidates_csv: Path
    candidates_gpkg: Path
    manual_template_csv: Path
    summary_json: Path
    candidate_count: int
    run_id: str
    anchor_audit_csv: Path | None = None
    anchor_manual_template_csv: Path | None = None
    all_1v1_not_replaced_csv: Path | None = None
    all_1v1_not_replaced_gpkg: Path | None = None
    all_1v1_not_replaced_xlsx: Path | None = None
    unreplaced_relation_gap_csv: Path | None = None
    unreplaced_relation_gap_gpkg: Path | None = None
    unreplaced_relation_gap_xlsx: Path | None = None
    all_evidence_relation_gap_csv: Path | None = None
    all_evidence_relation_gap_gpkg: Path | None = None
    all_evidence_relation_gap_xlsx: Path | None = None
    no_evidence_relation_gap_csv: Path | None = None
    no_evidence_relation_gap_gpkg: Path | None = None
    no_evidence_relation_gap_xlsx: Path | None = None


from .extract_pipeline import (
    extract_t11_relation_repair_candidates,
    _discover_inputs,
    _first_existing,
    _read_csv,
    _read_gdf,
    _build_node_index,
    _segment_lengths,
    _segment_node_index,
    _iter_t06_evidence_rows,
    _new_accumulator,
)


def _apply_t06_row(
    item: dict[str, Any],
    source_name: str,
    row: dict[str, str],
    segment_id: str,
    repair_rows: list[dict[str, str]],
) -> None:
    item["_segment_ids"].add(segment_id)
    item["_source_modules"].add("T06")
    item["_source_modules"].add(source_name)
    if source_name != "T06_replacement_plan":
        item["_rejected_segment_ids"].add(segment_id)

    reason = _text(row.get("reject_reason") or row.get("source_reason") or row.get("notes"))
    if reason:
        item["_reject_reasons"].add(reason)
        item["_candidate_reasons"].add(f"{source_name}:{reason}")
    root = _text(row.get("root_cause_category") or row.get("failure_business_category"))
    if root:
        item["_root_causes"].add(root)

    for field in (
        "rcsd_pair_nodes",
        "required_rcsd_nodes",
        "candidate_rcsd_node_ids",
        "retained_node_ids",
        "pair_anchor_error_original_rcsd_nodes",
        "pair_anchor_error_candidate_rcsd_nodes",
        "pair_anchor_endpoint_cluster_nodes",
        "original_rcsd_pair_nodes",
    ):
        item["_rcsd_nodes"].update(_parse_id_set(row.get(field)))
    for field in (
        "rcsd_road_ids",
        "candidate_rcsd_road_ids",
        "retained_rcsd_road_ids",
        "pair_anchor_bridge_road_ids",
    ):
        item["_rcsd_roads"].update(_parse_id_set(row.get(field)))
    for repair in repair_rows:
        item["_rcsd_nodes"].update(_parse_id_set(repair.get("candidate_rcsd_node_ids")))
        item["_rcsd_nodes"].update(_parse_nested_id_set(repair.get("candidate_rcsd_pair_node_sets")))
        item["_rcsd_roads"].update(_parse_id_set(repair.get("candidate_rcsd_road_ids")))

    evidence_text = " ".join(
        _text(row.get(field))
        for field in (
            "reject_reason",
            "root_cause_category",
            "failure_business_category",
            "problem_status",
            "pair_anchor_diagnostic_reason",
            "notes",
        )
    ).lower()
    if any(token in evidence_text for token in ("invalid_pair_relation_status", "missing_relation", "relation_mapping")):
        item["_category_evidence"].add("relation_missing_or_invalid")
    if any(token in evidence_text for token in ("pair_anchor", "required_nodes_disconnected", "not_connected", "disconnected")):
        item["_category_evidence"].add("required_nodes_disconnected_or_pair_anchor_issue")


def _target_ids_from_row(row: dict[str, str]) -> set[str]:
    ids: set[str] = set()
    for field in (
        "swsd_pair_nodes",
        "swsd_junc_nodes",
        "failed_pair_nodes",
        "failed_junc_nodes",
        "pair_anchor_error_swsd_nodes",
    ):
        ids.update(_parse_id_set(row.get(field)))
    return ids


def _apply_node_context(item: dict[str, Any], node: dict[str, Any]) -> None:
    if not node:
        return
    for field in ("kind_2", "has_evd", "is_anchor"):
        item[field] = _text(node.get(field))


def _apply_t05_context(item: dict[str, Any], graph: dict[str, str], junction: dict[str, str]) -> None:
    if graph:
        item["_source_modules"].add("T05")
        item["graph_consumable"] = _truthy(graph.get("graph_consumable"))
        item["graph_consumability_status"] = _text(graph.get("graph_consumability_status"))
        item["t05_status"] = _text(graph.get("relation_status"))
        item["t05_reason"] = _text(graph.get("reasons"))
        for field in ("matched_rcsdnode_ids", "incident_rcsdnode_ids"):
            item["_rcsd_nodes"].update(_parse_id_set(graph.get(field)))
        if not item["graph_consumable"]:
            item["_category_evidence"].add("relation_graph_unconsumable")
            if item["graph_consumability_status"]:
                item["_candidate_reasons"].add(f"T05:{item['graph_consumability_status']}")
        if item["t05_status"] and item["t05_status"] not in {"0", "success"}:
            item["_category_evidence"].add("relation_missing_or_invalid")
    if junction:
        item["_source_modules"].add("T05")
        item["t05_status"] = item["t05_status"] or _text(junction.get("status"))
        item["t05_reason"] = item["t05_reason"] or _text(junction.get("reason") or junction.get("skipped_reason"))
        item["_rcsd_nodes"].update(_parse_id_set(junction.get("original_rcsdnode_ids")))
        item["_rcsd_nodes"].update(_parse_id_set(junction.get("new_rcsdnode_ids")))
        item["_rcsd_nodes"].update(_parse_id_set(junction.get("grouped_rcsdnode_ids")))
        item["_rcsd_nodes"].update(_parse_id_set(junction.get("selected_main_rcsdnode_id")))
        item["_rcsd_roads"].update(_parse_id_set(junction.get("original_rcsdroad_ids")))
        item["_rcsd_roads"].update(_parse_id_set(junction.get("new_rcsdroad_ids")))


def _finalize_categories(item: dict[str, Any]) -> None:
    has_evd = _text(item.get("has_evd")).lower()
    has_rcsd = bool(item["_rcsd_nodes"] or item["_rcsd_roads"])
    if has_evd in {"", "no", "false", "0", "none", "null"} and has_rcsd:
        item["_category_evidence"].add("no_evidence_but_rcsd_present_in_segment_scope")
    if not item["_category_evidence"]:
        item["_category_evidence"].add("uncertain_upstream_or_data_issue")
    item["candidate_category"] = _join_sorted(item["_category_evidence"])


def _is_t06_plan_only_successful_t05_relation(item: dict[str, Any]) -> bool:
    sources = set(item["_source_modules"])
    t06_sources = {source for source in sources if source.startswith("T06")}
    if t06_sources != {"T06", "T06_replacement_plan"}:
        return False
    if item["_rejected_segment_ids"]:
        return False
    t05_success = _text(item.get("t05_status")).lower() in {"0", "success"}
    return t05_success and bool(item.get("graph_consumable"))


def _public_row(item: dict[str, Any]) -> dict[str, Any]:
    return {field: item.get(field, "") for field in CANDIDATE_FIELDS}


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_manual_template(path: Path, rows: list[dict[str, Any]]) -> None:
    template_rows = [
        {
            "case_id": row["case_id"],
            "target_id": row["target_id"],
            "manual_relation_type": "",
            "selected_ids": "",
            "comment": "",
        }
        for row in rows
    ]
    _write_csv(path, template_rows, MANUAL_TEMPLATE_FIELDS)


def _write_gpkg(path: Path, rows: list[dict[str, Any]], nodes: gpd.GeoDataFrame) -> None:
    node_index = _build_node_index(nodes)
    records: list[dict[str, Any]] = []
    geometries = []
    for row in rows:
        records.append(row)
        node = node_index.get(_text(row["target_id"]), {})
        geometries.append(node.get("geometry"))
    crs = nodes.crs or "EPSG:3857"
    gdf = gpd.GeoDataFrame(records, geometry=geometries, crs=crs)
    if gdf.empty:
        gdf = gpd.GeoDataFrame(columns=[*CANDIDATE_FIELDS, "geometry"], geometry="geometry", crs=crs)
    gdf.to_file(path, driver="GPKG", layer="t11_relation_repair_candidates")


def _write_rows_gpkg(
    path: Path,
    rows: list[dict[str, Any]],
    source_gdf: gpd.GeoDataFrame,
    *,
    id_field: str,
    layer: str,
    fields: Iterable[str],
) -> None:
    source_index = {
        _text(row.get("id") or row.get(id_field)): row.get("geometry")
        for _, row in source_gdf.iterrows()
        if _text(row.get("id") or row.get(id_field))
    }
    crs = source_gdf.crs or "EPSG:3857"
    records = [{field: row.get(field, "") for field in fields} for row in rows]
    geometries = [source_index.get(_text(row.get(id_field))) for row in rows]
    gdf = gpd.GeoDataFrame(records, geometry=geometries, crs=crs)
    if gdf.empty:
        gdf = gpd.GeoDataFrame(columns=[*fields, "geometry"], geometry="geometry", crs=crs)
    gdf.to_file(path, driver="GPKG", layer=layer)


def _write_text_xlsx(path: Path, rows: list[dict[str, Any]], fields: Iterable[str], *, sheet_name: str) -> None:
    write_text_xlsx(path, rows, fields, sheet_name=sheet_name)


def _excel_col(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result or "A"


def _clean_xml_text(value: Any) -> str:
    return "".join(char for char in _text(value) if char in "\t\n\r" or ord(char) >= 32)


def _read_existing_manual_rows(path: Path | None) -> dict[str, dict[str, str]]:
    rows = _read_csv(path)
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        target_id = _text(row.get("target_id"))
        if not target_id:
            continue
        manual = {
            "manual_relation_type": _text(row.get("manual_relation_type")),
            "selected_ids": _text(row.get("selected_ids")),
            "comment": _text(row.get("comment")),
        }
        if any(manual.values()):
            result[target_id] = manual
    return result


def _build_segment_anchor_audit_rows(
    *,
    case_id: str,
    final_nodes: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    segment_lengths: dict[str, float],
    graph_rows: list[dict[str, str]],
    junction_rows: list[dict[str, str]],
    repair_rows: list[dict[str, str]],
    problem_rows: list[dict[str, str]],
    rejected_rows: list[dict[str, str]],
    buffer_rejected_rows: list[dict[str, str]],
    plan_rows: list[dict[str, str]],
    final_units: list[dict[str, str]],
    step1_rejected_rows: list[dict[str, str]],
    segment_build_rows: list[dict[str, str]],
    existing_manual_rows: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    node_index = _build_node_index(final_nodes)
    non_right_turn_incident_counts = _non_right_turn_incident_road_counts(swsd_roads)
    graph_index = _index_by(graph_rows, "target_id")
    junction_index = _index_by(junction_rows, "target_id")
    repair_index = _rows_by(repair_rows, "swsd_segment_id")
    segment_scope = _build_anchor_segment_scope(
        problem_rows=problem_rows,
        rejected_rows=rejected_rows,
        buffer_rejected_rows=buffer_rejected_rows,
        plan_rows=plan_rows,
        final_units=final_units,
        step1_rejected_rows=step1_rejected_rows,
        segment_build_rows=segment_build_rows,
        repair_index=repair_index,
    )

    target_items: dict[str, dict[str, Any]] = {}
    for segment_id, scope in segment_scope.items():
        segment_length = round(segment_lengths.get(segment_id, 0.0), 3)
        segment_nodes = set(scope["pair_nodes"]) | set(scope["junc_nodes"])
        for target_id in segment_nodes:
            if not _is_effective_anchor_node(target_id, scope, non_right_turn_incident_counts):
                continue
            graph = graph_index.get(target_id, {})
            junction = junction_index.get(target_id, {})
            node = node_index.get(target_id, {})
            if _has_valid_1v1_anchor(node=node, graph=graph, junction=junction):
                continue
            item = target_items.setdefault(target_id, _new_anchor_item(case_id, target_id))
            category = _anchor_gap_category(node=node, graph=graph, junction=junction)
            item["_categories"].add(category)
            item["_segments"].add(segment_id)
            item["_segment_lengths"][segment_id] = segment_length
            item["_pair_nodes"].update(scope["pair_nodes"])
            item["_junc_nodes"].update(scope["junc_nodes"])
            item["_reject_reasons"].update(scope["reject_reasons"])
            item["_rcsd_nodes"].update(scope["rcsd_nodes"])
            item["_rcsd_roads"].update(scope["rcsd_roads"])
            if target_id in scope["pair_nodes"]:
                item["_node_roles"].add("pair_node")
            if target_id in scope["junc_nodes"]:
                item["_node_roles"].add("junc_node")
            _apply_anchor_node_context(item, node, graph, junction)

    for target_id, manual in existing_manual_rows.items():
        item = target_items.setdefault(target_id, _new_anchor_item(case_id, target_id))
        if not item["_categories"]:
            item["_categories"].add("manual_prefilled_existing_not_current_candidate")
        _apply_anchor_node_context(item, node_index.get(target_id, {}), graph_index.get(target_id, {}), junction_index.get(target_id, {}))

    rows: list[dict[str, Any]] = []
    for target_id, item in target_items.items():
        manual = existing_manual_rows.get(target_id, {})
        top_segment = _top_anchor_segment(item["_segment_lengths"])
        has_rcsd = bool(item["_rcsd_nodes"] or item["_rcsd_roads"])
        manual_reviewed = _has_manual_review_value(manual)
        if not has_rcsd and not manual_reviewed:
            continue
        item["anchor_gap_category"] = _anchor_primary_category(item["_categories"])
        item["review_focus"] = _anchor_review_focus(item["anchor_gap_category"], has_rcsd)
        item["highest_priority_segment_id"] = top_segment[0]
        item["highest_priority_segment_length_m"] = top_segment[1]
        item["affected_segment_count"] = len(item["_segments"])
        item["affected_segment_total_length_m"] = round(sum(item["_segment_lengths"].values()), 3)
        item["affected_segment_ids"] = _join_sorted(item["_segments"])
        item["node_roles"] = _join_sorted(item["_node_roles"])
        item["segment_pair_nodes"] = _join_sorted(item["_pair_nodes"])
        item["segment_junc_nodes"] = _join_sorted(item["_junc_nodes"])
        item["has_rcsd_in_segment_scope"] = has_rcsd
        item["machine_candidate_rcsdnode_ids"] = _join_sorted(item["_rcsd_nodes"])
        item["machine_candidate_rcsdroad_ids"] = _join_sorted(item["_rcsd_roads"])
        item["t06_reject_reasons"] = _join_sorted(item["_reject_reasons"])
        item["review_hint"] = _anchor_review_hint(item)
        item["recommended_manual_relation_types"] = "|".join(MANUAL_RELATION_TYPES)
        item["manual_relation_type"] = manual.get("manual_relation_type", "")
        item["selected_ids"] = manual.get("selected_ids", "")
        item["comment"] = manual.get("comment", "")
        rows.append({field: item.get(field, "") for field in ANCHOR_AUDIT_FIELDS})

    rows.sort(key=_anchor_sort_key)
    for idx, row in enumerate(rows, start=1):
        row["anchor_priority_rank"] = idx
    return rows


def _build_all_1v1_not_replaced_rows(
    *,
    case_id: str,
    segment_gdf: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    segment_lengths: dict[str, float],
    graph_rows: list[dict[str, str]],
    junction_rows: list[dict[str, str]],
    problem_rows: list[dict[str, str]],
    rejected_rows: list[dict[str, str]],
    buffer_rejected_rows: list[dict[str, str]],
    plan_rows: list[dict[str, str]],
    final_units: list[dict[str, str]],
    step3_relation_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    graph_index = _index_by(graph_rows, "target_id")
    junction_index = _index_by(junction_rows, "target_id")
    segment_scope = _build_segment_issue_scope(
        problem_rows=problem_rows,
        rejected_rows=rejected_rows,
        buffer_rejected_rows=buffer_rejected_rows,
        plan_rows=plan_rows,
    )
    step3_index = _index_by(step3_relation_rows, "swsd_segment_id")
    segment_attrs = _segment_attrs(segment_gdf, segment_lengths)
    non_right_turn_counts = _non_right_turn_incident_road_counts(swsd_roads)
    rows: list[dict[str, Any]] = []
    segment_rank = {
        segment_id: index
        for index, segment_id in enumerate(
            sorted(segment_attrs, key=lambda value: (-float(segment_attrs[value].get("segment_length_m") or 0.0), value)),
            start=1,
        )
    }
    segment_records = sorted(
        [row.to_dict() for _, row in segment_gdf.iterrows()],
        key=lambda row: (
            -float(segment_attrs.get(_text(row.get("id") or row.get("swsd_segment_id")), {}).get("segment_length_m", 0.0)),
            _text(row.get("id") or row.get("swsd_segment_id")),
        ),
    )
    for segment in segment_records:
        segment_id = _text(segment.get("id") or segment.get("swsd_segment_id"))
        if not segment_id:
            continue
        pair_nodes, junc_nodes, semantic_nodes = _effective_segment_nodes(segment, non_right_turn_counts)
        if not semantic_nodes:
            continue
        node_relations: list[tuple[str, str]] = []
        if not all(_is_consumable_1v1_relation(node_id, graph_index, junction_index, node_relations) for node_id in sorted(semantic_nodes)):
            continue
        step3 = step3_index.get(segment_id, {})
        step3_status = _text(step3.get("relation_status"))
        if step3_status == "replaced":
            continue
        attrs = segment_attrs.get(segment_id, {})
        scope = segment_scope.get(segment_id, {})
        rows.append(
            {
                "segment_rank_by_length": 0,
                "case_id": case_id,
                "swsd_segment_id": segment_id,
                "segment_length_m": attrs.get("segment_length_m", 0.0),
                "sgrade": attrs.get("sgrade") or _text(segment.get("sgrade")),
                "segment_pair_nodes": _join_sorted(pair_nodes),
                "segment_junc_nodes": _join_sorted(junc_nodes),
                "relation_target_ids": _join_sorted(target for target, _base in node_relations),
                "relation_base_ids": _join_sorted(base for _target, base in node_relations),
                "all_junction_relation_success_1v1_consumable": 1,
                "segment_has_t06_rcsd_scope": int(bool(scope.get("rcsd_nodes") or scope.get("rcsd_roads"))),
                "t06_step2_plan_status": _join_sorted(scope.get("plan_statuses", set())),
                "t06_step2_reject_reasons": _join_sorted(scope.get("reject_reasons", set())),
                "t06_root_cause_categories": _join_sorted(scope.get("root_causes", set())),
                "t06_step3_relation_status": step3_status or "missing_step3_relation",
                "t06_step3_relation_reason": _text(step3.get("relation_reason")),
                "audit_comment": "",
            }
        )
    rows.sort(key=lambda row: (-float(row.get("segment_length_m") or 0.0), _text(row.get("swsd_segment_id"))))
    for row in rows:
        row["segment_rank_by_length"] = segment_rank.get(_text(row.get("swsd_segment_id")), 0)
    return rows


def _build_unreplaced_relation_gap_rows(
    *,
    case_id: str,
    segment_gdf: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    segment_lengths: dict[str, float],
    graph_rows: list[dict[str, str]],
    junction_rows: list[dict[str, str]],
    problem_rows: list[dict[str, str]],
    rejected_rows: list[dict[str, str]],
    buffer_rejected_rows: list[dict[str, str]],
    plan_rows: list[dict[str, str]],
    step3_relation_rows: list[dict[str, str]],
    existing_manual_rows: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    graph_index = _index_by(graph_rows, "target_id")
    junction_index = _index_by(junction_rows, "target_id")
    segment_scope = _build_segment_issue_scope(
        problem_rows=problem_rows,
        rejected_rows=rejected_rows,
        buffer_rejected_rows=buffer_rejected_rows,
        plan_rows=plan_rows,
    )
    step3_index = _index_by(step3_relation_rows, "swsd_segment_id")
    segment_attrs = _segment_attrs(segment_gdf, segment_lengths)
    non_right_turn_counts = _non_right_turn_incident_road_counts(swsd_roads)
    segment_rank = _segment_rank_by_length(segment_attrs)
    rows: list[dict[str, Any]] = []
    for segment in _segment_records_by_length(segment_gdf, segment_attrs):
        segment_id = _text(segment.get("id") or segment.get("swsd_segment_id"))
        if not segment_id:
            continue
        step3 = step3_index.get(segment_id, {})
        step3_status = _text(step3.get("relation_status"))
        if step3_status == "replaced":
            continue
        pair_nodes, junc_nodes, semantic_nodes = _effective_segment_nodes(segment, non_right_turn_counts)
        attrs = segment_attrs.get(segment_id, {})
        scope = segment_scope.get(segment_id, {})
        if not semantic_nodes:
            rows.append(
                _unreplaced_relation_gap_row(
                    case_id=case_id,
                    segment_id=segment_id,
                    attrs=attrs,
                    pair_nodes=pair_nodes,
                    junc_nodes=junc_nodes,
                    target_id="",
                    role="segment",
                    category="no_effective_semantic_nodes",
                    reason="Segment has no effective pair/junc node after right-turn attachment filtering.",
                    graph={},
                    junction={},
                    scope=scope,
                    step3=step3,
                    manual={},
                    segment_rank=segment_rank.get(segment_id, 0),
                )
            )
            continue
        node_relations: list[tuple[str, str]] = []
        successful_nodes = {
            node_id
            for node_id in semantic_nodes
            if _is_consumable_1v1_relation(node_id, graph_index, junction_index, node_relations)
        }
        if successful_nodes == semantic_nodes:
            continue
        for target_id in sorted(semantic_nodes - successful_nodes):
            graph = graph_index.get(target_id, {})
            junction = junction_index.get(target_id, {})
            category, reason = _relation_gap_detail(target_id, graph, junction)
            rows.append(
                _unreplaced_relation_gap_row(
                    case_id=case_id,
                    segment_id=segment_id,
                    attrs=attrs,
                    pair_nodes=pair_nodes,
                    junc_nodes=junc_nodes,
                    target_id=target_id,
                    role=_segment_node_role(target_id, pair_nodes, junc_nodes),
                    category=category,
                    reason=reason,
                    graph=graph,
                    junction=junction,
                    scope=scope,
                    step3=step3,
                    manual=existing_manual_rows.get(target_id, {}),
                    segment_rank=segment_rank.get(segment_id, 0),
                )
            )
    rows.sort(
        key=lambda row: (
            -float(row.get("segment_length_m") or 0.0),
            _text(row.get("swsd_segment_id")),
            _text(row.get("node_role")),
            _text(row.get("target_id")),
        )
    )
    return rows


def _unreplaced_relation_gap_row(
    *,
    case_id: str,
    segment_id: str,
    attrs: dict[str, Any],
    pair_nodes: set[str],
    junc_nodes: set[str],
    target_id: str,
    role: str,
    category: str,
    reason: str,
    graph: dict[str, str],
    junction: dict[str, str],
    scope: dict[str, set[str]],
    step3: dict[str, str],
    manual: dict[str, str],
    segment_rank: int,
) -> dict[str, Any]:
    rcsd_nodes = set(scope.get("rcsd_nodes", set()))
    rcsd_roads = set(scope.get("rcsd_roads", set()))
    rcsd_nodes.update(_parse_id_set(graph.get("matched_rcsdnode_ids")))
    rcsd_nodes.update(_parse_id_set(graph.get("incident_rcsdnode_ids")))
    rcsd_nodes.update(_parse_id_set(junction.get("original_rcsdnode_ids")))
    rcsd_nodes.update(_parse_id_set(junction.get("new_rcsdnode_ids")))
    rcsd_nodes.update(_parse_id_set(junction.get("grouped_rcsdnode_ids")))
    rcsd_nodes.update(_parse_id_set(junction.get("selected_main_rcsdnode_id")))
    rcsd_roads.update(_parse_id_set(junction.get("original_rcsdroad_ids")))
    rcsd_roads.update(_parse_id_set(junction.get("new_rcsdroad_ids")))
    return {
        "segment_rank_by_length": segment_rank,
        "case_id": case_id,
        "swsd_segment_id": segment_id,
        "segment_length_m": attrs.get("segment_length_m", 0.0),
        "sgrade": attrs.get("sgrade", ""),
        "segment_pair_nodes": _join_sorted(pair_nodes),
        "segment_junc_nodes": _join_sorted(junc_nodes),
        "node_role": role,
        "target_id": target_id,
        "relation_gap_category": category,
        "relation_gap_reason": reason,
        "t05_status": _text(graph.get("relation_status") or junction.get("status")),
        "t05_base_id": _text(graph.get("base_id") or junction.get("base_id") or junction.get("selected_main_rcsdnode_id")),
        "graph_consumable": int(_truthy(graph.get("graph_consumable"))),
        "graph_consumability_status": _text(graph.get("graph_consumability_status")),
        "has_rcsd_in_segment_scope": int(bool(rcsd_nodes or rcsd_roads)),
        "machine_candidate_rcsdnode_ids": _join_sorted(rcsd_nodes),
        "machine_candidate_rcsdroad_ids": _join_sorted(rcsd_roads),
        "t06_step2_plan_status": _join_sorted(scope.get("plan_statuses", set())),
        "t06_step2_reject_reasons": _join_sorted(scope.get("reject_reasons", set())),
        "t06_root_cause_categories": _join_sorted(scope.get("root_causes", set())),
        "t06_step3_relation_status": _text(step3.get("relation_status")) or "missing_step3_relation",
        "t06_step3_relation_reason": _text(step3.get("relation_reason")),
        "manual_relation_type": manual.get("manual_relation_type", ""),
        "selected_ids": manual.get("selected_ids", ""),
        "comment": manual.get("comment", ""),
    }


def _relation_gap_detail(target_id: str, graph: dict[str, str], junction: dict[str, str]) -> tuple[str, str]:
    if not graph and not junction:
        return "missing_t05_relation", f"{target_id} has no T05 relation audit row."
    status = _text(graph.get("relation_status") or junction.get("status")).lower()
    base_id = _text(graph.get("base_id") or junction.get("base_id") or junction.get("selected_main_rcsdnode_id"))
    graph_status = _text(graph.get("graph_consumability_status"))
    multi = _text(junction.get("multi_base_relation")).lower()
    if status not in {"0", "success"}:
        return "relation_status_not_success", f"T05 relation_status/status is {status or 'empty'}."
    if not base_id or base_id in {"0", "-1"}:
        return "missing_relation_base_id", "T05 relation succeeded but has no consumable base_id."
    if not _truthy(graph.get("graph_consumable")):
        return "relation_graph_unconsumable", "T05 graph_consumable is not true."
    if graph_status != "base_node_graph_incident":
        return "relation_graph_unconsumable", f"T05 graph status is {graph_status or 'empty'}."
    if multi in {"1", "true", "yes"}:
        return "multi_base_relation", "T05 junction audit reports multi_base_relation."
    return "relation_not_1v1_success", "T05 relation is not a consumable 1v1 relation."


def _effective_segment_nodes(segment: dict[str, Any], non_right_turn_counts: dict[str, int]) -> tuple[set[str], set[str], set[str]]:
    pair_nodes = _parse_id_set(segment.get("pair_nodes"))
    raw_junc_nodes = _parse_id_set(segment.get("junc_nodes"))
    scope = {"pair_nodes": pair_nodes, "junc_nodes": raw_junc_nodes}
    junc_nodes = {
        node_id for node_id in raw_junc_nodes if _is_effective_anchor_node(node_id, scope, non_right_turn_counts)
    }
    return pair_nodes, junc_nodes, pair_nodes | junc_nodes


def _segment_rank_by_length(segment_attrs: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        segment_id: index
        for index, segment_id in enumerate(
            sorted(segment_attrs, key=lambda value: (-float(segment_attrs[value].get("segment_length_m") or 0.0), value)),
            start=1,
        )
    }


def _segment_records_by_length(segment_gdf: gpd.GeoDataFrame, segment_attrs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [row.to_dict() for _, row in segment_gdf.iterrows()],
        key=lambda row: (
            -float(segment_attrs.get(_text(row.get("id") or row.get("swsd_segment_id")), {}).get("segment_length_m", 0.0)),
            _text(row.get("id") or row.get("swsd_segment_id")),
        ),
    )


def _segment_node_role(target_id: str, pair_nodes: set[str], junc_nodes: set[str]) -> str:
    roles = []
    if target_id in pair_nodes:
        roles.append("pair_node")
    if target_id in junc_nodes:
        roles.append("junc_node")
    return "|".join(roles)


def _unreplaced_step3_segment_ids(step3_relation_rows: list[dict[str, str]]) -> set[str]:
    return {
        _text(row.get("swsd_segment_id"))
        for row in step3_relation_rows
        if _text(row.get("swsd_segment_id")) and _text(row.get("relation_status")) != "replaced"
    }


def _segment_attrs(segment_gdf: gpd.GeoDataFrame, segment_lengths: dict[str, float]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for _, row in segment_gdf.iterrows():
        segment_id = _text(row.get("id") or row.get("swsd_segment_id"))
        if not segment_id:
            continue
        result[segment_id] = {
            "segment_length_m": round(segment_lengths.get(segment_id, 0.0), 3),
            "sgrade": _text(row.get("sgrade")),
        }
    return result


def _build_segment_issue_scope(
    *,
    problem_rows: list[dict[str, str]],
    rejected_rows: list[dict[str, str]],
    buffer_rejected_rows: list[dict[str, str]],
    plan_rows: list[dict[str, str]],
) -> dict[str, dict[str, set[str]]]:
    scope: dict[str, dict[str, set[str]]] = {}

    def item(segment_id: str) -> dict[str, set[str]]:
        return scope.setdefault(
            segment_id,
            {"reject_reasons": set(), "root_causes": set(), "plan_statuses": set(), "rcsd_nodes": set(), "rcsd_roads": set()},
        )

    for row in [*problem_rows, *rejected_rows, *buffer_rejected_rows, *plan_rows]:
        segment_id = _text(row.get("swsd_segment_id"))
        if not segment_id:
            continue
        current = item(segment_id)
        for field, target in (("reject_reason", "reject_reasons"), ("source_reason", "reject_reasons")):
            value = _text(row.get(field))
            if value:
                current[target].add(value)
        for field in ("root_cause_category", "failure_business_category"):
            value = _text(row.get(field))
            if value:
                current["root_causes"].add(value)
        status = _text(row.get("plan_status"))
        if status:
            current["plan_statuses"].add(status)
        for field in (
            "rcsd_pair_nodes",
            "required_rcsd_nodes",
            "candidate_rcsd_node_ids",
            "retained_node_ids",
            "original_rcsd_pair_nodes",
            "pair_anchor_error_original_rcsd_nodes",
            "pair_anchor_error_candidate_rcsd_nodes",
            "rcsd_junc_nodes",
        ):
            current["rcsd_nodes"].update(_parse_id_set(row.get(field)))
        for field in ("rcsd_road_ids", "candidate_rcsd_road_ids", "retained_rcsd_road_ids", "pair_anchor_bridge_road_ids"):
            current["rcsd_roads"].update(_parse_id_set(row.get(field)))
    return scope


def _is_consumable_1v1_relation(
    target_id: str,
    graph_index: dict[str, dict[str, str]],
    junction_index: dict[str, dict[str, str]],
    collector: list[tuple[str, str]],
) -> bool:
    graph = graph_index.get(target_id, {})
    junction = junction_index.get(target_id, {})
    status = _text(graph.get("relation_status") or junction.get("status")).lower()
    base_id = _text(graph.get("base_id") or junction.get("base_id") or junction.get("selected_main_rcsdnode_id"))
    graph_status = _text(graph.get("graph_consumability_status"))
    multi = _text(junction.get("multi_base_relation")).lower()
    if status not in {"0", "success"}:
        return False
    if not base_id or base_id in {"0", "-1"}:
        return False
    if not _truthy(graph.get("graph_consumable")):
        return False
    if graph_status != "base_node_graph_incident":
        return False
    if multi in {"1", "true", "yes"}:
        return False
    collector.append((target_id, base_id))
    return True


def _new_anchor_item(case_id: str, target_id: str) -> dict[str, Any]:
    return {
        "anchor_priority_rank": 0,
        "case_id": case_id,
        "target_id": target_id,
        "anchor_gap_category": "",
        "review_focus": "",
        "highest_priority_segment_id": "",
        "highest_priority_segment_length_m": 0.0,
        "affected_segment_count": 0,
        "affected_segment_total_length_m": 0.0,
        "affected_segment_ids": "",
        "node_roles": "",
        "segment_pair_nodes": "",
        "segment_junc_nodes": "",
        "kind_2": "",
        "has_evd": "",
        "is_anchor": "",
        "t05_status": "",
        "t05_reason": "",
        "graph_consumable": False,
        "graph_consumability_status": "",
        "has_rcsd_in_segment_scope": False,
        "machine_candidate_rcsdnode_ids": "",
        "machine_candidate_rcsdroad_ids": "",
        "t06_reject_reasons": "",
        "review_hint": "",
        "recommended_manual_relation_types": "",
        "manual_relation_type": "",
        "selected_ids": "",
        "comment": "",
        "_categories": set(),
        "_segments": set(),
        "_segment_lengths": {},
        "_node_roles": set(),
        "_pair_nodes": set(),
        "_junc_nodes": set(),
        "_reject_reasons": set(),
        "_rcsd_nodes": set(),
        "_rcsd_roads": set(),
    }


def _build_anchor_segment_scope(
    *,
    problem_rows: list[dict[str, str]],
    rejected_rows: list[dict[str, str]],
    buffer_rejected_rows: list[dict[str, str]],
    plan_rows: list[dict[str, str]],
    final_units: list[dict[str, str]],
    step1_rejected_rows: list[dict[str, str]],
    segment_build_rows: list[dict[str, str]],
    repair_index: dict[str, list[dict[str, str]]],
) -> dict[str, dict[str, set[str]]]:
    scope: dict[str, dict[str, set[str]]] = {}

    def item(segment_id: str) -> dict[str, set[str]]:
        return scope.setdefault(
            segment_id,
            {
                "pair_nodes": set(),
                "junc_nodes": set(),
                "reject_reasons": set(),
                "rcsd_nodes": set(),
                "rcsd_roads": set(),
            },
        )

    def apply_row(row: dict[str, str], *, segment_field: str = "swsd_segment_id") -> None:
        segment_id = _text(row.get(segment_field))
        if not segment_id:
            return
        current = item(segment_id)
        current["pair_nodes"].update(_parse_id_set(row.get("swsd_pair_nodes") or row.get("pair_nodes")))
        current["junc_nodes"].update(_parse_id_set(row.get("swsd_junc_nodes") or row.get("junc_nodes")))
        current["pair_nodes"].update(_parse_id_set(row.get("failed_pair_nodes")))
        current["junc_nodes"].update(_parse_id_set(row.get("failed_junc_nodes")))
        current["pair_nodes"].update(_parse_id_set(row.get("pair_anchor_error_swsd_nodes")))
        reason = _text(row.get("reject_reason") or row.get("source_reason") or row.get("problem_status"))
        if reason:
            current["reject_reasons"].add(reason)
        for field in (
            "rcsd_pair_nodes",
            "required_rcsd_nodes",
            "candidate_rcsd_node_ids",
            "retained_node_ids",
            "original_rcsd_pair_nodes",
            "pair_anchor_error_original_rcsd_nodes",
            "pair_anchor_error_candidate_rcsd_nodes",
            "optional_junc_rcsd_nodes",
            "rcsd_junc_nodes",
        ):
            current["rcsd_nodes"].update(_parse_id_set(row.get(field)))
        for field in ("rcsd_road_ids", "candidate_rcsd_road_ids", "retained_rcsd_road_ids", "pair_anchor_bridge_road_ids"):
            current["rcsd_roads"].update(_parse_id_set(row.get(field)))

    for row in final_units:
        apply_row(row)
    for row in step1_rejected_rows:
        apply_row(row)
    for row in problem_rows:
        apply_row(row)
    for row in rejected_rows:
        apply_row(row)
    for row in buffer_rejected_rows:
        apply_row(row)
    for row in plan_rows:
        apply_row(row)

    for row in segment_build_rows:
        segment_id = _text(row.get("segmentid") or row.get("swsd_segment_id"))
        if segment_id in scope:
            current = item(segment_id)
            current["pair_nodes"].update(_parse_id_set(row.get("pair_nodes")))
            current["junc_nodes"].update(_parse_id_set(row.get("junc_nodes")))

    for segment_id, repairs in repair_index.items():
        if segment_id not in scope:
            continue
        current = item(segment_id)
        for repair in repairs:
            current["rcsd_nodes"].update(_parse_id_set(repair.get("candidate_rcsd_node_ids")))
            current["rcsd_nodes"].update(_parse_nested_id_set(repair.get("candidate_rcsd_pair_node_sets")))
            current["rcsd_roads"].update(_parse_id_set(repair.get("candidate_rcsd_road_ids")))

    return scope


def _non_right_turn_incident_road_counts(roads: gpd.GeoDataFrame) -> dict[str, int]:
    if roads.empty or "snodeid" not in roads.columns or "enodeid" not in roads.columns:
        return {}
    counts: dict[str, int] = defaultdict(int)
    for _, road in roads.iterrows():
        if _is_right_turn_road(road):
            continue
        for field in ("snodeid", "enodeid"):
            node_id = _text(road.get(field))
            if node_id and node_id not in {"0", "0.0", "-1"}:
                counts[node_id] += 1
    return counts


def _is_right_turn_road(road: Any) -> bool:
    value = _text(road.get("formway"))
    if not value:
        return False
    try:
        formway = int(float(value))
    except ValueError:
        return False
    return bool(formway & 128)


def _is_effective_anchor_node(
    target_id: str,
    scope: dict[str, set[str]],
    non_right_turn_incident_counts: dict[str, int],
) -> bool:
    if target_id in scope["pair_nodes"]:
        return True
    if target_id not in scope["junc_nodes"]:
        return True
    if not non_right_turn_incident_counts:
        return True
    return non_right_turn_incident_counts.get(target_id, 0) > 2


def _has_manual_review_value(row: dict[str, str]) -> bool:
    return bool(_text(row.get("manual_relation_type")) or _text(row.get("selected_ids")) or _text(row.get("comment")))


def _apply_anchor_node_context(
    item: dict[str, Any],
    node: dict[str, Any],
    graph: dict[str, str],
    junction: dict[str, str],
) -> None:
    for field in ("kind_2", "has_evd", "is_anchor"):
        if node and not item.get(field):
            item[field] = _text(node.get(field))
    if graph:
        item["graph_consumable"] = _truthy(graph.get("graph_consumable"))
        item["graph_consumability_status"] = _text(graph.get("graph_consumability_status"))
        item["t05_status"] = _text(graph.get("relation_status"))
        item["t05_reason"] = _text(graph.get("reasons"))
        item["_rcsd_nodes"].update(_parse_id_set(graph.get("matched_rcsdnode_ids")))
        item["_rcsd_nodes"].update(_parse_id_set(graph.get("incident_rcsdnode_ids")))
    if junction:
        item["t05_status"] = item.get("t05_status") or _text(junction.get("status"))
        item["t05_reason"] = item.get("t05_reason") or _text(junction.get("reason") or junction.get("skipped_reason"))
        item["_rcsd_nodes"].update(_parse_id_set(junction.get("original_rcsdnode_ids")))
        item["_rcsd_nodes"].update(_parse_id_set(junction.get("new_rcsdnode_ids")))
        item["_rcsd_nodes"].update(_parse_id_set(junction.get("grouped_rcsdnode_ids")))
        item["_rcsd_nodes"].update(_parse_id_set(junction.get("selected_main_rcsdnode_id")))
        item["_rcsd_roads"].update(_parse_id_set(junction.get("original_rcsdroad_ids")))
        item["_rcsd_roads"].update(_parse_id_set(junction.get("new_rcsdroad_ids")))


def _has_valid_1v1_anchor(*, node: dict[str, Any], graph: dict[str, str], junction: dict[str, str]) -> bool:
    has_evd = _text(node.get("has_evd")).lower()
    is_anchor = _text(node.get("is_anchor")).lower()
    if has_evd != "yes" or is_anchor != "yes":
        return False
    status = _text(graph.get("relation_status") or junction.get("status")).lower()
    graph_status = _text(graph.get("graph_consumability_status"))
    return status in {"0", "success"} and _truthy(graph.get("graph_consumable")) and graph_status == "base_node_graph_incident"


def _anchor_gap_category(*, node: dict[str, Any], graph: dict[str, str], junction: dict[str, str]) -> str:
    has_evd = _text(node.get("has_evd")).lower()
    is_anchor = _text(node.get("is_anchor")).lower()
    status = _text(graph.get("relation_status") or junction.get("status")).lower()
    if has_evd == "yes" and is_anchor == "fail4":
        return "anchor_failed_fail4"
    if has_evd == "yes" and is_anchor == "fail3":
        return "anchor_failed_fail3"
    if has_evd == "yes" and is_anchor and is_anchor != "yes":
        return "anchor_failed_other"
    if has_evd in {"", "no", "false", "0", "none", "null"}:
        return "no_evidence_or_missing_anchor"
    if status and status not in {"0", "success"}:
        return "relation_not_1v1_or_unconsumable"
    if graph and (not _truthy(graph.get("graph_consumable")) or _text(graph.get("graph_consumability_status")) != "base_node_graph_incident"):
        return "relation_not_1v1_or_unconsumable"
    return "anchor_relation_uncertain"


def _anchor_primary_category(categories: set[str]) -> str:
    order = (
        "anchor_failed_fail4",
        "anchor_failed_fail3",
        "anchor_failed_other",
        "relation_not_1v1_or_unconsumable",
        "no_evidence_or_missing_anchor",
        "anchor_relation_uncertain",
        "manual_prefilled_existing_not_current_candidate",
    )
    for category in order:
        if category in categories:
            return category
    return _join_sorted(categories)


def _anchor_review_focus(category: str, has_rcsd: bool) -> str:
    if not has_rcsd:
        return "low_priority_no_rcsd_context"
    if category.startswith("anchor_failed"):
        return "repair_anchor_first"
    if category == "no_evidence_or_missing_anchor":
        return "review_no_evidence_with_rcsd_context"
    if category == "relation_not_1v1_or_unconsumable":
        return "repair_relation_after_anchor_check"
    return "review_existing_context"


def _anchor_review_hint(item: dict[str, Any]) -> str:
    if not item.get("has_rcsd_in_segment_scope"):
        return "Segment scope has no machine RCSD context; review after RCSD-present candidates."
    category = _text(item.get("anchor_gap_category"))
    if category.startswith("anchor_failed"):
        return "Pair/junc node is not correctly anchored; inspect RCSD candidates around the highest-priority Segment."
    if category == "no_evidence_or_missing_anchor":
        return "No usable SWSD evidence/anchor; only prioritize because RCSD context exists in the Segment scope."
    if category == "relation_not_1v1_or_unconsumable":
        return "Anchor exists but T05 relation is not a consumable 1v1 graph relation."
    return "Review with existing T05/T06 context."


def _top_anchor_segment(segment_lengths: dict[str, float]) -> tuple[str, float]:
    if not segment_lengths:
        return "", 0.0
    segment_id, length = sorted(segment_lengths.items(), key=lambda item: (-item[1], item[0]))[0]
    return segment_id, round(length, 3)


def _anchor_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    severity = {
        "anchor_failed_fail4": 0,
        "anchor_failed_fail3": 1,
        "anchor_failed_other": 2,
        "relation_not_1v1_or_unconsumable": 3,
        "no_evidence_or_missing_anchor": 4,
        "anchor_relation_uncertain": 5,
        "manual_prefilled_existing_not_current_candidate": 6,
    }.get(_text(row.get("anchor_gap_category")), 9)
    has_rcsd = 1 if row.get("has_rcsd_in_segment_scope") in {True, "True", "true", "1", 1} else 0
    reviewed = 1 if _has_manual_review_value(row) else 0
    return (
        reviewed,
        -has_rcsd,
        -float(row.get("highest_priority_segment_length_m") or 0.0),
        -int(row.get("affected_segment_count") or 0),
        severity,
        _text(row.get("target_id")),
    )


def _summary(
    *,
    case_id: str,
    t10_case_root: Path,
    run_root: Path,
    inputs: dict[str, Path | None],
    rows: list[dict[str, Any]],
    duration_seconds: float,
    final_nodes: gpd.GeoDataFrame,
    segment_gdf: gpd.GeoDataFrame,
    source_counts: dict[str, int],
) -> dict[str, Any]:
    categories = Counter()
    for row in rows:
        for category in str(row["candidate_category"]).split("|"):
            if category:
                categories[category] += 1
    return {
        "module_id": "t11_manual_relation_review",
        "case_id": case_id,
        "run_id": run_root.name,
        "produced_at_utc": datetime.now(timezone.utc).isoformat(),
        "t10_case_root": str(t10_case_root),
        "run_root": str(run_root),
        "inputs": {key: str(value) if value else None for key, value in inputs.items()},
        "parameters": {
            "manual_relation_type_allowed_values": list(MANUAL_RELATION_TYPES),
            "sort_order": [
                "affected_segment_count desc",
                "affected_segment_total_length_m desc",
                "has_rcsd_in_segment_scope desc",
                "has_machine_candidate desc",
            ],
        },
        "candidate_count": len(rows),
        "category_stats": dict(sorted(categories.items())),
        "no_evidence_but_rcsd_present_candidate_count": categories.get(
            "no_evidence_but_rcsd_present_in_segment_scope", 0
        ),
        "relation_graph_unconsumable_candidate_count": categories.get("relation_graph_unconsumable", 0),
        "top_candidates": rows[:20],
        "top_affected_segments": _top_segments(rows),
        "input_scale": {
            **source_counts,
            "final_node_count": int(len(final_nodes)),
            "t01_segment_count": int(len(segment_gdf)),
        },
        "quality_checks": {
            "crs": {
                "status": "recorded",
                "final_nodes_crs": str(final_nodes.crs),
                "segment_crs": str(segment_gdf.crs),
                "length_unit_assumption": "meters when source CRS is projected; EPSG:3857 expected for T10 case replay.",
            },
            "topology": {
                "status": "audit_only",
                "note": "T11 reads existing geometries and does not edit, snap, dissolve, or repair topology.",
            },
            "geometry_semantics": {
                "status": "traceable",
                "note": "Candidate geometry is the SWSD final node point; RCSD candidates are copied from T05/T06 evidence fields.",
            },
            "audit": {
                "status": "traceable",
                "note": "Each row keeps source modules, T05 status, T06 reject reasons, affected segments, and machine candidate ids.",
            },
            "performance": {
                "duration_seconds": duration_seconds,
                "input_rows": source_counts,
            },
        },
    }


def _top_segments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        for segment_id in str(row["affected_segment_ids"]).split("|"):
            if not segment_id:
                continue
            item = stats.setdefault(
                segment_id,
                {
                    "swsd_segment_id": segment_id,
                    "candidate_count": 0,
                    "target_ids": set(),
                    "categories": set(),
                },
            )
            item["candidate_count"] += 1
            item["target_ids"].add(str(row["target_id"]))
            item["categories"].update(str(row["candidate_category"]).split("|"))
    result = []
    for item in stats.values():
        result.append(
            {
                "swsd_segment_id": item["swsd_segment_id"],
                "candidate_count": item["candidate_count"],
                "target_ids": _join_sorted(item["target_ids"]),
                "categories": _join_sorted(item["categories"]),
            }
        )
    return sorted(result, key=lambda row: (-row["candidate_count"], row["swsd_segment_id"]))[:20]


def _index_by(rows: list[dict[str, str]], field: str) -> dict[str, dict[str, str]]:
    return {_text(row.get(field)): row for row in rows if _text(row.get(field))}


def _rows_by(rows: list[dict[str, str]], field: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = _text(row.get(field))
        if key:
            result[key].append(row)
    return result


def _parse_id_set(value: Any) -> set[str]:
    value_text = _text(value)
    if not value_text:
        return set()
    try:
        parsed = ast.literal_eval(value_text)
    except (ValueError, SyntaxError):
        parsed = None
    if isinstance(parsed, (list, tuple, set)):
        return {_text(item) for item in _flatten(parsed) if _text(item)}
    return {part.strip() for part in value_text.replace(",", "|").split("|") if part.strip()}


def _parse_nested_id_set(value: Any) -> set[str]:
    return _parse_id_set(value)


def _flatten(values: Iterable[Any]) -> Iterable[Any]:
    for value in values:
        if isinstance(value, (list, tuple, set)):
            yield from _flatten(value)
        else:
            yield value


def _truthy(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "y", "passed", "success"}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _join_sorted(values: Iterable[Any]) -> str:
    return "|".join(sorted({_text(value) for value in values if _text(value)}))


def _default_run_id() -> str:
    return "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
