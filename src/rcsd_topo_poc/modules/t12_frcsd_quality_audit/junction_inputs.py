from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)

from .carrier_graph import normalize_id
from .inputs import _file_audit
from .models import T12ContractError


@dataclass(frozen=True)
class T03CaseEvidence:
    case_id: str
    case_dir: Path
    step3_status: dict[str, Any]
    association_status: dict[str, Any]
    step6_status: dict[str, Any]
    step6_audit: dict[str, Any]
    step7_status: dict[str, Any]
    step7_audit: dict[str, Any]
    artifact_audit: dict[str, Any]


@dataclass(frozen=True)
class JunctionSources:
    t03_cases: tuple[T03CaseEvidence, ...]
    t07_rows: tuple[dict[str, Any], ...]
    t03_eligibility_nodes_path: Path | None
    audit: dict[str, Any]


def load_junction_sources(
    *,
    t03_run_root: Path | None,
    t07_step3_run_root: Path | None,
) -> JunctionSources:
    t03_cases: tuple[T03CaseEvidence, ...] = ()
    t07_rows: tuple[dict[str, Any], ...] = ()
    eligibility_nodes_path: Path | None = None
    audit: dict[str, Any] = {
        "t03": {"provided": False, "case_count": 0},
        "t07": {"provided": False, "row_count": 0},
        "silent_fix": False,
    }
    if t03_run_root is not None:
        t03_cases, eligibility_nodes_path, t03_audit = _load_t03(t03_run_root)
        audit["t03"] = t03_audit
    if t07_step3_run_root is not None:
        t07_rows, t07_audit = _load_t07(t07_step3_run_root)
        audit["t07"] = t07_audit
    return JunctionSources(
        t03_cases=t03_cases,
        t07_rows=t07_rows,
        t03_eligibility_nodes_path=eligibility_nodes_path,
        audit=audit,
    )


def _load_t03(
    run_root: Path,
) -> tuple[tuple[T03CaseEvidence, ...], Path | None, dict[str, Any]]:
    root = run_root.resolve()
    if not root.is_dir():
        raise T12ContractError(f"T03 run root does not exist: {root}")
    preflight_path = root / "preflight.json"
    preflight = _read_json(preflight_path) if preflight_path.is_file() else {}
    internal_manifest_path = next(
        (
            path
            for path in (
                root / "_internal" / "t03_internal_full_input_manifest.json",
                root / "_internal" / "internal_full_input_manifest.json",
                root / "_internal" / "manifest.json",
            )
            if path.is_file()
        ),
        root / "_internal" / "t03_internal_full_input_manifest.json",
    )
    internal_manifest = (
        _read_json(internal_manifest_path)
        if internal_manifest_path.is_file()
        else {}
    )
    step3_root = _discover_step3_root(root, preflight, internal_manifest)
    cases_root = root / "cases"
    if not cases_root.is_dir():
        raise T12ContractError(f"T03 run root is missing cases/: {root}")
    cases: list[T03CaseEvidence] = []
    incomplete: list[str] = []
    for case_dir in sorted(
        (entry for entry in cases_root.iterdir() if entry.is_dir()),
        key=lambda path: _id_key(path.name),
    ):
        step7_path = case_dir / "step7_status.json"
        if not step7_path.is_file():
            continue
        step7_status = _read_json(step7_path)
        if str(step7_status.get("step7_state") or "") != "rejected":
            continue
        step3_path = step3_root / "cases" / case_dir.name / "step3_status.json"
        association_path = case_dir / "association_status.json"
        step6_status_path = case_dir / "step6_status.json"
        step6_audit_path = case_dir / "step6_audit.json"
        step7_audit_path = case_dir / "step7_audit.json"
        required = (
            step3_path,
            step6_status_path,
            step6_audit_path,
            step7_path,
            step7_audit_path,
        )
        if any(not path.is_file() for path in required):
            incomplete.append(case_dir.name)
            continue
        step6_status = _read_json(step6_status_path)
        association_status = (
            _read_json(association_path)
            if association_path.is_file()
            else {
                key: step6_status.get(key)
                for key in (
                    "association_class",
                    "association_state",
                    "association_reason",
                    "required_rcsdnode_ids",
                    "required_rcsdroad_ids",
                    "support_rcsdnode_ids",
                    "support_rcsdroad_ids",
                    "excluded_rcsdnode_ids",
                    "excluded_rcsdroad_ids",
                )
            }
        )
        audited_paths = [*required]
        if association_path.is_file():
            audited_paths.append(association_path)
        cases.append(
            T03CaseEvidence(
                case_id=normalize_id(
                    step7_status.get("case_id") or case_dir.name
                ),
                case_dir=case_dir,
                step3_status=_read_json(step3_path),
                association_status=association_status,
                step6_status=step6_status,
                step6_audit=_read_json(step6_audit_path),
                step7_status=step7_status,
                step7_audit=_read_json(step7_audit_path),
                artifact_audit={
                    path.name: _file_audit(path) for path in audited_paths
                },
            )
        )
    if incomplete:
        raise T12ContractError(
            "T03 rejected cases have incomplete formal audit chains: "
            + ", ".join(incomplete[:50])
        )
    nodes_value = (
        preflight.get("nodes_path")
        or internal_manifest.get("nodes_path")
        or ""
    )
    nodes_path = _resolve_declared_path(nodes_value, root)
    if nodes_value and (nodes_path is None or not nodes_path.is_file()):
        raise T12ContractError(
            f"T03 eligibility nodes input cannot be resolved: {nodes_value}"
        )
    identity_paths = [path for path in (preflight_path, internal_manifest_path) if path.is_file()]
    return tuple(cases), nodes_path, {
        "provided": True,
        "run_root": str(root),
        "step3_run_root": str(step3_root),
        "case_count": len(cases),
        "rejected_case_ids": [case.case_id for case in cases],
        "eligibility_nodes_path": str(nodes_path) if nodes_path else "",
        "identity_artifacts": {
            path.name: _file_audit(path) for path in identity_paths
        },
        "artifact_count": sum(len(case.artifact_audit) for case in cases),
        "silent_fix": False,
    }


def _load_t07(
    step3_run_root: Path,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    root = step3_run_root.resolve()
    if not root.is_dir():
        raise T12ContractError(f"T07 Step3 run root does not exist: {root}")
    json_path = root / "relation_cardinality_errors.json"
    csv_path = root / "relation_cardinality_errors.csv"
    if json_path.is_file():
        payload = _read_json(json_path)
        raw_rows = payload.get("rows")
        if not isinstance(raw_rows, list):
            raise T12ContractError(
                f"T07 relation cardinality JSON has no rows array: {json_path}"
            )
        rows = [dict(row) for row in raw_rows if isinstance(row, dict)]
    elif csv_path.is_file():
        rows = pd.read_csv(csv_path, dtype=str).fillna("").to_dict("records")
    else:
        raise T12ContractError(
            f"T07 Step3 root is missing relation_cardinality_errors: {root}"
        )
    required_fields = {"error_type", "target_id", "base_id"}
    invalid = [
        index
        for index, row in enumerate(rows)
        if not required_fields.issubset(row)
    ]
    if invalid:
        raise T12ContractError(
            f"T07 relation cardinality rows miss required fields: {invalid[:20]}"
        )
    artifact_paths = [path for path in (json_path, csv_path) if path.is_file()]
    return tuple(rows), {
        "provided": True,
        "step3_run_root": str(root),
        "row_count": len(rows),
        "by_error_type": _count_by(rows, "error_type"),
        "artifacts": {path.name: _file_audit(path) for path in artifact_paths},
        "silent_fix": False,
    }


def _discover_step3_root(
    root: Path,
    preflight: dict[str, Any],
    internal_manifest: dict[str, Any],
) -> Path:
    candidates: list[Path] = []
    for value in (
        internal_manifest.get("step3_run_root"),
        preflight.get("step3_root"),
        preflight.get("step3_run_root"),
    ):
        resolved = _resolve_declared_path(value, root)
        if resolved is not None:
            candidates.append(resolved)
    candidates.extend((root, root.parent / "step3"))
    internal_step3 = root / "_internal" / "step3_runs"
    if internal_step3.is_dir():
        candidates.extend(
            sorted(
                (entry for entry in internal_step3.iterdir() if entry.is_dir()),
                key=lambda path: path.name,
            )
        )
    for candidate in candidates:
        cases_dir = candidate / "cases"
        if cases_dir.is_dir() and any(
            (case_dir / "step3_status.json").is_file()
            for case_dir in cases_dir.iterdir()
            if case_dir.is_dir()
        ):
            return candidate.resolve()
    raise T12ContractError(f"cannot discover T03 Step3 formal run root from {root}")


def _resolve_declared_path(value: Any, root: Path) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = normalize_runtime_path(text)
    if path.is_absolute():
        return path.resolve()
    for candidate in (root / path, root.parent / path, Path.cwd() / path):
        if candidate.exists():
            return candidate.resolve()
    return (root / path).resolve()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise T12ContractError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise T12ContractError(f"JSON artifact must be an object: {path}")
    return payload


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _id_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value)
