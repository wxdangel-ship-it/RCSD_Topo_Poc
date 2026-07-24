from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


_JSG_PAYLOAD_KEYS = {
    "carrier_domain",
    "direction",
    "direction_role",
    "direction_structure",
    "explicit_loop",
    "growth_level",
    "junction_type",
    "outcome",
    "physical_reachable",
    "road_grade",
    "state",
    "structural_role",
}

_ROAD_PROPERTY_KEYS = {
    "direction",
    "generated",
    "is_split",
    "kind",
    "kind_2",
    "source",
}

_V0_WEIGHTS = {
    "payload:state=PUBLISHABLE": -1.0,
    "payload:state=REVIEW": 0.0,
    "payload:state=UNKNOWN": 1.0,
    "payload:direction_structure=UNKNOWN": 0.8,
    "payload:direction_role=UNKNOWN": 0.8,
    "payload:outcome=PRESENT": -0.25,
    "payload:outcome=ABSENT": 0.0,
    "payload:outcome=AUXILIARY_INTERNAL": -0.2,
    "payload:outcome=NOT_MATERIALIZED": -0.5,
    "payload:junction_type=TERMINAL_UNKNOWN": 0.3,
    "payload:junction_type=TERMINAL_DATA_BOUNDARY": -0.2,
    "source_kind:STRATEGY_REPLAY": -2.0,
    "source_kind:BASE_IDENTITY": -0.4,
    "lineage_kind:base_identity": -0.2,
    "lineage_kind:base_drop": 0.5,
    "action:COPY": -0.4,
    "action:DROP": 0.3,
    "action:UPDATE": -0.2,
    "action:SPLIT": -0.25,
    "action:CREATE": -0.2,
    "action:SELECT": -0.2,
    "source_role:t06_frcsd_road": -0.8,
    "source_role:t06_frcsd_node": -0.8,
    "source_role:t05_rcsdnode_out": -0.6,
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 3:
        return "2-3"
    if value <= 7:
        return "4-7"
    return "8+"


def _property(properties: Mapping[str, Any], name: str) -> Any:
    folded = name.casefold()
    for key, value in properties.items():
        if str(key).casefold() == folded:
            return value
    return None


def jsg_feature_tokens(candidate: Mapping[str, Any], *, group_option_count: int) -> tuple[str, ...]:
    tokens = {
        "domain:JSG",
        f"stage:{_text(candidate.get('stage'))}",
        f"object_type:{_text(candidate.get('object_type'))}",
        f"group_mode:{_text(candidate.get('group_mode'))}",
        f"dependency_count:{_bucket(len(list(candidate.get('dependencies') or [])))}",
        f"evidence_count:{_bucket(len(list(candidate.get('evidence_refs') or [])))}",
        f"group_option_count:{_bucket(group_option_count)}",
    }
    payload = dict(candidate.get("payload") or {})
    for key in sorted(_JSG_PAYLOAD_KEYS):
        value = _text(payload.get(key))
        if value:
            tokens.add(f"payload:{key}={value}")
    for value in candidate.get("source_kinds") or []:
        text = _text(value)
        if text:
            tokens.add(f"source_kind:{text}")
    for row in candidate.get("evidence_refs") or []:
        role = _text(dict(row).get("role"))
        if role:
            tokens.add(f"evidence_role:{role}")
    return tuple(sorted(tokens))


def roadgraph_feature_tokens(
    candidate: Mapping[str, Any], *, group_option_count: int
) -> tuple[str, ...]:
    outputs = list(candidate.get("output_payloads") or [])
    tokens = {
        "domain:ROADGRAPH",
        f"stage:{_text(candidate.get('stage'))}",
        f"object_kind:{_text(candidate.get('object_kind'))}",
        f"action:{_text(candidate.get('action'))}",
        f"lineage_kind:{_text(candidate.get('lineage_kind'))}",
        f"group_mode:{_text(candidate.get('group_mode'))}",
        f"has_base:{'true' if _text(candidate.get('base_object_id')) else 'false'}",
        f"output_count:{_bucket(len(outputs))}",
        f"pointer_state:{'SELECT' if _text(candidate.get('pointer_value')) else 'EMPTY'}",
        f"source_count:{_bucket(len(list(candidate.get('sources') or [])))}",
        f"group_option_count:{_bucket(group_option_count)}",
    }
    for source in candidate.get("sources") or []:
        row = dict(source)
        kind = _text(row.get("source_kind"))
        role = _text(row.get("role"))
        if kind:
            tokens.add(f"source_kind:{kind}")
        if role:
            tokens.add(f"source_role:{role}")
    for output in outputs:
        row = dict(output)
        geometry_type = _text(dict(row.get("geometry") or {}).get("type"))
        if geometry_type:
            tokens.add(f"geometry_type:{geometry_type}")
        properties = dict(row.get("properties") or {})
        for key in sorted(_ROAD_PROPERTY_KEYS):
            value = _text(_property(properties, key))
            if value:
                tokens.add(f"property:{key}={value}")
    return tuple(sorted(tokens))


def v0_cost(tokens: Iterable[str]) -> float:
    unique = tuple(sorted(set(tokens)))
    return float(sum(_V0_WEIGHTS.get(token, 0.0) for token in unique))


def v0_weight_contract() -> dict[str, Any]:
    return {
        "schema_version": "p05-jsg-p2-v0-explicit-model-v1",
        "feature_weights": dict(sorted(_V0_WEIGHTS.items())),
        "unknown_feature_weight": 0.0,
    }


def score_confidence(best_cost: float, second_cost: float | None) -> tuple[float, float, float]:
    if second_cost is None:
        return 1.0, 0.0, math.inf
    margin = max(0.0, float(second_cost) - float(best_cost))
    confidence = 1.0 / (1.0 + math.exp(-min(margin, 60.0)))
    return confidence, 1.0 - confidence, margin


def forbidden_feature_hits(tokens: Iterable[str], candidate: Mapping[str, Any]) -> list[str]:
    identifiers = {
        _text(candidate.get("candidate_id")),
        _text(candidate.get("case_key")),
        _text(candidate.get("business_id")),
        _text(candidate.get("object_key")),
        _text(candidate.get("group_id")),
        _text(candidate.get("base_object_id")),
    }
    identifiers.discard("")
    hits: list[str] = []
    for token in tokens:
        folded = token.casefold()
        if any(marker in folded for marker in ("truth", "oracle", "candidate_id", "group_id", "case_id")):
            hits.append(token)
            continue
        if any(value and value in token for value in identifiers):
            hits.append(token)
    return sorted(set(hits))


__all__ = [
    "forbidden_feature_hits",
    "jsg_feature_tokens",
    "roadgraph_feature_tokens",
    "score_confidence",
    "v0_cost",
    "v0_weight_contract",
]
