from __future__ import annotations

from typing import Any


def is_advance_right_turn_road(props: dict[str, Any], *, formway_bit: int = 128) -> bool:
    value = _parse_bitmask_int(props.get("formway"))
    return value is not None and (value & formway_bit) != 0


def is_uturn_road(props: dict[str, Any], *, formway_bit: int = 1024) -> bool:
    value = _parse_bitmask_int(props.get("formway"))
    return value is not None and (value & formway_bit) != 0


def is_near_advance_right_turn_duplicate(
    props: dict[str, Any],
    geometry: Any,
    candidate_geometries: list[Any],
    *,
    formway_bit: int = 128,
    buffer_m: float = 8.0,
    min_covered_ratio: float = 0.2,
) -> bool:
    if not is_advance_right_turn_road(props, formway_bit=formway_bit):
        return False
    if geometry is None or geometry.is_empty or not candidate_geometries:
        return False
    length = float(geometry.length or 0.0)
    if length <= 0:
        return False
    for candidate in candidate_geometries:
        if candidate is None or candidate.is_empty:
            continue
        if geometry.intersection(candidate.buffer(buffer_m)).length / length >= min_covered_ratio:
            return True
    return False


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
