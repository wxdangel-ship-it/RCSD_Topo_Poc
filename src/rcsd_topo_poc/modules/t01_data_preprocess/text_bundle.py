from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Sequence

import fiona
from shapely.affinity import translate
from shapely.geometry import shape

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer, write_vector
from rcsd_topo_poc.modules.t01_data_preprocess.slice_builder import (
    _resolve_profile_config,
    build_validation_slices,
)


T01_TEXT_BUNDLE_VERSION = "1"
T01_TEXT_BUNDLE_TYPE = "t01_data_preprocess_skill_v1_evidence"
T01_INPUT_TEXT_BUNDLE_TYPE = "t01_data_preprocess_input_nodes_roads_context"
T01_SUPPORTED_TEXT_BUNDLE_TYPES = {T01_TEXT_BUNDLE_TYPE, T01_INPUT_TEXT_BUNDLE_TYPE}
T01_INPUT_TEXT_BUNDLE_LIMIT_BYTES = 250 * 1024
T01_TEXT_BUNDLE_BEGIN = "BEGIN_T01_DATA_PREPROCESS_BUNDLE"
T01_TEXT_BUNDLE_PAYLOAD = "payload:"
T01_TEXT_BUNDLE_META = "meta: "
T01_TEXT_BUNDLE_CHECKSUM = "checksum: "
T01_TEXT_BUNDLE_END = "END_T01_DATA_PREPROCESS_BUNDLE"
T01_TEXT_BUNDLE_LINE_WIDTH = 120

T01_CURRENT_TEXT_BUNDLE_NAME = "t01_skill_v1_evidence_bundle.txt"
T01_CURRENT_TEXT_BUNDLE_SIZE_REPORT_NAME = "t01_skill_v1_evidence_bundle_size_report.json"
T01_BASELINE_TEXT_BUNDLE_NAME = "t01_skill_v1_freeze_evidence_bundle.txt"
T01_BASELINE_TEXT_BUNDLE_SIZE_REPORT_NAME = "t01_skill_v1_freeze_evidence_bundle_size_report.json"
T01_INPUT_TEXT_BUNDLE_NAME = "t01_input_nodes_roads_bundle.txt"
T01_INPUT_TEXT_BUNDLE_SIZE_REPORT_NAME = "t01_input_nodes_roads_bundle_size_report.json"
T01_INTERNAL_MANIFEST_NAME = "text_bundle_manifest.json"
T01_INTERNAL_SIZE_REPORT_NAME = "text_bundle_size_report.json"
T01_INPUT_PROFILE_IDS = ("XXXS", "XXS", "XS", "S", "M")
T01_INPUT_DEFAULT_PROFILE_ID = "XS"

T01_REQUIRED_EVIDENCE_FILES_BY_MODE = {
    "current": (
        "skill_v1_manifest.json",
        "skill_v1_summary.json",
        "validated_pairs_skill_v1.csv",
        "segment_body_membership_skill_v1.csv",
        "trunk_membership_skill_v1.csv",
        "refreshed_nodes_hash.json",
        "refreshed_roads_hash.json",
    ),
    "baseline": (
        "FREEZE_MANIFEST.json",
        "FREEZE_SUMMARY.json",
        "validated_pairs_baseline.csv",
        "segment_body_membership_baseline.csv",
        "trunk_membership_baseline.csv",
        "refreshed_nodes_hash.json",
        "refreshed_roads_hash.json",
    ),
}

T01_OPTIONAL_EVIDENCE_FILES = (
    "FREEZE_COMPARE_RULES.md",
    "segment_summary.json",
    "inner_nodes_summary.json",
    "oneway_segment_summary.json",
    "oneway_segment_build_table.csv",
    "unsegmented_roads.csv",
    "unsegmented_roads_summary.json",
    "distance_gate_scope_check.json",
    "freeze_compare_report.json",
    "freeze_compare_report.md",
    "t01_skill_v1_summary.json",
    "t01_skill_v1_summary.md",
    "t01_skill_v1_progress.json",
    "t01_skill_v1_perf.json",
    "t01_skill_v1_perf.md",
    "t01_skill_v1_perf_markers.jsonl",
)

T01_VECTOR_EVIDENCE_FILES = (
    "nodes.gpkg",
    "roads.gpkg",
    "segment.gpkg",
    "inner_nodes.gpkg",
    "segment_error.gpkg",
    "segment_error_s_grade_conflict.gpkg",
    "segment_error_grade_kind_conflict.gpkg",
    "oneway_segment_roads.gpkg",
    "unsegmented_roads.gpkg",
)


class T01TextBundleError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class T01TextBundleExportArtifacts:
    success: bool
    bundle_txt_path: Path
    size_report_path: Path | None
    bundle_size_bytes: int
    included_file_count: int = 0
    failure_reason: str | None = None
    failure_detail: str | None = None
    selected_profile_id: str | None = None
    selected_core_node_count: int | None = None
    part_txt_paths: tuple[Path, ...] = ()
    max_part_size_bytes: int = 0


@dataclass(frozen=True)
class T01TextBundleDecodeArtifacts:
    success: bool
    out_dir: Path
    manifest_path: Path


def text_bundle_name_for_mode(mode: Literal["current", "baseline"]) -> str:
    return T01_BASELINE_TEXT_BUNDLE_NAME if mode == "baseline" else T01_CURRENT_TEXT_BUNDLE_NAME


def text_bundle_size_report_name_for_mode(mode: Literal["current", "baseline"]) -> str:
    return T01_BASELINE_TEXT_BUNDLE_SIZE_REPORT_NAME if mode == "baseline" else T01_CURRENT_TEXT_BUNDLE_SIZE_REPORT_NAME


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _wrap_payload_text(text: str, *, width: int = T01_TEXT_BUNDLE_LINE_WIDTH) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def _build_bundle_text(*, meta: dict[str, Any], payload_bytes: bytes) -> tuple[str, int]:
    payload_text = base64.b85encode(payload_bytes).decode("ascii")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    lines = [
        T01_TEXT_BUNDLE_BEGIN,
        T01_TEXT_BUNDLE_META + json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        T01_TEXT_BUNDLE_PAYLOAD,
        _wrap_payload_text(payload_text),
        T01_TEXT_BUNDLE_CHECKSUM + checksum,
        T01_TEXT_BUNDLE_END,
        "",
    ]
    text = "\n".join(lines)
    return text, len(text.encode("utf-8"))


def _part_txt_paths(out_txt: Path, part_count: int) -> tuple[Path, ...]:
    if part_count <= 1:
        return (out_txt,)
    suffix = out_txt.suffix or ".txt"
    return tuple(
        out_txt if index == 1 else out_txt.with_name(f"{out_txt.stem}.part_{index:04d}_of_{part_count:04d}{suffix}")
        for index in range(1, part_count + 1)
    )


def _remove_existing_bundle_outputs(out_txt: Path) -> None:
    if out_txt.exists():
        out_txt.unlink()
    suffix = out_txt.suffix or ".txt"
    for path in out_txt.parent.glob(f"{out_txt.stem}.part_*_of_*{suffix}"):
        if path != out_txt and path.is_file():
            path.unlink()


def _split_payload_bundle_texts(
    *,
    out_txt: Path,
    meta: dict[str, Any],
    payload_bytes: bytes,
    max_text_size_bytes: int,
) -> tuple[tuple[Path, str, int], ...]:
    if max_text_size_bytes <= 0:
        raise T01TextBundleError("invalid_max_text_size", "max_text_size_bytes must be > 0.")

    full_payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()

    def build_parts(chunk_size: int) -> tuple[tuple[Path, str, int], ...]:
        chunks = [payload_bytes[index : index + chunk_size] for index in range(0, len(payload_bytes), chunk_size)]
        part_paths = _part_txt_paths(out_txt, len(chunks))
        part_filenames = [path.name for path in part_paths]
        parts: list[tuple[Path, str, int]] = []
        for index, chunk in enumerate(chunks, start=1):
            part_meta = {
                **meta,
                "split_bundle": {
                    "enabled": True,
                    "bundle_id": full_payload_sha256,
                    "part_index": index,
                    "part_count": len(chunks),
                    "part_filenames": part_filenames,
                    "full_payload_sha256": full_payload_sha256,
                },
            }
            text, size = _build_bundle_text(meta=part_meta, payload_bytes=chunk)
            parts.append((part_paths[index - 1], text, size))
        return tuple(parts)

    low, high = 1, max(1, len(payload_bytes))
    best: tuple[tuple[Path, str, int], ...] | None = None
    while low <= high:
        mid = (low + high) // 2
        parts = build_parts(mid)
        if max(size for _, _, size in parts) <= max_text_size_bytes:
            best = parts
            low = mid + 1
        else:
            high = mid - 1
    if best is None:
        raise T01TextBundleError(
            "bundle_part_too_large",
            f"Bundle part metadata cannot fit limit {max_text_size_bytes}.",
        )
    return best


def _parse_text_bundle(bundle_text: str) -> tuple[dict[str, Any], bytes]:
    lines = bundle_text.splitlines()
    if not lines or lines[0].strip() != T01_TEXT_BUNDLE_BEGIN:
        raise T01TextBundleError("invalid_bundle_format", "Bundle header not found.")
    try:
        meta_index = next(index for index, line in enumerate(lines) if line.startswith(T01_TEXT_BUNDLE_META))
        payload_index = next(index for index, line in enumerate(lines) if line.strip() == T01_TEXT_BUNDLE_PAYLOAD)
        checksum_index = next(index for index, line in enumerate(lines) if line.startswith(T01_TEXT_BUNDLE_CHECKSUM))
        end_index = next(index for index, line in enumerate(lines) if line.strip() == T01_TEXT_BUNDLE_END)
    except StopIteration as exc:
        raise T01TextBundleError("invalid_bundle_format", "Bundle markers are incomplete.") from exc
    if not (meta_index < payload_index < checksum_index < end_index):
        raise T01TextBundleError("invalid_bundle_format", "Bundle section order is invalid.")

    meta = json.loads(lines[meta_index][len(T01_TEXT_BUNDLE_META) :])
    payload_text = "".join(lines[payload_index + 1 : checksum_index]).strip()
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = lines[checksum_index][len(T01_TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise T01TextBundleError("checksum_mismatch", "Bundle payload checksum validation failed.")
    if str(meta.get("bundle_version")) != T01_TEXT_BUNDLE_VERSION:
        raise T01TextBundleError("bundle_version_mismatch", f"Unsupported bundle version: {meta.get('bundle_version')}")
    if str(meta.get("bundle_type")) not in T01_SUPPORTED_TEXT_BUNDLE_TYPES:
        raise T01TextBundleError("bundle_type_mismatch", f"Unsupported bundle type: {meta.get('bundle_type')}")
    return meta, payload_bytes


def _zip_bytes(files: dict[str, bytes]) -> tuple[bytes, dict[str, int]]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue()), "r") as zf:
        per_file_compressed = {info.filename: int(info.compress_size) for info in zf.infolist()}
    return buffer.getvalue(), per_file_compressed


def _assert_safe_bundle_name(name: str) -> str:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise T01TextBundleError("invalid_bundle_path", f"Bundle file path is not safe: {name}")
    return path.as_posix()


def _read_bundle_file(root: Path, relative_name: str) -> bytes:
    safe_name = _assert_safe_bundle_name(relative_name)
    path = root / safe_name
    if not path.is_file():
        raise T01TextBundleError("bundle_input_missing", f"Required bundle input is missing: {path}")
    return path.read_bytes()


def _collect_stage_segment_roads(root: Path) -> dict[str, bytes]:
    stage_root = root / "all_stage_segment_roads"
    if not stage_root.is_dir():
        return {}
    files: dict[str, bytes] = {}
    for path in sorted(stage_root.rglob("*")):
        if not path.is_file():
            continue
        relative_name = _assert_safe_bundle_name(path.relative_to(root).as_posix())
        files[relative_name] = path.read_bytes()
    return files


def _resolve_extra_file(root: Path, value: str | Path) -> tuple[str, bytes]:
    root_resolved = root.resolve()
    path = Path(value)
    source_path = path if path.is_absolute() else root / path
    source_resolved = source_path.resolve()
    try:
        relative_name = source_resolved.relative_to(root_resolved).as_posix()
    except ValueError as exc:
        raise T01TextBundleError(
            "extra_path_outside_root",
            f"Extra path is outside bundle root: {source_path}",
        ) from exc
    if not source_resolved.is_file():
        raise T01TextBundleError("extra_path_not_file", f"Extra path is not a file: {source_path}")
    return _assert_safe_bundle_name(relative_name), source_resolved.read_bytes()


def _geometry_origin(features: Sequence[dict[str, Any]]) -> tuple[float, float]:
    geometries = [
        feature.get("geometry")
        for feature in features
        if feature.get("geometry") is not None and not feature["geometry"].is_empty
    ]
    if not geometries:
        return 0.0, 0.0
    min_x = min(float(geometry.bounds[0]) for geometry in geometries)
    min_y = min(float(geometry.bounds[1]) for geometry in geometries)
    return round(min_x, 1), round(min_y, 1)


def _localized_features(
    features: Sequence[dict[str, Any]],
    *,
    origin_x: float,
    origin_y: float,
) -> list[dict[str, Any]]:
    localized: list[dict[str, Any]] = []
    for feature in features:
        geometry = feature.get("geometry")
        localized.append(
            {
                "properties": dict(feature.get("properties") or {}),
                "geometry": None if geometry is None else translate(geometry, xoff=-origin_x, yoff=-origin_y),
            }
        )
    return localized


def _prepare_input_context_files(
    *,
    node_path: Path,
    road_path: Path,
    node_layer: str | None,
    road_layer: str | None,
    node_crs: str | None,
    road_crs: str | None,
    profile_config_path: Path,
    profile_id: str,
    center_x: float,
    center_y: float,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        slice_root = temp_root / "slice"
        results = build_validation_slices(
            road_path=road_path,
            node_path=node_path,
            profile_config_path=profile_config_path,
            out_root=slice_root,
            selected_profile_ids=[profile_id],
            run_id=f"t01_input_bundle_{profile_id}",
            road_layer=road_layer,
            road_crs=road_crs,
            node_layer=node_layer,
            node_crs=node_crs,
            center_x=center_x,
            center_y=center_y,
        )
        if len(results) != 1:
            raise T01TextBundleError(
                "invalid_slice_result",
                f"Expected one T01 slice result for profile {profile_id}, got {len(results)}.",
            )
        result = results[0]
        slice_nodes_path = result.output_dir / "nodes.gpkg"
        slice_roads_path = result.output_dir / "roads.gpkg"
        node_read = read_vector_layer(slice_nodes_path, layer_name="nodes")
        road_read = read_vector_layer(slice_roads_path, layer_name="roads")
        selected_nodes = [
            {"properties": feature.properties, "geometry": feature.geometry} for feature in node_read.features
        ]
        selected_roads = [
            {"properties": feature.properties, "geometry": feature.geometry} for feature in road_read.features
        ]
        origin_x, origin_y = _geometry_origin([*selected_nodes, *selected_roads])
        output_nodes_gpkg = temp_root / "nodes.gpkg"
        output_roads_gpkg = temp_root / "roads.gpkg"
        write_vector(
            output_nodes_gpkg,
            _localized_features(selected_nodes, origin_x=origin_x, origin_y=origin_y),
            layer_name="nodes",
        )
        write_vector(
            output_roads_gpkg,
            _localized_features(selected_roads, origin_x=origin_x, origin_y=origin_y),
            layer_name="roads",
        )
        summary = dict(result.summary)
        slice_manifest_path = slice_root / "slice_manifest.json"
        slice_manifest = (
            json.loads(slice_manifest_path.read_text(encoding="utf-8")) if slice_manifest_path.is_file() else {}
        )
        audit = {
            "crop_mode": "t01_validation_profile_spatial_rank",
            "profile_id": result.profile.profile_id,
            "profile_description": result.profile.description,
            "target_core_node_count": result.profile.target_core_node_count,
            "center_x": float(center_x),
            "center_y": float(center_y),
            "input_node_path": str(node_path),
            "input_road_path": str(road_path),
            "profile_config_path": str(profile_config_path),
            "source_node_count": slice_manifest.get("source_node_count"),
            "source_road_count": slice_manifest.get("source_road_count"),
            "source_semantic_node_count": slice_manifest.get("source_semantic_node_count"),
            "selected_node_count": summary.get("output_physical_node_count"),
            "selected_semantic_node_count": summary.get("output_semantic_node_count"),
            "selected_road_count": summary.get("output_road_count"),
            "anchor_semantic_node_id": summary.get("anchor_semantic_node_id"),
            "anchor_representative_node_id": summary.get("anchor_representative_node_id"),
            "anchor_point_3857": summary.get("anchor_point_3857"),
            "anchor_semantic_point_3857": summary.get("anchor_semantic_point_3857"),
            "bounds_3857": summary.get("bounds_3857"),
            "node_crs": node_read.source_crs.to_string(),
            "road_crs": road_read.source_crs.to_string(),
            "node_crs_source": node_read.crs_source,
            "road_crs_source": road_read.crs_source,
            "local_origin": {"x": origin_x, "y": origin_y},
            "slice_summary": summary,
        }
        files = {
            "nodes.gpkg": output_nodes_gpkg.read_bytes(),
            "roads.gpkg": output_roads_gpkg.read_bytes(),
            "slice_summary.json": json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            "slice_manifest.json": json.dumps(
                slice_manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8"),
        }
        return files, audit


def _collect_bundle_files(
    *,
    root: Path,
    mode: Literal["current", "baseline"],
    include_vectors: bool,
    include_stage_segment_roads: bool,
    extra_relative_paths: Sequence[str | Path],
) -> tuple[dict[str, bytes], list[str]]:
    files: dict[str, bytes] = {}
    skipped_missing: list[str] = []

    for relative_name in T01_REQUIRED_EVIDENCE_FILES_BY_MODE[mode]:
        files[relative_name] = _read_bundle_file(root, relative_name)

    optional_names = list(T01_OPTIONAL_EVIDENCE_FILES)
    if include_vectors:
        optional_names.extend(T01_VECTOR_EVIDENCE_FILES)
    for relative_name in optional_names:
        safe_name = _assert_safe_bundle_name(relative_name)
        path = root / safe_name
        if path.is_file():
            files[safe_name] = path.read_bytes()
        else:
            skipped_missing.append(safe_name)

    if include_stage_segment_roads:
        files.update(_collect_stage_segment_roads(root))
        if "all_stage_segment_roads" not in {part.split("/", 1)[0] for part in files}:
            skipped_missing.append("all_stage_segment_roads/")

    for value in extra_relative_paths:
        relative_name, content = _resolve_extra_file(root, value)
        files[relative_name] = content

    return files, sorted(set(skipped_missing))


def _build_size_report(
    *,
    bundle_size_bytes: int,
    payload_size_bytes: int,
    per_file_raw_size_bytes: dict[str, int],
    per_file_compressed_size_bytes: dict[str, int],
    skipped_missing_files: list[str],
    mode: Literal["current", "baseline"],
    include_vectors: bool,
    include_stage_segment_roads: bool,
) -> dict[str, Any]:
    evidence_file_names = [
        name
        for name in per_file_raw_size_bytes
        if name not in {T01_INTERNAL_MANIFEST_NAME, T01_INTERNAL_SIZE_REPORT_NAME}
    ]
    dominant_size_source = None
    if evidence_file_names:
        dominant_size_source = max(evidence_file_names, key=lambda name: per_file_raw_size_bytes[name])
    return {
        "bundle_version": T01_TEXT_BUNDLE_VERSION,
        "bundle_type": T01_TEXT_BUNDLE_TYPE,
        "mode": mode,
        "total_text_size_bytes": bundle_size_bytes,
        "payload_size_bytes": payload_size_bytes,
        "included_file_count": len(evidence_file_names),
        "include_vectors": include_vectors,
        "include_stage_segment_roads": include_stage_segment_roads,
        "dominant_size_source": dominant_size_source,
        "per_file_raw_size_bytes": per_file_raw_size_bytes,
        "per_file_compressed_size_bytes": per_file_compressed_size_bytes,
        "skipped_missing_files": skipped_missing_files,
    }


def _build_input_size_report(
    *,
    bundle_size_bytes: int,
    payload_size_bytes: int,
    per_file_raw_size_bytes: dict[str, int],
    per_file_compressed_size_bytes: dict[str, int],
    selection_audit: dict[str, Any],
    max_text_size_bytes: int,
) -> dict[str, Any]:
    dominant_size_source = None
    if per_file_compressed_size_bytes:
        dominant_size_source = max(per_file_compressed_size_bytes.items(), key=lambda item: item[1])[0]
    return {
        "bundle_version": T01_TEXT_BUNDLE_VERSION,
        "bundle_type": T01_INPUT_TEXT_BUNDLE_TYPE,
        "total_text_size_bytes": bundle_size_bytes,
        "payload_size_bytes": payload_size_bytes,
        "included_file_count": len(
            [
                name
                for name in per_file_raw_size_bytes
                if name not in {T01_INTERNAL_MANIFEST_NAME, T01_INTERNAL_SIZE_REPORT_NAME}
            ]
        ),
        "within_limit": bundle_size_bytes <= max_text_size_bytes,
        "limit_bytes": max_text_size_bytes,
        "dominant_size_source": dominant_size_source,
        "selection_audit": selection_audit,
        "per_file_raw_size_bytes": per_file_raw_size_bytes,
        "per_file_compressed_size_bytes": per_file_compressed_size_bytes,
    }


def _build_input_text_bundle_for_profile_slice(
    *,
    node_path: Path,
    road_path: Path,
    node_layer: str | None,
    road_layer: str | None,
    node_crs: str | None,
    road_crs: str | None,
    profile_config_path: Path,
    profile_id: str,
    center_x: float,
    center_y: float,
    max_text_size_bytes: int,
) -> tuple[str, int, dict[str, Any]]:
    files, selection_audit = _prepare_input_context_files(
        node_path=node_path,
        road_path=road_path,
        node_layer=node_layer,
        road_layer=road_layer,
        node_crs=node_crs,
        road_crs=road_crs,
        profile_config_path=profile_config_path,
        profile_id=profile_id,
        center_x=center_x,
        center_y=center_y,
    )
    manifest = {
        "bundle_version": T01_TEXT_BUNDLE_VERSION,
        "bundle_type": T01_INPUT_TEXT_BUNDLE_TYPE,
        "profile_id": profile_id,
        "center_x": float(center_x),
        "center_y": float(center_y),
        "source_paths": {
            "nodes": str(node_path),
            "roads": str(road_path),
        },
        "selection": selection_audit,
        "file_list": sorted(set(files).union({T01_INTERNAL_MANIFEST_NAME, T01_INTERNAL_SIZE_REPORT_NAME})),
        "checksum": {},
        "encoder_info": {
            "archive_format": "zip",
            "compression": "deflate",
            "text_encoding": "base85",
            "line_width": T01_TEXT_BUNDLE_LINE_WIDTH,
            "max_text_size_bytes": max_text_size_bytes,
            "selection": "t01-input-nodes-roads-profile-centered-slice",
            "decoded_vector_format": "GeoPackage",
            "bundle_internal_vectors_localized": True,
        },
        "created_at": _now_text(),
    }

    files[T01_INTERNAL_SIZE_REPORT_NAME] = b"{}"
    files[T01_INTERNAL_MANIFEST_NAME] = b"{}"
    size_report: dict[str, Any] | None = None
    bundle_text = ""
    bundle_size_bytes = 0
    for _ in range(4):
        manifest["checksum"] = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(files.items())
            if name != T01_INTERNAL_MANIFEST_NAME
        }
        files[T01_INTERNAL_MANIFEST_NAME] = json.dumps(
            manifest,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        payload_bytes, per_file_compressed = _zip_bytes(files)
        meta = {
            "bundle_version": T01_TEXT_BUNDLE_VERSION,
            "bundle_type": T01_INPUT_TEXT_BUNDLE_TYPE,
            "profile_id": profile_id,
            "center_x": float(center_x),
            "center_y": float(center_y),
            "archive_format": "zip",
            "encoding": "base85",
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "created_at": _now_text(),
        }
        bundle_text, bundle_size_bytes = _build_bundle_text(meta=meta, payload_bytes=payload_bytes)
        next_size_report = _build_input_size_report(
            bundle_size_bytes=bundle_size_bytes,
            payload_size_bytes=len(payload_bytes),
            per_file_raw_size_bytes={name: len(content) for name, content in files.items()},
            per_file_compressed_size_bytes=per_file_compressed,
            selection_audit=selection_audit,
            max_text_size_bytes=max_text_size_bytes,
        )
        next_bytes = json.dumps(next_size_report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        if next_size_report == size_report:
            break
        size_report = next_size_report
        files[T01_INTERNAL_SIZE_REPORT_NAME] = next_bytes

    assert size_report is not None
    return bundle_text, bundle_size_bytes, size_report


def _attempt_summary(
    *,
    profile_id: str,
    center_x: float,
    center_y: float,
    bundle_size_bytes: int,
    size_report: dict[str, Any],
    max_text_size_bytes: int,
) -> dict[str, Any]:
    selection = size_report.get("selection_audit") or {}
    return {
        "profile_id": profile_id,
        "center_x": float(center_x),
        "center_y": float(center_y),
        "bundle_size_bytes": bundle_size_bytes,
        "within_limit": bundle_size_bytes <= max_text_size_bytes,
        "target_core_node_count": selection.get("target_core_node_count"),
        "selected_node_count": selection.get("selected_node_count"),
        "selected_road_count": selection.get("selected_road_count"),
        "dominant_size_source": size_report.get("dominant_size_source"),
    }


def _write_split_bundle(
    *,
    out_txt_path: Path,
    bundle_text: str,
    size_report: dict[str, Any],
    max_text_size_bytes: int,
) -> tuple[tuple[Path, ...], int]:
    meta, payload_bytes = _parse_text_bundle(bundle_text)
    parts = _split_payload_bundle_texts(
        out_txt=out_txt_path,
        meta=meta,
        payload_bytes=payload_bytes,
        max_text_size_bytes=max_text_size_bytes,
    )
    for path, text, _size in parts:
        path.write_text(text, encoding="utf-8")
    split_report = {
        "enabled": True,
        "part_count": len(parts),
        "part_files": [str(path) for path, _text, _size in parts],
        "part_size_bytes": {path.name: size for path, _text, size in parts},
        "max_part_size_bytes": max(size for _path, _text, size in parts),
    }
    size_report["split_bundle"] = split_report
    return tuple(path for path, _text, _size in parts), int(split_report["max_part_size_bytes"])


def _build_text_bundle(
    *,
    root: Path,
    mode: Literal["current", "baseline"],
    include_vectors: bool,
    include_stage_segment_roads: bool,
    extra_relative_paths: Sequence[str | Path],
) -> tuple[str, int, dict[str, Any]]:
    files, skipped_missing = _collect_bundle_files(
        root=root,
        mode=mode,
        include_vectors=include_vectors,
        include_stage_segment_roads=include_stage_segment_roads,
        extra_relative_paths=extra_relative_paths,
    )
    evidence_files = dict(files)
    manifest = {
        "bundle_version": T01_TEXT_BUNDLE_VERSION,
        "bundle_type": T01_TEXT_BUNDLE_TYPE,
        "mode": mode,
        "source_root": str(root.resolve()),
        "file_list": sorted(set(files).union({T01_INTERNAL_MANIFEST_NAME, T01_INTERNAL_SIZE_REPORT_NAME})),
        "checksum": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(evidence_files.items())},
        "encoder_info": {
            "archive_format": "zip",
            "compression": "deflate",
            "text_encoding": "base85",
            "line_width": T01_TEXT_BUNDLE_LINE_WIDTH,
            "selection": "t01-skill-v1-compact-evidence",
        },
        "created_at": _now_text(),
    }

    size_report: dict[str, Any] = {}
    bundle_text = ""
    bundle_size_bytes = 0
    for _ in range(4):
        files[T01_INTERNAL_MANIFEST_NAME] = json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        files[T01_INTERNAL_SIZE_REPORT_NAME] = json.dumps(
            size_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        payload_bytes, per_file_compressed = _zip_bytes(files)
        meta = {
            "bundle_version": T01_TEXT_BUNDLE_VERSION,
            "bundle_type": T01_TEXT_BUNDLE_TYPE,
            "mode": mode,
            "archive_format": "zip",
            "encoding": "base85",
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "created_at": _now_text(),
        }
        bundle_text, bundle_size_bytes = _build_bundle_text(meta=meta, payload_bytes=payload_bytes)
        next_report = _build_size_report(
            bundle_size_bytes=bundle_size_bytes,
            payload_size_bytes=len(payload_bytes),
            per_file_raw_size_bytes={name: len(content) for name, content in files.items()},
            per_file_compressed_size_bytes=per_file_compressed,
            skipped_missing_files=skipped_missing,
            mode=mode,
            include_vectors=include_vectors,
            include_stage_segment_roads=include_stage_segment_roads,
        )
        if next_report == size_report:
            break
        size_report = next_report

    return bundle_text, bundle_size_bytes, size_report


def run_t01_export_text_bundle(
    *,
    bundle_root: str | Path,
    out_txt: str | Path | None = None,
    mode: Literal["current", "baseline"] = "current",
    include_vectors: bool = False,
    include_stage_segment_roads: bool = False,
    extra_relative_paths: Sequence[str | Path] = (),
) -> T01TextBundleExportArtifacts:
    root = Path(bundle_root)
    out_txt_path = Path(out_txt) if out_txt is not None else root / text_bundle_name_for_mode(mode)
    size_report_path = out_txt_path.with_name(text_bundle_size_report_name_for_mode(mode))
    try:
        if mode not in T01_REQUIRED_EVIDENCE_FILES_BY_MODE:
            raise T01TextBundleError("invalid_mode", f"Unsupported T01 text bundle mode: {mode}")
        if not root.is_dir():
            raise T01TextBundleError("bundle_root_not_found", f"Bundle root does not exist: {root}")
        out_txt_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_text, bundle_size_bytes, size_report = _build_text_bundle(
            root=root,
            mode=mode,
            include_vectors=include_vectors,
            include_stage_segment_roads=include_stage_segment_roads,
            extra_relative_paths=extra_relative_paths,
        )
        out_txt_path.write_text(bundle_text, encoding="utf-8")
        size_report_path.write_text(
            json.dumps(size_report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return T01TextBundleExportArtifacts(
            success=True,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path,
            bundle_size_bytes=bundle_size_bytes,
            included_file_count=int(size_report.get("included_file_count") or 0),
        )
    except Exception as exc:
        reason = getattr(exc, "reason", "bundle_export_failed")
        detail = getattr(exc, "detail", str(exc))
        return T01TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            failure_reason=reason,
            failure_detail=detail,
        )


def run_t01_export_input_text_bundle(
    *,
    node_path: str | Path,
    road_path: str | Path,
    out_txt: str | Path,
    center_x: float,
    center_y: float,
    node_layer: str | None = None,
    road_layer: str | None = None,
    node_crs: str | None = None,
    road_crs: str | None = None,
    profile_id: str = T01_INPUT_DEFAULT_PROFILE_ID,
    profile_config_path: str | Path | None = None,
    max_text_size_bytes: int = T01_INPUT_TEXT_BUNDLE_LIMIT_BYTES,
) -> T01TextBundleExportArtifacts:
    out_txt_path = Path(out_txt)
    out_txt_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_existing_bundle_outputs(out_txt_path)
    size_report_path = out_txt_path.with_name(T01_INPUT_TEXT_BUNDLE_SIZE_REPORT_NAME)
    if size_report_path.exists():
        size_report_path.unlink()

    try:
        if max_text_size_bytes <= 0:
            raise T01TextBundleError("invalid_max_text_size", "max_text_size_bytes must be > 0.")

        resolved_node_path = Path(node_path)
        resolved_road_path = Path(road_path)
        selected_profile_id = str(profile_id).strip().upper()
        resolved_profile_config_path = _resolve_profile_config(profile_config_path)
        if selected_profile_id not in T01_INPUT_PROFILE_IDS:
            raise T01TextBundleError("invalid_profile_id", f"Unsupported profile_id: {profile_id}")

        selected_text, selected_size, selected_report = _build_input_text_bundle_for_profile_slice(
            node_path=resolved_node_path,
            road_path=resolved_road_path,
            node_layer=node_layer,
            road_layer=road_layer,
            node_crs=node_crs,
            road_crs=road_crs,
            profile_config_path=resolved_profile_config_path,
            profile_id=selected_profile_id,
            center_x=float(center_x),
            center_y=float(center_y),
            max_text_size_bytes=max_text_size_bytes,
        )
        selection = selected_report.get("selection_audit") or {}
        selected_report["attempt"] = _attempt_summary(
            profile_id=selected_profile_id,
            center_x=float(center_x),
            center_y=float(center_y),
            bundle_size_bytes=selected_size,
            size_report=selected_report,
            max_text_size_bytes=max_text_size_bytes,
        )

        part_paths: tuple[Path, ...]
        max_part_size_bytes = selected_size
        if selected_size <= max_text_size_bytes:
            out_txt_path.write_text(selected_text, encoding="utf-8")
            part_paths = (out_txt_path,)
        else:
            part_paths, max_part_size_bytes = _write_split_bundle(
                out_txt_path=out_txt_path,
                bundle_text=selected_text,
                size_report=selected_report,
                max_text_size_bytes=max_text_size_bytes,
            )
        size_report_path.write_text(
            json.dumps(selected_report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return T01TextBundleExportArtifacts(
            success=True,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path,
            bundle_size_bytes=selected_size,
            included_file_count=int(selected_report.get("included_file_count") or 0),
            selected_profile_id=selected_profile_id,
            selected_core_node_count=selection.get("target_core_node_count"),
            part_txt_paths=part_paths,
            max_part_size_bytes=max_part_size_bytes,
        )
    except Exception as exc:
        reason = getattr(exc, "reason", "bundle_export_failed")
        detail = getattr(exc, "detail", str(exc))
        return T01TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            failure_reason=reason,
            failure_detail=detail,
        )


def _bundle_payload_from_text_file(bundle_txt: Path) -> tuple[bytes, dict[str, Any] | None]:
    meta, payload_bytes = _parse_text_bundle(bundle_txt.read_text(encoding="utf-8"))
    split_meta = meta.get("split_bundle") or {}
    if not split_meta.get("enabled"):
        return payload_bytes, None

    part_count = int(split_meta.get("part_count") or 0)
    part_filenames = [str(name) for name in split_meta.get("part_filenames") or ()]
    full_payload_sha256 = str(split_meta.get("full_payload_sha256") or split_meta.get("bundle_id") or "")
    if part_count <= 0 or len(part_filenames) != part_count or not full_payload_sha256:
        raise T01TextBundleError("invalid_split_bundle", "Split bundle metadata is incomplete.")

    chunks: dict[int, bytes] = {}
    for filename in part_filenames:
        part_path = bundle_txt.parent / filename
        if not part_path.is_file():
            raise T01TextBundleError("bundle_part_missing", f"Split bundle part missing: {part_path}")
        part_meta, part_payload = _parse_text_bundle(part_path.read_text(encoding="utf-8"))
        part_split = part_meta.get("split_bundle") or {}
        if str(part_split.get("full_payload_sha256") or part_split.get("bundle_id") or "") != full_payload_sha256:
            raise T01TextBundleError("split_bundle_mismatch", f"Split bundle id mismatch: {part_path}")
        if int(part_split.get("part_count") or 0) != part_count:
            raise T01TextBundleError("split_bundle_mismatch", f"Split bundle part count mismatch: {part_path}")
        part_index = int(part_split.get("part_index") or 0)
        if part_index < 1 or part_index > part_count or part_index in chunks:
            raise T01TextBundleError("invalid_split_bundle", f"Invalid split bundle part index: {part_path}")
        chunks[part_index] = part_payload

    if len(chunks) != part_count:
        raise T01TextBundleError("bundle_part_missing", "Split bundle parts are incomplete.")
    full_payload = b"".join(chunks[index] for index in range(1, part_count + 1))
    if hashlib.sha256(full_payload).hexdigest() != full_payload_sha256:
        raise T01TextBundleError("checksum_mismatch", "Split bundle full payload checksum validation failed.")
    split_report = {
        "enabled": True,
        "part_count": part_count,
        "part_files": [str(bundle_txt.parent / filename) for filename in part_filenames],
        "part_size_bytes": {filename: (bundle_txt.parent / filename).stat().st_size for filename in part_filenames},
        "max_part_size_bytes": max((bundle_txt.parent / filename).stat().st_size for filename in part_filenames),
    }
    return full_payload, split_report


def _extract_and_verify_bundle(bundle_txt: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    payload_bytes, split_report = _bundle_payload_from_text_file(bundle_txt)
    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as zf:
        names = set(zf.namelist())
        for name in names:
            _assert_safe_bundle_name(name)
        files = {name: zf.read(name) for name in names}
    if T01_INTERNAL_MANIFEST_NAME not in files:
        raise T01TextBundleError("bundle_missing_files", f"Bundle is missing {T01_INTERNAL_MANIFEST_NAME}.")
    manifest = json.loads(files[T01_INTERNAL_MANIFEST_NAME])
    if str(manifest.get("bundle_version")) != T01_TEXT_BUNDLE_VERSION:
        raise T01TextBundleError(
            "bundle_version_mismatch",
            f"Unsupported bundle version: {manifest.get('bundle_version')}",
        )
    if str(manifest.get("bundle_type")) not in T01_SUPPORTED_TEXT_BUNDLE_TYPES:
        raise T01TextBundleError("bundle_type_mismatch", f"Unsupported bundle type: {manifest.get('bundle_type')}")
    for name, expected in dict(manifest.get("checksum") or {}).items():
        if name not in files:
            raise T01TextBundleError("bundle_missing_files", f"Bundle is missing checksummed file: {name}")
        if hashlib.sha256(files[name]).hexdigest() != expected:
            raise T01TextBundleError("checksum_mismatch", f"Checksum mismatch for {name}.")
    if split_report is not None and T01_INTERNAL_SIZE_REPORT_NAME in files:
        size_report = json.loads(files[T01_INTERNAL_SIZE_REPORT_NAME])
        size_report["split_bundle"] = split_report
        files[T01_INTERNAL_SIZE_REPORT_NAME] = json.dumps(
            size_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
    return manifest, files


def _restore_localized_vector_file(
    *,
    source_path: Path,
    target_path: Path,
    origin_x: float,
    origin_y: float,
) -> None:
    features: list[dict[str, Any]] = []
    with fiona.open(source_path) as src:
        for feature in src:
            geometry_payload = feature.get("geometry")
            geometry = None if geometry_payload is None else translate(shape(geometry_payload), xoff=origin_x, yoff=origin_y)
            features.append({"properties": dict(feature.get("properties") or {}), "geometry": geometry})
    write_vector(target_path, features, layer_name=target_path.stem)


def run_t01_decode_text_bundle(
    *,
    bundle_txt: str | Path,
    out_dir: str | Path | None = None,
) -> T01TextBundleDecodeArtifacts:
    bundle_path = Path(bundle_txt)
    if not bundle_path.is_file():
        raise T01TextBundleError("bundle_not_found", f"Bundle text file does not exist: {bundle_path}")
    out_dir_path = Path(out_dir) if out_dir is not None else bundle_path.with_suffix("")
    out_dir_path.mkdir(parents=True, exist_ok=True)
    manifest, files = _extract_and_verify_bundle(bundle_path)
    if str(manifest.get("bundle_type")) == T01_INPUT_TEXT_BUNDLE_TYPE:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for name, content in files.items():
                temp_path = temp_root / _assert_safe_bundle_name(name)
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path.write_bytes(content)
            origin = dict((manifest.get("selection") or {}).get("local_origin") or {})
            origin_x = float(origin.get("x", 0.0))
            origin_y = float(origin.get("y", 0.0))
            _restore_localized_vector_file(
                source_path=temp_root / "nodes.gpkg",
                target_path=out_dir_path / "nodes.gpkg",
                origin_x=origin_x,
                origin_y=origin_y,
            )
            _restore_localized_vector_file(
                source_path=temp_root / "roads.gpkg",
                target_path=out_dir_path / "roads.gpkg",
                origin_x=origin_x,
                origin_y=origin_y,
            )
            for name, content in files.items():
                if name in {"nodes.gpkg", "roads.gpkg"}:
                    continue
                target_path = out_dir_path / _assert_safe_bundle_name(name)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(content)
        manifest["decoded_output"] = {
            "decoded_at": _now_text(),
            "out_dir": str(out_dir_path.resolve()),
            "vector_coordinates": "absolute_epsg3857",
            "bundle_internal_vectors_localized": True,
        }
        manifest_path = out_dir_path / T01_INTERNAL_MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return T01TextBundleDecodeArtifacts(success=True, out_dir=out_dir_path, manifest_path=manifest_path)

    for name, content in files.items():
        target_path = out_dir_path / _assert_safe_bundle_name(name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
    manifest["decoded_output"] = {
        "decoded_at": _now_text(),
        "out_dir": str(out_dir_path.resolve()),
    }
    manifest_path = out_dir_path / T01_INTERNAL_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return T01TextBundleDecodeArtifacts(success=True, out_dir=out_dir_path, manifest_path=manifest_path)


def _build_export_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t01-export-text-bundle-dev")
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--out-txt")
    parser.add_argument("--mode", choices=("current", "baseline"), default="current")
    parser.add_argument("--include-vectors", action="store_true")
    parser.add_argument("--include-stage-segment-roads", action="store_true")
    parser.add_argument("--extra-path", action="append", default=[])
    return parser


def _build_decode_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t01-decode-text-bundle-dev")
    parser.add_argument("--bundle-txt", required=True)
    parser.add_argument("--out-dir")
    return parser


def _build_input_export_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t01-export-input-text-bundle-dev")
    parser.add_argument("--node-path", required=True)
    parser.add_argument("--road-path", required=True)
    parser.add_argument("--out-txt", required=True)
    parser.add_argument("--node-layer")
    parser.add_argument("--road-layer")
    parser.add_argument("--node-crs")
    parser.add_argument("--road-crs")
    parser.add_argument("--center-x", required=True, type=float)
    parser.add_argument("--center-y", required=True, type=float)
    parser.add_argument("--profile-id", default=T01_INPUT_DEFAULT_PROFILE_ID)
    parser.add_argument("--profile-config-path")
    parser.add_argument("--max-text-size-bytes", type=int, default=T01_INPUT_TEXT_BUNDLE_LIMIT_BYTES)
    return parser


def run_t01_export_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_export_arg_parser().parse_args(argv)
    artifacts = run_t01_export_text_bundle(
        bundle_root=args.bundle_root,
        out_txt=args.out_txt,
        mode=args.mode,
        include_vectors=args.include_vectors,
        include_stage_segment_roads=args.include_stage_segment_roads,
        extra_relative_paths=tuple(args.extra_path or ()),
    )
    if not artifacts.success:
        print(f"T01 text bundle export failed: {artifacts.failure_detail}", file=sys.stderr)
        if artifacts.size_report_path is not None:
            print(f"size_report={artifacts.size_report_path}", file=sys.stderr)
        return 1
    print(f"T01 text bundle written to: {artifacts.bundle_txt_path}")
    print(f"bundle_size_bytes={artifacts.bundle_size_bytes}")
    print(f"included_file_count={artifacts.included_file_count}")
    if artifacts.size_report_path is not None:
        print(f"size_report={artifacts.size_report_path}")
    return 0


def run_t01_export_input_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_input_export_arg_parser().parse_args(argv)
    artifacts = run_t01_export_input_text_bundle(
        node_path=args.node_path,
        road_path=args.road_path,
        out_txt=args.out_txt,
        center_x=args.center_x,
        center_y=args.center_y,
        node_layer=args.node_layer,
        road_layer=args.road_layer,
        node_crs=args.node_crs,
        road_crs=args.road_crs,
        profile_id=args.profile_id,
        profile_config_path=args.profile_config_path,
        max_text_size_bytes=args.max_text_size_bytes,
    )
    if not artifacts.success:
        print(f"T01 input text bundle export failed: {artifacts.failure_detail}", file=sys.stderr)
        if artifacts.size_report_path is not None:
            print(f"size_report={artifacts.size_report_path}", file=sys.stderr)
        return 1
    print(f"T01 input text bundle written to: {artifacts.bundle_txt_path}")
    print(f"bundle_size_bytes={artifacts.bundle_size_bytes}")
    print(f"included_file_count={artifacts.included_file_count}")
    if artifacts.part_txt_paths:
        print(f"bundle_part_count={len(artifacts.part_txt_paths)}")
        print(f"max_part_size_bytes={artifacts.max_part_size_bytes}")
        for path in artifacts.part_txt_paths:
            print(f"bundle_part={path}")
    if artifacts.selected_profile_id is not None:
        print(f"selected_profile_id={artifacts.selected_profile_id}")
    if artifacts.selected_core_node_count is not None:
        print(f"selected_core_node_count={artifacts.selected_core_node_count}")
    if artifacts.size_report_path is not None:
        print(f"size_report={artifacts.size_report_path}")
    return 0


def run_t01_decode_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_decode_arg_parser().parse_args(argv)
    artifacts = run_t01_decode_text_bundle(bundle_txt=args.bundle_txt, out_dir=args.out_dir)
    print(f"T01 text bundle decoded to: {artifacts.out_dir}")
    print(f"manifest={artifacts.manifest_path}")
    return 0
