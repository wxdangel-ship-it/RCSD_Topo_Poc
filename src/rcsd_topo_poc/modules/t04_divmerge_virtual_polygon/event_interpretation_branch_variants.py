from __future__ import annotations

import math
from collections import defaultdict
from itertools import product
from typing import Any

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_geometry_core import (
    CHAIN_CONTINUATION_MAX_TURN_DEG,
    CHAIN_CONTINUATION_MIN_MARGIN_DEG,
    _explode_component_geometries,
    _node_source_kind_2,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    BranchEvidence,
    ParsedNode,
    ParsedRoad,
    _angle_diff_deg,
    _branch_candidate_from_road,
)

from .case_models import T04UnitContext
from .event_interpretation_shared import _ExecutableBranchSet


MAX_COMPLEX_BRANCH_CONTINUATION_HOPS = 6
MAX_COMPLEX_BRANCH_PATH_VARIANTS_PER_SEED = 6
MAX_COMPLEX_BRANCH_SET_VARIANTS = 24


def _road_other_node_id(road: ParsedRoad, node_id: str) -> str | None:
    if str(road.snodeid) == str(node_id):
        return str(road.enodeid)
    if str(road.enodeid) == str(node_id):
        return str(road.snodeid)
    return None


def _road_travel_angle_from_node(road: ParsedRoad, from_node_id: str) -> float | None:
    geometry = road.geometry
    if geometry is None or geometry.is_empty:
        return None
    line = geometry if getattr(geometry, "geom_type", None) == "LineString" else None
    if line is None:
        components = [
            component
            for component in _explode_component_geometries(geometry)
            if getattr(component, "geom_type", None) == "LineString" and not component.is_empty
        ]
        if not components:
            return None
        line = max(components, key=lambda item: float(item.length))
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    if str(road.snodeid) == str(from_node_id):
        anchor = coords[0]
        away = coords[1]
    elif str(road.enodeid) == str(from_node_id):
        anchor = coords[-1]
        away = coords[-2]
    else:
        return None
    dx = float(away[0]) - float(anchor[0])
    dy = float(away[1]) - float(anchor[1])
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return None
    angle_deg = math.degrees(math.atan2(dy, dx))
    while angle_deg < 0.0:
        angle_deg += 360.0
    while angle_deg >= 360.0:
        angle_deg -= 360.0
    return float(angle_deg)


def _same_case_internal_member_node(*, node: ParsedNode | None, mainnodeid: str, representative_node_id: str) -> bool:
    if node is None:
        return False
    if str(node.node_id) == str(representative_node_id):
        return False
    if node.has_evd != "yes" or node.is_anchor != "no":
        return False
    return normalize_id(node.mainnodeid or node.node_id) == normalize_id(mainnodeid)


def _pick_branch_continuation(
    *,
    current_node_id: str,
    previous_node_id: str,
    previous_angle_deg: float,
    adjacent_roads: list[ParsedRoad],
):
    ranked: list[tuple[float, float, str, ParsedRoad, float]] = []
    for road in adjacent_roads:
        next_node_id = _road_other_node_id(road, current_node_id)
        if next_node_id is None or str(next_node_id) == str(previous_node_id):
            continue
        next_angle_deg = _road_travel_angle_from_node(road, current_node_id)
        if next_angle_deg is None:
            continue
        ranked.append(
            (
                float(_angle_diff_deg(previous_angle_deg, next_angle_deg)),
                -float(road.geometry.length) if road.geometry is not None and not road.geometry.is_empty else 0.0,
                str(next_node_id),
                road,
                float(next_angle_deg),
            )
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (float(item[0]), float(item[1]), item[2], str(item[3].road_id)))
    best_gap, _best_len, best_node_id, best_road, best_angle_deg = ranked[0]
    if float(best_gap) > CHAIN_CONTINUATION_MAX_TURN_DEG:
        return None
    if len(ranked) > 1:
        second_gap = float(ranked[1][0])
        if second_gap - float(best_gap) < CHAIN_CONTINUATION_MIN_MARGIN_DEG:
            return None
    return best_node_id, best_road, best_angle_deg


def _complex_branch_seed_rows(
    *,
    unit_context: T04UnitContext,
    filtered_roads: list[ParsedRoad],
):
    representative_node_id = str(unit_context.representative_node.node_id)
    drivezone_union = (
        unit_context.local_context.patch_drivezone_union
        if unit_context.local_context.patch_drivezone_union is not None
        else unit_context.local_context.drivezone_union
    )
    if drivezone_union is None or drivezone_union.is_empty:
        return None, None, None
    adjacency: dict[str, list[ParsedRoad]] = defaultdict(list)
    for road in filtered_roads:
        adjacency[str(road.snodeid)].append(road)
        adjacency[str(road.enodeid)].append(road)
    seed_rows: list[tuple[float, str, ParsedRoad, dict[str, Any]]] = []
    for road in adjacency.get(representative_node_id, []):
        candidate = _branch_candidate_from_road(
            road,
            member_node_ids={representative_node_id},
            drivezone_union=drivezone_union,
        )
        if candidate is None:
            continue
        seed_rows.append((float(candidate["angle_deg"]), str(road.road_id), road, candidate))
    if len(seed_rows) < 2:
        return None, None, None
    seed_rows.sort(key=lambda item: (float(item[0]), item[1]))
    node_lookup = {
        str(node.node_id): node
        for node in [*unit_context.local_context.local_nodes, *unit_context.group_nodes]
    }
    return drivezone_union, adjacency, (tuple(seed_rows), node_lookup)


def _enumerate_complex_branch_paths(
    *,
    seed_road: ParsedRoad,
    seed_angle_deg: float,
    representative_node_id: str,
    mainnodeid: str,
    adjacency: dict[str, list[ParsedRoad]],
    node_lookup: dict[str, ParsedNode],
    allow_same_case_propagation: bool,
    allow_multi_exit_resolution: bool,
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    results: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    seen_states: set[tuple[str, str, tuple[str, ...]]] = set()

    def _walk(
        *,
        previous_node_id: str,
        current_node_id: str | None,
        previous_angle_deg: float,
        road_ids: tuple[str, ...],
        bridge_node_ids: tuple[str, ...],
        hop_count: int,
    ) -> None:
        if current_node_id is None or hop_count >= MAX_COMPLEX_BRANCH_CONTINUATION_HOPS:
            results.append((road_ids, bridge_node_ids))
            return
        state_key = (str(previous_node_id), str(current_node_id), tuple(road_ids))
        if state_key in seen_states:
            return
        seen_states.add(state_key)
        current_node = node_lookup.get(str(current_node_id))
        is_same_case_bridge = _same_case_internal_member_node(
            node=current_node,
            mainnodeid=mainnodeid,
            representative_node_id=representative_node_id,
        )
        if not is_same_case_bridge:
            results.append((road_ids, bridge_node_ids))
            return
        if is_same_case_bridge and not allow_same_case_propagation:
            results.append((road_ids, bridge_node_ids))
            return

        next_rows: list[tuple[int, float, str, ParsedRoad, str, float]] = []
        for road in adjacency.get(str(current_node_id), []):
            next_node_id = _road_other_node_id(road, str(current_node_id))
            if next_node_id is None or str(next_node_id) == str(previous_node_id):
                continue
            next_road_id = str(road.road_id)
            if next_road_id in road_ids:
                continue
            next_angle_deg = _road_travel_angle_from_node(road, str(current_node_id))
            if next_angle_deg is None:
                continue
            next_node = node_lookup.get(str(next_node_id))
            is_same_case_next = _same_case_internal_member_node(
                node=next_node,
                mainnodeid=mainnodeid,
                representative_node_id=representative_node_id,
            )
            next_rows.append(
                (
                    0 if is_same_case_next else 1,
                    float(_angle_diff_deg(previous_angle_deg, next_angle_deg)),
                    next_road_id,
                    road,
                    str(next_node_id),
                    float(next_angle_deg),
                )
            )
        if not next_rows:
            results.append((road_ids, bridge_node_ids))
            return
        external_exit_count = sum(1 for item in next_rows if int(item[0]) == 1)
        if is_same_case_bridge and external_exit_count > 1 and not allow_multi_exit_resolution:
            results.append((road_ids, bridge_node_ids))
            return

        next_rows.sort(key=lambda item: (int(item[0]), float(item[1]), item[2]))
        for is_external_rank, _gap_deg, next_road_id, _road, next_node_id, next_angle_deg in next_rows:
            next_bridge_node_ids = bridge_node_ids
            if is_same_case_bridge:
                next_bridge_node_ids = tuple([*next_bridge_node_ids, str(current_node_id)])
            if int(is_external_rank) == 1:
                results.append((tuple([*road_ids, next_road_id]), next_bridge_node_ids))
                continue
            _walk(
                previous_node_id=str(current_node_id),
                current_node_id=str(next_node_id),
                previous_angle_deg=float(next_angle_deg),
                road_ids=tuple([*road_ids, next_road_id]),
                bridge_node_ids=next_bridge_node_ids,
                hop_count=hop_count + 1,
            )

    initial_current_node_id = _road_other_node_id(seed_road, representative_node_id)
    _walk(
        previous_node_id=representative_node_id,
        current_node_id=initial_current_node_id,
        previous_angle_deg=float(seed_angle_deg),
        road_ids=(str(seed_road.road_id),),
        bridge_node_ids=(),
        hop_count=0,
    )
    deduped: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    seen_paths: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for path in results:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        deduped.append(path)
    deduped.sort(key=lambda item: (len(item[0]), len(item[1]), item[0]))
    return tuple(deduped[:MAX_COMPLEX_BRANCH_PATH_VARIANTS_PER_SEED])


def _build_direct_adjacency_branch_set(
    *,
    unit_context: T04UnitContext,
    filtered_roads: list[ParsedRoad],
) -> _ExecutableBranchSet | None:
    drivezone_union, _adjacency, seed_bundle = _complex_branch_seed_rows(
        unit_context=unit_context,
        filtered_roads=filtered_roads,
    )
    if drivezone_union is None or seed_bundle is None:
        return None
    seed_rows, _node_lookup = seed_bundle
    if len(seed_rows) != 3:
        return None
    road_lookup = {str(road.road_id): road for road in filtered_roads}
    path_selection = tuple(
        ((str(seed_road_id),), ())
        for _seed_angle, seed_road_id, _seed_road, _candidate in seed_rows
    )
    branch_set = _build_executable_branch_set_from_paths(
        representative_node=unit_context.representative_node,
        drivezone_union=drivezone_union,
        seed_rows=seed_rows,
        path_selection=path_selection,
        road_lookup=road_lookup,
    )
    if len(branch_set.event_branch_ids) != 2 or len(branch_set.boundary_branch_ids) != 2:
        return None
    return branch_set


def _build_executable_branch_set_from_paths(
    *,
    representative_node,
    drivezone_union,
    seed_rows: tuple[tuple[float, str, ParsedRoad, dict[str, Any]], ...],
    path_selection: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
    road_lookup: dict[str, ParsedRoad],
    selected_event_branch_ids: tuple[str, ...] = (),
) -> _ExecutableBranchSet:
    road_branches: list[BranchEvidence] = []
    branch_road_memberships: dict[str, tuple[str, ...]] = {}
    branch_bridge_node_ids: dict[str, tuple[str, ...]] = {}
    for index, (_seed_angle, _seed_road_id, _seed_road, candidate) in enumerate(seed_rows, start=1):
        branch_id = f"road_{index}"
        road_ids, bridge_node_ids = path_selection[index - 1]
        road_support_m = 0.0
        for road_id in road_ids:
            road = road_lookup.get(str(road_id))
            if road is None or road.geometry is None or road.geometry.is_empty:
                continue
            road_support_m += float(road.geometry.intersection(drivezone_union).length)
        road_branches.append(
            BranchEvidence(
                branch_id=branch_id,
                angle_deg=float(candidate["angle_deg"]),
                branch_type="road",
                road_ids=list(road_ids),
                road_support_m=round(float(road_support_m), 3),
                has_incoming_support=bool(candidate["has_incoming_support"]),
                has_outgoing_support=bool(candidate["has_outgoing_support"]),
            )
        )
        branch_road_memberships[branch_id] = tuple(road_ids)
        branch_bridge_node_ids[branch_id] = tuple(bridge_node_ids)

    input_branch_ids = tuple(
        str(branch.branch_id)
        for branch in road_branches
        if bool(branch.has_incoming_support)
    )
    output_branch_ids = tuple(
        str(branch.branch_id)
        for branch in road_branches
        if bool(branch.has_outgoing_support)
    )
    source_kind_2 = _node_source_kind_2(representative_node)
    operational_kind_hint: int | None = None
    event_branch_ids: tuple[str, ...] = ()
    boundary_branch_ids: tuple[str, ...] = ()
    if len(input_branch_ids) >= 2 and len(output_branch_ids) == 1:
        operational_kind_hint = 8
        event_branch_ids = tuple(input_branch_ids)
        boundary_branch_ids = tuple(input_branch_ids[:2])
    elif len(output_branch_ids) >= 2 and len(input_branch_ids) == 1:
        operational_kind_hint = 16
        event_branch_ids = tuple(output_branch_ids)
        boundary_branch_ids = tuple(output_branch_ids[:2])
    elif source_kind_2 in {8, 16}:
        operational_kind_hint = int(source_kind_2)
        event_branch_ids = tuple(input_branch_ids if source_kind_2 == 8 else output_branch_ids)
        boundary_branch_ids = tuple(event_branch_ids[:2])
    selected_event_branch_set = {str(branch_id) for branch_id in selected_event_branch_ids if str(branch_id)}
    if len(selected_event_branch_set) >= 2 and event_branch_ids:
        selected_boundary_branch_ids = tuple(
            branch_id for branch_id in event_branch_ids if branch_id in selected_event_branch_set
        )
        if len(selected_boundary_branch_ids) == 2:
            event_branch_ids = selected_boundary_branch_ids
            boundary_branch_ids = selected_boundary_branch_ids

    branch_ids = tuple(str(branch.branch_id) for branch in road_branches)
    return _ExecutableBranchSet(
        road_branches=tuple(road_branches),
        branch_ids=branch_ids,
        main_branch_ids=tuple(branch_ids),
        input_branch_ids=tuple(input_branch_ids),
        output_branch_ids=tuple(output_branch_ids),
        event_branch_ids=tuple(event_branch_ids),
        boundary_branch_ids=tuple(boundary_branch_ids),
        branch_road_memberships=dict(branch_road_memberships),
        branch_bridge_node_ids=dict(branch_bridge_node_ids),
        operational_kind_hint=operational_kind_hint,
    )


def _build_complex_executable_branch_variants(
    *,
    unit_context: T04UnitContext,
    filtered_roads: list[ParsedRoad],
    selected_event_branch_ids: tuple[str, ...] = (),
) -> tuple[_ExecutableBranchSet, ...]:
    representative_node = unit_context.representative_node
    representative_node_id = str(representative_node.node_id)
    mainnodeid = str(unit_context.admission.mainnodeid)
    drivezone_union, adjacency, seed_bundle = _complex_branch_seed_rows(
        unit_context=unit_context,
        filtered_roads=filtered_roads,
    )
    if drivezone_union is None or adjacency is None or seed_bundle is None:
        return ()
    seed_rows, node_lookup = seed_bundle
    road_lookup = {str(road.road_id): road for road in filtered_roads}
    incoming_seed_count = sum(1 for *_rest, candidate in seed_rows if bool(candidate["has_incoming_support"]))
    outgoing_seed_count = sum(1 for *_rest, candidate in seed_rows if bool(candidate["has_outgoing_support"]))
    event_orientation = (
        "incoming"
        if incoming_seed_count >= 2 and outgoing_seed_count == 1
        else ("outgoing" if outgoing_seed_count >= 2 and incoming_seed_count == 1 else None)
    )
    path_options_per_seed: list[tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = []
    for seed_angle, _seed_road_id, seed_road, candidate in seed_rows:
        allow_same_case_propagation = bool(
            event_orientation is None
            or (event_orientation == "incoming" and bool(candidate["has_incoming_support"]))
            or (event_orientation == "outgoing" and bool(candidate["has_outgoing_support"]))
        )
        allow_multi_exit_resolution = bool(
            (event_orientation == "incoming" and bool(candidate["has_incoming_support"]))
            or (event_orientation == "outgoing" and bool(candidate["has_outgoing_support"]))
        )
        path_options = _enumerate_complex_branch_paths(
            seed_road=seed_road,
            seed_angle_deg=float(seed_angle),
            representative_node_id=representative_node_id,
            mainnodeid=mainnodeid,
            adjacency=adjacency,
            node_lookup=node_lookup,
            allow_same_case_propagation=allow_same_case_propagation,
            allow_multi_exit_resolution=allow_multi_exit_resolution,
        )
        if not path_options:
            return ()
        path_options_per_seed.append(path_options)

    variants: list[_ExecutableBranchSet] = []
    seen_memberships: set[tuple[tuple[str, tuple[str, ...]], ...]] = set()
    for combo_index, path_selection in enumerate(product(*path_options_per_seed), start=1):
        if combo_index > MAX_COMPLEX_BRANCH_SET_VARIANTS:
            break
        branch_set = _build_executable_branch_set_from_paths(
            representative_node=representative_node,
            drivezone_union=drivezone_union,
            seed_rows=seed_rows,
            path_selection=tuple(path_selection),
            road_lookup=road_lookup,
            selected_event_branch_ids=tuple(selected_event_branch_ids),
        )
        membership_key = tuple(
            (str(branch_id), tuple(road_ids))
            for branch_id, road_ids in sorted(branch_set.branch_road_memberships.items())
        )
        if membership_key in seen_memberships:
            continue
        seen_memberships.add(membership_key)
        variants.append(branch_set)
    variants.sort(
        key=lambda item: (
            sum(len(road_ids) for road_ids in item.branch_road_memberships.values()),
            sum(len(node_ids) for node_ids in item.branch_bridge_node_ids.values()),
            tuple(
                (str(branch_id), tuple(road_ids))
                for branch_id, road_ids in sorted(item.branch_road_memberships.items())
            ),
        )
    )
    return tuple(variants)
