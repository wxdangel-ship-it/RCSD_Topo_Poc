from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from rcsd_topo_poc.modules.t08_preprocess.output_naming import ensure_tool_output_name


DEFAULT_EXPERIMENT_PATCH_IDS = (
    "5524185996921171",
    "5724833136255764",
    "5524185996921755",
    "5724833136255765",
    "5724833136255763",
    "5524185996921337",
)
FRCSD_FILE_NAMES = (
    "RCSDNode.geojson",
    "RCSDRoad.geojson",
    "RCSDRoadNextRoad.geojson",
)
ROLE_SOURCE_RELATIVE_PATHS = {
    "SWSD": Path("SD_City") / "target_level1",
    "RCSD": Path("SD_City") / "base_origin",
    "FRCSD": Path("rc_sw_gd_merge"),
}
_COPY_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class T08PatchDataOrganizationArtifacts:
    output_root: Path
    experiment_output_root: Path
    summary_json: Path


class T08PatchDataOrganizationError(ValueError):
    def __init__(self, message: str, *, summary_json: Path | None = None) -> None:
        super().__init__(message)
        self.summary_json = summary_json


@dataclass(frozen=True)
class _FilePlan:
    patch_id: str
    role: str
    source_path: Path
    relative_path: Path
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class _PatchPlan:
    patch_id: str
    source_patch_dir: Path
    role_roots: dict[str, Path]
    directories: dict[str, tuple[Path, ...]]
    files: tuple[_FilePlan, ...]
    ignored_frcsd_entries: tuple[str, ...]
    is_experiment: bool


@dataclass
class _PublishState:
    staged_path: Path
    final_path: Path
    backup_path: Path
    had_existing: bool


def run_t08_patch_data_organization(
    *,
    source_root: str | Path,
    output_root: str | Path,
    experiment_output_root: str | Path,
    experiment_patch_ids: Sequence[str] | None = None,
    summary_output: str | Path | None = None,
    overwrite: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    progress_interval_files: int = 100,
) -> T08PatchDataOrganizationArtifacts:
    """Organize every Patch into SWSD/RCSD/FRCSD trees and publish an experiment subset."""

    started = time.perf_counter()
    generated_at = datetime.now(timezone.utc)
    run_token = uuid.uuid4().hex
    source_path = Path(source_root).expanduser().resolve()
    output_path = Path(output_root).expanduser().resolve()
    experiment_output_path = Path(experiment_output_root).expanduser().resolve()
    requested_summary_path = _resolve_summary_path(
        summary_output,
        output_root=output_path,
        generated_at=generated_at,
        run_token=run_token,
    )
    requested_summary_existed = requested_summary_path.exists()
    interval = int(progress_interval_files)
    normalized_experiment_ids: tuple[str, ...] = ()
    summary = _summary_skeleton(
        generated_at=generated_at,
        run_token=run_token,
        source_root=source_path,
        output_root=output_path,
        experiment_output_root=experiment_output_path,
        summary_path=requested_summary_path,
        overwrite=overwrite,
    )
    stage_paths: list[Path] = []
    publish_states: list[_PublishState] = []
    scan_elapsed = 0.0
    copy_elapsed = 0.0
    publish_elapsed = 0.0

    try:
        if interval <= 0:
            raise ValueError(f"progress_interval_files must be > 0: {progress_interval_files}")
        normalized_experiment_ids = _normalize_experiment_patch_ids(experiment_patch_ids)
        summary["parameters"]["experiment_patch_ids"] = list(normalized_experiment_ids)

        preflight_issues = _validate_root_boundaries(
            source_path,
            output_path,
            experiment_output_path,
            requested_summary_path,
        )
        summary["root_audit"]["paths_pairwise_non_overlapping"] = not any(
            _paths_overlap(left, right)
            for index, left in enumerate((source_path, output_path, experiment_output_path))
            for right in (source_path, output_path, experiment_output_path)[index + 1 :]
        )
        scan_started = time.perf_counter()
        plans, patch_rows, ignored_root_entries, scan_issues = _discover_patch_plans(
            source_path,
            experiment_patch_ids=normalized_experiment_ids,
        )
        scan_elapsed = time.perf_counter() - scan_started
        preflight_issues.extend(scan_issues)
        preflight_issues.extend(
            _output_conflicts(
                output_path,
                experiment_output_path,
                requested_summary_path,
                overwrite=overwrite,
            )
        )
        for patch_row in patch_rows:
            patch_id = str(patch_row["patch_id"])
            patch_row["main_output_patch_dir"] = str(output_path / patch_id)
            patch_row["experiment_output_patch_dir"] = (
                str(experiment_output_path / patch_id)
                if patch_row.get("is_experiment")
                else None
            )
        summary["root_audit"]["ignored_entries"] = ignored_root_entries
        summary["patches"] = patch_rows
        summary["preflight_issues"] = preflight_issues
        summary["performance"]["scan_elapsed_seconds"] = scan_elapsed

        if preflight_issues:
            issue_text = "\n".join(f"- {issue}" for issue in preflight_issues)
            raise ValueError(f"Tool11 preflight failed:\n{issue_text}")

        _emit(
            progress_callback,
            f"Tool11 discovered {len(plans)} Patch(es), "
            f"experiment_patch_count={len(normalized_experiment_ids)}.",
        )
        main_stage = _owned_sibling_path(output_path, run_token=run_token, kind="tmp")
        experiment_stage = _owned_sibling_path(
            experiment_output_path,
            run_token=run_token,
            kind="tmp",
        )
        stage_paths.extend((main_stage, experiment_stage))
        _prepare_empty_stage(main_stage, run_token=run_token)
        _prepare_empty_stage(experiment_stage, run_token=run_token)

        copy_started = time.perf_counter()
        file_audit, copy_counts = _copy_plans(
            plans,
            main_stage=main_stage,
            experiment_stage=experiment_stage,
            output_root=output_path,
            experiment_output_root=experiment_output_path,
            progress_callback=progress_callback,
            progress_interval_files=interval,
            patch_rows=patch_rows,
        )
        _apply_directory_metadata(
            plans,
            main_stage=main_stage,
            experiment_stage=experiment_stage,
        )
        copy_elapsed = time.perf_counter() - copy_started

        summary["file_audit"] = file_audit
        summary["counts"] = copy_counts
        summary["integrity_audit"] = _build_integrity_audit(
            plans,
            file_audit=file_audit,
            copy_counts=copy_counts,
            experiment_patch_ids=normalized_experiment_ids,
            main_stage=main_stage,
            experiment_stage=experiment_stage,
        )
        if not summary["integrity_audit"]["passed"]:
            raise ValueError(
                "Tool11 integrity validation failed: "
                + "; ".join(summary["integrity_audit"]["errors"])
            )
        summary["performance"].update(
            _copy_performance(copy_elapsed=copy_elapsed, copy_counts=copy_counts)
        )

        publish_started = time.perf_counter()
        publish_states.append(
            _publish_staged_path(
                main_stage,
                output_path,
                run_token=run_token,
                overwrite=overwrite,
            )
        )
        publish_states.append(
            _publish_staged_path(
                experiment_stage,
                experiment_output_path,
                run_token=run_token,
                overwrite=overwrite,
            )
        )
        publish_elapsed = time.perf_counter() - publish_started
        summary["status"] = "passed"
        summary["publication"] = {
            "main_output_published": True,
            "experiment_output_published": True,
            "summary_published": True,
            "rollback_applied": False,
        }
        summary["performance"].update(
            {
                "publish_elapsed_seconds": publish_elapsed,
                "elapsed_seconds": time.perf_counter() - started,
            }
        )

        summary_temp = _owned_sibling_path(
            requested_summary_path,
            run_token=run_token,
            kind="tmp",
        )
        stage_paths.append(summary_temp)
        _write_json_file(summary_temp, summary)
        publish_states.append(
            _publish_staged_path(
                summary_temp,
                requested_summary_path,
                run_token=run_token,
                overwrite=overwrite,
            )
        )
        cleanup_warnings = _finish_publication(publish_states)
        publish_states.clear()
        for warning in cleanup_warnings:
            _emit(progress_callback, f"Tool11 cleanup warning: {warning}")
        _emit(
            progress_callback,
            f"Tool11 completed: patches={copy_counts['patch_count']}, "
            f"files={copy_counts['main_output_file_count']}, "
            f"experiment_patches={copy_counts['experiment_patch_count']}.",
        )
        return T08PatchDataOrganizationArtifacts(
            output_root=output_path,
            experiment_output_root=experiment_output_path,
            summary_json=requested_summary_path,
        )
    except Exception as exc:
        rollback_error: Exception | None = None
        if publish_states:
            try:
                _rollback_publication(publish_states)
            except Exception as rollback_exc:  # pragma: no cover - filesystem fault path
                rollback_error = rollback_exc
        for stage_path in stage_paths:
            _cleanup_owned_path(stage_path, run_token=run_token)

        for patch_row in summary.get("patches", []):
            if patch_row.get("status") in {"preflight_passed", "copied"}:
                patch_row["status"] = "not_published"
        summary["status"] = "failed"
        summary["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "rollback_error": str(rollback_error) if rollback_error else None,
        }
        summary["publication"] = {
            "main_output_published": False,
            "experiment_output_published": False,
            "summary_published": True,
            "rollback_applied": bool(publish_states),
        }
        summary["performance"].update(
            {
                "scan_elapsed_seconds": scan_elapsed,
                "copy_elapsed_seconds": copy_elapsed,
                "publish_elapsed_seconds": publish_elapsed,
                "elapsed_seconds": time.perf_counter() - started,
            }
        )
        failure_summary_path = _failure_summary_path(
            requested_summary_path,
            requested_summary_existed=requested_summary_existed,
            source_root=source_path,
            output_root=output_path,
            experiment_output_root=experiment_output_path,
            run_token=run_token,
        )
        summary["outputs"]["summary_json"] = str(failure_summary_path)
        try:
            _write_json_atomic(failure_summary_path, summary, run_token=run_token)
        except Exception as summary_exc:  # pragma: no cover - filesystem fault path
            raise T08PatchDataOrganizationError(
                f"{exc}; failure summary write failed: {summary_exc}",
                summary_json=None,
            ) from exc
        raise T08PatchDataOrganizationError(
            str(exc),
            summary_json=failure_summary_path,
        ) from exc


def _summary_skeleton(
    *,
    generated_at: datetime,
    run_token: str,
    source_root: Path,
    output_root: Path,
    experiment_output_root: Path,
    summary_path: Path,
    overwrite: bool,
) -> dict[str, Any]:
    return {
        "tool": "T08 Tool11 patch data organization",
        "generated_at_utc": generated_at.isoformat(),
        "run_token": run_token,
        "status": "running",
        "error": None,
        "inputs": {
            "source_root": str(source_root),
            "patch_glob": "<source-root>/<numeric PatchID>",
            "role_sources": {
                role: relative.as_posix()
                for role, relative in ROLE_SOURCE_RELATIVE_PATHS.items()
            },
            "frcsd_file_names": list(FRCSD_FILE_NAMES),
        },
        "outputs": {
            "output_root": str(output_root),
            "experiment_output_root": str(experiment_output_root),
            "summary_json": str(summary_path),
        },
        "parameters": {
            "experiment_patch_ids": [],
            "overwrite": bool(overwrite),
            "copy_chunk_size_bytes": _COPY_CHUNK_SIZE,
            "symlink_policy": "reject",
            "special_file_policy": "reject",
        },
        "root_audit": {
            "paths_pairwise_non_overlapping": False,
            "ignored_entries": [],
        },
        "preflight_issues": [],
        "patches": [],
        "file_audit": [],
        "counts": {},
        "integrity_audit": {
            "passed": False,
            "errors": [],
        },
        "gis_audit": {
            "crs": "copied_without_transformation",
            "topology": "no_topology_operation",
            "geometry_semantics": "byte_preserving_copy_verified_by_sha256",
            "silent_fix_applied": False,
        },
        "publication": {
            "main_output_published": False,
            "experiment_output_published": False,
            "summary_published": False,
            "rollback_applied": False,
        },
        "performance": {
            "scan_elapsed_seconds": 0.0,
            "copy_elapsed_seconds": 0.0,
            "publish_elapsed_seconds": 0.0,
            "elapsed_seconds": 0.0,
        },
        "environment": {
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "os_name": os.name,
        },
    }


def _normalize_experiment_patch_ids(patch_ids: Sequence[str] | None) -> tuple[str, ...]:
    values = DEFAULT_EXPERIMENT_PATCH_IDS if patch_ids is None else tuple(str(value).strip() for value in patch_ids)
    if not values:
        raise ValueError("experiment_patch_ids must contain at least one PatchID")
    invalid = [value for value in values if not value or not value.isdigit()]
    if invalid:
        raise ValueError(f"experiment_patch_ids must be numeric: {invalid}")
    if len(set(values)) != len(values):
        duplicates = sorted({value for value in values if values.count(value) > 1})
        raise ValueError(f"experiment_patch_ids contains duplicates: {duplicates}")
    return tuple(values)


def _resolve_summary_path(
    summary_output: str | Path | None,
    *,
    output_root: Path,
    generated_at: datetime,
    run_token: str,
) -> Path:
    if summary_output is not None:
        return ensure_tool_output_name(summary_output, tool_number=11, label="summary output")
    timestamp = generated_at.strftime("%Y%m%dT%H%M%S%fZ")
    return (
        output_root.parent
        / f"{output_root.name}_patch_data_organization_{timestamp}_{run_token[:8]}_tool11.json"
    ).resolve()


def _validate_root_boundaries(
    source_root: Path,
    output_root: Path,
    experiment_output_root: Path,
    summary_path: Path,
) -> list[str]:
    issues: list[str] = []
    if not source_root.is_dir():
        issues.append(f"source root does not exist or is not a directory: {source_root}")
    roots = (
        ("source_root", source_root),
        ("output_root", output_root),
        ("experiment_output_root", experiment_output_root),
    )
    for index, (left_label, left_path) in enumerate(roots):
        for right_label, right_path in roots[index + 1 :]:
            if _paths_overlap(left_path, right_path):
                issues.append(
                    f"directory roots must not overlap: {left_label}={left_path}, "
                    f"{right_label}={right_path}"
                )
    for label, root in roots:
        if _is_within(summary_path, root):
            issues.append(f"summary output must be outside {label}: {summary_path}")
    return issues


def _output_conflicts(
    output_root: Path,
    experiment_output_root: Path,
    summary_path: Path,
    *,
    overwrite: bool,
) -> list[str]:
    issues: list[str] = []
    for label, path in (
        ("output root", output_root),
        ("experiment output root", experiment_output_root),
    ):
        if path.exists() and not path.is_dir():
            issues.append(f"{label} exists and is not a directory: {path}")
        elif path.exists() and not overwrite:
            issues.append(f"{label} already exists; use --overwrite to replace it: {path}")
    if summary_path.exists() and not summary_path.is_file():
        issues.append(f"summary output exists and is not a file: {summary_path}")
    elif summary_path.exists() and not overwrite:
        issues.append(f"summary output already exists; use --overwrite to replace it: {summary_path}")
    return issues


def _discover_patch_plans(
    source_root: Path,
    *,
    experiment_patch_ids: Sequence[str],
) -> tuple[list[_PatchPlan], list[dict[str, Any]], list[str], list[str]]:
    if not source_root.is_dir():
        return [], [], [], []
    try:
        root_entries = sorted(source_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        return [], [], [], [f"cannot list source root {source_root}: {exc}"]

    patch_entries: list[Path] = []
    ignored_root_entries: list[str] = []
    issues: list[str] = []
    for entry in root_entries:
        if entry.name.isdigit():
            if entry.is_symlink():
                issues.append(f"Patch directory must not be a symlink: {entry}")
            elif entry.is_dir():
                patch_entries.append(entry)
            else:
                issues.append(f"numeric Patch entry is not a directory: {entry}")
        else:
            ignored_root_entries.append(entry.name + ("/" if entry.is_dir() else ""))
    if not patch_entries:
        issues.append(f"no numeric Patch directories found under source root: {source_root}")

    discovered_ids = {entry.name for entry in patch_entries}
    missing_experiment_ids = sorted(set(experiment_patch_ids) - discovered_ids)
    if missing_experiment_ids:
        issues.append(f"experiment PatchIDs not found in source root: {missing_experiment_ids}")

    plans: list[_PatchPlan] = []
    patch_rows: list[dict[str, Any]] = []
    experiment_id_set = set(experiment_patch_ids)
    for patch_dir in patch_entries:
        plan, patch_row, patch_issues = _build_patch_plan(
            patch_dir,
            is_experiment=patch_dir.name in experiment_id_set,
        )
        patch_rows.append(patch_row)
        issues.extend(patch_issues)
        if plan is not None:
            plans.append(plan)
    return plans, patch_rows, ignored_root_entries, issues


def _build_patch_plan(
    patch_dir: Path,
    *,
    is_experiment: bool,
) -> tuple[_PatchPlan | None, dict[str, Any], list[str]]:
    patch_id = patch_dir.name
    role_roots = {
        role: patch_dir / relative
        for role, relative in ROLE_SOURCE_RELATIVE_PATHS.items()
    }
    errors: list[str] = []
    directories: dict[str, tuple[Path, ...]] = {}
    files: list[_FilePlan] = []
    ignored_frcsd_entries: tuple[str, ...] = ()

    for role in ("SWSD", "RCSD", "FRCSD"):
        role_root = role_roots[role]
        if role_root.is_symlink():
            errors.append(f"Patch {patch_id} {role} source must not be a symlink: {role_root}")
        elif not role_root.is_dir():
            errors.append(f"Patch {patch_id} missing {role} source directory: {role_root}")

    for role in ("SWSD", "RCSD"):
        if role_roots[role].is_dir() and not role_roots[role].is_symlink():
            role_directories, role_files, role_errors = _scan_recursive_role(
                patch_id,
                role,
                role_roots[role],
            )
            directories[role] = role_directories
            files.extend(role_files)
            errors.extend(role_errors)
    if role_roots["FRCSD"].is_dir() and not role_roots["FRCSD"].is_symlink():
        frcsd_files, ignored_frcsd_entries, frcsd_errors = _scan_frcsd_role(
            patch_id,
            role_roots["FRCSD"],
        )
        directories["FRCSD"] = (Path("."),)
        files.extend(frcsd_files)
        errors.extend(frcsd_errors)

    files.sort(key=lambda item: (item.role, item.relative_path.as_posix()))
    patch_row = {
        "patch_id": patch_id,
        "status": "invalid" if errors else "preflight_passed",
        "is_experiment": is_experiment,
        "source_patch_dir": str(patch_dir.resolve()),
        "source_role_roots": {role: str(path) for role, path in role_roots.items()},
        "output_roles": ["SWSD", "RCSD", "FRCSD"],
        "directories": {
            role: [path.as_posix() for path in role_directories]
            for role, role_directories in directories.items()
        },
        "ignored_frcsd_entries": list(ignored_frcsd_entries),
        "errors": errors,
        "counts": {
            "source_file_count": len(files),
            "source_bytes": sum(item.size_bytes for item in files),
        },
    }
    if errors:
        return None, patch_row, errors
    return (
        _PatchPlan(
            patch_id=patch_id,
            source_patch_dir=patch_dir.resolve(),
            role_roots=role_roots,
            directories=directories,
            files=tuple(files),
            ignored_frcsd_entries=ignored_frcsd_entries,
            is_experiment=is_experiment,
        ),
        patch_row,
        [],
    )


def _scan_recursive_role(
    patch_id: str,
    role: str,
    role_root: Path,
) -> tuple[tuple[Path, ...], list[_FilePlan], list[str]]:
    directories: list[Path] = [Path(".")]
    files: list[_FilePlan] = []
    errors: list[str] = []
    try:
        entries = sorted(role_root.rglob("*"), key=lambda path: path.relative_to(role_root).as_posix())
    except OSError as exc:
        return (), [], [f"Patch {patch_id} cannot scan {role} source {role_root}: {exc}"]
    for entry in entries:
        relative_path = entry.relative_to(role_root)
        if entry.is_symlink():
            errors.append(f"Patch {patch_id} {role} contains symlink: {entry}")
        elif entry.is_dir():
            directories.append(relative_path)
        elif entry.is_file():
            try:
                stat = entry.stat()
            except OSError as exc:
                errors.append(f"Patch {patch_id} cannot stat {role} file {entry}: {exc}")
                continue
            files.append(
                _FilePlan(
                    patch_id=patch_id,
                    role=role,
                    source_path=entry.resolve(),
                    relative_path=relative_path,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                )
            )
        else:
            errors.append(f"Patch {patch_id} {role} contains special file: {entry}")
    return tuple(directories), files, errors


def _scan_frcsd_role(
    patch_id: str,
    role_root: Path,
) -> tuple[list[_FilePlan], tuple[str, ...], list[str]]:
    files: list[_FilePlan] = []
    ignored_entries: list[str] = []
    errors: list[str] = []
    required_paths = {name: role_root / name for name in FRCSD_FILE_NAMES}
    for name, source_path in required_paths.items():
        if source_path.is_symlink():
            errors.append(f"Patch {patch_id} FRCSD file must not be a symlink: {source_path}")
        elif not source_path.is_file():
            errors.append(f"Patch {patch_id} missing FRCSD file: {source_path}")
        else:
            try:
                stat = source_path.stat()
            except OSError as exc:
                errors.append(f"Patch {patch_id} cannot stat FRCSD file {source_path}: {exc}")
                continue
            files.append(
                _FilePlan(
                    patch_id=patch_id,
                    role="FRCSD",
                    source_path=source_path.resolve(),
                    relative_path=Path(name),
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                )
            )
    try:
        entries = sorted(role_root.rglob("*"), key=lambda path: path.relative_to(role_root).as_posix())
    except OSError as exc:
        errors.append(f"Patch {patch_id} cannot scan FRCSD source {role_root}: {exc}")
        entries = []
    required_names = set(FRCSD_FILE_NAMES)
    for entry in entries:
        relative = entry.relative_to(role_root)
        if relative.parent == Path(".") and relative.name in required_names:
            continue
        if entry.is_symlink():
            errors.append(f"Patch {patch_id} FRCSD contains symlink: {entry}")
        elif not entry.is_dir() and not entry.is_file():
            errors.append(f"Patch {patch_id} FRCSD contains special file: {entry}")
        else:
            ignored_entries.append(relative.as_posix() + ("/" if entry.is_dir() else ""))
    return files, tuple(ignored_entries), errors


def _copy_plans(
    plans: Sequence[_PatchPlan],
    *,
    main_stage: Path,
    experiment_stage: Path,
    output_root: Path,
    experiment_output_root: Path,
    progress_callback: Callable[[str], None] | None,
    progress_interval_files: int,
    patch_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    patch_rows_by_id = {str(row["patch_id"]): row for row in patch_rows}
    file_audit: list[dict[str, Any]] = []
    processed_files = 0

    for plan in plans:
        for role, relative_directories in plan.directories.items():
            for relative_directory in relative_directories:
                main_directory = _role_target(main_stage, plan.patch_id, role, relative_directory)
                main_directory.mkdir(parents=True, exist_ok=True)
                if plan.is_experiment:
                    experiment_directory = _role_target(
                        experiment_stage,
                        plan.patch_id,
                        role,
                        relative_directory,
                    )
                    experiment_directory.mkdir(parents=True, exist_ok=True)

        for file_plan in plan.files:
            main_stage_path = (
                main_stage
                / plan.patch_id
                / file_plan.role
                / file_plan.relative_path
            )
            main_result = _copy_file_verified(
                file_plan.source_path,
                main_stage_path,
                expected_size=file_plan.size_bytes,
                expected_mtime_ns=file_plan.mtime_ns,
            )
            main_final_path = (
                output_root
                / plan.patch_id
                / file_plan.role
                / file_plan.relative_path
            )
            experiment_final_path: Path | None = None
            experiment_sha256: str | None = None
            experiment_verified: bool | None = None
            if plan.is_experiment:
                experiment_stage_path = (
                    experiment_stage
                    / plan.patch_id
                    / file_plan.role
                    / file_plan.relative_path
                )
                main_stat = main_stage_path.stat()
                experiment_result = _copy_file_verified(
                    main_stage_path,
                    experiment_stage_path,
                    expected_size=main_stat.st_size,
                    expected_mtime_ns=main_stat.st_mtime_ns,
                )
                experiment_final_path = (
                    experiment_output_root
                    / plan.patch_id
                    / file_plan.role
                    / file_plan.relative_path
                )
                experiment_sha256 = experiment_result["target_sha256"]
                experiment_verified = (
                    experiment_result["verified"]
                    and experiment_result["source_sha256"] == main_result["source_sha256"]
                )
            verified = bool(main_result["verified"]) and experiment_verified is not False
            file_audit.append(
                {
                    "patch_id": plan.patch_id,
                    "role": file_plan.role,
                    "relative_path": file_plan.relative_path.as_posix(),
                    "source_path": str(file_plan.source_path),
                    "main_output_path": str(main_final_path),
                    "experiment_output_path": (
                        str(experiment_final_path) if experiment_final_path else None
                    ),
                    "size_bytes": file_plan.size_bytes,
                    "source_sha256": main_result["source_sha256"],
                    "main_output_sha256": main_result["target_sha256"],
                    "experiment_output_sha256": experiment_sha256,
                    "source_stable_during_copy": main_result["source_stable_during_copy"],
                    "verified": verified,
                }
            )
            processed_files += 1
            if processed_files % progress_interval_files == 0:
                _emit(
                    progress_callback,
                    f"Tool11 copied and verified {processed_files} source file(s).",
                )
        patch_row = patch_rows_by_id[plan.patch_id]
        patch_row["status"] = "copied"
        patch_row["counts"].update(
            {
                "main_output_file_count": len(plan.files),
                "experiment_output_file_count": len(plan.files) if plan.is_experiment else 0,
                "directory_count": sum(len(rows) for rows in plan.directories.values()),
            }
        )
        _emit(
            progress_callback,
            f"Tool11 processed Patch {plan.patch_id}: files={len(plan.files)}, "
            f"experiment={plan.is_experiment}.",
        )

    for row in patch_rows:
        if row.get("status") == "copied":
            row["status"] = "passed"
    source_bytes = sum(item.size_bytes for plan in plans for item in plan.files)
    experiment_bytes = sum(
        item.size_bytes for plan in plans if plan.is_experiment for item in plan.files
    )
    return file_audit, {
        "patch_count": len(plans),
        "experiment_patch_count": sum(1 for plan in plans if plan.is_experiment),
        "source_file_count": len(file_audit),
        "source_bytes": source_bytes,
        "main_output_file_count": len(file_audit),
        "main_output_bytes": source_bytes,
        "experiment_output_file_count": sum(
            1 for row in file_audit if row["experiment_output_path"] is not None
        ),
        "experiment_output_bytes": experiment_bytes,
        "total_bytes_written": source_bytes + experiment_bytes,
        "main_directory_count": sum(
            len(rows) for plan in plans for rows in plan.directories.values()
        ),
        "experiment_directory_count": sum(
            len(rows)
            for plan in plans
            if plan.is_experiment
            for rows in plan.directories.values()
        ),
        "ignored_frcsd_entry_count": sum(
            len(plan.ignored_frcsd_entries) for plan in plans
        ),
        "swsd_file_count": sum(
            1 for plan in plans for item in plan.files if item.role == "SWSD"
        ),
        "rcsd_file_count": sum(
            1 for plan in plans for item in plan.files if item.role == "RCSD"
        ),
        "frcsd_file_count": sum(
            1 for plan in plans for item in plan.files if item.role == "FRCSD"
        ),
    }


def _copy_file_verified(
    source_path: Path,
    target_path: Path,
    *,
    expected_size: int,
    expected_mtime_ns: int,
) -> dict[str, Any]:
    before = source_path.stat()
    if before.st_size != expected_size or before.st_mtime_ns != expected_mtime_ns:
        raise ValueError(f"source file changed after preflight: {source_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_digest = hashlib.sha256()
    with source_path.open("rb") as source_handle, target_path.open("xb") as target_handle:
        while True:
            chunk = source_handle.read(_COPY_CHUNK_SIZE)
            if not chunk:
                break
            source_digest.update(chunk)
            target_handle.write(chunk)
        target_handle.flush()
        os.fsync(target_handle.fileno())
    after = source_path.stat()
    source_stable = (
        before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
    )
    if not source_stable:
        raise ValueError(f"source file changed during copy: {source_path}")
    source_sha256 = source_digest.hexdigest()
    target_sha256 = _sha256_file(target_path)
    if source_sha256 != target_sha256:
        raise ValueError(
            f"SHA-256 mismatch after copy: source={source_path}, target={target_path}"
        )
    shutil.copystat(source_path, target_path)
    return {
        "source_sha256": source_sha256,
        "target_sha256": target_sha256,
        "source_stable_during_copy": source_stable,
        "verified": True,
    }


def _apply_directory_metadata(
    plans: Sequence[_PatchPlan],
    *,
    main_stage: Path,
    experiment_stage: Path,
) -> None:
    for plan in plans:
        for role, relative_directories in plan.directories.items():
            ordered = sorted(
                relative_directories,
                key=lambda path: len(path.parts),
                reverse=True,
            )
            for relative_directory in ordered:
                source_directory = _role_target(
                    plan.role_roots[role],
                    "",
                    "",
                    relative_directory,
                )
                main_directory = _role_target(
                    main_stage,
                    plan.patch_id,
                    role,
                    relative_directory,
                )
                shutil.copystat(source_directory, main_directory)
                if plan.is_experiment:
                    experiment_directory = _role_target(
                        experiment_stage,
                        plan.patch_id,
                        role,
                        relative_directory,
                    )
                    shutil.copystat(main_directory, experiment_directory)


def _role_target(root: Path, patch_id: str, role: str, relative: Path) -> Path:
    target = root
    if patch_id:
        target = target / patch_id
    if role:
        target = target / role
    return target if relative == Path(".") else target / relative


def _build_integrity_audit(
    plans: Sequence[_PatchPlan],
    *,
    file_audit: Sequence[dict[str, Any]],
    copy_counts: dict[str, int],
    experiment_patch_ids: Sequence[str],
    main_stage: Path,
    experiment_stage: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    if not all(bool(row.get("verified")) for row in file_audit):
        errors.append("one or more file SHA-256 checks failed")
    if copy_counts["source_file_count"] != copy_counts["main_output_file_count"]:
        errors.append("source/main file count mismatch")
    if copy_counts["source_bytes"] != copy_counts["main_output_bytes"]:
        errors.append("source/main byte count mismatch")
    expected_experiment_file_count = sum(
        len(plan.files) for plan in plans if plan.is_experiment
    )
    if copy_counts["experiment_output_file_count"] != expected_experiment_file_count:
        errors.append("experiment file count mismatch")
    actual_experiment_ids = sorted(plan.patch_id for plan in plans if plan.is_experiment)
    if actual_experiment_ids != sorted(experiment_patch_ids):
        errors.append("experiment PatchID set mismatch")
    expected_main_files, expected_main_directories = _expected_tree_inventory(plans)
    expected_experiment_files, expected_experiment_directories = _expected_tree_inventory(
        [plan for plan in plans if plan.is_experiment]
    )
    actual_main_files, actual_main_directories = _tree_inventory(main_stage)
    actual_experiment_files, actual_experiment_directories = _tree_inventory(experiment_stage)
    main_files_exact = actual_main_files == expected_main_files
    main_directories_exact = actual_main_directories == expected_main_directories
    experiment_files_exact = actual_experiment_files == expected_experiment_files
    experiment_directories_exact = (
        actual_experiment_directories == expected_experiment_directories
    )
    if not main_files_exact:
        errors.append("main output staged file set mismatch")
    if not main_directories_exact:
        errors.append("main output staged directory set mismatch")
    if not experiment_files_exact:
        errors.append("experiment output staged file set mismatch")
    if not experiment_directories_exact:
        errors.append("experiment output staged directory set mismatch")
    source_patch_ids = sorted(plan.patch_id for plan in plans)
    main_patch_ids = sorted(
        path.name for path in main_stage.iterdir() if path.is_dir() and path.name.isdigit()
    )
    main_patch_ids_exact = main_patch_ids == source_patch_ids
    if not main_patch_ids_exact:
        errors.append("main output PatchID set mismatch")
    return {
        "passed": not errors,
        "errors": errors,
        "hash_algorithm": "SHA-256",
        "all_file_hashes_verified": not errors and bool(file_audit or not plans),
        "source_main_file_count_conserved": (
            copy_counts["source_file_count"] == copy_counts["main_output_file_count"]
        ),
        "source_main_byte_count_conserved": (
            copy_counts["source_bytes"] == copy_counts["main_output_bytes"]
        ),
        "main_patch_ids_exact": main_patch_ids_exact,
        "main_file_set_exact": main_files_exact,
        "main_directory_set_exact": main_directories_exact,
        "experiment_file_set_exact": experiment_files_exact,
        "experiment_directory_set_exact": experiment_directories_exact,
        "experiment_patch_ids_exact": actual_experiment_ids == sorted(experiment_patch_ids),
    }


def _expected_tree_inventory(
    plans: Iterable[_PatchPlan],
) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for plan in plans:
        directories.add(plan.patch_id)
        for role, relative_directories in plan.directories.items():
            role_prefix = Path(plan.patch_id) / role
            directories.add(role_prefix.as_posix())
            for relative_directory in relative_directories:
                if relative_directory != Path("."):
                    directories.add((role_prefix / relative_directory).as_posix())
        for item in plan.files:
            files.add(
                (Path(plan.patch_id) / item.role / item.relative_path).as_posix()
            )
    return files, directories


def _tree_inventory(root: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"staged output unexpectedly contains symlink: {path}")
        if path.is_dir():
            directories.add(relative)
        elif path.is_file():
            files.add(relative)
        else:
            raise ValueError(f"staged output unexpectedly contains special file: {path}")
    return files, directories


def _copy_performance(*, copy_elapsed: float, copy_counts: dict[str, int]) -> dict[str, float]:
    total_bytes = float(copy_counts["total_bytes_written"])
    bytes_per_second = total_bytes / copy_elapsed if copy_elapsed > 0 else 0.0
    return {
        "copy_elapsed_seconds": copy_elapsed,
        "bytes_per_second": bytes_per_second,
        "mib_per_second": bytes_per_second / (1024.0 * 1024.0),
        "source_files_per_second": (
            copy_counts["source_file_count"] / copy_elapsed if copy_elapsed > 0 else 0.0
        ),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_COPY_CHUNK_SIZE)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _prepare_empty_stage(path: Path, *, run_token: str) -> None:
    if path.exists():
        _cleanup_owned_path(path, run_token=run_token)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()


def _publish_staged_path(
    staged_path: Path,
    final_path: Path,
    *,
    run_token: str,
    overwrite: bool,
) -> _PublishState:
    if not staged_path.exists():
        raise ValueError(f"staged path does not exist: {staged_path}")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = _owned_sibling_path(final_path, run_token=run_token, kind="backup")
    if backup_path.exists():
        raise ValueError(f"Tool11 backup path already exists: {backup_path}")
    had_existing = final_path.exists()
    if had_existing and not overwrite:
        raise ValueError(f"output already exists: {final_path}")
    if had_existing:
        os.replace(final_path, backup_path)
    try:
        os.replace(staged_path, final_path)
    except Exception:
        if had_existing and backup_path.exists():
            os.replace(backup_path, final_path)
        raise
    return _PublishState(
        staged_path=staged_path,
        final_path=final_path,
        backup_path=backup_path,
        had_existing=had_existing,
    )


def _rollback_publication(states: Sequence[_PublishState]) -> None:
    errors: list[str] = []
    for state in reversed(states):
        try:
            if state.final_path.exists():
                _remove_path(state.final_path)
            if state.had_existing and state.backup_path.exists():
                os.replace(state.backup_path, state.final_path)
        except Exception as exc:  # pragma: no cover - filesystem fault path
            errors.append(f"{state.final_path}: {exc}")
    if errors:
        raise RuntimeError("Tool11 rollback failed: " + "; ".join(errors))


def _finish_publication(states: Sequence[_PublishState]) -> list[str]:
    warnings: list[str] = []
    for state in states:
        if state.backup_path.exists():
            try:
                _remove_path(state.backup_path)
            except Exception as exc:  # pragma: no cover - filesystem fault path
                warnings.append(f"cannot remove backup {state.backup_path}: {exc}")
    return warnings


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _cleanup_owned_path(path: Path, *, run_token: str) -> None:
    if not path.exists():
        return
    if run_token not in path.name or ".tool11." not in path.name:
        raise RuntimeError(f"refusing to clean non-Tool11 temporary path: {path}")
    _remove_path(path)


def _owned_sibling_path(final_path: Path, *, run_token: str, kind: str) -> Path:
    return final_path.with_name(f".{final_path.name}.tool11.{kind}.{run_token}")


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_atomic(path: Path, payload: dict[str, Any], *, run_token: str) -> None:
    temp_path = _owned_sibling_path(path, run_token=run_token, kind="tmp")
    if temp_path.exists():
        _cleanup_owned_path(temp_path, run_token=run_token)
    _write_json_file(temp_path, payload)
    try:
        os.replace(temp_path, path)
    finally:
        _cleanup_owned_path(temp_path, run_token=run_token)


def _failure_summary_path(
    preferred_path: Path,
    *,
    requested_summary_existed: bool,
    source_root: Path,
    output_root: Path,
    experiment_output_root: Path,
    run_token: str,
) -> Path:
    unsafe = any(
        _is_within(preferred_path, root)
        for root in (source_root, output_root, experiment_output_root)
    )
    if not requested_summary_existed and not preferred_path.exists() and not unsafe:
        return preferred_path
    candidate = output_root.parent / f"{output_root.name}_failure_{run_token[:12]}_tool11.json"
    if any(_is_within(candidate, root) for root in (source_root, output_root, experiment_output_root)):
        candidate = Path(tempfile.gettempdir()) / f"t08_tool11_failure_{run_token}_tool11.json"
    return candidate.resolve()


def _paths_overlap(left: Path, right: Path) -> bool:
    return _is_within(left, right) or _is_within(right, left)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _emit(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


__all__ = [
    "DEFAULT_EXPERIMENT_PATCH_IDS",
    "FRCSD_FILE_NAMES",
    "T08PatchDataOrganizationArtifacts",
    "T08PatchDataOrganizationError",
    "run_t08_patch_data_organization",
]
