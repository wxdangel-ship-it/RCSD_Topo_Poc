from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    DirectionRole,
    JSGCaseTruth,
    JunctionType,
    ObjectState,
    StructuralRole,
    split_segment_access,
)


def evaluate_jsg_case(case: JSGCaseTruth) -> dict[str, Any]:
    hard_failures: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []

    def fail(code: str, object_type: str, object_id: str, message: str) -> None:
        hard_failures.append(
            {"code": code, "object_type": object_type, "object_id": object_id, "message": message}
        )

    def review(code: str, object_type: str, object_id: str, message: str) -> None:
        reviews.append(
            {"code": code, "object_type": object_type, "object_id": object_id, "message": message}
        )

    if not case.crs:
        fail("missing_crs", "JSGCaseTruth", case.case_key, "canonical JSG truth has no CRS")
    if not case.label_only:
        fail("truth_not_label_only", "JSGCaseTruth", case.case_key, "P0 truth must be label-only")
    if case.content_repair:
        fail("content_repair", "JSGCaseTruth", case.case_key, "content repair must be false")
    if case.silent_fix:
        fail("silent_fix", "JSGCaseTruth", case.case_key, "silent fix must be false")
    if not case.carrier_realization.label_only:
        fail("carrier_not_label_only", "CarrierRealization", case.case_key, "carrier must be label-only")

    junctions = _unique_index(
        ((row.junction_id, row) for row in case.junction_units),
        object_type="JunctionUnit",
        fail=fail,
    )
    segments = _unique_index(
        ((row.segment_id, row) for row in case.standard_segments),
        object_type="StandardSegmentUnit",
        fail=fail,
    )
    connectors = _unique_index(
        ((row.connector_id, row) for row in case.segment_connectors),
        object_type="SegmentConnector",
        fail=fail,
    )
    _unique_index(
        ((row.movement_id, row) for row in case.physical_movements),
        object_type="PhysicalMovement",
        fail=fail,
    )

    relation_keys: set[tuple[str, str, str]] = set()
    through_by_junction: dict[str, list[Any]] = defaultdict(list)
    relation_lookup: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for relation in case.junction_segment_relations:
        key = (relation.junction_id, relation.segment_id, relation.structural_role.value)
        if key in relation_keys:
            fail("duplicate_relation", "JunctionSegmentRelation", "|".join(key), "duplicate relation")
        relation_keys.add(key)
        relation_lookup[(relation.junction_id, relation.segment_id)].append(relation)
        if relation.junction_id not in junctions:
            fail(
                "missing_junction_reference",
                "JunctionSegmentRelation",
                "|".join(key),
                relation.junction_id,
            )
        if relation.segment_id not in segments:
            fail(
                "missing_segment_reference",
                "JunctionSegmentRelation",
                "|".join(key),
                relation.segment_id,
            )
        if relation.structural_role is StructuralRole.THROUGH:
            through_by_junction[relation.junction_id].append(relation)
            junction = junctions.get(relation.junction_id)
            if junction and junction.junction_type is JunctionType.ROUNDABOUT:
                fail(
                    "roundabout_not_truncated",
                    "JunctionSegmentRelation",
                    "|".join(key),
                    "roundabout cannot publish THROUGH relation",
                )
        if relation.direction_role is DirectionRole.UNKNOWN:
            review(
                "unknown_direction_role",
                "JunctionSegmentRelation",
                "|".join(key),
                "carrier did not prove ENTER/EXIT/BOTH",
            )
        if relation.state is not ObjectState.PUBLISHABLE:
            review("relation_review", "JunctionSegmentRelation", "|".join(key), relation.state.value)

    for junction_id, rows in through_by_junction.items():
        publishable = [row for row in rows if row.state is ObjectState.PUBLISHABLE]
        if len(publishable) > 1:
            fail(
                "multiple_published_through",
                "JunctionUnit",
                junction_id,
                f"{len(publishable)} publishable THROUGH relations",
            )
        if len(rows) > 1 and any(row.state is ObjectState.PUBLISHABLE for row in rows):
            fail(
                "multi_through_auto_selected",
                "JunctionUnit",
                junction_id,
                "conflicting THROUGH evidence must all remain REVIEW",
            )

    for segment in case.standard_segments:
        if len(segment.endpoint_positions) != 2:
            fail(
                "segment_endpoint_cardinality",
                "StandardSegmentUnit",
                segment.segment_id,
                f"expected 2 endpoints, got {len(segment.endpoint_positions)}",
            )
            continue
        same_endpoint = segment.endpoint_positions[0] == segment.endpoint_positions[1]
        if same_endpoint != segment.explicit_loop:
            fail(
                "loop_evidence_mismatch",
                "StandardSegmentUnit",
                segment.segment_id,
                "same endpoints and explicit_loop must agree",
            )
        for junction_id in segment.endpoint_positions + segment.attached_junctions:
            if junction_id not in junctions:
                fail(
                    "missing_segment_junction",
                    "StandardSegmentUnit",
                    segment.segment_id,
                    junction_id,
                )
        for junction_id in segment.endpoint_positions:
            if not any(
                row.structural_role is StructuralRole.ENDPOINT
                for row in relation_lookup.get((junction_id, segment.segment_id), [])
            ):
                fail(
                    "missing_endpoint_relation",
                    "StandardSegmentUnit",
                    segment.segment_id,
                    junction_id,
                )
        for junction_id in segment.attached_junctions:
            if not any(
                row.structural_role is StructuralRole.THROUGH
                for row in relation_lookup.get((junction_id, segment.segment_id), [])
            ):
                fail(
                    "missing_through_relation",
                    "StandardSegmentUnit",
                    segment.segment_id,
                    junction_id,
                )

    for connector in connectors.values():
        if connector.direction != "FORWARD":
            fail(
                "connector_direction",
                "SegmentConnector",
                connector.connector_id,
                "SegmentConnector must be FORWARD",
            )
        if connector.state is ObjectState.PUBLISHABLE:
            for name, access in (
                ("source_segment_access", connector.source_segment_access),
                ("target_segment_access", connector.target_segment_access),
            ):
                try:
                    segment_id, access_position = split_segment_access(access)
                except ValueError as error:
                    fail("invalid_connector_access", "SegmentConnector", connector.connector_id, str(error))
                    continue
                if segment_id not in segments or not access_position:
                    fail(
                        "connector_access_reference",
                        "SegmentConnector",
                        connector.connector_id,
                        f"{name}={access}",
                    )
        else:
            review("connector_review", "SegmentConnector", connector.connector_id, connector.state.value)

    for movement in case.physical_movements:
        if movement.junction_id not in junctions:
            fail(
                "movement_missing_junction",
                "PhysicalMovement",
                movement.movement_id,
                movement.junction_id,
            )
        if not movement.physical_reachable:
            fail(
                "movement_not_reachable",
                "PhysicalMovement",
                movement.movement_id,
                "truth movement must be physically reachable",
            )
        for access in (movement.from_segment_access, movement.to_segment_access):
            try:
                segment_id, junction_id = split_segment_access(access)
            except ValueError as error:
                fail("invalid_movement_access", "PhysicalMovement", movement.movement_id, str(error))
                continue
            if segment_id not in segments or junction_id != movement.junction_id:
                fail(
                    "movement_access_reference",
                    "PhysicalMovement",
                    movement.movement_id,
                    access,
                )

    roundtrip = JSGCaseTruth.from_dict(case.to_dict())
    roundtrip_exact = roundtrip.semantic_signature() == case.semantic_signature()
    if not roundtrip_exact:
        fail("canonical_roundtrip", "JSGCaseTruth", case.case_key, "semantic signature changed")

    state_counts = Counter(row.state.value for row in case.junction_units)
    state_counts.update(row.state.value for row in case.standard_segments)
    state_counts.update(row.state.value for row in case.junction_segment_relations)
    state_counts.update(row.state.value for row in case.physical_movements)
    state_counts.update(row.state.value for row in case.segment_connectors)
    return {
        "schema_version": "p05-jsg-evaluation-v1",
        "case_key": case.case_key,
        "semantic_signature": case.semantic_signature(),
        "provenance_signature": case.provenance_signature(),
        "canonical_roundtrip_exact": roundtrip_exact,
        "object_counts": {
            "junction": len(case.junction_units),
            "standard_segment": len(case.standard_segments),
            "relation": len(case.junction_segment_relations),
            "physical_movement": len(case.physical_movements),
            "segment_connector": len(case.segment_connectors),
            "terminal": sum(row.junction_type.value.startswith("TERMINAL_") for row in case.junction_units),
            "loop": sum(row.explicit_loop for row in case.standard_segments),
        },
        "state_counts": dict(sorted(state_counts.items())),
        "through_conflict_junction_count": sum(len(rows) > 1 for rows in through_by_junction.values()),
        "multi_through_auto_selected_count": sum(
            len(rows) > 1 and any(row.state is ObjectState.PUBLISHABLE for row in rows)
            for rows in through_by_junction.values()
        ),
        "review_count": len(reviews),
        "reviews": reviews,
        "hard_failure_count": len(hard_failures),
        "hard_failures": hard_failures,
        "passed": not hard_failures,
        "content_repair": False,
        "silent_fix": False,
    }


def _unique_index(rows: Any, *, object_type: str, fail: Any) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for identifier, row in rows:
        if not identifier:
            fail("empty_id", object_type, "", "object ID must not be empty")
            continue
        if identifier in output:
            fail("duplicate_id", object_type, identifier, "object ID must be unique")
            continue
        output[identifier] = row
    return output


__all__ = ["evaluate_jsg_case"]
