from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from shapely.geometry import box

from .carrier_graph import field_name, normalize_id, parse_ids
from .models import AuditConfig, T12ContractError


@dataclass(frozen=True)
class LoadedInputs:
    segments: gpd.GeoDataFrame
    swsd_roads: gpd.GeoDataFrame
    swsd_nodes: gpd.GeoDataFrame
    frcsd_roads: gpd.GeoDataFrame
    frcsd_nodes: gpd.GeoDataFrame
    rcsd_intersections: gpd.GeoDataFrame
    drivezone: gpd.GeoDataFrame | None
    t05_anchor_audit: pd.DataFrame
    t06_cross_evidence: dict[str, dict[str, Any]]
    processing_crs: str
    crop_inner_geometry: Any | None
    input_audit: dict[str, Any]
    topology_audit: dict[str, Any]
    evidence_audit: dict[str, Any]


def load_inputs(
    *,
    swsd_segment_path: Path,
    swsd_roads_path: Path,
    swsd_nodes_path: Path,
    frcsd_roads_path: Path,
    frcsd_nodes_path: Path,
    t05_anchor_audit_path: Path,
    rcsd_intersection_path: Path,
    t06_run_root: Path,
    drivezone_path: Path | None,
    case_manifest_path: Path | None,
    config: AuditConfig,
) -> LoadedInputs:
    paths = {
        "swsd_segment": swsd_segment_path,
        "swsd_roads": swsd_roads_path,
        "swsd_nodes": swsd_nodes_path,
        "frcsd_roads": frcsd_roads_path,
        "frcsd_nodes": frcsd_nodes_path,
        "t05_anchor_audit": t05_anchor_audit_path,
        "rcsd_intersection": rcsd_intersection_path,
        "t06_run_root": t06_run_root,
    }
    if drivezone_path is not None:
        paths["drivezone"] = drivezone_path
    if case_manifest_path is not None:
        paths["case_manifest"] = case_manifest_path
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise T12ContractError(f"missing T12 inputs: {', '.join(missing)}")

    vectors: dict[str, gpd.GeoDataFrame] = {
        "segments": gpd.read_file(swsd_segment_path),
        "swsd_roads": gpd.read_file(swsd_roads_path),
        "swsd_nodes": gpd.read_file(swsd_nodes_path),
        "frcsd_roads": gpd.read_file(frcsd_roads_path),
        "frcsd_nodes": gpd.read_file(frcsd_nodes_path),
        "rcsd_intersections": gpd.read_file(rcsd_intersection_path),
    }
    if drivezone_path is not None:
        vectors["drivezone"] = gpd.read_file(drivezone_path)
    processing_crs, transform_audit = _normalize_crs(vectors, config.processing_crs)
    invalid_geometry = {
        name: int((~frame.geometry.is_valid | frame.geometry.is_empty).sum())
        for name, frame in vectors.items()
    }
    invalid_nonzero = {name: count for name, count in invalid_geometry.items() if count}
    if invalid_nonzero:
        raise T12ContractError(f"invalid or empty geometries found: {invalid_nonzero}")

    t05_anchor_audit = pd.read_csv(t05_anchor_audit_path, dtype=str).fillna("")
    t06_cross_evidence, evidence_audit = load_t06_cross_evidence(
        t06_run_root=t06_run_root,
        t05_anchor_audit_path=t05_anchor_audit_path,
        allow_unverified=config.allow_unverified_t06_evidence,
    )
    topology_audit = _topology_audit(vectors["frcsd_roads"], vectors["frcsd_nodes"])
    if topology_audit["endpoint_missing_count"]:
        raise T12ContractError(
            "FRCSD road endpoints are missing from the node layer: "
            f"{topology_audit['endpoint_missing_node_ids']}"
        )
    crop_inner = _case_inner_geometry(case_manifest_path, config.crop_inner_margin_m)
    input_audit = {
        name: _file_audit(path)
        for name, path in paths.items()
        if path.is_file()
    }
    input_audit["crs"] = transform_audit
    input_audit["invalid_geometry_count"] = invalid_geometry
    return LoadedInputs(
        segments=vectors["segments"],
        swsd_roads=vectors["swsd_roads"],
        swsd_nodes=vectors["swsd_nodes"],
        frcsd_roads=vectors["frcsd_roads"],
        frcsd_nodes=vectors["frcsd_nodes"],
        rcsd_intersections=vectors["rcsd_intersections"],
        drivezone=vectors.get("drivezone"),
        t05_anchor_audit=t05_anchor_audit,
        t06_cross_evidence=t06_cross_evidence,
        processing_crs=processing_crs,
        crop_inner_geometry=crop_inner,
        input_audit=input_audit,
        topology_audit=topology_audit,
        evidence_audit=evidence_audit,
    )


def load_t06_cross_evidence(
    *,
    t06_run_root: Path,
    t05_anchor_audit_path: Path,
    allow_unverified: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    step2 = t06_run_root / "step2_extract_rcsd_segments"
    summary_path = step2 / "t06_step2_summary.json"
    rejected_path = step2 / "t06_rcsd_buffer_segment_rejected.csv"
    probe_path = step2 / "t06_rcsd_buffer_only_probe.csv"
    failure_path = step2 / "t06_rcsd_segment_failure_business_audit.csv"
    problem_path = step2 / "t06_segment_replacement_problem_registry.csv"
    plan_path = step2 / "t06_segment_replacement_plan.csv"
    required = [summary_path, rejected_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise T12ContractError(f"missing T06 cross evidence: {missing}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    input_paths = summary.get("input_paths") or {}
    relation_path = Path(
        str(
            input_paths.get("intersection_match_path")
            or input_paths.get("relation_path")
            or ""
        )
    )
    evidence_relation = "unverified_legacy"
    if (
        relation_path.name
        and relation_path.parent.resolve() == t05_anchor_audit_path.parent.resolve()
    ):
        evidence_relation = "derived_copy_on_write"
    elif not allow_unverified:
        raise T12ContractError(
            "T06 evidence cannot be tied to the provided T05 run; "
            "use explicit legacy override only for audited historical evidence"
        )
    rows: defaultdict[str, dict[str, Any]] = defaultdict(dict)
    _merge_table(rows, rejected_path, "swsd_segment_id", prefix="t06")
    if probe_path.is_file():
        _merge_table(rows, probe_path, "swsd_segment_id", prefix="probe")
    if failure_path.is_file():
        _merge_table(rows, failure_path, "swsd_segment_id", prefix="failure")
    if problem_path.is_file():
        _merge_table(rows, problem_path, "swsd_segment_id", prefix="problem")
    if plan_path.is_file():
        _merge_table(rows, plan_path, "swsd_segment_id", prefix="plan")
    artifact_paths = {
        "summary": summary_path,
        "rejected": rejected_path,
        "buffer_only_probe": probe_path,
        "failure_business_audit": failure_path,
        "problem_registry": problem_path,
        "replacement_plan": plan_path,
    }
    return dict(rows), {
        "evidence_relation": evidence_relation,
        "t06_step2_summary": str(summary_path),
        "t06_input_paths": input_paths,
        "t05_anchor_audit": str(t05_anchor_audit_path),
        "cross_evidence_row_count": len(rows),
        "cross_evidence_artifacts": {
            name: _file_audit(path)
            for name, path in artifact_paths.items()
            if path.is_file()
        },
    }


def _normalize_crs(
    vectors: Mapping[str, gpd.GeoDataFrame],
    requested_crs: str | None,
) -> tuple[str, dict[str, Any]]:
    missing = [name for name, frame in vectors.items() if frame.crs is None]
    if missing:
        raise T12ContractError(f"missing CRS: {', '.join(missing)}")
    source_crs = {name: str(frame.crs) for name, frame in vectors.items()}
    distinct = {value.upper() for value in source_crs.values()}
    if requested_crs:
        target = CRS.from_user_input(requested_crs)
    elif len(distinct) == 1:
        target = CRS.from_user_input(next(iter(source_crs.values())))
    else:
        raise T12ContractError(
            f"CRS mismatch requires explicit processing_crs: {source_crs}"
        )
    if not target.is_projected:
        raise T12ContractError(
            f"processing CRS must be projected and metre-based: {target.to_string()}"
        )
    unit_names = {axis.unit_name.lower() for axis in target.axis_info if axis.unit_name}
    if unit_names and not any("metre" in unit or "meter" in unit for unit in unit_names):
        raise T12ContractError(
            f"processing CRS axis unit must be metre: {target.to_string()} {unit_names}"
        )
    transform_applied: dict[str, bool] = {}
    for name, frame in vectors.items():
        source = CRS.from_user_input(frame.crs)
        transform_applied[name] = source != target
        if source != target:
            vectors[name] = frame.to_crs(target)
    return target.to_string(), {
        "input_crs": source_crs,
        "processing_crs": target.to_string(),
        "transform_applied": transform_applied,
    }


def _topology_audit(
    roads: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
) -> dict[str, Any]:
    road_start = field_name(roads, "snodeid")
    road_end = field_name(roads, "enodeid")
    node_id_field = field_name(nodes, "id")
    node_ids = {normalize_id(value) for value in nodes[node_id_field]}
    missing: set[str] = set()
    for field in (road_start, road_end):
        missing.update(
            normalize_id(value)
            for value in roads[field]
            if normalize_id(value) not in node_ids
        )
    missing.discard("")
    return {
        "road_count": len(roads),
        "node_count": len(nodes),
        "endpoint_missing_count": len(missing),
        "endpoint_missing_node_ids": sorted(missing)[:100],
        "silent_fix": False,
    }


def _case_inner_geometry(path: Path | None, margin_m: float) -> Any | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    bounds = (payload.get("scope") or {}).get("bounds")
    if not isinstance(bounds, dict):
        raise T12ContractError("case manifest scope.bounds is required for crop-edge audit")
    minx = float(bounds["minx"])
    miny = float(bounds["miny"])
    maxx = float(bounds["maxx"])
    maxy = float(bounds["maxy"])
    if maxx - minx <= 2 * margin_m or maxy - miny <= 2 * margin_m:
        raise T12ContractError("case bounds are too small for crop_inner_margin_m")
    return box(minx + margin_m, miny + margin_m, maxx - margin_m, maxy - margin_m)


def _merge_table(
    output: defaultdict[str, dict[str, Any]],
    path: Path,
    id_field: str,
    *,
    prefix: str,
) -> None:
    frame = pd.read_csv(path, dtype=str).fillna("")
    resolved_id = field_name(frame, id_field)
    for _, row in frame.iterrows():
        segment_id = normalize_id(row[resolved_id])
        if not segment_id:
            continue
        for key, value in row.to_dict().items():
            output[segment_id].setdefault(f"{prefix}_{key}", value)


def _file_audit(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }
