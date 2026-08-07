from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    P12RConfig,
    _audit_case,
    _read_roads,
    _resolve_case_paths,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_audit import (
    _candidate_config,
    _candidate_key,
    _evidence_key,
    _oracle_hit,
    _row_key,
    _swsd_reachable,
    _truth_component_hits,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_candidates import (
    build_truth_free_case_candidates,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_models import (
    P12RR1Config,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


EXPECTED_R1_CANDIDATE_SIGNATURE = (
    "84344d11cdc168cea42cdaacd0c36f83f9f4b57e45dd01b802a9c35ce064f734"
)


def build_advance_right_candidate_label_store(
    *,
    target_label_root: Path,
    poc_data_root: Path,
    output_root: Path,
) -> Path:
    """Rebuild P12R-R1 candidates first, then attach T06 label-only truth."""
    started = time.perf_counter()
    label_root = normalize_runtime_path(target_label_root).resolve(strict=True)
    data_root = normalize_runtime_path(poc_data_root).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    case_rows = [
        row
        for row in _read_jsonl(label_root / "case_inventory.jsonl")
        if int(row.get("advance_right_count") or 0) > 0
    ]
    if len(case_rows) != 6:
        raise ValueError("Target A AdvanceRight Case scope differs")
    r1_config = P12RR1Config()
    p12r_config = P12RConfig()
    objects: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    case_cache: dict[
        str,
        tuple[Any, Mapping[str, Any], int, Sequence[Any]],
    ] = {}
    inference_inputs: list[dict[str, str]] = []

    # Candidate phase: only frozen T01 and raw RCSD inputs are opened.
    for case_row in sorted(case_rows, key=lambda row: str(row["case_key"])):
        paths, skeleton = _resolve_case_paths(
            baseline_root=label_root,
            case_row=case_row,
            poc_data_root=data_root,
        )
        t01_roads = _read_roads(paths.t01_roads)
        raw_roads = _read_roads(paths.raw_rcsd_roads)
        built = build_truth_free_case_candidates(
            case_key=paths.case_key,
            skeleton=skeleton,
            t01_roads=t01_roads,
            raw_rcsd_roads=raw_roads,
            config=r1_config,
        )
        objects.extend(built["objects"])
        candidates.extend(built["candidates"])
        evidence.extend(built["evidence"])
        fold = int(case_row["fold"])
        case_cache[paths.case_key] = (
            paths,
            skeleton,
            fold,
            raw_roads,
        )
        for role, path in (
            ("FROZEN_SKELETON", paths.frozen_skeleton),
            ("T01_ROADS", paths.t01_roads),
            ("T01_NODES", paths.t01_nodes),
            ("RAW_RCSD_ROADS", paths.raw_rcsd_roads),
            ("RAW_RCSD_NODES", paths.raw_rcsd_nodes),
        ):
            inference_inputs.append(
                {
                    "case_key": paths.case_key,
                    "path": str(path.resolve()),
                    "role": role,
                    "sha256": sha256_file(path),
                }
            )
    candidates.sort(key=_candidate_key)
    evidence.sort(key=_evidence_key)
    objects.sort(key=_row_key)
    candidate_signature = canonical_sha256(
        {
            "candidates": candidates,
            "config": _candidate_config(r1_config),
            "evidence": evidence,
            "objects": objects,
        }
    )
    object_path = root / "advance_right_objects.jsonl"
    candidate_path = root / "advance_right_candidates.jsonl"
    evidence_path = root / "endpoint_evidence.jsonl"
    _write_jsonl(object_path, objects)
    _write_jsonl(candidate_path, candidates)
    _write_jsonl(evidence_path, evidence)
    frozen_candidate_hashes = {
        path.name: sha256_file(path)
        for path in (object_path, candidate_path, evidence_path)
    }

    # Label phase starts only after all inference candidates are immutable.
    truth: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []
    p12r_candidates: list[dict[str, Any]] = []
    p12r_evaluation: dict[tuple[str, str], dict[str, Any]] = {}
    label_inputs: list[dict[str, str]] = []
    object_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in objects
    }
    for case_key in sorted(case_cache):
        paths, skeleton, fold, raw_roads = case_cache[case_key]
        audited = _audit_case(
            case_paths=paths,
            skeleton=skeleton,
            fold=fold,
            manual_rows={},
            cfg=p12r_config,
        )
        truth.extend(audited["truth"])
        attachments.extend(audited["attachments"])
        p12r_candidates.extend(audited["candidates"])
        audit_by_id = {
            str(row["object_id"]): row for row in audited["candidates"]
        }
        final_by_id = {
            road.road_id: road for road in _read_roads(paths.t06_final_roads)
        }
        raw_by_id = {road.road_id: road for road in raw_roads}
        for truth_row in audited["truth"]:
            object_id = str(truth_row["object_id"])
            key = (case_key, object_id)
            audit = audit_by_id[object_id]
            candidate_object = object_by_key[key]
            component_hits = _truth_component_hits(
                truth=truth_row,
                candidate_ids={
                    str(value)
                    for value in candidate_object[
                        "treatment_candidate_road_ids"
                    ]
                },
                raw_by_id=raw_by_id,
                final_by_id=final_by_id,
                max_distance_m=r1_config.local_distance_m,
            )
            swsd_reachable = _swsd_reachable(truth_row, audit)
            eligible = bool(audit["eligible"])
            materializer_ready = bool(audit["materializer_ready"])
            p12r_evaluation[key] = {
                "eligible": eligible,
                "materializer_ready": materializer_ready,
                "swsd_reachable": swsd_reachable,
                "treatment_truth_component_hits": component_hits,
                "treatment_oracle_hit": _oracle_hit(
                    eligible=eligible,
                    component_hits=component_hits,
                    swsd_reachable=swsd_reachable,
                    materializer_ready=materializer_ready,
                ),
            }
        for role, path in (
            ("T06_RELATION_LABEL", paths.t06_relation),
            ("T06_ATTACHMENT_LABEL", paths.t06_attachment_audit),
            ("T06_CLOSURE_LABEL", paths.t06_closure_audit),
            ("T06_TOPOLOGY_LABEL", paths.t06_topology_audit),
            ("T06_FINAL_ROADS_LABEL", paths.t06_final_roads),
            ("T06_FINAL_NODES_LABEL", paths.t06_final_nodes),
        ):
            label_inputs.append(
                {
                    "case_key": case_key,
                    "path": str(path.resolve()),
                    "role": role,
                    "sha256": sha256_file(path),
                }
            )
    truth.sort(key=_row_key)
    attachments.sort(key=_row_key)
    truth_keys = {
        (str(row["case_key"]), str(row["object_id"])) for row in truth
    }
    p12r_candidate_by_key = {
        (str(row["case_key"]), str(row["object_id"])): row
        for row in p12r_candidates
    }
    if set(object_by_key) != truth_keys:
        raise ValueError("Target A AdvanceRight candidate/truth scope differs")
    if set(object_by_key) != set(p12r_candidate_by_key):
        raise ValueError("Target A AdvanceRight P12R audit scope differs")
    labels = [
        build_advance_right_label(
            row,
            object_by_key[(str(row["case_key"]), str(row["object_id"]))],
            p12r_candidate_by_key[
                (str(row["case_key"]), str(row["object_id"]))
            ],
            p12r_evaluation[
                (str(row["case_key"]), str(row["object_id"]))
            ],
        )
        for row in truth
    ]
    label_path = root / "advance_right_labels.jsonl"
    attachment_path = root / "advance_right_attachment_labels.jsonl"
    _write_jsonl(label_path, labels)
    _write_jsonl(attachment_path, attachments)
    metrics = _metrics(labels, candidates)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_P12R_R1_CANDIDATE_LABEL_STORE",
        "candidate_signature": candidate_signature,
        "expected_candidate_signature": EXPECTED_R1_CANDIDATE_SIGNATURE,
        "candidate_signature_matches_formal_r1": (
            candidate_signature == EXPECTED_R1_CANDIDATE_SIGNATURE
        ),
        "candidate_freeze_before_label_read": True,
        "candidate_hashes_before_label_read": frozen_candidate_hashes,
        "inference_terminal_feature_count": 0,
        "t05_advance_right_label_count": 0,
        "metrics": metrics,
        "inputs": {
            "inference": inference_inputs,
            "label_only": label_inputs,
        },
        "outputs": {
            "objects": _file_record(object_path),
            "candidates": _file_record(candidate_path),
            "evidence": _file_record(evidence_path),
            "labels": _file_record(label_path),
            "attachments": _file_record(attachment_path),
        },
        "wall_seconds": time.perf_counter() - started,
        "gate_pass": (
            candidate_signature == EXPECTED_R1_CANDIDATE_SIGNATURE
            and metrics["object_count"] == 474
            and metrics["eligible_count"] == 396
            and metrics["reachable_eligible_count"] == 388
        ),
    }
    _write_json(root / "summary.json", summary)
    return root


def build_advance_right_label(
    truth: Mapping[str, Any],
    candidate_object: Mapping[str, Any],
    p12r_candidate: Mapping[str, Any],
    p12r_evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    plan_type = str(truth["truth_plan_type"])
    treatment = {
        str(value)
        for value in candidate_object["treatment_candidate_road_ids"]
    }
    truth_rcsd = {
        str(value) for value in truth.get("truth_rcsd_road_ids") or ()
    }
    truth_swsd = {
        str(value) for value in truth.get("truth_swsd_road_ids") or ()
    }
    eligible = bool(p12r_candidate["eligible"])
    if eligible != bool(p12r_evaluation["eligible"]):
        raise ValueError("P12R eligibility rows differ")
    component_hits = {
        str(road_id): sorted(str(value) for value in values)
        for road_id, values in (
            p12r_evaluation["treatment_truth_component_hits"]
        ).items()
    }
    reachable = bool(p12r_evaluation["treatment_oracle_hit"])
    if any(value not in treatment for values in component_hits.values() for value in values):
        raise ValueError("P12R component hit is outside treatment candidates")
    return {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "case_key": str(truth["case_key"]),
        "object_id": str(truth["object_id"]),
        "fold": int(truth["fold"]),
        "truth_plan_type": plan_type,
        "truth_rcsd_road_ids": sorted(truth_rcsd),
        "truth_swsd_road_ids": sorted(truth_swsd),
        "acceptable_rcsd_candidate_ids_by_truth_road": component_hits,
        "eligible": eligible,
        "candidate_reachable": reachable,
        "swsd_reachable": bool(p12r_evaluation["swsd_reachable"]),
        "materializer_ready": bool(
            p12r_evaluation["materializer_ready"]
        ),
        "plan_task_mask": eligible and reachable,
        "fallback_task_mask": not eligible,
        "label_weight": 0.7,
        "label_only": True,
        "feature_uses_truth": False,
    }


def _metrics(
    labels: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    plan_types = Counter(str(row["truth_plan_type"]) for row in labels)
    eligible = [row for row in labels if bool(row["eligible"])]
    reachable = [
        row for row in eligible if bool(row["candidate_reachable"])
    ]
    return {
        "object_count": len(labels),
        "candidate_road_count": len(candidates),
        "eligible_count": len(eligible),
        "reachable_eligible_count": len(reachable),
        "candidate_oracle_recall": (
            len(reachable) / len(eligible) if eligible else 0.0
        ),
        "fallback_count": len(labels) - len(eligible),
        "plan_type_counts": dict(sorted(plan_types.items())),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _file_record(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": sha256_file(resolved)}


__all__ = [
    "EXPECTED_R1_CANDIDATE_SIGNATURE",
    "build_advance_right_candidate_label_store",
    "build_advance_right_label",
]
