from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as transform_geometry

from rcsd_topo_poc.modules.p01_arm_build.models import (
    DATASETS,
    ArmMovement,
    DatasetBuildResult,
    LoadedDataset,
    RawRoadNextRoad,
    RoadRecord,
    to_plain,
)


SOURCE_TO_DATASET = {"1": "RCSD", "2": "SWSD"}
DATASET_TO_SOURCE = {"RCSD": "1", "SWSD": "2"}
MOVEMENT_TURNTYPE = {"unknown": "0", "straight": "1", "left": "2", "right": "3", "uturn": "4"}
SOURCE_GEOMETRY_MATCH_DECIMALS = 7
GENERATABLE_RULE_STATUSES = {"full_allowed", "trunk_only_allowed", "left_receiving_only_allowed"}


@dataclass(frozen=True)
class RoadRole:
    dataset: str
    arm_id: str
    road_id: str
    road_role: str
    target_role: str


@dataclass(frozen=True)
class SourceRoadMap:
    f_road_id: str
    f_road_source: str
    source_dataset: str
    source_road_id: str | None
    match_status: str
    match_reason: str
    issue_flags: tuple[str, ...]


@dataclass(frozen=True)
class SourceMovementPolicy:
    source_dataset: str
    from_arm_id: str
    to_arm_id: str
    movement_type: str
    from_road_role: str
    to_road_role: str
    from_source_road_ids: tuple[str, ...]
    to_source_road_ids: tuple[str, ...]
    permission_status: str
    source_road_next_road_ids: tuple[str, ...]


@dataclass(frozen=True)
class ArmSourceProfile:
    dataset: str
    arm_id: str
    source_distribution: dict[str, int]
    trunk_source_distribution: dict[str, int]
    advance_left_source_distribution: dict[str, int]
    parallel_branch_source_distribution: dict[str, int]
    source_mixed: bool
    risk_flags: tuple[str, ...]


@dataclass(frozen=True)
class SourceArmPassRule:
    source_dataset: str
    from_arm_id: str
    to_arm_id: str
    movement_type: str
    from_road_role: str
    rule_status: str
    generation_scope: str
    source_evidence_ids: tuple[str, ...]
    issue_flags: tuple[str, ...]


@dataclass(frozen=True)
class FinalGenerationDecision:
    from_arm_id: str
    to_arm_id: str
    movement_type: str
    from_road_role: str
    reference_source: str
    rule_status: str
    generation_scope: str
    generated_road_ids: tuple[str, ...]
    generated_next_road_ids: tuple[str, ...]
    issue_flags: tuple[str, ...]


@dataclass(frozen=True)
class FrcsdGenerationAudit:
    f_road_id: str
    f_next_road_id: str
    from_arm_id: str
    to_arm_id: str
    movement_type: str
    from_road_role: str
    to_road_role: str
    from_road_source: str
    to_road_source: str
    primary_source: str
    reference_source: str
    generation_rule: str
    permission_status: str
    source_evidence_ids: tuple[str, ...]
    confidence: str
    issue_flags: tuple[str, ...]
    rule_status: str = ""
    generation_scope: str = ""
    generation_basis: str = ""
    source_match_status: str = ""


@dataclass(frozen=True)
class ParallelBranchAlignment:
    dataset: str
    junction_group_id: str
    source_dataset: str
    arm_id: str
    frcsd_parallel_branch_road_ids: tuple[str, ...]
    source_parallel_branch_road_ids: tuple[str, ...]
    alignment_status: str
    alignment_order_rule: str
    aligned_pairs: tuple[dict[str, str], ...]
    issue_flags: tuple[str, ...]


@dataclass(frozen=True)
class FrcsdRoadNextRoadFinalResult:
    features: tuple[dict[str, Any], ...]
    source_road_map: tuple[SourceRoadMap, ...]
    source_movement_policy_swsd: tuple[SourceMovementPolicy, ...]
    source_movement_policy_rcsd: tuple[SourceMovementPolicy, ...]
    arm_source_profiles: tuple[ArmSourceProfile, ...]
    source_arm_pass_rules_swsd: tuple[SourceArmPassRule, ...]
    source_arm_pass_rules_rcsd: tuple[SourceArmPassRule, ...]
    final_generation_decisions: tuple[FinalGenerationDecision, ...]
    parallel_branch_alignment: tuple[ParallelBranchAlignment, ...]
    audit: tuple[FrcsdGenerationAudit, ...]
    issue_report: dict[str, Any]
    metrics: dict[str, int]


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def _layer_crs(layer: Any) -> CRS | None:
    for candidate in (getattr(layer, "crs_wkt", None), getattr(layer, "crs", None)):
        if candidate:
            try:
                return CRS.from_user_input(candidate)
            except Exception:
                continue
    return None


def _geometry_in_target_crs(geometry: BaseGeometry, *, source_crs: CRS | None, target_crs: CRS | None) -> BaseGeometry:
    if source_crs is None or target_crs is None or source_crs == target_crs:
        return geometry
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    return transform_geometry(transformer.transform, geometry)


def _rounded_bounds(geometry: BaseGeometry) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = geometry.bounds
    return (
        round(float(minx), SOURCE_GEOMETRY_MATCH_DECIMALS),
        round(float(miny), SOURCE_GEOMETRY_MATCH_DECIMALS),
        round(float(maxx), SOURCE_GEOMETRY_MATCH_DECIMALS),
        round(float(maxy), SOURCE_GEOMETRY_MATCH_DECIMALS),
    )


def _rounded_linestring_key(geometry: BaseGeometry) -> tuple[Any, ...]:
    if geometry.geom_type == "LineString":
        coords = tuple(
            (round(float(coord[0]), SOURCE_GEOMETRY_MATCH_DECIMALS), round(float(coord[1]), SOURCE_GEOMETRY_MATCH_DECIMALS))
            for coord in geometry.coords
        )
        return ("LineString", min(coords, tuple(reversed(coords))))
    if geometry.geom_type == "MultiLineString":
        parts = tuple(sorted(_rounded_linestring_key(part)[1] for part in geometry.geoms))
        return ("MultiLineString", parts)
    return (geometry.geom_type, geometry.wkb_hex)


def _source_geometry_key(road: RoadRecord, *, source_crs: CRS | None, target_crs: CRS | None) -> tuple[Any, ...]:
    geometry = _geometry_in_target_crs(road.geometry, source_crs=source_crs, target_crs=target_crs)
    return _rounded_linestring_key(geometry)


def _road_midpoint(road: RoadRecord | None) -> Point:
    if road is None or road.geometry.is_empty:
        return Point(0.0, 0.0)
    try:
        return road.geometry.interpolate(0.5, normalized=True)
    except Exception:
        return road.geometry.representative_point()


def _junction_center(loaded: LoadedDataset, result: DatasetBuildResult | None) -> Point:
    if result is not None:
        points = [
            loaded.nodes[node_id].geometry.centroid
            for node_id in result.context.member_node_ids
            if node_id in loaded.nodes and loaded.nodes[node_id].geometry is not None and not loaded.nodes[node_id].geometry.is_empty
        ]
        if points:
            return Point(sum(point.x for point in points) / len(points), sum(point.y for point in points) / len(points))
    geometries = [road.geometry for road in loaded.roads.values() if road.geometry is not None and not road.geometry.is_empty]
    if geometries:
        centroid = geometries[0].centroid
        return Point(float(centroid.x), float(centroid.y))
    return Point(0.0, 0.0)


def _road_endpoints(road: RoadRecord | None) -> tuple[Point, Point] | None:
    if road is None or road.geometry is None or road.geometry.is_empty:
        return None
    geometry = road.geometry
    if geometry.geom_type == "LineString":
        coords = list(geometry.coords)
    elif geometry.geom_type == "MultiLineString":
        parts = [part for part in geometry.geoms if not part.is_empty and len(part.coords) >= 2]
        if not parts:
            return None
        coords = list(max(parts, key=lambda item: item.length).coords)
    else:
        return None
    if len(coords) < 2:
        return None
    return Point(float(coords[0][0]), float(coords[0][1])), Point(float(coords[-1][0]), float(coords[-1][1]))


def _road_junction_endpoint(road: RoadRecord | None, center: Point) -> Point:
    endpoints = _road_endpoints(road)
    if endpoints is None:
        return _road_midpoint(road)
    start, end = endpoints
    return start if start.distance(center) <= end.distance(center) else end


def _road_local_point(road: RoadRecord | None, center: Point, *, offset_ratio: float = 0.14) -> Point:
    endpoints = _road_endpoints(road)
    if endpoints is None:
        return _road_midpoint(road)
    start, end = endpoints
    near, far = (start, end) if start.distance(center) <= end.distance(center) else (end, start)
    return Point(
        float(near.x) + (float(far.x) - float(near.x)) * offset_ratio,
        float(near.y) + (float(far.y) - float(near.y)) * offset_ratio,
    )


def _generated_review_line(from_road: RoadRecord | None, to_road: RoadRecord | None, center: Point) -> tuple[LineString, str]:
    start = _road_junction_endpoint(from_road, center)
    end = _road_junction_endpoint(to_road, center)
    if start.distance(end) > 1e-9:
        return LineString([start, end]), "junction_endpoint"
    local_start = _road_local_point(from_road, center)
    local_end = _road_local_point(to_road, center)
    if local_start.distance(local_end) > 1e-9:
        return LineString([local_start, local_end]), "junction_local_marker"
    fallback_end = Point(float(start.x) + 1e-6, float(start.y) + 1e-6)
    return LineString([start, fallback_end]), "junction_zero_length_marker"


def _arm_payload(arm: Any) -> dict[str, Any]:
    return dict(getattr(arm, "initial_arm", {}) or {})


def _corrected_trunk_by_arm(result: DatasetBuildResult) -> dict[str, tuple[str, ...]]:
    corrected = {item.arm_id: tuple(item.corrected_trunk_road_ids) for item in result.trunk_corrections}
    return {arm.final_arm_id: corrected.get(arm.final_arm_id, tuple(arm.trunk_road_ids)) for arm in result.final_arms}


def _road_roles(result: DatasetBuildResult) -> dict[str, RoadRole]:
    corrected_trunk = _corrected_trunk_by_arm(result)
    receiving_by_key = {(role.target_arm_id, role.road_id): role for role in result.arm_receiving_road_roles}
    roles: dict[str, RoadRole] = {}
    for arm in result.final_arms:
        payload = _arm_payload(arm)
        members = tuple(str(item) for item in payload.get("member_road_ids", []) or [])
        advance_left = set(arm.advance_left_turn_road_ids)
        trunk = set(corrected_trunk.get(arm.final_arm_id, arm.trunk_road_ids))
        for road_id in members:
            if road_id in advance_left:
                road_role = "advance_left"
            elif road_id in trunk:
                road_role = "trunk"
            else:
                road_role = "parallel_branch"
            receiving = receiving_by_key.get((arm.final_arm_id, road_id))
            if receiving and (
                receiving.advance_left_evidence_count > 0 or "left_turn_receiving_road" in receiving.receiving_roles
            ):
                target_role = "left_receiving"
            else:
                target_role = road_role
            roles[road_id] = RoadRole(
                dataset=result.dataset,
                arm_id=arm.final_arm_id,
                road_id=road_id,
                road_role=road_role,
                target_role=target_role,
            )
    return roles


def _parallel_count_by_entering_arm(result: DatasetBuildResult, roles: dict[str, RoadRole]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for arm in result.final_arms:
        for role in _arm_entering_roles(result, roles, arm.final_arm_id):
            if role.road_role == "parallel_branch":
                counts[role.arm_id] += 1
    return counts


def _road_order_key(road_id: str, roads: dict[str, RoadRecord]) -> tuple[float, float, str]:
    point = _road_midpoint(roads.get(road_id))
    return (round(float(point.x), 6), round(float(point.y), 6), road_id)


def _movement_by_pair(result: DatasetBuildResult) -> dict[tuple[str, str], ArmMovement]:
    return {(item.from_arm_id, item.to_arm_id): item for item in result.arm_movements}


def _movement_by_evidence(result: DatasetBuildResult) -> dict[str, ArmMovement]:
    mapping: dict[str, ArmMovement] = {}
    for movement in result.arm_movements:
        for evidence_id in movement.road_movement_evidence_ids:
            mapping[evidence_id] = movement
    return mapping


def _source_road_map(
    *,
    loaded_by_dataset: dict[str, LoadedDataset],
    f_roles: dict[str, RoadRole],
    progress: Callable[[str], None] | None = None,
) -> tuple[SourceRoadMap, ...]:
    def _phase(message: str) -> None:
        if progress is not None:
            progress(message)

    frcsd_loaded = loaded_by_dataset["FRCSD"]
    target_crs = _layer_crs(frcsd_loaded.road_layer)
    needed_keys: dict[str, set[tuple[Any, ...]]] = {"RCSD": set(), "SWSD": set()}
    needed_bounds: dict[str, set[tuple[float, float, float, float]]] = {"RCSD": set(), "SWSD": set()}
    f_lookup: dict[str, tuple[RoadRecord | None, str, str, tuple[Any, ...] | None]] = {}
    for f_road_id in sorted(f_roles):
        road = frcsd_loaded.roads.get(f_road_id)
        raw_source = _norm((road.properties if road else {}).get("source"))
        source_dataset = SOURCE_TO_DATASET.get(raw_source, "")
        key = _source_geometry_key(road, source_crs=target_crs, target_crs=target_crs) if road and source_dataset else None
        f_lookup[f_road_id] = (road, raw_source, source_dataset, key)
        if road and source_dataset and key is not None:
            needed_keys[source_dataset].add(key)
            needed_bounds[source_dataset].add(_rounded_bounds(road.geometry))

    source_index: dict[str, dict[tuple[Any, ...], list[str]]] = {}
    for dataset in ("RCSD", "SWSD"):
        if not needed_keys[dataset]:
            source_index[dataset] = {}
            _phase(f"source map skip {dataset}: no FRCSD role requires this source")
            continue
        source_crs = _layer_crs(loaded_by_dataset[dataset].road_layer)
        same_crs = source_crs is None or target_crs is None or source_crs == target_crs
        by_geometry: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        scanned_count = 0
        candidate_count = 0
        for road_id, road in loaded_by_dataset[dataset].roads.items():
            scanned_count += 1
            geometry = road.geometry if same_crs else _geometry_in_target_crs(road.geometry, source_crs=source_crs, target_crs=target_crs)
            if _rounded_bounds(geometry) not in needed_bounds[dataset]:
                continue
            candidate_count += 1
            key = _rounded_linestring_key(geometry)
            if key in needed_keys[dataset]:
                by_geometry[key].append(road_id)
        _phase(f"source map indexed {dataset}: scanned={scanned_count} bounds_candidates={candidate_count} matched_keys={len(by_geometry)}")
        source_index[dataset] = by_geometry
    rows: list[SourceRoadMap] = []
    for f_road_id in sorted(f_roles):
        road, raw_source, source_dataset, key = f_lookup[f_road_id]
        issue_flags: list[str] = []
        source_road_id: str | None = None
        if raw_source not in SOURCE_TO_DATASET:
            status = "source_invalid"
            reason = "source_missing_or_not_in_allowed_values"
            issue_flags.append("frcsd_source_invalid")
        else:
            matches = source_index[source_dataset].get(key, []) if key is not None else []
            if len(matches) == 1:
                status = "matched"
                reason = "source_limited_crs_normalized_rounded_exact_geometry_match"
                source_road_id = matches[0]
            elif len(matches) > 1:
                status = "ambiguous_source_geometry_match"
                reason = "multiple_source_roads_have_same_crs_normalized_rounded_geometry"
                issue_flags.append("ambiguous_source_geometry_match")
            else:
                status = "source_geometry_match_missing"
                reason = "no_source_road_has_same_crs_normalized_rounded_geometry"
                issue_flags.append("source_geometry_match_missing")
        rows.append(
            SourceRoadMap(
                f_road_id=f_road_id,
                f_road_source=raw_source,
                source_dataset=source_dataset,
                source_road_id=source_road_id,
                match_status=status,
                match_reason=reason,
                issue_flags=tuple(issue_flags),
            )
        )
    return tuple(rows)


def _source_policy(
    *,
    source_dataset: str,
    result: DatasetBuildResult,
    roles: dict[str, RoadRole],
) -> tuple[SourceMovementPolicy, ...]:
    movement_by_evidence = _movement_by_evidence(result)
    entering_roles_by_arm = {
        arm.final_arm_id: _arm_entering_roles(result, roles, arm.final_arm_id) for arm in result.final_arms
    }
    exit_roles_by_arm = {arm.final_arm_id: _target_exit_roles(result, roles, arm.final_arm_id) for arm in result.final_arms}
    entering_ids_by_arm = {
        arm_id: {role.road_id for role in arm_roles} for arm_id, arm_roles in entering_roles_by_arm.items()
    }
    exit_ids_by_arm = {arm_id: {role.road_id for role in arm_roles} for arm_id, arm_roles in exit_roles_by_arm.items()}
    candidate_grouped: dict[tuple[str, str, str, str, str], dict[str, set[str]]] = {}
    for movement in result.arm_movements:
        for from_role in entering_roles_by_arm.get(movement.from_arm_id, []):
            for to_role in exit_roles_by_arm.get(movement.to_arm_id, []):
                if from_role.road_id == to_role.road_id:
                    continue
                key = (
                    movement.from_arm_id,
                    movement.to_arm_id,
                    movement.movement_type,
                    from_role.road_role,
                    to_role.target_role,
                )
                bucket = candidate_grouped.setdefault(key, {"from": set(), "to": set(), "evidence": set()})
                bucket["from"].add(from_role.road_id)
                bucket["to"].add(to_role.road_id)
    allowed_grouped: dict[tuple[str, str, str, str, str], dict[str, set[str]]] = {}
    for evidence in result.road_movement_evidence:
        if evidence.mapping_status != "mapped" or not evidence.from_arm_id or not evidence.to_arm_id:
            continue
        movement = movement_by_evidence.get(evidence.evidence_id)
        if movement is None:
            continue
        from_role = roles.get(evidence.road_id)
        to_role = roles.get(evidence.next_road_id)
        if from_role is None or to_role is None:
            continue
        if evidence.road_id not in entering_ids_by_arm.get(evidence.from_arm_id, set()):
            continue
        if evidence.next_road_id not in exit_ids_by_arm.get(evidence.to_arm_id, set()):
            continue
        key = (
            evidence.from_arm_id,
            evidence.to_arm_id,
            movement.movement_type,
            from_role.road_role,
            to_role.target_role,
        )
        bucket = allowed_grouped.setdefault(key, {"from": set(), "to": set(), "evidence": set()})
        bucket["from"].add(evidence.road_id)
        bucket["to"].add(evidence.next_road_id)
        bucket["evidence"].add(evidence.raw_id or evidence.evidence_id)
    rows: list[SourceMovementPolicy] = []
    for key, bucket in sorted(candidate_grouped.items()):
        allowed_bucket = allowed_grouped.get(key)
        if allowed_bucket:
            from_ids = allowed_bucket["from"]
            to_ids = allowed_bucket["to"]
            evidence_ids = allowed_bucket["evidence"]
            permission_status = "allowed"
        else:
            from_ids = bucket["from"]
            to_ids = bucket["to"]
            evidence_ids = set()
            permission_status = "prohibited"
        rows.append(
            SourceMovementPolicy(
                source_dataset=source_dataset,
                from_arm_id=key[0],
                to_arm_id=key[1],
                movement_type=key[2],
                from_road_role=key[3],
                to_road_role=key[4],
                from_source_road_ids=tuple(sorted(from_ids)),
                to_source_road_ids=tuple(sorted(to_ids)),
                permission_status=permission_status,
                source_road_next_road_ids=tuple(sorted(evidence_ids)),
            )
        )
    return tuple(rows)


def _roles_by_arm(roles: dict[str, RoadRole]) -> dict[str, tuple[RoadRole, ...]]:
    grouped: dict[str, list[RoadRole]] = defaultdict(list)
    for role in roles.values():
        grouped[role.arm_id].append(role)
    return {arm_id: tuple(sorted(items, key=lambda item: item.road_id)) for arm_id, items in grouped.items()}


def _arm_by_id(result: DatasetBuildResult) -> dict[str, Any]:
    return {arm.final_arm_id: arm for arm in result.final_arms}


def _arm_member_ids(result: DatasetBuildResult, arm_id: str) -> tuple[str, ...]:
    arm = _arm_by_id(result).get(arm_id)
    if arm is None:
        return tuple()
    return tuple(str(item) for item in (_arm_payload(arm).get("member_road_ids", []) or []))


def _arm_entering_ids(result: DatasetBuildResult, arm_id: str) -> tuple[str, ...]:
    arm = _arm_by_id(result).get(arm_id)
    if arm is None:
        return tuple()
    payload = _arm_payload(arm)
    inbound = tuple(str(item) for item in (payload.get("inbound_member_road_ids", []) or []))
    bidirectional = tuple(str(item) for item in (payload.get("bidirectional_member_road_ids", []) or []))
    return tuple(sorted(set(inbound).union(bidirectional)))


def _arm_exit_ids(result: DatasetBuildResult, arm_id: str) -> tuple[str, ...]:
    arm = _arm_by_id(result).get(arm_id)
    if arm is None:
        return tuple()
    payload = _arm_payload(arm)
    outbound = tuple(str(item) for item in (payload.get("outbound_member_road_ids", []) or []))
    bidirectional = tuple(str(item) for item in (payload.get("bidirectional_member_road_ids", []) or []))
    return tuple(sorted(set(outbound).union(bidirectional)))


def _arm_entering_roles(result: DatasetBuildResult, roles: dict[str, RoadRole], arm_id: str) -> tuple[RoadRole, ...]:
    entering_ids = set(_arm_entering_ids(result, arm_id))
    return tuple(
        sorted(
            (role for role in roles.values() if role.arm_id == arm_id and role.road_id in entering_ids),
            key=lambda item: item.road_id,
        )
    )


def _target_exit_roles(result: DatasetBuildResult, roles: dict[str, RoadRole], arm_id: str) -> tuple[RoadRole, ...]:
    exit_ids = set(_arm_exit_ids(result, arm_id))
    return tuple(sorted((role for role in roles.values() if role.arm_id == arm_id and role.road_id in exit_ids), key=lambda item: item.road_id))


def _arm_structure_signature(result: DatasetBuildResult, roles: dict[str, RoadRole], arm_id: str) -> tuple[int, int, int, int, int]:
    arm_roles = [role for role in roles.values() if role.arm_id == arm_id]
    counts = Counter(role.road_role for role in arm_roles)
    return (
        len(_arm_member_ids(result, arm_id)),
        counts.get("trunk", 0),
        counts.get("advance_left", 0),
        counts.get("parallel_branch", 0),
        len(_arm_entering_ids(result, arm_id)),
    )


def _corridor_angle_by_arm(result: DatasetBuildResult) -> dict[str, float]:
    return {
        item.final_arm_id: float(item.corridor_angle_deg)
        for item in result.arm_corridor_evidence
        if item.corridor_angle_deg is not None
    }


def _angle_delta(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _corridor_ordinal_matched_arm(
    *,
    f_arm_id: str,
    source_dataset: str,
    result_by_dataset: dict[str, DatasetBuildResult],
) -> str | None:
    f_arms = tuple(sorted(arm.final_arm_id for arm in result_by_dataset["FRCSD"].final_arms))
    source_arms = tuple(sorted(arm.final_arm_id for arm in result_by_dataset[source_dataset].final_arms))
    if len(f_arms) != len(source_arms) or len(f_arms) < 2:
        return None
    f_angles = _corridor_angle_by_arm(result_by_dataset["FRCSD"])
    source_angles = _corridor_angle_by_arm(result_by_dataset[source_dataset])
    if any(arm_id not in f_angles for arm_id in f_arms) or any(arm_id not in source_angles for arm_id in source_arms):
        return None
    f_order = tuple(sorted(f_arms, key=lambda arm_id: (f_angles[arm_id] % 360.0, arm_id)))
    source_order = tuple(sorted(source_arms, key=lambda arm_id: (source_angles[arm_id] % 360.0, arm_id)))
    try:
        index = f_order.index(f_arm_id)
    except ValueError:
        return None
    candidate = source_order[index]
    if _angle_delta(f_angles[f_arm_id], source_angles[candidate]) > 55.0:
        return None
    return candidate


def _arm_source_profiles(
    *,
    loaded_frcsd: LoadedDataset,
    result_frcsd: DatasetBuildResult,
    f_roles: dict[str, RoadRole],
) -> tuple[ArmSourceProfile, ...]:
    profiles: list[ArmSourceProfile] = []
    roles_by_arm = _roles_by_arm(f_roles)
    for arm_id in sorted(roles_by_arm):
        distributions: dict[str, Counter[str]] = {
            "all": Counter(),
            "trunk": Counter(),
            "advance_left": Counter(),
            "parallel_branch": Counter(),
        }
        risk_flags: list[str] = []
        for role in roles_by_arm[arm_id]:
            road = loaded_frcsd.roads.get(role.road_id)
            source = _norm((road.properties if road else {}).get("source"))
            if source not in SOURCE_TO_DATASET:
                source = "invalid"
                risk_flags.append("frcsd_source_invalid")
            distributions["all"][source] += 1
            distributions.setdefault(role.road_role, Counter())[source] += 1
        source_keys = {key for key, count in distributions["all"].items() if count > 0 and key in SOURCE_TO_DATASET}
        if len(source_keys) > 1:
            risk_flags.append("mixed_source_arm")
        profiles.append(
            ArmSourceProfile(
                dataset="FRCSD",
                arm_id=arm_id,
                source_distribution=dict(sorted(distributions["all"].items())),
                trunk_source_distribution=dict(sorted(distributions["trunk"].items())),
                advance_left_source_distribution=dict(sorted(distributions["advance_left"].items())),
                parallel_branch_source_distribution=dict(sorted(distributions["parallel_branch"].items())),
                source_mixed=len(source_keys) > 1,
                risk_flags=tuple(sorted(set(risk_flags))),
            )
        )
    for arm in result_frcsd.final_arms:
        if arm.final_arm_id not in roles_by_arm:
            profiles.append(
                ArmSourceProfile(
                    dataset="FRCSD",
                    arm_id=arm.final_arm_id,
                    source_distribution={},
                    trunk_source_distribution={},
                    advance_left_source_distribution={},
                    parallel_branch_source_distribution={},
                    source_mixed=False,
                    risk_flags=("empty_arm_source_profile",),
                )
            )
    return tuple(sorted(profiles, key=lambda item: item.arm_id))


def _source_arm_pass_rules(
    *,
    source_dataset: str,
    result: DatasetBuildResult,
    roles: dict[str, RoadRole],
) -> tuple[SourceArmPassRule, ...]:
    entering_roles_by_arm = {
        arm.final_arm_id: _arm_entering_roles(result, roles, arm.final_arm_id) for arm in result.final_arms
    }
    entering_ids_by_arm = {
        arm_id: {role.road_id for role in arm_roles} for arm_id, arm_roles in entering_roles_by_arm.items()
    }
    exit_ids_by_arm = {arm.final_arm_id: set(_arm_exit_ids(result, arm.final_arm_id)) for arm in result.final_arms}
    evidence_by_key: dict[tuple[str, str, str], list[RoadMovementEvidence]] = defaultdict(list)
    for evidence in result.road_movement_evidence:
        from_role = roles.get(evidence.road_id)
        to_role = roles.get(evidence.next_road_id)
        to_arm_id = evidence.to_arm_id or (to_role.arm_id if to_role else None)
        if from_role is None or not to_arm_id:
            continue
        if evidence.mapping_status == "mapped" and evidence.from_arm_id:
            if evidence.road_id not in entering_ids_by_arm.get(evidence.from_arm_id, set()):
                continue
            if evidence.next_road_id not in exit_ids_by_arm.get(to_arm_id, set()):
                continue
            evidence_by_key[(evidence.from_arm_id, to_arm_id, from_role.road_role)].append(evidence)
        elif evidence.mapping_status in {"from_road_role_conflict", "to_road_role_conflict", "role_conflict"}:
            if evidence.road_id not in entering_ids_by_arm.get(from_role.arm_id, set()):
                continue
            if evidence.next_road_id not in exit_ids_by_arm.get(to_arm_id, set()):
                continue
            evidence_by_key[(from_role.arm_id, to_arm_id, from_role.road_role)].append(evidence)

    rows: list[SourceArmPassRule] = []
    for movement in result.arm_movements:
        target_exit_roles = _target_exit_roles(result, roles, movement.to_arm_id)
        target_exit_ids = {role.road_id for role in target_exit_roles}
        target_trunk_ids = {role.road_id for role in target_exit_roles if role.road_role == "trunk"}
        left_receiving_ids = {role.road_id for role in target_exit_roles if role.target_role == "left_receiving"}
        from_role_types = sorted({role.road_role for role in entering_roles_by_arm.get(movement.from_arm_id, tuple())})
        for from_road_role in from_role_types:
            evidence = tuple(evidence_by_key.get((movement.from_arm_id, movement.to_arm_id, from_road_role), tuple()))
            covered = {item.next_road_id for item in evidence if item.next_road_id in target_exit_ids}
            evidence_ids = tuple(sorted(item.raw_id or item.evidence_id for item in evidence))
            issue_flags: list[str] = []
            if not target_exit_ids:
                rule_status = "insufficient"
                generation_scope = "none"
                issue_flags.append("target_arm_exit_roads_missing")
            elif not covered:
                rule_status = "prohibited"
                generation_scope = "none"
            elif covered == target_exit_ids:
                rule_status = "full_allowed"
                generation_scope = "all_target_exit_roads"
            elif from_road_role == "trunk" and target_trunk_ids and covered == target_trunk_ids:
                rule_status = "trunk_only_allowed"
                generation_scope = "trunk_only"
            elif movement.movement_type == "uturn" and from_road_role == "trunk" and target_trunk_ids and covered == target_trunk_ids:
                rule_status = "trunk_only_allowed"
                generation_scope = "trunk_only"
            elif movement.movement_type == "left" and from_road_role == "advance_left" and target_trunk_ids and covered == target_trunk_ids:
                rule_status = "trunk_only_allowed"
                generation_scope = "trunk_only"
            elif movement.movement_type == "left" and from_road_role == "advance_left" and left_receiving_ids and covered == left_receiving_ids:
                rule_status = "left_receiving_only_allowed"
                generation_scope = "left_receiving_only"
            elif from_road_role in {"trunk", "parallel_branch"}:
                rule_status = "data_error_partial_target_coverage"
                generation_scope = "none"
                issue_flags.append("data_error_partial_target_coverage")
                issue_flags.append("manual_review_required")
            else:
                rule_status = "conflict"
                generation_scope = "none"
                issue_flags.append("manual_review_required")
            rows.append(
                SourceArmPassRule(
                    source_dataset=source_dataset,
                    from_arm_id=movement.from_arm_id,
                    to_arm_id=movement.to_arm_id,
                    movement_type=movement.movement_type,
                    from_road_role=from_road_role,
                    rule_status=rule_status,
                    generation_scope=generation_scope,
                    source_evidence_ids=evidence_ids,
                    issue_flags=tuple(sorted(set(issue_flags))),
                )
            )
    return tuple(rows)


def _policy_index(policy: tuple[SourceMovementPolicy, ...]) -> dict[tuple[str, str, str], tuple[SourceMovementPolicy, ...]]:
    grouped: dict[tuple[str, str, str], list[SourceMovementPolicy]] = defaultdict(list)
    for item in policy:
        if item.permission_status == "allowed":
            grouped[(item.movement_type, item.from_road_role, item.to_road_role)].append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def _rule_index(rules: tuple[SourceArmPassRule, ...]) -> dict[tuple[str, str, str, str], SourceArmPassRule]:
    indexed: dict[tuple[str, str, str, str], SourceArmPassRule] = {}
    for rule in rules:
        indexed[(rule.from_arm_id, rule.to_arm_id, rule.movement_type, rule.from_road_role)] = rule
    return indexed


def _movement_type_index(result: DatasetBuildResult) -> dict[tuple[str, str], tuple[str, ...]]:
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for movement in result.arm_movements:
        if movement.movement_type != "unknown":
            grouped[(movement.from_arm_id, movement.to_arm_id)].add(movement.movement_type)
    return {key: tuple(sorted(value)) for key, value in grouped.items()}


def _structure_matched_arm(
    *,
    f_arm_id: str,
    source_dataset: str,
    result_by_dataset: dict[str, DatasetBuildResult],
    roles: dict[str, dict[str, RoadRole]],
) -> str | None:
    f_signature = _arm_structure_signature(result_by_dataset["FRCSD"], roles["FRCSD"], f_arm_id)
    matches = [
        arm.final_arm_id
        for arm in result_by_dataset[source_dataset].final_arms
        if _arm_structure_signature(result_by_dataset[source_dataset], roles[source_dataset], arm.final_arm_id) == f_signature
    ]
    return matches[0] if len(matches) == 1 else None


def _geometry_matched_arm(
    *,
    f_arm_id: str,
    source_dataset: str,
    f_roles: dict[str, RoadRole],
    source_roles: dict[str, RoadRole],
    source_map_by_f: dict[str, SourceRoadMap],
) -> str | None:
    counts: Counter[str] = Counter()
    for f_role in f_roles.values():
        if f_role.arm_id != f_arm_id:
            continue
        source_item = source_map_by_f.get(f_role.road_id)
        if not source_item or source_item.match_status != "matched" or source_item.source_dataset != source_dataset:
            continue
        source_role = source_roles.get(source_item.source_road_id or "")
        if source_role:
            counts[source_role.arm_id] += 1
    if not counts:
        return None
    top_count = max(counts.values())
    top = sorted(arm_id for arm_id, count in counts.items() if count == top_count)
    return top[0] if len(top) == 1 else None


def _matched_source_arm(
    *,
    f_arm_id: str,
    source_dataset: str,
    result_by_dataset: dict[str, DatasetBuildResult],
    roles: dict[str, dict[str, RoadRole]],
    source_map_by_f: dict[str, SourceRoadMap],
) -> tuple[str | None, str]:
    geometry_match = _geometry_matched_arm(
        f_arm_id=f_arm_id,
        source_dataset=source_dataset,
        f_roles=roles["FRCSD"],
        source_roles=roles[source_dataset],
        source_map_by_f=source_map_by_f,
    )
    if geometry_match:
        return geometry_match, "exact_road_match_audit"
    structure_match = _structure_matched_arm(
        f_arm_id=f_arm_id,
        source_dataset=source_dataset,
        result_by_dataset=result_by_dataset,
        roles=roles,
    )
    if structure_match:
        return structure_match, "structure_matched"
    corridor_match = _corridor_ordinal_matched_arm(
        f_arm_id=f_arm_id,
        source_dataset=source_dataset,
        result_by_dataset=result_by_dataset,
    )
    if corridor_match:
        return corridor_match, "corridor_ordinal_matched"
    return None, "source_arm_unmatched"


def _choose_reference_source(profile: ArmSourceProfile, source_arm_matches: dict[str, tuple[str | None, str]]) -> tuple[str, str, tuple[str, ...]]:
    valid_sources = {source for source, count in profile.source_distribution.items() if count > 0 and source in SOURCE_TO_DATASET}
    if valid_sources == {"1"}:
        return "RCSD", "single_source_rcsd", tuple()
    if valid_sources == {"2"}:
        return "SWSD", "single_source_swsd", tuple()
    issues: list[str] = []
    swsd_arm, swsd_reason = source_arm_matches["SWSD"]
    rcsd_arm, rcsd_reason = source_arm_matches["RCSD"]
    if swsd_arm and swsd_reason == "structure_matched":
        return "SWSD", "mixed_source_structure_matched_swsd", ("mixed_source_arm",)
    if rcsd_arm and rcsd_reason == "structure_matched":
        return "RCSD", "mixed_source_structure_matched_rcsd", ("mixed_source_arm",)
    if swsd_arm:
        return "SWSD", "mixed_source_exact_audit_matched_swsd", ("mixed_source_arm",)
    if rcsd_arm:
        return "RCSD", "mixed_source_exact_audit_matched_rcsd", ("mixed_source_arm",)
    issues.extend(("mixed_source_arm", "low_confidence_swsd_basic_rule"))
    return "SWSD", "mixed_source_swsd_basic_rule_fallback", tuple(sorted(set(issues)))


def _generation_target_roles(
    *,
    result_frcsd: DatasetBuildResult,
    f_roles: dict[str, RoadRole],
    to_arm_id: str,
    generation_scope: str,
) -> tuple[RoadRole, ...]:
    exit_roles = _target_exit_roles(result_frcsd, f_roles, to_arm_id)
    if generation_scope == "all_target_exit_roads":
        return exit_roles
    if generation_scope == "trunk_only":
        return tuple(role for role in exit_roles if role.road_role == "trunk")
    if generation_scope == "left_receiving_only":
        left_receiving = tuple(role for role in exit_roles if role.target_role == "left_receiving")
        if left_receiving:
            return left_receiving
        return tuple(role for role in exit_roles if role.road_role == "trunk")
    return tuple()


def _parallel_branch_alignment(
    *,
    junction_group_id: str,
    loaded_by_dataset: dict[str, LoadedDataset],
    result_by_dataset: dict[str, DatasetBuildResult],
    roles: dict[str, dict[str, RoadRole]],
    source_map: tuple[SourceRoadMap, ...],
) -> tuple[ParallelBranchAlignment, ...]:
    source_map_by_f = {item.f_road_id: item for item in source_map}
    f_arm_ids = sorted(arm.final_arm_id for arm in result_by_dataset["FRCSD"].final_arms)
    rows: list[ParallelBranchAlignment] = []
    for arm_id in f_arm_ids:
        f_arm_roles = list(_arm_entering_roles(result_by_dataset["FRCSD"], roles["FRCSD"], arm_id))
        for source_dataset in ("SWSD", "RCSD"):
            source_arm_ids: set[str] = set()
            f_parallel_roles: list[RoadRole] = []
            mapped_source_by_f: dict[str, str] = {}
            for f_role in f_arm_roles:
                source_item = source_map_by_f.get(f_role.road_id)
                if not source_item or source_item.match_status != "matched" or source_item.source_dataset != source_dataset:
                    continue
                source_role = roles[source_dataset].get(source_item.source_road_id or "")
                if source_role is None:
                    continue
                source_arm_ids.add(source_role.arm_id)
                if f_role.road_role == "parallel_branch":
                    f_parallel_roles.append(f_role)
                    mapped_source_by_f[f_role.road_id] = source_item.source_road_id or ""
            source_entering_ids_by_arm = {
                source_arm_id: set(_arm_entering_ids(result_by_dataset[source_dataset], source_arm_id))
                for source_arm_id in source_arm_ids
            }
            source_parallel_roles = [
                role
                for role in roles[source_dataset].values()
                if role.arm_id in source_arm_ids and role.road_role == "parallel_branch"
                and role.road_id in source_entering_ids_by_arm.get(role.arm_id, set())
            ]
            if not source_arm_ids and not f_parallel_roles:
                continue
            f_ids = tuple(sorted((role.road_id for role in f_parallel_roles), key=lambda item: _road_order_key(item, loaded_by_dataset["FRCSD"].roads)))
            source_ids = tuple(
                sorted(
                    (role.road_id for role in source_parallel_roles),
                    key=lambda item: _road_order_key(item, loaded_by_dataset[source_dataset].roads),
                )
            )
            issue_flags: tuple[str, ...] = tuple()
            aligned_pairs: tuple[dict[str, str], ...] = tuple()
            order_rule = "source_exact_geometry_match_then_midpoint_xy_road_id"
            if not f_ids and not source_ids:
                status = "not_needed"
                order_rule = "not_needed_no_parallel_branch"
            elif source_ids and not f_ids:
                status = "source_missing_in_frcsd"
                issue_flags = ("source_parallel_branch_missing_in_frcsd",)
            elif len(f_ids) != len(source_ids):
                status = "count_mismatch_manual_review_required"
                issue_flags = ("parallel_branch_count_mismatch_manual_review_required", "data_error")
            else:
                pair_rows: list[dict[str, str]] = []
                mapped_source_ids = []
                for order_index, f_road_id in enumerate(f_ids, start=1):
                    source_road_id = mapped_source_by_f.get(f_road_id, "")
                    mapped_source_ids.append(source_road_id)
                    pair_rows.append(
                        {
                            "order_index": str(order_index),
                            "frcsd_road_id": f_road_id,
                            "source_road_id": source_road_id,
                        }
                    )
                if set(mapped_source_ids) == set(source_ids) and all(mapped_source_ids):
                    status = "count_matched_ordered"
                    aligned_pairs = tuple(pair_rows)
                else:
                    status = "insufficient_geometry_for_ordering"
                    issue_flags = ("insufficient_geometry_for_ordering",)
            rows.append(
                ParallelBranchAlignment(
                    dataset="FRCSD",
                    junction_group_id=junction_group_id,
                    source_dataset=source_dataset,
                    arm_id=arm_id,
                    frcsd_parallel_branch_road_ids=f_ids,
                    source_parallel_branch_road_ids=source_ids,
                    alignment_status=status,
                    alignment_order_rule=order_rule,
                    aligned_pairs=aligned_pairs,
                    issue_flags=issue_flags,
                )
            )
    return tuple(rows)


def _raw_by_needed_id(records: tuple[RawRoadNextRoad, ...], needed_ids: set[str]) -> dict[str, RawRoadNextRoad]:
    if not needed_ids:
        return {}
    return {record.raw_id: record for record in records if record.raw_id in needed_ids}


def _feature_properties(
    *,
    index: int,
    f_road_id: str,
    f_next_road_id: str,
    movement_type: str,
    reference_source: str,
    evidence_ids: tuple[str, ...],
    raw_by_source: dict[str, dict[str, RawRoadNextRoad]],
) -> dict[str, Any]:
    source_code = DATASET_TO_SOURCE.get(reference_source, "")
    raw: RawRoadNextRoad | None = None
    for evidence_id in evidence_ids:
        raw = raw_by_source.get(reference_source, {}).get(evidence_id)
        if raw:
            break
    raw_props = raw.raw_properties if raw else {}
    return {
        "id": f"frcsd_rnr_{index:06d}",
        "road_id": f_road_id,
        "next_road_id": f_next_road_id,
        "type": _norm(raw_props.get("type")) or _norm(raw.raw_type if raw else ""),
        "source": source_code,
        "turntype": MOVEMENT_TURNTYPE.get(movement_type, "0"),
        "city_code": _norm(raw_props.get("city_code")),
    }


def _audit(
    *,
    f_road_id: str,
    f_next_road_id: str,
    movement: ArmMovement,
    from_role: RoadRole,
    to_role: RoadRole,
    from_source: str,
    to_source: str,
    primary_source: str,
    reference_source: str,
    generation_rule: str,
    permission_status: str,
    evidence_ids: tuple[str, ...],
    confidence: str,
    issue_flags: tuple[str, ...] = tuple(),
    rule_status: str = "",
    generation_scope: str = "",
    generation_basis: str = "",
    source_match_status: str = "",
) -> FrcsdGenerationAudit:
    return FrcsdGenerationAudit(
        f_road_id=f_road_id,
        f_next_road_id=f_next_road_id,
        from_arm_id=movement.from_arm_id,
        to_arm_id=movement.to_arm_id,
        movement_type=movement.movement_type,
        from_road_role=from_role.road_role,
        to_road_role=to_role.target_role,
        from_road_source=from_source,
        to_road_source=to_source,
        primary_source=primary_source,
        reference_source=reference_source,
        generation_rule=generation_rule,
        permission_status=permission_status,
        source_evidence_ids=evidence_ids,
        confidence=confidence,
        issue_flags=issue_flags,
        rule_status=rule_status,
        generation_scope=generation_scope,
        generation_basis=generation_basis,
        source_match_status=source_match_status,
    )


def _issues_from_audit(
    source_map: tuple[SourceRoadMap, ...],
    parallel_branch_alignment: tuple[ParallelBranchAlignment, ...],
    audit_rows: list[FrcsdGenerationAudit],
    duplicate_count: int,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for row in source_map:
        for flag in row.issue_flags:
            issues.append({"issue_type": flag, "f_road_id": row.f_road_id, "match_status": row.match_status})
    for row in parallel_branch_alignment:
        for flag in row.issue_flags:
            issues.append(
                {
                    "issue_type": flag,
                    "arm_id": row.arm_id,
                    "source_dataset": row.source_dataset,
                    "alignment_status": row.alignment_status,
                }
            )
    for row in audit_rows:
        for flag in row.issue_flags:
            issues.append(
                {
                    "issue_type": flag,
                    "f_road_id": row.f_road_id,
                    "f_next_road_id": row.f_next_road_id,
                    "generation_rule": row.generation_rule,
                }
            )
    for _ in range(duplicate_count):
        issues.append({"issue_type": "duplicate_generated_road_next_road_suppressed"})
    return {"issues": issues, "issue_counts": dict(Counter(str(item["issue_type"]) for item in issues))}


def build_frcsd_road_next_road(
    *,
    loaded_by_dataset: dict[str, LoadedDataset],
    result_by_dataset: dict[str, DatasetBuildResult],
    road_next_road_by_dataset: dict[str, tuple[RawRoadNextRoad, ...]],
    junction_group_id: str = "",
    progress: Callable[[str], None] | None = None,
) -> FrcsdRoadNextRoadFinalResult:
    def _phase(message: str) -> None:
        if progress is not None:
            progress(message)

    _phase("roles start")
    roles = {dataset: _road_roles(result_by_dataset[dataset]) for dataset in DATASETS}
    _phase(
        "roles done "
        + " ".join(f"{dataset}={len(roles[dataset])}" for dataset in DATASETS)
    )
    source_map = _source_road_map(
        loaded_by_dataset=loaded_by_dataset,
        f_roles=roles["FRCSD"],
        progress=lambda message: _phase(message),
    )
    _phase(f"source map done records={len(source_map)}")
    arm_source_profiles = _arm_source_profiles(
        loaded_frcsd=loaded_by_dataset["FRCSD"],
        result_frcsd=result_by_dataset["FRCSD"],
        f_roles=roles["FRCSD"],
    )
    _phase(f"arm source profiles done records={len(arm_source_profiles)}")
    parallel_alignment = _parallel_branch_alignment(
        junction_group_id=junction_group_id,
        loaded_by_dataset=loaded_by_dataset,
        result_by_dataset=result_by_dataset,
        roles=roles,
        source_map=source_map,
    )
    _phase(f"parallel branch alignment done records={len(parallel_alignment)}")
    source_map_by_f = {item.f_road_id: item for item in source_map}
    _phase("source policy start")
    policies = {
        "SWSD": _source_policy(source_dataset="SWSD", result=result_by_dataset["SWSD"], roles=roles["SWSD"]),
        "RCSD": _source_policy(source_dataset="RCSD", result=result_by_dataset["RCSD"], roles=roles["RCSD"]),
    }
    source_arm_pass_rules = {
        "SWSD": _source_arm_pass_rules(source_dataset="SWSD", result=result_by_dataset["SWSD"], roles=roles["SWSD"]),
        "RCSD": _source_arm_pass_rules(source_dataset="RCSD", result=result_by_dataset["RCSD"], roles=roles["RCSD"]),
    }
    _phase(
        "source policy done "
        f"swsd_policy={len(policies['SWSD'])} rcsd_policy={len(policies['RCSD'])} "
        f"swsd_rules={len(source_arm_pass_rules['SWSD'])} rcsd_rules={len(source_arm_pass_rules['RCSD'])}"
    )
    needed_raw_ids = {
        dataset: {
            evidence_id
            for rule in source_arm_pass_rules[dataset]
            for evidence_id in rule.source_evidence_ids
        }
        for dataset in ("SWSD", "RCSD")
    }
    raw_by_source = {
        dataset: _raw_by_needed_id(road_next_road_by_dataset.get(dataset, tuple()), needed_raw_ids[dataset])
        for dataset in ("SWSD", "RCSD")
    }
    rule_indexes = {dataset: _rule_index(source_arm_pass_rules[dataset]) for dataset in ("SWSD", "RCSD")}
    movement_type_indexes = {dataset: _movement_type_index(result_by_dataset[dataset]) for dataset in ("SWSD", "RCSD")}
    policy_indexes = {dataset: _policy_index(policies[dataset]) for dataset in ("SWSD", "RCSD")}
    source_parallel_counts = {
        dataset: _parallel_count_by_entering_arm(result_by_dataset[dataset], roles[dataset]) for dataset in ("SWSD", "RCSD")
    }
    f_parallel_counts = _parallel_count_by_entering_arm(result_by_dataset["FRCSD"], roles["FRCSD"])
    validation_status_by_arm = {arm.final_arm_id: arm.validation_status for arm in result_by_dataset["FRCSD"].final_arms}
    profile_by_arm = {profile.arm_id: profile for profile in arm_source_profiles}
    source_arm_matches = {
        arm.final_arm_id: {
            dataset: _matched_source_arm(
                f_arm_id=arm.final_arm_id,
                source_dataset=dataset,
                result_by_dataset=result_by_dataset,
                roles=roles,
                source_map_by_f=source_map_by_f,
            )
            for dataset in ("SWSD", "RCSD")
        }
        for arm in result_by_dataset["FRCSD"].final_arms
    }
    _phase(f"source arm matches done arms={len(source_arm_matches)}")
    advance_right_pairs = {
        (relation.from_arm_id, relation.to_arm_id)
        for relation in result_by_dataset["FRCSD"].advance_right_turn_relations
        if relation.from_arm_id and relation.to_arm_id
    }
    features: list[dict[str, Any]] = []
    audit_rows: list[FrcsdGenerationAudit] = []
    decisions: list[FinalGenerationDecision] = []
    generated_pairs: set[tuple[str, str]] = set()
    duplicate_count = 0

    def append_feature(f_from: str, f_to: str, movement: ArmMovement, reference_source: str, evidence_ids: tuple[str, ...]) -> bool:
        nonlocal duplicate_count
        pair = (f_from, f_to)
        if pair in generated_pairs:
            duplicate_count += 1
            return False
        generated_pairs.add(pair)
        props = _feature_properties(
            index=len(features) + 1,
            f_road_id=f_from,
            f_next_road_id=f_to,
            movement_type=movement.movement_type,
            reference_source=reference_source,
            evidence_ids=evidence_ids,
            raw_by_source=raw_by_source,
        )
        features.append({"type": "Feature", "properties": props, "geometry": None})
        return True

    def right_turn_carrier_issues(movement: ArmMovement, from_role: RoadRole) -> tuple[str, ...]:
        if movement.movement_type != "right" or from_role.road_role != "trunk":
            return tuple()
        has_parallel_carrier = f_parallel_counts[movement.from_arm_id] > 0
        has_advance_right_carrier = (movement.from_arm_id, movement.to_arm_id) in advance_right_pairs
        if has_parallel_carrier or has_advance_right_carrier:
            return tuple()
        return ("data_error_or_missing_right_turn_carrier", "data_error")

    def final_arm_validation_issues(movement: ArmMovement) -> tuple[str, ...]:
        flags: list[str] = []
        for arm_id in (movement.from_arm_id, movement.to_arm_id):
            status = validation_status_by_arm.get(arm_id)
            if status == "conflict":
                flags.append("final_arm_validation_conflict")
            elif status == "unvalidated":
                flags.append("final_arm_validation_unvalidated")
            elif status == "weak_validated":
                flags.append("final_arm_validation_weak")
        return tuple(sorted(set(flags)))

    def with_validation_issues(movement: ArmMovement, issue_flags: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(issue_flags).union(final_arm_validation_issues(movement))))

    def has_blocking_issue(issue_flags: tuple[str, ...]) -> bool:
        blocking = {
            "data_error",
            "manual_review_required",
            "parallel_branch_count_mismatch_manual_review_required",
            "data_error_partial_target_coverage",
            "target_arm_exit_roads_missing",
        }
        return any(flag in blocking for flag in issue_flags)

    def resolve_source_movement_type(
        movement: ArmMovement,
        reference_source: str,
        source_from_arm: str | None,
        source_to_arm: str | None,
    ) -> tuple[str, tuple[str, ...]]:
        if movement.movement_type != "unknown" or not source_from_arm or not source_to_arm:
            return movement.movement_type, tuple()
        candidates = movement_type_indexes[reference_source].get((source_from_arm, source_to_arm), tuple())
        if len(candidates) == 1:
            return candidates[0], (
                "movement_type_resolved_from_reference_source",
                f"movement_type_resolved_from_{reference_source.lower()}",
            )
        if len(candidates) > 1:
            return movement.movement_type, ("source_movement_type_conflict", "manual_review_required")
        return movement.movement_type, tuple()

    def output_movement(movement: ArmMovement, source_rule: SourceArmPassRule | None) -> ArmMovement:
        if source_rule is None or source_rule.movement_type == movement.movement_type:
            return movement
        return replace(
            movement,
            movement_type=source_rule.movement_type,
            movement_type_source="reference_source_arm_movement",
            movement_type_confidence="medium",
            movement_type_reason="resolved_from_reference_source_rule",
        )

    def basic_swsd_rule(movement_type: str, from_road_role: str) -> SourceArmPassRule | None:
        if from_road_role == "parallel_branch":
            return None
        candidates = [
            rule
            for rule in source_arm_pass_rules["SWSD"]
            if rule.movement_type == movement_type
            and rule.from_road_role == from_road_role
            and rule.rule_status in {"full_allowed", "trunk_only_allowed", "left_receiving_only_allowed"}
        ]
        candidates.sort(
            key=lambda item: (
                {"full_allowed": 0, "trunk_only_allowed": 1, "left_receiving_only_allowed": 2}.get(item.rule_status, 9),
                item.from_arm_id,
                item.to_arm_id,
            )
        )
        return candidates[0] if candidates else None

    def rule_for(
        *,
        movement: ArmMovement,
        from_road_role: str,
        reference_source: str,
        reference_reason: str,
    ) -> tuple[SourceArmPassRule | None, str, str, tuple[str, ...]]:
        issues: list[str] = []
        source_from_arm, from_match_reason = source_arm_matches[movement.from_arm_id][reference_source]
        source_to_arm, to_match_reason = source_arm_matches[movement.to_arm_id][reference_source]
        effective_source = reference_source
        generation_rule = "structure_matched_source_rule"
        if reference_reason in {"single_source_rcsd", "single_source_swsd"}:
            generation_rule = "same_source_inherited"
        primary_rule: SourceArmPassRule | None = None
        primary_movement_type = movement.movement_type
        if source_from_arm and source_to_arm:
            primary_movement_type, movement_type_issues = resolve_source_movement_type(
                movement, reference_source, source_from_arm, source_to_arm
            )
            issues.extend(movement_type_issues)
            primary_rule = rule_indexes[reference_source].get((source_from_arm, source_to_arm, primary_movement_type, from_road_role))
            if primary_rule and primary_rule.rule_status in GENERATABLE_RULE_STATUSES:
                return primary_rule, effective_source, generation_rule, tuple(sorted(set(movement_type_issues)))
            if primary_rule:
                issues.append(f"{reference_source.lower()}_primary_source_rule_{primary_rule.rule_status}")

        if reference_source == "RCSD" and source_from_arm and not source_to_arm:
            issues.extend(("rcsd_target_arm_missing", "fallback_to_swsd_basic_rule"))
            fallback = basic_swsd_rule(primary_movement_type, from_road_role)
            if fallback:
                return fallback, "SWSD", "rcsd_to_swsd_fallback", tuple(sorted(set(issues)))
        alternate_source = "RCSD" if reference_source == "SWSD" else "SWSD"
        alternate_from_arm, alternate_from_reason = source_arm_matches[movement.from_arm_id][alternate_source]
        alternate_to_arm, alternate_to_reason = source_arm_matches[movement.to_arm_id][alternate_source]
        if alternate_from_arm and alternate_to_arm:
            alternate_movement_type, alternate_movement_type_issues = resolve_source_movement_type(
                movement, alternate_source, alternate_from_arm, alternate_to_arm
            )
            alternate_rule = rule_indexes[alternate_source].get(
                (alternate_from_arm, alternate_to_arm, alternate_movement_type, from_road_role)
            )
            if alternate_rule and alternate_rule.rule_status in GENERATABLE_RULE_STATUSES:
                alternate_issues = set(issues)
                alternate_issues.update(alternate_movement_type_issues)
                alternate_issues.add("alternate_source_role_ordinal_projection")
                if "corridor_ordinal_matched" in {alternate_from_reason, alternate_to_reason}:
                    alternate_issues.add("corridor_ordinal_source_arm_projection")
                if not source_from_arm:
                    alternate_issues.add(f"{reference_source.lower()}_from_arm_unmatched")
                if not source_to_arm:
                    alternate_issues.add(f"{reference_source.lower()}_to_arm_unmatched")
                if not issues:
                    alternate_issues.add(f"{reference_source.lower()}_source_rule_unavailable")
                return (
                    alternate_rule,
                    alternate_source,
                    "alternate_source_role_ordinal_projection",
                    tuple(sorted(alternate_issues)),
                )
        if reference_reason == "mixed_source_swsd_basic_rule_fallback" or not source_from_arm or not source_to_arm:
            issues.append("low_confidence_swsd_basic_rule")
            fallback = basic_swsd_rule(primary_movement_type, from_road_role)
            if fallback:
                return fallback, "SWSD", "swsd_basic_rule", tuple(sorted(set(issues)))
        if primary_rule:
            return primary_rule, effective_source, generation_rule, tuple(sorted(set(issues)))
        issues.append(f"{reference_source.lower()}_source_arm_rule_missing")
        if not source_from_arm:
            issues.append(f"{reference_source.lower()}_from_arm_unmatched")
        if not source_to_arm:
            issues.append(f"{reference_source.lower()}_to_arm_unmatched")
        return None, effective_source, generation_rule, tuple(sorted(set(issues)))

    def source_parallel_missing_decisions(movement: ArmMovement, reference_source: str) -> None:
        if f_parallel_counts[movement.from_arm_id] != 0:
            return
        source_from_arm, _ = source_arm_matches[movement.from_arm_id][reference_source]
        source_to_arm, _ = source_arm_matches[movement.to_arm_id][reference_source]
        if not source_from_arm or not source_to_arm:
            return
        source_movement_type, movement_type_issues = resolve_source_movement_type(
            movement, reference_source, source_from_arm, source_to_arm
        )
        rule = rule_indexes[reference_source].get((source_from_arm, source_to_arm, source_movement_type, "parallel_branch"))
        if rule and rule.rule_status in {"full_allowed", "trunk_only_allowed", "left_receiving_only_allowed"}:
            issues = with_validation_issues(
                movement,
                tuple(sorted(set(movement_type_issues).union({"source_parallel_branch_missing_in_frcsd"}))),
            )
            decisions.append(
                FinalGenerationDecision(
                    from_arm_id=movement.from_arm_id,
                    to_arm_id=movement.to_arm_id,
                    movement_type=rule.movement_type,
                    from_road_role="parallel_branch",
                    reference_source=reference_source,
                    rule_status=rule.rule_status,
                    generation_scope="none",
                    generated_road_ids=tuple(),
                    generated_next_road_ids=tuple(),
                    issue_flags=issues,
                )
            )

    movements = result_by_dataset["FRCSD"].arm_movements
    _phase(f"generation loop start movements={len(movements)}")
    for movement_index, movement in enumerate(movements, start=1):
        if movement_index == 1 or movement_index == len(movements) or movement_index % 10 == 0:
            _phase(f"generation loop progress {movement_index}/{len(movements)}")
        profile = profile_by_arm.get(
            movement.from_arm_id,
            ArmSourceProfile("FRCSD", movement.from_arm_id, {}, {}, {}, {}, False, ("empty_arm_source_profile",)),
        )
        reference_source, reference_reason, reference_issues = _choose_reference_source(
            profile, source_arm_matches[movement.from_arm_id]
        )
        source_parallel_missing_decisions(movement, reference_source)
        from_roles = _arm_entering_roles(result_by_dataset["FRCSD"], roles["FRCSD"], movement.from_arm_id)
        from_role_types = sorted({role.road_role for role in from_roles})
        for from_road_role in from_role_types:
            source_rule, effective_source, generation_rule, rule_lookup_issues = rule_for(
                movement=movement,
                from_road_role=from_road_role,
                reference_source=reference_source,
                reference_reason=reference_reason,
            )
            issue_flags = tuple(sorted(set(reference_issues).union(rule_lookup_issues)))
            if source_rule is None:
                rule_status = "insufficient"
                generation_scope = "none"
                evidence_ids: tuple[str, ...] = tuple()
            else:
                rule_status = source_rule.rule_status
                generation_scope = source_rule.generation_scope
                evidence_ids = source_rule.source_evidence_ids
                issue_flags = tuple(sorted(set(issue_flags).union(source_rule.issue_flags)))
            movement_for_output = output_movement(movement, source_rule)
            role_from_roads = tuple(role for role in from_roles if role.road_role == from_road_role)
            target_roles = _generation_target_roles(
                result_frcsd=result_by_dataset["FRCSD"],
                f_roles=roles["FRCSD"],
                to_arm_id=movement.to_arm_id,
                generation_scope=generation_scope,
            )
            if from_road_role == "parallel_branch" and source_rule is not None and rule_status != "prohibited":
                source_from_arm = source_rule.from_arm_id
                if source_parallel_counts[effective_source][source_from_arm] != f_parallel_counts[movement.from_arm_id]:
                    issue_flags = tuple(
                        sorted(set(issue_flags).union({"parallel_branch_count_mismatch_manual_review_required", "data_error"}))
                    )
                    rule_status = "data_error_partial_target_coverage"
                    generation_scope = "none"
                    target_roles = tuple()
            permission = (
                "allowed"
                if rule_status in {"full_allowed", "trunk_only_allowed", "left_receiving_only_allowed"}
                and not has_blocking_issue(issue_flags)
                else "prohibited"
            )
            if rule_status in {"data_error_partial_target_coverage", "insufficient", "conflict"}:
                permission = "manual_review_required"
            generated_from_ids: list[str] = []
            generated_to_ids: list[str] = []
            if permission in {"prohibited", "manual_review_required"}:
                for from_role in role_from_roads:
                    carrier_issues = right_turn_carrier_issues(movement_for_output, from_role)
                    if carrier_issues:
                        issue_flags = tuple(sorted(set(issue_flags).union(carrier_issues)))
                        permission = "manual_review_required"
                        rule_status = "data_error_partial_target_coverage" if "data_error" in carrier_issues else rule_status
                        break
            if permission == "allowed":
                for from_role in role_from_roads:
                    for to_role in target_roles:
                        if from_role.road_id == to_role.road_id:
                            continue
                        from_map = source_map_by_f.get(from_role.road_id)
                        to_map = source_map_by_f.get(to_role.road_id)
                        from_source = _norm((loaded_by_dataset["FRCSD"].roads.get(from_role.road_id).properties or {}).get("source")) if from_role.road_id in loaded_by_dataset["FRCSD"].roads else ""
                        to_source = _norm((loaded_by_dataset["FRCSD"].roads.get(to_role.road_id).properties or {}).get("source")) if to_role.road_id in loaded_by_dataset["FRCSD"].roads else ""
                        pair_rule = generation_rule
                        if generation_rule == "same_source_inherited" and from_source != to_source:
                            pair_rule = "cross_source_primary_source_policy"
                        if generation_rule == "structure_matched_source_rule" and reference_reason.startswith("mixed_source"):
                            pair_rule = "structure_matched_source_rule"
                        source_match_status = ",".join(
                            item
                            for item in (
                                from_map.match_status if from_map else "from_source_map_missing",
                                to_map.match_status if to_map else "to_source_map_missing",
                            )
                            if item
                        )
                        appended = append_feature(from_role.road_id, to_role.road_id, movement_for_output, effective_source, evidence_ids)
                        if appended:
                            generated_from_ids.append(from_role.road_id)
                            generated_to_ids.append(to_role.road_id)
                        audit_rows.append(
                            _audit(
                                f_road_id=from_role.road_id,
                                f_next_road_id=to_role.road_id,
                                movement=movement_for_output,
                                from_role=from_role,
                                to_role=to_role,
                                from_source=from_source,
                                to_source=to_source,
                                primary_source=reference_source,
                                reference_source=effective_source,
                                generation_rule=pair_rule,
                                permission_status="allowed",
                                evidence_ids=evidence_ids,
                                confidence=(
                                    "high"
                                    if source_match_status == "matched,matched"
                                    else (
                                        "low"
                                        if generation_rule in {"swsd_basic_rule", "alternate_source_role_ordinal_projection"}
                                        else "medium"
                                    )
                                ),
                                issue_flags=with_validation_issues(movement_for_output, issue_flags),
                                rule_status=rule_status,
                                generation_scope=generation_scope,
                                generation_basis="rule_projected",
                                source_match_status=source_match_status,
                            )
                        )
            else:
                for from_role in role_from_roads:
                    from_map = source_map_by_f.get(from_role.road_id)
                    from_source = _norm((loaded_by_dataset["FRCSD"].roads.get(from_role.road_id).properties or {}).get("source")) if from_role.road_id in loaded_by_dataset["FRCSD"].roads else ""
                    audit_rows.append(
                        _audit(
                            f_road_id=from_role.road_id,
                            f_next_road_id="",
                            movement=movement_for_output,
                            from_role=from_role,
                            to_role=RoadRole("FRCSD", movement.to_arm_id, "", "", ""),
                            from_source=from_source,
                            to_source="",
                            primary_source=reference_source,
                            reference_source=effective_source if permission == "manual_review_required" else "",
                            generation_rule=generation_rule,
                            permission_status=permission,
                            evidence_ids=evidence_ids,
                            confidence="none" if permission == "manual_review_required" else "medium",
                            issue_flags=with_validation_issues(movement_for_output, issue_flags),
                            rule_status=rule_status,
                            generation_scope=generation_scope,
                            generation_basis="rule_projected",
                            source_match_status=from_map.match_status if from_map else "from_source_map_missing",
                        )
                    )
            decisions.append(
                FinalGenerationDecision(
                    from_arm_id=movement.from_arm_id,
                    to_arm_id=movement.to_arm_id,
                    movement_type=movement_for_output.movement_type,
                    from_road_role=from_road_role,
                    reference_source=effective_source if source_rule is not None else reference_source,
                    rule_status=rule_status,
                    generation_scope=generation_scope,
                    generated_road_ids=tuple(sorted(set(generated_from_ids))),
                    generated_next_road_ids=tuple(sorted(set(generated_to_ids))),
                    issue_flags=with_validation_issues(movement_for_output, issue_flags),
                )
            )
    _phase(f"generation loop done features={len(features)} audit={len(audit_rows)} decisions={len(decisions)}")
    issue_report = _issues_from_audit(source_map, parallel_alignment, audit_rows, duplicate_count)
    source_counts = Counter(item.match_status for item in source_map)
    audit_counts = Counter(item.generation_rule for item in audit_rows if item.permission_status == "allowed")
    parallel_counts = Counter(item.alignment_status for item in parallel_alignment)
    rule_status_counts = Counter(item.rule_status for item in decisions)
    metrics = {
        "frcsd_generated_road_next_road_count": len(features),
        "frcsd_source_geometry_match_missing_count": source_counts.get("source_geometry_match_missing", 0),
        "frcsd_source_geometry_match_ambiguous_count": source_counts.get("ambiguous_source_geometry_match", 0),
        "frcsd_same_source_inherited_count": audit_counts.get("same_source_inherited", 0),
        "frcsd_cross_source_generated_count": audit_counts.get("cross_source_primary_source_policy", 0),
        "frcsd_fallback_to_swsd_count": audit_counts.get("rcsd_to_swsd_fallback", 0),
        "frcsd_alternate_source_projected_count": audit_counts.get("alternate_source_role_ordinal_projection", 0),
        "frcsd_swsd_basic_rule_count": audit_counts.get("swsd_basic_rule", 0),
        "frcsd_rule_projected_count": sum(1 for item in audit_rows if item.permission_status == "allowed"),
        "frcsd_data_error_partial_target_coverage_count": rule_status_counts.get("data_error_partial_target_coverage", 0),
        "frcsd_manual_review_required_count": sum(1 for item in audit_rows if item.permission_status == "manual_review_required"),
        "frcsd_parallel_branch_alignment_count": len(parallel_alignment),
        "frcsd_parallel_branch_count_matched_ordered_count": parallel_counts.get("count_matched_ordered", 0),
        "frcsd_parallel_branch_manual_review_required_count": sum(
            parallel_counts.get(status, 0)
            for status in (
                "source_missing_in_frcsd",
                "count_mismatch_manual_review_required",
                "insufficient_geometry_for_ordering",
            )
        ),
    }
    return FrcsdRoadNextRoadFinalResult(
        features=tuple(features),
        source_road_map=source_map,
        source_movement_policy_swsd=policies["SWSD"],
        source_movement_policy_rcsd=policies["RCSD"],
        arm_source_profiles=arm_source_profiles,
        source_arm_pass_rules_swsd=source_arm_pass_rules["SWSD"],
        source_arm_pass_rules_rcsd=source_arm_pass_rules["RCSD"],
        final_generation_decisions=tuple(decisions),
        parallel_branch_alignment=parallel_alignment,
        audit=tuple(audit_rows),
        issue_report=issue_report,
        metrics=metrics,
    )


def final_geojson(result: FrcsdRoadNextRoadFinalResult) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [to_plain(feature) for feature in result.features]}


def final_review_layers(
    *,
    loaded_frcsd: LoadedDataset,
    result_frcsd: DatasetBuildResult | None = None,
    result: FrcsdRoadNextRoadFinalResult,
) -> list[tuple[str, str, list[tuple[Any, dict[str, Any]]]]]:
    roads = loaded_frcsd.roads
    center = _junction_center(loaded_frcsd, result_frcsd)
    generated = []
    for feature in result.features:
        props = feature["properties"]
        from_road = roads.get(str(props.get("road_id", "")))
        to_road = roads.get(str(props.get("next_road_id", "")))
        line, review_geometry = _generated_review_line(from_road, to_road, center)
        generated.append((line, {**props, "review_geometry": review_geometry}))
    source_map = []
    for item in result.source_road_map:
        road = roads.get(item.f_road_id)
        if road:
            source_map.append((road.geometry, to_plain(item)))
    decisions = []
    for item in result.final_generation_decisions:
        arm_roads = [roads[road_id] for road_id in item.generated_road_ids if road_id in roads]
        if arm_roads:
            point = _road_midpoint(arm_roads[0])
        else:
            point = Point(0.0, 0.0)
        decisions.append((point, to_plain(item)))
    issues = []
    for issue in result.issue_report.get("issues", []):
        road = roads.get(str(issue.get("f_road_id", "")))
        issues.append((_road_midpoint(road), issue))
    return [
        ("frcsd_generated_road_next_road", "LineString", generated),
        ("frcsd_source_road_map", "LineString", source_map),
        ("final_generation_decisions", "Point", decisions),
        ("frcsd_road_next_road_issues", "Point", issues),
    ]


def render_final_review_png(path: Path, result: FrcsdRoadNextRoadFinalResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1100, 760), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    lines = [
        "P01-Final F-RCSD RoadNextRoad",
        f"generated={result.metrics['frcsd_generated_road_next_road_count']}",
        f"same_source={result.metrics['frcsd_same_source_inherited_count']}",
        f"cross_source={result.metrics['frcsd_cross_source_generated_count']}",
        f"fallback_swsd={result.metrics['frcsd_fallback_to_swsd_count']}",
        f"swsd_basic={result.metrics['frcsd_swsd_basic_rule_count']}",
        f"partial_error={result.metrics['frcsd_data_error_partial_target_coverage_count']}",
        f"manual_review={result.metrics['frcsd_manual_review_required_count']}",
        f"source_missing={result.metrics['frcsd_source_geometry_match_missing_count']}",
        f"source_ambiguous={result.metrics['frcsd_source_geometry_match_ambiguous_count']}",
    ]
    y = 20
    for line in lines:
        draw.text((20, y), line, fill=(20, 20, 20), font=font)
        y += 28
    for item in list(result.audit)[:18]:
        text = (
            f"{item.f_road_id}->{item.f_next_road_id} {item.generation_rule} "
            f"{item.permission_status} {','.join(item.issue_flags)}"
        )
        draw.text((20, y), text[:155], fill=(70, 70, 70), font=font)
        y += 24
    image.save(path)


def write_final_geojson(path: Path, result: FrcsdRoadNextRoadFinalResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(final_geojson(result), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
