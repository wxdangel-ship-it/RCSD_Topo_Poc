from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import EXTERNAL_INPUT_REQUIREMENTS, HANDOFF_REQUIREMENTS, T10_MODULE_ID, T10_T08_POLICY, T10_VERSION
from .spatial_slice import build_case_spatial_input_slices


T10_MATERIALIZATION_MANIFEST_ONLY = "manifest_only"
T10_MATERIALIZATION_COPY_FULL = "copy_full"
T10_MATERIALIZATION_SPATIAL_SLICE = "spatial_slice"


@dataclass(frozen=True)
class T10CaseEvidencePackageArtifacts:
    package_dir: Path
    manifest_json: Path
    summary_json: Path


@dataclass(frozen=True)
class T10MultiCaseEvidencePackageArtifacts:
    package_dir: Path
    manifest_json: Path
    summary_json: Path
    case_manifest_paths: tuple[Path, ...]


def build_case_evidence_package(
    *,
    manifest: Mapping[str, Any],
    out_root: str | Path,
    semantic_junction_id: str,
    radius_m: float,
    package_id: str | None = None,
    include_files: bool = False,
    materialization_mode: str | None = None,
    target_epsg: int = 3857,
) -> T10CaseEvidencePackageArtifacts:
    if not str(semantic_junction_id).strip():
        raise ValueError("semantic_junction_id must be non-empty.")
    if radius_m <= 0:
        raise ValueError("radius_m must be > 0.")

    effective_package_id = package_id or _default_package_id(semantic_junction_id)
    package_dir = Path(out_root).expanduser().resolve() / effective_package_id
    package_dir.mkdir(parents=True, exist_ok=True)

    external_inputs = _mapping(manifest.get("external_inputs"))
    handoffs = _mapping(manifest.get("handoffs"))
    mode = _resolve_materialization_mode(include_files=include_files, materialization_mode=materialization_mode)
    spatial_slice_summary = None
    if mode == T10_MATERIALIZATION_SPATIAL_SLICE:
        slice_result = build_case_spatial_input_slices(
            manifest=manifest,
            package_dir=package_dir,
            semantic_junction_id=str(semantic_junction_id),
            radius_m=radius_m,
            target_epsg=target_epsg,
        )
        included_inputs = slice_result.included_inputs
        spatial_slice_summary = slice_result.summary
    else:
        included_inputs = [
            _external_input_entry(
                package_dir=package_dir,
                slot=requirement.slot,
                source_path_text=external_inputs.get(requirement.slot),
                include_files=mode == T10_MATERIALIZATION_COPY_FULL,
                hash_source=mode == T10_MATERIALIZATION_COPY_FULL,
            )
            for requirement in EXTERNAL_INPUT_REQUIREMENTS
        ]
    missing_external = [entry["slot"] for entry in included_inputs if not entry["source_path"]]
    materialized_count = sum(1 for entry in included_inputs if entry.get("package_path"))
    scope_payload = {
        "swsd_semantic_junction_id": str(semantic_junction_id),
        "radius_m": radius_m,
        "selection_crs": f"EPSG:{target_epsg}",
        "selection_status": "spatial_slice_completed" if spatial_slice_summary else "manifest_scope_declared",
    }
    if spatial_slice_summary is not None:
        scope_payload.update(
            {
                "case_id": str(semantic_junction_id),
                "case_id_semantics": "swsd_semantic_junction_id",
                "center": spatial_slice_summary["center"],
                "bounds": spatial_slice_summary["bounds"],
                "member_node_ids": spatial_slice_summary["member_node_ids"],
            }
        )

    payload = {
        "module_id": T10_MODULE_ID,
        "version": T10_VERSION,
        "package_id": effective_package_id,
        "produced_at_utc": _now_text(),
        "scope": scope_payload,
        "materialization_mode": mode,
        "t08_policy": T10_T08_POLICY,
        "included_external_inputs": included_inputs,
        "excluded_intermediate_handoffs": [
            {"slot": requirement.slot, "configured_path": handoffs.get(requirement.slot)}
            for requirement in HANDOFF_REQUIREMENTS
            if requirement.slot in handoffs
        ],
        "qa": {
            "crs_and_transform": (
                spatial_slice_summary["qa"]["crs_and_transform"]
                if spatial_slice_summary
                else f"Case scope is declared in EPSG:{target_epsg}; no vector materialization was requested."
            ),
            "topology_consistency": "No topology repair or silent fix is performed while building the package.",
            "geometry_semantics": "The package is keyed by SWSD semantic junction id and radius.",
            "audit_traceability": "All included files are named by external input slot and source path.",
            "performance_verifiability": "Manifest records input counts and optional materialized file count.",
        },
        "spatial_slice_summary": spatial_slice_summary,
    }
    summary = {
        "module_id": T10_MODULE_ID,
        "package_id": effective_package_id,
        "swsd_semantic_junction_id": str(semantic_junction_id),
        "radius_m": radius_m,
        "materialization_mode": mode,
        "selection_status": scope_payload["selection_status"],
        "external_input_slot_count": len(EXTERNAL_INPUT_REQUIREMENTS),
        "missing_external_input_slots": missing_external,
        "materialized_file_count": materialized_count,
        "intermediate_handoff_slot_count_excluded": len(payload["excluded_intermediate_handoffs"]),
        "passed": not missing_external,
    }

    artifacts = T10CaseEvidencePackageArtifacts(
        package_dir=package_dir,
        manifest_json=package_dir / "t10_case_evidence_manifest.json",
        summary_json=package_dir / "t10_case_evidence_summary.json",
    )
    _write_json(artifacts.manifest_json, payload)
    _write_json(artifacts.summary_json, summary)
    return artifacts


def build_multi_case_evidence_package(
    *,
    manifest: Mapping[str, Any],
    out_root: str | Path,
    semantic_junction_ids: list[str] | tuple[str, ...],
    radius_m: float,
    package_id: str | None = None,
    include_files: bool = False,
    materialization_mode: str | None = None,
    target_epsg: int = 3857,
) -> T10MultiCaseEvidencePackageArtifacts:
    case_ids = [str(case_id).strip() for case_id in semantic_junction_ids if str(case_id).strip()]
    if not case_ids:
        raise ValueError("semantic_junction_ids must contain at least one non-empty case id.")
    if radius_m <= 0:
        raise ValueError("radius_m must be > 0.")

    effective_package_id = package_id or _default_multi_package_id(case_ids)
    package_dir = Path(out_root).expanduser().resolve() / effective_package_id
    cases_dir = package_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    mode = _resolve_materialization_mode(include_files=include_files, materialization_mode=materialization_mode)
    case_manifest_paths: list[Path] = []
    case_summaries: list[dict[str, Any]] = []
    for case_id in case_ids:
        case_dir = cases_dir / _safe_case_id(case_id)
        case_dir.mkdir(parents=True, exist_ok=True)
        case_payload, case_summary = _case_payload_and_summary(
            manifest=manifest,
            package_dir=case_dir,
            semantic_junction_id=case_id,
            radius_m=radius_m,
            package_id=effective_package_id,
            materialization_mode=mode,
            target_epsg=target_epsg,
        )
        case_manifest = case_dir / "t10_case_evidence_manifest.json"
        case_summary_path = case_dir / "t10_case_evidence_summary.json"
        _write_json(case_manifest, case_payload)
        _write_json(case_summary_path, case_summary)
        case_manifest_paths.append(case_manifest)
        case_summaries.append(
            {
                "case_id": case_id,
                "case_dir": str(case_dir.relative_to(package_dir)),
                "passed": case_summary["passed"],
                "selection_status": case_summary["selection_status"],
                "missing_external_input_slots": case_summary["missing_external_input_slots"],
                "materialized_file_count": case_summary["materialized_file_count"],
            }
        )

    payload = {
        "module_id": T10_MODULE_ID,
        "version": T10_VERSION,
        "package_id": effective_package_id,
        "produced_at_utc": _now_text(),
        "case_id_semantics": "SWSD semantic junction id; coordinates are derived scope metadata, not identifiers.",
        "case_count": len(case_summaries),
        "radius_m": radius_m,
        "selection_crs": f"EPSG:{target_epsg}",
        "materialization_mode": mode,
        "t08_policy": T10_T08_POLICY,
        "cases": case_summaries,
        "payload_policy": (
            "Each case directory contains external inputs only; spatial_slice mode materializes local vector slices."
        ),
    }
    summary = {
        "module_id": T10_MODULE_ID,
        "package_id": effective_package_id,
        "case_count": len(case_summaries),
        "radius_m": radius_m,
        "materialization_mode": mode,
        "passed": all(item["passed"] for item in case_summaries),
        "failed_case_count": sum(1 for item in case_summaries if not item["passed"]),
        "materialized_file_count": sum(int(item["materialized_file_count"]) for item in case_summaries),
    }
    artifacts = T10MultiCaseEvidencePackageArtifacts(
        package_dir=package_dir,
        manifest_json=package_dir / "t10_multi_case_evidence_manifest.json",
        summary_json=package_dir / "t10_multi_case_evidence_summary.json",
        case_manifest_paths=tuple(case_manifest_paths),
    )
    _write_json(artifacts.manifest_json, payload)
    _write_json(artifacts.summary_json, summary)
    return artifacts


def _case_payload_and_summary(
    *,
    manifest: Mapping[str, Any],
    package_dir: Path,
    semantic_junction_id: str,
    radius_m: float,
    package_id: str,
    materialization_mode: str,
    target_epsg: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    external_inputs = _mapping(manifest.get("external_inputs"))
    handoffs = _mapping(manifest.get("handoffs"))
    spatial_slice_summary = None
    if materialization_mode == T10_MATERIALIZATION_SPATIAL_SLICE:
        slice_result = build_case_spatial_input_slices(
            manifest=manifest,
            package_dir=package_dir,
            semantic_junction_id=str(semantic_junction_id),
            radius_m=radius_m,
            target_epsg=target_epsg,
        )
        included_inputs = slice_result.included_inputs
        spatial_slice_summary = slice_result.summary
    else:
        included_inputs = [
            _external_input_entry(
                package_dir=package_dir,
                slot=requirement.slot,
                source_path_text=external_inputs.get(requirement.slot),
                include_files=materialization_mode == T10_MATERIALIZATION_COPY_FULL,
                hash_source=materialization_mode == T10_MATERIALIZATION_COPY_FULL,
            )
            for requirement in EXTERNAL_INPUT_REQUIREMENTS
        ]
    missing_external = [entry["slot"] for entry in included_inputs if not entry["source_path"]]
    materialized_count = sum(1 for entry in included_inputs if entry.get("package_path"))
    scope_payload = {
        "case_id": str(semantic_junction_id),
        "case_id_semantics": "swsd_semantic_junction_id",
        "swsd_semantic_junction_id": str(semantic_junction_id),
        "radius_m": radius_m,
        "selection_crs": f"EPSG:{target_epsg}",
        "selection_status": "spatial_slice_completed" if spatial_slice_summary else "manifest_scope_declared",
    }
    if spatial_slice_summary is not None:
        scope_payload.update(
            {
                "center": spatial_slice_summary["center"],
                "bounds": spatial_slice_summary["bounds"],
                "member_node_ids": spatial_slice_summary["member_node_ids"],
            }
        )
    payload = {
        "module_id": T10_MODULE_ID,
        "version": T10_VERSION,
        "package_id": package_id,
        "produced_at_utc": _now_text(),
        "scope": scope_payload,
        "materialization_mode": materialization_mode,
        "t08_policy": T10_T08_POLICY,
        "included_external_inputs": included_inputs,
        "excluded_intermediate_handoffs": [
            {"slot": requirement.slot, "configured_path": handoffs.get(requirement.slot)}
            for requirement in HANDOFF_REQUIREMENTS
            if requirement.slot in handoffs
        ],
        "qa": {
            "crs_and_transform": (
                spatial_slice_summary["qa"]["crs_and_transform"]
                if spatial_slice_summary
                else f"Case scope is declared in EPSG:{target_epsg}; no vector materialization was requested."
            ),
            "topology_consistency": "No topology repair or silent fix is performed while building the package.",
            "geometry_semantics": "The package is keyed by SWSD semantic junction id and radius.",
            "audit_traceability": "All included files are named by external input slot and source path.",
            "performance_verifiability": "Manifest records input counts and optional materialized file count.",
        },
        "spatial_slice_summary": spatial_slice_summary,
    }
    summary = {
        "module_id": T10_MODULE_ID,
        "package_id": package_id,
        "case_id": str(semantic_junction_id),
        "swsd_semantic_junction_id": str(semantic_junction_id),
        "radius_m": radius_m,
        "materialization_mode": materialization_mode,
        "selection_status": scope_payload["selection_status"],
        "external_input_slot_count": len(EXTERNAL_INPUT_REQUIREMENTS),
        "missing_external_input_slots": missing_external,
        "materialized_file_count": materialized_count,
        "intermediate_handoff_slot_count_excluded": len(payload["excluded_intermediate_handoffs"]),
        "passed": not missing_external,
    }
    return payload, summary


def _external_input_entry(
    *,
    package_dir: Path,
    slot: str,
    source_path_text: Any,
    include_files: bool,
    hash_source: bool,
) -> dict[str, Any]:
    source_path = str(source_path_text) if isinstance(source_path_text, str) and source_path_text.strip() else ""
    entry: dict[str, Any] = {
        "slot": slot,
        "source_path": source_path,
        "source_exists": False,
        "source_sha256": "",
        "package_path": "",
        "materialization_mode": T10_MATERIALIZATION_COPY_FULL if include_files else T10_MATERIALIZATION_MANIFEST_ONLY,
    }
    if not source_path:
        return entry

    source = Path(source_path).expanduser()
    entry["source_exists"] = source.is_file()
    if source.is_file():
        stat = source.stat()
        entry["source_size_bytes"] = stat.st_size
        entry["source_mtime_ns"] = stat.st_mtime_ns
        if hash_source:
            entry["source_sha256"] = _sha256_file(source)
        if include_files:
            target = package_dir / "external_inputs" / slot / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            entry["package_path"] = target.relative_to(package_dir).as_posix()
    return entry


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _resolve_materialization_mode(*, include_files: bool, materialization_mode: str | None) -> str:
    if materialization_mode is None:
        return T10_MATERIALIZATION_SPATIAL_SLICE if include_files else T10_MATERIALIZATION_MANIFEST_ONLY
    mode = str(materialization_mode).strip().lower()
    allowed = {
        T10_MATERIALIZATION_MANIFEST_ONLY,
        T10_MATERIALIZATION_COPY_FULL,
        T10_MATERIALIZATION_SPATIAL_SLICE,
    }
    if mode not in allowed:
        raise ValueError(f"unsupported T10 materialization_mode: {materialization_mode!r}")
    if mode != T10_MATERIALIZATION_MANIFEST_ONLY and not include_files:
        raise ValueError("include_files must be true when materialization_mode writes files.")
    return mode


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_package_id(semantic_junction_id: str) -> str:
    return "t10_case_" + _safe_case_id(semantic_junction_id) + "_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _default_multi_package_id(case_ids: list[str]) -> str:
    first = _safe_case_id(case_ids[0])
    return "t10_cases_" + first + "_and_" + str(max(0, len(case_ids) - 1)) + "_more_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe_case_id(case_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(case_id))


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
