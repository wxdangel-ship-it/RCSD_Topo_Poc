from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

ROAD_SEGMENTID_FIELD = "segmentid"
LEGACY_ROAD_SEGMENTID_FIELDS = ("segment_id", "Segment_id")


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return None if stripped == "" else stripped
    return value


def _normalize_nullable_text(value: Any) -> str | None:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    return str(normalized)


def _coerce_int(value: Any) -> int | None:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    if isinstance(normalized, bool):
        return int(normalized)
    if isinstance(normalized, int):
        return normalized
    if isinstance(normalized, float):
        return int(normalized)
    return int(str(normalized), 10)


def _sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _bit_enabled(value: int | None, bit_index: int) -> bool:
    if value is None:
        return False
    return bool(value & (1 << bit_index))


def _get_road_segmentid(properties: Mapping[str, Any]) -> str | None:
    for field_name in (ROAD_SEGMENTID_FIELD, *LEGACY_ROAD_SEGMENTID_FIELDS):
        if field_name in properties:
            return _normalize_nullable_text(properties.get(field_name))
    return None


@dataclass(frozen=True)
class NeighborFamilySummary:
    family_id: str
    road_count: int
    segment_road_count: int
    residual_road_count: int
    has_in: bool
    has_out: bool

    @property
    def is_segment_family(self) -> bool:
        return self.segment_road_count > 0

    @property
    def is_residual_family(self) -> bool:
        return self.residual_road_count > 0

    @property
    def is_simple_residual_family(self) -> bool:
        return self.is_residual_family and self.road_count == 1


@dataclass(frozen=True)
class MainnodeRetypeTopology:
    total_neighbor_family_count: int
    segment_neighbor_family_count: int
    residual_neighbor_family_count: int
    simple_residual_neighbor_family_count: int
    family_rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class MainnodeRefreshRetypeDecision:
    grade_2: int
    kind_2: int
    applied_rule: str


def _road_flow_flags_for_group(road: Any, member_node_ids: set[str]) -> tuple[bool, bool]:
    touches_snode = str(road.snodeid) in member_node_ids
    touches_enode = str(road.enodeid) in member_node_ids
    if not touches_snode and not touches_enode:
        return False, False

    direction = _coerce_int(getattr(road, "direction", None))
    if direction in {0, 1}:
        return True, True
    if touches_snode and touches_enode:
        return True, True
    if direction == 2:
        return touches_enode, touches_snode
    if direction == 3:
        return touches_snode, touches_enode
    return False, False


def _pick_family_effective_node(
    *,
    family_id: str,
    member_node_ids: Sequence[str],
    node_properties_map: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[str | None, int | None, int | None]:
    if not member_node_ids:
        return None, None, None
    ordered_member_ids = sorted({str(node_id) for node_id in member_node_ids}, key=_sort_key)
    if node_properties_map is None:
        representative_node_id = family_id if family_id in ordered_member_ids else ordered_member_ids[0]
        return representative_node_id, None, None

    if family_id in ordered_member_ids:
        props = node_properties_map.get(family_id, {})
        return family_id, _coerce_int(props.get("grade_2")), _coerce_int(props.get("kind_2"))

    for node_id in ordered_member_ids:
        props = node_properties_map.get(node_id, {})
        grade_2 = _coerce_int(props.get("grade_2"))
        kind_2 = _coerce_int(props.get("kind_2"))
        if grade_2 not in {None, 0} or kind_2 not in {None, 0}:
            return node_id, grade_2, kind_2

    representative_node_id = ordered_member_ids[0]
    props = node_properties_map.get(representative_node_id, {})
    return representative_node_id, _coerce_int(props.get("grade_2")), _coerce_int(props.get("kind_2"))


def summarize_mainnode_retype_topology(
    *,
    member_node_ids: Sequence[str],
    associated_roads: Sequence[Any],
    road_properties_map: Mapping[str, Mapping[str, Any]],
    physical_to_semantic: Mapping[str, str],
    right_turn_formway_bit: int,
    node_properties_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> MainnodeRetypeTopology:
    member_id_set = {str(node_id) for node_id in member_node_ids}
    family_state: dict[str, dict[str, Any]] = {}

    for road in associated_roads:
        road_id = str(road.road_id)
        road_formway = _coerce_int(getattr(road, "formway", None))
        if _bit_enabled(road_formway, right_turn_formway_bit):
            continue

        snodeid = str(road.snodeid)
        enodeid = str(road.enodeid)
        touches_snode = snodeid in member_id_set
        touches_enode = enodeid in member_id_set
        if touches_snode == touches_enode:
            continue

        other_node_id = enodeid if touches_snode else snodeid
        family_id = str(physical_to_semantic.get(other_node_id, other_node_id))
        state = family_state.setdefault(
            family_id,
            {
                "family_id": family_id,
                "road_count": 0,
                "segment_road_count": 0,
                "residual_road_count": 0,
                "has_in": False,
                "has_out": False,
                "_member_node_ids": set(),
            },
        )
        state["road_count"] += 1
        state["_member_node_ids"].add(str(other_node_id))
        if _get_road_segmentid(dict(road_properties_map.get(road_id, {}))) is not None:
            state["segment_road_count"] += 1
        else:
            state["residual_road_count"] += 1

        has_in, has_out = _road_flow_flags_for_group(road, member_id_set)
        state["has_in"] = state["has_in"] or has_in
        state["has_out"] = state["has_out"] or has_out

    for family_id, state in family_state.items():
        representative_node_id, family_grade_2, family_kind_2 = _pick_family_effective_node(
            family_id=family_id,
            member_node_ids=tuple(state.get("_member_node_ids", set())),
            node_properties_map=node_properties_map,
        )
        state["family_representative_node_id"] = representative_node_id
        state["family_grade_2"] = family_grade_2
        state["family_kind_2"] = family_kind_2

    family_summaries = tuple(
        NeighborFamilySummary(
            family_id=str(row["family_id"]),
            road_count=int(row["road_count"]),
            segment_road_count=int(row["segment_road_count"]),
            residual_road_count=int(row["residual_road_count"]),
            has_in=bool(row["has_in"]),
            has_out=bool(row["has_out"]),
        )
        for _, row in sorted(family_state.items(), key=lambda item: _sort_key(item[0]))
    )
    return MainnodeRetypeTopology(
        total_neighbor_family_count=len(family_summaries),
        segment_neighbor_family_count=sum(1 for row in family_summaries if row.is_segment_family),
        residual_neighbor_family_count=sum(1 for row in family_summaries if row.is_residual_family),
        simple_residual_neighbor_family_count=sum(1 for row in family_summaries if row.is_simple_residual_family),
        family_rows=tuple(
            {
                "family_id": row.family_id,
                "road_count": row.road_count,
                "segment_road_count": row.segment_road_count,
                "residual_road_count": row.residual_road_count,
                "has_in": row.has_in,
                "has_out": row.has_out,
                "is_simple_residual_family": row.is_simple_residual_family,
                "family_representative_node_id": family_state[row.family_id].get("family_representative_node_id"),
                "family_grade_2": family_state[row.family_id].get("family_grade_2"),
                "family_kind_2": family_state[row.family_id].get("family_kind_2"),
            }
            for row in family_summaries
        ),
    )


def evaluate_mainnode_refresh_retype(
    *,
    current_grade_2: int | None,
    current_kind_2: int | None,
    topology: MainnodeRetypeTopology,
) -> MainnodeRefreshRetypeDecision | None:
    if current_grade_2 != 1 or current_kind_2 != 4:
        return None
    if topology.total_neighbor_family_count != 3:
        return None
    if topology.segment_neighbor_family_count != 1:
        return None
    if topology.residual_neighbor_family_count != 2:
        return None
    if topology.simple_residual_neighbor_family_count == 2:
        return MainnodeRefreshRetypeDecision(
            grade_2=2,
            kind_2=2048,
            applied_rule="retyped_grade2_kind2048_single_side_family",
        )
    return MainnodeRefreshRetypeDecision(
        grade_2=2,
        kind_2=4,
        applied_rule="retyped_grade2_kind4_mixed_side_family",
    )


def evaluate_mainnode_bootstrap_retype(
    *,
    current_grade_2: int | None,
    current_kind_2: int | None,
    topology: MainnodeRetypeTopology,
) -> MainnodeRefreshRetypeDecision | None:
    if current_grade_2 != 1 or current_kind_2 != 4:
        return None
    if topology.total_neighbor_family_count != 3:
        return None
    if topology.segment_neighbor_family_count != 0:
        return None
    if topology.residual_neighbor_family_count != 3:
        return None

    through_families = [
        row for row in topology.family_rows if bool(row.get("has_in")) and bool(row.get("has_out"))
    ]
    if len(through_families) != 1:
        return None
    through_family = through_families[0]
    if _coerce_int(through_family.get("family_grade_2")) != 1 or _coerce_int(through_family.get("family_kind_2")) != 4:
        return None

    plain_cross_side_count = 0
    t_side_count = 0
    for row in topology.family_rows:
        if row is through_family:
            continue
        has_in = bool(row.get("has_in"))
        has_out = bool(row.get("has_out"))
        road_count = int(row.get("road_count") or 0)
        if road_count != 1:
            return None
        if has_in and not has_out:
            pass
        elif has_out and not has_in:
            pass
        else:
            return None

        family_grade_2 = _coerce_int(row.get("family_grade_2"))
        family_kind_2 = _coerce_int(row.get("family_kind_2"))
        if family_grade_2 == 1 and family_kind_2 == 4:
            plain_cross_side_count += 1
            continue
        if family_kind_2 == 2048 and (family_grade_2 or 0) >= 2:
            t_side_count += 1
            continue
        return None

    if plain_cross_side_count != 1 or t_side_count != 1:
        return None

    return MainnodeRefreshRetypeDecision(
        grade_2=2,
        kind_2=2048,
        applied_rule="bootstrap_retyped_grade2_kind2048_strict_t",
    )
