from __future__ import annotations

import csv
import ctypes
import ctypes.wintypes
import importlib.metadata
import json
import os
import platform
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from pyproj import CRS

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    EvidenceRef,
    JSGCaseTruth,
    split_segment_access,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_fallback import (
    resolve_scheme_a_fallback,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_labels import (
    build_scheme_a_carrier_labels,
    label_weight as _label_weight,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    CarrierKind,
    CarrierLabel,
    CarrierTarget,
    ClueScope,
    FallbackPlan,
    FallbackUnit,
    FrozenJunction,
    FrozenJunctionSegmentRelation,
    FrozenPhysicalMovement,
    FrozenSchemeACase,
    FrozenSegment,
    RealityChangeClue,
    SchemeABaselineConfig,
    SegmentType,
    StrategyBaselineRecord,
    StrategyOutcome,
    canonical_sha256,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


SCHEME_A_MANIFEST_VERSION = "p05-scheme-a-baseline-manifest-v1"
FORWARD_DIRECTIONS = {0, 1, 2}
REVERSE_DIRECTIONS = {0, 1, 3}


def build_scheme_a_baseline_run(config: SchemeABaselineConfig) -> Path:
    started_at = datetime.now(timezone.utc)
    started_perf = time.perf_counter()
    started_cpu = time.process_time()
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(f"Scheme A run root already exists: {run_root}")

    p0_root = normalize_runtime_path(config.jsg_p0_run_root).resolve(strict=True)
    m0_root = normalize_runtime_path(config.m0_run_root).resolve(strict=True)
    p0_manifest_path = p0_root / "run_manifest.json"
    m0_manifest_path = m0_root / "p05_m0_manifest.json"
    p0_manifest = _validated_p0_manifest(p0_manifest_path, config)
    m0_manifest = _validated_m0_manifest(m0_manifest_path, config)
    p0_outputs = _verified_outputs(p0_manifest, strict_hashes=config.strict_hashes)
    m0_outputs = _verified_outputs(m0_manifest, strict_hashes=config.strict_hashes)

    p0_cases = _read_csv(p0_outputs["case_inventory"])
    if len(p0_cases) != config.expected_case_count:
        raise ValueError(
            f"Scheme A requires {config.expected_case_count} P0 Cases, got {len(p0_cases)}"
        )
    samples = _read_csv(m0_outputs["samples"])
    splits = {row["sample_id"]: int(row["fold"]) for row in _read_csv(m0_outputs["split"])}
    samples_by_key = {(row["family"], row["business_id"]): row for row in samples}

    run_root.mkdir(parents=True)
    cases_root = run_root / "cases"
    cases_root.mkdir()
    case_rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    labels: list[CarrierLabel] = []
    clues: list[RealityChangeClue] = []
    fallbacks: list[FallbackPlan] = []
    case_signatures: dict[str, str] = {}
    case_seconds: list[float] = []
    validation_totals: Counter[str] = Counter()
    peak_rss = _rss_bytes()

    for inventory_row in sorted(p0_cases, key=lambda row: row["case_key"]):
        case_started = time.perf_counter()
        family = inventory_row["family"]
        business_id = inventory_row["business_id"]
        if business_id in config.excluded_business_ids:
            raise ValueError(f"excluded business id leaked into P0 Case inventory: {business_id}")
        sample = samples_by_key.get((family, business_id))
        if sample is None:
            raise ValueError(f"M0 sample is missing for {family}:{business_id}")
        sample_id = sample["sample_id"]
        if sample_id not in splits:
            raise ValueError(f"M0 split is missing for {sample_id}")
        if config.enforce_poc_scope:
            _require_under_root(sample["case_root"], config.poc_data_root)

        historical_case_root = normalize_runtime_path(inventory_row["case_root"]).resolve(strict=True)
        truth_path = historical_case_root / "jsg_truth.json"
        _validate_case_artifacts(historical_case_root, truth_path, config.strict_hashes)
        truth = JSGCaseTruth.from_dict(_read_json(truth_path))
        if truth.case_key != inventory_row["case_key"]:
            raise ValueError(f"historical Case key mismatch: {truth.case_key}")
        if not truth.label_only or truth.content_repair or truth.silent_fix:
            raise ValueError(f"historical JSG truth is not label-only/no-repair: {truth.case_key}")

        built = _build_case(
            truth=truth,
            sample=sample,
            fold=splits[sample_id],
            strict_hashes=config.strict_hashes,
        )
        frozen_case, case_baselines, case_labels, case_clues, stats = built
        signature = frozen_case.skeleton_signature()
        clue_groups: dict[tuple[ClueScope, str], list[str]] = defaultdict(list)
        for clue in case_clues:
            clue_groups[(clue.scope, clue.object_id)].append(clue.clue_id)
        for (scope, object_id), clue_ids in sorted(
            clue_groups.items(), key=lambda item: (item[0][0].value, item[0][1])
        ):
            fallbacks.append(
                resolve_scheme_a_fallback(
                    frozen_case,
                    scope,
                    object_id,
                    clue_ids=tuple(clue_ids),
                )
            )
        for baseline in case_baselines:
            if baseline.outcome is not StrategyOutcome.FAIL:
                continue
            fallbacks.append(
                replace(
                    resolve_scheme_a_fallback(
                        frozen_case,
                        ClueScope.SEGMENT,
                        baseline.segment_id,
                    ),
                    trigger=f"STRATEGY_FAIL:{baseline.segment_id}",
                )
            )

        token = canonical_sha256(truth.case_key)[:20]
        case_output = cases_root / token / "frozen_skeleton.json"
        case_output.parent.mkdir()
        write_json(case_output, frozen_case.to_dict())
        case_signatures[truth.case_key] = signature
        case_elapsed = time.perf_counter() - case_started
        case_seconds.append(case_elapsed)
        peak_rss = max(peak_rss, _rss_bytes())

        case_rows.append(
            {
                "case_key": truth.case_key,
                "sample_id": sample_id,
                "family": truth.family,
                "business_id": truth.business_id,
                "fold": splits[sample_id],
                "crs": frozen_case.crs,
                "junction_count": len(frozen_case.junctions),
                "segment_count": len(frozen_case.segments),
                "advance_right_count": sum(
                    item.segment_type is SegmentType.ADVANCE_RIGHT for item in frozen_case.segments
                ),
                "relation_count": len(frozen_case.junction_segment_relations),
                "physical_movement_count": len(frozen_case.physical_movements),
                "strategy_record_count": len(case_baselines),
                "carrier_label_count": len(case_labels),
                "reality_change_clue_count": len(case_clues),
                "skeleton_signature": signature,
                "case_wall_seconds": case_elapsed,
                "frozen_skeleton": str(case_output.relative_to(run_root)),
            }
        )
        segment_rows.extend(_segment_inventory_rows(frozen_case, case_baselines))
        baseline_rows.extend(row.to_dict() for row in case_baselines)
        labels.extend(case_labels)
        clues.extend(case_clues)
        validation_totals.update(stats)

    labels.sort(key=lambda row: (row.case_key, row.object_type, row.object_id))
    clues = sorted(
        {row.clue_id: row for row in clues}.values(),
        key=lambda row: (row.case_key, row.scope.value, row.object_id, row.code),
    )
    fallbacks.sort(key=lambda row: (row.case_key, row.trigger, row.clue_ids))
    case_rows.sort(key=lambda row: row["case_key"])
    segment_rows.sort(key=lambda row: (row["case_key"], row["segment_id"]))
    baseline_rows.sort(key=lambda row: (row["case_key"], row["segment_id"]))

    _assert_output_invariants(
        case_rows=case_rows,
        segment_rows=segment_rows,
        baseline_rows=baseline_rows,
        labels=labels,
        clues=clues,
        fallbacks=fallbacks,
        expected_case_count=config.expected_case_count,
    )
    _write_run_tables(run_root, case_rows, segment_rows, baseline_rows, labels, clues, fallbacks)

    wall_seconds = time.perf_counter() - started_perf
    cpu_seconds = time.process_time() - started_cpu
    p95_seconds = _percentile(case_seconds, 0.95)
    max_seconds = max(case_seconds, default=0.0)
    performance = {
        "wall_seconds": wall_seconds,
        "cpu_seconds": cpu_seconds,
        "case_p95_wall_seconds": p95_seconds,
        "case_max_wall_seconds": max_seconds,
        "peak_rss_bytes": peak_rss,
        "gpu_required": False,
        "passed": (
            wall_seconds <= 15 * 60
            and cpu_seconds <= 60 * 60
            and p95_seconds <= 30
            and max_seconds <= 120
            and 0 < peak_rss <= 16 * 1024**3
        ),
    }
    signatures = {
        "skeleton": canonical_sha256(case_signatures),
        "strategy_baseline": canonical_sha256(baseline_rows),
        "carrier_labels": canonical_sha256([row.to_dict() for row in labels]),
        "reality_change_clues": canonical_sha256([row.to_dict() for row in clues]),
        "fallback_plans": canonical_sha256([row.to_dict() for row in fallbacks]),
    }
    summary = _build_summary(
        case_rows,
        segment_rows,
        baseline_rows,
        labels,
        clues,
        fallbacks,
        signatures,
        validation_totals,
        performance,
    )
    write_json(run_root / "scheme_a_summary.json", summary)
    (run_root / "validation_report.md").write_text(
        _validation_report(summary), encoding="utf-8"
    )

    completed_at = datetime.now(timezone.utc)
    run_manifest = {
        "schema_version": SCHEME_A_MANIFEST_VERSION,
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "passed" if summary["gate_pass"] else "failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "parameters": {
            "jsg_p0_run_root": str(p0_root),
            "m0_run_root": str(m0_root),
            "poc_data_root": str(normalize_runtime_path(config.poc_data_root).resolve()),
            "expected_case_count": config.expected_case_count,
            "excluded_business_ids": list(config.excluded_business_ids),
            "strict_hashes": config.strict_hashes,
            "enforce_poc_scope": config.enforce_poc_scope,
        },
        "input_manifests": {
            "jsg_p0": {"path": str(p0_manifest_path), "sha256": sha256_file(p0_manifest_path)},
            "m0": {"path": str(m0_manifest_path), "sha256": sha256_file(m0_manifest_path)},
        },
        "implementation": _implementation_records(),
        "signatures": signatures,
        "counts": summary["counts"],
        "performance": performance,
        "environment": _environment(),
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "label_only": True,
        "outputs": {
            "summary": output_record(run_root / "scheme_a_summary.json"),
            "case_inventory": output_record(run_root / "case_inventory.csv"),
            "segment_inventory": output_record(run_root / "segment_inventory.csv"),
            "strategy_baseline": output_record(run_root / "strategy_baseline.csv"),
            "carrier_labels": output_record(run_root / "carrier_labels.jsonl"),
            "reality_change_clues": output_record(run_root / "reality_change_clues.jsonl"),
            "fallback_plans": output_record(run_root / "fallback_plans.jsonl"),
            "report": output_record(run_root / "validation_report.md"),
        },
    }
    write_json(run_root / "scheme_a_manifest.json", run_manifest)
    formal_outputs = [
        path
        for path in sorted(run_root.rglob("*"))
        if path.is_file() and path.name != "artifact_manifest.json"
    ]
    artifact_manifest = {
        "schema_version": "p05-scheme-a-artifact-manifest-v1",
        "artifacts": [output_record(path) for path in formal_outputs],
    }
    write_json(run_root / "artifact_manifest.json", artifact_manifest)
    if not summary["gate_pass"]:
        raise RuntimeError(f"Scheme A baseline gate failed; evidence preserved at {run_root}")
    return run_root


def _build_case(
    *,
    truth: JSGCaseTruth,
    sample: Mapping[str, str],
    fold: int,
    strict_hashes: bool,
) -> tuple[
    FrozenSchemeACase,
    list[StrategyBaselineRecord],
    list[CarrierLabel],
    list[RealityChangeClue],
    Counter[str],
]:
    roles = _evidence_roles(truth)
    required = {"t01_segment", "t01_roads", "t06_segment_relation_truth"}
    missing = sorted(required - roles.keys())
    if missing:
        raise ValueError(f"{truth.case_key}: evidence roles missing {missing}")
    t01_segment = normalize_runtime_path(roles["t01_segment"].path).resolve(strict=True)
    t01_roads = normalize_runtime_path(roles["t01_roads"].path).resolve(strict=True)
    t01_nodes = (t01_roads.parent / "nodes.gpkg").resolve(strict=True)
    t06_relation = normalize_runtime_path(roles["t06_segment_relation_truth"].path).resolve(
        strict=True
    )
    truth_node = normalize_runtime_path(truth.carrier_realization.expected_truth_node).resolve(
        strict=True
    )
    truth_road = normalize_runtime_path(truth.carrier_realization.expected_truth_road).resolve(
        strict=True
    )
    source_hashes = dict(truth.source_hashes)
    carrier_hashes = dict(truth.carrier_realization.artifact_hashes)
    expected_hashes = {
        t01_segment: source_hashes["t01_segment"],
        t01_roads: source_hashes["t01_roads"],
        t01_nodes: source_hashes["t01_nodes"],
        t06_relation: source_hashes["t06_segment_relation_truth"],
        truth_node: carrier_hashes["truth_node"],
        truth_road: carrier_hashes["truth_road"],
    }
    if strict_hashes:
        for path, expected in expected_hashes.items():
            if sha256_file(path) != expected:
                raise ValueError(f"{truth.case_key}: source hash mismatch: {path}")

    segment_records, segment_crs, segment_geometry_ok = _read_vector(t01_segment)
    road_records, road_crs, road_geometry_ok = _read_vector(t01_roads)
    node_records, node_crs, node_geometry_ok = _read_vector(t01_nodes)
    relation_records, relation_crs, relation_geometry_ok = _read_vector(t06_relation)
    final_node_records, final_node_crs, final_node_geometry_ok = _read_vector(truth_node)
    final_road_records, final_road_crs, final_road_geometry_ok = _read_vector(truth_road)
    crs = _require_single_crs(
        truth.case_key,
        {
        segment_crs,
        road_crs,
        node_crs,
        relation_crs,
        final_node_crs,
        final_road_crs,
        _canonical_crs(truth.crs),
        },
    )

    segment_evidence = EvidenceRef("t01_segment", str(t01_segment), expected_hashes[t01_segment])
    road_evidence = EvidenceRef("t01_roads", str(t01_roads), expected_hashes[t01_roads])
    node_evidence = EvidenceRef("t01_nodes", str(t01_nodes), expected_hashes[t01_nodes])
    relation_evidence = EvidenceRef(
        "t06_segment_relation_truth", str(t06_relation), expected_hashes[t06_relation]
    )
    final_node_evidence = EvidenceRef(
        "t06_frcsd_node_truth", str(truth_node), expected_hashes[truth_node]
    )

    roads = {_text(row.get("id")): row for row in road_records if _text(row.get("id"))}
    nodes = {_text(row.get("id")): row for row in node_records if _text(row.get("id"))}
    final_nodes = {
        _text(row.get("id")): row for row in final_node_records if _text(row.get("id"))
    }
    final_roads = {
        _text(row.get("id")): row for row in final_road_records if _text(row.get("id"))
    }
    relation_by_segment = _unique_index(
        relation_records, "swsd_segment_id", f"{truth.case_key}: T06 relation"
    )
    old_segments = {row.segment_id: row for row in truth.standard_segments}
    old_relations = {
        (row.junction_id, row.segment_id): row for row in truth.junction_segment_relations
    }
    old_junctions = {row.junction_id: row for row in truth.junction_units}
    final_main_members = _main_members(final_nodes)
    t01_main_members = _main_members(nodes)

    preparsed_segments: dict[str, dict[str, Any]] = {}
    for raw in segment_records:
        segment_id = _text(raw.get("id"))
        if not segment_id:
            raise ValueError(f"{truth.case_key}: empty T01 Segment id")
        if segment_id in preparsed_segments:
            raise ValueError(f"{truth.case_key}: duplicate T01 Segment id {segment_id}")
        preparsed_segments[segment_id] = {
            "pair_nodes": tuple(_string_list(raw.get("pair_nodes"))),
            "junc_nodes": tuple(_string_list(raw.get("junc_nodes"))),
            "road_ids": tuple(_string_list(raw.get("roads"))),
            "segment_type": (
                SegmentType.ADVANCE_RIGHT
                if _text(raw.get("segment_type")).lower() == "advance_right"
                else SegmentType.STANDARD
            ),
        }
        if (
            preparsed_segments[segment_id]["segment_type"] is SegmentType.STANDARD
            and len(preparsed_segments[segment_id]["pair_nodes"]) != 2
        ):
            raise ValueError(
                f"{truth.case_key}: Standard Segment must have exactly two pair_nodes: {segment_id}"
            )
    road_owners: dict[str, str] = {}
    for segment_id, record in preparsed_segments.items():
        for road_id in record["road_ids"]:
            existing_owner = road_owners.get(road_id)
            if existing_owner is not None and existing_owner != segment_id:
                raise ValueError(
                    f"{truth.case_key}: SWSD Road {road_id} has multiple Segment owners: "
                    f"{existing_owner}, {segment_id}"
                )
            road_owners[road_id] = segment_id
    standard_node_to_segments: dict[str, set[str]] = defaultdict(set)
    for segment_id, record in preparsed_segments.items():
        if record["segment_type"] is not SegmentType.STANDARD:
            continue
        for road_id in record["road_ids"]:
            road = roads.get(road_id)
            if road is None:
                continue
            for node_id in (_text(road.get("snodeid")), _text(road.get("enodeid"))):
                for access_node in _node_access_closure(node_id, nodes, t01_main_members):
                    standard_node_to_segments[access_node].add(segment_id)

    frozen_segments: list[FrozenSegment] = []
    baselines: list[StrategyBaselineRecord] = []
    clues: list[RealityChangeClue] = []
    parsed_segments: dict[str, dict[str, Any]] = {}
    for segment_id, record in sorted(preparsed_segments.items()):
        pair_nodes = record["pair_nodes"]
        junc_nodes = record["junc_nodes"]
        road_ids = record["road_ids"]
        segment_type = record["segment_type"]
        missing_roads = sorted(set(road_ids) - roads.keys())
        missing_endpoints = sorted(
            {
                endpoint
                for road_id in road_ids
                if road_id in roads
                for endpoint in (_text(roads[road_id].get("snodeid")), _text(roads[road_id].get("enodeid")))
                if endpoint and endpoint not in nodes
            }
        )
        independent_valid = bool(road_ids) and not missing_roads and not missing_endpoints
        independent_valid = independent_valid and segment_geometry_ok.get(segment_id, False)
        independent_valid = independent_valid and all(
            road_geometry_ok.get(road_id, False) for road_id in road_ids if road_id in roads
        )
        direction_structure = (
            "DIRECTED"
            if segment_type is SegmentType.ADVANCE_RIGHT
            else old_segments.get(segment_id).direction_structure.value
            if segment_id in old_segments
            else "UNKNOWN"
        )
        evidence = (
            EvidenceRef(**{**asdict(segment_evidence), "object_id": segment_id}),
            EvidenceRef(**{**asdict(road_evidence), "object_id": segment_id}),
        )
        source_segment_access = ""
        target_segment_access = ""
        access_valid = True
        if segment_type is SegmentType.ADVANCE_RIGHT:
            source_nodes, target_nodes = _directed_carrier_terminals(road_ids, roads)
            source_candidates = {
                candidate
                for node_id in source_nodes
                for access_node in _node_access_closure(node_id, nodes, t01_main_members)
                for candidate in standard_node_to_segments.get(access_node, set())
            }
            target_candidates = {
                candidate
                for node_id in target_nodes
                for access_node in _node_access_closure(node_id, nodes, t01_main_members)
                for candidate in standard_node_to_segments.get(access_node, set())
            }
            access_valid = (
                len(source_nodes) == 1
                and len(target_nodes) == 1
                and len(source_candidates) == 1
                and len(target_candidates) == 1
            )
            if access_valid:
                source_segment_access = f"{next(iter(source_candidates))}@{source_nodes[0]}"
                target_segment_access = f"{next(iter(target_candidates))}@{target_nodes[0]}"
        frozen_segments.append(
            FrozenSegment(
                segment_id=segment_id,
                segment_type=segment_type,
                pair_nodes=pair_nodes,
                junc_nodes=junc_nodes,
                swsd_road_ids=road_ids,
                direction_structure=direction_structure,
                independent_road_valid=independent_valid,
                source_segment_access=source_segment_access,
                target_segment_access=target_segment_access,
                access_valid=access_valid,
                evidence_refs=evidence,
            )
        )
        parsed_segments[segment_id] = {
            "pair_nodes": pair_nodes,
            "junc_nodes": junc_nodes,
            "road_ids": road_ids,
            "segment_type": segment_type,
        }
        if not access_valid:
            clues.append(
                RealityChangeClue.create(
                    case_key=truth.case_key,
                    scope=ClueScope.SEGMENT,
                    object_id=segment_id,
                    code="ADVANCE_RIGHT_ACCESS_UNRESOLVED",
                    detail=(
                        f"source_nodes={list(source_nodes)}; target_nodes={list(target_nodes)}; "
                        f"source_candidates={sorted(source_candidates)}; "
                        f"target_candidates={sorted(target_candidates)}"
                    ),
                    evidence_refs=evidence,
                    recommended_fallback=FallbackUnit.SEGMENT,
                )
            )
        if not independent_valid:
            detail = (
                f"independent SWSD Road invalid; missing_roads={missing_roads}; "
                f"missing_endpoint_nodes={missing_endpoints}; segment_geometry_ok="
                f"{segment_geometry_ok.get(segment_id, False)}"
            )
            clues.append(
                RealityChangeClue.create(
                    case_key=truth.case_key,
                    scope=ClueScope.SEGMENT,
                    object_id=segment_id,
                    code="SWSD_INDEPENDENT_ROAD_INVALID",
                    detail=detail,
                    evidence_refs=evidence,
                    recommended_fallback=FallbackUnit.SEGMENT,
                )
            )
        relation_raw = relation_by_segment.get(segment_id)
        if relation_raw is None:
            raise ValueError(f"{truth.case_key}: T06 relation missing Segment {segment_id}")
        baseline = _strategy_record(
            truth.case_key,
            segment_id,
            relation_raw,
            road_ids,
            relation_evidence,
        )
        baselines.append(baseline)
        missing_selected = sorted(set(baseline.selected_road_ids) - final_roads.keys())
        if baseline.outcome is StrategyOutcome.SUCCESS_DIRECT and not baseline.selected_road_ids:
            missing_selected.append("<empty>")
        if baseline.outcome is not StrategyOutcome.FAIL and missing_selected:
            clues.append(
                RealityChangeClue.create(
                    case_key=truth.case_key,
                    scope=ClueScope.SEGMENT,
                    object_id=segment_id,
                    code="RCSD_CARRIER_ROAD_MISSING",
                    detail=f"strategy-selected Road absent from final RCSD: {missing_selected}",
                    evidence_refs=(
                        EvidenceRef(
                            relation_evidence.role,
                            relation_evidence.path,
                            relation_evidence.sha256,
                            segment_id,
                        ),
                    ),
                    recommended_fallback=FallbackUnit.SEGMENT,
                )
            )

    if set(relation_by_segment) != set(parsed_segments):
        extras = sorted(set(relation_by_segment) - set(parsed_segments))
        raise ValueError(f"{truth.case_key}: T06 relation contains unknown Segments {extras[:10]}")

    frozen_relations: list[FrozenJunctionSegmentRelation] = []
    junction_segments: dict[str, set[str]] = defaultdict(set)
    for segment_id, record in sorted(parsed_segments.items()):
        for structural_role, junction_ids in (
            ("ENDPOINT", record["pair_nodes"]),
            ("THROUGH", record["junc_nodes"]),
        ):
            for junction_id in dict.fromkeys(junction_ids):
                old = old_relations.get((junction_id, segment_id))
                if old is not None:
                    access_ids = tuple(sorted(set(old.access_legs)))
                    direction_role = old.direction_role.value
                else:
                    t01_access = _node_access_closure(junction_id, nodes, t01_main_members)
                    access_ids = _node_access_closure(
                        junction_id, final_nodes, final_main_members
                    )
                    direction_role = _direction_role(record["road_ids"], t01_access, roads)
                relation_refs = (
                    EvidenceRef(
                        relation_evidence.role,
                        relation_evidence.path,
                        relation_evidence.sha256,
                        segment_id,
                    ),
                    EvidenceRef(road_evidence.role, road_evidence.path, road_evidence.sha256, segment_id),
                )
                frozen_relations.append(
                    FrozenJunctionSegmentRelation(
                        junction_id=junction_id,
                        segment_id=segment_id,
                        structural_role=structural_role,
                        direction_role=direction_role,
                        access_node_ids=access_ids,
                        evidence_refs=relation_refs,
                    )
                )
                junction_segments[junction_id].add(segment_id)
                missing_access = sorted(set(access_ids) - final_nodes.keys())
                if not set(access_ids) & final_nodes.keys():
                    detail = f"Junction {junction_id} has no legal final access Node; candidates={missing_access}"
                    clues.append(
                        RealityChangeClue.create(
                            case_key=truth.case_key,
                            scope=ClueScope.SEGMENT,
                            object_id=segment_id,
                            code="SEGMENT_ACCESS_NODE_MISSING",
                            detail=detail,
                            evidence_refs=relation_refs,
                            recommended_fallback=FallbackUnit.SEGMENT,
                        )
                    )

    frozen_junctions: list[FrozenJunction] = []
    for junction_id, related_segments in sorted(junction_segments.items()):
        old = old_junctions.get(junction_id)
        access_ids = {
            access_id
            for relation in frozen_relations
            if relation.junction_id == junction_id
            for access_id in relation.access_node_ids
            if access_id in final_nodes
        }
        mainnode_ids = sorted(
            {
                mainnode
                for access_id in access_ids
                for mainnode in [_nonzero(final_nodes[access_id].get("mainnodeid"))]
                if mainnode
            }
        )
        junction_refs = (
            EvidenceRef(node_evidence.role, node_evidence.path, node_evidence.sha256, junction_id),
            EvidenceRef(
                final_node_evidence.role,
                final_node_evidence.path,
                final_node_evidence.sha256,
                junction_id,
            ),
        )
        frozen_junctions.append(
            FrozenJunction(
                junction_id=junction_id,
                junction_type=old.junction_type.value if old is not None else "UNCLASSIFIED",
                related_segment_ids=tuple(sorted(related_segments)),
                mainnode_ids=tuple(mainnode_ids),
                evidence_refs=junction_refs,
            )
        )
        if len(mainnode_ids) > 1:
            clues.append(
                RealityChangeClue.create(
                    case_key=truth.case_key,
                    scope=ClueScope.JUNCTION,
                    object_id=junction_id,
                    code="JUNCTION_MAINNODE_CONFLICT",
                    detail=f"one frozen Junction maps to multiple mainnode groups: {mainnode_ids}",
                    evidence_refs=junction_refs,
                    recommended_fallback=FallbackUnit.JUNCTION,
                )
            )

    relation_lookup = {
        (row.junction_id, row.segment_id): row for row in frozen_relations
    }
    movement_candidates: list[tuple[Any, tuple[str, ...]]] = []
    for movement in truth.physical_movements:
        from_segment, _ = split_segment_access(movement.from_segment_access)
        to_segment, _ = split_segment_access(movement.to_segment_access)
        from_relation = relation_lookup.get((movement.junction_id, from_segment))
        to_relation = relation_lookup.get((movement.junction_id, to_segment))
        carrier_ids = tuple(
            sorted(
                set(from_relation.access_node_ids if from_relation else ())
                & set(to_relation.access_node_ids if to_relation else ())
                & final_nodes.keys()
            )
        )
        movement_candidates.append((movement, carrier_ids))
    movement_node_uses: Counter[str] = Counter(
        node_id for _, carrier_ids in movement_candidates for node_id in carrier_ids
    )
    relation_node_uses: Counter[tuple[str, str]] = Counter(
        (relation.junction_id, node_id)
        for relation in frozen_relations
        for node_id in relation.access_node_ids
    )
    frozen_movements: list[FrozenPhysicalMovement] = []
    for movement, carrier_ids in movement_candidates:
        carrier_exclusive = bool(carrier_ids) and all(
            movement_node_uses[node_id] == 1 for node_id in carrier_ids
        )
        affects_shared = any(
            relation_node_uses[(movement.junction_id, node_id)] > 1 for node_id in carrier_ids
        )
        movement_refs = tuple(movement.evidence_refs) + (
            EvidenceRef(
                final_node_evidence.role,
                final_node_evidence.path,
                final_node_evidence.sha256,
                movement.movement_id,
            ),
        )
        frozen_movements.append(
            FrozenPhysicalMovement(
                movement_id=movement.movement_id,
                junction_id=movement.junction_id,
                from_segment_access=movement.from_segment_access,
                to_segment_access=movement.to_segment_access,
                carrier_kind=CarrierKind.NODE if carrier_ids else CarrierKind.UNKNOWN,
                carrier_ids=carrier_ids,
                carrier_exclusive=carrier_exclusive,
                affects_shared_junction_unit=affects_shared,
                evidence_refs=movement_refs,
            )
        )
        if not carrier_ids:
            clues.append(
                RealityChangeClue.create(
                    case_key=truth.case_key,
                    scope=ClueScope.MOVEMENT,
                    object_id=movement.movement_id,
                    code="MOVEMENT_CARRIER_UNAVAILABLE",
                    detail="frozen PhysicalMovement has no shared legal final Node carrier",
                    evidence_refs=movement_refs,
                    recommended_fallback=FallbackUnit.MOVEMENT,
                )
            )

    frozen_case = FrozenSchemeACase(
        case_key=truth.case_key,
        family=truth.family,
        business_id=truth.business_id,
        sample_id=sample["sample_id"],
        fold=fold,
        crs=crs,
        source_manifest=truth.source_manifest,
        source_hashes=tuple(
            sorted(
                {
                    "t01_segment": expected_hashes[t01_segment],
                    "t01_roads": expected_hashes[t01_roads],
                    "t01_nodes": expected_hashes[t01_nodes],
                    "t06_segment_relation_truth": expected_hashes[t06_relation],
                    "t06_frcsd_node_truth": expected_hashes[truth_node],
                    "t06_frcsd_road_truth": expected_hashes[truth_road],
                }.items()
            )
        ),
        junctions=tuple(sorted(frozen_junctions, key=lambda row: row.junction_id)),
        segments=tuple(sorted(frozen_segments, key=lambda row: row.segment_id)),
        junction_segment_relations=tuple(
            sorted(frozen_relations, key=lambda row: (row.junction_id, row.segment_id, row.structural_role))
        ),
        physical_movements=tuple(sorted(frozen_movements, key=lambda row: row.movement_id)),
    )
    signature = frozen_case.skeleton_signature()
    labels = build_scheme_a_carrier_labels(frozen_case, baselines, sample, signature, clues)
    stats = Counter(
        {
            "segment_geometry_missing": sum(not value for value in segment_geometry_ok.values()),
            "road_geometry_missing": sum(not value for value in road_geometry_ok.values()),
            "node_geometry_missing": sum(not value for value in node_geometry_ok.values()),
            "relation_geometry_missing": sum(not value for value in relation_geometry_ok.values()),
            "final_node_geometry_missing": sum(not value for value in final_node_geometry_ok.values()),
            "final_road_geometry_missing": sum(not value for value in final_road_geometry_ok.values()),
            "final_road_endpoint_reference_missing": sum(
                endpoint not in final_nodes
                for road in final_roads.values()
                for endpoint in (_text(road.get("snodeid")), _text(road.get("enodeid")))
                if endpoint
            ),
        }
    )
    return frozen_case, baselines, labels, clues, stats


def _strategy_record(
    case_key: str,
    segment_id: str,
    raw: Mapping[str, Any],
    swsd_road_ids: tuple[str, ...],
    evidence: EvidenceRef,
) -> StrategyBaselineRecord:
    status = _text(raw.get("relation_status"))
    outcome, target = _strategy_mapping(status)
    selected = tuple(_string_list(raw.get("frcsd_road_ids")))
    return StrategyBaselineRecord(
        case_key=case_key,
        segment_id=segment_id,
        relation_status=status,
        relation_reason=_text(raw.get("relation_reason")),
        source_mix=tuple(_string_list(raw.get("source_mix"))),
        outcome=outcome,
        carrier_target=target,
        selected_road_ids=selected,
        swsd_fallback_road_ids=swsd_road_ids,
        lineage=(EvidenceRef(evidence.role, evidence.path, evidence.sha256, segment_id),),
    )


def _strategy_mapping(status: str) -> tuple[StrategyOutcome, CarrierTarget]:
    mapping = {
        "replaced": (StrategyOutcome.SUCCESS_DIRECT, CarrierTarget.USE_RCSD),
        "retained_swsd": (StrategyOutcome.SUCCESS_WITH_FALLBACK, CarrierTarget.KEEP_SWSD),
        "replaced+retained_swsd": (
            StrategyOutcome.SUCCESS_WITH_FALLBACK,
            CarrierTarget.MIXED_CARRIER,
        ),
        "failed": (StrategyOutcome.FAIL, CarrierTarget.REVIEW_FALLBACK),
    }
    if status not in mapping:
        raise ValueError(f"unknown T06 relation_status: {status!r}")
    return mapping[status]


def _segment_inventory_rows(
    case: FrozenSchemeACase, baselines: list[StrategyBaselineRecord]
) -> list[dict[str, Any]]:
    baseline_by_id = {row.segment_id: row for row in baselines}
    return [
        {
            "case_key": case.case_key,
            "family": case.family,
            "business_id": case.business_id,
            "segment_id": segment.segment_id,
            "segment_type": segment.segment_type.value,
            "pair_nodes": segment.pair_nodes,
            "junc_nodes": segment.junc_nodes,
            "swsd_road_ids": segment.swsd_road_ids,
            "direction_structure": segment.direction_structure,
            "independent_road_valid": segment.independent_road_valid,
            "source_segment_access": segment.source_segment_access,
            "target_segment_access": segment.target_segment_access,
            "access_valid": segment.access_valid,
            "strategy_outcome": baseline_by_id[segment.segment_id].outcome.value,
            "carrier_target": baseline_by_id[segment.segment_id].carrier_target.value,
        }
        for segment in case.segments
    ]


def _build_summary(
    case_rows: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    labels: list[CarrierLabel],
    clues: list[RealityChangeClue],
    fallbacks: list[FallbackPlan],
    signatures: dict[str, str],
    validation_totals: Counter[str],
    performance: dict[str, Any],
) -> dict[str, Any]:
    outcomes = Counter(row["outcome"] for row in baseline_rows)
    segment_types = Counter(row["segment_type"] for row in segment_rows)
    label_availability = Counter("available" if row.available else "masked" for row in labels)
    clue_codes = Counter(row.code for row in clues)
    fallback_outcomes = Counter(row.outcome.value for row in fallbacks)
    counts = {
        "case_count": len(case_rows),
        "segment_count": len(segment_rows),
        "advance_right_count": segment_types[SegmentType.ADVANCE_RIGHT.value],
        "physical_movement_count": sum(row["physical_movement_count"] for row in case_rows),
        "strategy_record_count": len(baseline_rows),
        "carrier_label_count": len(labels),
        "reality_change_clue_count": len(clues),
        "fallback_plan_count": len(fallbacks),
        "skeleton_mutation_count": 0,
        "legacy_connector_object_count": 0,
    }
    gate_pass = (
        counts["case_count"] == 51
        and counts["segment_count"] == counts["strategy_record_count"]
        and counts["segment_count"] == 8863
        and counts["advance_right_count"] == 474
        and counts["physical_movement_count"] == 24779
        and counts["legacy_connector_object_count"] == 0
        and counts["skeleton_mutation_count"] == 0
        and not any(validation_totals.values())
        and performance["passed"]
    )
    return {
        "schema_version": "p05-scheme-a-summary-v1",
        "gate_pass": gate_pass,
        "counts": counts,
        "strategy_outcomes": dict(sorted(outcomes.items())),
        "segment_types": dict(sorted(segment_types.items())),
        "carrier_label_availability": dict(sorted(label_availability.items())),
        "reality_change_clue_codes": dict(sorted(clue_codes.items())),
        "fallback_outcomes": dict(sorted(fallback_outcomes.items())),
        "validation_totals": dict(sorted(validation_totals.items())),
        "signatures": signatures,
        "performance": performance,
        "content_repair": False,
        "silent_fix": False,
        "label_only": True,
    }


def _write_run_tables(
    root: Path,
    cases: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    baselines: list[dict[str, Any]],
    labels: list[CarrierLabel],
    clues: list[RealityChangeClue],
    fallbacks: list[FallbackPlan],
) -> None:
    write_csv(root / "case_inventory.csv", cases, list(cases[0]))
    write_csv(root / "segment_inventory.csv", segments, list(segments[0]))
    write_csv(root / "strategy_baseline.csv", baselines, list(baselines[0]))
    _write_jsonl(root / "carrier_labels.jsonl", (row.to_dict() for row in labels))
    _write_jsonl(root / "reality_change_clues.jsonl", (row.to_dict() for row in clues))
    _write_jsonl(root / "fallback_plans.jsonl", (row.to_dict() for row in fallbacks))


def _assert_output_invariants(
    *,
    case_rows: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    labels: list[CarrierLabel],
    clues: list[RealityChangeClue],
    fallbacks: list[FallbackPlan],
    expected_case_count: int,
) -> None:
    if len(case_rows) != expected_case_count:
        raise ValueError("Scheme A Case count changed during build")
    segment_keys = {(row["case_key"], row["segment_id"]) for row in segment_rows}
    baseline_keys = {(row["case_key"], row["segment_id"]) for row in baseline_rows}
    if len(segment_keys) != len(segment_rows) or segment_keys != baseline_keys:
        raise ValueError("Segment inventory and strategy baseline are not one-to-one")
    if any(row.feature_uses_truth or not row.label_only for row in labels):
        raise ValueError("carrier labels violate label-only/no-truth-feature contract")
    if any(not row.lineage for row in labels):
        raise ValueError("carrier label lineage is incomplete")
    if any(not row.evidence_refs for row in clues):
        raise ValueError("RealityChangeClue lineage is incomplete")
    if any(row.skeleton_mutation for row in clues) or any(row.skeleton_mutation for row in fallbacks):
        raise ValueError("clue/fallback attempted to mutate the frozen skeleton")
    clue_ids = {row.clue_id for row in clues}
    fallback_clue_ids = {
        clue_id for row in fallbacks for clue_id in row.clue_ids
    }
    if clue_ids != fallback_clue_ids:
        raise ValueError("RealityChangeClue and fallback plans are not fully linked")
    if any(bool(row.failure_reasons) == (row.outcome.value != "FAIL") for row in fallbacks):
        raise ValueError("fallback outcome is inconsistent with its business failure reasons")


def _validated_p0_manifest(path: Path, config: SchemeABaselineConfig) -> dict[str, Any]:
    manifest = _read_json(path)
    if manifest.get("schema_version") != "p05-jsg-p0-manifest-v1":
        raise ValueError("invalid JSG-P0 manifest schema")
    if manifest.get("status") != "passed" or manifest.get("label_only") is not True:
        raise ValueError("JSG-P0 input must be a passed label-only run")
    if manifest.get("content_repair") is not False or manifest.get("silent_fix") is not False:
        raise ValueError("JSG-P0 input must be no-repair/no-silent-fix")
    parameters = dict(manifest.get("parameters") or {})
    if int(parameters.get("expected_case_count", -1)) != config.expected_case_count:
        raise ValueError("JSG-P0 Case scope differs from Scheme A")
    if tuple(parameters.get("excluded_business_ids") or ()) != config.excluded_business_ids:
        raise ValueError("JSG-P0 exclusion scope differs from Scheme A")
    return manifest


def _validated_m0_manifest(path: Path, config: SchemeABaselineConfig) -> dict[str, Any]:
    manifest = _read_json(path)
    if manifest.get("schema_version") != "p05-m0-manifest-v1":
        raise ValueError("invalid M0 manifest schema")
    if manifest.get("silent_fix") is not False:
        raise ValueError("M0 input must be silent_fix=false")
    declared_root = normalize_runtime_path(manifest["poc_data_root"]).resolve()
    expected_root = normalize_runtime_path(config.poc_data_root).resolve()
    if declared_root != expected_root:
        raise ValueError(f"M0 POC scope mismatch: {declared_root} != {expected_root}")
    excluded = {
        str(row.get("business_id")) for row in manifest.get("approved_exclusions") or []
    }
    if set(config.excluded_business_ids) != excluded:
        raise ValueError("M0 exclusion scope differs from Scheme A")
    return manifest


def _verified_outputs(manifest: Mapping[str, Any], *, strict_hashes: bool) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for role, record_value in dict(manifest.get("outputs") or {}).items():
        record = dict(record_value)
        path = normalize_runtime_path(record["path"]).resolve(strict=True)
        if strict_hashes and sha256_file(path) != record["sha256"]:
            raise ValueError(f"manifest output hash mismatch: {role}: {path}")
        result[str(role)] = path
    return result


def _validate_case_artifacts(root: Path, truth_path: Path, strict_hashes: bool) -> None:
    manifest = _read_json(root / "artifact_manifest.json")
    if manifest.get("content_repair") is not False or manifest.get("silent_fix") is not False:
        raise ValueError(f"historical Case artifact manifest allows repair: {root}")
    artifacts = {
        normalize_runtime_path(row["path"]).resolve(strict=True): row
        for row in manifest.get("artifacts") or []
    }
    if truth_path.resolve() not in artifacts:
        raise ValueError(f"jsg_truth.json not declared by Case artifact manifest: {root}")
    if strict_hashes:
        for path, row in artifacts.items():
            if sha256_file(path) != row["sha256"]:
                raise ValueError(f"historical Case artifact hash mismatch: {path}")


def _evidence_roles(truth: JSGCaseTruth) -> dict[str, EvidenceRef]:
    result: dict[str, EvidenceRef] = {}
    groups: Iterable[Iterable[Any]] = (
        truth.standard_segments,
        truth.junction_segment_relations,
        truth.physical_movements,
        truth.segment_connectors,
    )
    for group in groups:
        for item in group:
            for ref in item.evidence_refs:
                existing = result.get(ref.role)
                if existing is not None and (existing.path, existing.sha256) != (ref.path, ref.sha256):
                    raise ValueError(f"{truth.case_key}: inconsistent evidence role {ref.role}")
                result[ref.role] = ref
    return result


def _read_vector(path: Path) -> tuple[list[dict[str, Any]], str, dict[str, bool]]:
    try:
        import fiona
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("fiona is required for Scheme A baseline replay") from exc
    rows: list[dict[str, Any]] = []
    geometry_ok: dict[str, bool] = {}
    with fiona.open(str(path)) as source:
        crs = _canonical_crs(source.crs_wkt or source.crs)
        for index, feature in enumerate(source):
            properties = {str(key): value for key, value in dict(feature["properties"]).items()}
            rows.append(properties)
            identifier = _text(properties.get("id") or properties.get("swsd_segment_id") or index)
            geometry = feature.get("geometry")
            geometry_ok[identifier] = geometry is not None
    return rows, crs, geometry_ok


def _unique_index(rows: list[dict[str, Any]], field: str, context: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _text(row.get(field))
        if not key:
            raise ValueError(f"{context}: empty {field}")
        if key in result:
            raise ValueError(f"{context}: duplicate {field}={key}")
        result[key] = row
    return result


def _main_members(nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for node_id, row in nodes.items():
        main = _nonzero(row.get("mainnodeid"))
        if main:
            result[main].add(node_id)
        for subnode in _string_list(row.get("subnodeid")):
            if main:
                result[main].add(subnode)
    return result


def _node_access_closure(
    junction_id: str,
    nodes: Mapping[str, Mapping[str, Any]],
    main_members: Mapping[str, set[str]],
) -> tuple[str, ...]:
    result = {junction_id}
    if junction_id in nodes:
        row = nodes[junction_id]
        result.update(_string_list(row.get("subnodeid")))
        main = _nonzero(row.get("mainnodeid"))
        if main:
            result.add(main)
            result.update(main_members.get(main, set()))
    result.update(main_members.get(junction_id, set()))
    result.intersection_update(nodes.keys())
    return tuple(sorted(result))


def _direction_role(
    road_ids: Iterable[str],
    access_node_ids: Iterable[str],
    roads: Mapping[str, Mapping[str, Any]],
) -> str:
    access = set(access_node_ids)
    enters = exits = False
    for road_id in road_ids:
        road = roads.get(str(road_id))
        if road is None:
            continue
        start = _text(road.get("snodeid"))
        end = _text(road.get("enodeid"))
        try:
            direction = int(road.get("direction"))
        except (TypeError, ValueError):
            continue
        if start in access:
            exits = exits or direction in FORWARD_DIRECTIONS
            enters = enters or direction in REVERSE_DIRECTIONS
        if end in access:
            enters = enters or direction in FORWARD_DIRECTIONS
            exits = exits or direction in REVERSE_DIRECTIONS
    if enters and exits:
        return "BOTH"
    if enters:
        return "ENTER"
    if exits:
        return "EXIT"
    return "UNKNOWN"


def _directed_carrier_terminals(
    road_ids: Iterable[str],
    roads: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    nodes: set[str] = set()
    for road_id in road_ids:
        road = roads.get(str(road_id))
        if road is None:
            continue
        start = _text(road.get("snodeid"))
        end = _text(road.get("enodeid"))
        nodes.update((start, end))
        try:
            direction = int(road.get("direction"))
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


def _canonical_crs(value: Any) -> str:
    if not value:
        return ""
    return CRS.from_user_input(value).to_string()


def _require_single_crs(case_key: str, values: Iterable[str]) -> str:
    canonical = {value for value in values if value}
    if len(canonical) != 1:
        raise ValueError(f"{case_key}: CRS mismatch {sorted(canonical)}")
    return next(iter(canonical))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _nonzero(value: Any) -> str:
    text = _text(value)
    return "" if text in {"", "0", "0.0"} else text


def _string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [_text(item) for item in value if _text(item)]
    text = _text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in text.split(",") if item.strip()]
    if not isinstance(parsed, list):
        parsed = [parsed]
    return [_text(item) for item in parsed if _text(item)]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            )


def _require_under_root(path_value: str, root_value: Path) -> None:
    path = normalize_runtime_path(path_value).resolve(strict=True)
    root = normalize_runtime_path(root_value).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError(f"sample escaped POC scope: {path}")


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _rss_bytes() -> int:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except (ImportError, OSError):
        pass
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.wintypes.DWORD,
        ]
        get_memory.restype = ctypes.wintypes.BOOL
        if get_memory(process, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
    try:
        import resource

        maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return maximum if sys.platform == "darwin" else maximum * 1024
    except (ImportError, OSError):
        return 0


def _environment() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("fiona", "pyproj", "psutil"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "packages": packages,
    }


def _implementation_records() -> dict[str, dict[str, Any]]:
    module_root = Path(__file__).resolve().parent
    result: dict[str, dict[str, Any]] = {}
    for name in (
        "scheme_a_baseline.py",
        "scheme_a_fallback.py",
        "scheme_a_labels.py",
        "scheme_a_models.py",
    ):
        path = module_root / name
        result[name] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return result


def _validation_report(summary: Mapping[str, Any]) -> str:
    counts = dict(summary["counts"])
    performance = dict(summary["performance"])
    return f"""# P05 方案 A Carrier 基线验证报告

## 结论

- Gate：{'PASS' if summary['gate_pass'] else 'FAIL'}。
- Case / Segment / ADVANCE_RIGHT：{counts['case_count']} / {counts['segment_count']} / {counts['advance_right_count']}。
- PhysicalMovement：{counts['physical_movement_count']}；骨架变更：{counts['skeleton_mutation_count']}。
- 策略三态：{json.dumps(summary['strategy_outcomes'], ensure_ascii=False, sort_keys=True)}。
- RealityChangeClue：{counts['reality_change_clue_count']}；fallback：{counts['fallback_plan_count']}。
- 资源：wall {performance['wall_seconds']:.3f}s，CPU {performance['cpu_seconds']:.3f}s，peak RSS {performance['peak_rss_bytes']} bytes，GPU required=false。

## 业务边界

本 run 冻结 T01 Segment/Junction 关系和既有 PhysicalMovement，只生成策略基线、carrier 软标签、异常线索与分级 fallback。模型没有新增、删除或改写业务骨架；`content_repair=false`，`silent_fix=false`。历史 JSG-PTO 仅作为可追溯证据输入，不恢复为当前业务骨架。
"""


__all__ = [
    "SCHEME_A_MANIFEST_VERSION",
    "build_scheme_a_baseline_run",
]
