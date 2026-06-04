from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature, read_vector_layer, write_geojson

from .phase2_io import read_table


T05_JUNCTIONIZATION_BUNDLE_VERSION = "1"
T05_JUNCTIONIZATION_BUNDLE_MODE = "t05_junctionization_input"
T05_JUNCTIONIZATION_BUNDLE_LIMIT_BYTES = 250 * 1024
T05_JUNCTIONIZATION_BUNDLE_BEGIN = "BEGIN_T05_JUNCTIONIZATION_BUNDLE"
T05_JUNCTIONIZATION_BUNDLE_PAYLOAD = "payload:"
T05_JUNCTIONIZATION_BUNDLE_META = "meta: "
T05_JUNCTIONIZATION_BUNDLE_CHECKSUM = "checksum: "
T05_JUNCTIONIZATION_BUNDLE_END = "END_T05_JUNCTIONIZATION_BUNDLE"
T05_JUNCTIONIZATION_BUNDLE_LINE_WIDTH = 120

EVIDENCE_ROAD_ID_FIELDS = (
    "support_rcsdroad_ids",
    "selected_rcsdroad_ids",
    "fallback_rcsdroad_ids",
    "required_rcsdroad_ids",
    "original_rcsdroad_ids",
    "new_rcsdroad_ids",
)
EVIDENCE_NODE_ID_FIELDS = (
    "base_id",
    "base_id_candidate",
    "required_rcsdnode_ids",
    "required_rcsd_node_ids",
    "selected_rcsdnode_ids",
    "selected_rcsd_node_ids",
    "original_rcsdnode_ids",
    "new_rcsdnode_ids",
    "grouped_rcsdnode_ids",
    "selected_main_rcsdnode_id",
)
AUDIT_TABLE_NAMES = (
    "rcsd_junctionization_audit.csv",
    "intersection_match_all_audit.csv",
    "blocking_errors.csv",
    "relation_cardinality_errors.csv",
)
PHASE2_VECTOR_OUTPUTS = (
    "intersection_match_all.geojson",
    "rcsdroad_split.gpkg",
    "rcsdnode_generated.gpkg",
    "rcsdnode_grouped.gpkg",
    "rcsdroad_out.gpkg",
    "rcsdnode_out.gpkg",
)
T04_CASE_INCLUDE_SUFFIXES = (".json", ".gpkg", ".geojson")
T04_CASE_MAX_FILE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class T05JunctionizationBundleArtifacts:
    success: bool
    out_dir: Path
    bundle_paths: tuple[Path, ...]
    index_path: Path
    requested_target_ids: tuple[str, ...]
    successful_target_ids: tuple[str, ...]
    failed_target_ids: tuple[str, ...]
    failures: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class _CasePackage:
    target_id: str
    files: dict[str, bytes]
    manifest: dict[str, Any]


@dataclass(frozen=True)
class _ShardPackage:
    target_ids: tuple[str, ...]
    text: str
    size_bytes: int
    oversized: bool


def run_t05_export_junctionization_bundle(
    *,
    target_ids: Iterable[str | int],
    out_dir: str | Path,
    junction_surface_path: str | Path,
    nodes_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    fusion_audit_path: str | Path | None = None,
    t02_relation_evidence_path: str | Path | None = None,
    t07_relation_evidence_path: str | Path | None = None,
    t03_relation_evidence_path: str | Path | None = None,
    t04_relation_evidence_path: str | Path | None = None,
    t04_surface_path: str | Path | None = None,
    t04_summary_path: str | Path | None = None,
    t04_audit_path: str | Path | None = None,
    t04_case_root: str | Path | None = None,
    phase2_root: str | Path | None = None,
    context_buffer_m: float = 80.0,
    max_text_size_bytes: int = T05_JUNCTIONIZATION_BUNDLE_LIMIT_BYTES,
) -> T05JunctionizationBundleArtifacts:
    normalized_target_ids = _normalize_ids(target_ids)
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    if not normalized_target_ids:
        index_path = out_dir_path / "t05_junctionization_bundle_index.json"
        index_payload = _index_payload(
            requested_target_ids=(),
            successful_target_ids=(),
            failed_target_ids=(),
            failures=({"target_id": "", "reason": "empty_target_ids", "detail": "No target ids were provided."},),
            shards=(),
            input_paths={},
            max_text_size_bytes=max_text_size_bytes,
            context_buffer_m=context_buffer_m,
        )
        _write_json(index_path, index_payload)
        return T05JunctionizationBundleArtifacts(
            success=False,
            out_dir=out_dir_path,
            bundle_paths=(),
            index_path=index_path,
            requested_target_ids=(),
            successful_target_ids=(),
            failed_target_ids=(),
            failures=({"target_id": "", "reason": "empty_target_ids", "detail": "No target ids were provided."},),
        )

    input_paths = {
        "junction_surface_path": str(junction_surface_path),
        "nodes_path": str(nodes_path),
        "rcsdroad_path": str(rcsdroad_path),
        "rcsdnode_path": str(rcsdnode_path),
        "fusion_audit_path": None if fusion_audit_path is None else str(fusion_audit_path),
        "t02_relation_evidence_path": None if t02_relation_evidence_path is None else str(t02_relation_evidence_path),
        "t07_relation_evidence_path": None if t07_relation_evidence_path is None else str(t07_relation_evidence_path),
        "t03_relation_evidence_path": None if t03_relation_evidence_path is None else str(t03_relation_evidence_path),
        "t04_relation_evidence_path": None if t04_relation_evidence_path is None else str(t04_relation_evidence_path),
        "t04_surface_path": None if t04_surface_path is None else str(t04_surface_path),
        "t04_summary_path": None if t04_summary_path is None else str(t04_summary_path),
        "t04_audit_path": None if t04_audit_path is None else str(t04_audit_path),
        "t04_case_root": None if t04_case_root is None else str(t04_case_root),
        "phase2_root": None if phase2_root is None else str(phase2_root),
    }
    inputs = _load_bundle_inputs(
        junction_surface_path=junction_surface_path,
        nodes_path=nodes_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        fusion_audit_path=fusion_audit_path,
        t02_relation_evidence_path=t02_relation_evidence_path,
        t07_relation_evidence_path=t07_relation_evidence_path,
        t03_relation_evidence_path=t03_relation_evidence_path,
        t04_relation_evidence_path=t04_relation_evidence_path,
        t04_surface_path=t04_surface_path,
        t04_summary_path=t04_summary_path,
        t04_audit_path=t04_audit_path,
        t04_case_root=t04_case_root,
        phase2_root=phase2_root,
    )

    case_packages: list[_CasePackage] = []
    failures: list[dict[str, str]] = []
    for target_id in normalized_target_ids:
        try:
            case_packages.append(
                _build_case_package(
                    target_id=target_id,
                    inputs=inputs,
                    input_paths=input_paths,
                    context_buffer_m=context_buffer_m,
                    max_text_size_bytes=max_text_size_bytes,
                )
            )
        except Exception as exc:
            failures.append({"target_id": target_id, "reason": "case_package_failed", "detail": str(exc)})

    shards = _build_shards(case_packages, max_text_size_bytes=max_text_size_bytes)
    bundle_paths = _write_shards(out_dir_path, shards)
    index_path = out_dir_path / "t05_junctionization_bundle_index.json"
    successful_target_ids = tuple(case.target_id for case in case_packages)
    failed_target_ids = tuple(item["target_id"] for item in failures)
    _write_json(
        index_path,
        _index_payload(
            requested_target_ids=tuple(normalized_target_ids),
            successful_target_ids=successful_target_ids,
            failed_target_ids=failed_target_ids,
            failures=tuple(failures),
            shards=tuple(zip(bundle_paths, shards)),
            input_paths=input_paths,
            max_text_size_bytes=max_text_size_bytes,
            context_buffer_m=context_buffer_m,
        ),
    )
    return T05JunctionizationBundleArtifacts(
        success=bool(case_packages) and not failures,
        out_dir=out_dir_path,
        bundle_paths=tuple(bundle_paths),
        index_path=index_path,
        requested_target_ids=tuple(normalized_target_ids),
        successful_target_ids=successful_target_ids,
        failed_target_ids=failed_target_ids,
        failures=tuple(failures),
    )


def decode_t05_junctionization_bundle(bundle_txt: str | Path, out_dir: str | Path) -> Path:
    bundle_path = Path(bundle_txt)
    payload_bytes = _parse_bundle_text(bundle_path.read_text(encoding="utf-8"))
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as zf:
        zf.extractall(out_dir_path)
    return out_dir_path


def _load_bundle_inputs(
    *,
    junction_surface_path: str | Path,
    nodes_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    fusion_audit_path: str | Path | None,
    t02_relation_evidence_path: str | Path | None,
    t07_relation_evidence_path: str | Path | None,
    t03_relation_evidence_path: str | Path | None,
    t04_relation_evidence_path: str | Path | None,
    t04_surface_path: str | Path | None,
    t04_summary_path: str | Path | None,
    t04_audit_path: str | Path | None,
    t04_case_root: str | Path | None,
    phase2_root: str | Path | None,
) -> dict[str, Any]:
    evidence_by_source = {
        "T02_INPUT": _tag_rows("T02_INPUT", read_table(t02_relation_evidence_path)),
        "T07": _tag_rows("T07", read_table(t07_relation_evidence_path)),
        "T03": _tag_rows("T03", read_table(t03_relation_evidence_path)),
        "T04": _tag_rows("T04", read_table(t04_relation_evidence_path)),
    }
    return {
        "surfaces": read_vector_layer(junction_surface_path).features,
        "nodes": read_vector_layer(nodes_path).features,
        "rcsdroad": read_vector_layer(rcsdroad_path).features,
        "rcsdnode": read_vector_layer(rcsdnode_path).features,
        "fusion_audit": _tag_rows("T05_PHASE1_FUSION_AUDIT", read_table(fusion_audit_path)),
        "evidence_by_source": evidence_by_source,
        "evidence": [row for rows in evidence_by_source.values() for row in rows],
        "t04_surface": _read_optional_vector(t04_surface_path),
        "t04_summary": _tag_rows("T04_SUMMARY", read_table(t04_summary_path)),
        "t04_audit": _read_optional_tagged_vector_or_table(t04_audit_path, "T04_AUDIT"),
        "t04_case_root": None if t04_case_root is None else Path(t04_case_root),
        "phase2_audits": _read_phase2_audits(phase2_root),
        "phase2_vectors": _read_phase2_vectors(phase2_root),
    }


def _build_case_package(
    *,
    target_id: str,
    inputs: dict[str, Any],
    input_paths: dict[str, Any],
    context_buffer_m: float,
    max_text_size_bytes: int,
) -> _CasePackage:
    surfaces = [feature for feature in inputs["surfaces"] if _surface_matches_target(feature, target_id)]
    swsd_nodes = [feature for feature in inputs["nodes"] if _node_matches_target(feature, target_id)]
    evidence_rows = [row for row in inputs["evidence"] if _row_matches_target(row, target_id)]
    evidence_rows_by_source = {
        source: [row for row in rows if _row_matches_target(row, target_id)]
        for source, rows in inputs["evidence_by_source"].items()
    }
    fusion_audit_rows = [row for row in inputs["fusion_audit"] if _row_matches_target(row, target_id)]
    phase2_audit_rows = [row for row in inputs["phase2_audits"] if _row_matches_target(row, target_id)]
    t04_summary_rows = [row for row in inputs["t04_summary"] if _row_matches_target(row, target_id)]
    t04_audit_rows = [row for row in inputs["t04_audit"] if _row_matches_target(row, target_id)]
    t04_surface = [feature for feature in inputs["t04_surface"] if _surface_matches_target(feature, target_id)]

    road_ids = _ids_from_rows(evidence_rows + phase2_audit_rows, EVIDENCE_ROAD_ID_FIELDS)
    node_ids = _ids_from_rows(evidence_rows + phase2_audit_rows, EVIDENCE_NODE_ID_FIELDS)
    context_geometry = _context_geometry(surfaces=surfaces, swsd_nodes=swsd_nodes, context_buffer_m=context_buffer_m)

    rcsdroad = [
        feature
        for feature in inputs["rcsdroad"]
        if _feature_id(feature) in road_ids or _feature_intersects(feature, context_geometry)
    ]
    for road in rcsdroad:
        props = road.properties or {}
        node_ids.update(_split_values(props.get("snodeid")))
        node_ids.update(_split_values(props.get("enodeid")))

    rcsdnode = [
        feature
        for feature in inputs["rcsdnode"]
        if _feature_id(feature) in node_ids or _feature_intersects(feature, context_geometry)
    ]
    expected_vectors = _expected_vectors_for_target(
        inputs["phase2_vectors"],
        target_id=target_id,
        road_ids=road_ids,
        node_ids=node_ids,
    )
    t04_case_files = _read_t04_case_files_for_target(inputs["t04_case_root"], target_id, evidence_rows)
    id_seed = _id_seed_from_audit(phase2_audit_rows)

    manifest = {
        "bundle_version": T05_JUNCTIONIZATION_BUNDLE_VERSION,
        "bundle_mode": T05_JUNCTIONIZATION_BUNDLE_MODE,
        "target_id": target_id,
        "epsg": 3857,
        "context_buffer_m": context_buffer_m,
        "max_text_size_bytes": max_text_size_bytes,
        "input_paths": input_paths,
        "feature_counts": {
            "junction_anchor_surface": len(surfaces),
            "nodes": len(swsd_nodes),
            "rcsdroad": len(rcsdroad),
            "rcsdnode": len(rcsdnode),
            "relation_evidence_rows": len(evidence_rows),
            "fusion_audit_rows": len(fusion_audit_rows),
            "phase2_audit_rows": len(phase2_audit_rows),
            "t04_surface": len(t04_surface),
            "t04_summary_rows": len(t04_summary_rows),
            "t04_audit_rows": len(t04_audit_rows),
            "expected_intersection_match_all": len(expected_vectors["intersection_match_all.geojson"]),
            "expected_rcsdroad_split": len(expected_vectors["rcsdroad_split.gpkg"]),
            "expected_rcsdnode_generated": len(expected_vectors["rcsdnode_generated.gpkg"]),
            "expected_rcsdnode_grouped": len(expected_vectors["rcsdnode_grouped.gpkg"]),
        },
        "selected_ids": {
            "rcsdroad_ids": sorted(road_ids),
            "rcsdnode_ids": sorted(node_ids),
        },
        "local_test": _local_test_config(target_id=target_id, id_seed=id_seed),
        "created_at": _now_text(),
    }
    files = {
        "manifest.json": _json_bytes(manifest),
        "README.md": _readme_bytes(target_id),
        "local_test_config.json": _json_bytes(_local_test_config(target_id=target_id, id_seed=id_seed)),
        "junction_anchor_surface.geojson": _geojson_bytes("junction_anchor_surface.geojson", surfaces),
        "t04_surface.geojson": _geojson_bytes("t04_surface.geojson", t04_surface),
        "nodes.geojson": _geojson_bytes("nodes.geojson", swsd_nodes),
        "rcsdroad.geojson": _geojson_bytes("rcsdroad.geojson", rcsdroad),
        "rcsdnode.geojson": _geojson_bytes("rcsdnode.geojson", rcsdnode),
        "relation_evidence.json": _json_bytes({"rows": evidence_rows}),
        "t02_swsd_rcsd_relation_evidence.json": _json_bytes({"rows": evidence_rows_by_source["T02_INPUT"]}),
        "t07_swsd_rcsd_relation_evidence.json": _json_bytes({"rows": evidence_rows_by_source["T07"]}),
        "t03_swsd_rcsd_relation_evidence.json": _json_bytes({"rows": evidence_rows_by_source["T03"]}),
        "t04_swsd_rcsd_relation_evidence.json": _json_bytes({"rows": evidence_rows_by_source["T04"]}),
        "fusion_audit.json": _json_bytes({"rows": fusion_audit_rows}),
        "junction_anchor_surface_fusion_audit.json": _json_bytes({"rows": fusion_audit_rows}),
        "t04_summary.json": _json_bytes({"rows": t04_summary_rows}),
        "t04_audit.json": _json_bytes({"rows": t04_audit_rows}),
        "phase2_audit.json": _json_bytes({"rows": phase2_audit_rows}),
        "expected_intersection_match_all.geojson": _geojson_bytes(
            "expected_intersection_match_all.geojson",
            expected_vectors["intersection_match_all.geojson"],
        ),
        "expected_rcsdroad_split.geojson": _geojson_bytes("expected_rcsdroad_split.geojson", expected_vectors["rcsdroad_split.gpkg"]),
        "expected_rcsdnode_generated.geojson": _geojson_bytes("expected_rcsdnode_generated.geojson", expected_vectors["rcsdnode_generated.gpkg"]),
        "expected_rcsdnode_grouped.geojson": _geojson_bytes("expected_rcsdnode_grouped.geojson", expected_vectors["rcsdnode_grouped.gpkg"]),
        "expected_rcsdroad_out_slice.geojson": _geojson_bytes("expected_rcsdroad_out_slice.geojson", expected_vectors["rcsdroad_out.gpkg"]),
        "expected_rcsdnode_out_slice.geojson": _geojson_bytes("expected_rcsdnode_out_slice.geojson", expected_vectors["rcsdnode_out.gpkg"]),
    }
    files.update(t04_case_files)
    manifest["checksum"] = {name: hashlib.sha256(content).hexdigest() for name, content in files.items() if name != "manifest.json"}
    files["manifest.json"] = _json_bytes(manifest)
    return _CasePackage(target_id=target_id, files=files, manifest=manifest)


def _build_shards(case_packages: list[_CasePackage], *, max_text_size_bytes: int) -> list[_ShardPackage]:
    shards: list[_ShardPackage] = []
    current: list[_CasePackage] = []
    for case in case_packages:
        candidate = [*current, case]
        candidate_shard = _build_shard(candidate, max_text_size_bytes=max_text_size_bytes)
        if current and candidate_shard.size_bytes > max_text_size_bytes:
            shards.append(_build_shard(current, max_text_size_bytes=max_text_size_bytes))
            current = [case]
            continue
        current = candidate
    if current:
        shards.append(_build_shard(current, max_text_size_bytes=max_text_size_bytes))
    return shards


def _build_shard(case_packages: list[_CasePackage], *, max_text_size_bytes: int) -> _ShardPackage:
    target_ids = tuple(case.target_id for case in case_packages)
    files: dict[str, bytes] = {}
    for case in case_packages:
        for name, content in case.files.items():
            files[f"{case.target_id}/{name}"] = content
    manifest = {
        "bundle_version": T05_JUNCTIONIZATION_BUNDLE_VERSION,
        "bundle_mode": T05_JUNCTIONIZATION_BUNDLE_MODE,
        "target_ids": list(target_ids),
        "target_count": len(target_ids),
        "max_text_size_bytes": max_text_size_bytes,
        "case_manifests": {case.target_id: case.manifest for case in case_packages},
        "file_list": sorted(files),
        "checksum": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
        "created_at": _now_text(),
    }
    files["manifest.json"] = _json_bytes(manifest)
    payload_bytes = _zip_bytes(files)
    meta = {
        "bundle_version": T05_JUNCTIONIZATION_BUNDLE_VERSION,
        "bundle_mode": T05_JUNCTIONIZATION_BUNDLE_MODE,
        "target_ids": list(target_ids),
        "target_count": len(target_ids),
        "archive_format": "zip",
        "encoding": "base85",
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "created_at": _now_text(),
    }
    text = _build_bundle_text(meta=meta, payload_bytes=payload_bytes)
    size_bytes = len(text.encode("utf-8"))
    return _ShardPackage(
        target_ids=target_ids,
        text=text,
        size_bytes=size_bytes,
        oversized=size_bytes > max_text_size_bytes,
    )


def _write_shards(out_dir: Path, shards: list[_ShardPackage]) -> list[Path]:
    paths: list[Path] = []
    for index, shard in enumerate(shards, start=1):
        if len(shards) == 1 and len(shard.target_ids) == 1:
            name = f"{shard.target_ids[0]}.txt"
        elif len(shards) == 1:
            name = "t05_junctionization_bundle.txt"
        else:
            name = f"t05_junctionization_bundle_part{index:03d}.txt"
        path = out_dir / name
        path.write_text(shard.text, encoding="utf-8")
        paths.append(path)
    return paths


def _read_phase2_audits(phase2_root: str | Path | None) -> list[dict[str, Any]]:
    if phase2_root is None:
        return []
    root = Path(phase2_root)
    rows: list[dict[str, Any]] = []
    for name in AUDIT_TABLE_NAMES:
        path = root / name
        if path.is_file():
            rows.extend(_tag_rows(path.stem, read_table(path)))
    return rows


def _read_phase2_vectors(phase2_root: str | Path | None) -> dict[str, list[LayerFeature]]:
    vectors: dict[str, list[LayerFeature]] = {name: [] for name in PHASE2_VECTOR_OUTPUTS}
    if phase2_root is None:
        return vectors
    root = Path(phase2_root)
    for name in PHASE2_VECTOR_OUTPUTS:
        path = root / name
        if path.is_file():
            vectors[name] = read_vector_layer(path).features
    return vectors


def _read_optional_vector(path: str | Path | None) -> list[LayerFeature]:
    if path is None:
        return []
    vector_path = Path(path)
    if not vector_path.is_file():
        return []
    return read_vector_layer(vector_path).features


def _read_optional_tagged_vector_or_table(path: str | Path | None, source: str) -> list[dict[str, Any]]:
    if path is None:
        return []
    audit_path = Path(path)
    if not audit_path.is_file():
        return []
    if audit_path.suffix.lower() in {".gpkg", ".gpkt", ".geojson", ".shp"}:
        return _tag_rows(source, (feature.properties for feature in read_vector_layer(audit_path).features))
    return _tag_rows(source, read_table(audit_path))


def _expected_vectors_for_target(
    phase2_vectors: dict[str, list[LayerFeature]],
    *,
    target_id: str,
    road_ids: set[str],
    node_ids: set[str],
) -> dict[str, list[LayerFeature]]:
    expected = {name: [] for name in PHASE2_VECTOR_OUTPUTS}
    expected["intersection_match_all.geojson"] = [
        feature for feature in phase2_vectors["intersection_match_all.geojson"]
        if _normalize_id((feature.properties or {}).get("target_id")) == target_id
    ]
    expected["rcsdroad_split.gpkg"] = [
        feature for feature in phase2_vectors["rcsdroad_split.gpkg"]
        if _feature_id(feature) in road_ids
    ]
    expected["rcsdnode_generated.gpkg"] = [
        feature for feature in phase2_vectors["rcsdnode_generated.gpkg"]
        if _feature_id(feature) in node_ids
    ]
    expected["rcsdnode_grouped.gpkg"] = [
        feature for feature in phase2_vectors["rcsdnode_grouped.gpkg"]
        if _feature_id(feature) in node_ids
    ]
    expected["rcsdroad_out.gpkg"] = [
        feature for feature in phase2_vectors["rcsdroad_out.gpkg"]
        if _feature_id(feature) in road_ids
    ]
    expected["rcsdnode_out.gpkg"] = [
        feature for feature in phase2_vectors["rcsdnode_out.gpkg"]
        if _feature_id(feature) in node_ids
    ]
    return expected


def _read_t04_case_files_for_target(
    t04_case_root: Path | None,
    target_id: str,
    evidence_rows: list[dict[str, Any]],
) -> dict[str, bytes]:
    if t04_case_root is None or not t04_case_root.is_dir():
        return {}
    candidate_case_ids = {target_id}
    for row in evidence_rows:
        for key in ("case_id", "source_case_id", "representative_node_id"):
            value = _normalize_id(row.get(key))
            if value:
                candidate_case_ids.add(value)
    files: dict[str, bytes] = {}
    for case_id in sorted(candidate_case_ids):
        case_dir = t04_case_root / case_id
        if not case_dir.is_dir():
            continue
        for path in sorted(case_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in T04_CASE_INCLUDE_SUFFIXES:
                continue
            if path.stat().st_size > T04_CASE_MAX_FILE_BYTES:
                continue
            relative = Path("t04_case_root") / case_id / path.relative_to(case_dir)
            files[str(relative)] = path.read_bytes()
    return files


def _tag_rows(source: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item.setdefault("_bundle_source", source)
        tagged.append(item)
    return tagged


def _row_matches_target(row: dict[str, Any], target_id: str) -> bool:
    target_values = (
        row.get("target_id"),
        row.get("mainnodeid"),
        row.get("case_id"),
        row.get("representative_node_id"),
        row.get("related_target_ids"),
    )
    return target_id in {item for value in target_values for item in _split_values(value)}


def _surface_matches_target(feature: LayerFeature, target_id: str) -> bool:
    props = feature.properties or {}
    if _normalize_id(props.get("mainnodeid")) == target_id:
        return True
    if _normalize_id(props.get("target_id")) == target_id:
        return True
    if str(props.get("surface_id") or "") == f"JAS:{target_id}":
        return True
    return target_id in _split_values(props.get("source_case_ids"))


def _node_matches_target(feature: LayerFeature, target_id: str) -> bool:
    props = feature.properties or {}
    return _normalize_id(props.get("id")) == target_id or _normalize_id(props.get("mainnodeid")) == target_id


def _context_geometry(*, surfaces: list[LayerFeature], swsd_nodes: list[LayerFeature], context_buffer_m: float) -> BaseGeometry | None:
    geometries = [feature.geometry for feature in [*surfaces, *swsd_nodes] if feature.geometry is not None and not feature.geometry.is_empty]
    if not geometries:
        return None
    return unary_union(geometries).buffer(float(context_buffer_m))


def _feature_intersects(feature: LayerFeature, context_geometry: BaseGeometry | None) -> bool:
    if context_geometry is None or context_geometry.is_empty:
        return False
    geometry = feature.geometry
    return geometry is not None and not geometry.is_empty and geometry.intersects(context_geometry)


def _feature_id(feature: LayerFeature) -> str | None:
    return _normalize_id((feature.properties or {}).get("id"))


def _local_test_config(*, target_id: str, id_seed: dict[str, int | None]) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "runner": "rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_runner.run_t05_phase2_rcsd_junctionization_and_relation",
        "runner_kwargs": {
            "next_road_id_start": id_seed.get("next_road_id_start"),
            "next_node_id_start": id_seed.get("next_node_id_start"),
        },
        "inputs": {
            "junction_surface_path": "junction_anchor_surface.geojson",
            "fusion_audit_path": "junction_anchor_surface_fusion_audit.json",
            "nodes_path": "nodes.geojson",
            "rcsdroad_path": "rcsdroad.geojson",
            "rcsdnode_path": "rcsdnode.geojson",
            "t02_relation_evidence_path": "t02_swsd_rcsd_relation_evidence.json",
            "t07_relation_evidence_path": "t07_swsd_rcsd_relation_evidence.json",
            "t03_relation_evidence_path": "t03_swsd_rcsd_relation_evidence.json",
            "t04_relation_evidence_path": "t04_swsd_rcsd_relation_evidence.json",
            "t04_surface_path": "t04_surface.geojson",
            "t04_summary_path": "t04_summary.json",
            "t04_audit_path": "t04_audit.json",
            "t04_case_root": "t04_case_root",
        },
        "expected": {
            "intersection_match_all": "expected_intersection_match_all.geojson",
            "rcsdroad_split": "expected_rcsdroad_split.geojson",
            "rcsdnode_generated": "expected_rcsdnode_generated.geojson",
            "rcsdnode_grouped": "expected_rcsdnode_grouped.geojson",
            "rcsdroad_out_slice": "expected_rcsdroad_out_slice.geojson",
            "rcsdnode_out_slice": "expected_rcsdnode_out_slice.geojson",
            "audit_rows": "phase2_audit.json",
        },
        "assertion_focus": [
            "relation target_id/base_id/status",
            "RCSDRoad split new road ids and endpoint ids",
            "generated RCSDNode geometry and mainnodeid grouping",
            "grouped existing RCSDNode mainnodeid",
        ],
    }


def _id_seed_from_audit(rows: list[dict[str, Any]]) -> dict[str, int | None]:
    road_ids = _ids_from_rows(rows, ("new_rcsdroad_ids",))
    node_ids = _ids_from_rows(rows, ("new_rcsdnode_ids",))
    return {
        "next_road_id_start": _min_int_or_none(road_ids),
        "next_node_id_start": _min_int_or_none(node_ids),
    }


def _min_int_or_none(values: set[str]) -> int | None:
    ints: list[int] = []
    for value in values:
        try:
            ints.append(int(value))
        except (TypeError, ValueError):
            continue
    return min(ints) if ints else None


def _readme_bytes(target_id: str) -> bytes:
    text = f"""# T05 junctionization fixture: {target_id}

This bundle is a small real-data fixture for local T05 Phase2 RCSD junctionization tests.

Use `local_test_config.json` for relative input and expected-output paths. The input files are GeoJSON/JSON slices intended to be passed to `run_t05_phase2_rcsd_junctionization_and_relation(...)` from a temporary output directory. Expected files are slices from the original full-data Phase2 outputs and are suitable for assertions around relation status, RCSDRoad split, generated RCSDNode, and RCSDNode grouping.
"""
    return text.encode("utf-8")


def _ids_from_rows(rows: Iterable[dict[str, Any]], field_names: tuple[str, ...]) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        for field_name in field_names:
            ids.update(_split_values(row.get(field_name)))
    ids.discard("0")
    ids.discard("-1")
    return ids


def _split_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        text = str(value).strip()
        if not text:
            return set()
        raw_values = text.replace("|", ",").replace(";", ",").replace(" ", ",").split(",")
    normalized: set[str] = set()
    for raw_value in raw_values:
        value_text = _normalize_id(raw_value)
        if value_text:
            normalized.add(value_text)
    return normalized


def _normalize_ids(values: Iterable[str | int]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_id(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    if text.endswith(".0"):
        try:
            return str(int(float(text)))
        except Exception:
            return text
    return text


def _geojson_bytes(filename: str, features: Iterable[LayerFeature]) -> bytes:
    records = [{"properties": dict(feature.properties or {}), "geometry": feature.geometry} for feature in features]
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / filename
        write_geojson(path, records)
        return path.read_bytes()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    return buffer.getvalue()


def _build_bundle_text(*, meta: dict[str, Any], payload_bytes: bytes) -> str:
    payload_text = base64.b85encode(payload_bytes).decode("ascii")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    lines = [
        T05_JUNCTIONIZATION_BUNDLE_BEGIN,
        T05_JUNCTIONIZATION_BUNDLE_META + json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        T05_JUNCTIONIZATION_BUNDLE_PAYLOAD,
        _wrap_payload_text(payload_text),
        T05_JUNCTIONIZATION_BUNDLE_CHECKSUM + checksum,
        T05_JUNCTIONIZATION_BUNDLE_END,
        "",
    ]
    return "\n".join(lines)


def _parse_bundle_text(bundle_text: str) -> bytes:
    lines = bundle_text.splitlines()
    if not lines or lines[0].strip() != T05_JUNCTIONIZATION_BUNDLE_BEGIN:
        raise ValueError("T05 junctionization bundle header not found.")
    try:
        payload_index = next(index for index, line in enumerate(lines) if line.strip() == T05_JUNCTIONIZATION_BUNDLE_PAYLOAD)
        checksum_index = next(index for index, line in enumerate(lines) if line.startswith(T05_JUNCTIONIZATION_BUNDLE_CHECKSUM))
        end_index = next(index for index, line in enumerate(lines) if line.strip() == T05_JUNCTIONIZATION_BUNDLE_END)
    except StopIteration as exc:
        raise ValueError("T05 junctionization bundle markers are incomplete.") from exc
    payload_text = "".join(lines[payload_index + 1 : checksum_index]).strip()
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = lines[checksum_index][len(T05_JUNCTIONIZATION_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise ValueError("T05 junctionization bundle checksum validation failed.")
    if checksum_index >= end_index:
        raise ValueError("T05 junctionization bundle footer order is invalid.")
    return payload_bytes


def _wrap_payload_text(text: str, *, width: int = T05_JUNCTIONIZATION_BUNDLE_LINE_WIDTH) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def _index_payload(
    *,
    requested_target_ids: tuple[str, ...],
    successful_target_ids: tuple[str, ...],
    failed_target_ids: tuple[str, ...],
    failures: tuple[dict[str, str], ...],
    shards: tuple[tuple[Path, _ShardPackage], ...],
    input_paths: dict[str, Any],
    max_text_size_bytes: int,
    context_buffer_m: float,
) -> dict[str, Any]:
    return {
        "bundle_version": T05_JUNCTIONIZATION_BUNDLE_VERSION,
        "bundle_mode": T05_JUNCTIONIZATION_BUNDLE_MODE,
        "created_at": _now_text(),
        "requested_target_ids": list(requested_target_ids),
        "successful_target_ids": list(successful_target_ids),
        "failed_target_ids": list(failed_target_ids),
        "failures": list(failures),
        "max_text_size_bytes": max_text_size_bytes,
        "context_buffer_m": context_buffer_m,
        "input_paths": input_paths,
        "shards": [
            {
                "path": str(path),
                "target_ids": list(shard.target_ids),
                "size_bytes": shard.size_bytes,
                "oversized": shard.oversized,
            }
            for path, shard in shards
        ],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
