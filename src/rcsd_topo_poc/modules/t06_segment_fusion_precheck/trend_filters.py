from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from .rcsd_candidate_extraction import RcsdCandidate


@dataclass(frozen=True)
class TrendResult:
    passed: bool
    reason: str
    metrics: dict[str, Any]


def evaluate_candidate(
    *,
    candidate: RcsdCandidate,
    swsd_directionality: str,
    swsd_pair_nodes: list[str],
    swsd_junc_nodes: list[str],
    rcsd_pair_nodes: list[str],
    rcsd_junc_nodes: list[str],
    all_relation_base_ids: set[str],
    swsd_geometry: BaseGeometry | None,
    swsd_node_geometries: dict[str, BaseGeometry],
    rcsd_node_geometries: dict[str, BaseGeometry],
    max_main_axis_angle_diff_deg: float,
    min_coarse_length_ratio: float,
    max_coarse_length_ratio: float,
) -> TrendResult:
    metrics: dict[str, Any] = {
        "directionality_trend_pass": True,
        "oneway_direction_trend_pass": True,
        "semantic_junc_order_trend_pass": True,
        "main_axis_angle_diff_deg": None,
        "main_axis_trend_pass": True,
        "length_ratio": None,
        "coarse_length_trend_pass": True,
    }

    junc_result = _check_junc_rules(candidate, set(rcsd_pair_nodes), rcsd_junc_nodes, all_relation_base_ids)
    if junc_result is not None:
        metrics["semantic_junc_order_trend_pass"] = False
        return TrendResult(False, junc_result, metrics)

    order_result = _check_junc_order(candidate.path.node_path, swsd_directionality, swsd_junc_nodes, rcsd_junc_nodes)
    if order_result is not None:
        metrics["semantic_junc_order_trend_pass"] = False
        return TrendResult(False, order_result, metrics)

    angle = _main_axis_angle(
        swsd_directionality=swsd_directionality,
        swsd_pair_nodes=swsd_pair_nodes,
        rcsd_pair_nodes=rcsd_pair_nodes,
        swsd_geometry=swsd_geometry,
        candidate_geometry=candidate.path.geometry,
        swsd_node_geometries=swsd_node_geometries,
        rcsd_node_geometries=rcsd_node_geometries,
    )
    metrics["main_axis_angle_diff_deg"] = angle
    if angle is None or angle > max_main_axis_angle_diff_deg:
        metrics["main_axis_trend_pass"] = False
        return TrendResult(False, "main_axis_trend_mismatch", metrics)

    swsd_length = float(swsd_geometry.length) if swsd_geometry is not None else 0.0
    length_ratio = candidate.path.length / swsd_length if swsd_length > 0 else None
    metrics["length_ratio"] = length_ratio
    if length_ratio is None or length_ratio < min_coarse_length_ratio or length_ratio > max_coarse_length_ratio:
        metrics["coarse_length_trend_pass"] = False
        return TrendResult(False, "coarse_length_trend_mismatch", metrics)

    return TrendResult(True, "passed", metrics)


def _check_junc_rules(
    candidate: RcsdCandidate,
    rcsd_pair_nodes: set[str],
    rcsd_junc_nodes: list[str],
    all_relation_base_ids: set[str],
) -> str | None:
    path_nodes = candidate.path.node_path
    path_node_set = set(path_nodes)
    allowed = rcsd_pair_nodes | set(rcsd_junc_nodes)
    for junc in rcsd_junc_nodes:
        if junc not in path_node_set:
            return "mapped_junc_not_covered"
        index = path_nodes.index(junc)
        if index == 0 or index == len(path_nodes) - 1:
            return "junc_internal_passage_broken"
        incident = 0
        for edge in candidate.all_edges:
            if edge.source == junc or edge.target == junc:
                incident += 1
        incident_limit = 4 if candidate.directionality == "dual" else 2
        if incident > incident_limit:
            return "junc_side_branch_leakage"
    for node_id in path_nodes:
        if node_id in all_relation_base_ids and node_id not in allowed:
            return "unexpected_semantic_junction_crossed"
    return None


def _check_junc_order(
    rcsd_node_path: list[str],
    swsd_directionality: str,
    swsd_junc_nodes: list[str],
    rcsd_junc_nodes: list[str],
) -> str | None:
    if not swsd_junc_nodes:
        return None
    order = [node for node in rcsd_node_path if node in set(rcsd_junc_nodes)]
    if len(order) != len(rcsd_junc_nodes):
        return "mapped_junc_not_covered"
    expected = list(rcsd_junc_nodes)
    if swsd_directionality == "dual":
        if order == expected or order == list(reversed(expected)):
            return None
    elif order == expected:
        return None
    return "semantic_junc_order_mismatch"


def _main_axis_angle(
    *,
    swsd_directionality: str,
    swsd_pair_nodes: list[str],
    rcsd_pair_nodes: list[str],
    swsd_geometry: BaseGeometry | None,
    candidate_geometry: BaseGeometry,
    swsd_node_geometries: dict[str, BaseGeometry],
    rcsd_node_geometries: dict[str, BaseGeometry],
) -> float | None:
    swsd_vector = _node_vector(swsd_pair_nodes, swsd_node_geometries) or _geometry_vector(swsd_geometry)
    rcsd_vector = _node_vector(rcsd_pair_nodes, rcsd_node_geometries) or _geometry_vector(candidate_geometry)
    if swsd_vector is None or rcsd_vector is None:
        return None
    diff = abs(_angle_deg(swsd_vector) - _angle_deg(rcsd_vector)) % 360.0
    if diff > 180.0:
        diff = 360.0 - diff
    if swsd_directionality == "dual" and diff > 90.0:
        diff = 180.0 - diff
    return abs(diff)


def _node_vector(nodes: list[str], node_geometries: dict[str, BaseGeometry]) -> tuple[float, float] | None:
    if len(nodes) != 2:
        return None
    first = _point_xy(node_geometries.get(nodes[0]))
    second = _point_xy(node_geometries.get(nodes[1]))
    if first is None or second is None:
        return None
    return (second[0] - first[0], second[1] - first[1])


def _geometry_vector(geometry: BaseGeometry | None) -> tuple[float, float] | None:
    if geometry is None or geometry.is_empty:
        return None
    line = geometry if isinstance(geometry, LineString) else LineString(list(geometry.envelope.exterior.coords))
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    return (coords[-1][0] - coords[0][0], coords[-1][1] - coords[0][1])


def _point_xy(geometry: BaseGeometry | None) -> tuple[float, float] | None:
    if geometry is None or geometry.is_empty:
        return None
    point = geometry if isinstance(geometry, Point) else geometry.centroid
    return (float(point.x), float(point.y))


def _angle_deg(vector: tuple[float, float]) -> float:
    return math.degrees(math.atan2(vector[1], vector[0]))
