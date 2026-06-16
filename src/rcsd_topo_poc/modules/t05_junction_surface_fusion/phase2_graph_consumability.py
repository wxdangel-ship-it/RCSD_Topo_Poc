from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .phase2_ids import normalize_target_id
from .phase2_models import STATUS_SUCCESS


RELATION_GRAPH_CONSUMABILITY_FIELDS = [
    "target_id",
    "base_id",
    "relation_status",
    "graph_consumable",
    "graph_consumability_status",
    "matched_rcsdnode_ids",
    "incident_rcsdnode_ids",
    "source_modules",
    "source_case_ids",
    "scenes",
    "reasons",
    "recommended_action",
]


def build_relation_graph_consumability_rows(
    *,
    relation_features: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    rcsdnode_out_features: list[dict[str, Any]],
    rcsdroad_out_features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Audit whether published T05 relations can be consumed by RCSD road graph endpoints."""

    graph = _GraphIndex.from_features(
        rcsdnode_out_features=rcsdnode_out_features,
        rcsdroad_out_features=rcsdroad_out_features,
    )
    audit_by_target = _audit_context_by_target(audit_rows)
    rows: list[dict[str, Any]] = []
    for feature in relation_features:
        props = feature.get("properties") or {}
        target_id = normalize_target_id(props.get("target_id"))
        base_id = _int_value(props.get("base_id"))
        relation_status = _int_value(props.get("status"))
        context = audit_by_target.get(target_id, {})
        if relation_status != STATUS_SUCCESS:
            row_status = "relation_not_success"
            graph_consumable = 0
            matched_node_ids: list[int] = []
            incident_node_ids: list[int] = []
            recommended_action = "not_applicable"
        elif base_id is None or base_id <= 0:
            row_status = "success_relation_missing_base_id"
            graph_consumable = 0
            matched_node_ids = []
            incident_node_ids = []
            recommended_action = "upstream_relation_or_junctionization_review"
        else:
            row_status, graph_consumable, matched_node_ids, incident_node_ids = graph.evaluate(base_id)
            recommended_action = (
                "consume_as_relation"
                if graph_consumable
                else "upstream_relation_or_junctionization_review"
            )
        rows.append(
            {
                "target_id": target_id,
                "base_id": "" if base_id is None else str(base_id),
                "relation_status": "" if relation_status is None else str(relation_status),
                "graph_consumable": graph_consumable,
                "graph_consumability_status": row_status,
                "matched_rcsdnode_ids": _join_ints(matched_node_ids),
                "incident_rcsdnode_ids": _join_ints(incident_node_ids),
                "source_modules": context.get("source_modules", ""),
                "source_case_ids": context.get("source_case_ids", ""),
                "scenes": context.get("scenes", ""),
                "reasons": context.get("reasons", ""),
                "recommended_action": recommended_action,
            }
        )
    return rows


def relation_graph_consumability_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("graph_consumability_status") or "") for row in rows)
    unconsumable_rows = [
        row
        for row in rows
        if str(row.get("relation_status") or "") == str(STATUS_SUCCESS)
        and int(row.get("graph_consumable") or 0) != 1
    ]
    return {
        "relation_graph_consumability_row_count": len(rows),
        "relation_graph_consumable_count": sum(1 for row in rows if int(row.get("graph_consumable") or 0) == 1),
        "relation_graph_unconsumable_success_count": len(unconsumable_rows),
        "relation_graph_consumability_status_counts": dict(sorted(status_counts.items())),
        "relation_graph_consumability_passed": not unconsumable_rows,
    }


class _GraphIndex:
    def __init__(
        self,
        *,
        node_ids: set[int],
        endpoint_node_ids: set[int],
        mainnode_members: dict[int, list[int]],
    ) -> None:
        self.node_ids = node_ids
        self.endpoint_node_ids = endpoint_node_ids
        self.mainnode_members = mainnode_members

    @classmethod
    def from_features(
        cls,
        *,
        rcsdnode_out_features: list[dict[str, Any]],
        rcsdroad_out_features: list[dict[str, Any]],
    ) -> "_GraphIndex":
        node_ids: set[int] = set()
        mainnode_members: dict[int, set[int]] = defaultdict(set)
        for feature in rcsdnode_out_features:
            props = feature.get("properties") or {}
            node_id = _int_value(_field_value(props, "id"))
            if node_id is None:
                continue
            node_ids.add(node_id)
            mainnodeid = _int_value(_field_value(props, "mainnodeid"))
            if mainnodeid not in (None, 0, -1):
                mainnode_members[int(mainnodeid)].add(node_id)
        endpoint_node_ids: set[int] = set()
        for feature in rcsdroad_out_features:
            props = feature.get("properties") or {}
            for field in ("snodeid", "enodeid"):
                node_id = _int_value(_field_value(props, field))
                if node_id is not None:
                    endpoint_node_ids.add(node_id)
        return cls(
            node_ids=node_ids,
            endpoint_node_ids=endpoint_node_ids,
            mainnode_members={key: sorted(value) for key, value in mainnode_members.items()},
        )

    def evaluate(self, base_id: int) -> tuple[str, int, list[int], list[int]]:
        base_exists = base_id in self.node_ids
        group_members = list(self.mainnode_members.get(base_id, []))
        matched_node_ids = sorted({base_id, *group_members}) if base_exists else sorted(set(group_members))
        incident_node_ids = sorted(node_id for node_id in matched_node_ids if node_id in self.endpoint_node_ids)
        if base_exists and base_id in self.endpoint_node_ids:
            return "base_node_graph_incident", 1, matched_node_ids, incident_node_ids
        if base_exists and incident_node_ids:
            return "base_node_group_graph_incident", 1, matched_node_ids, incident_node_ids
        if base_exists:
            return "base_node_not_incident_to_rcsdroad", 0, matched_node_ids, incident_node_ids
        if group_members and incident_node_ids:
            return "base_mainnodeid_graph_incident", 1, matched_node_ids, incident_node_ids
        if group_members:
            return "base_mainnodeid_not_incident_to_rcsdroad", 0, matched_node_ids, incident_node_ids
        return "base_id_not_found_in_rcsdnode_out", 0, [], []


def _audit_context_by_target(audit_rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in audit_rows:
        target_id = normalize_target_id(row.get("target_id"))
        if not target_id:
            continue
        grouped[target_id]["source_modules"].add(_text(row.get("source_module")))
        grouped[target_id]["source_case_ids"].add(normalize_target_id(row.get("source_case_id")))
        grouped[target_id]["scenes"].add(_text(row.get("scene")))
        grouped[target_id]["reasons"].add(_text(row.get("reason")))
    return {
        target_id: {key: _join_texts(values) for key, values in values_by_key.items()}
        for target_id, values_by_key in grouped.items()
    }


def _field_value(properties: dict[str, Any], field_name: str) -> Any:
    for key, value in properties.items():
        if str(key).lower() == field_name.lower():
            return value
    return None


def _int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _join_ints(values: list[int]) -> str:
    return "|".join(str(value) for value in sorted(set(values)))


def _join_texts(values: set[str]) -> str:
    return "|".join(sorted(value for value in values if value))
