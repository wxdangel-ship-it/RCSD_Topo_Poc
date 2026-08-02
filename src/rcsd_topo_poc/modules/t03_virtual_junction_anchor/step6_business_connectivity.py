from __future__ import annotations

from itertools import combinations
from typing import Any

from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry


CONNECTIVITY_TERMINAL_TOLERANCE_M = 1.0


def _polygon_components(geometry: BaseGeometry | None) -> list[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if hasattr(geometry, "geoms"):
        return [
            part
            for item in geometry.geoms
            for part in _polygon_components(item)
        ]
    return []


def _terminal_component_ids(
    components: list[BaseGeometry],
    terminal: BaseGeometry,
    *,
    tolerance_m: float,
) -> tuple[int, ...]:
    probe = terminal.buffer(tolerance_m) if tolerance_m > 0 else terminal
    return tuple(
        index
        for index, component in enumerate(components)
        if component.intersects(probe)
    )


def build_business_connectivity_audit(
    *,
    source_surface: BaseGeometry | None,
    output_surface: BaseGeometry | None,
    terminals: dict[str, BaseGeometry],
    tolerance_m: float = CONNECTIVITY_TERMINAL_TOLERANCE_M,
) -> dict[str, Any]:
    source_components = _polygon_components(source_surface)
    output_components = _polygon_components(output_surface)
    ordered_terminal_ids = sorted(terminals)
    source_membership = {
        terminal_id: _terminal_component_ids(
            source_components,
            terminals[terminal_id],
            tolerance_m=tolerance_m,
        )
        for terminal_id in ordered_terminal_ids
    }
    output_membership = {
        terminal_id: _terminal_component_ids(
            output_components,
            terminals[terminal_id],
            tolerance_m=tolerance_m,
        )
        for terminal_id in ordered_terminal_ids
    }
    source_missing = [
        terminal_id for terminal_id in ordered_terminal_ids if not source_membership[terminal_id]
    ]
    output_missing = [
        terminal_id for terminal_id in ordered_terminal_ids if not output_membership[terminal_id]
    ]
    mismatch_rows: list[dict[str, Any]] = []
    comparable_pair_count = 0
    for left_id, right_id in combinations(ordered_terminal_ids, 2):
        left_source = set(source_membership[left_id])
        right_source = set(source_membership[right_id])
        left_output = set(output_membership[left_id])
        right_output = set(output_membership[right_id])
        if not left_source or not right_source or not left_output or not right_output:
            continue
        comparable_pair_count += 1
        source_connected = bool(left_source & right_source)
        output_connected = bool(left_output & right_output)
        if source_connected == output_connected:
            continue
        mismatch_rows.append(
            {
                "left_terminal_id": left_id,
                "right_terminal_id": right_id,
                "source_connected": source_connected,
                "output_connected": output_connected,
                "mismatch_type": (
                    "source_connected_output_split"
                    if source_connected
                    else "source_split_output_connected"
                ),
            }
        )
    comparable = bool(ordered_terminal_ids) and not source_missing
    equivalent = comparable and not output_missing and not mismatch_rows
    return {
        "mode": "business_terminal_connectivity_partition",
        "tolerance_m": tolerance_m,
        "terminal_count": len(ordered_terminal_ids),
        "terminal_ids": ordered_terminal_ids,
        "source_component_count": len(source_components),
        "output_component_count": len(output_components),
        "source_terminal_component_ids": {
            key: list(value) for key, value in source_membership.items()
        },
        "output_terminal_component_ids": {
            key: list(value) for key, value in output_membership.items()
        },
        "source_missing_terminal_ids": source_missing,
        "output_missing_terminal_ids": output_missing,
        "comparable_pair_count": comparable_pair_count,
        "mismatch_count": len(mismatch_rows),
        "mismatches": mismatch_rows,
        "comparable": comparable,
        "equivalent": equivalent,
        "silent_fix": False,
        "source_geometry_modified": False,
    }
