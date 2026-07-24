from __future__ import annotations

import csv
import importlib.metadata
import json
import platform
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    DirectionRole,
    DirectionStructure,
    EvidenceRef,
    JunctionType,
    ObjectState,
    StructuralRole,
    segment_access,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p0 import _rss_bytes
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p1_models import (
    JSGP1Candidate,
    JSGP1CandidateConfig,
    P1ObjectType,
    P1Stage,
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_truth import (
    COMPLEX_JUNCTION_KINDS,
    SEMANTIC_JUNCTION_KINDS,
    _canonical_crs,
    _growth_level,
    _node_semantics,
    _property,
    _read_properties,
    _semantic_node_index,
    _string_list,
    _t01_access_nodes,
    _terminal_evidence,
    _text,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import read_vector_payloads
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


@dataclass(frozen=True)
class P1EvidenceCase:
    sample_id: str
    family: str
    business_id: str
    t01_segment: Path
    t01_nodes: Path
    t01_roads: Path
    source_manifest: Path
    source_hashes: tuple[tuple[str, str], ...]
    roadgraph_candidate_count: int
    roadgraph_candidate_signature: str
    replay_duration_seconds: float
    candidate_build_seconds: float

    @property
    def case_key(self) -> str:
        return f"{self.family}:{self.business_id}"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _verified_output(outputs: dict[str, Any], role: str, *, strict_hashes: bool) -> Path:
    record = dict(outputs.get(role) or {})
    path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"PTO candidate output hash mismatch: {role}")
    return path


def load_p1_evidence_cases(
    config: JSGP1CandidateConfig,
) -> tuple[Path, dict[str, Any], list[P1EvidenceCase]]:
    root = normalize_runtime_path(config.pto_candidate_run_root).resolve(strict=True)
    manifest_path = root / "p05_pto_candidate_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-pto-candidate-manifest-v1":
        raise ValueError("invalid RoadGraph PTO candidate manifest")
    if manifest.get("status") != "candidate_scope_passed" or manifest.get("silent_fix") is not False:
        raise ValueError("RoadGraph PTO candidate run must pass scope with silent_fix=false")
    if int(manifest.get("truth_input_count", -1)) != 0:
        raise ValueError("RoadGraph PTO candidate run declares truth input")
    if int(manifest.get("truth_derived_candidate_count", -1)) != 0:
        raise ValueError("RoadGraph PTO candidate run declares truth-derived candidates")
    parameters = dict(manifest.get("parameters") or {})
    if int(parameters.get("expected_case_count", -1)) != config.expected_case_count:
        raise ValueError("RoadGraph PTO candidate Case scope differs from JSG-P1")

    outputs = dict(manifest.get("outputs") or {})
    case_index_path = _verified_output(outputs, "case_index", strict_hashes=config.strict_hashes)
    lineage_path = _verified_output(outputs, "lineage", strict_hashes=config.strict_hashes)
    _verified_output(outputs, "candidates", strict_hashes=config.strict_hashes)
    _verified_output(outputs, "group_index", strict_hashes=config.strict_hashes)

    lineage: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in _read_csv(lineage_path):
        scope = (row["family"], row["business_id"])
        lineage[scope][row["role"]] = row

    poc_root = normalize_runtime_path(config.poc_data_root).resolve(strict=True)
    if config.enforce_poc_scope and poc_root != Path(r"E:\TestData\POC_Data").resolve(strict=True):
        raise ValueError(f"formal JSG-P1 scope must be E:\\TestData\\POC_Data, got {poc_root}")
    excluded = set(config.excluded_business_ids)
    cases: list[P1EvidenceCase] = []
    seen: set[tuple[str, str]] = set()
    for row in _read_csv(case_index_path):
        family = row["family"]
        business_id = row["business_id"]
        scope = (family, business_id)
        if scope in seen:
            raise ValueError(f"duplicate P1 candidate scope: {family}:{business_id}")
        seen.add(scope)
        if business_id in excluded:
            raise ValueError(f"excluded Case appears in candidate scope: {family}/{business_id}")
        if config.enforce_poc_scope and not (poc_root / family / business_id).exists():
            raise ValueError(f"candidate Case is outside POC_Data: {family}/{business_id}")
        role = lineage.get(scope, {}).get("t01_roads")
        if role is None:
            raise ValueError(f"{family}:{business_id}: missing t01_roads proposal lineage")
        t01_roads = normalize_runtime_path(role["path"]).resolve(strict=True)
        if config.strict_hashes and sha256_file(t01_roads) != role["sha256"]:
            raise ValueError(f"{family}:{business_id}: t01_roads hash mismatch")
        t01_segment = normalize_runtime_path(t01_roads.parent / "segment.gpkg").resolve(strict=True)
        t01_nodes = normalize_runtime_path(t01_roads.parent / "nodes.gpkg").resolve(strict=True)
        cases.append(
            P1EvidenceCase(
                sample_id=row["sample_id"],
                family=family,
                business_id=business_id,
                t01_segment=t01_segment,
                t01_nodes=t01_nodes,
                t01_roads=t01_roads,
                source_manifest=manifest_path,
                source_hashes=tuple(
                    sorted(
                        {
                            "pto_candidate_manifest": sha256_file(manifest_path),
                            "t01_segment": sha256_file(t01_segment),
                            "t01_nodes": sha256_file(t01_nodes),
                            "t01_roads": sha256_file(t01_roads),
                        }.items()
                    )
                ),
                roadgraph_candidate_count=int(row["candidate_count"]),
                roadgraph_candidate_signature=row["candidate_signature"],
                replay_duration_seconds=float(row.get("replay_duration_seconds") or 0.0),
                candidate_build_seconds=float(row.get("candidate_build_seconds") or 0.0),
            )
        )
    if len(cases) != config.expected_case_count:
        raise ValueError(f"JSG-P1 requires {config.expected_case_count} cases, got {len(cases)}")
    return manifest_path, manifest, sorted(cases, key=lambda item: (item.family, item.business_id))


def _candidate(
    case: P1EvidenceCase,
    *,
    object_type: P1ObjectType,
    object_key: str,
    group_id: str,
    payload: dict[str, Any],
    dependencies: tuple[str, ...] = (),
    evidence: EvidenceRef,
) -> JSGP1Candidate:
    return JSGP1Candidate.build(
        case_key=case.case_key,
        stage=P1Stage.PTO_A,
        object_type=object_type,
        object_key=object_key,
        group_id=group_id,
        payload=payload,
        dependencies=dependencies,
        evidence_refs=(evidence,),
        source_kinds=("T01_INFERENCE_EVIDENCE",),
    )


def _junction_group(junction_id: str) -> str:
    return f"PTO_A:JUNCTION:{junction_id}"


def _segment_group(segment_id: str) -> str:
    return f"PTO_A:STANDARD_SEGMENT:{segment_id}"


def _relation_group(junction_id: str, segment_id: str, role: StructuralRole) -> str:
    return f"PTO_A:RELATION:{junction_id}:{segment_id}:{role.value}"


def _movement_group(movement_id: str) -> str:
    return f"PTO_A:PHYSICAL_MOVEMENT:{movement_id}"


def _connector_group(connector_id: str) -> str:
    return f"PTO_A:SEGMENT_CONNECTOR:{connector_id}"


def build_p1_case_candidates(
    case: P1EvidenceCase,
) -> tuple[list[JSGP1Candidate], dict[str, Any]]:
    segment_rows, segment_crs = _read_properties(case.t01_segment)
    node_rows, node_crs = _read_properties(case.t01_nodes)
    road_payloads, road_meta = read_vector_payloads(case.t01_roads, source_role="p1_t01_roads")
    crs_values = {
        _canonical_crs(segment_crs),
        _canonical_crs(node_crs),
        _canonical_crs(str(road_meta.get("crs_wkt") or "")),
    }
    crs_values.discard("")
    if len(crs_values) != 1:
        raise ValueError(f"{case.case_key}: candidate evidence CRS mismatch {sorted(crs_values)}")
    crs = next(iter(crs_values))
    source_hashes = dict(case.source_hashes)
    segment_evidence = EvidenceRef(
        "t01_segment", str(case.t01_segment), source_hashes["t01_segment"]
    )
    node_evidence = EvidenceRef("t01_nodes", str(case.t01_nodes), source_hashes["t01_nodes"])
    road_evidence = EvidenceRef("t01_roads", str(case.t01_roads), source_hashes["t01_roads"])

    segments: dict[str, dict[str, Any]] = {}
    connectors: dict[str, dict[str, Any]] = {}
    for row in segment_rows:
        segment_id = _text(row.get("id"))
        record = {
            "segment_id": segment_id,
            "pair_nodes": tuple(_string_list(row.get("pair_nodes"))),
            "junc_nodes": tuple(_string_list(row.get("junc_nodes"))),
            "road_ids": tuple(_string_list(row.get("roads"))),
            "sgrade": _text(row.get("sgrade")),
            "segment_type": _text(row.get("segment_type")) or "normal",
        }
        if record["segment_type"] == "advance_right":
            connectors[segment_id] = record
        else:
            segments[segment_id] = record

    incident: dict[str, set[str]] = defaultdict(set)
    through: dict[str, set[str]] = defaultdict(set)
    for segment_id, row in segments.items():
        for junction_id in row["pair_nodes"]:
            incident[junction_id].add(segment_id)
        for junction_id in row["junc_nodes"]:
            incident[junction_id].add(segment_id)
            through[junction_id].add(segment_id)

    node_index, node_members = _semantic_node_index(node_rows)
    terminal_evidence, _ = _terminal_evidence(road_payloads, {})
    candidates: list[JSGP1Candidate] = []
    for junction_id in sorted(incident):
        kinds, grades = _node_semantics(junction_id, node_index, node_members)
        endpoint_only = junction_id not in through
        if 64 in kinds:
            types = (JunctionType.ROUNDABOUT,)
        elif kinds & COMPLEX_JUNCTION_KINDS:
            types = (JunctionType.COMPLEX_DIVMERGE,)
        elif kinds & SEMANTIC_JUNCTION_KINDS:
            types = (JunctionType.NORMAL,)
        elif junction_id in terminal_evidence:
            types = (JunctionType.TERMINAL_DEAD_END,)
        elif endpoint_only and len(incident[junction_id]) <= 1:
            types = (JunctionType.TERMINAL_DATA_BOUNDARY, JunctionType.TERMINAL_UNKNOWN)
        else:
            types = (JunctionType.NORMAL,)
        states = (
            (ObjectState.REVIEW,)
            if len(through.get(junction_id, set())) > 1
            else (ObjectState.PUBLISHABLE, ObjectState.REVIEW, ObjectState.UNKNOWN)
        )
        for junction_type in types:
            for state in states:
                if junction_type is JunctionType.TERMINAL_UNKNOWN and state is ObjectState.PUBLISHABLE:
                    continue
                candidates.append(
                    _candidate(
                        case,
                        object_type=P1ObjectType.JUNCTION,
                        object_key=junction_id,
                        group_id=_junction_group(junction_id),
                        payload={
                            "junction_id": junction_id,
                            "junction_type": junction_type.value,
                            "growth_level": str(min(grades)) if grades else "UNSPECIFIED",
                            "state": state.value,
                        },
                        evidence=EvidenceRef(**{**node_evidence.__dict__, "object_id": junction_id}),
                    )
                )

    for segment_id in sorted(segments):
        row = segments[segment_id]
        pair_nodes = row["pair_nodes"]
        if len(pair_nodes) != 2:
            continue
        dependencies = tuple(
            sorted({_junction_group(value) for value in pair_nodes + row["junc_nodes"]})
        )
        for direction in DirectionStructure:
            for state in (ObjectState.PUBLISHABLE, ObjectState.REVIEW, ObjectState.UNKNOWN):
                if direction is DirectionStructure.UNKNOWN and state is ObjectState.PUBLISHABLE:
                    continue
                candidates.append(
                    _candidate(
                        case,
                        object_type=P1ObjectType.STANDARD_SEGMENT,
                        object_key=segment_id,
                        group_id=_segment_group(segment_id),
                        payload={
                            "segment_id": segment_id,
                            "endpoint_positions": list(pair_nodes),
                            "attached_junctions": list(row["junc_nodes"]),
                            "direction_structure": direction.value,
                            "growth_level": _growth_level(row["sgrade"]),
                            "road_grade": "UNSPECIFIED",
                            "explicit_loop": pair_nodes[0] == pair_nodes[1],
                            "state": state.value,
                        },
                        dependencies=dependencies,
                        evidence=EvidenceRef(**{**segment_evidence.__dict__, "object_id": segment_id}),
                    )
                )
        for structural_role, junction_ids in (
            (StructuralRole.ENDPOINT, pair_nodes),
            (StructuralRole.THROUGH, row["junc_nodes"]),
        ):
            for junction_id in dict.fromkeys(junction_ids):
                relation_key = f"{junction_id}:{segment_id}:{structural_role.value}"
                relation_dependencies = (_junction_group(junction_id), _segment_group(segment_id))
                for direction_role in DirectionRole:
                    for state in (ObjectState.PUBLISHABLE, ObjectState.REVIEW, ObjectState.UNKNOWN):
                        if direction_role is DirectionRole.UNKNOWN and state is ObjectState.PUBLISHABLE:
                            continue
                        if structural_role is StructuralRole.THROUGH and len(through[junction_id]) > 1:
                            if state is ObjectState.PUBLISHABLE:
                                continue
                        candidates.append(
                            _candidate(
                                case,
                                object_type=P1ObjectType.RELATION,
                                object_key=relation_key,
                                group_id=_relation_group(junction_id, segment_id, structural_role),
                                payload={
                                    "junction_id": junction_id,
                                    "segment_id": segment_id,
                                    "structural_role": structural_role.value,
                                    "direction_role": direction_role.value,
                                    "state": state.value,
                                },
                                dependencies=relation_dependencies,
                                evidence=EvidenceRef(**{**road_evidence.__dict__, "object_id": relation_key}),
                            )
                        )

    movement_count = 0
    for junction_id in sorted(incident):
        segment_ids = sorted(incident[junction_id])
        for from_segment in segment_ids:
            for to_segment in segment_ids:
                if from_segment == to_segment:
                    continue
                movement_id = f"{junction_id}:{from_segment}->{to_segment}"
                group_id = _movement_group(movement_id)
                dependencies = (
                    _junction_group(junction_id),
                    _segment_group(from_segment),
                    _segment_group(to_segment),
                )
                candidates.append(
                    _candidate(
                        case,
                        object_type=P1ObjectType.PHYSICAL_MOVEMENT,
                        object_key=movement_id,
                        group_id=group_id,
                        payload={"movement_id": movement_id, "outcome": "ABSENT"},
                        dependencies=dependencies,
                        evidence=EvidenceRef(**{**road_evidence.__dict__, "object_id": movement_id}),
                    )
                )
                for state in (ObjectState.PUBLISHABLE, ObjectState.REVIEW):
                    candidates.append(
                        _candidate(
                            case,
                            object_type=P1ObjectType.PHYSICAL_MOVEMENT,
                            object_key=movement_id,
                            group_id=group_id,
                            payload={
                                "movement_id": movement_id,
                                "junction_id": junction_id,
                                "from_segment_access": segment_access(from_segment, junction_id),
                                "to_segment_access": segment_access(to_segment, junction_id),
                                "physical_reachable": True,
                                "state": state.value,
                                "outcome": "PRESENT",
                            },
                            dependencies=dependencies,
                            evidence=EvidenceRef(**{**road_evidence.__dict__, "object_id": movement_id}),
                        )
                    )
                movement_count += 1

    for connector_id in sorted(connectors):
        group_id = _connector_group(connector_id)
        for outcome, state in (
            ("PRESENT", ObjectState.PUBLISHABLE),
            ("PRESENT", ObjectState.REVIEW),
            ("AUXILIARY_INTERNAL", ObjectState.REVIEW),
            ("NOT_MATERIALIZED", ObjectState.REVIEW),
        ):
            candidates.append(
                _candidate(
                    case,
                    object_type=P1ObjectType.SEGMENT_CONNECTOR,
                    object_key=connector_id,
                    group_id=group_id,
                    payload={
                        "connector_id": connector_id,
                        "direction": "FORWARD",
                        "state": state.value,
                        "outcome": outcome,
                    },
                    evidence=EvidenceRef(**{**segment_evidence.__dict__, "object_id": connector_id}),
                )
            )

    carrier = JSGP1Candidate.build(
        case_key=case.case_key,
        stage=P1Stage.PTO_B,
        object_type=P1ObjectType.ROADGRAPH_CARRIER,
        object_key=case.sample_id,
        group_id=f"PTO_B:ROADGRAPH:{case.sample_id}",
        payload={
            "sample_id": case.sample_id,
            "roadgraph_candidate_count": case.roadgraph_candidate_count,
            "roadgraph_candidate_signature": case.roadgraph_candidate_signature,
            "carrier_domain": "FROZEN_ROADGRAPH_CANDIDATE_GROUPS",
        },
        evidence_refs=(
            EvidenceRef(
                "pto_candidate_manifest",
                str(case.source_manifest),
                source_hashes["pto_candidate_manifest"],
                case.sample_id,
            ),
        ),
        source_kinds=("TRUTH_FREE_STRATEGY_PROPOSAL", "BASE_IDENTITY"),
    )
    candidates.append(carrier)
    deduplicated = {candidate.candidate_id: candidate for candidate in candidates}
    if len(deduplicated) != len(candidates):
        candidates = list(deduplicated.values())
    candidates.sort(key=lambda row: (row.group_id, row.candidate_id))
    return candidates, {
        "case_key": case.case_key,
        "sample_id": case.sample_id,
        "crs": crs,
        "junction_count": len(incident),
        "standard_segment_count": len(segments),
        "relation_group_count": sum(
            len(set(row["pair_nodes"])) + len(set(row["junc_nodes"])) for row in segments.values()
        ),
        "movement_group_count": movement_count,
        "connector_group_count": len(connectors),
        "candidate_count": len(candidates),
    }


def _environment() -> dict[str, Any]:
    packages = {}
    for package in ("fiona", "pyproj", "shapely"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = "missing"
    return {"python": sys.version, "platform": platform.platform(), "packages": packages}


def build_jsg_p1_candidate_run(config: JSGP1CandidateConfig) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    started_at = datetime.now(timezone.utc)
    upstream_manifest_path, upstream_manifest, cases = load_p1_evidence_cases(config)
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    candidate_path = target_root / "p05_jsg_p1_candidates.jsonl"
    candidate_path.touch()
    case_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    rss_samples = [_rss_bytes()]
    for case in cases:
        case_started = time.perf_counter()
        candidates, metrics = build_p1_case_candidates(case)
        _append_jsonl(candidate_path, (candidate.to_dict() for candidate in candidates))
        by_group: dict[str, list[JSGP1Candidate]] = defaultdict(list)
        for candidate in candidates:
            by_group[candidate.group_id].append(candidate)
            counts[f"{candidate.stage.value}:{candidate.object_type.value}"] += 1
        for group_id, options in sorted(by_group.items()):
            group_rows.append(
                {
                    "case_key": case.case_key,
                    "family": case.family,
                    "business_id": case.business_id,
                    "group_id": group_id,
                    "stage": options[0].stage.value,
                    "object_type": options[0].object_type.value,
                    "option_count": len(options),
                    "group_signature": canonical_sha256(sorted(item.candidate_id for item in options)),
                }
            )
        candidate_signature = canonical_sha256(sorted(item.candidate_id for item in candidates))
        case_rows.append(
            {
                **metrics,
                "family": case.family,
                "business_id": case.business_id,
                "group_count": len(by_group),
                "candidate_signature": candidate_signature,
                "roadgraph_candidate_count": case.roadgraph_candidate_count,
                "roadgraph_candidate_signature": case.roadgraph_candidate_signature,
                "upstream_replay_seconds": case.replay_duration_seconds,
                "upstream_candidate_build_seconds": case.candidate_build_seconds,
                "p1_candidate_build_seconds": time.perf_counter() - case_started,
            }
        )
        for role, digest in case.source_hashes:
            lineage_rows.append(
                {
                    "case_key": case.case_key,
                    "family": case.family,
                    "business_id": case.business_id,
                    "role": role,
                    "sha256": digest,
                    "path": {
                        "pto_candidate_manifest": str(case.source_manifest),
                        "t01_segment": str(case.t01_segment),
                        "t01_nodes": str(case.t01_nodes),
                        "t01_roads": str(case.t01_roads),
                    }[role],
                    "truth_derived": False,
                }
            )
        rss_samples.append(_rss_bytes())

    case_index_path = target_root / "p05_jsg_p1_case_index.csv"
    group_index_path = target_root / "p05_jsg_p1_group_index.csv"
    lineage_path = target_root / "p05_jsg_p1_lineage.csv"
    summary_path = target_root / "p05_jsg_p1_candidate_summary.json"
    write_csv(case_index_path, case_rows, list(case_rows[0]))
    write_csv(group_index_path, group_rows, list(group_rows[0]))
    write_csv(lineage_path, lineage_rows, list(lineage_rows[0]))
    excluded = set(config.excluded_business_ids)
    summary = {
        "schema_version": "p05-jsg-p1-candidate-summary-v1",
        "case_count": len(case_rows),
        "family_counts": dict(sorted(Counter(row["family"] for row in case_rows).items())),
        "candidate_count": sum(int(row["candidate_count"]) for row in case_rows),
        "group_count": sum(int(row["group_count"]) for row in case_rows),
        "candidate_counts": dict(sorted(counts.items())),
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "label_only_candidate_count": 0,
        "excluded_business_ids": sorted(excluded),
        "excluded_occurrence_count": sum(row["business_id"] in excluded for row in case_rows),
        "unbounded_enumeration": False,
        "candidate_signature": canonical_sha256(
            {row["case_key"]: row["candidate_signature"] for row in case_rows}
        ),
        "upstream_replay_total_seconds": sum(float(row["upstream_replay_seconds"]) for row in case_rows),
        "p1_candidate_wall_seconds": time.perf_counter() - started,
        "p1_candidate_cpu_seconds": time.process_time() - cpu_started,
        "peak_rss_bytes": max(rss_samples, default=0),
        "gpu_required": False,
        "silent_fix": False,
    }
    write_json(summary_path, summary)
    outputs = {
        "candidates": output_record(candidate_path),
        "case_index": output_record(case_index_path),
        "group_index": output_record(group_index_path),
        "lineage": output_record(lineage_path),
        "summary": output_record(summary_path),
    }
    scope_pass = (
        len(case_rows) == config.expected_case_count
        and summary["excluded_occurrence_count"] == 0
        and summary["truth_input_count"] == 0
        and summary["truth_derived_candidate_count"] == 0
        and summary["label_only_candidate_count"] == 0
        and not summary["unbounded_enumeration"]
    )
    manifest = {
        "schema_version": "p05-jsg-p1-candidate-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "candidate_scope_passed" if scope_pass else "candidate_scope_failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_pto_candidate_manifest_path": str(upstream_manifest_path),
        "upstream_pto_candidate_manifest_sha256": sha256_file(upstream_manifest_path),
        "upstream_pto_candidate_run_root": str(
            normalize_runtime_path(config.pto_candidate_run_root).resolve(strict=True)
        ),
        "upstream_pto_candidate_status": upstream_manifest["status"],
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "label_only_candidate_count": 0,
        "parameters": {
            "poc_data_root": str(normalize_runtime_path(config.poc_data_root).resolve(strict=True)),
            "excluded_business_ids": sorted(excluded),
            "expected_case_count": config.expected_case_count,
            "strict_hashes": config.strict_hashes,
            "enforce_poc_scope": config.enforce_poc_scope,
        },
        "environment": _environment(),
        "outputs": outputs,
        "unbounded_enumeration": False,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = target_root / "p05_jsg_p1_candidate_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    summary["gate_pass"] = scope_pass
    return summary


__all__ = [
    "P1EvidenceCase",
    "build_jsg_p1_candidate_run",
    "build_p1_case_candidates",
    "load_p1_evidence_cases",
]
