from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


NULL_ID_TEXT = {"", "nan", "none", "null"}


def normalize_target_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).strip()
    text = str(value).strip()
    if text.lower() in NULL_ID_TEXT:
        return ""
    try:
        decimal_value = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    if decimal_value == decimal_value.to_integral_value():
        return str(int(decimal_value))
    return text
