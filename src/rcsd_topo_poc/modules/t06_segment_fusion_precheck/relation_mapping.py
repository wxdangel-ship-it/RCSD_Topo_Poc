from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .parsing import ParseError, normalize_id, parse_positive_int


@dataclass(frozen=True)
class RelationRecord:
    target_id: str
    base_id: int
    status: int | None
    properties: dict[str, Any]


@dataclass(frozen=True)
class RelationCheck:
    ok: bool
    rcsd_pair_nodes: list[str]
    rcsd_junc_nodes: list[str]
    reject_reason: str | None = None
    failed_pair_nodes: list[str] | None = None
    failed_junc_nodes: list[str] | None = None
    failed_junc_reasons: dict[str, str] | None = None


def build_relation_map(features: list[dict[str, Any]]) -> dict[str, RelationRecord]:
    relation_map: dict[str, RelationRecord] = {}
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            target_id = normalize_id(props.get("target_id"))
        except ParseError:
            continue
        relation_map[target_id] = RelationRecord(
            target_id=target_id,
            base_id=parse_positive_int(props.get("base_id")) or 0,
            status=_parse_status(props.get("status")),
            properties=props,
        )
    return relation_map


def check_segment_relations(
    *,
    pair_nodes: list[str],
    junc_nodes: list[str],
    relation_map: dict[str, RelationRecord],
) -> RelationCheck:
    pair_ok, pair_base, pair_reason, pair_failed = _check_nodes(pair_nodes, relation_map, prefix="pair")
    if not pair_ok:
        return RelationCheck(False, [str(item) for item in pair_base], [], pair_reason, failed_pair_nodes=pair_failed)
    junc_base, junc_failed, junc_reasons = _map_optional_nodes(junc_nodes, relation_map, prefix="junc")
    if junc_failed:
        reason = junc_reasons.get(junc_failed[0]) or "junc_relation_failed"
        return RelationCheck(
            False,
            [str(item) for item in pair_base],
            [str(item) for item in junc_base],
            reason,
            failed_junc_nodes=junc_failed,
            failed_junc_reasons=junc_reasons,
        )
    return RelationCheck(
        True,
        [str(item) for item in pair_base],
        [str(item) for item in junc_base],
        failed_junc_nodes=junc_failed,
        failed_junc_reasons=junc_reasons,
    )


def accepted_base_ids(relation_map: dict[str, RelationRecord]) -> set[str]:
    return {str(item.base_id) for item in relation_map.values() if item.status == 0 and item.base_id > 0}


def _check_nodes(
    nodes: list[str],
    relation_map: dict[str, RelationRecord],
    *,
    prefix: str,
) -> tuple[bool, list[int], str | None, list[str]]:
    mapped: list[int] = []
    failed: list[str] = []
    reject_reason: str | None = None
    for node_id in nodes:
        relation = relation_map.get(node_id)
        if relation is None:
            failed.append(node_id)
            reject_reason = reject_reason or f"missing_{prefix}_relation"
            continue
        if relation.status != 0:
            failed.append(node_id)
            reject_reason = reject_reason or f"invalid_{prefix}_relation_status"
            continue
        if relation.base_id <= 0:
            failed.append(node_id)
            reject_reason = reject_reason or f"invalid_{prefix}_base_id"
            continue
        mapped.append(relation.base_id)
    if failed:
        return False, mapped, reject_reason, failed
    return True, mapped, None, []


def _map_optional_nodes(
    nodes: list[str],
    relation_map: dict[str, RelationRecord],
    *,
    prefix: str,
) -> tuple[list[int], list[str], dict[str, str]]:
    mapped: list[int] = []
    failed: list[str] = []
    reasons: dict[str, str] = {}
    for node_id in nodes:
        relation = relation_map.get(node_id)
        if relation is None:
            failed.append(node_id)
            reasons[node_id] = f"missing_{prefix}_relation"
            continue
        if relation.status != 0:
            failed.append(node_id)
            reasons[node_id] = f"invalid_{prefix}_relation_status"
            continue
        if relation.base_id <= 0:
            failed.append(node_id)
            reasons[node_id] = f"invalid_{prefix}_base_id"
            continue
        mapped.append(relation.base_id)
    return mapped, failed, reasons


def _parse_status(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None
