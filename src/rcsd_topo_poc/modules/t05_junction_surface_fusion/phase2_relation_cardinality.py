from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .phase2_ids import normalize_target_id
from .phase2_models import STATUS_SUCCESS


RELATION_CARDINALITY_ERROR_FIELDS = [
    "error_type",
    "target_id",
    "base_id",
    "related_target_ids",
    "introduced_by_module",
    "source_modules",
    "source_case_ids",
    "scenes",
    "reasons",
]


def build_relation_cardinality_errors(
    *,
    relation_features: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    audit_by_target = _audit_by_target(audit_rows)
    success_rows = _success_relation_rows(relation_features)
    target_to_base: dict[str, set[str]] = defaultdict(set)
    base_to_target: dict[str, set[str]] = defaultdict(set)
    target_counter: Counter[str] = Counter()
    for row in success_rows:
        target_id = row["target_id"]
        base_id = row["base_id"]
        target_counter[target_id] += 1
        target_to_base[target_id].add(base_id)
        base_to_target[base_id].add(target_id)

    errors: list[dict[str, str]] = []
    for target_id, base_ids in sorted(target_to_base.items(), key=lambda item: _sort_key(item[0])):
        if len(base_ids) <= 1:
            continue
        info = _merged_audit_info([target_id], audit_by_target)
        errors.append(
            _error_row(
                error_type="one_target_to_many_base",
                target_ids=[target_id],
                base_ids=sorted(base_ids, key=_sort_key),
                audit_info=info,
            )
        )
    for base_id, target_ids in sorted(base_to_target.items(), key=lambda item: _sort_key(item[0])):
        if len(target_ids) <= 1:
            continue
        sorted_target_ids = sorted(target_ids, key=_sort_key)
        info = _merged_audit_info(sorted_target_ids, audit_by_target)
        errors.append(
            _error_row(
                error_type="many_target_to_one_base",
                target_ids=sorted_target_ids,
                base_ids=[base_id],
                audit_info=info,
            )
        )
    for target_id, count in sorted(target_counter.items(), key=lambda item: _sort_key(item[0])):
        if count <= 1:
            continue
        info = _merged_audit_info([target_id], audit_by_target)
        errors.append(
            _error_row(
                error_type="duplicate_target_rows",
                target_ids=[target_id],
                base_ids=sorted(target_to_base.get(target_id, set()), key=_sort_key),
                audit_info={**info, "reasons": [*info["reasons"], f"target_id duplicated {count} success rows"]},
            )
        )
    return errors


def relation_cardinality_summary(error_rows: list[dict[str, str]]) -> dict[str, Any]:
    counts = Counter(row.get("error_type", "") for row in error_rows)
    return {
        "relation_cardinality_error_count": len(error_rows),
        "one_target_to_many_base_count": int(counts["one_target_to_many_base"]),
        "many_target_to_one_base_count": int(counts["many_target_to_one_base"]),
        "duplicate_target_rows_count": int(counts["duplicate_target_rows"]),
        "relation_cardinality_passed": not error_rows,
    }


def relation_cardinality_error_target_ids(error_rows: list[dict[str, str]]) -> set[str]:
    target_ids: set[str] = set()
    for row in error_rows:
        target_ids.update(_normalized_parts(row.get("related_target_ids")))
        target_ids.update(_normalized_parts(row.get("target_id")))
    return target_ids


def filter_cardinality_error_relations(
    relation_features: list[dict[str, Any]],
    error_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], set[str], int]:
    target_ids = relation_cardinality_error_target_ids(error_rows)
    if not target_ids:
        return relation_features, set(), 0
    filtered = [
        feature
        for feature in relation_features
        if normalize_target_id((feature.get("properties") or {}).get("target_id")) not in target_ids
    ]
    return filtered, target_ids, len(relation_features) - len(filtered)


def _success_relation_rows(relation_features: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for feature in relation_features:
        props = feature.get("properties") or {}
        if _int_text(props.get("status")) != str(STATUS_SUCCESS):
            continue
        target_id = normalize_target_id(props.get("target_id"))
        base_id = _text(props.get("base_id"))
        if not target_id or base_id in {"", "0", "-1"}:
            continue
        rows.append({"target_id": target_id, "base_id": base_id})
    return rows


def _audit_by_target(audit_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in audit_rows:
        target_id = normalize_target_id(row.get("target_id"))
        if target_id:
            result[target_id].append(row)
    return result


def _merged_audit_info(target_ids: list[str], audit_by_target: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    modules: set[str] = set()
    case_ids: set[str] = set()
    scenes: set[str] = set()
    reasons: set[str] = set()
    for target_id in target_ids:
        for row in audit_by_target.get(target_id, []):
            modules.update(_parts(row.get("source_module")))
            case_ids.update(_parts(row.get("source_case_id")))
            scenes.update(_parts(row.get("scene")))
            reasons.update(_parts(row.get("reason")))
    return {
        "source_modules": sorted(modules, key=_sort_key),
        "source_case_ids": sorted(case_ids, key=_sort_key),
        "scenes": sorted(scenes, key=_sort_key),
        "reasons": sorted(reasons, key=_sort_key),
    }


def _error_row(
    *,
    error_type: str,
    target_ids: list[str],
    base_ids: list[str],
    audit_info: dict[str, list[str]],
) -> dict[str, str]:
    source_modules = audit_info["source_modules"]
    return {
        "error_type": error_type,
        "target_id": "|".join(target_ids),
        "base_id": "|".join(base_ids),
        "related_target_ids": "|".join(target_ids),
        "introduced_by_module": "|".join(source_modules) or "UNKNOWN",
        "source_modules": "|".join(source_modules),
        "source_case_ids": "|".join(audit_info["source_case_ids"]),
        "scenes": "|".join(audit_info["scenes"]),
        "reasons": "|".join(audit_info["reasons"]),
    }


def _parts(value: Any) -> set[str]:
    return {part for part in str(value or "").replace(",", "|").split("|") if part}


def _normalized_parts(value: Any) -> set[str]:
    return {normalized for item in _parts(value) if (normalized := normalize_target_id(item))}


def _int_text(value: Any) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return _text(value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, value)
