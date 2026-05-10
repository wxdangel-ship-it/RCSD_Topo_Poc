from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Point

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
    parallel_branch_alignment: tuple[ParallelBranchAlignment, ...]
    audit: tuple[FrcsdGenerationAudit, ...]
    issue_report: dict[str, Any]
    metrics: dict[str, int]


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def _geometry_key(road: RoadRecord) -> str:
    return road.geometry.wkb_hex


def _road_midpoint(road: RoadRecord | None) -> Point:
    if road is None or road.geometry.is_empty:
        return Point(0.0, 0.0)
    try:
        return road.geometry.interpolate(0.5, normalized=True)
    except Exception:
        return road.geometry.representative_point()


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


def _parallel_count_by_arm(roles: dict[str, RoadRole]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for role in roles.values():
        if role.road_role == "parallel_branch":
            counts[role.arm_id] += 1
    return counts


def _road_order_key(road_id: str, roads: dict[str, RoadRecord]) -> tuple[float, float, str]:
    point = _road_midpoint(roads.get(road_id))
    return (round(float(point.x), 6), round(float(point.y), 6), road_id)


def _raw_pair_index(records: tuple[RawRoadNextRoad, ...]) -> dict[tuple[str, str], tuple[RawRoadNextRoad, ...]]:
    pairs: dict[tuple[str, str], list[RawRoadNextRoad]] = defaultdict(list)
    for record in records:
        pairs[(record.road_id, record.next_road_id)].append(record)
    return {key: tuple(value) for key, value in pairs.items()}


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
    frcsd_roads: dict[str, RoadRecord],
    source_roads: dict[str, dict[str, RoadRecord]],
    f_roles: dict[str, RoadRole],
) -> tuple[SourceRoadMap, ...]:
    source_index: dict[str, dict[str, list[str]]] = {}
    for dataset in ("RCSD", "SWSD"):
        by_geometry: dict[str, list[str]] = defaultdict(list)
        for road_id, road in source_roads[dataset].items():
            by_geometry[_geometry_key(road)].append(road_id)
        source_index[dataset] = by_geometry
    rows: list[SourceRoadMap] = []
    for f_road_id in sorted(f_roles):
        road = frcsd_roads.get(f_road_id)
        raw_source = _norm((road.properties if road else {}).get("source"))
        issue_flags: list[str] = []
        source_dataset = SOURCE_TO_DATASET.get(raw_source, "")
        source_road_id: str | None = None
        if raw_source not in SOURCE_TO_DATASET:
            status = "source_invalid"
            reason = "source_missing_or_not_in_allowed_values"
            issue_flags.append("frcsd_source_invalid")
        else:
            matches = source_index[source_dataset].get(_geometry_key(road), []) if road else []
            if len(matches) == 1:
                status = "matched"
                reason = "source_limited_exact_geometry_match"
                source_road_id = matches[0]
            elif len(matches) > 1:
                status = "ambiguous_source_geometry_match"
                reason = "multiple_source_roads_have_exact_same_geometry"
                issue_flags.append("ambiguous_source_geometry_match")
            else:
                status = "source_geometry_match_missing"
                reason = "no_source_road_has_exact_same_geometry"
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
    roles_by_arm: dict[str, list[RoadRole]] = defaultdict(list)
    for role in roles.values():
        roles_by_arm[role.arm_id].append(role)
    candidate_grouped: dict[tuple[str, str, str, str, str], dict[str, set[str]]] = {}
    for movement in result.arm_movements:
        for from_role in roles_by_arm.get(movement.from_arm_id, []):
            for to_role in roles_by_arm.get(movement.to_arm_id, []):
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


def _policy_index(policy: tuple[SourceMovementPolicy, ...]) -> dict[tuple[str, str, str], tuple[SourceMovementPolicy, ...]]:
    grouped: dict[tuple[str, str, str], list[SourceMovementPolicy]] = defaultdict(list)
    for item in policy:
        if item.permission_status == "allowed":
            grouped[(item.movement_type, item.from_road_role, item.to_road_role)].append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def _parallel_branch_alignment(
    *,
    junction_group_id: str,
    loaded_by_dataset: dict[str, LoadedDataset],
    roles: dict[str, dict[str, RoadRole]],
    source_map: tuple[SourceRoadMap, ...],
) -> tuple[ParallelBranchAlignment, ...]:
    source_map_by_f = {item.f_road_id: item for item in source_map}
    f_arm_ids = sorted({role.arm_id for role in roles["FRCSD"].values()})
    rows: list[ParallelBranchAlignment] = []
    for arm_id in f_arm_ids:
        f_arm_roles = [role for role in roles["FRCSD"].values() if role.arm_id == arm_id]
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
            source_parallel_roles = [
                role
                for role in roles[source_dataset].values()
                if role.arm_id in source_arm_ids and role.road_role == "parallel_branch"
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


def _raw_by_id(records: tuple[RawRoadNextRoad, ...]) -> dict[str, RawRoadNextRoad]:
    return {record.raw_id: record for record in records}


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
) -> FrcsdRoadNextRoadFinalResult:
    roles = {dataset: _road_roles(result_by_dataset[dataset]) for dataset in DATASETS}
    source_map = _source_road_map(
        frcsd_roads=loaded_by_dataset["FRCSD"].roads,
        source_roads={"SWSD": loaded_by_dataset["SWSD"].roads, "RCSD": loaded_by_dataset["RCSD"].roads},
        f_roles=roles["FRCSD"],
    )
    parallel_alignment = _parallel_branch_alignment(
        junction_group_id=junction_group_id,
        loaded_by_dataset=loaded_by_dataset,
        roles=roles,
        source_map=source_map,
    )
    source_map_by_f = {item.f_road_id: item for item in source_map}
    raw_pairs = {dataset: _raw_pair_index(road_next_road_by_dataset.get(dataset, tuple())) for dataset in ("SWSD", "RCSD")}
    raw_by_source = {dataset: _raw_by_id(road_next_road_by_dataset.get(dataset, tuple())) for dataset in ("SWSD", "RCSD")}
    policies = {
        "SWSD": _source_policy(source_dataset="SWSD", result=result_by_dataset["SWSD"], roles=roles["SWSD"]),
        "RCSD": _source_policy(source_dataset="RCSD", result=result_by_dataset["RCSD"], roles=roles["RCSD"]),
    }
    policy_indexes = {dataset: _policy_index(policies[dataset]) for dataset in ("SWSD", "RCSD")}
    source_roles_by_road = {dataset: roles[dataset] for dataset in ("SWSD", "RCSD")}
    source_parallel_counts = {dataset: _parallel_count_by_arm(roles[dataset]) for dataset in ("SWSD", "RCSD")}
    f_parallel_counts = _parallel_count_by_arm(roles["FRCSD"])
    f_movements = _movement_by_pair(result_by_dataset["FRCSD"])
    advance_right_pairs = {
        (relation.from_arm_id, relation.to_arm_id)
        for relation in result_by_dataset["FRCSD"].advance_right_turn_relations
        if relation.from_arm_id and relation.to_arm_id
    }
    features: list[dict[str, Any]] = []
    audit_rows: list[FrcsdGenerationAudit] = []
    generated_pairs: set[tuple[str, str]] = set()
    duplicate_count = 0

    def append_feature(f_from: str, f_to: str, movement: ArmMovement, reference_source: str, evidence_ids: tuple[str, ...]) -> None:
        nonlocal duplicate_count
        pair = (f_from, f_to)
        if pair in generated_pairs:
            duplicate_count += 1
            return
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

    def right_turn_carrier_issues(movement: ArmMovement, from_role: RoadRole) -> tuple[str, ...]:
        if movement.movement_type != "right" or from_role.road_role != "trunk":
            return tuple()
        has_parallel_carrier = f_parallel_counts[movement.to_arm_id] > 0
        has_advance_right_carrier = (movement.from_arm_id, movement.to_arm_id) in advance_right_pairs
        if has_parallel_carrier or has_advance_right_carrier:
            return tuple()
        return ("data_error_or_missing_right_turn_carrier", "data_error")

    def source_parallel_missing_issues(
        *,
        source_dataset: str,
        movement: ArmMovement,
        from_role: RoadRole,
        to_role: RoadRole,
    ) -> tuple[str, ...]:
        issues: list[str] = []
        if (
            f_parallel_counts[movement.from_arm_id] == 0
            and policy_indexes[source_dataset].get((movement.movement_type, "parallel_branch", to_role.target_role), tuple())
        ):
            issues.append("source_parallel_branch_missing_in_frcsd")
        if (
            f_parallel_counts[movement.to_arm_id] == 0
            and policy_indexes[source_dataset].get((movement.movement_type, from_role.road_role, "parallel_branch"), tuple())
        ):
            issues.append("source_parallel_branch_missing_in_frcsd")
        return tuple(sorted(set(issues)))

    for movement in result_by_dataset["FRCSD"].arm_movements:
        from_roads = [role for role in roles["FRCSD"].values() if role.arm_id == movement.from_arm_id]
        to_roads = [role for role in roles["FRCSD"].values() if role.arm_id == movement.to_arm_id]
        for from_role in from_roads:
            for to_role in to_roads:
                if from_role.road_id == to_role.road_id:
                    continue
                from_map = source_map_by_f.get(from_role.road_id)
                to_map = source_map_by_f.get(to_role.road_id)
                if not from_map or not to_map or from_map.match_status != "matched" or to_map.match_status != "matched":
                    audit_rows.append(
                        _audit(
                            f_road_id=from_role.road_id,
                            f_next_road_id=to_role.road_id,
                            movement=movement,
                            from_role=from_role,
                            to_role=to_role,
                            from_source=from_map.f_road_source if from_map else "",
                            to_source=to_map.f_road_source if to_map else "",
                            primary_source="",
                            reference_source="",
                            generation_rule="source_mapping_unresolved",
                            permission_status="manual_review_required",
                            evidence_ids=tuple(),
                            confidence="none",
                            issue_flags=("source_mapping_unresolved",),
                        )
                    )
                    continue
                primary_source = SOURCE_TO_DATASET[from_map.f_road_source]
                if from_map.f_road_source == to_map.f_road_source:
                    pair_records = raw_pairs[primary_source].get((from_map.source_road_id or "", to_map.source_road_id or ""), tuple())
                    if pair_records:
                        evidence_ids = tuple(record.raw_id for record in pair_records)
                        append_feature(from_role.road_id, to_role.road_id, movement, primary_source, evidence_ids)
                        permission = "allowed"
                        rule = "same_source_inherited"
                        confidence = "high"
                        issue_flags = source_parallel_missing_issues(
                            source_dataset=primary_source,
                            movement=movement,
                            from_role=from_role,
                            to_role=to_role,
                        )
                    else:
                        evidence_ids = tuple()
                        issue_flags = right_turn_carrier_issues(movement, from_role)
                        permission = "manual_review_required" if issue_flags else "prohibited"
                        rule = "same_source_missing_source_road_next_road"
                        confidence = "none" if issue_flags else "high"
                    audit_rows.append(
                        _audit(
                            f_road_id=from_role.road_id,
                            f_next_road_id=to_role.road_id,
                            movement=movement,
                            from_role=from_role,
                            to_role=to_role,
                            from_source=from_map.f_road_source,
                            to_source=to_map.f_road_source,
                            primary_source=primary_source,
                            reference_source=primary_source,
                            generation_rule=rule,
                            permission_status=permission,
                            evidence_ids=evidence_ids,
                            confidence=confidence,
                            issue_flags=issue_flags,
                        )
                    )
                    continue
                key = (movement.movement_type, from_role.road_role, to_role.target_role)
                allowed = policy_indexes[primary_source].get(key, tuple())
                reference_source = primary_source
                rule = "cross_source_primary_source_policy"
                issue_flags: tuple[str, ...] = tuple()
                if not allowed and from_map.f_road_source == "1" and to_map.f_road_source == "2":
                    fallback_allowed = policy_indexes["SWSD"].get(key, tuple())
                    if fallback_allowed:
                        source_from_role = source_roles_by_road["RCSD"].get(from_map.source_road_id or "")
                        primary_count = (
                            sum(1 for role in source_roles_by_road["RCSD"].values() if role.arm_id == source_from_role.arm_id)
                            if source_from_role
                            else -1
                        )
                        fallback_counts = {
                            sum(1 for role in source_roles_by_road["SWSD"].values() if role.arm_id == item.from_arm_id)
                            for item in fallback_allowed
                        }
                        if primary_count in fallback_counts:
                            allowed = fallback_allowed
                            reference_source = "SWSD"
                            rule = "rcsd_to_swsd_fallback"
                        else:
                            issue_flags = ("entering_arm_road_count_mismatch_between_primary_and_fallback_source",)
                if allowed and not issue_flags:
                    if "parallel_branch" in {from_role.road_role, to_role.target_role}:
                        f_count = f_parallel_counts[movement.from_arm_id if from_role.road_role == "parallel_branch" else movement.to_arm_id]
                        source_counts = {
                            source_parallel_counts[reference_source][
                                item.from_arm_id if from_role.road_role == "parallel_branch" else item.to_arm_id
                            ]
                            for item in allowed
                        }
                        if source_counts and f_count not in source_counts:
                            issue_flags = ("parallel_branch_count_mismatch_manual_review_required", "data_error")
                    if not issue_flags:
                        issue_flags = source_parallel_missing_issues(
                            source_dataset=reference_source,
                            movement=movement,
                            from_role=from_role,
                            to_role=to_role,
                        )
                        evidence_ids = tuple(sorted({eid for item in allowed for eid in item.source_road_next_road_ids}))
                        append_feature(from_role.road_id, to_role.road_id, movement, reference_source, evidence_ids)
                        permission = "allowed"
                        confidence = "medium" if rule == "cross_source_primary_source_policy" else "low"
                    else:
                        evidence_ids = tuple()
                        permission = "manual_review_required"
                        confidence = "none"
                else:
                    evidence_ids = tuple()
                    permission = "manual_review_required" if issue_flags else "prohibited"
                    confidence = "none" if issue_flags else "medium"
                if permission == "prohibited":
                    carrier_issues = right_turn_carrier_issues(movement, from_role)
                    if carrier_issues:
                        issue_flags = tuple(sorted(set(issue_flags).union(carrier_issues)))
                        permission = "manual_review_required"
                        confidence = "none"
                audit_rows.append(
                    _audit(
                        f_road_id=from_role.road_id,
                        f_next_road_id=to_role.road_id,
                        movement=movement,
                        from_role=from_role,
                        to_role=to_role,
                        from_source=from_map.f_road_source,
                        to_source=to_map.f_road_source,
                        primary_source=primary_source,
                        reference_source=reference_source if permission == "allowed" else "",
                        generation_rule=rule,
                        permission_status=permission,
                        evidence_ids=evidence_ids,
                        confidence=confidence,
                        issue_flags=issue_flags,
                    )
                )
    issue_report = _issues_from_audit(source_map, parallel_alignment, audit_rows, duplicate_count)
    source_counts = Counter(item.match_status for item in source_map)
    audit_counts = Counter(item.generation_rule for item in audit_rows if item.permission_status == "allowed")
    parallel_counts = Counter(item.alignment_status for item in parallel_alignment)
    metrics = {
        "frcsd_generated_road_next_road_count": len(features),
        "frcsd_source_geometry_match_missing_count": source_counts.get("source_geometry_match_missing", 0),
        "frcsd_source_geometry_match_ambiguous_count": source_counts.get("ambiguous_source_geometry_match", 0),
        "frcsd_same_source_inherited_count": audit_counts.get("same_source_inherited", 0),
        "frcsd_cross_source_generated_count": audit_counts.get("cross_source_primary_source_policy", 0),
        "frcsd_fallback_to_swsd_count": audit_counts.get("rcsd_to_swsd_fallback", 0),
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
    result: FrcsdRoadNextRoadFinalResult,
) -> list[tuple[str, str, list[tuple[Any, dict[str, Any]]]]]:
    roads = loaded_frcsd.roads
    generated = []
    for feature in result.features:
        props = feature["properties"]
        from_road = roads.get(str(props.get("road_id", "")))
        to_road = roads.get(str(props.get("next_road_id", "")))
        line = LineString([_road_midpoint(from_road), _road_midpoint(to_road)])
        generated.append((line, props))
    source_map = []
    for item in result.source_road_map:
        road = roads.get(item.f_road_id)
        if road:
            source_map.append((road.geometry, to_plain(item)))
    issues = []
    for issue in result.issue_report.get("issues", []):
        road = roads.get(str(issue.get("f_road_id", "")))
        issues.append((_road_midpoint(road), issue))
    return [
        ("frcsd_generated_road_next_road", "LineString", generated),
        ("frcsd_source_road_map", "LineString", source_map),
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
