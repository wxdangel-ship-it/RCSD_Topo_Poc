from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from rcsd_topo_poc.modules.t08_preprocess.vector_io import read_vector

from .contracts import EXTERNAL_INPUT_REQUIREMENTS, HANDOFF_REQUIREMENTS, T10_MODULE_ID, T10_T08_POLICY, T10_VERSION
from .evidence_package import (
    T10_MATERIALIZATION_MANIFEST_ONLY,
    T10_MATERIALIZATION_SPATIAL_SLICE,
)
from .spatial_slice import build_segment_spatial_input_slices


SEGMENT_EVIDENCE_ARTIFACT_NAMES = {
    "t06_rcsd_segment_replaceable": (
        "t06_rcsd_segment_replaceable.csv",
        "t06_rcsd_segment_replaceable.gpkg",
        "t06_rcsd_segment_replaceable.json",
    ),
    "t06_segment_replacement_plan": (
        "t06_segment_replacement_plan.csv",
        "t06_segment_replacement_plan.gpkg",
        "t06_segment_replacement_plan.json",
    ),
    "t06_segment_replacement_problem_registry": (
        "t06_segment_replacement_problem_registry.csv",
        "t06_segment_replacement_problem_registry.gpkg",
        "t06_segment_replacement_problem_registry.json",
    ),
    "t06_step3_swsd_frcsd_segment_relation": (
        "t06_step3_swsd_frcsd_segment_relation.csv",
        "t06_step3_swsd_frcsd_segment_relation.gpkg",
        "t06_step3_swsd_frcsd_segment_relation.json",
    ),
}

SEGMENT_ID_FIELDS = (
    "swsd_segment_id",
    "segment_id",
    "SegmentID",
    "segmentid",
    "id",
)

SEGMENT_ID_LIST_FIELDS = (
    "group_segment_ids",
    "covered_segment_ids",
    "replacement_plan_segment_ids",
)


@dataclass(frozen=True)
class T10SegmentEvidencePackageArtifacts:
    package_dir: Path
    manifest_json: Path
    summary_json: Path


@dataclass(frozen=True)
class T10MultiSegmentEvidencePackageArtifacts:
    package_dir: Path
    manifest_json: Path
    summary_json: Path
    case_manifest_paths: tuple[Path, ...]


def build_segment_evidence_package(
    *,
    manifest: Mapping[str, Any],
    out_root: str | Path,
    swsd_segment_id: str,
    t10_run_root: str | Path,
    package_id: str | None = None,
    t01_segment_path: str | Path | None = None,
    include_files: bool = True,
    materialization_mode: str | None = None,
    target_epsg: int = 3857,
) -> T10SegmentEvidencePackageArtifacts:
    segment_id = _required_segment_id(swsd_segment_id)
    effective_package_id = package_id or _default_segment_package_id(segment_id)
    package_dir = Path(out_root).expanduser().resolve() / effective_package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    payload, summary = _segment_payload_and_summary(
        manifest=manifest,
        package_dir=package_dir,
        swsd_segment_id=segment_id,
        t10_run_root=t10_run_root,
        package_id=effective_package_id,
        t01_segment_path=t01_segment_path,
        include_files=include_files,
        materialization_mode=materialization_mode,
        target_epsg=target_epsg,
    )
    artifacts = T10SegmentEvidencePackageArtifacts(
        package_dir=package_dir,
        manifest_json=package_dir / "t10_case_evidence_manifest.json",
        summary_json=package_dir / "t10_case_evidence_summary.json",
    )
    _write_json(artifacts.manifest_json, payload)
    _write_json(artifacts.summary_json, summary)
    return artifacts


def build_multi_segment_evidence_package(
    *,
    manifest: Mapping[str, Any],
    out_root: str | Path,
    swsd_segment_ids: Sequence[str],
    t10_run_root: str | Path,
    package_id: str | None = None,
    t01_segment_path: str | Path | None = None,
    include_files: bool = True,
    materialization_mode: str | None = None,
    target_epsg: int = 3857,
) -> T10MultiSegmentEvidencePackageArtifacts:
    segment_ids = [_required_segment_id(segment_id) for segment_id in swsd_segment_ids if str(segment_id).strip()]
    if not segment_ids:
        raise ValueError("swsd_segment_ids must contain at least one non-empty SegmentID.")

    effective_package_id = package_id or _default_multi_segment_package_id(segment_ids)
    package_dir = Path(out_root).expanduser().resolve() / effective_package_id
    cases_dir = package_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    case_manifest_paths: list[Path] = []
    case_summaries: list[dict[str, Any]] = []
    for segment_id in segment_ids:
        case_id = _segment_case_id(segment_id)
        case_dir = cases_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        payload, summary = _segment_payload_and_summary(
            manifest=manifest,
            package_dir=case_dir,
            swsd_segment_id=segment_id,
            t10_run_root=t10_run_root,
            package_id=effective_package_id,
            t01_segment_path=t01_segment_path,
            include_files=include_files,
            materialization_mode=materialization_mode,
            target_epsg=target_epsg,
        )
        case_manifest = case_dir / "t10_case_evidence_manifest.json"
        case_summary = case_dir / "t10_case_evidence_summary.json"
        _write_json(case_manifest, payload)
        _write_json(case_summary, summary)
        case_manifest_paths.append(case_manifest)
        case_summaries.append(
            {
                "case_id": case_id,
                "swsd_segment_id": segment_id,
                "case_dir": str(case_dir.relative_to(package_dir)),
                "passed": summary["passed"],
                "selection_status": summary["selection_status"],
                "missing_external_input_slots": summary["missing_external_input_slots"],
                "materialized_file_count": summary["materialized_file_count"],
                "matched_evidence_artifact_count": summary["matched_evidence_artifact_count"],
            }
        )

    payload = {
        "module_id": T10_MODULE_ID,
        "version": T10_VERSION,
        "package_type": "t10_segment_evidence",
        "package_id": effective_package_id,
        "produced_at_utc": _now_text(),
        "case_id_semantics": "Segment package case id; formal Segment identity is scope.swsd_segment_id.",
        "scope_type": "swsd_segment",
        "segment_count": len(case_summaries),
        "selection_crs": f"EPSG:{target_epsg}",
        "materialization_mode": _resolve_materialization_mode(
            include_files=include_files,
            materialization_mode=materialization_mode,
        ),
        "t10_run_root": str(Path(t10_run_root).expanduser().resolve()),
        "t08_policy": T10_T08_POLICY,
        "cases": case_summaries,
        "payload_policy": (
            "Each Segment directory contains external input slices only; T10/T06 intermediate artifacts are referenced as evidence."
        ),
    }
    summary = {
        "module_id": T10_MODULE_ID,
        "package_type": "t10_segment_evidence",
        "package_id": effective_package_id,
        "segment_count": len(case_summaries),
        "materialization_mode": payload["materialization_mode"],
        "passed": all(item["passed"] for item in case_summaries),
        "failed_segment_count": sum(1 for item in case_summaries if not item["passed"]),
        "materialized_file_count": sum(int(item["materialized_file_count"]) for item in case_summaries),
        "matched_evidence_artifact_count": sum(int(item["matched_evidence_artifact_count"]) for item in case_summaries),
    }
    artifacts = T10MultiSegmentEvidencePackageArtifacts(
        package_dir=package_dir,
        manifest_json=package_dir / "t10_multi_segment_evidence_manifest.json",
        summary_json=package_dir / "t10_multi_segment_evidence_summary.json",
        case_manifest_paths=tuple(case_manifest_paths),
    )
    _write_json(artifacts.manifest_json, payload)
    _write_json(artifacts.summary_json, summary)
    return artifacts


def _segment_payload_and_summary(
    *,
    manifest: Mapping[str, Any],
    package_dir: Path,
    swsd_segment_id: str,
    t10_run_root: str | Path,
    package_id: str,
    t01_segment_path: str | Path | None,
    include_files: bool,
    materialization_mode: str | None,
    target_epsg: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mode = _resolve_materialization_mode(include_files=include_files, materialization_mode=materialization_mode)
    evidence = _discover_segment_evidence(
        t10_run_root=Path(t10_run_root).expanduser().resolve(),
        swsd_segment_id=swsd_segment_id,
        t01_segment_path=t01_segment_path,
    )
    segment_source_path = evidence["t01_segment_path"]
    spatial_slice_summary = None
    if mode == T10_MATERIALIZATION_SPATIAL_SLICE:
        slice_result = build_segment_spatial_input_slices(
            manifest=manifest,
            package_dir=package_dir,
            swsd_segment_path=segment_source_path,
            swsd_segment_id=swsd_segment_id,
            segment_evidence_rows=_matched_evidence_rows(evidence),
            target_epsg=target_epsg,
        )
        included_inputs = slice_result.included_inputs
        spatial_slice_summary = slice_result.summary
    else:
        included_inputs = [
            _external_input_entry(slot=requirement.slot, source_path_text=_mapping(manifest.get("external_inputs")).get(requirement.slot))
            for requirement in EXTERNAL_INPUT_REQUIREMENTS
        ]

    missing_external = [entry["slot"] for entry in included_inputs if not entry["source_path"]]
    materialized_count = sum(1 for entry in included_inputs if entry.get("package_path"))
    case_id = _segment_case_id(swsd_segment_id)
    scope_payload = {
        "case_id": case_id,
        "case_id_semantics": "swsd_segment_package_case_id",
        "scope_type": "swsd_segment",
        "swsd_segment_id": swsd_segment_id,
        "selection_crs": f"EPSG:{target_epsg}",
        "selection_status": "spatial_slice_completed" if spatial_slice_summary else "manifest_scope_declared",
    }
    if spatial_slice_summary is not None:
        scope_payload.update(
            {
                "center": spatial_slice_summary["center"],
                "bounds": spatial_slice_summary["bounds"],
                "segment_bounds": spatial_slice_summary["segment_bounds"],
                "segment_endpoint_node_ids": spatial_slice_summary["segment_endpoint_node_ids"],
                "segment_properties": spatial_slice_summary["segment_properties"],
            }
        )

    payload = {
        "module_id": T10_MODULE_ID,
        "version": T10_VERSION,
        "package_type": "t10_segment_evidence",
        "package_id": package_id,
        "produced_at_utc": _now_text(),
        "scope": scope_payload,
        "materialization_mode": mode,
        "t08_policy": T10_T08_POLICY,
        "segment_evidence": evidence,
        "included_external_inputs": included_inputs,
        "excluded_intermediate_handoffs": [
            {"slot": requirement.slot, "configured_path": _mapping(manifest.get("handoffs")).get(requirement.slot)}
            for requirement in HANDOFF_REQUIREMENTS
            if requirement.slot in _mapping(manifest.get("handoffs"))
        ],
        "qa": {
            "crs_and_transform": (
                spatial_slice_summary["qa"]["crs_and_transform"]
                if spatial_slice_summary
                else f"Segment scope is declared in EPSG:{target_epsg}; no vector materialization was requested."
            ),
            "topology_consistency": "No topology repair or silent fix is performed while building the Segment package.",
            "geometry_semantics": "The package is keyed by SWSD Segment id and selects local inputs from T01 Segment geometry plus matched T10/T06 evidence dependencies; no radius parameter is used.",
            "audit_traceability": "The manifest records T10 run root, T01 Segment source, T06 evidence paths, external source paths and checksums.",
            "performance_verifiability": "Manifest records input counts and optional materialized file count.",
        },
        "spatial_slice_summary": spatial_slice_summary,
    }
    matched_artifact_count = sum(1 for item in evidence["artifacts"] if item["matched_row_count"])
    summary = {
        "module_id": T10_MODULE_ID,
        "package_type": "t10_segment_evidence",
        "package_id": package_id,
        "case_id": case_id,
        "swsd_segment_id": swsd_segment_id,
        "materialization_mode": mode,
        "selection_status": scope_payload["selection_status"],
        "external_input_slot_count": len(EXTERNAL_INPUT_REQUIREMENTS),
        "missing_external_input_slots": missing_external,
        "materialized_file_count": materialized_count,
        "matched_evidence_artifact_count": matched_artifact_count,
        "t01_segment_path": evidence["t01_segment_path"],
        "t10_run_root": evidence["t10_run_root"],
        "passed": not missing_external and bool(evidence["t01_segment_path"]),
    }
    return payload, summary


def _discover_segment_evidence(
    *,
    t10_run_root: Path,
    swsd_segment_id: str,
    t01_segment_path: str | Path | None,
) -> dict[str, Any]:
    if not t10_run_root.is_dir():
        raise FileNotFoundError(f"T10 run root is not a directory: {t10_run_root}")
    t01_segment = Path(t01_segment_path).expanduser().resolve() if t01_segment_path else _discover_t01_segment_path(t10_run_root)
    if t01_segment is None or not t01_segment.is_file():
        raise FileNotFoundError(f"T01 segment.gpkg could not be discovered for T10 run root: {t10_run_root}")

    visual_rows = _read_visual_check_rows(t10_run_root)
    artifact_paths = _artifact_paths_from_visual_rows(visual_rows)
    _merge_artifact_paths(artifact_paths, _artifact_paths_from_case_manifest(t10_run_root))
    _merge_artifact_paths(artifact_paths, _artifact_paths_from_conventional_t06_dirs(t10_run_root))

    artifacts: list[dict[str, Any]] = []
    for role, paths in sorted(artifact_paths.items()):
        for path in sorted(paths):
            row_payload = _matching_rows(path, swsd_segment_id)
            artifacts.append(
                {
                    "role": role,
                    "path": str(path),
                    "exists": path.is_file(),
                    "matched_row_count": len(row_payload),
                    "matched_rows": row_payload[:20],
                }
            )

    return {
        "t10_run_root": str(t10_run_root),
        "t01_segment_path": str(t01_segment),
        "visual_check_row_count": len(visual_rows),
        "artifacts": artifacts,
    }


def _matched_evidence_rows(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in evidence.get("artifacts", []):
        if not isinstance(artifact, Mapping):
            continue
        matched_rows = artifact.get("matched_rows")
        if isinstance(matched_rows, list):
            rows.extend(dict(row) for row in matched_rows if isinstance(row, Mapping))
    return rows


def _discover_t01_segment_path(t10_run_root: Path) -> Path | None:
    visual_rows = _read_visual_check_rows(t10_run_root)
    for row in visual_rows:
        value = str(row.get("t01_segment_gpkg") or "").strip()
        if value and Path(value).expanduser().is_file():
            return Path(value).expanduser().resolve()

    manifest_paths = [
        t10_run_root / "t10_innernet_full_pipeline_manifest.json",
        t10_run_root / "t10_e2e_run_manifest.json",
    ]
    for manifest_path in manifest_paths:
        value = _path_from_manifest(manifest_path, ("outputs", "t01_segment"))
        if value and Path(value).expanduser().is_file():
            return Path(value).expanduser().resolve()
    for candidate in t10_run_root.rglob("segment.gpkg"):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _path_from_manifest(manifest_path: Path, keys: tuple[str, ...]) -> str:
    if not manifest_path.is_file():
        return ""
    payload = _read_json(manifest_path)
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return ""
        current = current.get(key)
    return str(current or "")


def _read_visual_check_rows(t10_run_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    json_path = t10_run_root / "t10_t06_visual_check_summary.json"
    csv_path = t10_run_root / "t10_t06_visual_check_summary.csv"
    if json_path.is_file():
        payload = _read_json(json_path)
        raw_rows = payload.get("rows") if isinstance(payload, Mapping) else payload
        if isinstance(raw_rows, list):
            rows.extend(dict(row) for row in raw_rows if isinstance(row, Mapping))
    if csv_path.is_file():
        rows.extend(_read_csv_rows(csv_path))
    return rows


def _artifact_paths_from_visual_rows(rows: list[dict[str, Any]]) -> dict[str, set[Path]]:
    mapping = {
        "t06_rcsd_segment_replaceable": "t06_rcsd_segment_replaceable_gpkg",
        "t06_segment_replacement_plan": "t06_segment_replacement_plan_gpkg",
        "t06_segment_replacement_problem_registry": "t06_segment_replacement_problem_registry_gpkg",
        "t06_step3_swsd_frcsd_segment_relation": "t06_segment_relation_gpkg",
    }
    paths: dict[str, set[Path]] = {role: set() for role in mapping}
    for row in rows:
        for role, field in mapping.items():
            value = str(row.get(field) or "").strip()
            if value:
                paths[role].add(Path(value).expanduser().resolve())
    return {role: role_paths for role, role_paths in paths.items() if role_paths}


def _artifact_paths_from_case_manifest(t10_run_root: Path) -> dict[str, set[Path]]:
    manifest_path = t10_run_root / "t10_e2e_case_run_manifest.json"
    if not manifest_path.is_file():
        return {}
    manifest = _read_json(manifest_path)
    handoffs = _mapping(manifest.get("handoffs"))
    mapping = {
        "t06_rcsd_segment_replaceable": ("t06_step2_replaceable",),
        "t06_step3_swsd_frcsd_segment_relation": ("t06_swsd_frcsd_segment_relation",),
    }
    paths: dict[str, set[Path]] = {}
    for role, keys in mapping.items():
        role_paths = {
            Path(handoffs[key]).expanduser().resolve()
            for key in keys
            if isinstance(handoffs.get(key), str) and Path(handoffs[key]).expanduser().is_file()
        }
        if role_paths:
            paths[role] = role_paths
    return paths


def _artifact_paths_from_conventional_t06_dirs(t10_run_root: Path) -> dict[str, set[Path]]:
    roots = _candidate_t06_roots(t10_run_root)
    paths: dict[str, set[Path]] = {}
    for role, names in SEGMENT_EVIDENCE_ARTIFACT_NAMES.items():
        role_paths: set[Path] = set()
        for root in roots:
            for name in names:
                for child in (
                    root / "step2_extract_rcsd_segments" / name,
                    root / "step3_segment_replacement" / name,
                    root / name,
                ):
                    if child.is_file():
                        role_paths.add(child.resolve())
        if role_paths:
            paths[role] = role_paths
    return paths


def _candidate_t06_roots(t10_run_root: Path) -> list[Path]:
    roots = [t10_run_root, t10_run_root / "t06", t10_run_root / "t06_step12" / "t06"]
    manifest_path = t10_run_root / "t10_e2e_case_run_manifest.json"
    if manifest_path.is_file():
        handoffs = _mapping(_read_json(manifest_path).get("handoffs"))
        run_root = handoffs.get("t06_run_root")
        if isinstance(run_root, str) and run_root.strip():
            roots.append(Path(run_root).expanduser())
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = root.resolve()
        key = str(resolved)
        if key not in seen and resolved.exists():
            seen.add(key)
            unique.append(resolved)
    return unique


def _merge_artifact_paths(target: dict[str, set[Path]], source: dict[str, set[Path]]) -> None:
    for role, paths in source.items():
        target.setdefault(role, set()).update(paths)


def _matching_rows(path: Path, swsd_segment_id: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _read_csv_rows(path)
    elif suffix in {".json", ".geojson"}:
        rows = _rows_from_json(_read_json(path))
    elif suffix == ".gpkg":
        try:
            rows = [dict(feature.properties) for feature in read_vector(path, target_epsg=3857).features]
        except Exception:
            return []
    else:
        return []
    return [_json_safe_row(row) for row in rows if _row_matches_segment(row, swsd_segment_id)]


def _row_matches_segment(row: Mapping[str, Any], swsd_segment_id: str) -> bool:
    target = _normalize_id(swsd_segment_id)
    for field in SEGMENT_ID_FIELDS:
        if _normalize_id(_field(row, field)) == target:
            return True
    for field in SEGMENT_ID_LIST_FIELDS:
        if target in _parse_id_list(_field(row, field)):
            return True
    return False


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as fp:
        return [dict(row) for row in csv.DictReader(fp)]


def _rows_from_json(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "features"):
            value = payload.get(key)
            if isinstance(value, list):
                if key == "features":
                    return [
                        dict(feature.get("properties") or {})
                        for feature in value
                        if isinstance(feature, Mapping)
                    ]
                return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _external_input_entry(*, slot: str, source_path_text: Any) -> dict[str, Any]:
    source_path = str(source_path_text) if isinstance(source_path_text, str) and source_path_text.strip() else ""
    entry: dict[str, Any] = {
        "slot": slot,
        "source_path": source_path,
        "source_exists": False,
        "source_sha256": "",
        "package_path": "",
        "materialization_mode": T10_MATERIALIZATION_MANIFEST_ONLY,
    }
    if not source_path:
        return entry
    source = Path(source_path).expanduser()
    entry["source_exists"] = source.is_file()
    if source.is_file():
        stat = source.stat()
        entry["source_size_bytes"] = stat.st_size
        entry["source_mtime_ns"] = stat.st_mtime_ns
        entry["source_sha256"] = _sha256_file(source)
    return entry


def _resolve_materialization_mode(*, include_files: bool, materialization_mode: str | None) -> str:
    if materialization_mode is None:
        return T10_MATERIALIZATION_SPATIAL_SLICE if include_files else T10_MATERIALIZATION_MANIFEST_ONLY
    mode = str(materialization_mode).strip().lower()
    allowed = {T10_MATERIALIZATION_MANIFEST_ONLY, T10_MATERIALIZATION_SPATIAL_SLICE}
    if mode not in allowed:
        raise ValueError(f"unsupported Segment materialization_mode: {materialization_mode!r}")
    if mode != T10_MATERIALIZATION_MANIFEST_ONLY and not include_files:
        raise ValueError("include_files must be true when materialization_mode writes files.")
    return mode


def _required_segment_id(value: str) -> str:
    segment_id = str(value).strip()
    if not segment_id:
        raise ValueError("swsd_segment_id must be non-empty.")
    return segment_id


def _segment_case_id(segment_id: str) -> str:
    return "segment_" + _safe_id(segment_id)


def _default_segment_package_id(segment_id: str) -> str:
    return "t10_segment_" + _safe_id(segment_id) + "_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _default_multi_segment_package_id(segment_ids: Sequence[str]) -> str:
    first = _safe_id(segment_ids[0])
    return "t10_segments_" + first + "_and_" + str(max(0, len(segment_ids) - 1)) + "_more_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _field(row: Mapping[str, Any], field_name: str) -> Any:
    for key, value in row.items():
        if str(key).lower() == field_name.lower():
            return value
    return None


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None


def _parse_id_list(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {item for item in (_normalize_id(part) for part in value) if item}
    cleaned = str(value).strip().strip("[](){}")
    if not cleaned:
        return set()
    values: set[str] = set()
    for part in cleaned.replace(";", ",").replace("|", ",").split(","):
        normalized = _normalize_id(part.strip().strip("'\""))
        if normalized:
            values.add(normalized)
    return values


def _json_safe_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
