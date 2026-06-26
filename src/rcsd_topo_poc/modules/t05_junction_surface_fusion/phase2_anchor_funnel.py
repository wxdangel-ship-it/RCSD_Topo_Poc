from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .phase2_ids import normalize_target_id
from .phase2_models import (
    SCENE_DIRECT,
    SCENE_FAILURE,
    SCENE_GROUP_EXISTING,
    SCENE_NO_RCSD,
    SCENE_ROAD_SPLIT,
    SCENE_ROUNDABOUT,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    Phase2Evidence,
)
from .phase2_scene_classifier import SOURCE_T03, SOURCE_T04, SOURCE_T07, classify_evidence


SEMANTIC_JUNCTION_KIND_2_VALUES = (4, 8, 16, 64, 128, 2048)
SOURCE_FUNNEL_FIELDS = [
    "source_module",
    "input_junction_total",
    "success_evidence_junction_total",
    "no_rcsd_junction_total",
    "failure_evidence_junction_total",
    "handoff_to_t05_total",
    "accepted_by_t05_total",
    "success_after_t05_total",
    "failure_after_t05_total",
    "not_handed_to_t05_total",
]
KIND2_FUNNEL_FIELDS = [
    "kind_2",
    "junction_type",
    "semantic_junction_total",
    "evidence_junction_total",
    "relation_success_total",
    "graph_consumable_success_total",
    "graph_unconsumable_success_total",
    "relation_failure_total",
]
FAILURE_REASON_FIELDS = ["failure_category", "scene", "reason", "count"]
_PRIMARY_SOURCES = (SOURCE_T07, SOURCE_T03, SOURCE_T04)
_ACTIONABLE_SCENES = {SCENE_DIRECT, SCENE_GROUP_EXISTING, SCENE_ROAD_SPLIT, SCENE_ROUNDABOUT}
_JUNCTION_TYPE_BY_KIND_2 = {
    4: "center_junction",
    8: "merge",
    16: "diverge",
    64: "roundabout",
    128: "complex_divmerge",
    2048: "single_sided_t_mouth",
}
_T05_CLOSURE_REASONS = {
    "t07_rcsdintersection_base_not_in_rcsdnode_out",
    "missing_base_id_candidate",
    "rcsdroad_split_failed",
    "roundabout_rcsdnode_grouping_failed",
    "rcsdnode_grouping_failed",
}


def build_junction_anchor_funnel(
    *,
    swsd_nodes: list[dict[str, Any]],
    evidence_rows: list[Phase2Evidence],
    relation_features: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    relation_graph_consumability_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    semantic_junctions = _semantic_junction_records(swsd_nodes)
    semantic_ids = set(semantic_junctions)
    relation_rows = [feature.get("properties") or {} for feature in relation_features]
    relation_rows_by_target = {
        normalize_target_id(row.get("target_id")): row
        for row in relation_rows
        if normalize_target_id(row.get("target_id"))
    }
    semantic_relation_rows = {
        target_id: row
        for target_id, row in relation_rows_by_target.items()
        if target_id in semantic_ids
    }
    evidence_ids = {
        evidence.target_id
        for evidence in evidence_rows
        if evidence.source_module in _PRIMARY_SOURCES and evidence.target_id in semantic_ids
    }
    graph_consumable_targets = {
        normalize_target_id(row.get("target_id"))
        for row in relation_graph_consumability_rows
        if normalize_target_id(row.get("target_id")) in semantic_ids and _int_value(row.get("graph_consumable")) == 1
    }
    success_targets = {
        target_id
        for target_id, row in semantic_relation_rows.items()
        if _int_value(row.get("status")) == STATUS_SUCCESS
    }
    failure_targets = {
        target_id
        for target_id, row in semantic_relation_rows.items()
        if _int_value(row.get("status")) == STATUS_FAILURE
    }
    source_rows = _source_funnel_rows(
        semantic_ids=semantic_ids,
        evidence_rows=evidence_rows,
        audit_rows=audit_rows,
    )
    failure_breakdown, failure_reason_rows = _failure_breakdown(audit_rows, semantic_ids=semantic_ids)
    top_level = {
        "semantic_junction_total": len(semantic_ids),
        "evidence_junction_total": len(evidence_ids),
        "t05_phase2_target_total": len(semantic_relation_rows),
        "relation_published_total": len(semantic_relation_rows),
        "relation_success_total": len(success_targets),
        "relation_published_success_total": len(success_targets),
        "relation_failure_total": len(failure_targets),
        "graph_consumable_success_total": len(graph_consumable_targets & success_targets),
        "graph_unconsumable_success_total": len(success_targets - graph_consumable_targets),
        "relation_graph_consumable_total": len(graph_consumable_targets & success_targets),
        "relation_graph_unconsumable_total": len(success_targets - graph_consumable_targets),
        "relation_graph_consumable_rate": _rate(len(graph_consumable_targets & success_targets), len(success_targets)),
        "relation_graph_unconsumable_rate": _rate(len(success_targets - graph_consumable_targets), len(success_targets)),
        "non_semantic_phase2_target_total": len(relation_rows_by_target) - len(semantic_relation_rows),
    }
    kind2_rows = _kind2_funnel_rows(
        semantic_junctions=semantic_junctions,
        evidence_ids=evidence_ids,
        success_targets=success_targets,
        failure_targets=failure_targets,
        graph_consumable_targets=graph_consumable_targets,
    )
    return {
        "semantic_junction_kind_2_values": list(SEMANTIC_JUNCTION_KIND_2_VALUES),
        "semantic_junction_id_rule": "mainnodeid if valid else id",
        "top_level_funnel": top_level,
        "kind2_funnel": kind2_rows,
        "source_module_funnel": source_rows,
        "t05_failure_breakdown": failure_breakdown,
        "failure_reason_rows": failure_reason_rows,
        "notes": [
            "source_module_funnel is module-level contribution statistics; rows are not mutually exclusive across T07/T03/T04.",
            "top_level_funnel is restricted to semantic junctions with kind_2 in the configured set.",
        ],
    }


def _semantic_junction_records(swsd_nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for feature in swsd_nodes:
        props = feature.get("properties") or {}
        kind_2 = _int_value(_field_value(props, "kind_2"))
        if kind_2 not in SEMANTIC_JUNCTION_KIND_2_VALUES:
            continue
        junction_id = normalize_target_id(_field_value(props, "mainnodeid") or _field_value(props, "id"))
        if junction_id:
            result.setdefault(junction_id, {"kind_2": kind_2, "junction_type": _JUNCTION_TYPE_BY_KIND_2.get(kind_2, "unknown")})
    return result


def _kind2_funnel_rows(
    *,
    semantic_junctions: dict[str, dict[str, Any]],
    evidence_ids: set[str],
    success_targets: set[str],
    failure_targets: set[str],
    graph_consumable_targets: set[str],
) -> list[dict[str, Any]]:
    rows_by_kind: dict[int, dict[str, Any]] = {}
    for target_id, record in semantic_junctions.items():
        kind_2 = int(record["kind_2"])
        row = rows_by_kind.setdefault(
            kind_2,
            {
                "kind_2": kind_2,
                "junction_type": record["junction_type"],
                "semantic_junction_total": 0,
                "evidence_junction_total": 0,
                "relation_success_total": 0,
                "graph_consumable_success_total": 0,
                "graph_unconsumable_success_total": 0,
                "relation_failure_total": 0,
            },
        )
        row["semantic_junction_total"] += 1
        if target_id in evidence_ids:
            row["evidence_junction_total"] += 1
        if target_id in success_targets:
            row["relation_success_total"] += 1
            if target_id in graph_consumable_targets:
                row["graph_consumable_success_total"] += 1
            else:
                row["graph_unconsumable_success_total"] += 1
        if target_id in failure_targets:
            row["relation_failure_total"] += 1
    return [rows_by_kind[kind_2] for kind_2 in SEMANTIC_JUNCTION_KIND_2_VALUES if kind_2 in rows_by_kind]


def _source_funnel_rows(
    *,
    semantic_ids: set[str],
    evidence_rows: list[Phase2Evidence],
    audit_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_decisions: dict[str, dict[str, list[Any]]] = {
        source: defaultdict(list)
        for source in _PRIMARY_SOURCES
    }
    for evidence in evidence_rows:
        if evidence.source_module not in _PRIMARY_SOURCES or evidence.target_id not in semantic_ids:
            continue
        source_decisions[evidence.source_module][evidence.target_id].append(classify_evidence(evidence, junction_type="unknown"))
    adopted_by_source: dict[str, set[str]] = {source: set() for source in _PRIMARY_SOURCES}
    success_by_source: dict[str, set[str]] = {source: set() for source in _PRIMARY_SOURCES}
    failure_by_source: dict[str, set[str]] = {source: set() for source in _PRIMARY_SOURCES}
    for row in audit_rows:
        target_id = normalize_target_id(row.get("target_id"))
        if target_id not in semantic_ids:
            continue
        source_text = str(row.get("source_module") or "")
        for source in _PRIMARY_SOURCES:
            if source not in source_text.split("|"):
                continue
            adopted_by_source[source].add(target_id)
            if _int_value(row.get("status")) == STATUS_SUCCESS:
                success_by_source[source].add(target_id)
            elif _int_value(row.get("status")) == STATUS_FAILURE:
                failure_by_source[source].add(target_id)
    rows: list[dict[str, Any]] = []
    for source in _PRIMARY_SOURCES:
        decisions_by_target = source_decisions[source]
        input_targets = set(decisions_by_target)
        success_evidence = {
            target_id
            for target_id, decisions in decisions_by_target.items()
            if any(decision.scene in _ACTIONABLE_SCENES for decision in decisions)
        }
        no_rcsd = {
            target_id
            for target_id, decisions in decisions_by_target.items()
            if decisions and all(decision.scene == SCENE_NO_RCSD for decision in decisions)
        }
        failure_evidence = input_targets - success_evidence - no_rcsd
        handoff_targets = input_targets & {normalize_target_id(row.get("target_id")) for row in audit_rows}
        rows.append(
            {
                "source_module": source,
                "input_junction_total": len(input_targets),
                "success_evidence_junction_total": len(success_evidence),
                "no_rcsd_junction_total": len(no_rcsd),
                "failure_evidence_junction_total": len(failure_evidence),
                "handoff_to_t05_total": len(handoff_targets),
                "accepted_by_t05_total": len(adopted_by_source[source]),
                "success_after_t05_total": len(success_by_source[source]),
                "failure_after_t05_total": len(failure_by_source[source]),
                "not_handed_to_t05_total": len(input_targets - handoff_targets),
            }
        )
    return rows


def _failure_breakdown(
    audit_rows: list[dict[str, Any]],
    *,
    semantic_ids: set[str],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    category_counts: Counter[str] = Counter()
    reason_counts: Counter[tuple[str, str, str]] = Counter()
    for row in audit_rows:
        target_id = normalize_target_id(row.get("target_id"))
        if target_id not in semantic_ids or _int_value(row.get("status")) != STATUS_FAILURE:
            continue
        scene = str(row.get("scene") or "")
        reason = str(row.get("reason") or "")
        category = _failure_category(scene, reason)
        category_counts[category] += 1
        reason_counts[(category, scene, reason)] += 1
    rows = [
        {"failure_category": category, "scene": scene, "reason": reason, "count": count}
        for (category, scene, reason), count in sorted(reason_counts.items())
    ]
    return {
        "no_related_failure_total": category_counts["NO_RCSD"],
        "upstream_failure_total": category_counts["UPSTREAM_FAILED"],
        "t05_closure_failure_total": category_counts["T05_CLOSURE_FAILED"],
        "missing_evidence_failure_total": category_counts["MISSING_EVIDENCE"],
        "other_failure_total": category_counts["OTHER"],
    }, rows


def _failure_category(scene: str, reason: str) -> str:
    if scene == SCENE_NO_RCSD or reason == "no_related_rcsd":
        return "NO_RCSD"
    if reason in _T05_CLOSURE_REASONS:
        return "T05_CLOSURE_FAILED"
    if scene == "missing_relation_evidence" or reason == "missing_relation_evidence":
        return "MISSING_EVIDENCE"
    if scene == SCENE_FAILURE:
        return "UPSTREAM_FAILED"
    return "OTHER"


def _field_value(props: dict[str, Any], field_name: str) -> Any:
    for key, value in props.items():
        if key.lower() == field_name:
            return value
    return None


def _int_value(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)
