from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path, sort_patch_key
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import CaseSpec


REQUIRED_CASE_FILES = (
    "manifest.json",
    "size_report.json",
    "drivezone.gpkg",
    "nodes.gpkg",
    "roads.gpkg",
    "rcsdroad.gpkg",
    "rcsdnode.gpkg",
)

DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS = (
    "922217",
    "54265667",
    "502058682",
)


def _stable_case_sort_key(value: str) -> tuple[int, int | str]:
    return sort_patch_key(value)


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _validate_manifest(case_root: Path, manifest: dict[str, Any], size_report: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    manifest_file_list = {str(item) for item in manifest.get("file_list") or []}
    actual_files = {path.name for path in case_root.iterdir() if path.is_file()}
    required_files = set(REQUIRED_CASE_FILES)
    missing_required = sorted(required_files - actual_files)
    if missing_required:
        issues.append(f"missing_required_files={','.join(missing_required)}")
    missing_from_manifest = sorted(required_files - manifest_file_list)
    if missing_from_manifest:
        issues.append(f"manifest_missing_files={','.join(missing_from_manifest)}")
    if int(manifest.get("bundle_version") or 0) != 1:
        issues.append(f"bundle_version={manifest.get('bundle_version')!r}")
    if int(manifest.get("epsg") or 0) != 3857:
        issues.append(f"manifest_epsg={manifest.get('epsg')!r}")
    decoded_output = manifest.get("decoded_output") or {}
    if str(decoded_output.get("vector_crs") or "") != "EPSG:3857":
        issues.append(f"decoded_vector_crs={decoded_output.get('vector_crs')!r}")
    if bool(size_report.get("within_limit")) is not True:
        issues.append(f"within_limit={size_report.get('within_limit')!r}")
    return issues


def load_case_specs(
    *,
    case_root: str | Path,
    case_ids: list[str] | None = None,
    max_cases: int | None = None,
    exclude_case_ids: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[CaseSpec], dict[str, Any]]:
    resolved_case_root = normalize_runtime_path(case_root)
    if not resolved_case_root.is_dir():
        raise ValueError(f"case root does not exist: {resolved_case_root}")

    selected_case_ids = {str(case_id) for case_id in case_ids or []}
    explicit_case_selection = bool(selected_case_ids)
    default_excluded_case_ids = {str(case_id) for case_id in exclude_case_ids or []}
    raw_case_dirs = [
        path
        for path in resolved_case_root.iterdir()
        if path.is_dir() and path.name not in {"out", "renders"}
    ]
    sorted_case_dirs = sorted(raw_case_dirs, key=lambda path: _stable_case_sort_key(path.name))
    raw_case_ids = [path.name for path in sorted_case_dirs]
    default_formal_case_ids = [
        case_id
        for case_id in raw_case_ids
        if case_id not in default_excluded_case_ids
    ]

    specs: list[CaseSpec] = []
    preflight_rows: list[dict[str, Any]] = []
    applied_excluded_case_ids: list[str] = []
    for case_dir in sorted_case_dirs:
        case_id = str(case_dir.name)
        if selected_case_ids and case_id not in selected_case_ids:
            continue
        if not explicit_case_selection and case_id in default_excluded_case_ids:
            applied_excluded_case_ids.append(case_id)
            continue
        manifest = _read_json(case_dir / "manifest.json")
        size_report = _read_json(case_dir / "size_report.json")
        issues = _validate_manifest(case_dir, manifest, size_report)
        row = {
            "case_id": case_id,
            "case_root": str(case_dir),
            "issues": issues,
        }
        preflight_rows.append(row)
        if issues:
            raise ValueError(f"invalid case-package for case_id={case_id}: {issues}")
        specs.append(
            CaseSpec(
                case_id=case_id,
                mainnodeid=str(manifest.get("mainnodeid") or case_id),
                case_root=case_dir,
                manifest=manifest,
                size_report=size_report,
                input_paths={
                    "manifest_path": case_dir / "manifest.json",
                    "size_report_path": case_dir / "size_report.json",
                    "drivezone_path": case_dir / "drivezone.gpkg",
                    "nodes_path": case_dir / "nodes.gpkg",
                    "roads_path": case_dir / "roads.gpkg",
                    "rcsdroad_path": case_dir / "rcsdroad.gpkg",
                    "rcsdnode_path": case_dir / "rcsdnode.gpkg",
                },
            )
        )
        if max_cases is not None and len(specs) >= max_cases:
            break

    preflight_doc = {
        "case_root": str(resolved_case_root),
        "raw_case_count": len(raw_case_ids),
        "raw_case_ids": raw_case_ids,
        "explicit_case_selection": explicit_case_selection,
        "default_full_batch_excluded_case_ids": sorted(
            default_excluded_case_ids,
            key=_stable_case_sort_key,
        ),
        "default_formal_case_count": len(default_formal_case_ids),
        "default_formal_case_ids": default_formal_case_ids,
        "formal_full_batch_case_count": len(default_formal_case_ids),
        "formal_full_batch_case_ids": default_formal_case_ids,
        "applied_excluded_case_ids": sorted(
            applied_excluded_case_ids,
            key=_stable_case_sort_key,
        ),
        "excluded_case_ids": sorted(
            applied_excluded_case_ids,
            key=_stable_case_sort_key,
        ),
        "applied_excluded_case_count": len(applied_excluded_case_ids),
        "effective_case_count": len(specs),
        "effective_case_ids": [spec.case_id for spec in specs],
        "selected_case_count": len(specs),
        "selected_case_ids": [spec.case_id for spec in specs],
        "missing_case_ids": [],
        "failed_case_ids": [],
        "rows": preflight_rows,
    }
    return specs, preflight_doc
