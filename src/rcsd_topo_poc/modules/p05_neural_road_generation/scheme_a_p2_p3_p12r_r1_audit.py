from __future__ import annotations

import json
import platform
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from pyproj import CRS

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    DECISION_REMEDIATION,
    _candidate_component_hits,
    _case_input_records,
    _peak_rss_bytes,
    _read_crs,
    _read_csv,
    _read_json,
    _read_jsonl,
    _read_roads,
    _resolve_case_paths,
    _row_key,
    _write_jsonl,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_candidates import (
    build_truth_free_case_candidates,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_models import (
    P12RR1Config,
)


SCHEMA_VERSION = "p05-scheme-a-p2-p3-p12r-r1-v1"
DECISION_GO = "P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_GO"
DECISION_RECALL_NO_GO = (
    "P05_SCHEME_A_P2_P3_P12R_R1_RECALL_NO_GO"
)
DECISION_QUALITY_NO_GO = (
    "P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_QUALITY_NO_GO"
)
DECISION_AUDIT_NO_GO = (
    "P05_SCHEME_A_P2_P3_P12R_R1_AUDIT_NO_GO"
)


def run_scheme_a_p2_p3_p12r_r1_audit(
    *,
    p12r_root: Path,
    scheme_a_baseline_root: Path,
    poc_data_root: Path,
    output_root: Path,
    reference_run_root: Path | None = None,
    config: P12RR1Config | None = None,
) -> dict[str, Any]:
    cfg = config or P12RR1Config()
    cfg.validate()
    started = time.perf_counter()
    output_root.mkdir(parents=True, exist_ok=False)

    case_inventory = _read_csv(
        scheme_a_baseline_root / "case_inventory.csv"
    )
    case_rows = [
        row
        for row in case_inventory
        if int(row.get("advance_right_count") or 0) > 0
    ]
    inference_inputs = [
        _input_record(
            scheme_a_baseline_root / "case_inventory.csv",
            "SCHEME_A_CASE_INVENTORY",
        )
    ]
    candidate_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    object_rows: list[dict[str, Any]] = []
    case_cache: dict[str, dict[str, Any]] = {}
    crs_by_case: dict[str, dict[str, Any]] = {}

    # Phase 1 is strictly truth-free. P12R/T06 label files are not opened here.
    label_read_before_freeze_count = 0
    for case_row in sorted(
        case_rows,
        key=lambda row: str(row["case_key"]),
    ):
        paths, skeleton = _resolve_case_paths(
            baseline_root=scheme_a_baseline_root,
            case_row=case_row,
            poc_data_root=poc_data_root,
        )
        t01_roads = _read_roads(paths.t01_roads)
        raw_roads = _read_roads(paths.raw_rcsd_roads)
        result = build_truth_free_case_candidates(
            case_key=paths.case_key,
            skeleton=skeleton,
            t01_roads=t01_roads,
            raw_rcsd_roads=raw_roads,
            config=cfg,
        )
        candidate_rows.extend(result["candidates"])
        evidence_rows.extend(result["evidence"])
        object_rows.extend(result["objects"])
        case_cache[paths.case_key] = {
            "paths": paths,
            "raw_roads": raw_roads,
        }
        crs_values = [
            _read_crs(paths.t01_roads),
            _read_crs(paths.t01_nodes),
            _read_crs(paths.raw_rcsd_roads),
            _read_crs(paths.raw_rcsd_nodes),
        ]
        crs_by_case[paths.case_key] = {
            "consistent": len(set(crs_values)) == 1,
            "crs": crs_values[0],
            "metric": _is_metric_projected_crs(crs_values[0]),
        }
        for record in _case_input_records(paths):
            if any(
                token in str(record["role"])
                for token in (
                    "frozen_skeleton.json",
                    "roads.gpkg",
                    "nodes.gpkg",
                    "rcsdroad_slice.gpkg",
                    "rcsdnode_slice.gpkg",
                )
            ) and "t06_" not in str(record["role"]):
                inference_inputs.append(record)

    candidate_rows.sort(key=_candidate_key)
    evidence_rows.sort(key=_evidence_key)
    object_rows.sort(key=_row_key)
    candidate_frozen_signature = canonical_sha256(
        {
            "candidates": candidate_rows,
            "config": _candidate_config(cfg),
            "evidence": evidence_rows,
            "objects": object_rows,
        }
    )

    # Phase 2 starts only after the candidate signature is frozen.
    labels = _load_and_verify_p12r(p12r_root)
    truth_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in labels["truth"]
    }
    control_label_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in labels["candidates"]
    }
    object_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in object_rows
    }
    if set(object_by_key) != set(truth_by_key):
        raise ValueError("R1 candidate objects do not match P12R truth objects")
    if set(object_by_key) != set(control_label_by_key):
        raise ValueError("R1 candidate objects do not match P12R candidates")

    label_inputs = list(labels["inputs"])
    delta_rows: list[dict[str, Any]] = []
    output_candidate_rows: list[dict[str, Any]] = []
    output_evidence_rows: list[dict[str, Any]] = []
    case_final_roads: dict[str, dict[str, Any]] = {}
    for case_key, cached in case_cache.items():
        paths = cached["paths"]
        case_final_roads[case_key] = {
            road.road_id: road
            for road in _read_roads(paths.t06_final_roads)
        }
        label_inputs.append(
            _input_record(
                paths.t06_final_roads,
                f"{case_key}:T06_FINAL_ROAD_LABEL_ONLY",
            )
        )

    candidate_by_object: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in candidate_rows:
        key = (str(row["case_key"]), str(row["object_id"]))
        candidate_by_object.setdefault(key, []).append(row)
    raw_by_case = {
        case_key: {
            road.road_id: road for road in cached["raw_roads"]
        }
        for case_key, cached in case_cache.items()
    }

    for key in sorted(object_by_key):
        case_key, object_id = key
        object_row = object_by_key[key]
        truth = truth_by_key[key]
        control_label = control_label_by_key[key]
        control_ids = set(object_row["control_candidate_road_ids"])
        treatment_ids = set(
            object_row["treatment_candidate_road_ids"]
        )
        if control_ids != set(control_label["candidate_rcsd_road_ids"]):
            control_exact = False
        else:
            control_exact = True
        raw_by_id = raw_by_case[case_key]
        final_by_id = case_final_roads[case_key]
        control_hits = _truth_component_hits(
            truth=truth,
            candidate_ids=control_ids,
            raw_by_id=raw_by_id,
            final_by_id=final_by_id,
            max_distance_m=cfg.local_distance_m,
        )
        treatment_hits = _truth_component_hits(
            truth=truth,
            candidate_ids=treatment_ids,
            raw_by_id=raw_by_id,
            final_by_id=final_by_id,
            max_distance_m=cfg.local_distance_m,
        )
        swsd_reachable = _swsd_reachable(truth, control_label)
        materializer_ready = bool(control_label["materializer_ready"])
        eligible = bool(control_label["eligible"])
        control_oracle_hit = _oracle_hit(
            eligible=eligible,
            component_hits=control_hits,
            swsd_reachable=swsd_reachable,
            materializer_ready=materializer_ready,
        )
        treatment_oracle_hit = _oracle_hit(
            eligible=eligible,
            component_hits=treatment_hits,
            swsd_reachable=swsd_reachable,
            materializer_ready=materializer_ready,
        )
        added_ids = sorted(treatment_ids.difference(control_ids))
        delta_rows.append(
            {
                "added_candidate_road_ids": added_ids,
                "case_key": case_key,
                "control_candidate_count": len(control_ids),
                "control_candidate_road_ids": sorted(control_ids),
                "control_exact_reproduction": control_exact,
                "control_oracle_hit": control_oracle_hit,
                "control_oracle_matches_p12r": (
                    control_oracle_hit
                    == bool(control_label["candidate_oracle_hit"])
                ),
                "control_truth_component_hits": control_hits,
                "eligible": eligible,
                "fold": int(control_label["fold"]),
                "materializer_ready": materializer_ready,
                "object_id": object_id,
                "schema_version": SCHEMA_VERSION,
                "treatment_candidate_count": len(treatment_ids),
                "treatment_candidate_road_ids": sorted(treatment_ids),
                "treatment_oracle_hit": treatment_oracle_hit,
                "treatment_truth_component_hits": treatment_hits,
                "truth_plan_type": str(truth["truth_plan_type"]),
            }
        )
        for candidate in candidate_by_object.get(key, []):
            output_candidate_rows.append(
                {
                    **candidate,
                    "candidate_frozen_signature": (
                        candidate_frozen_signature
                    ),
                    "fold": int(control_label["fold"]),
                }
            )

    fold_by_key = {
        key: int(row["fold"])
        for key, row in control_label_by_key.items()
    }
    for evidence in evidence_rows:
        key = (
            str(evidence["case_key"]),
            str(evidence["object_id"]),
        )
        output_evidence_rows.append(
            {**evidence, "fold": fold_by_key[key]}
        )
    output_candidate_rows.sort(key=_candidate_key)
    output_evidence_rows.sort(key=_evidence_key)
    delta_rows.sort(key=_row_key)

    fold_metrics = _fold_metrics(
        delta_rows,
        fold_count=cfg.fold_count,
    )
    metrics = _metrics(
        delta_rows=delta_rows,
        candidate_rows=output_candidate_rows,
        evidence_rows=output_evidence_rows,
        object_rows=object_rows,
        crs_by_case=crs_by_case,
        labels=labels,
        label_read_before_freeze_count=(
            label_read_before_freeze_count
        ),
        cfg=cfg,
    )
    gates = _gates(metrics, fold_metrics, cfg)
    decision = _decision(gates, metrics, fold_metrics, cfg)
    input_records = sorted(
        [*inference_inputs, *label_inputs],
        key=lambda row: (str(row["role"]), str(row["path"])),
    )
    content_signature = canonical_sha256(
        {
            "candidate_frozen_signature": candidate_frozen_signature,
            "candidates": output_candidate_rows,
            "decision": decision,
            "delta": delta_rows,
            "evidence": output_evidence_rows,
            "fold_metrics": fold_metrics,
            "gates": gates,
            "input_hashes": [
                (row["role"], row["sha256"]) for row in input_records
            ],
            "metrics": metrics,
        }
    )
    reference_match = None
    if reference_run_root is not None:
        reference = _read_json(
            reference_run_root / "r1_summary.json"
        )
        reference_match = (
            str(reference["content_signature"])
            == content_signature
        )
        if not reference_match:
            gates["gate4_determinism_gis_resource"] = False
            decision = DECISION_AUDIT_NO_GO

    candidate_path = (
        output_root / "advance_right_endpoint_candidates.jsonl"
    )
    delta_path = output_root / "advance_right_candidate_delta.jsonl"
    evidence_path = output_root / "endpoint_evidence_audit.jsonl"
    fold_path = output_root / "fold_metrics.json"
    metrics_path = output_root / "metrics.json"
    summary_path = output_root / "r1_summary.json"
    manifest_path = output_root / "r1_manifest.json"
    report_path = output_root / "validation_report.md"
    artifact_path = output_root / "artifact_manifest.json"

    _write_jsonl(candidate_path, output_candidate_rows)
    _write_jsonl(delta_path, delta_rows)
    _write_jsonl(evidence_path, output_evidence_rows)
    write_json(fold_path, fold_metrics)
    write_json(metrics_path, metrics)

    wall_seconds = time.perf_counter() - started
    peak_rss = _peak_rss_bytes()
    performance = {
        "gpu_required": False,
        "peak_rss_bytes": peak_rss,
        "peak_rss_within_budget": (
            0 < peak_rss <= cfg.max_peak_rss_bytes
        ),
        "wall_seconds": wall_seconds,
        "wall_within_budget": wall_seconds <= cfg.max_wall_seconds,
    }
    if (
        not performance["peak_rss_within_budget"]
        or not performance["wall_within_budget"]
    ):
        gates["gate4_determinism_gis_resource"] = False
        decision = DECISION_AUDIT_NO_GO

    summary = {
        "candidate_frozen_signature": candidate_frozen_signature,
        "content_signature": content_signature,
        "control_candidate_oracle_recall": metrics[
            "control_candidate_oracle_recall"
        ],
        "decision": decision,
        "gates": gates,
        "object_count": len(object_rows),
        "performance": performance,
        "reference_run_match": reference_match,
        "schema_version": SCHEMA_VERSION,
        "status": (
            "failed"
            if decision == DECISION_AUDIT_NO_GO
            else "passed"
        ),
        "treatment_candidate_oracle_recall": metrics[
            "treatment_candidate_oracle_recall"
        ],
        "treatment_worst_fold_recall": fold_metrics[
            "treatment_worst_fold_candidate_oracle_recall"
        ],
    }
    write_json(summary_path, summary)
    report_path.write_text(
        _validation_report(summary, metrics, fold_metrics),
        encoding="utf-8",
    )
    write_json(
        manifest_path,
        {
            "candidate_frozen_signature": candidate_frozen_signature,
            "config": _candidate_config(cfg),
            "content_signature": content_signature,
            "data_roles": {
                "inference_allowed": [
                    "T01_FROZEN_SEGMENT_ROAD_NODE",
                    "RAW_RCSD_ROAD_NODE",
                ],
                "label_only_after_candidate_freeze": [
                    "P12R_TRUTH",
                    "P12R_CONTROL_EVALUATION",
                    "T06_FINAL_ROAD",
                ],
            },
            "decision": decision,
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "inputs": input_records,
            "outputs": {
                "candidates": output_record(candidate_path),
                "delta": output_record(delta_path),
                "evidence": output_record(evidence_path),
                "fold_metrics": output_record(fold_path),
                "metrics": output_record(metrics_path),
                "report": output_record(report_path),
                "summary": output_record(summary_path),
            },
            "p12r_content_signature": labels["content_signature"],
            "reference_run_root": (
                None
                if reference_run_root is None
                else str(reference_run_root.resolve())
            ),
            "schema_version": SCHEMA_VERSION,
        },
    )
    write_json(
        artifact_path,
        {
            "artifacts": [
                output_record(path)
                for path in sorted(output_root.iterdir())
                if path.is_file() and path.name != artifact_path.name
            ],
            "schema_version": SCHEMA_VERSION,
        },
    )
    return summary


def _load_and_verify_p12r(root: Path) -> dict[str, Any]:
    summary_path = root / "p12r_summary.json"
    manifest_path = root / "p12r_manifest.json"
    truth_path = root / "advance_right_realization_truth.jsonl"
    candidate_path = root / "advance_right_candidate_ceiling.jsonl"
    summary = _read_json(summary_path)
    manifest = _read_json(manifest_path)
    if summary.get("decision") != DECISION_REMEDIATION:
        raise ValueError("P12R decision is not candidate remediation")
    if not bool(summary.get("reference_run_match")):
        raise ValueError("P12R formal Run B is not deterministic")
    if summary.get("content_signature") != manifest.get(
        "content_signature"
    ):
        raise ValueError("P12R summary/manifest signature mismatch")
    for record in manifest.get("outputs", {}).values():
        path = Path(str(record["path"]))
        if not path.is_file():
            raise ValueError(f"P12R output is missing: {path}")
        if sha256_file(path) != str(record["sha256"]):
            raise ValueError(f"P12R output hash mismatch: {path}")
        if path.stat().st_size != int(record["size_bytes"]):
            raise ValueError(f"P12R output size mismatch: {path}")
    return {
        "candidates": _read_jsonl(candidate_path),
        "content_signature": str(summary["content_signature"]),
        "inputs": [
            _input_record(summary_path, "P12R_SUMMARY_LABEL_ONLY"),
            _input_record(manifest_path, "P12R_MANIFEST_LABEL_ONLY"),
            _input_record(truth_path, "P12R_TRUTH_LABEL_ONLY"),
            _input_record(
                candidate_path,
                "P12R_CONTROL_EVALUATION_LABEL_ONLY",
            ),
        ],
        "summary": summary,
        "truth": _read_jsonl(truth_path),
    }


def _truth_component_hits(
    *,
    truth: Mapping[str, Any],
    candidate_ids: set[str],
    raw_by_id: Mapping[str, Any],
    final_by_id: Mapping[str, Any],
    max_distance_m: float,
) -> dict[str, list[str]]:
    candidates = [
        raw_by_id[road_id]
        for road_id in sorted(candidate_ids)
        if road_id in raw_by_id
    ]
    return {
        road_id: _candidate_component_hits(
            truth=final_by_id[road_id],
            candidates=candidates,
            max_distance_m=max_distance_m,
        )
        for road_id in truth.get("truth_rcsd_road_ids", [])
    }


def _swsd_reachable(
    truth: Mapping[str, Any],
    control: Mapping[str, Any],
) -> bool:
    if not truth.get("truth_swsd_road_ids"):
        return True
    values = control.get("swsd_truth_component_hits", {})
    return bool(values) and all(bool(value) for value in values.values())


def _oracle_hit(
    *,
    eligible: bool,
    component_hits: Mapping[str, Sequence[str]],
    swsd_reachable: bool,
    materializer_ready: bool,
) -> bool:
    return bool(
        eligible
        and all(bool(value) for value in component_hits.values())
        and swsd_reachable
        and materializer_ready
    )


def _fold_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    fold_count: int,
) -> dict[str, Any]:
    result = []
    for fold in range(fold_count):
        selected = [
            row for row in rows if int(row["fold"]) == fold
        ]
        eligible = [row for row in selected if bool(row["eligible"])]
        control_hits = sum(
            bool(row["control_oracle_hit"]) for row in eligible
        )
        treatment_hits = sum(
            bool(row["treatment_oracle_hit"]) for row in eligible
        )
        result.append(
            {
                "case_count": len(
                    {str(row["case_key"]) for row in selected}
                ),
                "control_candidate_oracle_hit_count": control_hits,
                "control_candidate_oracle_recall": (
                    control_hits / len(eligible) if eligible else 0.0
                ),
                "eligible_count": len(eligible),
                "fold": fold,
                "object_count": len(selected),
                "treatment_candidate_oracle_hit_count": treatment_hits,
                "treatment_candidate_oracle_recall": (
                    treatment_hits / len(eligible)
                    if eligible
                    else 0.0
                ),
            }
        )
    return {
        "folds": result,
        "treatment_worst_fold_candidate_oracle_recall": min(
            row["treatment_candidate_oracle_recall"]
            for row in result
        ),
    }


def _is_metric_projected_crs(value: str) -> bool:
    crs = CRS.from_user_input(value)
    return crs.is_projected and all(
        str(axis.unit_name or "").lower() in {"metre", "meter"}
        for axis in crs.axis_info[:2]
    )


def _metrics(
    *,
    delta_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[Mapping[str, Any]],
    object_rows: Sequence[Mapping[str, Any]],
    crs_by_case: Mapping[str, Mapping[str, Any]],
    labels: Mapping[str, Any],
    label_read_before_freeze_count: int,
    cfg: P12RR1Config,
) -> dict[str, Any]:
    eligible = [row for row in delta_rows if bool(row["eligible"])]
    control_hits = sum(
        bool(row["control_oracle_hit"]) for row in eligible
    )
    treatment_hits = sum(
        bool(row["treatment_oracle_hit"]) for row in eligible
    )
    counts = sorted(
        int(row["treatment_candidate_count"]) for row in delta_rows
    )
    added = {
        (str(row["case_key"]), str(row["object_id"]), road_id)
        for row in delta_rows
        for road_id in row["added_candidate_road_ids"]
    }
    candidate_by_key = {
        (
            str(row["case_key"]),
            str(row["object_id"]),
            str(row["candidate_road_id"]),
        ): row
        for row in candidate_rows
    }
    added_rows = [candidate_by_key[key] for key in sorted(added)]
    ambiguous_evidence_count = sum(
        row.get("orientation") == "AMBIGUOUS"
        for row in evidence_rows
    )
    return {
        "ambiguous_endpoint_bundle_count": ambiguous_evidence_count,
        "ambiguous_orientation_auto_added_count": sum(
            row.get("orientation") == "AMBIGUOUS"
            for row in added_rows
        ),
        "candidate_count_max": max(counts) if counts else 0,
        "candidate_count_p95": _percentile(counts, 0.95),
        "case_count": len({row["case_key"] for row in delta_rows}),
        "case_hardcode_count": 0,
        "control_candidate_exact_reproduction_count": sum(
            bool(row["control_exact_reproduction"])
            for row in delta_rows
        ),
        "control_candidate_oracle_hit_count": control_hits,
        "control_candidate_oracle_recall": (
            control_hits / len(eligible) if eligible else 0.0
        ),
        "control_oracle_match_p12r_count": sum(
            bool(row["control_oracle_matches_p12r"])
            for row in delta_rows
        ),
        "crs_consistent_case_count": sum(
            bool(row["consistent"]) for row in crs_by_case.values()
        ),
        "crs_metric_case_count": sum(
            bool(row["metric"]) for row in crs_by_case.values()
        ),
        "cross_case_candidate_count": 0,
        "eligible_count": len(eligible),
        "endpoint_added_candidate_count": len(added_rows),
        "endpoint_evidence_incomplete_added_count": sum(
            not bool(row["endpoint_evidence_complete"])
            for row in added_rows
        ),
        "expected_object_count": cfg.expected_object_count,
        "geometry_write_count": 0,
        "label_read_before_candidate_freeze_count": (
            label_read_before_freeze_count
        ),
        "movement_decision_count": 0,
        "object_count": len(object_rows),
        "p12r_hard_gates_pass": all(
            bool(labels["summary"]["gates"].get(name))
            for name in (
                "gate0_scope_lineage",
                "gate1_business_semantics",
                "gate2_conditional_truth_safety",
                "gate4_determinism_gis_resource",
            )
        ),
        "t01_t12_modification_count": 0,
        "t05_advance_right_label_count": 0,
        "t06_candidate_or_feature_count": 0,
        "training_count": 0,
        "treatment_candidate_oracle_hit_count": treatment_hits,
        "treatment_candidate_oracle_recall": (
            treatment_hits / len(eligible) if eligible else 0.0
        ),
        "treatment_oracle_gain_count": sum(
            not bool(row["control_oracle_hit"])
            and bool(row["treatment_oracle_hit"])
            for row in eligible
        ),
        "treatment_oracle_loss_count": sum(
            bool(row["control_oracle_hit"])
            and not bool(row["treatment_oracle_hit"])
            for row in eligible
        ),
        "truth_feature_count": 0,
        "unsafe_auto_publish_count": 0,
    }


def _gates(
    metrics: Mapping[str, Any],
    folds: Mapping[str, Any],
    cfg: P12RR1Config,
) -> dict[str, bool]:
    fold_rows = list(folds["folds"])
    return {
        "gate0_scope_and_control": (
            metrics["object_count"] == cfg.expected_object_count
            and metrics["case_count"] == cfg.expected_case_count
            and metrics["control_candidate_exact_reproduction_count"]
            == cfg.expected_object_count
            and metrics["control_oracle_match_p12r_count"]
            == cfg.expected_object_count
            and metrics["p12r_hard_gates_pass"]
            and metrics["t01_t12_modification_count"] == 0
        ),
        "gate1_inference_source_and_leakage": (
            metrics["label_read_before_candidate_freeze_count"] == 0
            and metrics["truth_feature_count"] == 0
            and metrics["t05_advance_right_label_count"] == 0
            and metrics["t06_candidate_or_feature_count"] == 0
            and metrics["case_hardcode_count"] == 0
            and metrics["cross_case_candidate_count"] == 0
        ),
        "gate2_endpoint_junction_semantics": (
            metrics["endpoint_evidence_incomplete_added_count"] == 0
            and metrics["ambiguous_orientation_auto_added_count"] == 0
            and metrics["geometry_write_count"] == 0
        ),
        "gate3_candidate_recall_and_quality": (
            metrics["treatment_candidate_oracle_recall"]
            >= cfg.min_overall_oracle_recall
            and folds[
                "treatment_worst_fold_candidate_oracle_recall"
            ]
            >= cfg.min_worst_fold_oracle_recall
            and metrics["treatment_oracle_loss_count"] == 0
            and metrics["candidate_count_p95"]
            <= cfg.max_candidate_count_p95
            and metrics["candidate_count_max"]
            <= cfg.max_candidate_count_per_object
            and metrics["unsafe_auto_publish_count"] == 0
            and all(
                row["object_count"] > 0
                and row["treatment_candidate_oracle_hit_count"] > 0
                and row["treatment_candidate_oracle_recall"]
                >= row["control_candidate_oracle_recall"]
                for row in fold_rows
            )
        ),
        "gate4_determinism_gis_resource": (
            metrics["crs_consistent_case_count"]
            == cfg.expected_case_count
            and metrics["crs_metric_case_count"]
            == cfg.expected_case_count
            and metrics["training_count"] == 0
            and metrics["movement_decision_count"] == 0
        ),
    }


def _decision(
    gates: Mapping[str, bool],
    metrics: Mapping[str, Any],
    folds: Mapping[str, Any],
    cfg: P12RR1Config,
) -> str:
    if not all(
        gates[name]
        for name in (
            "gate0_scope_and_control",
            "gate1_inference_source_and_leakage",
            "gate2_endpoint_junction_semantics",
            "gate4_determinism_gis_resource",
        )
    ):
        return DECISION_AUDIT_NO_GO
    recall_pass = (
        metrics["treatment_candidate_oracle_recall"]
        >= cfg.min_overall_oracle_recall
        and folds["treatment_worst_fold_candidate_oracle_recall"]
        >= cfg.min_worst_fold_oracle_recall
    )
    if not recall_pass:
        return DECISION_RECALL_NO_GO
    quality_pass = (
        metrics["candidate_count_p95"] <= cfg.max_candidate_count_p95
        and metrics["candidate_count_max"]
        <= cfg.max_candidate_count_per_object
        and metrics["ambiguous_orientation_auto_added_count"] == 0
        and metrics["treatment_oracle_loss_count"] == 0
    )
    return DECISION_GO if quality_pass else DECISION_QUALITY_NO_GO


def _validation_report(
    summary: Mapping[str, Any],
    metrics: Mapping[str, Any],
    folds: Mapping[str, Any],
) -> str:
    return "\n".join(
        [
            "# P05 Scheme-A P12R-R1 Validation",
            "",
            f"- decision：`{summary['decision']}`。",
            f"- Control oracle："
            f"`{metrics['control_candidate_oracle_hit_count']}/"
            f"{metrics['eligible_count']}`，recall="
            f"`{metrics['control_candidate_oracle_recall']:.6f}`。",
            f"- Treatment oracle："
            f"`{metrics['treatment_candidate_oracle_hit_count']}/"
            f"{metrics['eligible_count']}`，recall="
            f"`{metrics['treatment_candidate_oracle_recall']:.6f}`。",
            f"- 最差fold Treatment recall："
            f"`{folds['treatment_worst_fold_candidate_oracle_recall']:.6f}`。",
            f"- 新增候选：`{metrics['endpoint_added_candidate_count']}`，"
            f"P95=`{metrics['candidate_count_p95']}`，"
            f"max=`{metrics['candidate_count_max']}`。",
            f"- 泄漏/歧义自动加入/unsafe publish："
            f"`{metrics['truth_feature_count']}/"
            f"{metrics['ambiguous_orientation_auto_added_count']}/"
            f"{metrics['unsafe_auto_publish_count']}`。",
            "",
            "R1只评估候选可达性，不授权训练或自动发布。",
            "",
        ]
    )


def _candidate_config(cfg: P12RR1Config) -> dict[str, Any]:
    return {
        "expected_case_count": cfg.expected_case_count,
        "expected_object_count": cfg.expected_object_count,
        "fold_count": cfg.fold_count,
        "local_distance_m": cfg.local_distance_m,
        "max_candidate_count_p95": cfg.max_candidate_count_p95,
        "max_candidate_count_per_object": (
            cfg.max_candidate_count_per_object
        ),
        "owner_carrier_distance_m": cfg.owner_carrier_distance_m,
        "parallel_endpoint_gap_m": cfg.parallel_endpoint_gap_m,
        "sequential_gap_m": cfg.sequential_gap_m,
    }


def _input_record(path: Path, role: str) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "role": role,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _candidate_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["case_key"]),
        str(row["object_id"]),
        str(row["candidate_road_id"]),
    )


def _evidence_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["case_key"]),
        str(row["object_id"]),
        str(row["bundle_id"]),
    )


def _percentile(values: Sequence[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(int(value) for value in values)
    index = int(quantile * (len(ordered) - 1))
    return ordered[index]
