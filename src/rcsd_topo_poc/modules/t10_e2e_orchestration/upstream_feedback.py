from __future__ import annotations

import csv
import json
import ast
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import T10_MODULE_ID


SEGMENT_FIELDS = (
    "case_id",
    "swsd_segment_id",
    "problem_status",
    "recommended_module",
    "upstream_issue_owner",
    "failure_business_category",
    "reject_reason",
    "root_cause_category",
    "feedback_action",
    "manual_review_required",
    "rcsd_pair_nodes",
    "candidate_rcsd_pair_node_sets",
    "pair_anchor_error_swsd_nodes",
    "pair_anchor_error_original_rcsd_nodes",
    "pair_anchor_error_candidate_rcsd_nodes",
    "pair_anchor_endpoint_cluster_nodes",
    "pair_anchor_bridge_road_ids",
    "pair_anchor_bridge_length_m",
    "pair_anchor_diagnostic_source",
    "pair_anchor_diagnostic_reason",
    "evidence_artifacts",
    "problem_registry_path",
)

SUMMARY_FIELDS = (
    "recommended_module",
    "upstream_issue_owner",
    "failure_business_category",
    "reject_reason",
    "root_cause_category",
    "count",
    "sample_case_ids",
    "sample_swsd_segment_ids",
)

RELATION_FIELDS = (
    "case_id",
    "target_id",
    "base_id",
    "problem_status",
    "recommended_module",
    "upstream_issue_owner",
    "failure_business_category",
    "graph_consumability_status",
    "feedback_action",
    "manual_review_required",
    "source_modules",
    "source_case_ids",
    "scenes",
    "reasons",
    "affected_problem_segment_count",
    "affected_problem_segment_ids",
    "matched_rcsdnode_ids",
    "incident_rcsdnode_ids",
    "relation_graph_consumability_audit_path",
)

RELATION_SUMMARY_FIELDS = (
    "recommended_module",
    "upstream_issue_owner",
    "failure_business_category",
    "graph_consumability_status",
    "source_modules",
    "reasons",
    "count",
    "sample_case_ids",
    "sample_target_ids",
)

SIDE_GROUP_FIELDS = (
    "case_id",
    "swsd_segment_id",
    "source_problem_status",
    "swsd_endpoint_node_ids",
    "rcsd_primary_pair_node_ids",
    "candidate_rcsd_pair_node_sets",
    "candidate_group_rcsdnode_ids",
    "candidate_group_node_count",
    "recommended_module",
    "upstream_issue_owner",
    "failure_business_category",
    "reject_reason",
    "root_cause_category",
    "feedback_action",
    "side_group_action",
    "manual_review_required",
    "problem_registry_path",
)

SIDE_GROUP_ENDPOINT_FIELDS = (
    "case_id",
    "swsd_segment_id",
    "target_id",
    "endpoint_index",
    "source_problem_status",
    "rcsd_primary_node_id",
    "candidate_rcsdnode_ids",
    "candidate_rcsdnode_count",
    "candidate_rcsd_pair_node_sets",
    "recommended_module",
    "upstream_issue_owner",
    "failure_business_category",
    "reject_reason",
    "root_cause_category",
    "feedback_action",
    "side_group_action",
    "manual_review_required",
    "problem_registry_path",
)

PAIR_ANCHOR_ENDPOINT_CLUSTER_FIELDS = (
    "case_id",
    "swsd_segment_id",
    "target_id",
    "endpoint_index",
    "source_problem_status",
    "rcsd_primary_node_id",
    "endpoint_cluster_rcsdnode_ids",
    "endpoint_cluster_node_count",
    "candidate_rcsdnode_ids_from_pair_sets",
    "candidate_rcsd_pair_node_sets",
    "pair_anchor_error_swsd_nodes",
    "pair_anchor_error_original_rcsd_nodes",
    "pair_anchor_error_candidate_rcsd_nodes",
    "pair_anchor_bridge_road_ids",
    "pair_anchor_bridge_length_m",
    "pair_anchor_diagnostic_source",
    "pair_anchor_diagnostic_reason",
    "recommended_module",
    "upstream_issue_owner",
    "failure_business_category",
    "reject_reason",
    "root_cause_category",
    "feedback_action",
    "pair_anchor_cluster_action",
    "auto_consumable_by_t05",
    "manual_review_required",
    "problem_registry_path",
)


@dataclass(frozen=True)
class T10UpstreamFeedbackArtifacts:
    segments_csv: Path
    segments_json: Path
    summary_csv: Path
    summary_json: Path
    relations_csv: Path
    relations_json: Path
    relation_summary_csv: Path
    relation_summary_json: Path
    side_group_candidates_csv: Path
    side_group_candidates_json: Path
    side_group_endpoint_candidates_csv: Path
    side_group_endpoint_candidates_json: Path
    pair_anchor_endpoint_clusters_csv: Path
    pair_anchor_endpoint_clusters_json: Path
    segment_count: int
    summary_count: int
    relation_count: int
    relation_summary_count: int
    side_group_candidate_count: int
    side_group_endpoint_candidate_count: int
    pair_anchor_endpoint_cluster_count: int


def write_t10_upstream_feedback(
    *,
    run_root: Path,
    case_results: Sequence[Mapping[str, Any]],
) -> T10UpstreamFeedbackArtifacts:
    rows = _collect_requires_upstream_rows(case_results)
    summary_rows = _summary_rows(rows)
    side_group_rows = _side_group_candidate_rows(rows)
    side_group_endpoint_rows = _side_group_endpoint_candidate_rows(rows)
    side_group_endpoint_rows = _dedupe_side_group_endpoint_rows(
        [
            *side_group_endpoint_rows,
            *_relation_graph_bridge_endpoint_candidate_rows(case_results, rows),
        ]
    )
    pair_anchor_endpoint_cluster_rows = _pair_anchor_endpoint_cluster_rows(rows)
    relation_rows = _collect_relation_requires_upstream_rows(case_results)
    relation_summary_rows = _relation_summary_rows(relation_rows)
    segments_csv = run_root / "t10_upstream_feedback_segments.csv"
    segments_json = run_root / "t10_upstream_feedback_segments.json"
    summary_csv = run_root / "t10_upstream_feedback_summary.csv"
    summary_json = run_root / "t10_upstream_feedback_summary.json"
    relations_csv = run_root / "t10_upstream_feedback_relations.csv"
    relations_json = run_root / "t10_upstream_feedback_relations.json"
    relation_summary_csv = run_root / "t10_upstream_feedback_relation_summary.csv"
    relation_summary_json = run_root / "t10_upstream_feedback_relation_summary.json"
    side_group_candidates_csv = run_root / "t10_upstream_side_group_candidates.csv"
    side_group_candidates_json = run_root / "t10_upstream_side_group_candidates.json"
    side_group_endpoint_candidates_csv = run_root / "t10_upstream_side_group_endpoint_candidates.csv"
    side_group_endpoint_candidates_json = run_root / "t10_upstream_side_group_endpoint_candidates.json"
    pair_anchor_endpoint_clusters_csv = run_root / "t10_upstream_pair_anchor_endpoint_clusters.csv"
    pair_anchor_endpoint_clusters_json = run_root / "t10_upstream_pair_anchor_endpoint_clusters.json"

    _write_csv(segments_csv, rows, SEGMENT_FIELDS)
    _write_json(
        segments_json,
        {
            "module_id": T10_MODULE_ID,
            "produced_at_utc": _now_text(),
            "run_root": str(run_root),
            "segment_count": len(rows),
            "rows": rows,
            "qa": _qa_payload(),
        },
    )
    _write_csv(summary_csv, summary_rows, SUMMARY_FIELDS)
    _write_json(
        summary_json,
        {
            "module_id": T10_MODULE_ID,
            "produced_at_utc": _now_text(),
            "run_root": str(run_root),
            "segment_count": len(rows),
            "summary_count": len(summary_rows),
            "rows": summary_rows,
            "qa": _qa_payload(),
        },
    )
    _write_csv(side_group_candidates_csv, side_group_rows, SIDE_GROUP_FIELDS)
    _write_json(
        side_group_candidates_json,
        {
            "module_id": T10_MODULE_ID,
            "produced_at_utc": _now_text(),
            "run_root": str(run_root),
            "side_group_candidate_count": len(side_group_rows),
            "rows": side_group_rows,
            "qa": _qa_payload(),
        },
    )
    _write_csv(side_group_endpoint_candidates_csv, side_group_endpoint_rows, SIDE_GROUP_ENDPOINT_FIELDS)
    _write_json(
        side_group_endpoint_candidates_json,
        {
            "module_id": T10_MODULE_ID,
            "produced_at_utc": _now_text(),
            "run_root": str(run_root),
            "side_group_endpoint_candidate_count": len(side_group_endpoint_rows),
            "rows": side_group_endpoint_rows,
            "qa": _qa_payload(),
        },
    )
    _write_csv(
        pair_anchor_endpoint_clusters_csv,
        pair_anchor_endpoint_cluster_rows,
        PAIR_ANCHOR_ENDPOINT_CLUSTER_FIELDS,
    )
    _write_json(
        pair_anchor_endpoint_clusters_json,
        {
            "module_id": T10_MODULE_ID,
            "produced_at_utc": _now_text(),
            "run_root": str(run_root),
            "pair_anchor_endpoint_cluster_count": len(pair_anchor_endpoint_cluster_rows),
            "rows": pair_anchor_endpoint_cluster_rows,
            "qa": _qa_payload(),
        },
    )
    _write_csv(relations_csv, relation_rows, RELATION_FIELDS)
    _write_json(
        relations_json,
        {
            "module_id": T10_MODULE_ID,
            "produced_at_utc": _now_text(),
            "run_root": str(run_root),
            "relation_count": len(relation_rows),
            "rows": relation_rows,
            "qa": _qa_payload(),
        },
    )
    _write_csv(relation_summary_csv, relation_summary_rows, RELATION_SUMMARY_FIELDS)
    _write_json(
        relation_summary_json,
        {
            "module_id": T10_MODULE_ID,
            "produced_at_utc": _now_text(),
            "run_root": str(run_root),
            "relation_count": len(relation_rows),
            "summary_count": len(relation_summary_rows),
            "rows": relation_summary_rows,
            "qa": _qa_payload(),
        },
    )
    return T10UpstreamFeedbackArtifacts(
        segments_csv=segments_csv,
        segments_json=segments_json,
        summary_csv=summary_csv,
        summary_json=summary_json,
        relations_csv=relations_csv,
        relations_json=relations_json,
        relation_summary_csv=relation_summary_csv,
        relation_summary_json=relation_summary_json,
        side_group_candidates_csv=side_group_candidates_csv,
        side_group_candidates_json=side_group_candidates_json,
        side_group_endpoint_candidates_csv=side_group_endpoint_candidates_csv,
        side_group_endpoint_candidates_json=side_group_endpoint_candidates_json,
        pair_anchor_endpoint_clusters_csv=pair_anchor_endpoint_clusters_csv,
        pair_anchor_endpoint_clusters_json=pair_anchor_endpoint_clusters_json,
        segment_count=len(rows),
        summary_count=len(summary_rows),
        relation_count=len(relation_rows),
        relation_summary_count=len(relation_summary_rows),
        side_group_candidate_count=len(side_group_rows),
        side_group_endpoint_candidate_count=len(side_group_endpoint_rows),
        pair_anchor_endpoint_cluster_count=len(pair_anchor_endpoint_cluster_rows),
    )


def _collect_requires_upstream_rows(case_results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_result in case_results:
        case_id = str(case_result.get("case_id") or "").strip()
        case_run_dir = Path(str(case_result.get("case_run_dir") or ""))
        registry_path = (
            case_run_dir
            / "t06_step12"
            / "t06"
            / "step2_extract_rcsd_segments"
            / "t06_segment_replacement_problem_registry.csv"
        )
        if not registry_path.is_file():
            continue
        with registry_path.open(newline="", encoding="utf-8-sig") as fp:
            for raw in csv.DictReader(fp):
                if not _is_requires_upstream_status(raw.get("problem_status")):
                    continue
                row = {field: str(raw.get(field) or "") for field in SEGMENT_FIELDS if field != "problem_registry_path"}
                row["case_id"] = row.get("case_id") or case_id
                row["problem_registry_path"] = str(registry_path)
                rows.append(row)
    return rows


def _collect_relation_requires_upstream_rows(case_results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_result in case_results:
        case_id = str(case_result.get("case_id") or "").strip()
        case_run_dir = Path(str(case_result.get("case_run_dir") or ""))
        audit_path = case_run_dir / "t05" / "t05_phase2" / "relation_graph_consumability_audit.csv"
        if not audit_path.is_file():
            continue
        problem_segments_by_endpoint = _problem_segment_ids_by_endpoint(case_run_dir)
        with audit_path.open(newline="", encoding="utf-8-sig") as fp:
            for raw in csv.DictReader(fp):
                if str(raw.get("relation_status") or "").strip() != "0":
                    continue
                if str(raw.get("graph_consumable") or "").strip() == "1":
                    continue
                source_modules = _text(raw.get("source_modules"))
                target_id = _text(raw.get("target_id"))
                affected_problem_segments = problem_segments_by_endpoint.get(target_id, [])
                rows.append(
                    {
                        "case_id": case_id,
                        "target_id": target_id,
                        "base_id": _text(raw.get("base_id")),
                        "problem_status": "requires_upstream_iteration",
                        "recommended_module": _relation_recommended_module(source_modules),
                        "upstream_issue_owner": "T05",
                        "failure_business_category": "relation_graph_unconsumable",
                        "graph_consumability_status": _text(raw.get("graph_consumability_status")),
                        "feedback_action": "rerun_relation_evidence_or_t05_junctionization",
                        "manual_review_required": "true",
                        "source_modules": source_modules,
                        "source_case_ids": _text(raw.get("source_case_ids")),
                        "scenes": _text(raw.get("scenes")),
                        "reasons": _text(raw.get("reasons")),
                        "affected_problem_segment_count": str(len(affected_problem_segments)),
                        "affected_problem_segment_ids": "|".join(affected_problem_segments),
                        "matched_rcsdnode_ids": _text(raw.get("matched_rcsdnode_ids")),
                        "incident_rcsdnode_ids": _text(raw.get("incident_rcsdnode_ids")),
                        "relation_graph_consumability_audit_path": str(audit_path),
                    }
                )
    return rows


def _problem_segment_ids_by_endpoint(case_run_dir: Path) -> dict[str, list[str]]:
    registry_path = (
        case_run_dir
        / "t06_step12"
        / "t06"
        / "step2_extract_rcsd_segments"
        / "t06_segment_replacement_problem_registry.csv"
    )
    if not registry_path.is_file():
        return {}
    result: dict[str, list[str]] = {}
    with registry_path.open(newline="", encoding="utf-8-sig") as fp:
        for raw in csv.DictReader(fp):
            if not _is_requires_upstream_status(raw.get("problem_status")):
                continue
            segment_id = _text(raw.get("swsd_segment_id"))
            if not segment_id:
                continue
            for endpoint_id in _segment_endpoint_ids(segment_id):
                bucket = result.setdefault(endpoint_id, [])
                if segment_id not in bucket:
                    bucket.append(segment_id)
    return {endpoint_id: sorted(segment_ids) for endpoint_id, segment_ids in result.items()}


def _summary_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: Counter[tuple[str, str, str, str, str]] = Counter()
    samples: dict[tuple[str, str, str, str, str], dict[str, list[str]]] = {}
    for row in rows:
        key = (
            _text(row.get("recommended_module")),
            _text(row.get("upstream_issue_owner")),
            _text(row.get("failure_business_category")),
            _text(row.get("reject_reason")),
            _text(row.get("root_cause_category")),
        )
        groups[key] += 1
        bucket = samples.setdefault(key, {"case_ids": [], "segment_ids": []})
        _append_sample(bucket["case_ids"], _text(row.get("case_id")))
        _append_sample(bucket["segment_ids"], _text(row.get("swsd_segment_id")))

    result: list[dict[str, Any]] = []
    for key, count in groups.most_common():
        recommended_module, owner, category, reason, root_cause = key
        bucket = samples[key]
        result.append(
            {
                "recommended_module": recommended_module,
                "upstream_issue_owner": owner,
                "failure_business_category": category,
                "reject_reason": reason,
                "root_cause_category": root_cause,
                "count": count,
                "sample_case_ids": "|".join(bucket["case_ids"]),
                "sample_swsd_segment_ids": "|".join(bucket["segment_ids"]),
            }
        )
    return result


def _side_group_candidate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        if _text(row.get("problem_status")) != "requires_upstream_side_group_or_rcsd_directionality_review":
            continue
        rcsd_primary_pair = _parsed_id_list(row.get("rcsd_pair_nodes"))
        candidate_pair_sets = _parsed_id_sets(row.get("candidate_rcsd_pair_node_sets"))
        if not _has_side_group_extension(rcsd_primary_pair, candidate_pair_sets):
            continue
        candidate_group_ids = _unique_ids(
            [*rcsd_primary_pair, *[node_id for pair in candidate_pair_sets for node_id in pair]]
        )
        swsd_endpoint_ids = _parsed_id_list(row.get("swsd_pair_nodes")) or list(
            _segment_endpoint_ids(_text(row.get("swsd_segment_id")))
        )
        result.append(
            {
                "case_id": _text(row.get("case_id")),
                "swsd_segment_id": _text(row.get("swsd_segment_id")),
                "source_problem_status": _text(row.get("problem_status")),
                "swsd_endpoint_node_ids": "|".join(swsd_endpoint_ids),
                "rcsd_primary_pair_node_ids": "|".join(rcsd_primary_pair),
                "candidate_rcsd_pair_node_sets": ";".join("|".join(pair) for pair in candidate_pair_sets),
                "candidate_group_rcsdnode_ids": "|".join(candidate_group_ids),
                "candidate_group_node_count": str(len(candidate_group_ids)),
                "recommended_module": _text(row.get("recommended_module")),
                "upstream_issue_owner": _text(row.get("upstream_issue_owner")),
                "failure_business_category": _text(row.get("failure_business_category")),
                "reject_reason": _text(row.get("reject_reason")),
                "root_cause_category": _text(row.get("root_cause_category")),
                "feedback_action": _text(row.get("feedback_action")),
                "side_group_action": "evaluate_virtual_junction_grouping_before_rcsd_directionality_review",
                "manual_review_required": _text(row.get("manual_review_required")),
                "problem_registry_path": _text(row.get("problem_registry_path")),
            }
        )
    return result


def _side_group_endpoint_candidate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        if _text(row.get("problem_status")) != "requires_upstream_side_group_or_rcsd_directionality_review":
            continue
        swsd_endpoint_ids = _parsed_id_list(row.get("swsd_pair_nodes")) or list(_segment_endpoint_ids(_text(row.get("swsd_segment_id"))))
        rcsd_primary_pair = _parsed_id_list(row.get("rcsd_pair_nodes"))
        candidate_pair_sets = _parsed_id_sets(row.get("candidate_rcsd_pair_node_sets"))
        if not _has_side_group_extension(rcsd_primary_pair, candidate_pair_sets):
            continue
        for endpoint_index, target_id in enumerate(swsd_endpoint_ids):
            if not target_id:
                continue
            primary_node_id = rcsd_primary_pair[endpoint_index] if endpoint_index < len(rcsd_primary_pair) else ""
            other_primary_node_ids = {
                node_id
                for index, node_id in enumerate(rcsd_primary_pair)
                if index != endpoint_index and node_id
            }
            candidate_extension_ids = [
                pair[endpoint_index]
                for pair in candidate_pair_sets
                if endpoint_index < len(pair)
                and pair[endpoint_index]
                and pair[endpoint_index] not in other_primary_node_ids
            ]
            endpoint_candidates = _unique_ids(
                [
                    primary_node_id,
                    *candidate_extension_ids,
                ]
            )
            if len([node_id for node_id in endpoint_candidates if node_id and node_id != primary_node_id]) <= 0:
                continue
            result.append(
                {
                    "case_id": _text(row.get("case_id")),
                    "swsd_segment_id": _text(row.get("swsd_segment_id")),
                    "target_id": target_id,
                    "endpoint_index": str(endpoint_index),
                    "source_problem_status": _text(row.get("problem_status")),
                    "rcsd_primary_node_id": primary_node_id,
                    "candidate_rcsdnode_ids": "|".join(endpoint_candidates),
                    "candidate_rcsdnode_count": str(len(endpoint_candidates)),
                    "candidate_rcsd_pair_node_sets": ";".join("|".join(pair) for pair in candidate_pair_sets),
                    "recommended_module": _text(row.get("recommended_module")),
                    "upstream_issue_owner": _text(row.get("upstream_issue_owner")),
                    "failure_business_category": _text(row.get("failure_business_category")),
                    "reject_reason": _text(row.get("reject_reason")),
                    "root_cause_category": _text(row.get("root_cause_category")),
                    "feedback_action": _text(row.get("feedback_action")),
                    "side_group_action": "supplement_existing_relation_with_endpoint_rcsdnode_grouping",
                    "manual_review_required": _text(row.get("manual_review_required")),
                    "problem_registry_path": _text(row.get("problem_registry_path")),
                }
            )
    return result


def _relation_graph_bridge_endpoint_candidate_rows(
    case_results: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_case[_text(row.get("case_id"))].append(row)

    result: list[dict[str, Any]] = []
    for case_result in case_results:
        case_id = _text(case_result.get("case_id"))
        case_run_dir = Path(str(case_result.get("case_run_dir") or ""))
        segment_rows = rows_by_case.get(case_id, [])
        if not case_id or not case_run_dir or not segment_rows:
            continue

        t05_phase2_dir = case_run_dir / "t05" / "t05_phase2"
        relation_graph_path = t05_phase2_dir / "relation_graph_consumability_audit.csv"
        junctionization_path = t05_phase2_dir / "rcsd_junctionization_audit.csv"
        rcsdroad_path = t05_phase2_dir / "rcsdroad_out.gpkg"
        probe_path = (
            case_run_dir
            / "t06_step12"
            / "t06"
            / "step2_extract_rcsd_segments"
            / "t06_rcsd_buffer_only_probe.csv"
        )
        if not (
            relation_graph_path.is_file()
            and junctionization_path.is_file()
            and rcsdroad_path.is_file()
            and probe_path.is_file()
        ):
            continue

        road_adjacency = _read_rcsdroad_adjacency(rcsdroad_path)
        if not road_adjacency:
            continue

        result.extend(
            _relation_graph_bridge_endpoint_rows_from_tables(
                case_id=case_id,
                segment_rows=segment_rows,
                probe_rows=_read_csv_rows(probe_path),
                relation_rows=_read_csv_rows(relation_graph_path),
                junctionization_rows=_read_csv_rows(junctionization_path),
                road_adjacency=road_adjacency,
            )
        )
    return _dedupe_side_group_endpoint_rows(result)


def _relation_graph_bridge_endpoint_rows_from_tables(
    *,
    case_id: str,
    segment_rows: Sequence[Mapping[str, Any]],
    probe_rows: Sequence[Mapping[str, Any]],
    relation_rows: Sequence[Mapping[str, Any]],
    junctionization_rows: Sequence[Mapping[str, Any]],
    road_adjacency: Mapping[str, Sequence[tuple[str, str]]],
) -> list[dict[str, Any]]:
    probe_by_segment = {_text(row.get("swsd_segment_id")): row for row in probe_rows}
    consumable_relation_by_base = {
        _text(row.get("base_id")): row
        for row in relation_rows
        if _text(row.get("relation_status")) == "0"
        and _text(row.get("graph_consumable")) == "1"
        and _text(row.get("base_id"))
    }
    bridge_targets = _relation_graph_bridge_targets(relation_rows, junctionization_rows)
    if not bridge_targets:
        return []

    result: list[dict[str, Any]] = []
    for row in segment_rows:
        if not _is_relation_graph_bridge_problem(row):
            continue
        segment_id = _text(row.get("swsd_segment_id"))
        probe_row = probe_by_segment.get(segment_id)
        if not _is_bridge_probe_row(probe_row):
            continue
        primary_nodes = _parsed_id_list(row.get("rcsd_pair_nodes")) or _parsed_id_list(
            probe_row.get("original_rcsd_pair_nodes")
        )
        if len(primary_nodes) < 2:
            continue
        primary_node_set = set(primary_nodes)
        swsd_endpoint_ids = _parsed_id_list(row.get("swsd_pair_nodes")) or list(_segment_endpoint_ids(segment_id))
        candidate_nodes = _parsed_id_list(probe_row.get("candidate_rcsd_node_ids"))
        for candidate_node_id in candidate_nodes:
            if candidate_node_id in primary_node_set:
                continue
            candidate_relation = consumable_relation_by_base.get(candidate_node_id)
            if not candidate_relation:
                continue
            endpoint_path = _shortest_graph_path_to_any(
                candidate_node_id,
                primary_nodes,
                road_adjacency,
                max_hops=1,
            )
            if endpoint_path is None:
                continue

            target_matches = []
            for bridge_target in bridge_targets:
                if bridge_target["target_id"] in swsd_endpoint_ids:
                    continue
                if bridge_target["target_id"] == _text(candidate_relation.get("target_id")):
                    continue
                if bridge_target["base_id"] in primary_node_set:
                    continue
                if candidate_node_id in bridge_target["context_node_ids"]:
                    continue
                bridge_path = _shortest_graph_path_to_any(
                    candidate_node_id,
                    bridge_target["context_node_ids"],
                    road_adjacency,
                    max_hops=3,
                )
                if bridge_path is None:
                    continue
                if set(bridge_path["node_path"][1:-1]) & primary_node_set:
                    continue
                target_matches.append((bridge_path["hop_count"], bridge_target["target_id"], bridge_target))

            if not target_matches:
                continue
            _, _, bridge_target = sorted(target_matches, key=lambda item: (item[0], item[1]))[0]
            endpoint_index = str(primary_nodes.index(endpoint_path["target_node"]))
            candidate_ids = _unique_ids([bridge_target["base_id"], candidate_node_id])
            result.append(
                {
                    "case_id": case_id,
                    "swsd_segment_id": segment_id,
                    "target_id": bridge_target["target_id"],
                    "endpoint_index": endpoint_index,
                    "source_problem_status": _text(row.get("problem_status")),
                    "rcsd_primary_node_id": bridge_target["base_id"],
                    "candidate_rcsdnode_ids": "|".join(candidate_ids),
                    "candidate_rcsdnode_count": str(len(candidate_ids)),
                    "candidate_rcsd_pair_node_sets": _text(row.get("candidate_rcsd_pair_node_sets")),
                    "recommended_module": "T03/T04/T05",
                    "upstream_issue_owner": "T05",
                    "failure_business_category": _text(row.get("failure_business_category")),
                    "reject_reason": _text(row.get("reject_reason")),
                    "root_cause_category": _text(row.get("root_cause_category")),
                    "feedback_action": "rerun_t05_with_relation_graph_bridge_side_group",
                    "side_group_action": "supplement_existing_relation_with_relation_graph_bridge",
                    "manual_review_required": "false",
                    "problem_registry_path": _text(row.get("problem_registry_path")),
                }
            )
    return result


def _relation_graph_bridge_targets(
    relation_rows: Sequence[Mapping[str, Any]],
    junctionization_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    junction_by_target = {_text(row.get("target_id")): row for row in junctionization_rows}
    targets: list[dict[str, Any]] = []
    for row in relation_rows:
        target_id = _text(row.get("target_id"))
        audit_row = junction_by_target.get(target_id, {})
        source_modules = _text(row.get("source_modules"))
        source_module = _text(audit_row.get("source_module"))
        if "T10_SIDE_GROUP" not in source_modules and "T10_SIDE_GROUP" not in source_module:
            continue
        if _text(row.get("relation_status")) != "0" or _text(row.get("graph_consumable")) != "1":
            continue
        grouped_node_ids = _parsed_id_list(audit_row.get("grouped_rcsdnode_ids"))
        if len(grouped_node_ids) <= 1 and _text(audit_row.get("multi_base_relation")) != "1":
            continue
        base_id = _text(row.get("base_id")) or _text(audit_row.get("base_id"))
        context_node_ids = _unique_ids(
            [
                base_id,
                *_parsed_id_list(row.get("matched_rcsdnode_ids")),
                *_parsed_id_list(row.get("incident_rcsdnode_ids")),
                *grouped_node_ids,
                *_parsed_id_list(audit_row.get("original_rcsdnode_ids")),
                *_parsed_id_list(audit_row.get("new_rcsdnode_ids")),
            ]
        )
        if not target_id or not base_id or len(context_node_ids) <= 1:
            continue
        targets.append({"target_id": target_id, "base_id": base_id, "context_node_ids": context_node_ids})
    return targets


def _is_relation_graph_bridge_problem(row: Mapping[str, Any]) -> bool:
    return (
        _text(row.get("problem_status")) == "requires_upstream_side_group_or_rcsd_directionality_review"
        and _text(row.get("failure_business_category")) == "directionality_mismatch_fixable"
        and _text(row.get("reject_reason")) == "rcsd_not_bidirectional_for_swsd_dual"
    )


def _is_bridge_probe_row(row: Mapping[str, Any] | None) -> bool:
    if not row:
        return False
    return (
        _text(row.get("probe_status")) == "completed"
        and _text(row.get("buffer_only_candidate_status")) == "corridor_found"
        and _text(row.get("failure_business_category")) == "directionality_mismatch_fixable"
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fp:
        return [dict(row) for row in csv.DictReader(fp)]


def _read_rcsdroad_adjacency(path: Path) -> dict[str, list[tuple[str, str]]]:
    try:
        import pyogrio
    except ImportError:
        return {}
    try:
        frame = pyogrio.read_dataframe(path, columns=["id", "snodeid", "enodeid"], read_geometry=False)
    except Exception:
        return {}
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for record in frame.to_dict("records"):
        road_id = _text(record.get("id"))
        snodeid = _text(record.get("snodeid"))
        enodeid = _text(record.get("enodeid"))
        if not snodeid or not enodeid:
            continue
        adjacency[snodeid].append((enodeid, road_id))
        adjacency[enodeid].append((snodeid, road_id))
    return dict(adjacency)


def _shortest_graph_path_to_any(
    start_node_id: str,
    target_node_ids: Sequence[str],
    road_adjacency: Mapping[str, Sequence[tuple[str, str]]],
    *,
    max_hops: int,
) -> dict[str, Any] | None:
    start = _text(start_node_id)
    targets = set(_unique_ids(target_node_ids))
    if not start or not targets:
        return None
    if start in targets:
        return {"target_node": start, "hop_count": 0, "node_path": [start], "road_path": []}

    queue = deque([(start, [start], [])])
    seen = {start}
    while queue:
        node_id, node_path, road_path = queue.popleft()
        if len(road_path) >= max_hops:
            continue
        for next_node_id, road_id in road_adjacency.get(node_id, []):
            if next_node_id in seen:
                continue
            next_node_path = [*node_path, next_node_id]
            next_road_path = [*road_path, road_id]
            if next_node_id in targets:
                return {
                    "target_node": next_node_id,
                    "hop_count": len(next_road_path),
                    "node_path": next_node_path,
                    "road_path": next_road_path,
                }
            seen.add(next_node_id)
            queue.append((next_node_id, next_node_path, next_road_path))
    return None


def _dedupe_side_group_endpoint_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in rows:
        key = (
            _text(row.get("case_id")),
            _text(row.get("swsd_segment_id")),
            _text(row.get("target_id")),
            _text(row.get("rcsd_primary_node_id")),
            _text(row.get("candidate_rcsdnode_ids")),
            _text(row.get("side_group_action")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(row))
    return result


def _has_side_group_extension(primary_pair: Sequence[str], candidate_pair_sets: Sequence[Sequence[str]]) -> bool:
    primary_ids = set(_unique_ids(primary_pair))
    if not primary_ids:
        return False
    candidate_ids = set(_unique_ids(node_id for pair in candidate_pair_sets for node_id in pair))
    return bool(candidate_ids - primary_ids)


def _pair_anchor_endpoint_cluster_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        endpoint_clusters = _parsed_id_sets(row.get("pair_anchor_endpoint_cluster_nodes"))
        if not endpoint_clusters:
            continue
        swsd_endpoint_ids = _parsed_id_list(row.get("swsd_pair_nodes")) or list(
            _segment_endpoint_ids(_text(row.get("swsd_segment_id")))
        )
        rcsd_primary_pair = _parsed_id_list(row.get("rcsd_pair_nodes"))
        candidate_pair_sets = _parsed_id_sets(row.get("candidate_rcsd_pair_node_sets"))
        for endpoint_index, cluster_node_ids in enumerate(endpoint_clusters):
            target_id = swsd_endpoint_ids[endpoint_index] if endpoint_index < len(swsd_endpoint_ids) else ""
            primary_node_id = rcsd_primary_pair[endpoint_index] if endpoint_index < len(rcsd_primary_pair) else ""
            candidate_endpoint_ids = _unique_ids(
                [
                    pair[endpoint_index]
                    for pair in candidate_pair_sets
                    if endpoint_index < len(pair) and pair[endpoint_index]
                ]
            )
            auto_consumable = _pair_anchor_cluster_auto_consumable(
                row=row,
                target_id=target_id,
                primary_node_id=primary_node_id,
                cluster_node_ids=cluster_node_ids,
            )
            result.append(
                {
                    "case_id": _text(row.get("case_id")),
                    "swsd_segment_id": _text(row.get("swsd_segment_id")),
                    "target_id": target_id,
                    "endpoint_index": str(endpoint_index),
                    "source_problem_status": _text(row.get("problem_status")),
                    "rcsd_primary_node_id": primary_node_id,
                    "endpoint_cluster_rcsdnode_ids": "|".join(cluster_node_ids),
                    "endpoint_cluster_node_count": str(len(cluster_node_ids)),
                    "candidate_rcsdnode_ids_from_pair_sets": "|".join(candidate_endpoint_ids),
                    "candidate_rcsd_pair_node_sets": ";".join("|".join(pair) for pair in candidate_pair_sets),
                    "pair_anchor_error_swsd_nodes": _text(row.get("pair_anchor_error_swsd_nodes")),
                    "pair_anchor_error_original_rcsd_nodes": _text(row.get("pair_anchor_error_original_rcsd_nodes")),
                    "pair_anchor_error_candidate_rcsd_nodes": _text(row.get("pair_anchor_error_candidate_rcsd_nodes")),
                    "pair_anchor_bridge_road_ids": _text(row.get("pair_anchor_bridge_road_ids")),
                    "pair_anchor_bridge_length_m": _text(row.get("pair_anchor_bridge_length_m")),
                    "pair_anchor_diagnostic_source": _text(row.get("pair_anchor_diagnostic_source")),
                    "pair_anchor_diagnostic_reason": _text(row.get("pair_anchor_diagnostic_reason")),
                    "recommended_module": _text(row.get("recommended_module")),
                    "upstream_issue_owner": _text(row.get("upstream_issue_owner")),
                    "failure_business_category": _text(row.get("failure_business_category")),
                    "reject_reason": _text(row.get("reject_reason")),
                    "root_cause_category": _text(row.get("root_cause_category")),
                    "feedback_action": _text(row.get("feedback_action")),
                    "pair_anchor_cluster_action": (
                        "supplement_existing_relation_with_pair_anchor_endpoint_cluster"
                        if auto_consumable
                        else "publish_attribute_only_pair_anchor_cluster_for_upstream_review"
                    ),
                    "auto_consumable_by_t05": "true" if auto_consumable else "false",
                    "manual_review_required": _text(row.get("manual_review_required")),
                    "problem_registry_path": _text(row.get("problem_registry_path")),
                }
            )
    return result


def _pair_anchor_cluster_auto_consumable(
    *,
    row: Mapping[str, Any],
    target_id: str,
    primary_node_id: str,
    cluster_node_ids: Sequence[str],
) -> bool:
    if not target_id or not primary_node_id:
        return False
    cluster = _unique_ids(cluster_node_ids)
    if len(cluster) <= 1 or primary_node_id not in cluster:
        return False
    if not _is_requires_upstream_status(row.get("problem_status")):
        return False
    if _text(row.get("failure_business_category")) != "pair_anchor_mismatch":
        return False
    if _text(row.get("reject_reason")) != "rcsd_pair_nodes_not_distinct":
        return False
    if _text(row.get("pair_anchor_diagnostic_source")) != "buffer_only_endpoint_cluster":
        return False
    if _text(row.get("pair_anchor_diagnostic_reason")) != "short_connected_endpoint_cluster":
        return False
    return True


def _is_requires_upstream_status(value: Any) -> bool:
    return str(value or "").strip().startswith("requires_upstream")


def _parsed_id_list(value: Any) -> list[str]:
    parsed = _parse_literal(value)
    if isinstance(parsed, (list, tuple, set)):
        return _unique_ids(str(item).strip() for item in parsed if str(item).strip())
    text = _text(value)
    if not text:
        return []
    return _unique_ids(part.strip(" '\"[]") for part in text.replace(",", "|").split("|") if part.strip(" '\"[]"))


def _parsed_id_sets(value: Any) -> list[list[str]]:
    parsed = _parse_literal(value)
    result: list[list[str]] = []
    if isinstance(parsed, (list, tuple)):
        for item in parsed:
            if isinstance(item, (list, tuple, set)):
                ids = _unique_ids(str(part).strip() for part in item if str(part).strip())
                if ids:
                    result.append(ids)
            else:
                ids = _parsed_id_list(item)
                if ids:
                    result.append(ids)
    elif _text(value):
        ids = _parsed_id_list(value)
        if ids:
            result.append(ids)
    return result


def _parse_literal(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None


def _unique_ids(values: Sequence[str] | Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _relation_summary_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: Counter[tuple[str, str, str, str, str, str]] = Counter()
    samples: dict[tuple[str, str, str, str, str, str], dict[str, list[str]]] = {}
    for row in rows:
        key = (
            _text(row.get("recommended_module")),
            _text(row.get("upstream_issue_owner")),
            _text(row.get("failure_business_category")),
            _text(row.get("graph_consumability_status")),
            _text(row.get("source_modules")),
            _text(row.get("reasons")),
        )
        groups[key] += 1
        bucket = samples.setdefault(key, {"case_ids": [], "target_ids": []})
        _append_sample(bucket["case_ids"], _text(row.get("case_id")))
        _append_sample(bucket["target_ids"], _text(row.get("target_id")))

    result: list[dict[str, Any]] = []
    for key, count in groups.most_common():
        recommended_module, owner, category, status, source_modules, reasons = key
        bucket = samples[key]
        result.append(
            {
                "recommended_module": recommended_module,
                "upstream_issue_owner": owner,
                "failure_business_category": category,
                "graph_consumability_status": status,
                "source_modules": source_modules,
                "reasons": reasons,
                "count": count,
                "sample_case_ids": "|".join(bucket["case_ids"]),
                "sample_target_ids": "|".join(bucket["target_ids"]),
            }
        )
    return result


def _relation_recommended_module(source_modules: str) -> str:
    modules = {item for item in source_modules.split("|") if item}
    if modules:
        return "|".join(sorted(modules | {"T05"}))
    return "T05"


def _segment_endpoint_ids(segment_id: str) -> tuple[str, ...]:
    parts = [part.strip() for part in segment_id.split("_") if part.strip()]
    return tuple(parts) if len(parts) >= 2 else ()


def _append_sample(values: list[str], value: str, *, limit: int = 5) -> None:
    if not value or value in values or len(values) >= limit:
        return
    values.append(value)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _qa_payload() -> dict[str, Any]:
    return {
        "crs_and_transform": "This feedback artifact is attribute-only and references source registry paths; no geometry transform is performed.",
        "topology_consistency": "No topology mutation or silent repair is performed.",
        "geometry_semantics": "Rows preserve T06 Segment ids and root-cause fields without inventing spatial semantics.",
        "audit_traceability": "Each row records its source problem registry path and case id.",
        "performance_verifiability": "Aggregation is one pass over per-case CSV registries; summary records row counts.",
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
