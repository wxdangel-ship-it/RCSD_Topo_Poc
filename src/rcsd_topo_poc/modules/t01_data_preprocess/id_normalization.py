from __future__ import annotations

import re
from typing import Any, Optional


_INTEGRAL_DECIMAL_TEXT_RE = re.compile(r"^([0-9]+)\.0+$")


def normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        return stripped
    return value


def normalize_id(value: Any) -> Optional[str]:
    normalized = normalize_scalar(value)
    if normalized is None:
        return None
    if isinstance(normalized, int):
        return str(normalized)
    if isinstance(normalized, float) and normalized.is_integer():
        return str(int(normalized))
    text = str(normalized)
    match = _INTEGRAL_DECIMAL_TEXT_RE.match(text)
    if match:
        return match.group(1)
    return text


def normalize_mainnodeid(value: Any) -> Optional[str]:
    normalized = normalize_id(value)
    if normalized in {None, "0"}:
        return None
    return normalized


def normalize_nullable_text(value: Any) -> Optional[str]:
    normalized = normalize_scalar(value)
    if normalized is None:
        return None
    return str(normalized)
