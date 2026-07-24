from __future__ import annotations

import json
from dataclasses import dataclass
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


SCHEMA_VERSION = "p05-scheme-a-p2-p3-p10-human-adjudication-v1"
EXPECTED_P9_DECISION = "P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO"
DECISION_REBASELINE_NO_GAIN = (
    "P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN"
)
DECISION_PROMOTION_REOPENED = (
    "P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_REOPENED"
)
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P10_AUDIT_NO_GO"
_ALLOWED_TARGETS = frozenset(
    {"KEEP_SWSD", "REVIEW_FALLBACK", "USE_RCSD"}
)
_REQUIRED_INPUTS = (
    "control_eligible_decisions.jsonl",
    "control_evaluation.jsonl",
    "scheme_a_p2_p3_p9_summary.json",
    "treatment_eligible_decisions.jsonl",
    "treatment_evaluation.jsonl",
)


@dataclass(frozen=True)
class HumanCarrierAdjudication:
    group_id: str
    case_key: str
    object_id: str
    allowed_targets: tuple[str, ...]
    preferred_target: str
    clue_target: bool
    target_weight: float
    fallback_scope: str
    rcsd_candidate_role: str
    rationale: str

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "HumanCarrierAdjudication":
        allowed_targets = tuple(str(value) for value in payload["allowed_targets"])
        preferred_target = str(payload["preferred_target"])
        fallback_scope = str(payload.get("fallback_scope", "NONE"))
        if not allowed_targets or len(set(allowed_targets)) != len(allowed_targets):
            raise ValueError("allowed_targets must be a non-empty unique list")
        if not set(allowed_targets).issubset(_ALLOWED_TARGETS):
            raise ValueError("adjudication contains an unsupported carrier target")
        if preferred_target not in allowed_targets:
            raise ValueError("preferred_target must belong to allowed_targets")
        if fallback_scope not in {"NONE", "SEGMENT", "JUNCTION"}:
            raise ValueError("fallback_scope must be NONE, SEGMENT, or JUNCTION")
        target_weight = float(payload["target_weight"])
        if target_weight != 1.0:
            raise ValueError("object-level human adjudication must use weight 1.0")
        return cls(
            group_id=str(payload["group_id"]),
            case_key=str(payload["case_key"]),
            object_id=str(payload["object_id"]),
            allowed_targets=allowed_targets,
            preferred_target=preferred_target,
            clue_target=bool(payload["clue_target"]),
            target_weight=target_weight,
            fallback_scope=fallback_scope,
            rcsd_candidate_role=str(
                payload.get("rcsd_candidate_role", "FINAL_ALLOWED")
            ),
            rationale=str(payload["rationale"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_targets": list(self.allowed_targets),
            "case_key": self.case_key,
            "clue_target": self.clue_target,
            "fallback_scope": self.fallback_scope,
            "group_id": self.group_id,
            "object_id": self.object_id,
            "preferred_target": self.preferred_target,
            "rationale": self.rationale,
            "rcsd_candidate_role": self.rcsd_candidate_role,
            "target_weight": self.target_weight,
        }


def load_human_adjudications(
    path: Path,
) -> tuple[dict[str, HumanCarrierAdjudication], dict[str, Any]]:
    payload = _read_json(path)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("human adjudication schema version differs")
    if payload.get("truth_precedence") != "OBJECT_MANUAL_OVERRIDES_CASE":
        raise ValueError("human adjudication truth precedence differs")
    rows = [
        HumanCarrierAdjudication.from_mapping(row)
        for row in payload.get("adjudications", [])
    ]
    by_group = {row.group_id: row for row in rows}
    if len(by_group) != len(rows):
        raise ValueError("human adjudication group_id must be unique")
    if not rows:
        raise ValueError("human adjudication manifest is empty")
    return by_group, payload


def evaluate_frozen_p9_rows(
    *,
    arm: str,
    evaluations: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    adjudications: Mapping[str, HumanCarrierAdjudication],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    decision_by_key = {
        _seed_group_key(row): row
        for row in decisions
    }
    if len(decision_by_key) != len(decisions):
        raise ValueError(f"{arm} P9 decision keys are not unique")
    evaluation_by_key = {
        _seed_group_key(row): row
        for row in evaluations
    }
    if len(evaluation_by_key) != len(evaluations):
        raise ValueError(f"{arm} P9 evaluation keys are not unique")
    if set(decision_by_key) != set(evaluation_by_key):
        raise ValueError(f"{arm} P9 decision/evaluation scopes differ")

    normalized_rows: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    for key in sorted(evaluation_by_key):
        evaluation = evaluation_by_key[key]
        decision = decision_by_key[key]
        group_id = str(evaluation["group_id"])
        adjudication = adjudications.get(group_id)
        if adjudication is None:
            allowed_targets = (str(evaluation["truth_target"]),)
            preferred_target = str(evaluation["truth_target"])
            clue_target = bool(evaluation["clue_target"])
            carrier_valid = (
                evaluation["selected_candidate_id"]
                == evaluation["truth_candidate_id"]
            )
            validation_basis = "FROZEN_CANDIDATE_EXACT"
            fallback_scope = "NONE"
        else:
            _validate_adjudication_join(evaluation, adjudication)
            allowed_targets = adjudication.allowed_targets
            preferred_target = adjudication.preferred_target
            clue_target = adjudication.clue_target
            carrier_valid = str(evaluation["selected_target"]) in allowed_targets
            validation_basis = "OBJECT_MANUAL_ALLOWED_TARGET_SET"
            fallback_scope = adjudication.fallback_scope

        selected_target = str(evaluation["selected_target"])
        accepted = bool(decision["accepted"])
        review_target = "REVIEW_FALLBACK" in allowed_targets
        junction_fallback_violation = (
            fallback_scope == "JUNCTION"
            and (accepted or selected_target != "KEEP_SWSD")
        )
        row = {
            "accepted": accepted,
            "allowed_targets": list(allowed_targets),
            "arm": arm,
            "carrier_valid": carrier_valid,
            "case_key": str(evaluation["case_key"]),
            "clue_exact": bool(decision["clue_predicted"]) == clue_target,
            "clue_predicted": bool(decision["clue_predicted"]),
            "clue_target": clue_target,
            "fold": int(evaluation["fold"]),
            "group_id": group_id,
            "human_adjudicated": adjudication is not None,
            "junction_fallback_violation": junction_fallback_violation,
            "label_eligible": bool(evaluation["label_eligible"]),
            "preferred_target": preferred_target,
            "preference_hit": selected_target == preferred_target,
            "review_target": review_target,
            "schema_version": SCHEMA_VERSION,
            "seed": int(evaluation["seed"]),
            "selected_candidate_id": str(evaluation["selected_candidate_id"]),
            "selected_target": selected_target,
            "source_applicable": bool(evaluation["source_applicable"]),
            "validation_basis": validation_basis,
            "wrong_accepted": accepted and not carrier_valid,
        }
        normalized_rows.append(row)
        if adjudication is not None:
            ledger.append(
                {
                    **row,
                    "old_clue_target": bool(evaluation["clue_target"]),
                    "old_truth_candidate_id": str(
                        evaluation["truth_candidate_id"]
                    ),
                    "old_truth_target": str(evaluation["truth_target"]),
                    "rationale": adjudication.rationale,
                    "rcsd_candidate_role": adjudication.rcsd_candidate_role,
                    "target_weight": adjudication.target_weight,
                }
            )

    seeds = sorted({int(row["seed"]) for row in normalized_rows})
    seed_metrics = [
        _scope_metrics(
            [row for row in normalized_rows if int(row["seed"]) == seed],
            seed=seed,
        )
        for seed in seeds
    ]
    source_rows = [row for row in normalized_rows if row["source_applicable"]]
    metrics = {
        "adjudicated_group_count": len(adjudications),
        "adjudicated_row_count": len(ledger),
        "all_scope": _scope_metrics(normalized_rows, seed=None),
        "arm": arm,
        "clue_metrics": _clue_metrics(normalized_rows),
        "pooled_source_applicable": _source_metrics(source_rows),
        "seed_metrics": seed_metrics,
    }
    return metrics, ledger


def run_scheme_a_p2_p3_p10_adjudication_audit(
    *,
    p9_run_root: Path,
    adjudication_manifest_path: Path,
    output_root: Path,
    reference_run_root: Path | None = None,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=False)
    input_hashes = _verify_p9_artifacts(p9_run_root)
    p9_summary = _read_json(
        p9_run_root / "scheme_a_p2_p3_p9_summary.json"
    )
    p9_contract_ok = (
        p9_summary.get("decision") == EXPECTED_P9_DECISION
        and bool(p9_summary.get("audit_gate_pass"))
        and bool(p9_summary.get("architecture_gate_pass"))
        and bool(p9_summary.get("roadgraph_gate_pass"))
        and int(p9_summary.get("movement_decision_count", -1)) == 0
        and int(p9_summary.get("geometry_write_count", -1)) == 0
    )
    adjudications, raw_adjudication_manifest = load_human_adjudications(
        adjudication_manifest_path
    )
    adjudication_signature = canonical_sha256(
        [adjudications[key].to_dict() for key in sorted(adjudications)]
    )

    arm_metrics: dict[str, Any] = {}
    combined_ledger: list[dict[str, Any]] = []
    for arm in ("CONTROL", "TREATMENT"):
        prefix = arm.lower()
        evaluations = list(
            _read_jsonl(p9_run_root / f"{prefix}_evaluation.jsonl")
        )
        decisions = list(
            _read_jsonl(
                p9_run_root / f"{prefix}_eligible_decisions.jsonl"
            )
        )
        metrics, ledger = evaluate_frozen_p9_rows(
            arm=arm,
            evaluations=evaluations,
            decisions=decisions,
            adjudications=adjudications,
        )
        arm_metrics[prefix] = metrics
        combined_ledger.extend(ledger)

    expected_seeds = tuple(
        int(seed) for seed in raw_adjudication_manifest["expected_seeds"]
    )
    expected_ledger_rows = (
        len(adjudications) * len(expected_seeds) * len(arm_metrics)
    )
    observed_seeds = tuple(
        sorted({int(row["seed"]) for row in combined_ledger})
    )
    adjudication_join_ok = (
        len(combined_ledger) == expected_ledger_rows
        and observed_seeds == expected_seeds
        and all(
            metrics["adjudicated_row_count"]
            == len(adjudications) * len(expected_seeds)
            for metrics in arm_metrics.values()
        )
    )
    control_source = arm_metrics["control"]["pooled_source_applicable"]
    treatment_source = arm_metrics["treatment"]["pooled_source_applicable"]
    strict_gain = (
        treatment_source["preferred_macro_f1"]
        > control_source["preferred_macro_f1"] + 1e-12
        or treatment_source["preferred_keep_recall"]
        > control_source["preferred_keep_recall"] + 1e-12
        or treatment_source["valid_accuracy"]
        > control_source["valid_accuracy"] + 1e-12
    )
    treatment_seeds = arm_metrics["treatment"]["seed_metrics"]
    carrier_safety_gate = all(
        row["wrong_accepted_count"] == 0
        and row["review_auto_publish_count"] == 0
        and row["junction_fallback_violation_count"] == 0
        and row["carrier_safety_recall"] == 1.0
        for row in treatment_seeds
    )
    promotion_gate = (
        p9_contract_ok
        and adjudication_join_ok
        and carrier_safety_gate
        and strict_gain
    )
    audit_gate = p9_contract_ok and adjudication_join_ok
    decision = (
        DECISION_AUDIT_NO_GO
        if not audit_gate
        else (
            DECISION_PROMOTION_REOPENED
            if promotion_gate
            else DECISION_REBASELINE_NO_GAIN
        )
    )

    metrics = {
        "adjudication_join_gate_pass": adjudication_join_ok,
        "carrier_safety_gate_pass": carrier_safety_gate,
        "comparison": {
            "control": control_source,
            "pooled_strict_gain": strict_gain,
            "promotion_gate_pass": promotion_gate,
            "treatment": treatment_source,
        },
        "control": arm_metrics["control"],
        "p9_contract_gate_pass": p9_contract_ok,
        "treatment": arm_metrics["treatment"],
    }
    content_signature = canonical_sha256(
        {
            "adjudication_signature": adjudication_signature,
            "decision": decision,
            "input_hashes": input_hashes,
            "ledger": combined_ledger,
            "metrics": metrics,
        }
    )
    reference_match = None
    if reference_run_root is not None:
        reference_summary = _read_json(
            reference_run_root / "scheme_a_p2_p3_p10_summary.json"
        )
        reference_match = (
            reference_summary.get("content_signature")
            == content_signature
        )
        if not reference_match:
            audit_gate = False
            decision = DECISION_AUDIT_NO_GO

    snapshot_path = output_root / "human_adjudication_snapshot.json"
    ledger_path = output_root / "adjudication_ledger.jsonl"
    metrics_path = output_root / "metrics.json"
    summary_path = output_root / "scheme_a_p2_p3_p10_summary.json"
    report_path = output_root / "validation_report.md"
    manifest_path = output_root / "scheme_a_p2_p3_p10_manifest.json"
    artifact_manifest_path = output_root / "artifact_manifest.json"

    write_json(
        snapshot_path,
        {
            **raw_adjudication_manifest,
            "adjudication_signature": adjudication_signature,
        },
    )
    _write_jsonl(
        ledger_path,
        sorted(
            combined_ledger,
            key=lambda row: (
                row["arm"],
                row["seed"],
                row["group_id"],
            ),
        ),
    )
    write_json(metrics_path, metrics)
    summary = {
        "adjudication_group_count": len(adjudications),
        "adjudication_signature": adjudication_signature,
        "audit_gate_pass": audit_gate,
        "carrier_safety_gate_pass": carrier_safety_gate,
        "content_signature": content_signature,
        "decision": decision,
        "expected_seeds": list(expected_seeds),
        "geometry_write_count": 0,
        "model_weight_change_count": 0,
        "movement_decision_count": 0,
        "p9_frozen": True,
        "promotion_gate_pass": promotion_gate,
        "reference_run_match": reference_match,
        "schema_version": SCHEMA_VERSION,
        "training_count": 0,
    }
    write_json(summary_path, summary)
    report_path.write_text(
        _validation_report(summary, metrics),
        encoding="utf-8",
    )
    write_json(
        manifest_path,
        {
            "adjudication_input": {
                "path": str(adjudication_manifest_path.resolve()),
                "sha256": sha256_file(adjudication_manifest_path),
            },
            "decision": decision,
            "input_hashes": input_hashes,
            "outputs": {
                "adjudication_ledger": output_record(ledger_path),
                "human_adjudication_snapshot": output_record(snapshot_path),
                "metrics": output_record(metrics_path),
                "summary": output_record(summary_path),
                "validation_report": output_record(report_path),
            },
            "p9_run_root": str(p9_run_root.resolve()),
            "reference_run_root": (
                None
                if reference_run_root is None
                else str(reference_run_root.resolve())
            ),
            "schema_version": SCHEMA_VERSION,
        },
    )
    write_json(
        artifact_manifest_path,
        {
            "artifacts": [
                output_record(path)
                for path in sorted(output_root.iterdir())
                if path.is_file() and path.name != artifact_manifest_path.name
            ],
            "schema_version": SCHEMA_VERSION,
        },
    )
    return summary


def _verify_p9_artifacts(p9_run_root: Path) -> dict[str, str]:
    artifact_manifest = _read_json(p9_run_root / "artifact_manifest.json")
    records = {
        Path(str(row["path"])).name: row
        for row in artifact_manifest.get("artifacts", [])
    }
    verified: dict[str, str] = {}
    for name in _REQUIRED_INPUTS:
        path = p9_run_root / name
        record = records.get(name)
        if record is None or not path.is_file():
            raise ValueError(f"P9 required artifact is missing: {name}")
        digest = sha256_file(path)
        if digest != record.get("sha256"):
            raise ValueError(f"P9 artifact hash differs: {name}")
        if path.stat().st_size != int(record.get("size_bytes", -1)):
            raise ValueError(f"P9 artifact size differs: {name}")
        verified[name] = digest
    return verified


def _validate_adjudication_join(
    evaluation: Mapping[str, Any],
    adjudication: HumanCarrierAdjudication,
) -> None:
    if evaluation["case_key"] != adjudication.case_key:
        raise ValueError("adjudication case_key differs from P9 evaluation")
    object_id = str(evaluation["group_id"]).rsplit(":", maxsplit=1)[-1]
    if object_id != adjudication.object_id:
        raise ValueError("adjudication object_id differs from P9 evaluation")


def _scope_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: int | None,
) -> dict[str, Any]:
    unsafe_count = sum(
        (not bool(row["carrier_valid"])) or bool(row["review_target"])
        for row in rows
    )
    wrong_accepted = sum(bool(row["wrong_accepted"]) for row in rows)
    review_auto = sum(
        bool(row["accepted"]) and bool(row["review_target"])
        for row in rows
    )
    junction_violations = sum(
        bool(row["junction_fallback_violation"]) for row in rows
    )
    safety_errors = wrong_accepted + review_auto + junction_violations
    return {
        "carrier_safety_recall": (
            1.0 - safety_errors / max(1, unsafe_count)
        ),
        "group_count": len(rows),
        "junction_fallback_violation_count": junction_violations,
        "review_auto_publish_count": review_auto,
        "seed": seed,
        "wrong_accepted_count": wrong_accepted,
    }


def _source_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    classification = _preferred_classification_metrics(rows)
    return {
        "group_count": len(rows),
        "preferred_accuracy": (
            sum(bool(row["preference_hit"]) for row in rows) / max(1, len(rows))
        ),
        **classification,
        "valid_accuracy": (
            sum(bool(row["carrier_valid"]) for row in rows) / max(1, len(rows))
        ),
    }


def _preferred_classification_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    classes = ("KEEP_SWSD", "REVIEW_FALLBACK", "USE_RCSD")
    f1_values: list[float] = []
    keep_true = 0
    keep_correct = 0
    for label in classes:
        true_positive = sum(
            row["preferred_target"] == label
            and row["selected_target"] == label
            for row in rows
        )
        false_positive = sum(
            row["preferred_target"] != label
            and row["selected_target"] == label
            for row in rows
        )
        false_negative = sum(
            row["preferred_target"] == label
            and row["selected_target"] != label
            for row in rows
        )
        denominator = 2 * true_positive + false_positive + false_negative
        f1_values.append(
            1.0 if denominator == 0 else 2 * true_positive / denominator
        )
        if label == "KEEP_SWSD":
            keep_true = true_positive + false_negative
            keep_correct = true_positive
    return {
        "preferred_keep_recall": keep_correct / max(1, keep_true),
        "preferred_macro_f1": sum(f1_values) / len(f1_values),
    }


def _clue_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    true_positive = sum(
        bool(row["clue_target"]) and bool(row["clue_predicted"])
        for row in rows
    )
    false_positive = sum(
        not bool(row["clue_target"]) and bool(row["clue_predicted"])
        for row in rows
    )
    false_negative = sum(
        bool(row["clue_target"]) and not bool(row["clue_predicted"])
        for row in rows
    )
    true_negative = len(rows) - true_positive - false_positive - false_negative
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    positive_f1 = (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    negative_precision = true_negative / max(1, true_negative + false_negative)
    negative_recall = true_negative / max(1, true_negative + false_positive)
    negative_f1 = (
        0.0
        if negative_precision + negative_recall == 0
        else 2
        * negative_precision
        * negative_recall
        / (negative_precision + negative_recall)
    )
    return {
        "false_negative": false_negative,
        "false_positive": false_positive,
        "macro_f1": (positive_f1 + negative_f1) / 2,
        "precision": precision,
        "recall": recall,
        "true_negative": true_negative,
        "true_positive": true_positive,
    }


def _validation_report(
    summary: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> str:
    comparison = metrics["comparison"]
    treatment = metrics["treatment"]
    adjudicated = treatment["adjudicated_row_count"]
    return (
        "# P05 Scheme-A P2-P3-P10 Validation\n\n"
        f"- decision: `{summary['decision']}`\n"
        f"- adjudicated treatment rows: `{adjudicated}`\n"
        f"- carrier safety gate: `{summary['carrier_safety_gate_pass']}`\n"
        f"- pooled strict gain: `{comparison['pooled_strict_gain']}`\n"
        f"- promotion gate: `{summary['promotion_gate_pass']}`\n"
        f"- P9 frozen / training count: `{summary['p9_frozen']}` / "
        f"`{summary['training_count']}`\n"
        f"- reference run match: `{summary['reference_run_match']}`\n"
    )


def _seed_group_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row["seed"]), str(row["group_id"])


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_PROMOTION_REOPENED",
    "DECISION_REBASELINE_NO_GAIN",
    "HumanCarrierAdjudication",
    "evaluate_frozen_p9_rows",
    "load_human_adjudications",
    "run_scheme_a_p2_p3_p10_adjudication_audit",
]
