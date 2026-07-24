from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import fiona
from pyproj import CRS

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    CarrierRealization,
    DirectionRole,
    DirectionStructure,
    EvidenceRef,
    JSGAnomaly,
    JSGCaseTruth,
    JSGP0Config,
    JunctionSegmentRelation,
    JunctionType,
    JunctionUnit,
    ObjectState,
    PhysicalMovement,
    SegmentConnector,
    StandardSegmentUnit,
    StructuralRole,
    segment_access,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import read_vector_payloads
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


SEMANTIC_JUNCTION_KINDS = {4, 8, 16, 64, 128, 2048}
COMPLEX_JUNCTION_KINDS = {8, 16, 128}
FORWARD_DIRECTIONS = {0, 1, 2}
REVERSE_DIRECTIONS = {0, 1, 3}


@dataclass(frozen=True)
class JSGInputCase:
    sample_id: str
    family: str
    business_id: str
    fold: int
    source_manifest: Path
    t01_segment: Path
    t01_nodes: Path
    t01_roads: Path
    t05_relation: Path
    t06_segment_relation: Path
    truth_road: Path
    truth_node: Path
    source_hashes: tuple[tuple[str, str], ...]
    carrier_realization: CarrierRealization

    @property
    def case_key(self) -> str:
        return f"{self.family}:{self.business_id}"


def load_jsg_input_cases(config: JSGP0Config) -> list[JSGInputCase]:
    oracle_root = normalize_runtime_path(config.r2_oracle_run_root).resolve(strict=True)
    oracle_manifest_path = oracle_root / "p05_r2_oracle_manifest.json"
    oracle_manifest = _read_json(oracle_manifest_path)
    if oracle_manifest.get("schema_version") != "p05-r2-oracle-manifest-v1":
        raise ValueError("invalid R2 oracle manifest")
    if oracle_manifest.get("status") != "gate1_passed" or oracle_manifest.get("silent_fix") is not False:
        raise ValueError("R2 oracle must be gate1_passed with silent_fix=false")
    outputs = dict(oracle_manifest.get("outputs") or {})
    case_index_path = _verified_output(outputs, "case_index", strict_hashes=config.strict_hashes)
    road_edits_path = _verified_output(outputs, "road_edits", strict_hashes=config.strict_hashes)
    node_edits_path = _verified_output(outputs, "node_edits", strict_hashes=config.strict_hashes)

    dataset_manifest_path = normalize_runtime_path(
        str(oracle_manifest.get("m2r_dataset_manifest_path") or "")
    ).resolve(strict=True)
    if config.strict_hashes:
        expected = str(oracle_manifest.get("m2r_dataset_manifest_sha256") or "")
        if sha256_file(dataset_manifest_path) != expected:
            raise ValueError("M2R dataset manifest differs from R2 oracle lineage")
    dataset_manifest = _read_json(dataset_manifest_path)
    artifact_path = _verified_output(
        dict(dataset_manifest.get("outputs") or {}), "input_artifacts", strict_hashes=config.strict_hashes
    )

    artifacts: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in _read_csv(artifact_path):
        artifacts[row["sample_id"]][row["role"]] = row
    pto_manifest_path, pto_lineage = _load_pto_lineage(config)

    poc_root = normalize_runtime_path(config.poc_data_root).resolve(strict=True)
    if config.enforce_poc_scope and poc_root != Path(r"E:\TestData\POC_Data").resolve(strict=True):
        raise ValueError(f"formal JSG-P0 scope must be E:\\TestData\\POC_Data, got {poc_root}")

    cases: list[JSGInputCase] = []
    seen_case_keys: set[str] = set()
    for row in _read_csv(case_index_path):
        sample_id = row["sample_id"]
        family = row["family"]
        business_id = row["business_id"]
        if business_id in set(config.excluded_business_ids):
            raise ValueError(f"excluded Case appears in R2 scope: {family}/{business_id}")
        case_key = f"{family}:{business_id}"
        if case_key in seen_case_keys:
            raise ValueError(f"duplicate family/business Case: {case_key}")
        seen_case_keys.add(case_key)
        if config.enforce_poc_scope and not (poc_root / family / business_id).exists():
            raise ValueError(f"Case is outside allowed POC scope: {family}/{business_id}")
        roles = artifacts[sample_id]
        required = {"t01_segment", "t01_roads", "t05_relation_truth", "t06_segment_relation_truth", "t06_frcsd_road_truth"}
        missing = sorted(required - set(roles))
        if missing:
            raise ValueError(f"{sample_id}: missing JSG input roles {missing}")
        role_paths: dict[str, Path] = {}
        source_hashes: dict[str, str] = {
            "r2_oracle_manifest": sha256_file(oracle_manifest_path),
            "m2r_dataset_manifest": sha256_file(dataset_manifest_path),
        }
        for role in sorted(required):
            role_path = normalize_runtime_path(roles[role]["path"]).resolve(strict=True)
            digest = sha256_file(role_path)
            if config.strict_hashes and digest != roles[role]["sha256"]:
                raise ValueError(f"{sample_id}:{role}: artifact hash mismatch")
            role_paths[role] = role_path
            source_hashes[role] = digest
        carrier_truth_road = role_paths["t06_frcsd_road_truth"]
        carrier_truth_node = normalize_runtime_path(row["truth_node_path"]).resolve(strict=True)
        if pto_manifest_path is not None:
            replay_roles = pto_lineage.get((family, business_id), {})
            replay_required = {
                "t01_roads",
                "t05_intersection_match_all",
                "t06_frcsd_road",
                "t06_frcsd_node",
            }
            replay_missing = sorted(replay_required - set(replay_roles))
            if replay_missing:
                raise ValueError(f"{case_key}: PTO lineage missing roles {replay_missing}")
            t01_roads = replay_roles["t01_roads"]
            t01_segment = _resolve_existing(t01_roads.parent / "segment.gpkg")
            t01_nodes = _resolve_existing(t01_roads.parent / "nodes.gpkg")
            truth_road = carrier_truth_road
            truth_node = carrier_truth_node
            t06_segment_relation = role_paths["t06_segment_relation_truth"]
            source_manifest = pto_manifest_path
            source_hashes.update(
                {
                    "pto_candidate_manifest": sha256_file(pto_manifest_path),
                    "t01_segment": sha256_file(t01_segment),
                    "t01_nodes": sha256_file(t01_nodes),
                    "t01_roads": sha256_file(t01_roads),
                    "t05_relation_truth": sha256_file(replay_roles["t05_intersection_match_all"]),
                    "t06_segment_relation_truth": sha256_file(t06_segment_relation),
                    "t06_frcsd_road_truth": sha256_file(truth_road),
                    "t06_frcsd_node_truth": sha256_file(truth_node),
                    "pto_replay_t06_frcsd_road": sha256_file(replay_roles["t06_frcsd_road"]),
                    "pto_replay_t06_frcsd_node": sha256_file(replay_roles["t06_frcsd_node"]),
                }
            )
            t05_relation = replay_roles["t05_intersection_match_all"]
        else:
            t01_segment = role_paths["t01_segment"]
            t01_roads = role_paths["t01_roads"]
            t01_nodes = _resolve_existing(t01_roads.parent / "nodes.gpkg")
            truth_road = role_paths["t06_frcsd_road_truth"]
            truth_node = carrier_truth_node
            t06_segment_relation = role_paths["t06_segment_relation_truth"]
            t05_relation = role_paths["t05_relation_truth"]
            source_manifest = dataset_manifest_path
            source_hashes["t01_nodes"] = sha256_file(t01_nodes)
            source_hashes["t06_frcsd_node_truth"] = sha256_file(truth_node)
        source_hashes["road_edits"] = sha256_file(road_edits_path)
        source_hashes["node_edits"] = sha256_file(node_edits_path)
        carrier = CarrierRealization(
            r2_oracle_run_manifest=str(oracle_manifest_path),
            r2_case_sample_id=sample_id,
            road_edits_path=str(road_edits_path),
            node_edits_path=str(node_edits_path),
            expected_truth_road=str(carrier_truth_road),
            expected_truth_node=str(carrier_truth_node),
            artifact_hashes=tuple(
                sorted(
                    {
                        "r2_oracle_manifest": source_hashes["r2_oracle_manifest"],
                        "road_edits": source_hashes["road_edits"],
                        "node_edits": source_hashes["node_edits"],
                        "truth_road": sha256_file(carrier_truth_road),
                        "truth_node": sha256_file(carrier_truth_node),
                    }.items()
                )
            ),
        )
        cases.append(
            JSGInputCase(
                sample_id=sample_id,
                family=family,
                business_id=business_id,
                fold=int(row["fold"]),
                source_manifest=source_manifest,
                t01_segment=t01_segment,
                t01_nodes=t01_nodes,
                t01_roads=t01_roads,
                t05_relation=t05_relation,
                t06_segment_relation=t06_segment_relation,
                truth_road=truth_road,
                truth_node=truth_node,
                source_hashes=tuple(sorted(source_hashes.items())),
                carrier_realization=carrier,
            )
        )
    if len(cases) != config.expected_case_count:
        raise ValueError(f"JSG-P0 requires {config.expected_case_count} cases, got {len(cases)}")
    return sorted(cases, key=lambda item: (item.family, item.business_id, item.sample_id))


def _load_pto_lineage(
    config: JSGP0Config,
) -> tuple[Path | None, dict[tuple[str, str], dict[str, Path]]]:
    if config.pto_candidate_run_root is None:
        return None, {}
    root = normalize_runtime_path(config.pto_candidate_run_root).resolve(strict=True)
    manifest_path = root / "p05_pto_candidate_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-pto-candidate-manifest-v1":
        raise ValueError("invalid PTO candidate manifest")
    if manifest.get("status") != "candidate_scope_passed" or manifest.get("silent_fix") is not False:
        raise ValueError("PTO candidate run must be candidate_scope_passed with silent_fix=false")
    if int(manifest.get("truth_input_count", -1)) != 0 or int(
        manifest.get("truth_derived_candidate_count", -1)
    ) != 0:
        raise ValueError("PTO candidate lineage contains truth leakage")
    if int(dict(manifest.get("parameters") or {}).get("expected_case_count", -1)) != config.expected_case_count:
        raise ValueError("PTO candidate Case scope differs from JSG-P0 scope")
    lineage_path = _verified_output(
        dict(manifest.get("outputs") or {}), "lineage", strict_hashes=config.strict_hashes
    )
    lineage: dict[tuple[str, str], dict[str, Path]] = defaultdict(dict)
    for row in _read_csv(lineage_path):
        path = normalize_runtime_path(row["path"]).resolve(strict=True)
        if config.strict_hashes and sha256_file(path) != row["sha256"]:
            raise ValueError(f"PTO lineage artifact hash mismatch: {row['family']}:{row['business_id']}:{row['role']}")
        lineage[(row["family"], row["business_id"])][row["role"]] = path
    return manifest_path, lineage


def build_jsg_case_truth(input_case: JSGInputCase) -> JSGCaseTruth:
    segment_rows, segment_crs = _read_properties(input_case.t01_segment)
    node_rows, node_crs = _read_properties(input_case.t01_nodes)
    t01_road_payloads, t01_road_meta = read_vector_payloads(input_case.t01_roads, source_role="t01_roads")
    truth_roads, truth_road_meta = read_vector_payloads(input_case.truth_road, source_role="t06_frcsd_road_truth")
    truth_nodes, truth_node_meta = read_vector_payloads(input_case.truth_node, source_role="t06_frcsd_node_truth")
    truth_node_ids = set(truth_nodes)
    relation_rows, relation_crs = _read_properties(input_case.t06_segment_relation)
    crs_values = {
        _canonical_crs(segment_crs),
        _canonical_crs(node_crs),
        _canonical_crs(str(t01_road_meta.get("crs_wkt") or "")),
        _canonical_crs(str(truth_road_meta.get("crs_wkt") or "")),
        _canonical_crs(str(truth_node_meta.get("crs_wkt") or "")),
        _canonical_crs(relation_crs),
    }
    crs_values.discard("")
    if len(crs_values) != 1:
        raise ValueError(f"{input_case.case_key}: CRS mismatch {sorted(crs_values)}")
    crs = next(iter(crs_values))

    segment_evidence = EvidenceRef(
        role="t01_segment",
        path=str(input_case.t01_segment),
        sha256=dict(input_case.source_hashes)["t01_segment"],
    )
    relation_evidence = EvidenceRef(
        role="t06_segment_relation_truth",
        path=str(input_case.t06_segment_relation),
        sha256=dict(input_case.source_hashes)["t06_segment_relation_truth"],
    )
    t01_road_evidence = EvidenceRef(
        role="t01_roads",
        path=str(input_case.t01_roads),
        sha256=dict(input_case.source_hashes)["t01_roads"],
    )
    road_evidence = EvidenceRef(
        role="t06_frcsd_road_truth",
        path=str(input_case.truth_road),
        sha256=dict(input_case.source_hashes)["t06_frcsd_road_truth"],
    )

    relation_by_segment: dict[str, dict[str, Any]] = {}
    anomalies: list[JSGAnomaly] = []
    for row in relation_rows:
        segment_id = _text(row.get("swsd_segment_id"))
        if not segment_id:
            anomalies.append(JSGAnomaly("empty_segment_relation_id", "CarrierRelation", "", "missing swsd_segment_id", "FAIL"))
            continue
        if segment_id in relation_by_segment:
            anomalies.append(JSGAnomaly("duplicate_segment_relation", "CarrierRelation", segment_id, "duplicate row", "FAIL"))
            continue
        relation_by_segment[segment_id] = row

    parsed_segments: dict[str, dict[str, Any]] = {}
    connector_rows: dict[str, dict[str, Any]] = {}
    for row in segment_rows:
        segment_id = _text(row.get("id"))
        pair_nodes = tuple(_string_list(row.get("pair_nodes")))
        junc_nodes = tuple(_string_list(row.get("junc_nodes")))
        record = {
            "segment_id": segment_id,
            "pair_nodes": pair_nodes,
            "junc_nodes": junc_nodes,
            "road_ids": tuple(_string_list(row.get("roads"))),
            "sgrade": _text(row.get("sgrade")),
            "segment_type": _text(row.get("segment_type")) or "normal",
        }
        if record["segment_type"] == "advance_right":
            connector_rows[segment_id] = record
        else:
            parsed_segments[segment_id] = record

    node_index, node_members = _semantic_node_index(node_rows)
    terminal_evidence, data_boundary_evidence = _terminal_evidence(t01_road_payloads, truth_roads)
    directed_edges = _directed_road_edges(truth_roads)
    final_node_closure = _final_node_closure(truth_nodes)

    carrier_by_segment: dict[str, dict[str, Any]] = {}
    for segment_id in set(parsed_segments) | set(connector_rows):
        raw = relation_by_segment.get(segment_id)
        if raw is None:
            carrier_by_segment[segment_id] = {
                "road_ids": (),
                "node_map": {},
                "special_road_ids": (),
                "connectivity_road_ids": (),
                "raw": {},
            }
            anomalies.append(
                JSGAnomaly(
                    "missing_carrier_relation",
                    "StandardSegmentUnit" if segment_id in parsed_segments else "SegmentConnector",
                    segment_id,
                    "T06 segment relation row not found",
                )
            )
            continue
        node_map: dict[str, tuple[str, ...]] = {}
        for item in _json_list(raw.get("swsd_to_frcsd_node_map")):
            if not isinstance(item, Mapping):
                continue
            node_map[_text(item.get("swsd_node_id"))] = tuple(
                _text(value) for value in item.get("frcsd_node_ids") or [] if _text(value)
            )
        direct_road_ids = {
            road_id for road_id in _string_list(raw.get("frcsd_road_ids")) if road_id in truth_roads
        }
        if segment_id in parsed_segments:
            direct_road_ids.update(
                road_id
                for road_id in _string_list(raw.get("external_retained_swsd_carrier_ids"))
                if road_id in truth_roads
            )
            direct_road_ids.update(
                road_id
                for road_id in _string_list(raw.get("retained_detached_swsd_road_ids"))
                if road_id in truth_roads
            )
        carrier_by_segment[segment_id] = {
            "road_ids": tuple(sorted(direct_road_ids)),
            "node_map": node_map,
            "special_road_ids": tuple(
                road_id
                for road_id in _string_list(raw.get("related_special_junction_internal_road_ids"))
                if road_id in truth_roads
            ),
            "connectivity_road_ids": tuple(
                road_id
                for road_id in _string_list(raw.get("related_connectivity_road_ids"))
                if road_id in truth_roads
            ),
            "raw": raw,
        }

    through_segments: dict[str, list[str]] = defaultdict(list)
    incident_segments: dict[str, list[str]] = defaultdict(list)
    access_roles: dict[tuple[str, str], DirectionRole] = {}
    access_nodes: dict[tuple[str, str], tuple[str, ...]] = {}
    for segment_id, record in parsed_segments.items():
        carrier = carrier_by_segment[segment_id]
        for junction_id in record["pair_nodes"]:
            incident_segments[junction_id].append(segment_id)
        for junction_id in record["junc_nodes"]:
            incident_segments[junction_id].append(segment_id)
            through_segments[junction_id].append(segment_id)
        for junction_id in record["pair_nodes"] + record["junc_nodes"]:
            mapped = final_node_closure({junction_id, *carrier["node_map"].get(junction_id, ())})
            access_nodes[(segment_id, junction_id)] = mapped
            role = _direction_role(
                carrier["road_ids"], mapped, truth_roads
            )
            if role is DirectionRole.UNKNOWN:
                role = _direction_role(
                    record["road_ids"],
                    _t01_access_nodes(junction_id, node_index, node_members),
                    t01_road_payloads,
                )
            access_roles[(segment_id, junction_id)] = role

    junction_ids = sorted(incident_segments)
    junction_units: list[JunctionUnit] = []
    for junction_id in junction_ids:
        kinds, grades = _node_semantics(junction_id, node_index, node_members)
        is_endpoint_only = junction_id not in through_segments
        if 64 in kinds:
            junction_type = JunctionType.ROUNDABOUT
        elif kinds & COMPLEX_JUNCTION_KINDS:
            junction_type = JunctionType.COMPLEX_DIVMERGE
        elif kinds & SEMANTIC_JUNCTION_KINDS:
            junction_type = JunctionType.NORMAL
        elif junction_id in terminal_evidence:
            junction_type = JunctionType.TERMINAL_DEAD_END
        elif junction_id in data_boundary_evidence:
            junction_type = JunctionType.TERMINAL_DATA_BOUNDARY
        elif is_endpoint_only and len(incident_segments[junction_id]) <= 1:
            junction_type = JunctionType.TERMINAL_UNKNOWN
        else:
            junction_type = JunctionType.NORMAL
        if len(through_segments.get(junction_id, [])) > 1:
            state = ObjectState.REVIEW
        elif junction_type is JunctionType.TERMINAL_UNKNOWN:
            state = ObjectState.UNKNOWN
        else:
            state = ObjectState.PUBLISHABLE
        junction_units.append(
            JunctionUnit(
                junction_id=junction_id,
                junction_type=junction_type,
                growth_level=str(min(grades)) if grades else "UNSPECIFIED",
                evidence_refs=(
                    EvidenceRef(
                        role="t01_nodes",
                        path=str(input_case.t01_nodes),
                        sha256=dict(input_case.source_hashes)["t01_nodes"],
                        object_id=junction_id,
                    ),
                ),
                state=state,
            )
        )

    standard_segments: list[StandardSegmentUnit] = []
    relations: list[JunctionSegmentRelation] = []
    for segment_id in sorted(parsed_segments):
        record = parsed_segments[segment_id]
        pair_nodes = record["pair_nodes"]
        carrier = carrier_by_segment[segment_id]
        if len(pair_nodes) != 2:
            anomalies.append(
                JSGAnomaly(
                    "segment_endpoint_cardinality",
                    "StandardSegmentUnit",
                    segment_id,
                    f"expected 2 pair nodes, got {len(pair_nodes)}",
                    "FAIL",
                )
            )
            padded = tuple(list(pair_nodes[:2]) + [f"MISSING:{segment_id}"] * max(0, 2 - len(pair_nodes)))
            pair_nodes = padded[:2]
        role_values = [access_roles.get((segment_id, junction_id), DirectionRole.UNKNOWN) for junction_id in pair_nodes]
        if role_values and all(value is DirectionRole.BOTH for value in role_values):
            direction_structure = DirectionStructure.BIDIRECTIONAL
        elif all(value is not DirectionRole.UNKNOWN for value in role_values):
            direction_structure = DirectionStructure.DIRECTED
        else:
            direction_structure = DirectionStructure.UNKNOWN
        state = (
            ObjectState.PUBLISHABLE
            if direction_structure is not DirectionStructure.UNKNOWN and carrier["road_ids"]
            else ObjectState.REVIEW
        )
        if not carrier["road_ids"]:
            anomalies.append(
                JSGAnomaly(
                    "carrier_unavailable",
                    "StandardSegmentUnit",
                    segment_id,
                    "T06 final carrier realization is empty; object remains REVIEW",
                )
            )
        standard_segments.append(
            StandardSegmentUnit(
                segment_id=segment_id,
                endpoint_positions=(pair_nodes[0], pair_nodes[1]),
                attached_junctions=record["junc_nodes"],
                direction_structure=direction_structure,
                growth_level=_growth_level(record["sgrade"]),
                road_grade="UNSPECIFIED",
                carrier_road_ids=tuple(sorted(set(carrier["road_ids"]))),
                evidence_refs=(
                    EvidenceRef(**{**segment_evidence.__dict__, "object_id": segment_id}),
                    EvidenceRef(**{**relation_evidence.__dict__, "object_id": segment_id}),
                    EvidenceRef(**{**t01_road_evidence.__dict__, "object_id": segment_id}),
                ),
                explicit_loop=pair_nodes[0] == pair_nodes[1],
                state=state,
            )
        )
        for structural_role, junction_list in (
            (StructuralRole.ENDPOINT, pair_nodes),
            (StructuralRole.THROUGH, record["junc_nodes"]),
        ):
            for junction_id in dict.fromkeys(junction_list):
                role = access_roles.get((segment_id, junction_id), DirectionRole.UNKNOWN)
                relation_state = ObjectState.PUBLISHABLE
                if (
                    role is DirectionRole.UNKNOWN
                    or state is ObjectState.REVIEW
                    or not set(access_nodes.get((segment_id, junction_id), ())) & truth_node_ids
                    or (
                    structural_role is StructuralRole.THROUGH
                    and len(through_segments.get(junction_id, [])) > 1
                    )
                ):
                    relation_state = ObjectState.REVIEW
                relations.append(
                    JunctionSegmentRelation(
                        junction_id=junction_id,
                        segment_id=segment_id,
                        structural_role=structural_role,
                        direction_role=role,
                        access_legs=tuple(sorted(access_nodes.get((segment_id, junction_id), ()))),
                        evidence_refs=(
                            EvidenceRef(**{**relation_evidence.__dict__, "object_id": segment_id}),
                            EvidenceRef(**{**t01_road_evidence.__dict__, "object_id": segment_id}),
                        ),
                        state=relation_state,
                    )
                )

    relation_lookup = {(row.junction_id, row.segment_id): row for row in relations}
    carrier_node_to_segments: dict[str, set[str]] = defaultdict(set)
    for segment_id, carrier in carrier_by_segment.items():
        if segment_id not in parsed_segments:
            continue
        for road_id in carrier["road_ids"]:
            payload = truth_roads.get(road_id)
            if payload is None:
                continue
            properties = dict(payload.get("properties") or {})
            carrier_node_to_segments[_text(_property(properties, "snodeid"))].add(segment_id)
            carrier_node_to_segments[_text(_property(properties, "enodeid"))].add(segment_id)
    movements: list[PhysicalMovement] = []
    for junction_id in junction_ids:
        incident = sorted(set(incident_segments[junction_id]))
        for from_segment in incident:
            from_relation = relation_lookup.get((junction_id, from_segment))
            if from_relation is None or from_relation.direction_role not in {DirectionRole.ENTER, DirectionRole.BOTH}:
                continue
            for to_segment in incident:
                if from_segment == to_segment:
                    continue
                to_relation = relation_lookup.get((junction_id, to_segment))
                if to_relation is None or to_relation.direction_role not in {DirectionRole.EXIT, DirectionRole.BOTH}:
                    continue
                allowed = set(carrier_by_segment[from_segment]["road_ids"])
                allowed.update(carrier_by_segment[to_segment]["road_ids"])
                allowed.update(carrier_by_segment[from_segment]["special_road_ids"])
                allowed.update(carrier_by_segment[to_segment]["special_road_ids"])
                allowed.update(carrier_by_segment[from_segment]["connectivity_road_ids"])
                allowed.update(carrier_by_segment[to_segment]["connectivity_road_ids"])
                path = _shortest_road_path(
                    tuple(
                        node_id
                        for node_id in access_nodes.get((from_segment, junction_id), ())
                        if node_id in truth_node_ids
                    ),
                    tuple(
                        node_id
                        for node_id in access_nodes.get((to_segment, junction_id), ())
                        if node_id in truth_node_ids
                    ),
                    directed_edges,
                    allowed,
                )
                if path is None:
                    continue
                movement_id = f"{junction_id}:{from_segment}->{to_segment}"
                movements.append(
                    PhysicalMovement(
                        movement_id=movement_id,
                        junction_id=junction_id,
                        from_segment_access=segment_access(from_segment, junction_id),
                        to_segment_access=segment_access(to_segment, junction_id),
                        physical_reachable=True,
                        carrier_road_ids=tuple(path),
                        evidence_refs=(EvidenceRef(**{**road_evidence.__dict__, "object_id": movement_id}),),
                        state=ObjectState.PUBLISHABLE,
                    )
                )

    connectors: list[SegmentConnector] = []
    for connector_id in sorted(connector_rows):
        record = connector_rows[connector_id]
        carrier = carrier_by_segment[connector_id]
        if not carrier["road_ids"]:
            anomalies.append(
                JSGAnomaly(
                    "connector_not_materialized",
                    "SegmentConnectorCandidate",
                    connector_id,
                    "T01 advance_right has no T06 final carrier and is retained as a negative truth outcome",
                )
            )
            continue
        if any(
            _text(
                _property(
                    dict(truth_roads[road_id].get("properties") or {}),
                    "t06_mixed_advance_right_carrier",
                )
            )
            not in {"", "0", "0.0"}
            for road_id in carrier["road_ids"]
        ):
            anomalies.append(
                JSGAnomaly(
                    "auxiliary_internal_carrier",
                    "SegmentUnitCarrier",
                    connector_id,
                    "T06 explicitly marks this advance-right road as a mixed internal carrier, not SegmentConnector",
                    "INFO",
                )
            )
            continue
        source_access = target_access = ""
        state = ObjectState.REVIEW
        source_nodes, target_nodes = _directed_carrier_terminals(carrier["road_ids"], truth_roads)
        if len(source_nodes) == 1 and len(target_nodes) == 1:
            source_candidates: set[str] = set()
            target_candidates: set[str] = set()
            for node_id in final_node_closure(source_nodes):
                source_candidates.update(carrier_node_to_segments.get(node_id, set()))
            for node_id in final_node_closure(target_nodes):
                target_candidates.update(carrier_node_to_segments.get(node_id, set()))
            if len(source_candidates) == 1 and len(target_candidates) == 1:
                source_segment = next(iter(source_candidates))
                target_segment = next(iter(target_candidates))
                source_access = segment_access(source_segment, source_nodes[0])
                target_access = segment_access(target_segment, target_nodes[0])
                state = ObjectState.PUBLISHABLE
        if state is ObjectState.REVIEW:
            anomalies.append(
                JSGAnomaly(
                    "connector_access_unresolved",
                    "SegmentConnector",
                    connector_id,
                    "source/target StandardSegment access is not uniquely proven",
                )
            )
        connectors.append(
            SegmentConnector(
                connector_id=connector_id,
                source_segment_access=source_access,
                target_segment_access=target_access,
                direction="FORWARD",
                carrier_road_ids=tuple(sorted(set(carrier["road_ids"]))),
                evidence_refs=(
                    EvidenceRef(**{**segment_evidence.__dict__, "object_id": connector_id}),
                    EvidenceRef(**{**relation_evidence.__dict__, "object_id": connector_id}),
                ),
                state=state,
            )
        )

    return JSGCaseTruth(
        case_key=input_case.case_key,
        family=input_case.family,
        business_id=input_case.business_id,
        crs=crs,
        source_manifest=str(input_case.source_manifest),
        source_hashes=input_case.source_hashes,
        junction_units=tuple(sorted(junction_units, key=lambda row: row.junction_id)),
        standard_segments=tuple(sorted(standard_segments, key=lambda row: row.segment_id)),
        junction_segment_relations=tuple(
            sorted(relations, key=lambda row: (row.junction_id, row.segment_id, row.structural_role.value))
        ),
        physical_movements=tuple(sorted(movements, key=lambda row: row.movement_id)),
        segment_connectors=tuple(sorted(connectors, key=lambda row: row.connector_id)),
        carrier_realization=input_case.carrier_realization,
        anomalies=tuple(sorted(anomalies, key=lambda row: (row.severity, row.code, row.object_id))),
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_existing(path: Path | str) -> Path:
    normalized = normalize_runtime_path(path)
    raw = str(normalized)
    if os.name == "nt" and normalized.is_absolute() and not raw.startswith("\\\\?\\") and len(raw) >= 248:
        normalized = Path("\\\\?\\" + raw)
    if not normalized.exists():
        raise FileNotFoundError(normalized)
    return normalized


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _verified_output(outputs: dict[str, Any], role: str, *, strict_hashes: bool) -> Path:
    record = dict(outputs.get(role) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"output hash mismatch: {role}")
    return path


def _read_properties(path: Path) -> tuple[list[dict[str, Any]], str]:
    layers = fiona.listlayers(path)
    if len(layers) != 1:
        raise ValueError(f"expected one vector layer: {path}")
    with fiona.open(path, layer=layers[0]) as source:
        return [dict(feature["properties"]) for feature in source], source.crs_wkt or ""


def _canonical_crs(value: str) -> str:
    if not value:
        return ""
    crs = CRS.from_user_input(value)
    authority = crs.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else crs.to_wkt()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    text = _text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in text.split(",") if item.strip()]
    if isinstance(parsed, list):
        return parsed
    return [parsed] if parsed is not None else []


def _string_list(value: Any) -> list[str]:
    return [_text(item) for item in _json_list(value) if _text(item)]


def _property(properties: Mapping[str, Any], name: str) -> Any:
    folded = name.casefold()
    return next((value for key, value in properties.items() if str(key).casefold() == folded), None)


def _semantic_node_index(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_main: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        identifier = _text(row.get("id"))
        if identifier:
            by_id[identifier] = row
        mainnode = _text(row.get("mainnodeid"))
        if mainnode and mainnode not in {"0", "0.0"}:
            by_main[mainnode].append(row)
    return by_id, by_main


def _node_semantics(
    junction_id: str,
    by_id: dict[str, dict[str, Any]],
    by_main: dict[str, list[dict[str, Any]]],
) -> tuple[set[int], set[int]]:
    rows = list(by_main.get(junction_id, []))
    if junction_id in by_id:
        rows.append(by_id[junction_id])
    kinds: set[int] = set()
    grades: set[int] = set()
    for row in rows:
        for field, target in (("kind_2", kinds), ("grade_2", grades)):
            try:
                target.add(int(row.get(field)))
            except (TypeError, ValueError):
                pass
    return kinds, grades


def _t01_access_nodes(
    junction_id: str,
    by_id: Mapping[str, dict[str, Any]],
    by_main: Mapping[str, list[dict[str, Any]]],
) -> tuple[str, ...]:
    output = {junction_id}
    rows = list(by_main.get(junction_id, []))
    if junction_id in by_id:
        rows.append(by_id[junction_id])
    for row in rows:
        output.add(_text(row.get("id")))
        output.update(_string_list(row.get("subnodeid")))
        mainnode = _text(row.get("mainnodeid"))
        if mainnode and mainnode not in {"0", "0.0"}:
            output.add(mainnode)
            output.update(_text(item.get("id")) for item in by_main.get(mainnode, []))
    output.discard("")
    return tuple(sorted(output))


def _terminal_evidence(
    t01_roads: Mapping[str, dict[str, Any]],
    truth_roads: Mapping[str, dict[str, Any]],
) -> tuple[set[str], set[str]]:
    terminal: set[str] = set()
    boundary: set[str] = set()
    for payload in t01_roads.values():
        properties = dict(payload.get("properties") or {})
        leaf = _text(_property(properties, "leaf_node_id"))
        bundle = _text(_property(properties, "dead_end_bundle_type"))
        if leaf and bundle:
            terminal.add(leaf)
    for payload in truth_roads.values():
        properties = dict(payload.get("properties") or {})
        boundary.update(_string_list(_property(properties, "t06_accepted_native_boundary_node_ids")))
    return terminal, boundary


def _growth_level(sgrade: str) -> str:
    parts = sgrade.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else "UNSPECIFIED"


def _direction_role(
    road_ids: Iterable[str], access_node_ids: Iterable[str], roads: Mapping[str, dict[str, Any]]
) -> DirectionRole:
    access = set(access_node_ids)
    enters = exits = False
    for road_id in road_ids:
        payload = roads.get(str(road_id))
        if payload is None:
            continue
        properties = dict(payload.get("properties") or {})
        start = _text(_property(properties, "snodeid"))
        end = _text(_property(properties, "enodeid"))
        try:
            direction = int(_property(properties, "direction"))
        except (TypeError, ValueError):
            continue
        if start in access:
            exits = exits or direction in FORWARD_DIRECTIONS
            enters = enters or direction in REVERSE_DIRECTIONS
        if end in access:
            enters = enters or direction in FORWARD_DIRECTIONS
            exits = exits or direction in REVERSE_DIRECTIONS
    if enters and exits:
        return DirectionRole.BOTH
    if enters:
        return DirectionRole.ENTER
    if exits:
        return DirectionRole.EXIT
    return DirectionRole.UNKNOWN


def _directed_road_edges(roads: Mapping[str, dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for road_id, payload in roads.items():
        properties = dict(payload.get("properties") or {})
        start = _text(_property(properties, "snodeid"))
        end = _text(_property(properties, "enodeid"))
        try:
            direction = int(_property(properties, "direction"))
        except (TypeError, ValueError):
            continue
        if direction in FORWARD_DIRECTIONS:
            edges[start].append((end, str(road_id)))
        if direction in REVERSE_DIRECTIONS:
            edges[end].append((start, str(road_id)))
    for node_id in edges:
        edges[node_id].sort()
    return edges


def _directed_carrier_terminals(
    road_ids: Iterable[str], roads: Mapping[str, dict[str, Any]]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    nodes: set[str] = set()
    for road_id in road_ids:
        payload = roads.get(str(road_id))
        if payload is None:
            continue
        properties = dict(payload.get("properties") or {})
        start = _text(_property(properties, "snodeid"))
        end = _text(_property(properties, "enodeid"))
        nodes.update((start, end))
        try:
            direction = int(_property(properties, "direction"))
        except (TypeError, ValueError):
            continue
        if direction in FORWARD_DIRECTIONS:
            outgoing[start] += 1
            incoming[end] += 1
        if direction in REVERSE_DIRECTIONS:
            outgoing[end] += 1
            incoming[start] += 1
    sources = tuple(sorted(node for node in nodes if outgoing[node] > incoming[node]))
    targets = tuple(sorted(node for node in nodes if incoming[node] > outgoing[node]))
    return sources, targets


def _final_node_closure(
    nodes: Mapping[str, dict[str, Any]],
) -> Any:
    by_main: dict[str, set[str]] = defaultdict(set)
    by_semantic_group: dict[str, set[str]] = defaultdict(set)
    properties_by_id: dict[str, dict[str, Any]] = {}
    for node_id, payload in nodes.items():
        properties = dict(payload.get("properties") or {})
        identifier = str(node_id)
        properties_by_id[identifier] = properties
        mainnode = _text(_property(properties, "mainnodeid"))
        if mainnode and mainnode not in {"0", "0.0"}:
            by_main[mainnode].add(identifier)
            by_main[mainnode].add(mainnode)
        group = _text(_property(properties, "semantic_junction_group_id"))
        if group:
            by_semantic_group[group].add(identifier)

    def expand(seed_ids: Iterable[str]) -> tuple[str, ...]:
        expanded = {_text(value) for value in seed_ids if _text(value)}
        queue = deque(sorted(expanded))
        while queue:
            node_id = queue.popleft()
            properties = properties_by_id.get(node_id)
            if properties is None:
                continue
            related = set(_string_list(_property(properties, "subnodeid")))
            mainnode = _text(_property(properties, "mainnodeid"))
            if mainnode and mainnode not in {"0", "0.0"}:
                related.update(by_main.get(mainnode, set()))
            group = _text(_property(properties, "semantic_junction_group_id"))
            if group:
                related.update(by_semantic_group.get(group, set()))
            for related_id in sorted(related - expanded):
                expanded.add(related_id)
                queue.append(related_id)
        return tuple(sorted(expanded))

    return expand


def _shortest_road_path(
    starts: Iterable[str],
    targets: Iterable[str],
    edges: Mapping[str, list[tuple[str, str]]],
    allowed_road_ids: set[str],
) -> list[str] | None:
    target_set = set(targets)
    queue: deque[tuple[str, tuple[str, ...]]] = deque()
    visited: set[str] = set()
    for node_id in sorted(set(starts)):
        if node_id in target_set:
            return []
        queue.append((node_id, ()))
        visited.add(node_id)
    while queue:
        node_id, path = queue.popleft()
        for next_node, road_id in edges.get(node_id, []):
            if road_id not in allowed_road_ids or next_node in visited:
                continue
            next_path = path + (road_id,)
            if next_node in target_set:
                return list(next_path)
            visited.add(next_node)
            queue.append((next_node, next_path))
    return None


__all__ = ["JSGInputCase", "build_jsg_case_truth", "load_jsg_input_cases"]
