from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    SWSDSegmentInput,
    SWSDRoadInput,
    T09SwsdArm,
)


SAME_ROLE_BUNDLE_TOLERANCE_DEG = 15.0
SAME_DIRECTION_PAIR_TOLERANCE_DEG = 18.0
OUTBOUND_TO_INBOUND_MAX_GAP_DEG = 80.0


@dataclass(frozen=True)
class _SeedItem:
    road: SWSDRoadInput
    inbound: bool
    outbound: bool
    role: str
    angle_deg: float | None
    terminal_node_id: str
    segment_matches: tuple[tuple[str, str], ...]
    segment_ids: tuple[str, ...]


def build_swsd_arms(
    *,
    junction_id: str,
    member_node_ids: tuple[str, ...],
    roads: tuple[SWSDRoadInput, ...],
    segments: tuple[SWSDSegmentInput, ...] = tuple(),
    road_geometries: dict[str, BaseGeometry] | None = None,
) -> tuple[T09SwsdArm, ...]:
    member_set = set(member_node_ids)
    segment_by_road = _segment_index(segments, member_set)
    internal_roads = tuple(
        road.road_id for road in roads if road.snodeid in member_set and road.enodeid in member_set
    )
    seed_items = _seed_items(
        roads=roads,
        member_set=member_set,
        segment_by_road=segment_by_road,
        road_geometries=road_geometries or {},
    )
    seed_groups = _directional_seed_groups(seed_items) if road_geometries else tuple((item,) for item in seed_items)
    all_seed_ids = {item.road.road_id for item in seed_items}
    segment_by_id = {segment.segment_id: segment for segment in segments}

    arms: list[T09SwsdArm] = []
    for group in seed_groups:
        arms.append(
            _arm_from_seed_group(
                junction_id=junction_id,
                member_node_ids=member_node_ids,
                internal_roads=internal_roads,
                seed_group=group,
                all_seed_ids=all_seed_ids,
                segment_by_id=segment_by_id,
            )
        )
    return tuple(arms)


def _seed_items(
    *,
    roads: tuple[SWSDRoadInput, ...],
    member_set: set[str],
    segment_by_road: dict[str, tuple[tuple[str, str], ...]],
    road_geometries: dict[str, BaseGeometry],
) -> tuple[_SeedItem, ...]:
    items: list[_SeedItem] = []
    for road in roads:
        snode_inside = road.snodeid in member_set
        enode_inside = road.enodeid in member_set
        if snode_inside == enode_inside:
            continue
        inbound, outbound = _road_roles_for_junction(road, snode_inside=snode_inside)
        segment_matches = segment_by_road.get(road.road_id, tuple())
        segment_ids = road.segment_ids or tuple(segment_id for segment_id, _ in segment_matches)
        terminal_node_id = road.enodeid if snode_inside else road.snodeid
        items.append(
            _SeedItem(
                road=road,
                inbound=inbound,
                outbound=outbound,
                role=_role(inbound=inbound, outbound=outbound),
                angle_deg=_road_outward_angle(road, road_geometries.get(road.road_id), member_set),
                terminal_node_id=terminal_node_id,
                segment_matches=segment_matches,
                segment_ids=segment_ids,
            )
        )
    return tuple(items)


def _arm_from_seed_group(
    *,
    junction_id: str,
    member_node_ids: tuple[str, ...],
    internal_roads: tuple[str, ...],
    seed_group: tuple[_SeedItem, ...],
    all_seed_ids: set[str],
    segment_by_id: dict[str, SWSDSegmentInput],
) -> T09SwsdArm:
    seed_ids = tuple(sorted((item.road.road_id for item in seed_group), key=_sort_key))
    segment_ids = tuple(
        sorted({segment_id for item in seed_group for segment_id in item.segment_ids}, key=_sort_key)
    )
    inbound_ids = tuple(sorted((item.road.road_id for item in seed_group if item.inbound), key=_sort_key))
    outbound_ids = tuple(sorted((item.road.road_id for item in seed_group if item.outbound), key=_sort_key))
    bidirectional_ids = tuple(
        sorted((item.road.road_id for item in seed_group if item.inbound and item.outbound), key=_sort_key)
    )
    connector_ids = _connector_road_ids(
        segment_ids=segment_ids,
        segment_by_id=segment_by_id,
        all_seed_ids=all_seed_ids,
        internal_roads=set(internal_roads),
    )
    terminal_ids = tuple(sorted({item.terminal_node_id for item in seed_group}, key=_sort_key))
    risk_flags = []
    if any(not item.segment_ids for item in seed_group):
        risk_flags.append("segment_membership_missing")
    if len(segment_ids) > 1:
        risk_flags.append("multi_segment_directional_arm")
    angle = _mean_angle([item.angle_deg for item in seed_group if item.angle_deg is not None])
    audit_refs = (
        f"grouping=segment_local_direction",
        f"seed_road_ids={','.join(seed_ids)}",
        f"terminal_node_ids={','.join(terminal_ids)}",
    )
    return T09SwsdArm(
        junction_id=junction_id,
        arm_id=f"{junction_id}:arm:{'+'.join(seed_ids)}",
        member_node_ids=member_node_ids,
        internal_road_ids=internal_roads,
        seed_road_ids=seed_ids,
        connector_road_ids=connector_ids,
        segment_ids=segment_ids,
        inbound_road_ids=inbound_ids,
        outbound_road_ids=outbound_ids,
        bidirectional_road_ids=bidirectional_ids,
        approach_road_ids=tuple(sorted(set(inbound_ids) | set(bidirectional_ids), key=_sort_key)),
        exit_road_ids=tuple(sorted(set(outbound_ids) | set(bidirectional_ids), key=_sort_key)),
        trunk_road_ids=seed_ids,
        advance_left_road_ids=tuple(sorted((item.road.road_id for item in seed_group if item.road.formway & 256), key=_sort_key)),
        terminal_node_id=terminal_ids[0] if len(terminal_ids) == 1 else None,
        terminal_kind=_group_terminal_kind(seed_group, segment_ids),
        angle_deg=angle,
        risk_flags=tuple(sorted(risk_flags)),
        audit_refs=audit_refs,
    )


def _connector_road_ids(
    *,
    segment_ids: tuple[str, ...],
    segment_by_id: dict[str, SWSDSegmentInput],
    all_seed_ids: set[str],
    internal_roads: set[str],
) -> tuple[str, ...]:
    road_ids = {
        road_id
        for segment_id in segment_ids
        for road_id in segment_by_id.get(segment_id, SWSDSegmentInput(segment_id=segment_id)).road_ids
    }
    return tuple(sorted(road_ids - all_seed_ids - internal_roads, key=_sort_key))


def _segment_index(
    segments: tuple[SWSDSegmentInput, ...],
    member_set: set[str],
) -> dict[str, tuple[tuple[str, str], ...]]:
    indexed: dict[str, list[tuple[str, str]]] = {}
    for segment in segments:
        membership_kind = _segment_membership_kind(segment, member_set)
        for road_id in segment.road_ids:
            indexed.setdefault(road_id, []).append((segment.segment_id, membership_kind))
    return {road_id: tuple(segment_ids) for road_id, segment_ids in indexed.items()}


def _segment_membership_kind(segment: SWSDSegmentInput, member_set: set[str]) -> str:
    if member_set.intersection(segment.junc_nodes):
        return "segment_junc_node"
    if member_set.intersection(segment.pair_nodes):
        return "segment_pair_node"
    return "segment_road_member"


def _terminal_kind(
    segment_ids: tuple[str, ...],
    segment_matches: tuple[tuple[str, str], ...],
) -> str:
    if not segment_ids:
        return "local_topology_fallback"
    kinds = {kind for _, kind in segment_matches}
    if "segment_junc_node" in kinds:
        return "segment_junc_node"
    if "segment_pair_node" in kinds:
        return "segment_pair_node"
    if segment_matches:
        return "segment_road_member"
    return "segment_reference"


def _group_terminal_kind(seed_group: tuple[_SeedItem, ...], segment_ids: tuple[str, ...]) -> str:
    if len(segment_ids) > 1:
        return "multi_segment_directional_corridor"
    kinds = {
        _terminal_kind(item.segment_ids, item.segment_matches)
        for item in seed_group
    }
    if len(kinds) == 1:
        return next(iter(kinds))
    if "segment_junc_node" in kinds:
        return "segment_junc_node"
    if "segment_pair_node" in kinds:
        return "segment_pair_node"
    return "mixed_segment_reference"


def _road_roles_for_junction(road: SWSDRoadInput, *, snode_inside: bool) -> tuple[bool, bool]:
    if road.direction in {0, 1}:
        return True, True
    if road.direction == 2:
        return (not snode_inside, snode_inside)
    if road.direction == 3:
        return (snode_inside, not snode_inside)
    return False, False


def _role(*, inbound: bool, outbound: bool) -> str:
    if inbound and outbound:
        return "bidirectional"
    if inbound:
        return "inbound"
    if outbound:
        return "outbound"
    return "none"


def _directional_seed_groups(seed_items: tuple[_SeedItem, ...]) -> tuple[tuple[_SeedItem, ...], ...]:
    angle_items = [item for item in seed_items if item.angle_deg is not None]
    none_items = [item for item in seed_items if item.angle_deg is None]
    bundles = _role_seed_bundles(angle_items)
    groups: list[tuple[_SeedItem, ...]] = []
    used_bundle_ids: set[int] = set()

    for bundle in sorted((item for item in bundles if item["role"] == "bidirectional"), key=_bundle_sort_key):
        used_bundle_ids.add(id(bundle))
        groups.append(tuple(bundle["items"]))

    outbound_bundles = sorted((item for item in bundles if item["role"] == "outbound"), key=_bundle_sort_key)
    inbound_bundles = sorted((item for item in bundles if item["role"] == "inbound"), key=_bundle_sort_key)
    for outbound in outbound_bundles:
        if id(outbound) in used_bundle_ids:
            continue
        candidates = [
            (float(_angular_distance(float(outbound["mean_angle"]), float(inbound["mean_angle"]))), inbound)
            for inbound in inbound_bundles
            if id(inbound) not in used_bundle_ids
            and _angular_distance(float(outbound["mean_angle"]), float(inbound["mean_angle"])) <= SAME_DIRECTION_PAIR_TOLERANCE_DEG
        ]
        if not candidates:
            continue
        selected = min(candidates, key=lambda item: (item[0], _bundle_first_road_id(item[1])))[1]
        groups.append(tuple(list(outbound["items"]) + list(selected["items"])))
        used_bundle_ids.add(id(outbound))
        used_bundle_ids.add(id(selected))

    for outbound in outbound_bundles:
        if id(outbound) in used_bundle_ids:
            continue
        out_angle = float(outbound["mean_angle"])
        next_outbound_delta = min(
            (
                _clockwise_delta(out_angle, float(other["mean_angle"]))
                for other in outbound_bundles
                if other is not outbound and _clockwise_delta(out_angle, float(other["mean_angle"])) > 0.0
            ),
            default=360.0,
        )
        candidates = [
            (_clockwise_delta(out_angle, float(inbound["mean_angle"])), inbound)
            for inbound in inbound_bundles
            if id(inbound) not in used_bundle_ids
            and 0.0 < _clockwise_delta(out_angle, float(inbound["mean_angle"])) <= OUTBOUND_TO_INBOUND_MAX_GAP_DEG
            and _clockwise_delta(out_angle, float(inbound["mean_angle"])) < next_outbound_delta
        ]
        selected = min(candidates, key=lambda item: (item[0], _bundle_first_road_id(item[1])))[1] if candidates else None
        items = list(outbound["items"])
        if selected is not None:
            items.extend(selected["items"])
            used_bundle_ids.add(id(selected))
        groups.append(tuple(items))
        used_bundle_ids.add(id(outbound))

    for inbound in inbound_bundles:
        if id(inbound) not in used_bundle_ids:
            groups.append(tuple(inbound["items"]))
            used_bundle_ids.add(id(inbound))
    for bundle in sorted((item for item in bundles if item["role"] == "none"), key=_bundle_sort_key):
        if id(bundle) not in used_bundle_ids:
            groups.append(tuple(bundle["items"]))
    groups.extend((item,) for item in none_items)
    return tuple(sorted(groups, key=_group_sort_key))


def _role_seed_bundles(seed_items: list[_SeedItem]) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    for item in sorted(seed_items, key=lambda value: (value.role, float(value.angle_deg or 0.0), value.road.road_id)):
        best_index: int | None = None
        best_distance = SAME_ROLE_BUNDLE_TOLERANCE_DEG + 1.0
        for index, bundle in enumerate(bundles):
            if bundle["role"] != item.role:
                continue
            distance = _angular_distance(float(item.angle_deg or 0.0), float(bundle["mean_angle"]))
            if distance <= SAME_ROLE_BUNDLE_TOLERANCE_DEG and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            bundles.append({"items": [item], "role": item.role, "mean_angle": float(item.angle_deg or 0.0)})
        else:
            bundles[best_index]["items"].append(item)
            bundles[best_index]["mean_angle"] = _mean_angle(
                [seed_item.angle_deg for seed_item in bundles[best_index]["items"] if seed_item.angle_deg is not None]
            )
    return bundles


def _road_outward_angle(
    road: SWSDRoadInput,
    geometry: BaseGeometry | None,
    member_nodes: set[str],
) -> float | None:
    if geometry is None:
        return None
    coords = _line_coords(geometry)
    if len(coords) < 2:
        return None
    if road.snodeid in member_nodes and road.enodeid not in member_nodes:
        start, end = coords[0], coords[-1]
    elif road.enodeid in member_nodes and road.snodeid not in member_nodes:
        start, end = coords[-1], coords[0]
    else:
        return None
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return None
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _line_coords(geometry: BaseGeometry) -> list[tuple[float, float]]:
    if isinstance(geometry, LineString):
        return [(float(x), float(y)) for x, y, *_rest in geometry.coords]
    if isinstance(geometry, MultiLineString):
        parts = [part for part in geometry.geoms if not part.is_empty]
        if not parts:
            return []
        longest = max(parts, key=lambda part: float(part.length))
        return [(float(x), float(y)) for x, y, *_rest in longest.coords]
    return []


def _angular_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _clockwise_delta(start_angle: float, end_angle: float) -> float:
    return (end_angle - start_angle) % 360.0


def _mean_angle(angles: list[float]) -> float | None:
    if not angles:
        return None
    x = sum(math.cos(math.radians(angle)) for angle in angles)
    y = sum(math.sin(math.radians(angle)) for angle in angles)
    if abs(x) <= 1e-12 and abs(y) <= 1e-12:
        return angles[0]
    return math.degrees(math.atan2(y, x)) % 360.0


def _bundle_first_road_id(bundle: dict[str, Any]) -> str:
    return str(bundle["items"][0].road.road_id)


def _bundle_sort_key(bundle: dict[str, Any]) -> tuple[float, tuple[int, Any]]:
    return (float(bundle["mean_angle"]), _sort_key(_bundle_first_road_id(bundle)))


def _group_sort_key(group: tuple[_SeedItem, ...]) -> tuple[float, tuple[int, Any]]:
    angle = _mean_angle([item.angle_deg for item in group if item.angle_deg is not None])
    return (float(angle) if angle is not None else 999.0, _sort_key(group[0].road.road_id))


def _sort_key(value: str) -> tuple[int, Any]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)
