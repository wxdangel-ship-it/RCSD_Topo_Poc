from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import geopandas as gpd
import pandas as pd

from .models import AuditConfig, EvidenceLayers, SCHEMA_VERSION, T12Artifacts


def write_outputs(
    *,
    run_root: Path,
    run_id: str,
    processing_crs: str,
    config: AuditConfig,
    candidates: list[dict[str, Any]],
    reviewed: list[dict[str, Any]],
    confirmed: list[dict[str, Any]],
    exclusions: list[dict[str, Any]],
    manual: list[dict[str, Any]],
    layers: EvidenceLayers,
    input_audit: Mapping[str, Any],
    topology_audit: Mapping[str, Any],
    evidence_audit: Mapping[str, Any],
    candidate_audit: Mapping[str, Any],
    runtime: dict[str, Any],
) -> T12Artifacts:
    output_started = time.perf_counter()
    run_root.mkdir(parents=True, exist_ok=True)
    paths = _output_paths(run_root)
    candidate_rows = [_flatten_candidate(row) for row in reviewed]
    confirmed_rows = [_flatten_candidate(row) for row in confirmed]
    exclusion_rows = [_flatten_candidate(row) for row in exclusions]
    manual_rows = [_flatten_candidate(row) for row in manual]
    _write_csv(paths["candidates_csv"], candidate_rows, _candidate_fields())
    _write_csv(paths["confirmed_csv"], confirmed_rows, _candidate_fields())
    _write_csv(paths["exclusions_csv"], exclusion_rows, _candidate_fields())
    _write_csv(paths["manual_csv"], manual_rows, _candidate_fields())
    _write_single_layer(
        paths["candidates_gpkg"],
        "t12_frcsd_quality_candidates",
        layers.candidate_segments,
        processing_crs,
        empty_columns=("candidate_id", "segment_id", "candidate_status"),
    )
    confirmed_by_id = {row["candidate_id"]: row for row in confirmed}
    confirmed_features = [
        {
            **feature,
            **_review_feature_fields(confirmed_by_id[feature["candidate_id"]]),
        }
        for feature in layers.candidate_segments
        if feature["candidate_id"] in confirmed_by_id
    ]
    _write_single_layer(
        paths["confirmed_gpkg"],
        "t12_frcsd_confirmed_quality_issues",
        confirmed_features,
        processing_crs,
        empty_columns=("candidate_id", "segment_id", "review_status", "issue_type"),
    )
    _write_evidence(paths["evidence_gpkg"], layers, processing_crs)
    stage_elapsed = runtime.get("stage_elapsed_seconds")
    if isinstance(stage_elapsed, dict):
        stage_elapsed["output_write"] = time.perf_counter() - output_started
        runtime["elapsed_seconds"] = float(sum(stage_elapsed.values()))
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "passed",
        "target": {
            "frcsd_roads_sha256": input_audit["frcsd_roads"]["sha256"],
            "frcsd_nodes_sha256": input_audit["frcsd_nodes"]["sha256"],
            "evidence_relation": evidence_audit["evidence_relation"],
            "t05_run_identity": evidence_audit.get("t05_anchor_audit"),
        },
        "counts": {
            **dict(candidate_audit.get("counts") or {}),
            "candidate_count": len(candidates),
            "confirmed_quality_issue_count": len(confirmed),
            "review_exclusion_count": len(exclusions),
            "manual_review_required_count": len(manual),
            "by_issue_type": _count_by(confirmed, "issue_type"),
            "by_review_status": _count_by(reviewed, "review_status"),
            "by_decision_source": _count_by(reviewed, "decision_source"),
            "by_decision_rule": _count_by(reviewed, "decision_rule"),
        },
        "crs": input_audit["crs"],
        "quality": {
            "invalid_geometry_count": input_audit["invalid_geometry_count"],
            **dict(topology_audit),
            "t07_truth_audit": candidate_audit.get("t07_truth_audit"),
            "t07_surface_audit": _compact_t07_surface_audit(
                candidate_audit.get("t07_surface_audit")
            ),
            "semantic_carrier_policy": candidate_audit.get(
                "semantic_carrier_policy"
            ),
        },
        "runtime": dict(runtime),
        "outputs": {name: str(path) for name, path in paths.items()},
        "silent_fix": False,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "passed",
        "inputs": dict(input_audit),
        "parameters": config.as_dict(),
        "t06_evidence": dict(evidence_audit),
        "candidate_audit": dict(candidate_audit),
        "counts": summary["counts"],
        "runtime": dict(runtime),
        "outputs": summary["outputs"],
        "silent_fix": False,
    }
    paths["summary_json"].write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["manifest_json"].write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["report_md"].write_text(
        _report(summary, confirmed_rows, exclusion_rows, manual_rows),
        encoding="utf-8",
    )
    return T12Artifacts(
        run_root=run_root,
        manifest_json=paths["manifest_json"],
        summary_json=paths["summary_json"],
        candidates_csv=paths["candidates_csv"],
        candidates_gpkg=paths["candidates_gpkg"],
        carrier_evidence_gpkg=paths["evidence_gpkg"],
        confirmed_csv=paths["confirmed_csv"],
        confirmed_gpkg=paths["confirmed_gpkg"],
        exclusions_csv=paths["exclusions_csv"],
        manual_review_csv=paths["manual_csv"],
        report_md=paths["report_md"],
        candidate_count=len(candidates),
        confirmed_count=len(confirmed),
        exclusion_count=len(exclusions),
        manual_review_count=len(manual),
    )


def write_failure_manifest(
    run_root: Path,
    *,
    run_id: str,
    status: str,
    error: BaseException,
    config: AuditConfig,
) -> Path:
    run_root.mkdir(parents=True, exist_ok=True)
    path = run_root / "t12_frcsd_quality_audit_manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "status": status,
                "error_type": type(error).__name__,
                "error": str(error),
                "parameters": config.as_dict(),
                "silent_fix": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _output_paths(root: Path) -> dict[str, Path]:
    return {
        "manifest_json": root / "t12_frcsd_quality_audit_manifest.json",
        "summary_json": root / "t12_frcsd_quality_audit_summary.json",
        "candidates_csv": root / "t12_frcsd_quality_candidates.csv",
        "candidates_gpkg": root / "t12_frcsd_quality_candidates.gpkg",
        "evidence_gpkg": root / "t12_frcsd_carrier_evidence.gpkg",
        "confirmed_csv": root / "t12_frcsd_confirmed_quality_issues.csv",
        "confirmed_gpkg": root / "t12_frcsd_confirmed_quality_issues.gpkg",
        "exclusions_csv": root / "t12_frcsd_quality_review_exclusions.csv",
        "manual_csv": root / "t12_frcsd_quality_manual_review_required.csv",
        "report_md": root / "t12_frcsd_quality_report.md",
    }


def _candidate_fields() -> tuple[str, ...]:
    return (
        "candidate_id",
        "segment_id",
        "candidate_status",
        "suggested_issue_type",
        "issue_type",
        "required_directions",
        "raw_failed_directions",
        "failed_directions",
        "anchor_modules",
        "base_nodes",
        "anchor_confidence",
        "t07_surface_statuses",
        "portal_equivalent",
        "automatic_equivalence_basis",
        "portal_constrained_semantic_status",
        "drivezone_in_road_ratio",
        "local_directed_status",
        "local_undirected_status",
        "full_directed_status",
        "raw_local_directed_status",
        "raw_local_undirected_status",
        "raw_full_directed_status",
        "semantic_local_directed_status",
        "semantic_local_undirected_status",
        "t06_reject_reason",
        "t06_root_cause",
        "decision_source",
        "decision_rule",
        "automatic_review_status",
        "automatic_issue_type",
        "automatic_decision_rule",
        "review_status",
        "review_reason",
        "review_source",
        "reviewed_at_utc",
    )


def _flatten_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    directions = list(row.get("directions") or [])
    local_directed = [
        f"{item['direction']}:{_path_status(item.get('local_directed') or {})}"
        for item in directions
    ]
    local_undirected = [
        f"{item['direction']}:{_path_status(item.get('local_undirected') or {})}"
        for item in directions
    ]
    full_directed = [
        f"{item['direction']}:{_path_status(item.get('full_directed') or {})}"
        for item in directions
    ]
    semantic_local_directed = [
        f"{item['direction']}:{_path_status(item.get('semantic_local_directed') or {})}"
        for item in directions
    ]
    semantic_local_undirected = [
        f"{item['direction']}:{_path_status(item.get('semantic_local_undirected') or {})}"
        for item in directions
    ]
    portal_constrained_semantic = [
        (
            f"{item['direction']}:"
            f"{_semantic_carrier_status(item.get('portal_constrained_semantic_directed') or {})}"
        )
        for item in directions
    ]
    t06 = row.get("t06_cross_evidence") or {}
    return {
        "candidate_id": row.get("candidate_id", ""),
        "segment_id": row.get("segment_id", ""),
        "candidate_status": row.get("candidate_status", ""),
        "suggested_issue_type": row.get("suggested_issue_type", ""),
        "issue_type": row.get("issue_type", ""),
        "required_directions": "|".join(row.get("required_directions") or []),
        "raw_failed_directions": "|".join(
            row.get("raw_failed_directions") or []
        ),
        "failed_directions": "|".join(row.get("failed_directions") or []),
        "anchor_modules": "|".join(row.get("anchor_modules") or []),
        "base_nodes": "|".join(row.get("base_nodes") or []),
        "anchor_confidence": row.get("anchor_confidence", ""),
        "t07_surface_statuses": "|".join(
            row.get("t07_surface_statuses") or []
        ),
        "portal_equivalent": bool(row.get("automatic_all_directions_equivalent")),
        "automatic_equivalence_basis": row.get(
            "automatic_equivalence_basis", ""
        ),
        "portal_constrained_semantic_status": "|".join(
            portal_constrained_semantic
        ),
        "drivezone_in_road_ratio": row.get("drivezone_in_road_ratio"),
        "local_directed_status": "|".join(local_directed),
        "local_undirected_status": "|".join(local_undirected),
        "full_directed_status": "|".join(full_directed),
        "raw_local_directed_status": "|".join(local_directed),
        "raw_local_undirected_status": "|".join(local_undirected),
        "raw_full_directed_status": "|".join(full_directed),
        "semantic_local_directed_status": "|".join(
            semantic_local_directed
        ),
        "semantic_local_undirected_status": "|".join(
            semantic_local_undirected
        ),
        "t06_reject_reason": t06.get("t06_reject_reason", ""),
        "t06_root_cause": t06.get("t06_root_cause_category", "")
        or t06.get("failure_root_cause_category", ""),
        "decision_source": row.get("decision_source", ""),
        "decision_rule": row.get("decision_rule", ""),
        "automatic_review_status": row.get("automatic_review_status", ""),
        "automatic_issue_type": row.get("automatic_issue_type", ""),
        "automatic_decision_rule": row.get("automatic_decision_rule", ""),
        "review_status": row.get("review_status", ""),
        "review_reason": row.get("review_reason", ""),
        "review_source": row.get("review_source", ""),
        "reviewed_at_utc": row.get("reviewed_at_utc", ""),
    }


def _path_status(value: Mapping[str, Any]) -> str:
    if value.get("accepted_equivalent_carrier"):
        return "equivalent"
    if value.get("exists"):
        return "non_equivalent_path"
    return "missing"


def _semantic_carrier_status(value: Mapping[str, Any]) -> str:
    if value.get("accepted_equivalent_carrier"):
        return "equivalent"
    reason = str(value.get("rejection_reason") or "")
    return reason or "not_evaluated"


def _review_feature_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "review_status": row.get("review_status", ""),
        "issue_type": row.get("issue_type", ""),
        "review_reason": row.get("review_reason", ""),
        "decision_source": row.get("decision_source", ""),
        "decision_rule": row.get("decision_rule", ""),
        "anchor_confidence": row.get("anchor_confidence", ""),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str]) -> None:
    fieldnames = list(fields)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _write_single_layer(
    path: Path,
    layer: str,
    rows: list[dict[str, Any]],
    crs: str,
    *,
    empty_columns: tuple[str, ...],
) -> None:
    if path.exists():
        path.unlink()
    frame = _spatial_frame(rows, crs, empty_columns)
    frame.to_file(path, layer=layer, driver="GPKG")


def _write_evidence(path: Path, layers: EvidenceLayers, crs: str) -> None:
    if path.exists():
        path.unlink()
    definitions = (
        (
            "candidate_segments",
            layers.candidate_segments,
            ("candidate_id", "segment_id", "candidate_status"),
        ),
        (
            "anchor_portals",
            layers.anchor_portals,
            ("candidate_id", "direction", "raw_id", "canonical_id"),
        ),
        (
            "swsd_required_carriers",
            layers.swsd_required_carriers,
            ("candidate_id", "direction", "road_id"),
        ),
        (
            "frcsd_carrier_paths",
            layers.frcsd_carrier_paths,
            ("candidate_id", "direction", "path_kind", "road_id"),
        ),
    )
    for index, (layer_name, rows, empty_columns) in enumerate(definitions):
        frame = _spatial_frame(rows, crs, empty_columns)
        frame.to_file(
            path,
            layer=layer_name,
            driver="GPKG",
            mode="w" if index == 0 else "a",
        )


def _spatial_frame(
    rows: list[dict[str, Any]],
    crs: str,
    empty_columns: tuple[str, ...],
) -> gpd.GeoDataFrame:
    if not rows:
        payload = {column: pd.Series(dtype="str") for column in empty_columns}
        payload["geometry"] = gpd.GeoSeries([], crs=crs)
        return gpd.GeoDataFrame(payload, geometry="geometry", crs=crs)
    normalized = []
    for row in rows:
        normalized.append(
            {
                key: (
                    json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(value, (list, tuple, dict, set))
                    else value
                )
                for key, value in row.items()
            }
        )
    return gpd.GeoDataFrame(normalized, geometry="geometry", crs=crs)


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    output: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "")
        output[key] = output.get(key, 0) + 1
    return dict(sorted(output.items()))


def _compact_t07_surface_audit(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    compact = dict(value)
    surface_ids = compact.pop("surface_ids", {})
    compact["surface_id_count"] = (
        len(surface_ids) if isinstance(surface_ids, Mapping) else 0
    )
    return compact


def _report(
    summary: Mapping[str, Any],
    confirmed: list[dict[str, Any]],
    exclusions: list[dict[str, Any]],
    manual: list[dict[str, Any]],
) -> str:
    counts = summary["counts"]
    lines = [
        "# T12 FRCSD 质量审计报告",
        "",
        f"- Run ID：`{summary['run_id']}`",
        f"- 自动候选：{counts['candidate_count']}",
        f"- 最终确认质量问题：{counts['confirmed_quality_issue_count']}",
        f"- 最终排除：{counts['review_exclusion_count']}",
        f"- 显式 QA 待定：{counts['manual_review_required_count']}",
        "- Silent fix：否",
        "",
        "最终问题清单只包含自动高置信或外部 QA 覆盖确认的 "
        "`confirmed_frcsd_quality_issue`，不使用高/中概率标签。",
        "",
        "## 已确认质量问题",
        "",
        "| Segment | 类型 | 决定来源 | 证据理由 |",
        "|---|---|---|---|",
    ]
    for row in confirmed:
        lines.append(
            f"| {row['segment_id']} | {row['issue_type']} | "
            f"{row['decision_source']} | "
            f"{str(row['review_reason']).replace('|', '/')} |"
        )
    if not confirmed:
        lines.append("| - | - | - | 当前无已确认问题 |")
    lines.extend(
        [
            "",
            "## 决定分层",
            "",
            f"- 排除项：{len(exclusions)}",
            f"- 显式 QA 待定项：{len(manual)}",
            "",
        ]
    )
    return "\n".join(lines)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and (pd.isna(value) or value in {float("inf"), float("-inf")}):
        return None
    return value
