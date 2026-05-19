from __future__ import annotations

from typing import Any

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from .phase2_models import RELATION_FIELDS, STATUS_FAILURE, STATUS_SUCCESS, SwsdTargetContext


def success_relation_feature(
    *,
    context: SwsdTargetContext,
    base_id: int,
    rcsd_point: BaseGeometry | None,
) -> dict[str, Any]:
    base_point = rcsd_point if rcsd_point is not None and not rcsd_point.is_empty else context.point
    return _relation_feature(
        target_id=context.target_id,
        base_id=base_id,
        status=STATUS_SUCCESS,
        level=context.level,
        is_highway=context.is_highway,
        start_point=context.point,
        end_point=base_point,
    )


def failure_relation_feature(
    *,
    context: SwsdTargetContext,
    reason_point: BaseGeometry | None = None,
) -> dict[str, Any]:
    end_point = reason_point if reason_point is not None and not reason_point.is_empty else context.point
    return _relation_feature(
        target_id=context.target_id,
        base_id=0,
        status=STATUS_FAILURE,
        level=context.level,
        is_highway=context.is_highway,
        start_point=context.point,
        end_point=end_point,
    )


def relation_properties(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") or {}
    return {field: props.get(field) for field in RELATION_FIELDS}


def _relation_feature(
    *,
    target_id: str,
    base_id: int,
    status: int,
    level: Any,
    is_highway: Any,
    start_point: BaseGeometry,
    end_point: BaseGeometry,
) -> dict[str, Any]:
    line = LineString([(start_point.x, start_point.y), (end_point.x, end_point.y)])
    return {
        "properties": {
            "target_id": target_id,
            "base_id": base_id,
            "status": status,
            "level": level if level not in (None, "") else -1,
            "is_highway": is_highway if is_highway not in (None, "") else -1,
        },
        "geometry": line,
    }
