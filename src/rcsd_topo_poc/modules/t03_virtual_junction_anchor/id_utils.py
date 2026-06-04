from __future__ import annotations

from typing import Any


def normalize_id(value: Any) -> str | None:
    """Normalize vector ID fields without preserving Fiona float artifacts."""
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if lower in {"null", "none", "nan"}:
        return None
    if text.endswith(".0"):
        prefix = text[:-2]
        if prefix.isdigit() or (prefix.startswith("-") and prefix[1:].isdigit()):
            return prefix
    return text


def stable_id_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value)
