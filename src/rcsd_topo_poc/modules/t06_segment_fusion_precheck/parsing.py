from __future__ import annotations

import ast
import json
import math
import re
from typing import Any


NULL_TEXTS = {"", "none", "null", "nan", "na", "n/a", "[]"}


class ParseError(ValueError):
    pass


def normalize_id(value: Any) -> str:
    if value is None:
        raise ParseError("empty id")
    if isinstance(value, bool):
        raise ParseError("boolean id")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ParseError("non-finite id")
        if value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip().strip("\"'")
    if text.lower() in NULL_TEXTS:
        raise ParseError("empty id")
    if re.fullmatch(r"-?\d+\.0+", text):
        return str(int(float(text)))
    return text


def parse_positive_int(value: Any) -> int | None:
    try:
        text = normalize_id(value)
    except ParseError:
        return None
    if not re.fullmatch(r"-?\d+", text):
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


def parse_id_list(value: Any, *, allow_empty: bool = True) -> list[str]:
    if _is_empty(value):
        if allow_empty:
            return []
        raise ParseError("empty list")
    if isinstance(value, (list, tuple, set)):
        return _normalize_sequence(list(value), allow_empty=allow_empty)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _normalize_sequence([value], allow_empty=allow_empty)

    text = str(value).strip()
    if text.lower() in NULL_TEXTS:
        if allow_empty:
            return []
        raise ParseError("empty list")

    parsed = _parse_structured_text(text)
    if parsed is not None:
        if isinstance(parsed, (list, tuple, set)):
            return _normalize_sequence(list(parsed), allow_empty=allow_empty)
        return _normalize_sequence([parsed], allow_empty=allow_empty)

    cleaned = text.strip("[](){}")
    cleaned = cleaned.replace("\\", ",")
    parts = [part for part in re.split(r"[,;|\s]+", cleaned) if part.strip()]
    return _normalize_sequence(parts, allow_empty=allow_empty)


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def directionality_from_sgrade(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text.endswith("双") or text in {"dual", "bidirectional", "two_way", "twoway"}:
        return "dual"
    if text.endswith("单") or text in {"single", "oneway", "one_way"}:
        return "single"
    return None


def yes_value(value: Any) -> bool:
    return str(value or "").strip().lower() == "yes"


def anchor_eligible(value: Any) -> bool:
    return str(value or "").strip().lower() in {"yes", "fail4_fallback"}


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _parse_structured_text(text: str) -> Any | None:
    if not text or text[0] not in "[({\"'":
        return None
    for loader in (json.loads, ast.literal_eval):
        try:
            return loader(text)
        except Exception:
            continue
    return None


def _normalize_sequence(values: list[Any], *, allow_empty: bool) -> list[str]:
    result: list[str] = []
    for value in values:
        if _is_empty(value):
            continue
        result.append(normalize_id(value))
    if not result and not allow_empty:
        raise ParseError("empty list")
    return result
