from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)

from .carrier_graph import field_name, normalize_id, parse_ids
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
    t07_run_root: Path | None = None,
    t07_step3_run_root: Path | None = None,
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
    if t07_run_root is not None or t07_step3_run_root is not None:
        t07_rows, t07_audit = _load_t07(
            t07_run_root=t07_run_root,
            legacy_t07_step3_run_root=t07_step3_run_root,
        )
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
    internal_roots = _t03_internal_roots(root)
    internal_manifest_path = next(
        (
            path
            for internal_root in internal_roots
            for path in (
                internal_root / "t03_internal_full_input_manifest.json",
                internal_root / "internal_full_input_manifest.json",
                internal_root / "manifest.json",
            )
            if path.is_file()
        ),
        internal_roots[0] / "t03_internal_full_input_manifest.json",
    )
    internal_manifest = (
        _read_json(internal_manifest_path)
        if internal_manifest_path.is_file()
        else {}
    )
    step3_root = _discover_step3_root(
        root,
        preflight,
        internal_manifest,
        internal_roots=internal_roots,
    )
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
    *,
    t07_run_root: Path | None,
    legacy_t07_step3_run_root: Path | None,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    deprecated_locator_used = False
    if t07_run_root is not None:
        declared_root = t07_run_root.resolve()
        if not declared_root.is_dir():
            raise T12ContractError(f"T07 run root does not exist: {declared_root}")
        step2_root = _discover_t07_step2_root(declared_root)
    elif legacy_t07_step3_run_root is not None:
        legacy_root = legacy_t07_step3_run_root.resolve()
        if not legacy_root.is_dir():
            raise T12ContractError(
                f"deprecated T07 Step3 run root does not exist: {legacy_root}"
            )
        step2_root = _discover_t07_step2_root_from_legacy(legacy_root)
        declared_root = step2_root.parent
        deprecated_locator_used = True
    else:
        raise T12ContractError("T07 Step2 source was requested without a run root")

    nodes_path = step2_root / "nodes.gpkg"
    error1_path = step2_root / "node_error_1.gpkg"
    error2_path = step2_root / "node_error_2.gpkg"
    summary_path = step2_root / "t07_step2_summary.json"
    evidence_paths = [
        path
        for path in (
            step2_root / "t07_swsd_rcsd_relation_evidence.csv",
            step2_root / "t07_swsd_rcsd_relation_evidence.json",
        )
        if path.is_file()
    ]
    required = (nodes_path, error1_path, error2_path, summary_path)
    missing = [str(path) for path in required if not path.is_file()]
    if not evidence_paths:
        missing.append(
            str(step2_root / "t07_swsd_rcsd_relation_evidence.csv|json")
        )
    if missing:
        raise T12ContractError(
            "T07 Step2 root is missing formal artifacts: " + ", ".join(missing)
        )

    try:
        nodes = gpd.read_file(nodes_path)
    except Exception as exc:
        raise T12ContractError(f"cannot read T07 Step2 nodes: {nodes_path}: {exc}") from exc
    node_id_field = field_name(nodes, "id")
    state_field = field_name(nodes, "is_anchor")
    main_field = _optional_field_name(nodes, "mainnodeid")
    final_by_junction: dict[str, str] = {}
    group_members: dict[str, list[str]] = {}
    for _, source in nodes.iterrows():
        node_id = normalize_id(source[node_id_field])
        if not node_id:
            continue
        main_id = normalize_id(source[main_field]) if main_field else ""
        group_id = main_id or node_id
        group_members.setdefault(group_id, []).append(node_id)
        state = str(source[state_field] or "").strip().lower()
        if state not in {"fail1", "fail2"}:
            continue
        if node_id in final_by_junction:
            raise T12ContractError(
                f"duplicate T07 Step2 final failure representative: {node_id}"
            )
        final_by_junction[node_id] = state

    error1 = _read_t07_error_memberships(error1_path, "node_error_1")
    error2 = _read_t07_error_memberships(error2_path, "node_error_2")
    final_fail1 = {
        junction_id for junction_id, state in final_by_junction.items() if state == "fail1"
    }
    final_fail2 = {
        junction_id for junction_id, state in final_by_junction.items() if state == "fail2"
    }
    missing_error1 = sorted(final_fail1 - set(error1), key=_id_key)
    missing_error2 = sorted(final_fail2 - set(error2), key=_id_key)
    extra_error1 = sorted(set(error1) - final_fail1 - final_fail2, key=_id_key)
    extra_error2 = sorted(set(error2) - final_fail2, key=_id_key)
    if missing_error1 or extra_error1:
        raise T12ContractError(
            "T07 Step2 fail1 final state/error evidence mismatch: "
            f"missing={missing_error1} extra={extra_error1}"
        )
    if missing_error2 or extra_error2:
        raise T12ContractError(
            "T07 Step2 fail2 final state/error evidence mismatch: "
            f"missing={missing_error2} extra={extra_error2}"
        )

    summary = _read_json(summary_path)
    summary_fail1 = _required_nonnegative_int(summary, "anchor_fail1_count")
    summary_fail2 = _required_nonnegative_int(summary, "anchor_fail2_count")
    if summary_fail1 != len(final_fail1):
        raise T12ContractError(
            "T07 Step2 fail1 count mismatch: "
            f"summary={summary_fail1} final_nodes={len(final_fail1)}"
        )
    if summary_fail2 != len(final_fail2):
        raise T12ContractError(
            "T07 Step2 fail2 count mismatch: "
            f"summary={summary_fail2} final_nodes={len(final_fail2)}"
        )
    relation_evidence = _read_t07_relation_evidence(evidence_paths)
    for failure_type, final_ids, error_memberships, expected_state in (
        (
            "fail1",
            final_fail1,
            error1,
            "multiple_intersections_for_group",
        ),
        (
            "fail2",
            final_fail2,
            error2,
            "intersection_shared_by_multiple_groups",
        ),
    ):
        for target_id in sorted(final_ids, key=_id_key):
            evidence = relation_evidence.get(target_id)
            if evidence is None:
                raise T12ContractError(
                    f"T07 Step2 {failure_type} relation evidence is missing: {target_id}"
                )
            relation_state, matched_ids = evidence
            if relation_state != expected_state:
                raise T12ContractError(
                    f"T07 Step2 {failure_type} relation_state mismatch: "
                    f"target={target_id} expected={expected_state} actual={relation_state}"
                )
            expected_ids = set(error_memberships[target_id])
            if set(matched_ids) != expected_ids:
                raise T12ContractError(
                    f"T07 Step2 {failure_type} relation evidence IDs mismatch: "
                    f"target={target_id} expected={sorted(expected_ids, key=_id_key)} "
                    f"actual={matched_ids}"
                )

    rows: list[dict[str, Any]] = []
    for target_id in sorted(final_fail1, key=_id_key):
        rows.append(
            {
                "failure_type": "fail1",
                "target_id": target_id,
                "related_target_ids": [target_id],
                "base_ids": sorted(error1[target_id], key=_id_key),
                "target_group_node_ids": sorted(
                    set(group_members.get(target_id) or [target_id]),
                    key=_id_key,
                ),
                "source_step2_root": str(step2_root),
            }
        )
    for targets, base_ids in _fail2_components(
        {target_id: error2[target_id] for target_id in final_fail2}
    ):
        rows.append(
            {
                "failure_type": "fail2",
                "target_id": targets[0],
                "related_target_ids": targets,
                "base_ids": base_ids,
                "target_group_node_ids_by_target": {
                    target_id: sorted(
                        set(group_members.get(target_id) or [target_id]),
                        key=_id_key,
                    )
                    for target_id in targets
                },
                "source_step2_root": str(step2_root),
            }
        )
    rows.sort(
        key=lambda row: (
            0 if row["failure_type"] == "fail1" else 1,
            _id_key(str(row["target_id"])),
        )
    )
    artifact_paths = [*required, *evidence_paths]
    return tuple(rows), {
        "provided": True,
        "source_kind": "t07_step2_final_anchor_failure",
        "t07_run_root": str(declared_root),
        "step2_run_root": str(step2_root),
        "row_count": len(rows),
        "final_fail1_count": len(final_fail1),
        "final_fail2_count": len(final_fail2),
        "final_fail1_junction_ids": sorted(final_fail1, key=_id_key),
        "final_fail2_junction_ids": sorted(final_fail2, key=_id_key),
        "by_failure_type": _count_by(rows, "failure_type"),
        "relation_evidence_validated_failure_count": len(final_by_junction),
        "step3_cardinality_import_count": 0,
        "deprecated_step3_locator_used": deprecated_locator_used,
        "deprecated_step3_run_root": (
            str(legacy_t07_step3_run_root.resolve())
            if legacy_t07_step3_run_root is not None
            else ""
        ),
        "artifacts": {path.name: _file_audit(path) for path in artifact_paths},
        "silent_fix": False,
    }


def _discover_t07_step2_root(root: Path) -> Path:
    candidates = (root, root / "step2_anchor_recognition")
    for candidate in candidates:
        if (
            (candidate / "nodes.gpkg").is_file()
            and (candidate / "t07_step2_summary.json").is_file()
        ):
            return candidate.resolve()
    raise T12ContractError(f"cannot discover T07 Step2 formal root from {root}")


def _discover_t07_step2_root_from_legacy(step3_root: Path) -> Path:
    try:
        return _discover_t07_step2_root(step3_root)
    except T12ContractError:
        pass
    search_roots = [step3_root, *list(step3_root.parents)[:4]]
    found: dict[str, Path] = {}
    for search_root in search_roots:
        direct = (
            search_root / "step2_anchor_recognition",
            search_root / "t07_step12" / "t07_step12" / "step2_anchor_recognition",
        )
        shallow = [
            *search_root.glob("*/step2_anchor_recognition"),
            *search_root.glob("*/*/step2_anchor_recognition"),
        ]
        for candidate in (*direct, *shallow):
            if (
                (candidate / "nodes.gpkg").is_file()
                and (candidate / "t07_step2_summary.json").is_file()
            ):
                resolved = candidate.resolve()
                found[str(resolved)] = resolved
    if len(found) == 1:
        return next(iter(found.values()))
    if not found:
        raise T12ContractError(
            "deprecated --t07-step3-run-root cannot locate the corresponding "
            "T07 Step2 root; provide --t07-run-root"
        )
    raise T12ContractError(
        "deprecated --t07-step3-run-root resolves multiple T07 Step2 roots; "
        "provide --t07-run-root explicitly"
    )


def _read_t07_error_memberships(
    path: Path,
    expected_error_type: str,
) -> dict[str, set[str]]:
    try:
        frame = gpd.read_file(path)
    except Exception as exc:
        raise T12ContractError(f"cannot read T07 Step2 error evidence {path}: {exc}") from exc
    if frame.empty:
        return {}
    junction_field = _optional_field_name(frame, "junction_id")
    representative_field = _optional_field_name(frame, "representative_node_id")
    intersections_field = _optional_field_name(frame, "intersection_ids")
    error_field = _optional_field_name(frame, "error_type")
    if junction_field is None and representative_field is None:
        raise T12ContractError(
            f"T07 Step2 error evidence has no junction identity field: {path}"
        )
    output: dict[str, set[str]] = {}
    for _, source in frame.iterrows():
        if error_field:
            error_type = str(source[error_field] or "").strip()
            if error_type and error_type != expected_error_type:
                raise T12ContractError(
                    f"T07 error evidence type mismatch in {path}: {error_type}"
                )
        target_id = normalize_id(
            source[junction_field]
            if junction_field
            else source[representative_field]  # type: ignore[index]
        )
        if not target_id:
            raise T12ContractError(f"T07 error evidence has empty junction ID: {path}")
        base_ids = (
            parse_ids(source[intersections_field]) if intersections_field else []
        )
        output.setdefault(target_id, set()).update(base_ids)
    return output


def _read_t07_relation_evidence(
    paths: list[Path],
) -> dict[str, tuple[str, list[str]]]:
    canonical_by_path: list[tuple[Path, dict[str, tuple[str, list[str]]]]] = []
    for path in paths:
        if path.suffix.lower() == ".csv":
            raw_rows = pd.read_csv(path, dtype=str).fillna("").to_dict("records")
        else:
            payload = _read_json(path)
            rows_value = payload.get("rows")
            if not isinstance(rows_value, list):
                raise T12ContractError(
                    f"T07 relation evidence JSON has no rows array: {path}"
                )
            raw_rows = [dict(row) for row in rows_value if isinstance(row, dict)]
        by_target: dict[str, tuple[str, list[str]]] = {}
        for row in raw_rows:
            target_id = normalize_id(row.get("target_id"))
            if not target_id:
                raise T12ContractError(
                    f"T07 relation evidence has empty target_id: {path}"
                )
            if target_id in by_target:
                raise T12ContractError(
                    f"T07 relation evidence has duplicate target_id: {path}: {target_id}"
                )
            relation_source = str(row.get("relation_source") or "").strip()
            if relation_source and relation_source != "T07_STEP2":
                raise T12ContractError(
                    f"T07 Step2 relation evidence has invalid source: {target_id}: {relation_source}"
                )
            by_target[target_id] = (
                str(row.get("relation_state") or "").strip(),
                sorted(
                    set(parse_ids(row.get("matched_rcsdintersection_ids"))),
                    key=_id_key,
                ),
            )
        canonical_by_path.append((path, by_target))
    canonical = canonical_by_path[0][1]
    for path, other in canonical_by_path[1:]:
        if other != canonical:
            raise T12ContractError(
                f"T07 relation evidence CSV/JSON mismatch: {canonical_by_path[0][0]} != {path}"
            )
    return canonical


def _fail2_components(
    target_to_bases: dict[str, set[str]],
) -> list[tuple[list[str], list[str]]]:
    base_to_targets: dict[str, set[str]] = {}
    for target_id, base_ids in target_to_bases.items():
        if not base_ids:
            raise T12ContractError(
                f"T07 Step2 fail2 has no RCSDIntersection IDs: {target_id}"
            )
        for base_id in base_ids:
            base_to_targets.setdefault(base_id, set()).add(target_id)
    remaining = set(target_to_bases)
    components: list[tuple[list[str], list[str]]] = []
    while remaining:
        pending_targets = [min(remaining, key=_id_key)]
        component_targets: set[str] = set()
        component_bases: set[str] = set()
        while pending_targets:
            target_id = pending_targets.pop()
            if target_id in component_targets:
                continue
            component_targets.add(target_id)
            remaining.discard(target_id)
            for base_id in target_to_bases[target_id]:
                if base_id in component_bases:
                    continue
                component_bases.add(base_id)
                pending_targets.extend(base_to_targets.get(base_id, ()))
        if len(component_targets) < 2:
            raise T12ContractError(
                "T07 Step2 fail2 component has fewer than two semantic junctions: "
                + ",".join(sorted(component_targets, key=_id_key))
            )
        components.append(
            (
                sorted(component_targets, key=_id_key),
                sorted(component_bases, key=_id_key),
            )
        )
    return sorted(components, key=lambda item: _id_key(item[0][0]))


def _optional_field_name(frame: pd.DataFrame, requested: str) -> str | None:
    by_lower = {str(column).lower(): str(column) for column in frame.columns}
    return by_lower.get(requested.lower())


def _required_nonnegative_int(payload: dict[str, Any], field: str) -> int:
    try:
        value = int(payload[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise T12ContractError(f"T07 Step2 summary has invalid {field}") from exc
    if value < 0:
        raise T12ContractError(f"T07 Step2 summary has negative {field}")
    return value


def _discover_step3_root(
    root: Path,
    preflight: dict[str, Any],
    internal_manifest: dict[str, Any],
    *,
    internal_roots: tuple[Path, ...],
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
    for internal_root in internal_roots:
        internal_step3 = internal_root / "step3_runs"
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


def _t03_internal_roots(root: Path) -> tuple[Path, ...]:
    return (
        root.parent / "_internal" / root.name,
        root / "_internal",
    )


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
