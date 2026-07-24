from __future__ import annotations

import csv
import ctypes
import json
import os
import platform
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p2_p2_p1_models import (
    INFERENCE_EVIDENCE_AVAILABLE,
    SCHEME_A_P2_P2_P2_P1_SCHEMA,
    SOURCE_FACT_BLOCKED,
    UNOBSERVABLE_FALLBACK,
    SchemeAP2P2P2P1Config,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


DECISION_EVIDENCE_ROUTE_GO = "P05_SCHEME_A_P2_P2_P2_P1_EVIDENCE_ROUTE_GO"
DECISION_SOURCE_FACT_BLOCKED = "P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED"
DECISION_UNOBSERVABLE = "P05_SCHEME_A_P2_P2_P2_P1_UNOBSERVABLE_FALLBACK"

POPULATION_AGREED_WRONG = "AGREED_WRONG"
POPULATION_RESIDUAL_UNSAFE = "RESIDUAL_UNSAFE_ACCEPTED"
POPULATION_REVIEW = "REVIEW_TARGET"


def build_scheme_a_p2_p2_p2_p1_attribution(
    config: SchemeAP2P2P2P1Config,
) -> Path:
    started = time.perf_counter()
    p0_root = _resolve_dir(config.p2_p2_p2_p0_run_root)
    dataset_root = _resolve_dir(config.p2_p1_dataset_run_root)
    oof_root = _resolve_dir(config.p2_p1_oof_run_root)
    baseline_root = _resolve_dir(config.scheme_a_baseline_run_root)
    output_root = normalize_runtime_path(config.output_root).resolve()
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    manifests, manifest_records = _load_and_validate_manifests(
        config, p0_root, dataset_root, oof_root, baseline_root
    )
    paths = _verified_input_paths(config, manifests)

    p0_labels = {
        str(row["group_id"]): row for row in _read_jsonl(paths["p0_labels"])
    }
    if len(p0_labels) != config.expected_segment_count:
        raise ValueError("P2-P2-P2-P0 label denominator differs")

    ledger = list(_read_jsonl(paths["p0_ledger"]))
    agreed_wrong = [
        row for row in ledger if not bool(row.get("review_target"))
    ]
    review = [row for row in ledger if bool(row.get("review_target"))]
    if len(agreed_wrong) != config.expected_agreed_wrong_count:
        raise ValueError("agreed-wrong denominator differs")
    if len(review) != config.expected_review_count:
        raise ValueError("Review denominator differs")

    residual = _load_residual_unsafe(config, paths["p0_decisions"], p0_labels)
    if len(residual) != config.expected_residual_unsafe_count:
        raise ValueError("residual unsafe denominator differs")

    population_rows = _population_rows(agreed_wrong, residual, review)
    audited_group_ids = {str(row["group_id"]) for row in population_rows}
    if len(audited_group_ids) != len(population_rows):
        raise ValueError("audit populations overlap")

    dataset_labels = {
        str(row["group_id"]): row
        for row in _read_jsonl(paths["dataset_labels"])
        if row.get("object_type") == "SEGMENT"
    }
    if len(dataset_labels) != config.expected_segment_count:
        raise ValueError("P2-P1 Segment label denominator differs")

    inventories = _load_segment_inventory(paths["segment_inventory"])
    if len(inventories) != config.expected_segment_count:
        raise ValueError("Scheme A Segment inventory denominator differs")
    carrier_labels = _load_segment_carrier_labels(paths["carrier_labels"])
    if len(carrier_labels) != config.expected_segment_count:
        raise ValueError("Scheme A carrier-label denominator differs")

    compatibility = _read_json(paths["compatibility_oracle"])
    junction_override_keys = {
        (str(case_key), str(segment_id))
        for case_key, segment_id in compatibility.get(
            "junction_fallback_segment_keys", []
        )
    }
    fallback_plans = _load_fallback_plans(paths["fallback_plans"])
    clues = {
        str(row["clue_id"]): row
        for row in _read_jsonl(paths["reality_change_clues"])
    }

    joint_signals, joint_metrics = _load_joint_signal_audit(
        config, paths["oof_selections"], p0_labels, audited_group_ids
    )
    records = _attribute_objects(
        population_rows=population_rows,
        dataset_labels=dataset_labels,
        inventories=inventories,
        carrier_labels=carrier_labels,
        junction_override_keys=junction_override_keys,
        fallback_plans=fallback_plans,
        clues=clues,
        joint_signals=joint_signals,
        paths=paths,
    )
    if len(records) != len(population_rows):
        raise ValueError("attribution denominator differs")
    terminal_counts = Counter(str(row["terminal_class"]) for row in records)
    if sum(terminal_counts.values()) != len(records):
        raise ValueError("terminal attribution is not mutually exclusive")

    evidence_candidates = _evidence_candidate_ledger(
        records=records,
        joint_metrics=joint_metrics,
        paths=paths,
    )
    decision = _decision(terminal_counts)
    source_contract = {
        "schema_version": SCHEME_A_P2_P2_P2_P1_SCHEMA,
        "terminal_classes": [
            INFERENCE_EVIDENCE_AVAILABLE,
            SOURCE_FACT_BLOCKED,
            UNOBSERVABLE_FALLBACK,
        ],
        "direct_cause_required": True,
        "auxiliary_signal_cannot_upgrade_source_fact": True,
        "allowed_inference_modules": ["T01", "T07", "P05_TRUTH_FREE"],
        "prohibited_inference_modules": ["T03", "T04", "T05", "T06"],
        "t07_evidence_mode": "DRIVEZONE_ONLY",
        "movement_ignored": True,
        "training_performed": False,
        "threshold_tuning_performed": False,
        "candidate_reselection_performed": False,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "geometry_modified": False,
        "coordinate_transform_performed": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }
    direct_counts = Counter(str(row["direct_cause_code"]) for row in records)
    population_counts = Counter(str(row["population"]) for row in records)
    new_permitted = sum(
        1
        for row in evidence_candidates
        if row["role"] == "DIRECT"
        and row["inference_available"]
        and not row["already_present_in_p2_p2_p2_p0"]
    )
    deterministic_payload = {
        "schema_version": SCHEME_A_P2_P2_P2_P1_SCHEMA,
        "decision": decision,
        "records": records,
        "evidence_candidates": evidence_candidates,
        "source_contract": source_contract,
        "population_counts": dict(sorted(population_counts.items())),
        "terminal_counts": dict(sorted(terminal_counts.items())),
        "direct_cause_counts": dict(sorted(direct_counts.items())),
        "joint_signal_metrics": joint_metrics,
        "new_permitted_direct_evidence_count": new_permitted,
    }
    determinism_signature = canonical_sha256(deterministic_payload)
    reference_match = _reference_match(config.reference_run_root, determinism_signature)

    attribution_path = run_root / "object_attribution.jsonl"
    candidate_path = run_root / "evidence_candidate_ledger.jsonl"
    contract_path = run_root / "source_contract.json"
    _write_jsonl(attribution_path, records)
    _write_jsonl(candidate_path, evidence_candidates)
    write_json(contract_path, source_contract)

    summary = {
        "schema_version": SCHEME_A_P2_P2_P2_P1_SCHEMA,
        "decision": decision,
        "case_count": config.expected_case_count,
        "segment_count": config.expected_segment_count,
        "audited_object_count": len(records),
        "population_counts": dict(sorted(population_counts.items())),
        "terminal_counts": dict(sorted(terminal_counts.items())),
        "direct_cause_counts": dict(sorted(direct_counts.items())),
        "unattributed_count": terminal_counts.get(UNOBSERVABLE_FALLBACK, 0),
        "new_permitted_direct_evidence_count": new_permitted,
        "new_inference_evidence_justifies_model_stage": new_permitted > 0,
        "joint_signal_metrics": joint_metrics,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "training_performed": False,
        "threshold_tuning_performed": False,
        "t01_t12_modification_count": 0,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "determinism_signature": determinism_signature,
        "reference_run_match": reference_match,
        "resource": {
            "wall_seconds": time.perf_counter() - started,
            "peak_rss_mb": _peak_rss_bytes() / (1024 * 1024),
            "gpu_peak_memory_mb": 0.0,
            "wall_within_30_minutes": time.perf_counter() - started <= 1800.0,
            "cpu_ram_within_8gb": _peak_rss_bytes() <= 8 * 1024**3,
            "gpu_vram_zero": True,
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
    }
    summary_path = run_root / "scheme_a_p2_p2_p2_p1_summary.json"
    write_json(summary_path, summary)
    report_path = run_root / "validation_report.md"
    report_path.write_text(
        _validation_report(summary, evidence_candidates),
        encoding="utf-8",
        newline="\n",
    )

    outputs = {
        "attribution": output_record(attribution_path),
        "evidence_candidates": output_record(candidate_path),
        "source_contract": output_record(contract_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": f"{SCHEME_A_P2_P2_P2_P1_SCHEMA}-manifest",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "decision": decision,
        "status": "audit_completed",
        "input_manifests": manifest_records,
        "counts": {
            "case_count": config.expected_case_count,
            "segment_count": config.expected_segment_count,
            "audited_object_count": len(records),
            "population_counts": dict(sorted(population_counts.items())),
            "terminal_counts": dict(sorted(terminal_counts.items())),
        },
        "new_permitted_direct_evidence_count": new_permitted,
        "new_inference_evidence_justifies_model_stage": new_permitted > 0,
        "truth_feature_count": 0,
        "identifier_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "movement_feature_count": 0,
        "training_performed": False,
        "threshold_tuning_performed": False,
        "skeleton_mutation_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "determinism_signature": determinism_signature,
        "reference_run_match": reference_match,
        "outputs": outputs,
    }
    manifest_path = run_root / "scheme_a_p2_p2_p2_p1_manifest.json"
    write_json(manifest_path, manifest)
    artifact_path = run_root / "artifact_manifest.json"
    write_json(
        artifact_path,
        {
            "schema_version": f"{SCHEME_A_P2_P2_P2_P1_SCHEMA}-artifact-manifest",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return run_root


def classify_direct_cause(
    *,
    population: str,
    access_valid: bool,
    in_truth_conditioned_junction_override: bool,
    truth_target: str,
    clue_codes: Sequence[str],
    t06_direct_role_present: bool,
) -> dict[str, Any]:
    if population == POPULATION_REVIEW and not access_valid:
        return {
            "terminal_class": INFERENCE_EVIDENCE_AVAILABLE,
            "direct_cause_code": "T01_ADVANCE_RIGHT_ACCESS_INVALID",
            "direct_source_module": "T01",
            "direct_source_roles": ["t01_segment", "t01_roads"],
            "evidence_generation_time": "before candidate scoring",
            "inference_available": True,
            "computation_cost": "O(1) per Segment after frozen T01 access audit",
            "recommended_action": "retain deterministic Segment fallback; do not learn this gate",
        }
    if in_truth_conditioned_junction_override:
        return {
            "terminal_class": SOURCE_FACT_BLOCKED,
            "direct_cause_code": "TRUTH_CONDITIONED_JUNCTION_FALLBACK_OVERRIDE",
            "direct_source_module": "P05+T06_LABEL_ONLY",
            "direct_source_roles": [
                "t06_segment_relation_truth",
                "truth_conditioned_node_requirement",
            ],
            "evidence_generation_time": "after candidate freeze during label-only joint truth construction",
            "inference_available": False,
            "computation_cost": "O(Segment + compatibility edge) if the source fact is authorized",
            "recommended_action": "keep fallback in truth/evaluation only until the source fact is explicitly authorized",
        }
    if truth_target == "MIXED_CARRIER" and t06_direct_role_present:
        return {
            "terminal_class": SOURCE_FACT_BLOCKED,
            "direct_cause_code": "T06_SEGMENT_RELATION_CARRIER_TRUTH",
            "direct_source_module": "T06_LABEL_ONLY",
            "direct_source_roles": ["t06_segment_relation_truth"],
            "evidence_generation_time": "after candidate freeze during label join",
            "inference_available": False,
            "computation_cost": "O(1) per Segment if the source fact is authorized",
            "recommended_action": "request a business decision before promoting the T06 carrier terminal fact",
        }
    if "RCSD_CARRIER_ROAD_MISSING" in clue_codes and t06_direct_role_present:
        return {
            "terminal_class": SOURCE_FACT_BLOCKED,
            "direct_cause_code": "T06_RCSD_CARRIER_ROAD_MISSING",
            "direct_source_module": "T06_LABEL_ONLY",
            "direct_source_roles": ["t06_segment_relation_truth"],
            "evidence_generation_time": "after final T06 relation truth is available",
            "inference_available": False,
            "computation_cost": "O(1) per Segment if the source fact is authorized",
            "recommended_action": "preserve SWSD and report the clue only through an explicitly authorized source contract",
        }
    return {
        "terminal_class": UNOBSERVABLE_FALLBACK,
        "direct_cause_code": "NO_DIRECT_OBSERVABLE_SOURCE",
        "direct_source_module": "NONE",
        "direct_source_roles": [],
        "evidence_generation_time": "unavailable",
        "inference_available": False,
        "computation_cost": "not applicable",
        "recommended_action": "permanent fallback/Review; do not auto-publish",
    }


def _load_and_validate_manifests(
    config: SchemeAP2P2P2P1Config,
    p0_root: Path,
    dataset_root: Path,
    oof_root: Path,
    baseline_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    definitions = {
        "p2_p2_p2_p0": (
            p0_root / "scheme_a_p2_p2_p2_p0_manifest.json",
            "decision",
            "P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO",
        ),
        "p2_p1_dataset": (
            dataset_root / "scheme_a_p2_p1_dataset_manifest.json",
            "status",
            "dataset_passed",
        ),
        "p2_p1_oof": (
            oof_root / "scheme_a_p2_p1_oof_manifest.json",
            "decision",
            "P05_SCHEME_A_P2_P1_SAFETY_NO_GO",
        ),
        "scheme_a_baseline": (
            baseline_root / "scheme_a_manifest.json",
            "status",
            "passed",
        ),
    }
    manifests: dict[str, dict[str, Any]] = {}
    records: dict[str, dict[str, Any]] = {}
    for role, (path, field, expected) in definitions.items():
        manifest = _read_json(path)
        if manifest.get(field) != expected:
            raise ValueError(f"{role} status differs from the frozen contract")
        if config.strict_hashes:
            _verify_manifest_outputs(manifest)
        manifests[role] = manifest
        records[role] = {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
        }
    if int(
        manifests["scheme_a_baseline"].get("counts", {}).get("case_count", 0)
    ) != config.expected_case_count:
        raise ValueError("Scheme A Case denominator differs")
    if int(
        manifests["scheme_a_baseline"].get("counts", {}).get("segment_count", 0)
    ) != config.expected_segment_count:
        raise ValueError("Scheme A Segment denominator differs")
    return manifests, records


def _verified_input_paths(
    config: SchemeAP2P2P2P1Config,
    manifests: Mapping[str, Mapping[str, Any]],
) -> dict[str, Path]:
    requested = {
        "p0_ledger": ("p2_p2_p2_p0", "ledger"),
        "p0_labels": ("p2_p2_p2_p0", "labels"),
        "p0_decisions": ("p2_p2_p2_p0", "decisions"),
        "dataset_labels": ("p2_p1_dataset", "labels"),
        "compatibility_oracle": ("p2_p1_dataset", "compatibility_oracle"),
        "oof_selections": ("p2_p1_oof", "selections"),
        "segment_inventory": ("scheme_a_baseline", "segment_inventory"),
        "carrier_labels": ("scheme_a_baseline", "carrier_labels"),
        "fallback_plans": ("scheme_a_baseline", "fallback_plans"),
        "reality_change_clues": ("scheme_a_baseline", "reality_change_clues"),
    }
    result: dict[str, Path] = {}
    for alias, (manifest_role, output_role) in requested.items():
        record = dict(manifests[manifest_role].get("outputs") or {}).get(output_role)
        if not record:
            raise ValueError(f"missing output role: {manifest_role}.{output_role}")
        path = normalize_runtime_path(str(record["path"])).resolve(strict=True)
        if config.strict_hashes and sha256_file(path) != str(record["sha256"]):
            raise ValueError(f"output hash mismatch: {manifest_role}.{output_role}")
        result[alias] = path
    return result


def _load_residual_unsafe(
    config: SchemeAP2P2P2P1Config,
    decision_path: Path,
    labels: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision in _read_jsonl(decision_path):
        if (
            decision.get("probe") != config.residual_probe
            or int(decision.get("seed", -1)) != config.residual_probe_seed
            or not bool(decision.get("accepted"))
        ):
            continue
        group_id = str(decision["group_id"])
        label = labels.get(group_id)
        if not label or not bool(label.get("unsafe")):
            continue
        if group_id in seen:
            raise ValueError("residual unsafe group repeated")
        seen.add(group_id)
        rows.append(
            {
                "case_key": str(decision["case_key"]),
                "group_id": group_id,
                "object_id": group_id.rsplit(":", 1)[-1],
                "proposal_target": str(decision.get("proposal_target") or ""),
                "truth_target": str(label.get("truth_target") or ""),
                "proposal_correct": bool(label.get("proposal_correct")),
                "review_target": bool(label.get("review_target")),
                "anomaly_target": bool(label.get("anomaly_target")),
                "unsafe": bool(label.get("unsafe")),
                "risk": float(decision.get("risk", 0.0)),
                "risk_threshold": float(decision.get("risk_threshold", 0.0)),
            }
        )
    return sorted(rows, key=lambda row: (row["case_key"], row["group_id"]))


def _population_rows(
    agreed_wrong: Sequence[Mapping[str, Any]],
    residual: Sequence[Mapping[str, Any]],
    review: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for population, rows in (
        (POPULATION_AGREED_WRONG, agreed_wrong),
        (POPULATION_RESIDUAL_UNSAFE, residual),
        (POPULATION_REVIEW, review),
    ):
        for row in rows:
            result.append(
                {
                    **dict(row),
                    "population": population,
                    "case_key": str(row["case_key"]),
                    "group_id": str(row["group_id"]),
                    "object_id": str(
                        row.get("object_id")
                        or str(row["group_id"]).rsplit(":", 1)[-1]
                    ),
                }
            )
    return sorted(result, key=lambda row: (row["population"], row["case_key"], row["group_id"]))


def _attribute_objects(
    *,
    population_rows: Sequence[Mapping[str, Any]],
    dataset_labels: Mapping[str, Mapping[str, Any]],
    inventories: Mapping[tuple[str, str], Mapping[str, Any]],
    carrier_labels: Mapping[tuple[str, str], Mapping[str, Any]],
    junction_override_keys: set[tuple[str, str]],
    fallback_plans: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    clues: Mapping[str, Mapping[str, Any]],
    joint_signals: Mapping[str, Mapping[str, Any]],
    paths: Mapping[str, Path],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for population_row in population_rows:
        case_key = str(population_row["case_key"])
        object_id = str(population_row["object_id"])
        group_id = str(population_row["group_id"])
        key = (case_key, object_id)
        inventory = inventories.get(key)
        label = dataset_labels.get(group_id)
        carrier = carrier_labels.get(key)
        if inventory is None or label is None or carrier is None:
            raise ValueError(f"object lineage missing: {key}")
        plan_rows = list(fallback_plans.get(key, ()))
        clue_rows = [
            clues[str(clue_id)]
            for plan in plan_rows
            for clue_id in plan.get("clue_ids") or []
            if str(clue_id) in clues
        ]
        clue_codes = sorted({str(row.get("code") or "") for row in clue_rows})
        direct_refs = _direct_source_refs(carrier, clue_rows)
        direct_t06_refs = [
            ref
            for ref in direct_refs
            if str(ref.get("role") or "").startswith("t06_")
        ]
        classification = classify_direct_cause(
            population=str(population_row["population"]),
            access_valid=_yes(inventory.get("access_valid")),
            in_truth_conditioned_junction_override=key in junction_override_keys,
            truth_target=str(label.get("carrier_target") or ""),
            clue_codes=clue_codes,
            t06_direct_role_present=bool(direct_t06_refs),
        )
        lineage = _object_lineage(
            classification=classification,
            direct_refs=direct_refs,
            paths=paths,
        )
        signal = dict(joint_signals.get(group_id) or {})
        result.append(
            {
                "schema_version": SCHEME_A_P2_P2_P2_P1_SCHEMA,
                "population": population_row["population"],
                "case_key": case_key,
                "group_id": group_id,
                "object_id": object_id,
                "segment_type": str(inventory.get("segment_type") or ""),
                "access_valid": _yes(inventory.get("access_valid")),
                "proposal_target": str(population_row.get("proposal_target") or ""),
                "truth_target": str(label.get("carrier_target") or ""),
                "proposal_correct": bool(population_row.get("proposal_correct")),
                "anomaly_target": bool(population_row.get("anomaly_target")),
                "review_target": bool(population_row.get("review_target")),
                "direct_clue_codes": clue_codes,
                **classification,
                "auxiliary_joint_fallback_seed_count": int(
                    signal.get("fallback_seed_count", 0)
                ),
                "auxiliary_joint_fallback_seeds": list(
                    signal.get("fallback_seeds") or []
                ),
                "auxiliary_joint_reasons": list(signal.get("reasons") or []),
                "auxiliary_signal_role": "AUXILIARY_ONLY",
                "lineage": lineage,
                "truth_used_for_attribution_only": True,
                "truth_feature_used": False,
                "identifier_feature_used": False,
                "absolute_coordinate_feature_used": False,
                "movement_feature_used": False,
            }
        )
    return result


def _evidence_candidate_ledger(
    *,
    records: Sequence[Mapping[str, Any]],
    joint_metrics: Mapping[str, Any],
    paths: Mapping[str, Path],
) -> list[dict[str, Any]]:
    causes = Counter(str(row["direct_cause_code"]) for row in records)
    terminal = Counter(str(row["terminal_class"]) for row in records)
    candidates = [
        {
            "schema_version": SCHEME_A_P2_P2_P2_P1_SCHEMA,
            "candidate": "T01_ACCESS_VALIDITY_HARD_GATE",
            "role": "DIRECT",
            "source_module": "T01",
            "source_roles": ["t01_segment", "t01_roads"],
            "generation_time": "before candidate scoring",
            "inference_available": True,
            "computation_cost": "O(1) per Segment after frozen T01 access audit",
            "direct_object_count": causes.get("T01_ADVANCE_RIGHT_ACCESS_INVALID", 0),
            "already_present_in_p2_p2_p2_p0": True,
            "decision": "RETAIN_DETERMINISTIC_GATE",
            "lineage": [_record_for_path(paths["segment_inventory"])],
        },
        {
            "schema_version": SCHEME_A_P2_P2_P2_P1_SCHEMA,
            "candidate": "P2P1_JOINT_FALLBACK_SIGNAL",
            "role": "AUXILIARY",
            "source_module": "P05_TRUTH_FREE",
            "source_roles": ["joint_node_constraint", "seed_fallback_decision"],
            "generation_time": "after Segment scoring and before RoadGraph publication",
            "inference_available": True,
            "computation_cost": "O(Segment + compatibility edge) per inference run",
            "direct_object_count": 0,
            "already_present_in_p2_p2_p2_p0": False,
            "decision": "AUXILIARY_ONLY_NOT_A_HARD_BUSINESS_FACT",
            "global_signal_metrics": dict(joint_metrics),
            "lineage": [_record_for_path(paths["oof_selections"])],
        },
        {
            "schema_version": SCHEME_A_P2_P2_P2_P1_SCHEMA,
            "candidate": "T06_SEGMENT_RELATION_TERMINAL_FACT",
            "role": "DIRECT",
            "source_module": "T06_LABEL_ONLY",
            "source_roles": ["t06_segment_relation_truth"],
            "generation_time": "after candidate freeze during label/evaluation construction",
            "inference_available": False,
            "computation_cost": "O(1) per Segment if explicitly authorized",
            "direct_object_count": causes.get("T06_SEGMENT_RELATION_CARRIER_TRUTH", 0)
            + causes.get("T06_RCSD_CARRIER_ROAD_MISSING", 0),
            "already_present_in_p2_p2_p2_p0": False,
            "decision": "SOURCE_FACT_BLOCKED",
            "lineage": [_record_for_path(paths["carrier_labels"])],
        },
        {
            "schema_version": SCHEME_A_P2_P2_P2_P1_SCHEMA,
            "candidate": "TRUTH_CONDITIONED_JUNCTION_FALLBACK_FACT",
            "role": "DIRECT",
            "source_module": "P05+T06_LABEL_ONLY",
            "source_roles": [
                "t06_segment_relation_truth",
                "truth_conditioned_node_requirement",
            ],
            "generation_time": "after candidate freeze during joint truth construction",
            "inference_available": False,
            "computation_cost": "O(Segment + compatibility edge) if explicitly authorized",
            "direct_object_count": causes.get(
                "TRUTH_CONDITIONED_JUNCTION_FALLBACK_OVERRIDE", 0
            ),
            "already_present_in_p2_p2_p2_p0": False,
            "decision": "SOURCE_FACT_BLOCKED",
            "lineage": [
                _record_for_path(paths["dataset_labels"]),
                _record_for_path(paths["compatibility_oracle"]),
            ],
        },
        {
            "schema_version": SCHEME_A_P2_P2_P2_P1_SCHEMA,
            "candidate": "NO_DIRECT_OBSERVABLE_SOURCE",
            "role": "DIRECT",
            "source_module": "NONE",
            "source_roles": [],
            "generation_time": "unavailable",
            "inference_available": False,
            "computation_cost": "not applicable",
            "direct_object_count": terminal.get(UNOBSERVABLE_FALLBACK, 0),
            "already_present_in_p2_p2_p2_p0": False,
            "decision": "PERMANENT_FALLBACK",
            "lineage": [],
        },
    ]
    return candidates


def _load_joint_signal_audit(
    config: SchemeAP2P2P2P1Config,
    path: Path,
    labels: Mapping[str, Mapping[str, Any]],
    audited_group_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    per_seed_total: Counter[int] = Counter()
    per_seed_unsafe: Counter[int] = Counter()
    any_groups: set[str] = set()
    any_unsafe: set[str] = set()
    target_signals: dict[str, dict[str, Any]] = {
        group_id: {"fallback_seeds": [], "reasons": []}
        for group_id in audited_group_ids
    }
    segment_rows = 0
    seen_seeds: set[int] = set()
    for row in _read_jsonl(path):
        if row.get("object_type") != "SEGMENT":
            continue
        segment_rows += 1
        seed = int(row["seed"])
        seen_seeds.add(seed)
        group_id = str(row["group_id"])
        if group_id in target_signals:
            target_signals[group_id]["reasons"].append(
                f"{seed}:{row.get('reason') or ''}"
            )
        if not bool(row.get("junction_fallback_applied")):
            continue
        per_seed_total[seed] += 1
        any_groups.add(group_id)
        if bool(labels.get(group_id, {}).get("unsafe")):
            per_seed_unsafe[seed] += 1
            any_unsafe.add(group_id)
        if group_id in target_signals:
            target_signals[group_id]["fallback_seeds"].append(seed)
    expected_rows = config.expected_segment_count * len(config.expected_base_seeds)
    if segment_rows != expected_rows or seen_seeds != set(config.expected_base_seeds):
        raise ValueError("P2-P1 Segment selection denominator differs")
    for signal in target_signals.values():
        signal["fallback_seeds"] = sorted(set(signal["fallback_seeds"]))
        signal["reasons"] = sorted(signal["reasons"])
        signal["fallback_seed_count"] = len(signal["fallback_seeds"])
    seed_metrics = {}
    for seed in config.expected_base_seeds:
        total = per_seed_total[seed]
        unsafe = per_seed_unsafe[seed]
        seed_metrics[str(seed)] = {
            "fallback_count": total,
            "unsafe_count": unsafe,
            "unsafe_precision": unsafe / max(1, total),
        }
    metrics = {
        "seed_metrics": seed_metrics,
        "any_seed_fallback_count": len(any_groups),
        "any_seed_unsafe_count": len(any_unsafe),
        "any_seed_unsafe_precision": len(any_unsafe) / max(1, len(any_groups)),
        "audited_object_any_seed_signal_count": sum(
            bool(signal["fallback_seeds"]) for signal in target_signals.values()
        ),
        "audited_object_count": len(target_signals),
        "direct_cause": False,
    }
    return target_signals, metrics


def _load_segment_inventory(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = str(row["case_key"]), str(row["segment_id"])
            if key in result:
                raise ValueError(f"duplicate Segment inventory: {key}")
            result[key] = row
    return result


def _load_segment_carrier_labels(
    path: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_jsonl(path):
        if row.get("object_type") != "SEGMENT":
            continue
        key = str(row["case_key"]), str(row["object_id"])
        if key in result:
            raise ValueError(f"duplicate Segment carrier label: {key}")
        result[key] = row
    return result


def _load_fallback_plans(
    path: Path,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(path):
        case_key = str(row["case_key"])
        for segment_id in row.get("segment_ids") or []:
            result[(case_key, str(segment_id))].append(row)
    return dict(result)


def _direct_source_refs(
    carrier: Mapping[str, Any],
    clues: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for ref in carrier.get("lineage") or []:
        if str(ref.get("role") or "").startswith(("t01_", "t06_")):
            refs.append(dict(ref))
    for clue in clues:
        for ref in clue.get("evidence_refs") or []:
            if str(ref.get("role") or "").startswith(("t01_", "t06_")):
                refs.append(dict(ref))
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for ref in refs:
        key = (
            str(ref.get("role") or ""),
            str(ref.get("path") or ""),
            str(ref.get("sha256") or ""),
            str(ref.get("object_id") or ""),
        )
        unique[key] = ref
    return [unique[key] for key in sorted(unique)]


def _object_lineage(
    *,
    classification: Mapping[str, Any],
    direct_refs: Sequence[Mapping[str, Any]],
    paths: Mapping[str, Path],
) -> list[dict[str, Any]]:
    cause = str(classification["direct_cause_code"])
    if cause == "T01_ADVANCE_RIGHT_ACCESS_INVALID":
        return [
            _record_for_path(paths["segment_inventory"]),
            *[
                dict(ref)
                for ref in direct_refs
                if str(ref.get("role") or "").startswith("t01_")
            ],
        ]
    if cause == "TRUTH_CONDITIONED_JUNCTION_FALLBACK_OVERRIDE":
        return [
            _record_for_path(paths["dataset_labels"]),
            _record_for_path(paths["compatibility_oracle"]),
            *[dict(ref) for ref in direct_refs],
        ]
    if cause in {
        "T06_SEGMENT_RELATION_CARRIER_TRUTH",
        "T06_RCSD_CARRIER_ROAD_MISSING",
    }:
        return [
            dict(ref)
            for ref in direct_refs
            if str(ref.get("role") or "").startswith("t06_")
        ]
    return []


def _decision(terminal_counts: Mapping[str, int]) -> str:
    if terminal_counts.get(UNOBSERVABLE_FALLBACK, 0):
        return DECISION_UNOBSERVABLE
    if terminal_counts.get(SOURCE_FACT_BLOCKED, 0):
        return DECISION_SOURCE_FACT_BLOCKED
    return DECISION_EVIDENCE_ROUTE_GO


def _validation_report(
    summary: Mapping[str, Any],
    evidence_candidates: Sequence[Mapping[str, Any]],
) -> str:
    terminal = summary["terminal_counts"]
    populations = summary["population_counts"]
    candidates = "\n".join(
        f"- `{row['candidate']}`: role={row['role']}, direct objects={row['direct_object_count']}, "
        f"inference={str(row['inference_available']).lower()}, decision={row['decision']}"
        for row in evidence_candidates
    )
    return (
        "# P05-Scheme-A-P2-P2-P2-P1 验证报告\n\n"
        f"- 决策：`{summary['decision']}`\n"
        f"- 审计对象：{summary['audited_object_count']}\n"
        f"- 9-error / residual unsafe / Review："
        f"{populations.get(POPULATION_AGREED_WRONG, 0)} / "
        f"{populations.get(POPULATION_RESIDUAL_UNSAFE, 0)} / "
        f"{populations.get(POPULATION_REVIEW, 0)}\n"
        f"- inference available / source fact blocked / unobservable："
        f"{terminal.get(INFERENCE_EVIDENCE_AVAILABLE, 0)} / "
        f"{terminal.get(SOURCE_FACT_BLOCKED, 0)} / "
        f"{terminal.get(UNOBSERVABLE_FALLBACK, 0)}\n"
        f"- 新增且合法的直接推理证据：{summary['new_permitted_direct_evidence_count']}\n"
        f"- 确定性 signature：`{summary['determinism_signature']}`\n"
        f"- reference match：`{str(summary['reference_run_match']).lower()}`\n\n"
        "## 证据候选\n\n"
        f"{candidates}\n"
    )


def _reference_match(reference_root: Path | None, signature: str) -> bool | None:
    if reference_root is None:
        return None
    root = _resolve_dir(reference_root)
    manifest = _read_json(root / "scheme_a_p2_p2_p2_p1_manifest.json")
    return str(manifest.get("determinism_signature") or "") == signature


def _verify_manifest_outputs(manifest: Mapping[str, Any]) -> None:
    for role, raw_record in dict(manifest.get("outputs") or {}).items():
        record = dict(raw_record)
        path = normalize_runtime_path(str(record.get("path") or "")).resolve(strict=True)
        if sha256_file(path) != str(record.get("sha256") or ""):
            raise ValueError(f"manifest output hash mismatch: {role}")
        if "size_bytes" in record and int(record["size_bytes"]) != path.stat().st_size:
            raise ValueError(f"manifest output size mismatch: {role}")


def _record_for_path(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _resolve_dir(path: Path) -> Path:
    result = normalize_runtime_path(path).resolve(strict=True)
    if not result.is_dir():
        raise NotADirectoryError(result)
    return result


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            stream.write("\n")


def _yes(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _peak_rss_bytes() -> int:
    if os.name == "nt":
        class _ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return int(counters.PeakWorkingSetSize)
        return 0
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (ImportError, OSError, ValueError):
        return 0


__all__ = [
    "build_scheme_a_p2_p2_p2_p1_attribution",
    "classify_direct_cause",
]
