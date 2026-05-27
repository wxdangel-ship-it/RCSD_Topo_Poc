from __future__ import annotations

from typing import Any


def is_advance_right_turn_road(props: dict[str, Any], *, formway_bit: int = 128) -> bool:
    value = _parse_bitmask_int(props.get("formway"))
    return value is not None and (value & formway_bit) != 0


def is_uturn_road(props: dict[str, Any], *, formway_bit: int = 1024) -> bool:
    value = _parse_bitmask_int(props.get("formway"))
    return value is not None and (value & formway_bit) != 0


def _parse_bitmask_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).strip())
    except Exception:
        return None
    if not number.is_integer():
        return None
    return int(number)
