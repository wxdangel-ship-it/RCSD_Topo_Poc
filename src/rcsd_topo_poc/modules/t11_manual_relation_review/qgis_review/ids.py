from __future__ import annotations

from typing import Any, Iterable


NULL_ID_TEXTS = {"", "0", "NULL", "NONE", "NAN"}


def parse_selected_ids(value: Any) -> list[str]:
    text = _text(value)
    if not text or text.upper() == "NULL":
        return []
    return _dedupe(part.strip() for part in text.split("|"))


def join_selected_ids(values: Iterable[Any]) -> str:
    return "|".join(_dedupe(_text(value) for value in values))


def extract_rcsdnode_selected_ids(features: Iterable[Any]) -> str:
    ids: list[str] = []
    for feature in features:
        mainnodeid = _text(_feature_value(feature, "mainnodeid"))
        ids.append(mainnodeid if mainnodeid.upper() not in NULL_ID_TEXTS else _text(_feature_value(feature, "id")))
    return join_selected_ids(ids)


def extract_rcsdroad_selected_ids(features: Iterable[Any]) -> str:
    return join_selected_ids(_feature_value(feature, "id") for feature in features)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _feature_value(feature: Any, field: str) -> Any:
    if isinstance(feature, dict):
        return feature.get(field, "")
    try:
        return feature[field]
    except Exception:
        pass
    try:
        return feature.attribute(field)
    except Exception:
        return ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()
