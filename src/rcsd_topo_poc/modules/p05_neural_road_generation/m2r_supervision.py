from __future__ import annotations

import csv
import json
import platform
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    EXPECTED_POC_DATA_ROOT,
    sha256_file,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_historical import (
    HistoricalTarget,
    audit_historical_surface_outputs,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


TASK_TARGET_KINDS: dict[str, tuple[str, ...]] = {
    "T03": ("object_scope", "nodes", "surface", "relation"),
    "T04": ("object_scope", "nodes", "surface", "relation"),
    "T05": ("surface", "relation", "rcsd_road", "rcsd_node"),
    "T06": ("road", "node", "segment_relation"),
    "T07": ("nodes",),
}

ROLE_TO_TARGET: dict[str, tuple[str, str]] = {
    "t03_nodes": ("T03", "nodes"),
    "t04_nodes": ("T04", "nodes"),
    "t05_intersection_match_all": ("T05", "relation"),
    "t05_rcsdroad_out": ("T05", "rcsd_road"),
    "t05_rcsdnode_out": ("T05", "rcsd_node"),
    "t06_frcsd_road": ("T06", "road"),
    "t06_frcsd_node": ("T06", "node"),
    "t06_swsd_frcsd_segment_relation": ("T06", "segment_relation"),
    "t07_nodes": ("T07", "nodes"),
}


@dataclass(frozen=True)
class M2RSupervisionConfig:
    m0_run_root: Path
    output_root: Path
    run_id: str
    enforce_poc_scope: bool = True
    historical_output_roots: tuple[Path, ...] = ()
    allow_user_confirmed_strategy_replay: bool = False
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")


@dataclass(frozen=True)
class TaskTarget:
    sample_id: str
    sample_group_id: str
    family: str
    business_id: str
    fold: int
    split: str
    task_name: str
    target_kind: str
    availability: str
    trust_tier: str
    target_weight: float
    context_weight: float
    target_selector: str
    artifact_role: str
    artifact_path: str
    artifact_sha256: str
    crs: str
    source_run: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupervisionAnomaly:
    severity: str
    category: str
    detail: str
    sample_id: str = ""
    task_name: str = ""
    target_kind: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _canonical(path: Path | str) -> Path:
    return normalize_runtime_path(path).resolve(strict=False)


def _same_path(first: Path | str, second: Path | str) -> bool:
    return str(_canonical(first)).casefold() == str(_canonical(second)).casefold()


def _resolve_output_path(run_root: Path, record: dict[str, Any]) -> Path:
    configured = _canonical(str(record.get("path") or ""))
    if configured.is_file():
        return configured
    fallback = run_root / configured.name
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(configured)


def _verify_m0_run(run_root: Path, *, strict_hashes: bool) -> tuple[dict[str, Any], dict[str, Path]]:
    manifest_path = run_root / "p05_m0_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-m0-manifest-v1":
        raise ValueError(f"unsupported M0 manifest schema: {manifest.get('schema_version')!r}")
    if manifest.get("silent_fix") is not False:
        raise ValueError("M0 manifest must declare silent_fix=false")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("M0 manifest outputs are missing")
    required = {"samples", "artifacts", "split", "anomalies", "oracle", "summary"}
    if not required.issubset(outputs):
        raise ValueError(f"M0 manifest outputs missing: {sorted(required - set(outputs))}")
    resolved: dict[str, Path] = {}
    for role in sorted(required):
        record = outputs[role]
        if not isinstance(record, dict):
            raise ValueError(f"invalid M0 output record: {role}")
        path = _resolve_output_path(run_root, record)
        if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
            raise ValueError(f"M0 output hash mismatch: {role}: {path}")
        resolved[role] = path
    return manifest, resolved


def _artifact_crs(path: Path) -> str:
    if path.suffix.casefold() not in {".gpkg", ".geojson", ".fgb", ".shp"}:
        return ""
    import fiona

    layers = fiona.listlayers(path)
    if not layers:
        return ""
    with fiona.open(path, layer=layers[0]) as source:
        if source.crs:
            return source.crs.to_string()
        if source.crs_wkt:
            return source.crs_wkt
    return ""


def _manifest_crs(path: Path) -> str:
    try:
        payload = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    epsg = payload.get("epsg")
    if epsg is None:
        return ""
    text = str(epsg).strip()
    return text if text.upper().startswith("EPSG:") else f"EPSG:{text}"


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trust_tier(sample: dict[str, str], availability: str) -> str:
    if availability != "available":
        return "unknown"
    if str(sample.get("scope_type") or "") == "single_junction_object":
        return "gold"
    return "silver"


def _artifact_index(
    artifacts: list[dict[str, str]],
) -> tuple[dict[tuple[str, str], dict[str, str]], set[tuple[str, str]], list[SupervisionAnomaly]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for artifact in artifacts:
        if artifact.get("role") in ROLE_TO_TARGET:
            grouped[(str(artifact.get("sample_id") or ""), str(artifact.get("role") or ""))].append(artifact)
    selected: dict[tuple[str, str], dict[str, str]] = {}
    invalid: set[tuple[str, str]] = set()
    anomalies: list[SupervisionAnomaly] = []
    for key, candidates in sorted(grouped.items()):
        distinct_hashes = {str(item.get("artifact_sha256") or "") for item in candidates}
        if len(distinct_hashes) > 1:
            invalid.add(key)
            anomalies.append(
                SupervisionAnomaly(
                    severity="error",
                    category="conflicting_artifact_versions",
                    detail=f"{len(candidates)} artifacts have {len(distinct_hashes)} distinct hashes",
                    sample_id=key[0],
                    path=";".join(str(item.get("artifact_path") or "") for item in candidates),
                )
            )
            continue
        selected[key] = candidates[0]
    return selected, invalid, anomalies


def derive_task_targets(
    samples: list[dict[str, str]],
    artifacts: list[dict[str, str]],
    assignments: list[dict[str, str]],
    *,
    approved_exclusions: set[tuple[str, str]],
) -> tuple[list[TaskTarget], list[SupervisionAnomaly]]:
    assignment_by_sample = {str(item.get("sample_id") or ""): item for item in assignments}
    artifact_by_key, invalid_artifacts, anomalies = _artifact_index(artifacts)
    targets: list[TaskTarget] = []

    for sample in sorted(samples, key=lambda item: str(item.get("sample_id") or "")):
        sample_id = str(sample.get("sample_id") or "")
        family = str(sample.get("family") or "")
        business_id = str(sample.get("business_id") or "")
        assignment = assignment_by_sample.get(sample_id)
        if assignment is None:
            anomalies.append(
                SupervisionAnomaly(
                    severity="error",
                    category="missing_split_assignment",
                    detail="sample has no grouped split assignment",
                    sample_id=sample_id,
                )
            )
            fold, split = -1, "unknown"
        else:
            try:
                fold = int(assignment.get("fold") or -1)
            except ValueError:
                fold = -1
            split = str(assignment.get("split") or "unknown")

        excluded = (family, business_id) in approved_exclusions
        target_weight = _float_value(sample.get("target_weight"), 0.0)
        context_weight = _float_value(sample.get("context_weight"), 0.0)
        single_point_module = ""
        if str(sample.get("scope_type") or "") == "single_junction_object":
            if family.startswith("T03"):
                single_point_module = "T03"
            elif family.startswith("T04"):
                single_point_module = "T04"

        for task_name, target_kinds in TASK_TARGET_KINDS.items():
            for target_kind in target_kinds:
                availability = "excluded" if excluded else "unknown"
                reason = "approved_sample_exclusion" if excluded else "no_traceable_target_artifact"
                artifact_role = ""
                artifact_path = ""
                artifact_sha256 = ""
                crs = ""
                source_run = ""
                target_selector = business_id

                if not excluded and target_kind == "object_scope" and task_name == single_point_module:
                    availability = "available"
                    reason = "single_point_target_object_manually_confirmed_or_corrected"
                    artifact_role = "case_manifest_scope"
                    artifact_path = str(sample.get("manifest_path") or "")
                    artifact_sha256 = str(sample.get("manifest_sha256") or "")
                    crs = _manifest_crs(_canonical(artifact_path)) if artifact_path else ""
                    source_run = "m0_case_inventory"
                elif not excluded:
                    role = next(
                        (
                            candidate_role
                            for candidate_role, mapped in ROLE_TO_TARGET.items()
                            if mapped == (task_name, target_kind)
                        ),
                        "",
                    )
                    if role:
                        artifact_role = role
                        key = (sample_id, role)
                        if key in invalid_artifacts:
                            availability = "invalid"
                            reason = "conflicting_artifact_versions"
                        elif key in artifact_by_key:
                            artifact = artifact_by_key[key]
                            artifact_path = str(artifact.get("artifact_path") or "")
                            artifact_sha256 = str(artifact.get("artifact_sha256") or "")
                            source_run = str(artifact.get("baseline_id") or "")
                            target_selector = str(artifact.get("target_selector") or business_id)
                            path = _canonical(artifact_path)
                            if not path.is_file():
                                availability = "invalid"
                                reason = "artifact_missing"
                                anomalies.append(
                                    SupervisionAnomaly(
                                        "error",
                                        "artifact_missing",
                                        f"{role} artifact is missing",
                                        sample_id,
                                        task_name,
                                        target_kind,
                                        str(path),
                                    )
                                )
                            elif artifact_sha256 and sha256_file(path) != artifact_sha256:
                                availability = "invalid"
                                reason = "artifact_hash_mismatch"
                                anomalies.append(
                                    SupervisionAnomaly(
                                        "error",
                                        "artifact_hash_mismatch",
                                        f"{role} artifact hash differs from M0 lineage",
                                        sample_id,
                                        task_name,
                                        target_kind,
                                        str(path),
                                    )
                                )
                            else:
                                try:
                                    crs = _artifact_crs(path)
                                except Exception as exc:
                                    availability = "invalid"
                                    reason = "artifact_crs_read_failed"
                                    anomalies.append(
                                        SupervisionAnomaly(
                                            "error",
                                            "artifact_crs_read_failed",
                                            str(exc),
                                            sample_id,
                                            task_name,
                                            target_kind,
                                            str(path),
                                        )
                                    )
                                else:
                                    if path.suffix.casefold() == ".gpkg" and not crs:
                                        availability = "invalid"
                                        reason = "geometry_crs_missing"
                                        anomalies.append(
                                            SupervisionAnomaly(
                                                "error",
                                                "geometry_crs_missing",
                                                f"{role} GPKG has no CRS",
                                                sample_id,
                                                task_name,
                                                target_kind,
                                                str(path),
                                            )
                                        )
                                    else:
                                        availability = "available"
                                        reason = "traceable_m0_label_artifact"
                        else:
                            reason = f"no_traceable_artifact_role:{role}"
                    elif target_kind == "object_scope" and single_point_module and task_name != single_point_module:
                        reason = "single_point_scope_only_confirms_another_task"

                targets.append(
                    TaskTarget(
                        sample_id=sample_id,
                        sample_group_id=str(sample.get("sample_group_id") or ""),
                        family=family,
                        business_id=business_id,
                        fold=fold,
                        split=split,
                        task_name=task_name,
                        target_kind=target_kind,
                        availability=availability,
                        trust_tier=_trust_tier(sample, availability),
                        target_weight=target_weight if availability == "available" else 0.0,
                        context_weight=context_weight if availability == "available" else 0.0,
                        target_selector=target_selector,
                        artifact_role=artifact_role,
                        artifact_path=artifact_path,
                        artifact_sha256=artifact_sha256,
                        crs=crs,
                        source_run=source_run,
                        reason=reason,
                    )
                )

    targets.sort(key=lambda item: (item.sample_id, item.task_name, item.target_kind))
    anomalies.sort(key=lambda item: (item.severity, item.category, item.sample_id, item.task_name, item.target_kind, item.path))
    return targets, anomalies


def _apply_historical_targets(
    targets: list[TaskTarget],
    historical_targets: list[HistoricalTarget],
) -> tuple[list[TaskTarget], list[SupervisionAnomaly]]:
    by_key = {(item.sample_id, item.task_name, item.target_kind): item for item in historical_targets}
    anomalies: list[SupervisionAnomaly] = []
    updated: list[TaskTarget] = []
    for target in targets:
        key = (target.sample_id, target.task_name, target.target_kind)
        historical = by_key.get(key)
        if historical is None:
            updated.append(target)
            continue
        if target.availability not in {"unknown"}:
            anomalies.append(
                SupervisionAnomaly(
                    severity="error",
                    category="historical_target_conflicts_with_registered_target",
                    detail=f"existing availability is {target.availability}",
                    sample_id=target.sample_id,
                    task_name=target.task_name,
                    target_kind=target.target_kind,
                    path=historical.artifact_path,
                )
            )
            updated.append(target)
            continue
        updated.append(
            replace(
                target,
                availability="available",
                trust_tier="gold",
                target_weight=1.0,
                context_weight=0.3,
                artifact_role="historical_terminal_surface_label",
                artifact_path=historical.artifact_path,
                artifact_sha256=historical.artifact_sha256,
                crs=historical.crs,
                source_run=historical.source_run,
                target_selector=historical.target_selector,
                reason=historical.reason,
            )
        )
    updated.sort(key=lambda item: (item.sample_id, item.task_name, item.target_kind))
    return updated, anomalies


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _coverage(targets: list[TaskTarget]) -> dict[str, Any]:
    availability_counts = Counter(target.availability for target in targets)
    by_target: dict[str, Any] = {}
    for task_name, target_kinds in TASK_TARGET_KINDS.items():
        for target_kind in target_kinds:
            selected = [item for item in targets if item.task_name == task_name and item.target_kind == target_kind]
            available = [item for item in selected if item.availability == "available"]
            folds = sorted({item.fold for item in available if item.fold >= 0})
            key = f"{task_name}:{target_kind}"
            by_target[key] = {
                "availability_counts": dict(sorted(Counter(item.availability for item in selected).items())),
                "available_group_count": len({item.sample_group_id for item in available}),
                "available_folds": folds,
                "assessable_in_at_least_three_folds": len(folds) >= 3,
                "family_counts": dict(sorted(Counter(item.family for item in available).items())),
                "trust_tier_counts": dict(sorted(Counter(item.trust_tier for item in available).items())),
            }
    return {
        "schema_version": "p05-m2r-task-coverage-v1",
        "target_count": len(targets),
        "availability_counts": dict(sorted(availability_counts.items())),
        "by_target": by_target,
    }


def _report(summary: dict[str, Any], coverage: dict[str, Any]) -> str:
    rows = []
    for key, item in coverage["by_target"].items():
        counts = item["availability_counts"]
        rows.append(
            f"| `{key}` | {counts.get('available', 0)} | {counts.get('unknown', 0)} | "
            f"{counts.get('invalid', 0)} | {counts.get('excluded', 0)} | "
            f"{'yes' if item['assessable_in_at_least_three_folds'] else 'no'} |"
        )
    return "\n".join(
        [
            "# P05 M2R 多任务监督就绪性报告",
            "",
            "## 摘要",
            "",
            f"- 登记样本：{summary['sample_count']}。",
            f"- 任务目标：{summary['target_count']}；available {summary['available_target_count']}；unknown {summary['unknown_target_count']}；invalid {summary['invalid_target_count']}；excluded {summary['excluded_target_count']}。",
            f"- 使用标签 lineage/hash 校验失败：{summary['label_integrity_error_count']}。",
            f"- 跨 split group 冲突：{summary['split_group_conflict_count']}。",
            f"- 总耗时：{summary['duration_seconds']:.3f} 秒。",
            "",
            "## 任务覆盖",
            "",
            "| 任务目标 | available | unknown | invalid | excluded | 至少三折可评价 |",
            "|---|---:|---:|---:|---:|---|",
            *rows,
            "",
            "## 边界",
            "",
            "`Error` 目录名没有被解释为类别。缺少可追溯历史 artifact 的任务保持 Unknown；本 run 未执行任何上游业务规则，也未补造真值。",
            "",
        ]
    )


def _current_rss_bytes() -> int:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except (ImportError, OSError):
        return 0


def build_m2r_supervision(config: M2RSupervisionConfig) -> dict[str, Any]:
    started = time.perf_counter()
    m0_root = _canonical(config.m0_run_root)
    m0_manifest, paths = _verify_m0_run(m0_root, strict_hashes=config.strict_hashes)
    poc_data_root = _canonical(str(m0_manifest.get("poc_data_root") or ""))
    if config.enforce_poc_scope and not _same_path(poc_data_root, EXPECTED_POC_DATA_ROOT):
        raise ValueError(f"P05 M2R scope violation: expected {EXPECTED_POC_DATA_ROOT}, got {poc_data_root}")

    samples = _read_csv(paths["samples"])
    artifacts = _read_csv(paths["artifacts"])
    assignments = _read_csv(paths["split"])
    approved_exclusions = {
        (str(item.get("family") or ""), str(item.get("business_id") or ""))
        for item in m0_manifest.get("approved_exclusions", [])
        if isinstance(item, dict)
    }
    targets, anomalies = derive_task_targets(
        samples,
        artifacts,
        assignments,
        approved_exclusions=approved_exclusions,
    )
    output_root = _canonical(config.output_root)
    run_root = output_root / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    historical_targets, historical_anomalies, historical_documents, historical_audit = (
        audit_historical_surface_outputs(
            samples,
            config.historical_output_roots,
            label_root=run_root / "historical_labels",
            user_confirmed_strategy_replay=config.allow_user_confirmed_strategy_replay,
        )
    )
    anomalies.extend(SupervisionAnomaly(**item) for item in historical_anomalies)
    targets, historical_conflicts = _apply_historical_targets(targets, historical_targets)
    anomalies.extend(historical_conflicts)

    groups_by_fold: dict[str, set[int]] = defaultdict(set)
    for assignment in assignments:
        try:
            groups_by_fold[str(assignment.get("sample_group_id") or "")].add(int(assignment.get("fold") or -1))
        except ValueError:
            groups_by_fold[str(assignment.get("sample_group_id") or "")].add(-1)
    split_group_conflicts = {group: sorted(folds) for group, folds in groups_by_fold.items() if len(folds) > 1}
    if split_group_conflicts:
        anomalies.append(
            SupervisionAnomaly(
                severity="error",
                category="split_group_conflict",
                detail=json.dumps(split_group_conflicts, ensure_ascii=False, sort_keys=True),
            )
        )

    coverage = _coverage(targets)
    availability = Counter(target.availability for target in targets)
    duration = time.perf_counter() - started
    summary = {
        "schema_version": "p05-m2r-supervision-summary-v1",
        "sample_count": len(samples),
        "sample_group_count": len({str(item.get("sample_group_id") or "") for item in samples}),
        "target_count": len(targets),
        "available_target_count": availability.get("available", 0),
        "unknown_target_count": availability.get("unknown", 0),
        "invalid_target_count": availability.get("invalid", 0),
        "excluded_target_count": availability.get("excluded", 0),
        "approved_exclusion_count": len(approved_exclusions),
        "historical_replay_target_count": len(historical_targets),
        "historical_surface_label_count": sum(item.target_kind == "surface" for item in historical_targets),
        "historical_relation_label_count": sum(item.target_kind == "relation" for item in historical_targets),
        "label_integrity_error_count": sum(item.severity == "error" for item in anomalies),
        "split_group_conflict_count": len(split_group_conflicts),
        "duration_seconds": duration,
        "current_rss_bytes": _current_rss_bytes(),
        "silent_fix": False,
    }

    output_root.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(exist_ok=False)
    output_paths = {
        "targets": run_root / "p05_m2r_task_targets.csv",
        "coverage": run_root / "p05_m2r_task_coverage.json",
        "anomalies": run_root / "p05_m2r_label_anomalies.csv",
        "split_audit": run_root / "p05_m2r_split_audit.json",
        "summary": run_root / "p05_m2r_supervision_summary.json",
        "report": run_root / "p05_m2r_supervision_report.md",
        "historical_audit": run_root / "p05_m2r_historical_output_audit.json",
    }
    for path, payload in historical_documents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    _write_csv(output_paths["targets"], (item.to_dict() for item in targets), list(TaskTarget.__dataclass_fields__))
    _write_json(output_paths["coverage"], coverage)
    _write_csv(output_paths["anomalies"], (item.to_dict() for item in anomalies), list(SupervisionAnomaly.__dataclass_fields__))
    _write_json(
        output_paths["split_audit"],
        {
            "schema_version": "p05-m2r-split-audit-v1",
            "sample_count": len(samples),
            "group_count": len(groups_by_fold),
            "group_conflict_count": len(split_group_conflicts),
            "group_conflicts": split_group_conflicts,
        },
    )
    _write_json(output_paths["summary"], summary)
    _write_json(output_paths["historical_audit"], historical_audit)
    output_paths["report"].write_text(_report(summary, coverage), encoding="utf-8")

    manifest = {
        "schema_version": "p05-m2r-supervision-manifest-v1",
        "run_id": config.run_id,
        "m0_run_id": m0_manifest.get("run_id"),
        "m0_manifest_path": str((m0_root / "p05_m0_manifest.json").resolve()),
        "m0_manifest_sha256": sha256_file(m0_root / "p05_m0_manifest.json"),
        "poc_data_root": str(poc_data_root),
        "approved_exclusions": sorted(
            ({"family": family, "business_id": business_id} for family, business_id in approved_exclusions),
            key=lambda item: (item["family"], item["business_id"]),
        ),
        "historical_output_roots": [str(_canonical(root)) for root in config.historical_output_roots],
        "allow_user_confirmed_strategy_replay": config.allow_user_confirmed_strategy_replay,
        "strict_hashes": config.strict_hashes,
        "silent_fix": False,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
        },
        "performance": {
            "duration_seconds": duration,
            "current_rss_bytes": summary["current_rss_bytes"],
        },
        "outputs": {
            role: {"path": str(path.resolve()), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
            for role, path in output_paths.items()
        },
    }
    manifest_path = run_root / "p05_m2r_supervision_manifest.json"
    _write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = [
    "M2RSupervisionConfig",
    "SupervisionAnomaly",
    "TASK_TARGET_KINDS",
    "TaskTarget",
    "build_m2r_supervision",
    "derive_task_targets",
]
