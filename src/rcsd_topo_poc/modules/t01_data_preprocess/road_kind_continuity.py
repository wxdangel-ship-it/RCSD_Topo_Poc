from __future__ import annotations

from dataclasses import dataclass
from math import acos, degrees, hypot, isfinite
from typing import Any, Optional

from shapely.ops import linemerge


DEFAULT_KIND_CONTINUITY_ANGLE_TOLERANCE_DEG = 15.0


@dataclass(frozen=True)
class ContinuationDecision:
    edges: tuple[Any, ...]
    pruned_edges: tuple[Any, ...]
    same_level_applied: bool
    angle_applied: bool
    best_angle_deg: Optional[float]
    kept_angle_limit_deg: Optional[float]
    edge_angles_deg: dict[str, float]


def _sort_key(value: Any) -> tuple[int, Any]:
    text = str(value)
    if text.isdigit():
        return (0, int(text))
    return (1, text)


def _normalize_kind_token(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"{value:04d}"
    if isinstance(value, float):
        if not isfinite(value):
            return None
        if value.is_integer():
            return f"{int(value):04d}"
        return str(value).strip()

    token = str(value).strip()
    if not token:
        return None
    if token.endswith(".0") and token[:-2].isdigit():
        token = token[:-2]
    if token.isdigit() and len(token) < 4:
        token = token.zfill(4)
    return token


def road_kind_tokens(road: Any) -> tuple[str, ...]:
    raw_properties = getattr(road, "raw_properties", {}) or {}
    raw_kind = raw_properties.get("kind")
    if raw_kind is None:
        return ()

    values = raw_kind if isinstance(raw_kind, (list, tuple, set)) else str(raw_kind).split("|")
    tokens: list[str] = []
    for value in values:
        token = _normalize_kind_token(value)
        if token is None:
            continue
        tokens.append(token)
    return tuple(dict.fromkeys(tokens))


def road_kind_levels(road: Any) -> tuple[str, ...]:
    levels = [token[:2] for token in road_kind_tokens(road) if len(token) >= 2]
    return tuple(dict.fromkeys(levels))


def roads_share_kind_level(incoming_road: Any, outgoing_road: Any) -> bool:
    incoming_levels = set(road_kind_levels(incoming_road))
    if not incoming_levels:
        return False
    return bool(incoming_levels & set(road_kind_levels(outgoing_road)))


def _geometry_coords(geometry: Any) -> tuple[tuple[float, float], ...]:
    if geometry is None or getattr(geometry, "is_empty", False):
        return ()
    if geometry.geom_type == "LineString":
        return tuple((float(x), float(y)) for x, y in geometry.coords)

    merged = linemerge(geometry)
    if merged.geom_type == "LineString":
        return tuple((float(x), float(y)) for x, y in merged.coords)

    coords: list[tuple[float, float]] = []
    for part in getattr(merged, "geoms", ()):
        part_coords = [(float(x), float(y)) for x, y in part.coords]
        if not coords:
            coords.extend(part_coords)
        elif coords[-1] == part_coords[0]:
            coords.extend(part_coords[1:])
        else:
            coords.extend(part_coords)
    return tuple(coords)


def _semantic_endpoint_ids(road: Any, physical_to_semantic: dict[str, str]) -> tuple[str, str]:
    snodeid = str(getattr(road, "snodeid"))
    enodeid = str(getattr(road, "enodeid"))
    return physical_to_semantic.get(snodeid, snodeid), physical_to_semantic.get(enodeid, enodeid)


def _travel_vector(
    *,
    road: Any,
    from_node_id: str,
    to_node_id: str,
    physical_to_semantic: dict[str, str],
) -> Optional[tuple[float, float]]:
    coords = _geometry_coords(getattr(road, "geometry", None))
    if len(coords) < 2:
        return None

    snode_id, enode_id = _semantic_endpoint_ids(road, physical_to_semantic)
    if from_node_id == snode_id and to_node_id == enode_id:
        start, end = coords[0], coords[1]
    elif from_node_id == enode_id and to_node_id == snode_id:
        start, end = coords[-1], coords[-2]
    else:
        return None

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = hypot(dx, dy)
    if length <= 0.0:
        return None
    return dx / length, dy / length


def _angle_deg(
    incoming_vector: tuple[float, float],
    outgoing_vector: tuple[float, float],
) -> float:
    dot = incoming_vector[0] * outgoing_vector[0] + incoming_vector[1] * outgoing_vector[1]
    dot = max(-1.0, min(1.0, dot))
    return degrees(acos(dot))


def choose_preferred_continuation_edges(
    *,
    current_node_id: str,
    incoming_from_node_id: str,
    incoming_road_id: str,
    outgoing_edges: tuple[Any, ...],
    roads: dict[str, Any],
    physical_to_semantic: dict[str, str],
    angle_tolerance_deg: float = DEFAULT_KIND_CONTINUITY_ANGLE_TOLERANCE_DEG,
) -> ContinuationDecision:
    if len(outgoing_edges) <= 1:
        return ContinuationDecision(
            edges=outgoing_edges,
            pruned_edges=(),
            same_level_applied=False,
            angle_applied=False,
            best_angle_deg=None,
            kept_angle_limit_deg=None,
            edge_angles_deg={},
        )

    incoming_road = roads.get(incoming_road_id)
    if incoming_road is None:
        return ContinuationDecision(
            edges=outgoing_edges,
            pruned_edges=(),
            same_level_applied=False,
            angle_applied=False,
            best_angle_deg=None,
            kept_angle_limit_deg=None,
            edge_angles_deg={},
        )

    same_level_edges = tuple(
        edge
        for edge in outgoing_edges
        if (outgoing_road := roads.get(edge.road_id)) is not None
        and roads_share_kind_level(incoming_road, outgoing_road)
    )
    same_level_applied = bool(same_level_edges)
    level_edges = same_level_edges if same_level_applied else outgoing_edges

    edge_angles: dict[str, float] = {}
    incoming_vector = _travel_vector(
        road=incoming_road,
        from_node_id=incoming_from_node_id,
        to_node_id=current_node_id,
        physical_to_semantic=physical_to_semantic,
    )
    if incoming_vector is not None:
        for edge in level_edges:
            outgoing_road = roads.get(edge.road_id)
            if outgoing_road is None:
                continue
            outgoing_vector = _travel_vector(
                road=outgoing_road,
                from_node_id=current_node_id,
                to_node_id=edge.to_node,
                physical_to_semantic=physical_to_semantic,
            )
            if outgoing_vector is None:
                continue
            edge_angles[edge.road_id] = _angle_deg(incoming_vector, outgoing_vector)

    angle_applied = same_level_applied and len(level_edges) > 1 and len(edge_angles) == len(level_edges)
    best_angle: Optional[float] = None
    angle_limit: Optional[float] = None
    if angle_applied:
        best_angle = min(edge_angles.values())
        angle_limit = best_angle + angle_tolerance_deg
        selected_edges = tuple(edge for edge in level_edges if edge_angles[edge.road_id] <= angle_limit)
    else:
        selected_edges = level_edges

    selected_edges = tuple(
        sorted(
            selected_edges,
            key=lambda edge: (
                edge_angles.get(edge.road_id, 999.0),
                _sort_key(edge.road_id),
                _sort_key(edge.to_node),
            ),
        )
    )
    selected_keys = {(edge.road_id, edge.from_node, edge.to_node) for edge in selected_edges}
    pruned_edges = tuple(
        edge for edge in outgoing_edges if (edge.road_id, edge.from_node, edge.to_node) not in selected_keys
    )

    return ContinuationDecision(
        edges=selected_edges,
        pruned_edges=pruned_edges,
        same_level_applied=same_level_applied,
        angle_applied=angle_applied,
        best_angle_deg=best_angle,
        kept_angle_limit_deg=angle_limit,
        edge_angles_deg=edge_angles,
    )
