from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import pandas as pd

from .xlsx_writer import write_text_xlsx


MANUAL_AUDIT_TYPES = (
    "1v1_rcsd_junction",
    "1vN_rcsd_junction",
    "1v1_rcsd_road",
    "1vN_rcsd_road",
    "no_valid_relation",
    "uncertain",
    "NULL",
)

SEGMENT_RELATION_GAP_REVIEW_FIELDS = (
    "segment_priority_rank",
    "case_id",
    "swsd_segment_id",
    "segment_length_m",
    "segment_priority_bucket",
    "sgrade",
    "segment_pair_nodes",
    "segment_junc_nodes",
    "segment_relation_success_node_ids",
    "segment_relation_gap_node_ids",
    "segment_no_evidence_node_ids",
    "node_role",
    "target_id",
    "has_evd",
    "is_anchor",
    "relation_gap_category",
    "relation_gap_reason",
    "t05_status",
    "t05_base_id",
    "graph_consumable",
    "graph_consumability_status",
    "t05_source_modules",
    "t05_scenes",
    "t05_reasons",
    "t03_scene_hint",
    "t04_scene_hint",
    "upstream_no_rcsd_reference_hint",
    "rcsd_50m_hint",
    "rcsd_50m_feature_count",
    "rcsd_50m_nearest_ids",
    "rcsd_50m_nearest_distance_m",
    "has_rcsd_in_segment_scope",
    "machine_candidate_rcsdnode_ids",
    "machine_candidate_rcsdroad_ids",
    "t06_step2_plan_status",
    "t06_step2_reject_reasons",
    "t06_root_cause_categories",
    "t06_step3_relation_status",
    "t06_step3_relation_reason",
    "duplicate_target_first_segment_id",
    "duplicate_target_policy",
    "manual_row_consumable",
    "manual_relation_type",
    "selected_ids",
    "comment",
)


@dataclass(frozen=True)
class SegmentRelationReviewTables:
    all_evidence_relation_gap_rows: list[dict[str, Any]]
    no_evidence_relation_gap_rows: list[dict[str, Any]]


def build_segment_relation_review_tables(
    *,
    case_id: str,
    segment_gdf: gpd.GeoDataFrame,
    final_nodes: gpd.GeoDataFrame,
    rcsd_nodes: gpd.GeoDataFrame,
    rcsd_roads: gpd.GeoDataFrame,
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
    t03_relation_rows: list[dict[str, str]],
    t03_anchor_rows: list[dict[str, str]],
    t04_relation_rows: list[dict[str, str]],
    t04_anchor_rows: list[dict[str, str]],
    t04_fallback_rows: list[dict[str, str]],
) -> SegmentRelationReviewTables:
    graph_index = _index_by(graph_rows, "target_id")
    junction_index = _index_by(junction_rows, "target_id")
    node_index = _node_index(final_nodes)
    t03_index = _merge_indexes(_index_by(t03_relation_rows, "target_id"), _index_by(t03_anchor_rows, "representative_node_id"))
    t04_index = _merge_indexes(
        _index_by(t04_relation_rows, "target_id"),
        _index_by(t04_anchor_rows, "representative_node_id"),
        _index_by(t04_fallback_rows, "target_id"),
    )
    segment_scope = _build_segment_issue_scope(
        problem_rows=problem_rows,
        rejected_rows=rejected_rows,
        buffer_rejected_rows=buffer_rejected_rows,
        plan_rows=plan_rows,
    )
    step3_index = _index_by(step3_relation_rows, "swsd_segment_id")
    attrs = _segment_attrs(segment_gdf, segment_lengths)
    non_right_turn_counts = _non_right_turn_incident_road_counts(swsd_roads)
    rcsd_feature_gdf = _rcsd_feature_gdf(rcsd_nodes, rcsd_roads, final_nodes.crs or segment_gdf.crs)
    rcsd50_cache: dict[str, dict[str, Any]] = {}

    first_target_segment: dict[str, str] = {}
    all_evidence_rows: list[dict[str, Any]] = []
    no_evidence_rows: list[dict[str, Any]] = []
    segment_orders: list[tuple[int, int, float, str]] = []
    pending_rows: list[tuple[str, dict[str, Any]]] = []

    for segment in _segment_records_by_length(segment_gdf, attrs):
        segment_id = _text(segment.get("id") or segment.get("swsd_segment_id"))
        if not segment_id:
            continue
        step3 = step3_index.get(segment_id, {})
        step3_status = _text(step3.get("relation_status"))
        if step3_status == "replaced":
            continue
        pair_nodes, junc_nodes, semantic_nodes = _effective_segment_nodes(segment, non_right_turn_counts)
        if not semantic_nodes:
            row = _review_row(
                case_id=case_id,
                segment_id=segment_id,
                attrs=attrs.get(segment_id, {}),
                segment_priority_bucket="2_no_effective_semantic_nodes",
                pair_nodes=pair_nodes,
                junc_nodes=junc_nodes,
                relation_success_nodes=set(),
                relation_gap_nodes={""},
                no_evidence_nodes={""},
                role="segment",
                target_id="",
                node={},
                graph={},
                junction={},
                scope=segment_scope.get(segment_id, {}),
                step3=step3,
                t03_hint="",
                t04_hint="",
                no_rcsd_reference_hint="",
                rcsd50=_empty_rcsd50("no_effective_semantic_nodes"),
                manual={},
                first_segment_id="",
                duplicate_policy="",
                manual_row_consumable=0,
            )
            pending_rows.append(("no_evidence", row))
            segment_orders.append((2, 0, -float(attrs.get(segment_id, {}).get("segment_length_m") or 0.0), segment_id))
            continue

        relation_success_nodes: set[str] = set()
        relation_gap_nodes: set[str] = set()
        no_evidence_nodes: set[str] = set()
        rcsd50_by_node: dict[str, dict[str, Any]] = {}
        for node_id in sorted(semantic_nodes):
            node = node_index.get(node_id, {})
            has_evidence = _node_has_evidence(node)
            if not has_evidence:
                no_evidence_nodes.add(node_id)
            if _is_consumable_1v1_relation(node_id, graph_index, junction_index):
                relation_success_nodes.add(node_id)
            else:
                relation_gap_nodes.add(node_id)
            rcsd50 = rcsd50_cache.get(node_id)
            if rcsd50 is None:
                rcsd50 = _rcsd_50m_context(node, rcsd_feature_gdf)
                rcsd50_cache[node_id] = rcsd50
            rcsd50_by_node[node_id] = rcsd50

        if relation_success_nodes == semantic_nodes:
            continue

        table_name = "no_evidence" if no_evidence_nodes else "all_evidence"
        bucket = _segment_priority_bucket(table_name, semantic_nodes, no_evidence_nodes, relation_success_nodes, rcsd50_by_node)
        segment_orders.append((_bucket_sort_value(bucket), 0 if table_name == "all_evidence" else 1, -float(attrs.get(segment_id, {}).get("segment_length_m") or 0.0), segment_id))
        for target_id in sorted(relation_gap_nodes):
            node = node_index.get(target_id, {})
            graph = graph_index.get(target_id, {})
            junction = junction_index.get(target_id, {})
            t03_hint, t04_hint, no_rcsd_reference_hint = _scene_hints(target_id, t03_index, t04_index)
            first_segment_id = first_target_segment.setdefault(target_id, segment_id)
            manual = existing_manual_rows.get(target_id, {})
            duplicate_policy = ""
            manual_row_consumable = 1
            comment = manual.get("comment", "")
            if first_segment_id != segment_id:
                duplicate_policy = f"duplicate_of_segment:{first_segment_id};do_not_consume_duplicate_row"
                manual_row_consumable = 0
                if not comment:
                    manual = {**manual, "comment": duplicate_policy}
            category, reason = _relation_gap_detail(target_id, graph, junction)
            row = _review_row(
                case_id=case_id,
                segment_id=segment_id,
                attrs=attrs.get(segment_id, {}),
                segment_priority_bucket=bucket,
                pair_nodes=pair_nodes,
                junc_nodes=junc_nodes,
                relation_success_nodes=relation_success_nodes,
                relation_gap_nodes=relation_gap_nodes,
                no_evidence_nodes=no_evidence_nodes,
                role=_segment_node_role(target_id, pair_nodes, junc_nodes),
                target_id=target_id,
                node=node,
                graph=graph,
                junction=junction,
                scope=segment_scope.get(segment_id, {}),
                step3=step3,
                t03_hint=t03_hint,
                t04_hint=t04_hint,
                no_rcsd_reference_hint=no_rcsd_reference_hint,
                rcsd50=rcsd50_by_node.get(target_id, _empty_rcsd50("")),
                manual=manual,
                first_segment_id=first_segment_id if first_segment_id != segment_id else "",
                duplicate_policy=duplicate_policy,
                manual_row_consumable=manual_row_consumable,
                relation_gap_category=category,
                relation_gap_reason=reason,
            )
            pending_rows.append((table_name, row))

    segment_rank = {
        segment_id: index
        for index, (_bucket_sort, _table_sort, _negative_length, segment_id) in enumerate(sorted(set(segment_orders)), start=1)
    }
    for table_name, row in pending_rows:
        row["segment_priority_rank"] = segment_rank.get(_text(row.get("swsd_segment_id")), 0)
        if table_name == "all_evidence":
            all_evidence_rows.append(row)
        else:
            no_evidence_rows.append(row)

    all_evidence_rows.sort(key=_review_sort_key)
    no_evidence_rows.sort(key=_review_sort_key)
    return SegmentRelationReviewTables(
        all_evidence_relation_gap_rows=all_evidence_rows,
        no_evidence_relation_gap_rows=no_evidence_rows,
    )


def write_review_xlsx(path: Path, rows: list[dict[str, Any]], *, sheet_name: str) -> None:
    write_text_xlsx(
        path,
        rows,
        SEGMENT_RELATION_GAP_REVIEW_FIELDS,
        sheet_name=sheet_name,
        validation_field="manual_relation_type",
        validation_values=MANUAL_AUDIT_TYPES,
    )


def _review_row(
    *,
    case_id: str,
    segment_id: str,
    attrs: dict[str, Any],
    segment_priority_bucket: str,
    pair_nodes: set[str],
    junc_nodes: set[str],
    relation_success_nodes: set[str],
    relation_gap_nodes: set[str],
    no_evidence_nodes: set[str],
    role: str,
    target_id: str,
    node: dict[str, Any],
    graph: dict[str, str],
    junction: dict[str, str],
    scope: dict[str, set[str]],
    step3: dict[str, str],
    t03_hint: str,
    t04_hint: str,
    no_rcsd_reference_hint: str,
    rcsd50: dict[str, Any],
    manual: dict[str, str],
    first_segment_id: str,
    duplicate_policy: str,
    manual_row_consumable: int,
    relation_gap_category: str = "no_effective_semantic_nodes",
    relation_gap_reason: str = "Segment has no effective pair/junc node after right-turn attachment filtering.",
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
        "segment_priority_rank": 0,
        "case_id": case_id,
        "swsd_segment_id": segment_id,
        "segment_length_m": attrs.get("segment_length_m", 0.0),
        "segment_priority_bucket": segment_priority_bucket,
        "sgrade": attrs.get("sgrade", ""),
        "segment_pair_nodes": _join_sorted(pair_nodes),
        "segment_junc_nodes": _join_sorted(junc_nodes),
        "segment_relation_success_node_ids": _join_sorted(relation_success_nodes),
        "segment_relation_gap_node_ids": _join_sorted(relation_gap_nodes),
        "segment_no_evidence_node_ids": _join_sorted(no_evidence_nodes),
        "node_role": role,
        "target_id": target_id,
        "has_evd": _text(node.get("has_evd")),
        "is_anchor": _text(node.get("is_anchor")),
        "relation_gap_category": relation_gap_category,
        "relation_gap_reason": relation_gap_reason,
        "t05_status": _text(graph.get("relation_status") or junction.get("status")),
        "t05_base_id": _text(graph.get("base_id") or junction.get("base_id") or junction.get("selected_main_rcsdnode_id")),
        "graph_consumable": int(_truthy(graph.get("graph_consumable"))),
        "graph_consumability_status": _text(graph.get("graph_consumability_status")),
        "t05_source_modules": _text(graph.get("source_modules") or junction.get("source_module")),
        "t05_scenes": _text(graph.get("scenes") or junction.get("scene")),
        "t05_reasons": _text(graph.get("reasons") or junction.get("reason") or junction.get("skipped_reason")),
        "t03_scene_hint": t03_hint,
        "t04_scene_hint": t04_hint,
        "upstream_no_rcsd_reference_hint": no_rcsd_reference_hint,
        "rcsd_50m_hint": rcsd50.get("hint", ""),
        "rcsd_50m_feature_count": rcsd50.get("feature_count", 0),
        "rcsd_50m_nearest_ids": rcsd50.get("nearest_ids", ""),
        "rcsd_50m_nearest_distance_m": rcsd50.get("nearest_distance_m", ""),
        "has_rcsd_in_segment_scope": int(bool(rcsd_nodes or rcsd_roads)),
        "machine_candidate_rcsdnode_ids": _join_sorted(rcsd_nodes),
        "machine_candidate_rcsdroad_ids": _join_sorted(rcsd_roads),
        "t06_step2_plan_status": _join_sorted(scope.get("plan_statuses", set())),
        "t06_step2_reject_reasons": _join_sorted(scope.get("reject_reasons", set())),
        "t06_root_cause_categories": _join_sorted(scope.get("root_causes", set())),
        "t06_step3_relation_status": _text(step3.get("relation_status")) or "missing_step3_relation",
        "t06_step3_relation_reason": _text(step3.get("relation_reason")),
        "duplicate_target_first_segment_id": first_segment_id,
        "duplicate_target_policy": duplicate_policy,
        "manual_row_consumable": manual_row_consumable,
        "manual_relation_type": manual.get("manual_relation_type", ""),
        "selected_ids": manual.get("selected_ids", ""),
        "comment": manual.get("comment", ""),
    }


def _segment_priority_bucket(
    table_name: str,
    semantic_nodes: set[str],
    no_evidence_nodes: set[str],
    relation_success_nodes: set[str],
    rcsd50_by_node: dict[str, dict[str, Any]],
) -> str:
    if table_name == "all_evidence":
        return "0_all_junctions_have_evidence"
    all_nodes_have_context = all(
        node_id in relation_success_nodes
        or node_id not in no_evidence_nodes
        or int(rcsd50_by_node.get(node_id, {}).get("feature_count") or 0) > 0
        for node_id in semantic_nodes
    )
    if all_nodes_have_context:
        return "0_no_evidence_but_all_nodes_have_context"
    has_partial_context = any(node_id not in no_evidence_nodes for node_id in semantic_nodes) or any(
        int(rcsd50_by_node.get(node_id, {}).get("feature_count") or 0) > 0 for node_id in no_evidence_nodes
    )
    if has_partial_context:
        return "1_no_evidence_with_partial_context"
    return "2_no_evidence_no_rcsd_50m_low_priority"


def _bucket_sort_value(bucket: str) -> int:
    if bucket.startswith("0_"):
        return 0
    if bucket.startswith("1_"):
        return 1
    return 2


def _review_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _bucket_sort_value(_text(row.get("segment_priority_bucket"))),
        -float(row.get("segment_length_m") or 0.0),
        _text(row.get("swsd_segment_id")),
        1 if _text(row.get("duplicate_target_policy")) else 0,
        _text(row.get("node_role")),
        _text(row.get("target_id")),
    )


def _scene_hints(
    target_id: str,
    t03_index: dict[str, dict[str, str]],
    t04_index: dict[str, dict[str, str]],
) -> tuple[str, str, str]:
    t03 = t03_index.get(target_id, {})
    t04 = t04_index.get(target_id, {})
    t03_hint = _compact_hint(
        "T03",
        t03,
        ("association_class", "template_class", "relation_state", "step7_state", "reason"),
    )
    t04_hint = _compact_hint(
        "T04",
        t04,
        ("scene_type", "junction_type", "rcsd_profile", "relation_state", "fallback_state", "reason"),
    )
    refs = []
    if _text(t03.get("association_class")) == "C":
        refs.append("T03 association_class=C")
    for field in ("scene_type", "junction_type", "fallback_state", "reason"):
        value = _text(t04.get(field))
        if value in {"3", "6"}:
            refs.append(f"T04 {field}={value}")
    return t03_hint, t04_hint, "|".join(refs)


def _compact_hint(prefix: str, row: dict[str, str], fields: tuple[str, ...]) -> str:
    parts = [f"{field}={_text(row.get(field))}" for field in fields if _text(row.get(field))]
    return f"{prefix}: " + "; ".join(parts) if parts else ""


def _rcsd_50m_context(node: dict[str, Any], rcsd_features: gpd.GeoDataFrame) -> dict[str, Any]:
    geom = node.get("geometry") if node else None
    if geom is None or rcsd_features.empty:
        return _empty_rcsd50("无RCSD")
    candidate_positions = rcsd_features.sindex.query(geom.buffer(50.0))
    candidates = rcsd_features.iloc[candidate_positions]
    distances = candidates.geometry.distance(geom)
    within = candidates.loc[distances <= 50.0].copy()
    if within.empty:
        _nearest_positions, nearest_distances = rcsd_features.sindex.nearest(
            geom,
            return_all=False,
            return_distance=True,
        )
        nearest = float(nearest_distances[0]) if len(nearest_distances) else None
        return {
            "hint": "无RCSD",
            "feature_count": 0,
            "nearest_ids": "",
            "nearest_distance_m": round(nearest, 3) if nearest is not None else "",
        }
    within["_distance"] = distances.loc[within.index]
    within = within.sort_values(["_distance", "feature_id"])
    return {
        "hint": "50m内有RCSD",
        "feature_count": int(len(within)),
        "nearest_ids": _join_sorted(within["feature_id"].astype(str).head(5).tolist()),
        "nearest_distance_m": round(float(within["_distance"].iloc[0]), 3),
    }


def _empty_rcsd50(hint: str) -> dict[str, Any]:
    return {"hint": hint, "feature_count": 0, "nearest_ids": "", "nearest_distance_m": ""}


def _rcsd_feature_gdf(rcsd_nodes: gpd.GeoDataFrame, rcsd_roads: gpd.GeoDataFrame, target_crs: Any) -> gpd.GeoDataFrame:
    frames = []
    for source, gdf in (("rcsdnode", rcsd_nodes), ("rcsdroad", rcsd_roads)):
        if gdf is None or gdf.empty or "geometry" not in gdf:
            continue
        current = gdf.copy()
        if target_crs and current.crs and current.crs != target_crs:
            current = current.to_crs(target_crs)
        ids = []
        for _, row in current.iterrows():
            feature_id = _text(row.get("id") or row.get("node_id") or row.get("road_id"))
            ids.append(f"{source}:{feature_id}" if feature_id else source)
        current["feature_id"] = ids
        frames.append(current[["feature_id", "geometry"]])
    if not frames:
        return gpd.GeoDataFrame(columns=["feature_id", "geometry"], geometry="geometry", crs=target_crs or "EPSG:3857")
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs=frames[0].crs or target_crs or "EPSG:3857",
    )


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


def _is_consumable_1v1_relation(
    target_id: str,
    graph_index: dict[str, dict[str, str]],
    junction_index: dict[str, dict[str, str]],
) -> bool:
    graph = graph_index.get(target_id, {})
    junction = junction_index.get(target_id, {})
    status = _text(graph.get("relation_status") or junction.get("status")).lower()
    base_id = _text(graph.get("base_id") or junction.get("base_id") or junction.get("selected_main_rcsdnode_id"))
    graph_status = _text(graph.get("graph_consumability_status"))
    multi = _text(junction.get("multi_base_relation")).lower()
    return (
        status in {"0", "success"}
        and bool(base_id)
        and base_id not in {"0", "-1"}
        and _truthy(graph.get("graph_consumable"))
        and graph_status == "base_node_graph_incident"
        and multi not in {"1", "true", "yes"}
    )


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


def _segment_attrs(segment_gdf: gpd.GeoDataFrame, segment_lengths: dict[str, float]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for _, row in segment_gdf.iterrows():
        segment_id = _text(row.get("id") or row.get("swsd_segment_id"))
        if segment_id:
            result[segment_id] = {
                "segment_length_m": round(segment_lengths.get(segment_id, 0.0), 3),
                "sgrade": _text(row.get("sgrade")),
            }
    return result


def _segment_records_by_length(segment_gdf: gpd.GeoDataFrame, segment_attrs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [row.to_dict() for _, row in segment_gdf.iterrows()],
        key=lambda row: (
            -float(segment_attrs.get(_text(row.get("id") or row.get("swsd_segment_id")), {}).get("segment_length_m", 0.0)),
            _text(row.get("id") or row.get("swsd_segment_id")),
        ),
    )


def _effective_segment_nodes(segment: dict[str, Any], non_right_turn_counts: dict[str, int]) -> tuple[set[str], set[str], set[str]]:
    pair_nodes = _parse_id_set(segment.get("pair_nodes"))
    raw_junc_nodes = _parse_id_set(segment.get("junc_nodes"))
    junc_nodes = {
        node_id for node_id in raw_junc_nodes if _is_effective_anchor_node(node_id, pair_nodes, raw_junc_nodes, non_right_turn_counts)
    }
    return pair_nodes, junc_nodes, pair_nodes | junc_nodes


def _is_effective_anchor_node(
    target_id: str,
    pair_nodes: set[str],
    junc_nodes: set[str],
    non_right_turn_counts: dict[str, int],
) -> bool:
    if target_id in pair_nodes:
        return True
    if target_id not in junc_nodes:
        return True
    if not non_right_turn_counts:
        return True
    return non_right_turn_counts.get(target_id, 0) > 2


def _non_right_turn_incident_road_counts(roads: gpd.GeoDataFrame) -> dict[str, int]:
    counts: dict[str, int] = {}
    if roads.empty or "snodeid" not in roads.columns or "enodeid" not in roads.columns:
        return counts
    for _, road in roads.iterrows():
        if _is_right_turn_road(road):
            continue
        for field in ("snodeid", "enodeid"):
            node_id = _text(road.get(field))
            if node_id and node_id not in {"0", "0.0", "-1"}:
                counts[node_id] = counts.get(node_id, 0) + 1
    return counts


def _is_right_turn_road(road: Any) -> bool:
    try:
        return bool(int(float(_text(road.get("formway")))) & 128)
    except ValueError:
        return False


def _node_index(nodes: gpd.GeoDataFrame) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    records = [row.to_dict() for _, row in nodes.iterrows()]
    for row in records:
        node_id = _text(row.get("id"))
        if node_id and node_id not in {"0", "0.0", "-1"}:
            result[node_id] = row
    for row in records:
        mainnodeid = _text(row.get("mainnodeid"))
        if mainnodeid and mainnodeid not in {"0", "0.0", "-1"}:
            result.setdefault(mainnodeid, row)
    return result


def _node_has_evidence(node: dict[str, Any]) -> bool:
    return _text(node.get("has_evd")).lower() == "yes"


def _segment_node_role(target_id: str, pair_nodes: set[str], junc_nodes: set[str]) -> str:
    roles = []
    if target_id in pair_nodes:
        roles.append("pair_node")
    if target_id in junc_nodes:
        roles.append("junc_node")
    return "|".join(roles)


def _merge_indexes(*indexes: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for index in indexes:
        for key, row in index.items():
            merged = result.setdefault(key, {})
            merged.update({field: value for field, value in row.items() if _text(value)})
    return result


def _index_by(rows: list[dict[str, str]], field: str) -> dict[str, dict[str, str]]:
    return {_text(row.get(field)): row for row in rows if _text(row.get(field))}


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


def _flatten(values: Iterable[Any]) -> Iterable[Any]:
    for value in values:
        if isinstance(value, (list, tuple, set)):
            yield from _flatten(value)
        else:
            yield value


def _join_sorted(values: Iterable[Any]) -> str:
    return "|".join(sorted({_text(value) for value in values if _text(value)}))


def _truthy(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "y", "success"}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()
