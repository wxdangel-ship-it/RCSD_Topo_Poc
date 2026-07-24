from __future__ import annotations

import hashlib
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import fiona
import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from .geometry import canonical_id
from .io import write_gpkg_layers, write_json


@dataclass(frozen=True)
class DirectionalQualityThresholds:
    analysis_crs: str = "EPSG:32650"
    physical_node_gap_tolerance_m: float = 0.05
    turn_sample_spacing_m: float = 5.0
    supported_turn_excess_tolerance_deg: float = 12.0
    movement_portal_tolerance_m: float = 0.05
    movement_join_angle_tolerance_deg: float = 10.0


def run_directional_quality_audit(
    run_root: str | Path,
    *,
    thresholds: DirectionalQualityThresholds | None = None,
) -> dict[str, Any]:
    """Audit only the published package in a process separate from generation."""

    started = time.perf_counter()
    root = Path(run_root).expanduser().resolve()
    limits = thresholds or DirectionalQualityThresholds()
    road_path = root / "p04_directional_roads.gpkg"
    movement_path = root / "p04_directional_movements.gpkg"
    graph_path = root / "p04_directional_road_graph.gpkg"
    lane_group_path = root / "p04_directional_lane_groups.gpkg"
    support_path = root / "p04_directional_support_intervals.gpkg"
    roads = gpd.read_file(road_path, layer="directional_roads")
    movements = gpd.read_file(movement_path, layer="directional_movements")
    parents = gpd.read_file(graph_path, layer="parent_swsd_roads")
    cross_direction = _read_optional_layer(
        lane_group_path,
        "cross_direction_quality_audit",
        crs=limits.analysis_crs,
    )
    support_intervals = _read_optional_layer(
        support_path,
        "support_intervals",
        crs=limits.analysis_crs,
    )
    geometry_segments = _read_optional_layer(
        support_path,
        "geometry_segments",
        crs=limits.analysis_crs,
    )

    roads["directional_road_id"] = roads["directional_road_id"].astype(str)
    parents["swsd_unit_id"] = parents["swsd_unit_id"].map(canonical_id)
    road_by_id = roads.set_index("directional_road_id", drop=False)
    parent_by_id = parents.set_index("swsd_unit_id", drop=False)

    road_audit = _road_smoothness_audit(
        roads,
        parent_by_id,
        sample_spacing_m=limits.turn_sample_spacing_m,
        excess_tolerance_deg=limits.supported_turn_excess_tolerance_deg,
    )
    node_audit = _physical_node_audit(
        roads,
        tolerance_m=limits.physical_node_gap_tolerance_m,
    )
    movement_audit = _movement_join_audit(
        movements,
        road_by_id,
        portal_tolerance_m=limits.movement_portal_tolerance_m,
        angle_tolerance_deg=limits.movement_join_angle_tolerance_deg,
    )
    direction_pair_audit = _direction_pair_audit(
        roads,
        cross_direction,
        geometry_segments,
    )

    supported = road_audit[road_audit["quality_gate_applicable"]]
    road_turn_violations = supported[~supported["turn_gate_pass"]]
    node_violations = node_audit[~node_audit["gap_gate_pass"]]
    movement_violations = movement_audit[~movement_audit["join_gate_pass"]]
    direction_pair_violations = direction_pair_audit[
        ~direction_pair_audit["direction_pair_gate_pass"]
    ]
    long_gap_review = _long_gap_review(support_intervals, roads)
    expected_crs = limits.analysis_crs.upper()
    gates = {
        "road_crs_explicit": _crs_matches(roads, expected_crs),
        "parent_crs_explicit": _crs_matches(parents, expected_crs),
        "movement_crs_explicit": _crs_matches(movements, expected_crs),
        "cross_direction_crs_explicit": _crs_matches(cross_direction, expected_crs),
        "support_interval_crs_explicit": _crs_matches(support_intervals, expected_crs),
        "geometry_segment_crs_explicit": _crs_matches(geometry_segments, expected_crs),
        "road_geometry_valid_simple": bool(
            roads.geometry.notna().all()
            and (~roads.geometry.is_empty).all()
            and roads.geometry.is_valid.all()
            and roads.geometry.is_simple.all()
        ),
        "movement_geometry_valid_simple": bool(
            movements.geometry.notna().all()
            and (~movements.geometry.is_empty).all()
            and movements.geometry.is_valid.all()
            and movements.geometry.is_simple.all()
        ),
        "parent_lineage_complete": bool(
            roads["parent_swsd_unit_id"].map(canonical_id).isin(parent_by_id.index).all()
        ),
        "all_physical_nodes_closed": node_violations.empty,
        "supported_road_smoothness": road_turn_violations.empty,
        "movement_portal_and_tangent": movement_violations.empty,
        "cross_direction_high_precision_separation": direction_pair_violations.empty,
    }
    gate_pass = all(gates.values())
    fail_reasons = [name for name, passed in gates.items() if not passed]
    run_ids = sorted(set(roads["run_id"].astype(str))) if "run_id" in roads else []
    payload = {
        "audit_version": "p04_directional_independent_quality_v2",
        "audit_scope": "published_gpkg_only; no generation summary consumed",
        "run_root": str(root),
        "published_run_ids": run_ids,
        "thresholds": asdict(limits),
        "source_files": {
            path.name: {"sha256": _sha256(path), "size_bytes": path.stat().st_size}
            for path in (road_path, movement_path, graph_path, lane_group_path, support_path)
        },
        "road": {
            "count": int(len(roads)),
            "supported_count": int(len(supported)),
            "turn_violation_count": int(len(road_turn_violations)),
            "max_supported_turn_excess_deg": _safe_max(
                supported["max_turn_excess_deg"]
            ),
            "max_supported_local_turn_deg": _safe_max(
                supported["max_local_turn_deg"]
            ),
        },
        "physical_node": {
            "audited_count": int(len(node_audit)),
            "violation_count": int(len(node_violations)),
            "max_gap_m": _safe_max(node_audit["max_endpoint_gap_m"]),
        },
        "movement": {
            "count": int(len(movements)),
            "violation_count": int(len(movement_violations)),
            "max_portal_gap_m": _safe_max(movement_audit["max_portal_gap_m"]),
            "max_join_angle_deg": _safe_max(movement_audit["max_join_angle_deg"]),
        },
        "direction_pair": {
            "audited_parent_count": int(len(direction_pair_audit)),
            "violation_count": int(len(direction_pair_violations)),
            "collapsed_evidence_candidate_count": int(
                direction_pair_audit.get(
                    "collapsed_evidence_candidate", gpd.GeoSeries(dtype=bool)
                ).sum()
            ),
            "max_required_min_separation_m": _safe_max(
                direction_pair_audit.get(
                    "required_min_separation_m", gpd.GeoSeries(dtype=float)
                )
            ),
        },
        "long_sd_gap_review": long_gap_review,
        "gates": gates,
        "gate_pass": gate_pass,
        "fail_reasons": fail_reasons,
        "performance": {"audit_seconds": time.perf_counter() - started},
        "outputs": {
            "audit_json": "p04_directional_independent_quality.json",
            "audit_gpkg": "p04_directional_independent_quality.gpkg",
        },
    }
    write_gpkg_layers(
        root / "p04_directional_independent_quality.gpkg",
        {
            "road_smoothness_audit": road_audit,
            "physical_node_audit": node_audit,
            "movement_join_audit": movement_audit,
            "direction_pair_audit": direction_pair_audit,
        },
    )
    write_json(root / "p04_directional_independent_quality.json", payload)
    return payload


def _direction_pair_audit(
    roads: gpd.GeoDataFrame,
    cross_direction: gpd.GeoDataFrame,
    geometry_segments: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    published_sides = {
        str(parent_id): set(frame["travel_side"].astype(str))
        for parent_id, frame in roads.groupby("parent_swsd_unit_id")
    }
    hp = geometry_segments[
        geometry_segments.get("interval_state", "") == "hp_supported"
    ] if not geometry_segments.empty else geometry_segments
    hp_sides = {
        str(parent_id): set(frame["travel_side"].astype(str))
        for parent_id, frame in hp.groupby("parent_swsd_unit_id")
    } if not hp.empty else {}
    cross_ids = (
        set(cross_direction["parent_swsd_unit_id"].astype(str))
        if not cross_direction.empty
        else set()
    )
    published_hp_pairs = {
        parent_id
        for parent_id, sides in hp_sides.items()
        if {"forward", "reverse"}.issubset(sides)
    }
    rows: list[dict[str, Any]] = []
    for parent_id in sorted(cross_ids | published_hp_pairs):
        evidence = (
            cross_direction[
                cross_direction["parent_swsd_unit_id"].astype(str) == parent_id
            ]
            if not cross_direction.empty
            else cross_direction
        )
        evidence_by_side = {
            str(row.travel_side): row.geometry
            for row in evidence.itertuples(index=False)
            if str(row.travel_side) in {"forward", "reverse"}
        }
        evidence_present = {"forward", "reverse"}.issubset(evidence_by_side)
        required = (
            float(evidence["required_min_separation_m"].dropna().max())
            if evidence_present and evidence["required_min_separation_m"].notna().any()
            else 0.5
        )
        if evidence_present:
            evidence_median, evidence_p95 = _symmetric_geometry_distance(
                evidence_by_side["forward"], evidence_by_side["reverse"], 1.0
            )
        else:
            evidence_median, evidence_p95 = float("nan"), float("nan")
        collapsed = evidence_present and evidence_median < required
        published_children = published_sides.get(parent_id, set())
        disposition_pass = (not collapsed) or not {
            "forward", "reverse"
        }.issubset(published_children)
        hp_frame = (
            hp[hp["parent_swsd_unit_id"].astype(str) == parent_id]
            if not hp.empty
            else hp
        )
        hp_by_side = {
            side: unary_union(hp_frame[hp_frame["travel_side"] == side].geometry)
            for side in ("forward", "reverse")
            if not hp_frame[hp_frame["travel_side"] == side].empty
        }
        hp_applicable = {"forward", "reverse"}.issubset(hp_by_side)
        if hp_applicable:
            hp_median, hp_p95 = _symmetric_geometry_distance(
                hp_by_side["forward"], hp_by_side["reverse"], 1.0
            )
            hp_gate_pass = hp_median >= required
        else:
            hp_median, hp_p95, hp_gate_pass = float("nan"), float("nan"), True
        audit_coverage_pass = evidence_present or not hp_applicable
        gate_pass = audit_coverage_pass and disposition_pass and hp_gate_pass
        geometry_parts = list(evidence_by_side.values()) or list(hp_by_side.values())
        rows.append(
            {
                "parent_swsd_unit_id": parent_id,
                "evidence_audit_present": evidence_present,
                "evidence_anchor_median_separation_m": evidence_median,
                "evidence_anchor_p95_separation_m": evidence_p95,
                "required_min_separation_m": required,
                "collapsed_evidence_candidate": collapsed,
                "published_directional_child_count": len(
                    published_children & {"forward", "reverse"}
                ),
                "collapsed_candidate_disposition_gate_pass": disposition_pass,
                "published_hp_pair_applicable": hp_applicable,
                "published_hp_median_separation_m": hp_median,
                "published_hp_p95_separation_m": hp_p95,
                "published_hp_separation_gate_pass": hp_gate_pass,
                "audit_coverage_gate_pass": audit_coverage_pass,
                "direction_pair_gate_pass": gate_pass,
                "reason_codes": "pass" if gate_pass else "cross_direction_high_precision_separation_failed",
                "geometry": unary_union(geometry_parts) if geometry_parts else LineString(),
            }
        )
    columns = [
        "parent_swsd_unit_id",
        "evidence_audit_present",
        "evidence_anchor_median_separation_m",
        "evidence_anchor_p95_separation_m",
        "required_min_separation_m",
        "collapsed_evidence_candidate",
        "published_directional_child_count",
        "collapsed_candidate_disposition_gate_pass",
        "published_hp_pair_applicable",
        "published_hp_median_separation_m",
        "published_hp_p95_separation_m",
        "published_hp_separation_gate_pass",
        "audit_coverage_gate_pass",
        "direction_pair_gate_pass",
        "reason_codes",
        "geometry",
    ]
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=roads.crs)


def _long_gap_review(
    support_intervals: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
) -> dict[str, Any]:
    empty_result = {
        "road_count": 0,
        "max_gap_m": 0.0,
        "declared_road_count": 0,
        "declaration_mismatch_count": 0,
        "threshold_m": 100.0,
        "policy": "report_only_high_precision_claim_scope_limited",
    }
    if support_intervals.empty:
        return empty_result
    partial_ids = set(
        roads.loc[
            roads["support_state"] == "partial_hp_supported",
            "directional_road_id",
        ].astype(str)
    )
    gaps = support_intervals[
        (support_intervals["interval_state"] == "sd_gap")
        & support_intervals["directional_road_id"].astype(str).isin(partial_ids)
    ].copy()
    if gaps.empty:
        return empty_result
    maximum_by_road = gaps.groupby("directional_road_id")["interval_length_m"].max()
    declared = set(
        roads.loc[
            roads.get("sd_gap_risk_state", "") == "long_sd_gap_review",
            "directional_road_id",
        ].astype(str)
    ) if "sd_gap_risk_state" in roads.columns else set()
    threshold_values = (
        roads["long_sd_gap_review_threshold_m"].dropna().astype(float)
        if "long_sd_gap_review_threshold_m" in roads.columns
        else []
    )
    threshold = float(min(threshold_values)) if len(threshold_values) else 100.0
    independently_long = set(
        maximum_by_road[maximum_by_road.ge(threshold)].index.astype(str)
    )
    return {
        "road_count": int(len(independently_long)),
        "max_gap_m": float(maximum_by_road.max()),
        "declared_road_count": int(len(declared)),
        "declaration_mismatch_count": int(len(independently_long.symmetric_difference(declared))),
        "threshold_m": threshold,
        "policy": "report_only_high_precision_claim_scope_limited",
    }


def _symmetric_geometry_distance(
    first: Any,
    second: Any,
    spacing_m: float,
) -> tuple[float, float]:
    distances = [
        float(second.distance(point)) for point in _sample_geometry(first, spacing_m)
    ] + [float(first.distance(point)) for point in _sample_geometry(second, spacing_m)]
    if not distances:
        return float("nan"), float("nan")
    return float(np.median(distances)), float(np.percentile(distances, 95))


def _sample_geometry(geometry: Any, spacing_m: float) -> list[Point]:
    lines = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    points: list[Point] = []
    for line in lines:
        if line is None or line.is_empty or not hasattr(line, "interpolate"):
            continue
        count = max(3, int(math.ceil(float(line.length) / max(spacing_m, 1e-6))) + 1)
        points.extend(
            line.interpolate(float(distance))
            for distance in np.linspace(0.0, float(line.length), count)
        )
    return points


def _read_optional_layer(
    path: Path,
    layer: str,
    *,
    crs: str,
) -> gpd.GeoDataFrame:
    if path.is_file() and layer in fiona.listlayers(path):
        return gpd.read_file(path, layer=layer)
    return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=crs)


def _road_smoothness_audit(
    roads: gpd.GeoDataFrame,
    parent_by_id: gpd.GeoDataFrame,
    *,
    sample_spacing_m: float,
    excess_tolerance_deg: float,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, Any]] = []
    for road in roads.itertuples(index=False):
        parent_id = canonical_id(road.parent_swsd_unit_id)
        parent = parent_by_id.loc[parent_id].geometry
        if str(road.travel_side) == "reverse":
            parent = LineString(list(parent.coords)[::-1])
        maximum, parent_at_maximum, excess, point = _aligned_turn_metrics(
            road.geometry,
            parent,
            sample_spacing_m,
        )
        applicable = str(road.support_state) in {
            "hp_supported",
            "partial_hp_supported",
        }
        rows.append(
            {
                "run_id": str(road.run_id),
                "directional_road_id": str(road.directional_road_id),
                "parent_swsd_unit_id": parent_id,
                "support_state": str(road.support_state),
                "quality_gate_applicable": applicable,
                "max_local_turn_deg": maximum,
                "parent_turn_at_same_station_deg": parent_at_maximum,
                "max_turn_excess_deg": excess,
                "turn_gate_pass": (not applicable) or excess <= excess_tolerance_deg,
                "geometry": point,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=roads.crs)


def _physical_node_audit(
    roads: gpd.GeoDataFrame,
    *,
    tolerance_m: float,
) -> gpd.GeoDataFrame:
    endpoints: dict[str, list[tuple[str, str, Point]]] = {}
    for road in roads.itertuples(index=False):
        road_id = str(road.directional_road_id)
        endpoints.setdefault(canonical_id(road.snode_id), []).append(
            (road_id, "s", Point(road.geometry.coords[0]))
        )
        endpoints.setdefault(canonical_id(road.enode_id), []).append(
            (road_id, "e", Point(road.geometry.coords[-1]))
        )
    rows: list[dict[str, Any]] = []
    for node_id, values in sorted(endpoints.items()):
        if len(values) < 2:
            continue
        maximum = max(
            (
                first[2].distance(second[2])
                for index, first in enumerate(values)
                for second in values[index + 1 :]
            ),
            default=0.0,
        )
        point = Point(
            float(np.median([value[2].x for value in values])),
            float(np.median([value[2].y for value in values])),
        )
        rows.append(
            {
                "physical_node_id": node_id,
                "endpoint_count": len(values),
                "endpoint_keys": ";".join(
                    sorted(f"{road_id}:{endpoint}" for road_id, endpoint, _ in values)
                ),
                "max_endpoint_gap_m": float(maximum),
                "gap_gate_pass": maximum <= tolerance_m,
                "geometry": point,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=roads.crs)


def _movement_join_audit(
    movements: gpd.GeoDataFrame,
    road_by_id: gpd.GeoDataFrame,
    *,
    portal_tolerance_m: float,
    angle_tolerance_deg: float,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, Any]] = []
    for movement in movements.itertuples(index=False):
        source = road_by_id.loc[str(movement.source_directional_road_id)].geometry
        target = road_by_id.loc[str(movement.target_directional_road_id)].geometry
        source_portal_gap = Point(source.coords[-1]).distance(movement.geometry)
        target_portal_gap = Point(target.coords[0]).distance(movement.geometry)
        start_angle = _angle(
            _vector(source.coords[-2], source.coords[-1]),
            _vector(movement.geometry.coords[0], movement.geometry.coords[1]),
        )
        end_angle = _angle(
            _vector(movement.geometry.coords[-2], movement.geometry.coords[-1]),
            _vector(target.coords[0], target.coords[1]),
        )
        maximum_gap = max(source_portal_gap, target_portal_gap)
        maximum_angle = max(start_angle, end_angle)
        direct_gap = Point(source.coords[-1]).distance(Point(target.coords[0]))
        rows.append(
            {
                "run_id": str(movement.run_id),
                "directional_movement_id": str(movement.directional_movement_id),
                "source_directional_road_id": str(movement.source_directional_road_id),
                "target_directional_road_id": str(movement.target_directional_road_id),
                "junction_relation": str(movement.junction_relation),
                "geometry_source": str(movement.geometry_source),
                "source_portal_gap_m": float(source_portal_gap),
                "target_portal_gap_m": float(target_portal_gap),
                "max_portal_gap_m": float(maximum_gap),
                "source_join_angle_deg": float(start_angle),
                "target_join_angle_deg": float(end_angle),
                "max_join_angle_deg": float(maximum_angle),
                "path_length_m": float(movement.geometry.length),
                "direct_portal_gap_m": float(direct_gap),
                "join_gate_pass": maximum_gap <= portal_tolerance_m
                and maximum_angle <= angle_tolerance_deg,
                "geometry": movement.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=movements.crs)


def _aligned_turn_metrics(
    candidate: LineString,
    parent: LineString,
    spacing_m: float,
) -> tuple[float, float, float, Point]:
    count = max(3, int(math.ceil(float(parent.length) / max(spacing_m, 1e-6))) + 1)
    fractions = np.linspace(0.0, 1.0, count)
    candidate_points = [candidate.interpolate(float(value), normalized=True) for value in fractions]
    parent_points = [parent.interpolate(float(value), normalized=True) for value in fractions]
    best = (0.0, 0.0, 0.0, candidate_points[len(candidate_points) // 2])
    for index in range(1, count - 1):
        candidate_turn = _point_turn(
            candidate_points[index - 1],
            candidate_points[index],
            candidate_points[index + 1],
        )
        parent_turn = _point_turn(
            parent_points[index - 1],
            parent_points[index],
            parent_points[index + 1],
        )
        excess = max(0.0, candidate_turn - parent_turn)
        if excess > best[2]:
            best = (candidate_turn, parent_turn, excess, candidate_points[index])
    return best


def _point_turn(first: Point, middle: Point, last: Point) -> float:
    return _angle(
        (middle.x - first.x, middle.y - first.y),
        (last.x - middle.x, last.y - middle.y),
    )


def _vector(first: Any, second: Any) -> tuple[float, float]:
    return float(second[0] - first[0]), float(second[1] - first[1])


def _angle(first: tuple[float, float], second: tuple[float, float]) -> float:
    first_norm = math.hypot(*first)
    second_norm = math.hypot(*second)
    if min(first_norm, second_norm) <= 1e-12:
        return 180.0
    cosine = (first[0] * second[0] + first[1] * second[1]) / (
        first_norm * second_norm
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _safe_max(values: Any) -> float:
    return float(values.max()) if len(values) else 0.0


def _crs_matches(frame: gpd.GeoDataFrame, expected: str) -> bool:
    return bool(frame.crs and frame.crs.to_string().upper() == expected)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["DirectionalQualityThresholds", "run_directional_quality_audit"]
