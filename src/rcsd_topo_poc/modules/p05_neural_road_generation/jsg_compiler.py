from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_evaluation import evaluate_jsg_case
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    JSGCaseTruth,
    ObjectState,
    split_segment_access,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import (
    materialize_edit_payloads,
    read_vector_payloads,
    write_vector_payloads,
)


def load_r2_edits_by_sample(
    path: Path,
    *,
    expected_sha256: str,
    strict_hashes: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    resolved = path.resolve(strict=True)
    if strict_hashes and sha256_file(resolved) != expected_sha256:
        raise ValueError(f"R2 edit artifact hash mismatch: {resolved}")
    grouped: dict[str, list[dict[str, Any]]] = {}
    with resolved.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            sample_id = str(row.get("sample_id") or "")
            if not sample_id:
                raise ValueError(f"R2 edit row has no sample_id: {resolved}:{line_number}")
            if row.get("label_only") is not True:
                raise ValueError(f"R2 edit row is not label-only: {resolved}:{line_number}")
            grouped.setdefault(sample_id, []).append(row)
    return grouped


def compile_jsg_case(
    case: JSGCaseTruth,
    road_edits: Iterable[dict[str, Any]],
    node_edits: Iterable[dict[str, Any]],
    output_root: Path,
    *,
    strict_hashes: bool = True,
    preverified_shared_artifacts: bool = False,
) -> dict[str, Any]:
    jsg_evaluation = evaluate_jsg_case(case)
    if not jsg_evaluation["passed"]:
        raise ValueError(f"JSG semantic hard gate failed: {case.case_key}")
    carrier = case.carrier_realization
    if not carrier.label_only:
        raise ValueError("JSG carrier realization must be label-only")
    expected_hashes = dict(carrier.artifact_hashes)
    for role, path in (
        ("r2_oracle_manifest", Path(carrier.r2_oracle_run_manifest)),
        ("road_edits", Path(carrier.road_edits_path)),
        ("node_edits", Path(carrier.node_edits_path)),
        ("truth_road", Path(carrier.expected_truth_road)),
        ("truth_node", Path(carrier.expected_truth_node)),
    ):
        resolved = path.resolve(strict=True)
        shared = role in {"r2_oracle_manifest", "road_edits", "node_edits"}
        if strict_hashes and not (shared and preverified_shared_artifacts) and sha256_file(resolved) != expected_hashes.get(role):
            raise ValueError(f"carrier artifact hash mismatch: {role}")

    road_rows = list(road_edits)
    node_rows = list(node_edits)
    for kind, rows in (("Road", road_rows), ("Node", node_rows)):
        if not rows:
            raise ValueError(f"{case.case_key}: no {kind} edits")
        for row in rows:
            if row.get("sample_id") != carrier.r2_case_sample_id:
                raise ValueError(f"{case.case_key}: foreign {kind} edit sample")
            if row.get("label_only") is not True:
                raise ValueError(f"{case.case_key}: non-label-only {kind} edit")

    roads, nodes = materialize_edit_payloads(road_rows, node_rows)
    graph_signature = _payload_signature(roads, nodes)
    carrier_failures, carrier_reference_count = _carrier_failures(case, set(roads), set(nodes))
    _, road_meta = read_vector_payloads(
        Path(carrier.expected_truth_road), source_role="t06_frcsd_road_truth"
    )
    _, node_meta = read_vector_payloads(
        Path(carrier.expected_truth_node), source_role="t06_frcsd_node_truth"
    )
    output_root.mkdir(parents=True, exist_ok=False)
    road_path = output_root / "compiled_road.gpkg"
    node_path = output_root / "compiled_node.gpkg"
    write_vector_payloads(road_path, roads.values(), meta=road_meta)
    write_vector_payloads(node_path, nodes.values(), meta=node_meta)
    evaluation = evaluate_frcsd(
        road_path,
        node_path,
        Path(carrier.expected_truth_road),
        Path(carrier.expected_truth_node),
    )
    road_f1 = float(evaluation.get("road_object", {}).get("f1", 0.0))
    node_f1 = float(evaluation.get("node_object", {}).get("f1", 0.0))
    topology_f1 = float(evaluation.get("directed_topology", {}).get("f1", 0.0))
    attributes = dict(evaluation.get("attributes") or {})
    direction_accuracy = float(attributes.get("direction_accuracy", 0.0))
    source_accuracy = float(attributes.get("source_accuracy", 0.0))
    endpoint_semantic_accuracy = float(attributes.get("endpoint_semantic_accuracy", 0.0))
    crs_compatible = bool(dict(evaluation.get("crs") or {}).get("compatible"))
    hard_failures = list(evaluation.get("hard_failures") or [])
    exact = (
        road_f1 == 1.0
        and node_f1 == 1.0
        and topology_f1 == 1.0
        and direction_accuracy == 1.0
        and source_accuracy == 1.0
        and endpoint_semantic_accuracy == 1.0
        and crs_compatible
        and not hard_failures
        and not carrier_failures
    )
    return {
        "schema_version": "p05-jsg-compiler-result-v1",
        "case_key": case.case_key,
        "r2_case_sample_id": carrier.r2_case_sample_id,
        "road_edit_count": len(road_rows),
        "node_edit_count": len(node_rows),
        "compiled_road_count": len(roads),
        "compiled_node_count": len(nodes),
        "compiled_road_path": str(road_path.resolve()),
        "compiled_node_path": str(node_path.resolve()),
        "compiled_road_sha256": sha256_file(road_path),
        "compiled_node_sha256": sha256_file(node_path),
        "compiled_graph_signature": graph_signature,
        "roadgraph_evaluation": evaluation,
        "road_f1": road_f1,
        "node_f1": node_f1,
        "directed_topology_f1": topology_f1,
        "direction_accuracy": direction_accuracy,
        "source_accuracy": source_accuracy,
        "endpoint_semantic_accuracy": endpoint_semantic_accuracy,
        "crs_compatible": crs_compatible,
        "roadgraph_hard_failure_count": len(hard_failures),
        "carrier_reference_count": carrier_reference_count,
        "carrier_missing_reference_count": len(carrier_failures),
        "carrier_hard_failures": carrier_failures,
        "hard_failure_count": len(hard_failures) + len(carrier_failures),
        "exact": exact,
        "label_only": True,
        "content_repair": False,
        "silent_fix": False,
    }


def _carrier_failures(
    case: JSGCaseTruth,
    road_ids: set[str],
    node_ids: set[str],
) -> tuple[list[dict[str, str]], int]:
    failures: list[dict[str, str]] = []
    reference_count = 0

    def missing(object_type: str, object_id: str, reference: str, message: str) -> None:
        failures.append(
            {
                "code": "missing_carrier_reference",
                "object_type": object_type,
                "object_id": object_id,
                "reference": reference,
                "message": message,
            }
        )

    relations = {(row.junction_id, row.segment_id): row for row in case.junction_segment_relations}
    for segment in case.standard_segments:
        if segment.state is not ObjectState.PUBLISHABLE:
            continue
        reference_count += len(segment.carrier_road_ids)
        for road_id in segment.carrier_road_ids:
            if road_id not in road_ids:
                missing("StandardSegmentUnit", segment.segment_id, road_id, "carrier Road is absent")
    for relation in case.junction_segment_relations:
        if relation.state is not ObjectState.PUBLISHABLE:
            continue
        reference_count += len(relation.access_legs)
        if not set(relation.access_legs) & node_ids:
            missing(
                "JunctionSegmentRelation",
                f"{relation.junction_id}|{relation.segment_id}",
                ",".join(relation.access_legs),
                "no declared access leg exists in compiled Node",
            )
    for connector in case.segment_connectors:
        if connector.state is not ObjectState.PUBLISHABLE:
            continue
        reference_count += len(connector.carrier_road_ids) + 2
        for road_id in connector.carrier_road_ids:
            if road_id not in road_ids:
                missing("SegmentConnector", connector.connector_id, road_id, "carrier Road is absent")
        for access in (connector.source_segment_access, connector.target_segment_access):
            _, access_position = split_segment_access(access)
            if access_position not in node_ids:
                missing("SegmentConnector", connector.connector_id, access_position, "access Node is absent")
    for movement in case.physical_movements:
        if movement.state is not ObjectState.PUBLISHABLE:
            continue
        reference_count += len(movement.carrier_road_ids)
        for road_id in movement.carrier_road_ids:
            if road_id not in road_ids:
                missing("PhysicalMovement", movement.movement_id, road_id, "carrier Road is absent")
        if not movement.carrier_road_ids:
            from_segment, _ = split_segment_access(movement.from_segment_access)
            to_segment, _ = split_segment_access(movement.to_segment_access)
            from_relation = relations.get((movement.junction_id, from_segment))
            to_relation = relations.get((movement.junction_id, to_segment))
            from_legs = set(from_relation.access_legs if from_relation else ()) & node_ids
            to_legs = set(to_relation.access_legs if to_relation else ()) & node_ids
            reference_count += len(from_legs) + len(to_legs)
            if not from_legs & to_legs:
                missing(
                    "PhysicalMovement",
                    movement.movement_id,
                    movement.junction_id,
                    "zero-Road movement has no shared compiled access Node",
                )
    return failures, reference_count


def _payload_signature(
    roads: dict[str, dict[str, Any]], nodes: dict[str, dict[str, Any]]
) -> str:
    payload = {
        "roads": [
            {
                "id": identifier,
                "geometry": roads[identifier].get("geometry"),
                "properties": roads[identifier].get("properties"),
            }
            for identifier in sorted(roads)
        ],
        "nodes": [
            {
                "id": identifier,
                "geometry": nodes[identifier].get("geometry"),
                "properties": nodes[identifier].get("properties"),
            }
            for identifier in sorted(nodes)
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["compile_jsg_case", "load_r2_edits_by_sample"]
