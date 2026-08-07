from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence


ANCHOR_ARM_FEATURE_DIM = 7
ANCHOR_MEMBER_LOCAL_FEATURE_DIM = 12
ANCHOR_MEMBER_RELATION_DIM = 7
ANCHOR_MEMBER_INCIDENCE_DIM = 4
AnchorArm = tuple[float, int, int]
AnchorMemberKey = tuple[bool, str]
RoadEndpointEvidence = tuple[str, str, int, int]


@dataclass(frozen=True)
class AnchorStructuralEvidence:
    """Truth-free arm sets and exact raw-topology member relations."""

    member_ids: tuple[str, ...]
    swsd_arm_features: tuple[tuple[float, ...], ...]
    member_arm_features: tuple[tuple[tuple[float, ...], ...], ...]
    member_local_features: tuple[tuple[float, ...], ...] = ()
    member_relation_edges: tuple[
        tuple[int, int, tuple[float, ...]],
        ...,
    ] = ()
    member_incidence_edges: tuple[
        tuple[int, int, tuple[float, ...]],
        ...,
    ] = ()


def build_anchor_structural_evidence(
    member_keys: Sequence[AnchorMemberKey],
    *,
    swsd_arms: Sequence[AnchorArm],
    member_arms: Mapping[AnchorMemberKey, Sequence[AnchorArm]],
    road_endpoints: Mapping[str, RoadEndpointEvidence],
    member_local_features: (
        Mapping[AnchorMemberKey, Sequence[float]] | None
    ) = None,
) -> AnchorStructuralEvidence:
    """Encode structure without embedding raw Road/Node identifiers."""
    if not member_keys:
        raise ValueError("anchor structural evidence requires members")
    if len(set(member_keys)) != len(member_keys):
        raise ValueError("anchor structural evidence members are duplicated")
    member_ids = tuple(
        f"{'ROAD' if is_road else 'NODE'}:{member_id}"
        for is_road, member_id in member_keys
    )
    arm_rows = tuple(
        anchor_arm_feature_rows(member_arms.get(key, ()))
        for key in member_keys
    )
    local_rows = (
        tuple(
            tuple(float(value) for value in member_local_features[key])
            for key in member_keys
        )
        if member_local_features is not None
        else ()
    )
    relation_edges: list[tuple[int, int, tuple[float, ...]]] = []
    for left_index, (left_is_road, left_id) in enumerate(member_keys):
        left = road_endpoints.get(left_id) if left_is_road else None
        if left is None:
            continue
        for right_index, (right_is_road, right_id) in enumerate(member_keys):
            if left_index == right_index or not right_is_road:
                continue
            right = road_endpoints.get(right_id)
            if right is None:
                continue
            features = _road_relation_features(left, right)
            if features[0] > 0.5:
                relation_edges.append(
                    (left_index, right_index, features)
                )
    result = AnchorStructuralEvidence(
        member_ids=member_ids,
        swsd_arm_features=anchor_arm_feature_rows(swsd_arms),
        member_arm_features=arm_rows,
        member_local_features=local_rows,
        member_relation_edges=tuple(relation_edges),
    )
    validate_anchor_structural_evidence(result)
    return result


def anchor_arm_feature_rows(
    arms: Sequence[AnchorArm],
) -> tuple[tuple[float, ...], ...]:
    rows: list[tuple[float, ...]] = []
    for bearing, function_class, direction in arms:
        direction_values = tuple(
            float(int(direction) == value) for value in range(4)
        )
        row = (
            math.sin(float(bearing)),
            math.cos(float(bearing)),
            float(function_class) / 8.0,
            *direction_values,
        )
        if len(row) != ANCHOR_ARM_FEATURE_DIM:
            raise AssertionError("anchor arm feature dimension drifted")
        if not all(math.isfinite(value) for value in row):
            raise ValueError("anchor arm feature is not finite")
        rows.append(row)
    return tuple(rows)


def build_member_incidence_edges(
    member_ids: Sequence[str],
    *,
    node_members: Mapping[str, Sequence[str]],
    road_endpoints: Mapping[str, tuple[str, str]],
) -> tuple[tuple[int, int, tuple[float, ...]], ...]:
    """Encode exact raw Node-group/Road endpoint incidence in both directions."""
    parsed = tuple(value.split(":", 1) for value in member_ids)
    result: list[tuple[int, int, tuple[float, ...]]] = []
    for node_index, (node_kind, node_id) in enumerate(parsed):
        if node_kind != "NODE":
            continue
        raw_nodes = set(node_members.get(node_id, ()))
        if not raw_nodes:
            continue
        for road_index, (road_kind, road_id) in enumerate(parsed):
            if road_kind != "ROAD" or road_id not in road_endpoints:
                continue
            start_node_id, end_node_id = road_endpoints[road_id]
            at_start = start_node_id in raw_nodes
            at_end = end_node_id in raw_nodes
            if not (at_start or at_end):
                continue
            result.extend(
                (
                    (
                        node_index,
                        road_index,
                        (1.0, 0.0, float(at_start), float(at_end)),
                    ),
                    (
                        road_index,
                        node_index,
                        (0.0, 1.0, float(at_start), float(at_end)),
                    ),
                )
            )
    return tuple(result)


def validate_anchor_structural_evidence(
    evidence: AnchorStructuralEvidence,
) -> None:
    member_count = len(evidence.member_ids)
    if member_count < 1:
        raise ValueError("anchor structural evidence requires members")
    if len(evidence.member_arm_features) != member_count:
        raise ValueError("anchor member IDs/arm features differ")
    if evidence.member_local_features and (
        len(evidence.member_local_features) != member_count
        or any(
            len(row) != ANCHOR_MEMBER_LOCAL_FEATURE_DIM
            for row in evidence.member_local_features
        )
    ):
        raise ValueError("anchor member local feature shape differs")
    if len(set(evidence.member_ids)) != member_count:
        raise ValueError("anchor structural evidence member IDs repeat")
    arm_rows = [
        *evidence.swsd_arm_features,
        *(
            row
            for member_rows in evidence.member_arm_features
            for row in member_rows
        ),
    ]
    if any(len(row) != ANCHOR_ARM_FEATURE_DIM for row in arm_rows):
        raise ValueError("anchor structural arm dimension differs")
    if any(
        not math.isfinite(value)
        for row in arm_rows
        for value in row
    ):
        raise ValueError("anchor structural arm feature is not finite")
    if any(
        not math.isfinite(value)
        for row in evidence.member_local_features
        for value in row
    ):
        raise ValueError("anchor member local feature is not finite")
    seen_edges: set[tuple[int, int]] = set()
    for left, right, features in evidence.member_relation_edges:
        if not 0 <= left < member_count or not 0 <= right < member_count:
            raise ValueError("anchor member relation index is invalid")
        if left == right:
            raise ValueError("anchor member relation cannot be self-edge")
        if (left, right) in seen_edges:
            raise ValueError("anchor member relation edge repeats")
        seen_edges.add((left, right))
        if len(features) != ANCHOR_MEMBER_RELATION_DIM:
            raise ValueError("anchor member relation dimension differs")
        if not all(math.isfinite(value) for value in features):
            raise ValueError("anchor member relation feature is not finite")
    seen_incidence: set[tuple[int, int]] = set()
    for left, right, features in evidence.member_incidence_edges:
        if not 0 <= left < member_count or not 0 <= right < member_count:
            raise ValueError("anchor member incidence index is invalid")
        if left == right or (left, right) in seen_incidence:
            raise ValueError("anchor member incidence repeats or self-links")
        seen_incidence.add((left, right))
        if len(features) != ANCHOR_MEMBER_INCIDENCE_DIM:
            raise ValueError("anchor member incidence dimension differs")
        if not all(math.isfinite(value) for value in features):
            raise ValueError("anchor member incidence feature is not finite")


def _road_relation_features(
    left: RoadEndpointEvidence,
    right: RoadEndpointEvidence,
) -> tuple[float, ...]:
    left_start, left_end, left_direction, left_fc = left
    right_start, right_end, right_direction, right_fc = right
    same_start = left_start == right_start
    start_to_end = left_start == right_end
    end_to_start = left_end == right_start
    same_end = left_end == right_end
    share_endpoint = same_start or start_to_end or end_to_start or same_end
    return (
        float(share_endpoint),
        float(same_start),
        float(start_to_end),
        float(end_to_start),
        float(same_end),
        float(int(left_direction) == int(right_direction)),
        max(0.0, 1.0 - abs(int(left_fc) - int(right_fc)) / 8.0),
    )


__all__ = [
    "ANCHOR_ARM_FEATURE_DIM",
    "ANCHOR_MEMBER_LOCAL_FEATURE_DIM",
    "ANCHOR_MEMBER_INCIDENCE_DIM",
    "ANCHOR_MEMBER_RELATION_DIM",
    "AnchorArm",
    "AnchorMemberKey",
    "AnchorStructuralEvidence",
    "RoadEndpointEvidence",
    "anchor_arm_feature_rows",
    "build_member_incidence_edges",
    "build_anchor_structural_evidence",
    "validate_anchor_structural_evidence",
]
