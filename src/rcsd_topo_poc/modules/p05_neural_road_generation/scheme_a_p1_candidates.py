from __future__ import annotations

import json
import math
import platform
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Mapping

import fiona
from pyproj import CRS
from shapely.geometry import shape

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    split_segment_access,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_models import (
    SchemeAP1Candidate,
    SchemeAP1CandidateConfig,
    candidate_group_signature,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


CANDIDATE_MANIFEST_VERSION = "p05-scheme-a-p1-candidate-manifest-v1"
FORBIDDEN_FEATURE_FIELDS = {
    "relation_status",
    "relation_reason",
    "carrier_ids",
    "access_node_ids",
    "target_payload",
    "truth",
    "oracle",
}


def build_scheme_a_p1_candidate_run(config: SchemeAP1CandidateConfig) -> Path:
    started = time.perf_counter()
    started_cpu = time.process_time()
    baseline_root = _resolve_dir(config.scheme_a_baseline_run_root)
    pto_root = _resolve_dir(config.pto_candidate_run_root)
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    baseline_manifest_path = baseline_root / "scheme_a_manifest.json"
    baseline_manifest = _read_json(baseline_manifest_path)
    if baseline_manifest.get("status") != "passed":
        raise ValueError("Scheme A baseline must be passed")
    if int(baseline_manifest.get("counts", {}).get("case_count", 0)) != config.expected_case_count:
        raise ValueError("Scheme A baseline Case count mismatch")
    if baseline_manifest.get("skeleton_mutation_count") != 0:
        raise ValueError("Scheme A baseline skeleton is not frozen")

    pto_manifest_path = pto_root / "p05_pto_candidate_manifest.json"
    pto_manifest = _read_json(pto_manifest_path)
    if pto_manifest.get("status") != "candidate_scope_passed":
        raise ValueError("PTO candidate manifest is not passed")
    for field in ("truth_input_count", "truth_derived_candidate_count"):
        if int(pto_manifest.get(field, -1)) != 0:
            raise ValueError(f"PTO candidate is not truth-free: {field}")

    artifact_manifest_path = baseline_root / "artifact_manifest.json"
    artifacts = _verified_artifacts(artifact_manifest_path, config.strict_hashes)
    skeleton_paths = sorted(
        path for path in artifacts if path.name == "frozen_skeleton.json"
    )
    if len(skeleton_paths) != config.expected_case_count:
        raise ValueError("frozen skeleton count mismatch")

    candidates: list[SchemeAP1Candidate] = []
    case_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    excluded_occurrences = 0
    crs_counts: Counter[str] = Counter()
    case_durations: list[float] = []
    for skeleton_path in skeleton_paths:
        case_started = time.perf_counter()
        skeleton = _read_json(skeleton_path)
        business_id = str(skeleton["business_id"])
        if business_id in config.excluded_business_ids:
            excluded_occurrences += 1
            continue
        case_candidates, case_lineage, canonical_crs = _build_case_candidates(
            skeleton,
            skeleton_path=skeleton_path,
            pto_manifest_path=pto_manifest_path,
            strict_hashes=config.strict_hashes,
        )
        candidates.extend(case_candidates)
        lineage_rows.extend(case_lineage)
        crs_counts[canonical_crs] += 1
        groups = defaultdict(list)
        for row in case_candidates:
            groups[row.group_id].append(row)
        case_rows.append(
            {
                "case_key": skeleton["case_key"],
                "family": skeleton["family"],
                "business_id": business_id,
                "fold": skeleton["fold"],
                "crs": canonical_crs,
                "group_count": len(groups),
                "candidate_count": len(case_candidates),
                "candidate_signature": canonical_sha256(
                    [
                        candidate_group_signature(rows)
                        for _, rows in sorted(groups.items())
                    ]
                ),
            }
        )
        case_durations.append(time.perf_counter() - case_started)

    if excluded_occurrences:
        raise ValueError("approved exclusion appeared in candidate scope")
    if len(case_rows) != config.expected_case_count:
        raise ValueError("candidate Case count mismatch")
    if set(crs_counts) != {"EPSG:3857"}:
        raise ValueError(f"unexpected candidate CRS: {dict(crs_counts)}")

    candidates.sort(key=lambda row: (row.case_key, row.object_type, row.object_id, row.candidate_id))
    group_map: dict[str, list[SchemeAP1Candidate]] = defaultdict(list)
    for row in candidates:
        group_map[row.group_id].append(row)
    candidate_path = run_root / "candidate_groups.jsonl"
    feature_path = run_root / "candidate_features.jsonl"
    _write_jsonl(candidate_path, [row.to_dict() for row in candidates])
    _write_jsonl(
        feature_path,
        [
            {
                "case_key": row.case_key,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "group_id": row.group_id,
                "candidate_id": row.candidate_id,
                "object_tokens": list(row.object_tokens),
                "candidate_tokens": list(row.candidate_tokens),
                "context_tokens": list(row.context_tokens),
                "numeric_features": list(row.numeric_features),
                "hard_unsafe": row.hard_unsafe,
                "feature_uses_truth": False,
                "absolute_coordinate_feature_count": 0,
            }
            for row in candidates
        ],
    )
    case_index_path = run_root / "case_index.csv"
    write_csv(
        case_index_path,
        case_rows,
        [
            "case_key",
            "family",
            "business_id",
            "fold",
            "crs",
            "group_count",
            "candidate_count",
            "candidate_signature",
        ],
    )
    lineage_path = run_root / "lineage.csv"
    write_csv(
        lineage_path,
        _dedupe_lineage(lineage_rows),
        ["case_key", "role", "path", "sha256", "size_bytes", "label_only", "truth_derived"],
    )

    object_counts = Counter(row.object_type for row in candidates)
    source_counts = Counter(source for row in candidates for source in row.source_kinds)
    hard_unsafe_groups = len(
        {row.group_id for row in candidates if row.hard_unsafe}
    )
    signatures = {
        "candidate": canonical_sha256(
            [
                {
                    "candidate_id": row.candidate_id,
                    "group_id": row.group_id,
                    "candidate_target": row.candidate_target,
                    "target_kind": row.target_kind,
                    "target_payload": list(row.target_payload),
                    "tokens": list(row.object_tokens + row.candidate_tokens + row.context_tokens),
                    "numeric": list(row.numeric_features),
                }
                for row in candidates
            ]
        ),
        "groups": canonical_sha256(
            {
                key: candidate_group_signature(rows)
                for key, rows in sorted(group_map.items())
            }
        ),
    }
    wall = time.perf_counter() - started
    summary = {
        "schema_version": "p05-scheme-a-p1-candidate-summary-v1",
        "gate_pass": True,
        "case_count": len(case_rows),
        "group_count": len(group_map),
        "candidate_count": len(candidates),
        "object_candidate_counts": dict(sorted(object_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "hard_unsafe_group_count": hard_unsafe_groups,
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "truth_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "excluded_occurrence_count": excluded_occurrences,
        "crs_counts": dict(sorted(crs_counts.items())),
        "performance": {
            "wall_seconds": wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "case_p95_seconds": _percentile(case_durations, 0.95),
            "case_max_seconds": max(case_durations, default=0.0),
            "gpu_required": False,
        },
        "signatures": signatures,
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }
    summary_path = run_root / "scheme_a_p1_candidate_summary.json"
    write_json(summary_path, summary)
    outputs = {
        "candidates": output_record(candidate_path),
        "features": output_record(feature_path),
        "case_index": output_record(case_index_path),
        "lineage": output_record(lineage_path),
        "summary": output_record(summary_path),
    }
    manifest = {
        "schema_version": CANDIDATE_MANIFEST_VERSION,
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "candidate_scope_passed",
        "input_manifests": {
            "scheme_a_baseline": {
                "path": str(baseline_manifest_path.resolve()),
                "sha256": _sha256_file(baseline_manifest_path),
            },
            "pto_candidate": {
                "path": str(pto_manifest_path.resolve()),
                "sha256": _sha256_file(pto_manifest_path),
            },
        },
        "parameters": {
            "poc_data_root": str(normalize_runtime_path(config.poc_data_root)),
            "expected_case_count": config.expected_case_count,
            "excluded_business_ids": list(config.excluded_business_ids),
            "strict_hashes": config.strict_hashes,
            "enforce_poc_scope": config.enforce_poc_scope,
        },
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "truth_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "fiona": fiona.__version__,
        },
        "signatures": signatures,
        "outputs": outputs,
    }
    manifest_path = run_root / "scheme_a_p1_candidate_manifest.json"
    write_json(manifest_path, manifest)
    artifact_manifest_path_out = run_root / "artifact_manifest.json"
    write_json(
        artifact_manifest_path_out,
        {
            "schema_version": "p05-scheme-a-p1-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def classify_segment_candidate(
    swsd_road_ids: Iterable[str], proposal_road_ids: Iterable[str]
) -> str:
    swsd = {str(value) for value in swsd_road_ids if str(value)}
    proposal = {str(value) for value in proposal_road_ids if str(value)}
    if not proposal:
        return "REVIEW_FALLBACK"
    if proposal == swsd:
        return "KEEP_SWSD"
    if proposal & swsd:
        return "MIXED_CARRIER"
    return "USE_RCSD"


def _build_case_candidates(
    skeleton: dict[str, Any],
    *,
    skeleton_path: Path,
    pto_manifest_path: Path,
    strict_hashes: bool,
) -> tuple[list[SchemeAP1Candidate], list[dict[str, Any]], str]:
    evidence = _whitelisted_skeleton_evidence(skeleton)
    t01_segment = _single_evidence(evidence, "t01_segment")
    case_root = _absolute_path(t01_segment["path"]).parent.parent
    run_summary_path = case_root / "t10_e2e_case_run_summary.json"
    summary = _read_json(run_summary_path)
    if not summary.get("passed") or summary.get("status") != "passed":
        raise ValueError(f"strategy replay is not passed: {run_summary_path}")
    handoffs = dict(summary.get("t06_funnel", {}).get("handoffs") or {})
    paths = {
        "t01_segment": _handoff_path(handoffs, "t01_segment"),
        "t01_roads": _handoff_path(handoffs, "t01_roads"),
        "t01_nodes": case_root / "t01" / "nodes.gpkg",
        "proposal_relation": _handoff_path(handoffs, "t06_swsd_frcsd_segment_relation"),
        "proposal_roads": _handoff_path(handoffs, "t06_frcsd_road"),
        "proposal_nodes": _handoff_path(handoffs, "t06_frcsd_node"),
    }
    for path in paths.values():
        if not _io_path(path).is_file():
            raise FileNotFoundError(path)
    if strict_hashes:
        for role in ("t01_segment", "t01_roads"):
            expected = _single_evidence(evidence, role)["sha256"]
            if _sha256_file(paths[role]) != expected:
                raise ValueError(f"replay evidence hash mismatch: {role}")

    t01_roads, t01_crs = _read_features(paths["t01_roads"])
    t01_nodes, t01_node_crs = _read_features(paths["t01_nodes"])
    proposal_roads, proposal_crs = _read_features(paths["proposal_roads"])
    proposal_nodes, proposal_node_crs = _read_features(paths["proposal_nodes"])
    relation_rows, relation_crs = _read_properties(paths["proposal_relation"])
    canonical_crs = _canonical_crs(skeleton.get("crs") or t01_crs)
    observed_crs = {
        _canonical_crs(value)
        for value in (t01_crs, t01_node_crs, proposal_crs, proposal_node_crs, relation_crs)
    }
    if observed_crs != {canonical_crs}:
        raise ValueError(f"candidate CRS mismatch for {skeleton['case_key']}: {observed_crs}")

    relation_by_segment = {
        _text(_property(row, "swsd_segment_id")): row
        for row in relation_rows
        if _text(_property(row, "swsd_segment_id"))
    }
    segment_by_id = {str(row["segment_id"]): row for row in skeleton["segments"]}
    junction_by_id = {str(row["junction_id"]): row for row in skeleton["junctions"]}
    movement_by_segment: Counter[str] = Counter()
    for movement in skeleton["physical_movements"]:
        from_segment, _ = split_segment_access(str(movement["from_segment_access"]))
        to_segment, _ = split_segment_access(str(movement["to_segment_access"]))
        movement_by_segment[from_segment] += 1
        movement_by_segment[to_segment] += 1
    junction_degree = {
        key: len(value.get("related_segment_ids") or []) for key, value in junction_by_id.items()
    }
    refs = {
        role: (role, str(_absolute_path(path)), _sha256_file(path)) for role, path in paths.items()
    }
    refs["strategy_run_summary"] = (
        "strategy_run_summary",
        str(run_summary_path.resolve()),
        _sha256_file(run_summary_path),
    )
    refs["pto_candidate_manifest"] = (
        "pto_candidate_manifest",
        str(pto_manifest_path.resolve()),
        _sha256_file(pto_manifest_path),
    )

    proposal_closure = _node_closure(proposal_nodes)
    proposal_access_by_relation: dict[tuple[str, str], tuple[str, ...]] = {}
    proposal_conflict_junctions: set[str] = set()
    for junction_id, junction in sorted(junction_by_id.items()):
        mainnode_groups: set[str] = set()
        for segment_id in junction.get("related_segment_ids") or []:
            relation = relation_by_segment.get(str(segment_id), {})
            access_ids = tuple(
                sorted(
                    set(
                        proposal_closure(
                            {junction_id, *_mapped_nodes(relation, junction_id)}
                        )
                    )
                    & set(proposal_nodes)
                )
            )
            proposal_access_by_relation[(junction_id, str(segment_id))] = access_ids
            for node_id in access_ids:
                properties = dict(proposal_nodes[node_id].get("properties") or {})
                mainnode = _text(_property(properties, "mainnodeid"))
                if mainnode and mainnode not in {"0", "0.0"}:
                    mainnode_groups.add(mainnode)
                elif _string_list(_property(properties, "subnodeid")):
                    mainnode_groups.add(node_id)
        if len(mainnode_groups) > 1:
            proposal_conflict_junctions.add(junction_id)

    candidates: list[SchemeAP1Candidate] = []
    segment_hard_unsafe: dict[str, bool] = {}
    for segment_id, segment in sorted(segment_by_id.items()):
        related_junctions = tuple(
            str(value)
            for value in (*segment.get("pair_nodes", []), *segment.get("junc_nodes", []))
        )
        conflict_count = sum(
            junction_id in proposal_conflict_junctions
            for junction_id in related_junctions
        )
        missing_access_count = sum(
            not proposal_access_by_relation.get((junction_id, segment_id))
            for junction_id in related_junctions
        )
        relation = relation_by_segment.get(segment_id, {})
        declared_proposal_ids = tuple(
            sorted(_string_list(_property(relation, "frcsd_road_ids")))
        )
        missing_proposal_road_count = sum(
            road_id not in proposal_roads for road_id in declared_proposal_ids
        )
        object_tokens = _segment_object_tokens(
            segment,
            movement_count=movement_by_segment[segment_id],
            junction_degree=junction_degree,
        ) + (
            f"PROPOSAL_JUNCTION_CONFLICT_COUNT:{_count_bucket(conflict_count)}",
            f"PROPOSAL_ACCESS_MISSING_COUNT:{_count_bucket(missing_access_count)}",
            f"PROPOSAL_ROAD_MISSING_COUNT:{_count_bucket(missing_proposal_road_count)}",
        )
        context_tokens = (
            f"CONTEXT_MOVEMENT_DEGREE:{_count_bucket(movement_by_segment[segment_id])}",
            f"CONTEXT_JUNCTION_COUNT:{_count_bucket(len(segment.get('pair_nodes') or []) + len(segment.get('junc_nodes') or []))}",
            f"CONTEXT_PROPOSAL_CONFLICT:{conflict_count > 0}",
            f"CONTEXT_PROPOSAL_ACCESS_MISSING:{missing_access_count > 0}",
        )
        hard_unsafe = (
            not bool(segment.get("access_valid"))
            or not bool(segment.get("independent_road_valid"))
            or conflict_count > 0
            or missing_access_count > 0
            or missing_proposal_road_count > 0
        )
        segment_hard_unsafe[segment_id] = hard_unsafe
        swsd_ids = tuple(sorted(str(value) for value in segment.get("swsd_road_ids") or []))
        group_rows: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
        _merge_option(
            group_rows,
            candidate_target="KEEP_SWSD",
            target_kind="ROAD",
            payload=swsd_ids,
            source_kind="SWSD_IDENTITY",
            artifact=refs["t01_roads"],
            road_payloads=t01_roads,
        )
        proposal_ids = tuple(
            sorted(
                {
                    road_id
                    for road_id in _string_list(_property(relation, "frcsd_road_ids"))
                    if road_id in proposal_roads
                }
            )
        )
        if proposal_ids:
            _merge_option(
                group_rows,
                candidate_target=classify_segment_candidate(swsd_ids, proposal_ids),
                target_kind="ROAD",
                payload=proposal_ids,
                source_kind="REGISTERED_STRATEGY_PROPOSAL",
                artifact=refs["proposal_roads"],
                road_payloads=proposal_roads,
            )
            mixed_ids = tuple(sorted(set(swsd_ids) | set(proposal_ids)))
            if mixed_ids not in {swsd_ids, proposal_ids}:
                mixed_roads = {**t01_roads, **proposal_roads}
                _merge_option(
                    group_rows,
                    candidate_target="MIXED_CARRIER",
                    target_kind="ROAD",
                    payload=mixed_ids,
                    source_kind="REGISTERED_STRATEGY_PROPOSAL",
                    artifact=refs["proposal_roads"],
                    road_payloads=mixed_roads,
                    artifact_payload_ids=tuple(
                        road_id for road_id in mixed_ids if road_id in proposal_roads
                    ),
                )
                _merge_option(
                    group_rows,
                    candidate_target="MIXED_CARRIER",
                    target_kind="ROAD",
                    payload=mixed_ids,
                    source_kind="SWSD_IDENTITY",
                    artifact=refs["t01_roads"],
                    road_payloads=mixed_roads,
                    artifact_payload_ids=tuple(
                        road_id for road_id in mixed_ids if road_id not in proposal_roads
                    ),
                )
        _merge_option(
            group_rows,
            candidate_target="REVIEW_FALLBACK",
            target_kind="UNKNOWN",
            payload=(),
            source_kind="SAFE_FALLBACK",
            artifact=refs["strategy_run_summary"],
            road_payloads={},
        )
        for option in group_rows.values():
            candidates.append(
                SchemeAP1Candidate.create(
                    case_key=str(skeleton["case_key"]),
                    family=str(skeleton["family"]),
                    business_id=str(skeleton["business_id"]),
                    object_type="SEGMENT",
                    object_id=segment_id,
                    candidate_target=option["candidate_target"],
                    target_kind=option["target_kind"],
                    target_payload=option["payload"],
                    source_kinds=tuple(option["source_kinds"]),
                    object_tokens=object_tokens,
                    candidate_tokens=tuple(option["candidate_tokens"]),
                    context_tokens=context_tokens,
                    numeric_features=option["numeric_features"],
                    payload_artifacts=tuple(option["artifacts"]),
                    payload_artifact_by_id=tuple(option["artifact_by_id"]),
                    hard_unsafe=hard_unsafe,
                )
            )

    t01_access = _t01_access_builder(t01_nodes)
    for movement in sorted(skeleton["physical_movements"], key=lambda row: row["movement_id"]):
        from_segment, _ = split_segment_access(str(movement["from_segment_access"]))
        to_segment, _ = split_segment_access(str(movement["to_segment_access"]))
        junction_id = str(movement["junction_id"])
        object_tokens = _movement_object_tokens(
            segment_by_id.get(from_segment, {}),
            segment_by_id.get(to_segment, {}),
            junction_degree.get(junction_id, 0),
        ) + (
            f"PROPOSAL_JUNCTION_CONFLICT:{junction_id in proposal_conflict_junctions}",
            f"FROM_SEGMENT_HARD_UNSAFE:{segment_hard_unsafe.get(from_segment, True)}",
            f"TO_SEGMENT_HARD_UNSAFE:{segment_hard_unsafe.get(to_segment, True)}",
        )
        context_tokens = (
            f"CONTEXT_JUNCTION_DEGREE:{_count_bucket(junction_degree.get(junction_id, 0))}",
            f"CONTEXT_FROM_MOVEMENT_DEGREE:{_count_bucket(movement_by_segment[from_segment])}",
            f"CONTEXT_TO_MOVEMENT_DEGREE:{_count_bucket(movement_by_segment[to_segment])}",
            f"CONTEXT_PROPOSAL_JUNCTION_CONFLICT:{junction_id in proposal_conflict_junctions}",
        )
        group_rows = {}
        swsd_nodes = tuple(sorted(set(t01_access(junction_id)) & set(t01_nodes)))
        if swsd_nodes:
            _merge_node_option(
                group_rows,
                payload=swsd_nodes,
                source_kind="SWSD_IDENTITY",
                artifact=refs["t01_nodes"],
            )
        from_relation = relation_by_segment.get(from_segment, {})
        to_relation = relation_by_segment.get(to_segment, {})
        from_nodes = proposal_closure(
            {junction_id, *_mapped_nodes(from_relation, junction_id)}
        )
        to_nodes = proposal_closure(
            {junction_id, *_mapped_nodes(to_relation, junction_id)}
        )
        proposal_node_ids = tuple(
            sorted(set(from_nodes) & set(to_nodes) & set(proposal_nodes))
        )
        if proposal_node_ids:
            _merge_node_option(
                group_rows,
                payload=proposal_node_ids,
                source_kind="REGISTERED_STRATEGY_PROPOSAL",
                artifact=refs["proposal_nodes"],
            )
        _merge_node_option(
            group_rows,
            payload=(),
            source_kind="SAFE_FALLBACK",
            artifact=refs["strategy_run_summary"],
            fallback=True,
        )
        hard_unsafe = (
            not proposal_node_ids
            or junction_id in proposal_conflict_junctions
        )
        for option in group_rows.values():
            candidates.append(
                SchemeAP1Candidate.create(
                    case_key=str(skeleton["case_key"]),
                    family=str(skeleton["family"]),
                    business_id=str(skeleton["business_id"]),
                    object_type="MOVEMENT",
                    object_id=str(movement["movement_id"]),
                    candidate_target=option["candidate_target"],
                    target_kind=option["target_kind"],
                    target_payload=option["payload"],
                    source_kinds=tuple(option["source_kinds"]),
                    object_tokens=object_tokens,
                    candidate_tokens=tuple(option["candidate_tokens"]),
                    context_tokens=context_tokens,
                    numeric_features=option["numeric_features"],
                    payload_artifacts=tuple(option["artifacts"]),
                    payload_artifact_by_id=tuple(option["artifact_by_id"]),
                    hard_unsafe=hard_unsafe,
                )
            )

    lineage = [
        {
            "case_key": skeleton["case_key"],
            "role": role,
            "path": str(path.resolve()),
            "sha256": _sha256_file(path),
            "size_bytes": _io_path(path).stat().st_size,
            "label_only": False,
            "truth_derived": False,
        }
        for role, path in sorted(paths.items())
    ]
    lineage.extend(
        [
            {
                "case_key": skeleton["case_key"],
                "role": "strategy_run_summary",
                "path": str(run_summary_path.resolve()),
                "sha256": _sha256_file(run_summary_path),
                "size_bytes": run_summary_path.stat().st_size,
                "label_only": False,
                "truth_derived": False,
            },
            {
                "case_key": skeleton["case_key"],
                "role": "frozen_business_skeleton",
                "path": str(skeleton_path.resolve()),
                "sha256": _sha256_file(skeleton_path),
                "size_bytes": skeleton_path.stat().st_size,
                "label_only": False,
                "truth_derived": False,
            },
        ]
    )
    return candidates, lineage, canonical_crs


def _merge_option(
    output: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]],
    *,
    candidate_target: str,
    target_kind: str,
    payload: tuple[str, ...],
    source_kind: str,
    artifact: tuple[str, str, str],
    road_payloads: Mapping[str, dict[str, Any]],
    artifact_payload_ids: tuple[str, ...] | None = None,
) -> None:
    key = candidate_target, target_kind, tuple(sorted(payload))
    stats, tokens = _road_features(payload, road_payloads)
    row = output.setdefault(
        key,
        {
            "candidate_target": candidate_target,
            "target_kind": target_kind,
            "payload": tuple(sorted(payload)),
            "source_kinds": set(),
            "artifacts": set(),
            "artifact_by_id": set(),
            "candidate_tokens": set(tokens),
            "numeric_features": stats,
        },
    )
    row["source_kinds"].add(source_kind)
    row["artifacts"].add(artifact)
    for payload_id in artifact_payload_ids if artifact_payload_ids is not None else payload:
        row["artifact_by_id"].add((str(payload_id), *artifact))
    row["candidate_tokens"].add(f"OPTION:{candidate_target}")
    row["candidate_tokens"].add(f"SOURCE:{source_kind}")


def _merge_node_option(
    output: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]],
    *,
    payload: tuple[str, ...],
    source_kind: str,
    artifact: tuple[str, str, str],
    fallback: bool = False,
) -> None:
    target = "REVIEW_FALLBACK" if fallback else "USE_RCSD"
    kind = "UNKNOWN" if fallback else "NODE"
    key = target, kind, tuple(sorted(payload))
    count = len(payload)
    row = output.setdefault(
        key,
        {
            "candidate_target": target,
            "target_kind": kind,
            "payload": tuple(sorted(payload)),
            "source_kinds": set(),
            "artifacts": set(),
            "artifact_by_id": set(),
            "candidate_tokens": {
                f"OPTION:{target}",
                f"NODE_COUNT:{_count_bucket(count)}",
            },
            "numeric_features": (
                math.log1p(count),
                float(count > 0),
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ),
        },
    )
    row["source_kinds"].add(source_kind)
    row["artifacts"].add(artifact)
    for payload_id in payload:
        row["artifact_by_id"].add((str(payload_id), *artifact))
    row["candidate_tokens"].add(f"SOURCE:{source_kind}")


def _road_features(
    road_ids: Iterable[str], roads: Mapping[str, dict[str, Any]]
) -> tuple[tuple[float, ...], tuple[str, ...]]:
    payloads = [roads[road_id] for road_id in road_ids if road_id in roads]
    lengths: list[float] = []
    endpoints: set[str] = set()
    directions: set[str] = set()
    sources: Counter[str] = Counter()
    edges: list[tuple[str, str]] = []
    for payload in payloads:
        geometry = payload.get("geometry")
        if geometry:
            try:
                lengths.append(float(shape(geometry).length))
            except (TypeError, ValueError):
                lengths.append(0.0)
        properties = dict(payload.get("properties") or {})
        start = _text(_property(properties, "snodeid"))
        end = _text(_property(properties, "enodeid"))
        if start:
            endpoints.add(start)
        if end:
            endpoints.add(end)
        if start and end:
            edges.append((start, end))
        directions.add(_text(_property(properties, "direction")) or "UNKNOWN")
        sources[_text(_property(properties, "source")) or "UNKNOWN"] += 1
    count = len(payloads)
    total_length = sum(lengths)
    mean_length = total_length / count if count else 0.0
    component_count = _component_count(edges)
    source_two_share = sources.get("2", 0) / count if count else 0.0
    numeric = (
        math.log1p(count),
        math.log1p(total_length),
        math.log1p(mean_length),
        len(endpoints) / max(1, count * 2),
        len(directions) / 4.0,
        source_two_share,
        math.log1p(component_count),
        float(count > 0),
    )
    tokens = (
        f"ROAD_COUNT:{_count_bucket(count)}",
        f"ENDPOINT_COUNT:{_count_bucket(len(endpoints))}",
        f"DIRECTION_VARIANTS:{_count_bucket(len(directions))}",
        f"COMPONENT_COUNT:{_count_bucket(component_count)}",
        f"SOURCE_VARIANTS:{_count_bucket(len(sources))}",
    )
    return numeric, tokens


def _segment_object_tokens(
    segment: Mapping[str, Any], *, movement_count: int, junction_degree: Mapping[str, int]
) -> tuple[str, ...]:
    pair_nodes = [str(value) for value in segment.get("pair_nodes") or []]
    junc_nodes = [str(value) for value in segment.get("junc_nodes") or []]
    degrees = [junction_degree.get(value, 0) for value in pair_nodes + junc_nodes]
    return (
        f"OBJECT:SEGMENT",
        f"SEGMENT_TYPE:{segment.get('segment_type', 'UNKNOWN')}",
        f"DIRECTION_STRUCTURE:{segment.get('direction_structure', 'UNKNOWN')}",
        f"PAIR_COUNT:{_count_bucket(len(pair_nodes))}",
        f"JUNC_COUNT:{_count_bucket(len(junc_nodes))}",
        f"MOVEMENT_DEGREE:{_count_bucket(movement_count)}",
        f"MAX_JUNCTION_DEGREE:{_count_bucket(max(degrees, default=0))}",
        f"ACCESS_VALID:{bool(segment.get('access_valid'))}",
        f"INDEPENDENT_ROAD_VALID:{bool(segment.get('independent_road_valid'))}",
    )


def _movement_object_tokens(
    from_segment: Mapping[str, Any],
    to_segment: Mapping[str, Any],
    junction_degree: int,
) -> tuple[str, ...]:
    return (
        "OBJECT:MOVEMENT",
        f"FROM_SEGMENT_TYPE:{from_segment.get('segment_type', 'UNKNOWN')}",
        f"TO_SEGMENT_TYPE:{to_segment.get('segment_type', 'UNKNOWN')}",
        f"FROM_DIRECTION:{from_segment.get('direction_structure', 'UNKNOWN')}",
        f"TO_DIRECTION:{to_segment.get('direction_structure', 'UNKNOWN')}",
        f"JUNCTION_DEGREE:{_count_bucket(junction_degree)}",
        f"FROM_ACCESS_VALID:{bool(from_segment.get('access_valid'))}",
        f"TO_ACCESS_VALID:{bool(to_segment.get('access_valid'))}",
    )


def _whitelisted_skeleton_evidence(skeleton: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for segment in skeleton.get("segments") or []:
        for ref in segment.get("evidence_refs") or []:
            if ref.get("role") in {"t01_segment", "t01_roads"}:
                rows.append({key: str(ref.get(key) or "") for key in ("role", "path", "sha256")})
    for junction in skeleton.get("junctions") or []:
        for ref in junction.get("evidence_refs") or []:
            if ref.get("role") == "t01_nodes":
                rows.append({key: str(ref.get(key) or "") for key in ("role", "path", "sha256")})
    return rows


def _single_evidence(rows: list[dict[str, str]], role: str) -> dict[str, str]:
    matches = {(row["path"], row["sha256"]) for row in rows if row["role"] == role}
    if len(matches) != 1:
        raise ValueError(f"expected one {role} evidence, got {len(matches)}")
    path, digest = next(iter(matches))
    return {"role": role, "path": str(_resolve_file(path)), "sha256": digest}


def _mapped_nodes(relation: Mapping[str, Any], junction_id: str) -> tuple[str, ...]:
    for item in _json_list(_property(relation, "swsd_to_frcsd_node_map")):
        if not isinstance(item, Mapping):
            continue
        if _text(item.get("swsd_node_id")) == junction_id:
            return tuple(_text(value) for value in item.get("frcsd_node_ids") or [] if _text(value))
    return ()


def _node_closure(nodes: Mapping[str, dict[str, Any]]) -> Any:
    by_main: dict[str, set[str]] = defaultdict(set)
    by_group: dict[str, set[str]] = defaultdict(set)
    properties_by_id: dict[str, dict[str, Any]] = {}
    for node_id, payload in nodes.items():
        properties = dict(payload.get("properties") or {})
        properties_by_id[node_id] = properties
        mainnode = _text(_property(properties, "mainnodeid"))
        if mainnode and mainnode not in {"0", "0.0"}:
            by_main[mainnode].update({node_id, mainnode})
        group = _text(_property(properties, "semantic_junction_group_id"))
        if group:
            by_group[group].add(node_id)

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
                related.update(by_group.get(group, set()))
            for value in sorted(related - expanded):
                expanded.add(value)
                queue.append(value)
        return tuple(sorted(expanded))

    return expand


def _t01_access_builder(nodes: Mapping[str, dict[str, Any]]) -> Any:
    by_main: dict[str, list[str]] = defaultdict(list)
    for node_id, payload in nodes.items():
        mainnode = _text(_property(dict(payload.get("properties") or {}), "mainnodeid"))
        if mainnode and mainnode not in {"0", "0.0"}:
            by_main[mainnode].append(node_id)

    def access(junction_id: str) -> tuple[str, ...]:
        output = {junction_id, *by_main.get(junction_id, [])}
        payload = nodes.get(junction_id)
        if payload:
            properties = dict(payload.get("properties") or {})
            output.update(_string_list(_property(properties, "subnodeid")))
            mainnode = _text(_property(properties, "mainnodeid"))
            if mainnode and mainnode not in {"0", "0.0"}:
                output.add(mainnode)
                output.update(by_main.get(mainnode, []))
        return tuple(sorted(value for value in output if value))

    return access


def _read_features(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    io_path = _io_path(path)
    layers = fiona.listlayers(io_path)
    if len(layers) != 1:
        raise ValueError(f"expected one vector layer: {path}")
    output: dict[str, dict[str, Any]] = {}
    with fiona.open(io_path, layer=layers[0]) as source:
        crs = source.crs_wkt or str(source.crs)
        for feature in source:
            properties = dict(feature["properties"])
            identifier = _text(_property(properties, "id"))
            if not identifier:
                continue
            geometry = dict(feature["geometry"]) if feature["geometry"] is not None else None
            if identifier in output:
                raise ValueError(f"duplicate feature ID {identifier}: {path}")
            output[identifier] = {"properties": properties, "geometry": geometry}
    return output, crs


def _read_properties(path: Path) -> tuple[list[dict[str, Any]], str]:
    io_path = _io_path(path)
    layers = fiona.listlayers(io_path)
    if len(layers) != 1:
        raise ValueError(f"expected one vector layer: {path}")
    with fiona.open(io_path, layer=layers[0]) as source:
        return [dict(feature["properties"]) for feature in source], source.crs_wkt or str(source.crs)


def _verified_artifacts(path: Path, strict_hashes: bool) -> list[Path]:
    manifest = _read_json(path)
    output: list[Path] = []
    for record in manifest.get("artifacts") or []:
        artifact = _resolve_file(record["path"])
        if strict_hashes and _sha256_file(artifact) != record["sha256"]:
            raise ValueError(f"artifact hash mismatch: {artifact}")
        output.append(artifact)
    return output


def _component_count(edges: list[tuple[str, str]]) -> int:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for start, end in edges:
        adjacency[start].add(end)
        adjacency[end].add(start)
    unseen = set(adjacency)
    count = 0
    while unseen:
        count += 1
        queue = [unseen.pop()]
        while queue:
            node = queue.pop()
            for neighbor in adjacency[node] & unseen:
                unseen.remove(neighbor)
                queue.append(neighbor)
    return count


def _count_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value <= 2:
        return str(value)
    if value <= 4:
        return "3_4"
    if value <= 8:
        return "5_8"
    if value <= 16:
        return "9_16"
    return "17_PLUS"


def _canonical_crs(value: Any) -> str:
    crs = CRS.from_user_input(value)
    authority = crs.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else crs.to_wkt()


def _handoff_path(handoffs: Mapping[str, Any], role: str) -> Path:
    value = handoffs.get(role)
    if not value:
        raise ValueError(f"strategy replay handoff missing: {role}")
    return _resolve_file(str(value))


def _resolve_dir(path: Path | str) -> Path:
    resolved = _absolute_path(path)
    if not _io_path(resolved).is_dir():
        raise NotADirectoryError(resolved)
    return resolved


def _resolve_file(path: Path | str) -> Path:
    resolved = _absolute_path(path)
    if not _io_path(resolved).is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _absolute_path(path: Path | str) -> Path:
    normalized = normalize_runtime_path(path)
    return normalized if normalized.is_absolute() else normalized.absolute()


def _io_path(path: Path | str) -> Path:
    absolute = _absolute_path(path)
    raw = str(absolute)
    if platform.system() == "Windows" and not raw.startswith("\\\\?\\") and len(raw) >= 248:
        return Path("\\\\?\\" + raw)
    return absolute


def _sha256_file(path: Path | str) -> str:
    return sha256_file(_io_path(path))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(_io_path(path).read_text(encoding="utf-8"))


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
    return next(
        (value for key, value in properties.items() if str(key).casefold() == folded),
        None,
    )


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            stream.write("\n")


def _dedupe_lineage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(
        {
            (row["case_key"], row["role"], row["path"], row["sha256"]): row
            for row in rows
        }.values()
    )


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * quantile) - 1))
    return ordered[index]


__all__ = ["build_scheme_a_p1_candidate_run", "classify_segment_candidate"]
