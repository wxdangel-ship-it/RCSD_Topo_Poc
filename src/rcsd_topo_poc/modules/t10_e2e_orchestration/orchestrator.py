from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    DIRECTORY_ONLY_HANDOFF_KEYS,
    EXTERNAL_INPUT_REQUIREMENTS,
    HANDOFF_REQUIREMENTS,
    T10_MODULE_ID,
    T10_T08_POLICY,
    T10_V1_CHAIN,
    T10_VERSION,
    WORKFLOW_STEPS,
)


@dataclass(frozen=True)
class T10PlanningArtifacts:
    out_dir: Path
    workflow_plan_json: Path
    handoff_audit_json: Path
    summary_json: Path


def build_workflow_plan() -> dict[str, Any]:
    return {
        "module_id": T10_MODULE_ID,
        "version": T10_VERSION,
        "chain": list(T10_V1_CHAIN),
        "t08_policy": T10_T08_POLICY,
        "steps": [
            {
                "step_id": step.step_id,
                "module_id": step.module_id,
                "consumes": list(step.consumes),
                "produces": list(step.produces),
                "notes": step.notes,
            }
            for step in WORKFLOW_STEPS
        ],
        "external_input_slots": [requirement.slot for requirement in EXTERNAL_INPUT_REQUIREMENTS],
        "handoff_slots": [requirement.slot for requirement in HANDOFF_REQUIREMENTS],
    }


def validate_t10_manifest(manifest: Mapping[str, Any], *, strict_exists: bool = False) -> dict[str, Any]:
    external_inputs = _mapping(manifest.get("external_inputs"))
    handoffs = _mapping(manifest.get("handoffs"))
    issues: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []

    for key in sorted(set(external_inputs) | set(handoffs)):
        if key in DIRECTORY_ONLY_HANDOFF_KEYS:
            issues.append(
                {
                    "severity": "error",
                    "code": "directory_only_handoff",
                    "slot": key,
                    "message": "T10 v1 requires explicit file-level artifacts, not module run directories.",
                }
            )

    for requirement in EXTERNAL_INPUT_REQUIREMENTS:
        issues.extend(_validate_slot(requirement.slot, external_inputs, strict_exists=strict_exists, source="external_inputs"))
        checked.append({"slot": requirement.slot, "source": "external_inputs", "required": requirement.required})

    for requirement in HANDOFF_REQUIREMENTS:
        issues.extend(_validate_slot(requirement.slot, handoffs, strict_exists=strict_exists, source="handoffs"))
        checked.append({"slot": requirement.slot, "source": "handoffs", "required": requirement.required})

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    return {
        "passed": error_count == 0,
        "error_count": error_count,
        "warning_count": warning_count,
        "checked_slots": checked,
        "issues": issues,
    }


def write_t10_planning_outputs(
    *,
    manifest: Mapping[str, Any],
    out_root: str | Path,
    run_id: str | None = None,
    strict_exists: bool = False,
) -> T10PlanningArtifacts:
    effective_run_id = run_id or _default_run_id()
    out_dir = Path(out_root).expanduser().resolve() / effective_run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    plan = build_workflow_plan()
    audit = validate_t10_manifest(manifest, strict_exists=strict_exists)
    summary = {
        "module_id": T10_MODULE_ID,
        "version": T10_VERSION,
        "run_id": effective_run_id,
        "produced_at_utc": _now_text(),
        "execution_mode": "contract_validation",
        "chain": list(T10_V1_CHAIN),
        "t08_policy": T10_T08_POLICY,
        "passed": audit["passed"],
        "error_count": audit["error_count"],
        "warning_count": audit["warning_count"],
        "qa": {
            "crs_and_transform": "T10 validates explicit file handoffs; CRS checks remain delegated to module runners until execution wiring.",
            "topology_consistency": "T10 does not silently repair topology; missing handoff evidence is reported as an issue.",
            "geometry_semantics": "Case package scope is declared by SWSD semantic junction id and radius.",
            "audit_traceability": "Every required external input and inter-module handoff has a named slot.",
            "performance_verifiability": "This stage records contract-validation counts; execution timings are pending runtime orchestration.",
        },
    }

    artifacts = T10PlanningArtifacts(
        out_dir=out_dir,
        workflow_plan_json=out_dir / "t10_workflow_plan.json",
        handoff_audit_json=out_dir / "t10_handoff_audit.json",
        summary_json=out_dir / "t10_summary.json",
    )
    _write_json(artifacts.workflow_plan_json, plan)
    _write_json(artifacts.handoff_audit_json, audit)
    _write_json(artifacts.summary_json, summary)
    return artifacts


def _validate_slot(slot: str, values: Mapping[str, Any], *, strict_exists: bool, source: str) -> list[dict[str, Any]]:
    if slot not in values:
        return [
            {
                "severity": "error",
                "code": "missing_required_artifact",
                "source": source,
                "slot": slot,
                "message": f"Missing required T10 artifact slot: {slot}.",
            }
        ]

    value = values[slot]
    if not isinstance(value, str) or not value.strip():
        return [
            {
                "severity": "error",
                "code": "invalid_artifact_path",
                "source": source,
                "slot": slot,
                "message": "Artifact path must be a non-empty string.",
            }
        ]

    path = Path(value).expanduser()
    issues: list[dict[str, Any]] = []
    if path.exists() and path.is_dir():
        issues.append(
            {
                "severity": "error",
                "code": "artifact_path_is_directory",
                "source": source,
                "slot": slot,
                "path": str(path),
                "message": "Artifact path points to a directory; T10 requires explicit file paths.",
            }
        )
    if strict_exists and not path.exists():
        issues.append(
            {
                "severity": "error",
                "code": "artifact_path_missing",
                "source": source,
                "slot": slot,
                "path": str(path),
                "message": "Artifact path does not exist under strict validation.",
            }
        )
    return issues


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _default_run_id() -> str:
    return "t10_e2e_orchestration_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
