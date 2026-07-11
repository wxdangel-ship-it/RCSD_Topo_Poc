from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shlex
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from shapely.geometry import box, mapping
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.io import read_features
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.parsing import (
    ParseError,
    normalize_id,
    parse_id_list,
    parse_positive_int,
    unique_preserve_order,
)

from .schemas import (
    STEP1_CANDIDATES_STEM,
    STEP1_DIR,
    STEP1_FINAL_FUSION_STEM,
    STEP1_REJECTED_STEM,
    STEP1_STATS_CSV,
    STEP1_SUMMARY,
    STEP2_BUFFER_REJECTED_STEM,
    STEP2_BUFFER_SEGMENTS_STEM,
    STEP2_CANDIDATES_STEM,
    STEP2_DIR,
    STEP2_REJECTED_STEM,
    STEP2_REPLACEABLE_STEM,
    STEP2_SUMMARY,
)


T06_TEXT_BUNDLE_VERSION = "1"
T06_TEXT_BUNDLE_TYPE = "t06_segment_fusion_precheck_evidence"
T06_TEXT_BUNDLE_BEGIN = "BEGIN_T06_SEGMENT_FUSION_PRECHECK_BUNDLE"
T06_TEXT_BUNDLE_PAYLOAD = "payload:"
T06_TEXT_BUNDLE_META = "meta: "
T06_TEXT_BUNDLE_CHECKSUM = "checksum: "
T06_TEXT_BUNDLE_END = "END_T06_SEGMENT_FUSION_PRECHECK_BUNDLE"
T06_TEXT_BUNDLE_LINE_WIDTH = 120
T06_TEXT_BUNDLE_LIMIT_BYTES = 250 * 1024

T06_TEXT_BUNDLE_NAME = "t06_segment_fusion_precheck_evidence_bundle.txt"
T06_TEXT_BUNDLE_SIZE_REPORT_NAME = "t06_segment_fusion_precheck_evidence_bundle_size_report.json"
T06_INTERNAL_MANIFEST_NAME = "t06_evidence_manifest.json"
T06_INTERNAL_SIZE_REPORT_NAME = "t06_evidence_size_report.json"
T06_INPUT_MANIFEST_NAME = "t06_input_manifest.json"
T06_REPLAY_COMMAND_NAME = "replay_t06_run_innernet_precheck.sh"
T06_LOCAL_REPLAY_PRECHECK_NAME = "replay_t06_decoded_precheck.sh"
T06_LOCAL_REPLAY_STEP3_NAME = "replay_t06_decoded_step3_segment_replacement.sh"
T06_LOCAL_CASE_MANIFEST_NAME = "t06_local_case_manifest.json"
T06_LOCAL_CASE_README_NAME = "README_t06_local_case.md"
T06_INPUT_SLICE_SUMMARY_NAME = "t06_input_slice_summary.json"
T06_INPUT_SLICE_BUNDLE_NAME = "t06_input_slice_bundle.txt"
T06_INPUT_SLICE_SIZE_REPORT_NAME = "t06_input_slice_bundle_size_report.json"

DEFAULT_RUN_ID = "t06_innernet_precheck"
DEFAULT_SWSD_SEGMENT = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg"
DEFAULT_SWSD_ROADS = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg"
DEFAULT_SWSD_NODES = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg"
DEFAULT_T05_PHASE2_ROOT = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet"
DEFAULT_OUT_ROOT = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck"
T06_INPUT_SLICE_PROFILE_RADII_M = {
    "XXXS": 250.0,
    "XXS": 500.0,
    "XS": 1000.0,
    "S": 2000.0,
    "M": 5000.0,
}
T06_INPUT_SLICE_DEFAULT_PROFILE_ID = "XS"
T06_INPUT_SLICE_CRS_TEXT = "EPSG:3857"

_OUTPUT_STEMS_BY_STEP_DIR = {
    STEP1_DIR: (STEP1_CANDIDATES_STEM, STEP1_FINAL_FUSION_STEM, STEP1_REJECTED_STEM),
    STEP2_DIR: (
        STEP2_CANDIDATES_STEM,
        STEP2_REPLACEABLE_STEM,
        STEP2_REJECTED_STEM,
        STEP2_BUFFER_SEGMENTS_STEM,
        STEP2_BUFFER_REJECTED_STEM,
    ),
}
_SUMMARY_BY_STEP_DIR = {
    STEP1_DIR: STEP1_SUMMARY,
    STEP2_DIR: STEP2_SUMMARY,
}
_OUTPUT_FILES_BY_STEP_DIR = {
    STEP1_DIR: (STEP1_STATS_CSV,),
}
_COMPACT_OUTPUT_SUFFIXES = (".json", ".csv")
_VECTOR_OUTPUT_SUFFIXES = (".gpkg",)
_INPUT_ARCHIVE_NAMES = {
    "swsd_segment_path": "inputs/swsd/segment.gpkg",
    "swsd_roads_path": "inputs/swsd/roads.gpkg",
    "swsd_nodes_path": "inputs/swsd/nodes.gpkg",
    "intersection_match_path": "inputs/t05_phase2/intersection_match_all.geojson",
    "rcsdroad_path": "inputs/t05_phase2/rcsdroad_out.gpkg",
    "rcsdnode_path": "inputs/t05_phase2/rcsdnode_out.gpkg",
}


from .text_bundle import (
    T06TextBundleError,
    _dependency_audit,
    _feature_collection_bytes,
    _feature_id,
    _intersects_window,
    _is_status_zero,
    _node_has_identity_in,
    _road_endpoint_ids,
    _safe_normalize_id,
    _safe_parse_id_list,
    _add_file,
    _build_bundle_text,
    _build_decoded_precheck_replay_script,
    _build_decoded_step3_replay_script,
    _build_local_case_manifest,
    _build_local_case_readme,
    _build_replay_command,
    _build_size_report,
    _now_text,
    _zip_bytes,
    _parse_text_bundle,
    _remove_existing_bundle_outputs,
    _split_payload_bundle_texts,
    _write_bundle_text,
)

def _resolve_slice_size_m(*, profile_id: str, size_m: float | None, radius_m: float | None) -> tuple[str, float, float]:
    selected_profile_id = str(profile_id or T06_INPUT_SLICE_DEFAULT_PROFILE_ID).strip().upper()
    if radius_m is not None:
        if radius_m <= 0:
            raise T06TextBundleError("invalid_radius_m", "radius_m must be > 0.")
        selected_radius_m = float(radius_m)
        return selected_profile_id, selected_radius_m * 2.0, selected_radius_m
    if size_m is not None:
        if size_m <= 0:
            raise T06TextBundleError("invalid_size_m", "size_m must be > 0.")
        selected_size_m = float(size_m)
        return selected_profile_id, selected_size_m, selected_size_m / 2.0
    if selected_profile_id not in T06_INPUT_SLICE_PROFILE_RADII_M:
        raise T06TextBundleError("invalid_profile_id", f"Unsupported T06 input slice profile_id: {profile_id}")
    selected_radius_m = T06_INPUT_SLICE_PROFILE_RADII_M[selected_profile_id]
    return selected_profile_id, selected_radius_m * 2.0, selected_radius_m


def _select_t06_input_slice(
    *,
    swsd_segment_path: Path,
    swsd_roads_path: Path,
    swsd_nodes_path: Path,
    intersection_match_path: Path,
    rcsdroad_path: Path,
    rcsdnode_path: Path,
    center_x: float,
    center_y: float,
    profile_id: str,
    size_m: float | None,
    radius_m: float | None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    selected_profile_id, selected_size_m, selected_radius_m = _resolve_slice_size_m(
        profile_id=profile_id,
        size_m=size_m,
        radius_m=radius_m,
    )
    window = box(
        float(center_x) - selected_radius_m,
        float(center_y) - selected_radius_m,
        float(center_x) + selected_radius_m,
        float(center_y) + selected_radius_m,
    )

    swsd_segments = read_features(swsd_segment_path)
    selected_segments = [feature for feature in swsd_segments if _intersects_window(feature, window)]
    selected_segment_ids = [
        segment_id
        for segment_id in (_feature_id(feature.get("properties") or {}) for feature in selected_segments)
        if segment_id is not None
    ]

    required_swsd_road_ids: list[str] = []
    required_swsd_semantic_node_ids: list[str] = []
    for feature in selected_segments:
        properties = feature.get("properties") or {}
        required_swsd_road_ids.extend(_safe_parse_id_list(properties.get("roads")))
        required_swsd_semantic_node_ids.extend(_safe_parse_id_list(properties.get("pair_nodes")))
        required_swsd_semantic_node_ids.extend(_safe_parse_id_list(properties.get("junc_nodes")))
    required_swsd_road_ids = unique_preserve_order(required_swsd_road_ids)
    required_swsd_semantic_node_ids = unique_preserve_order(required_swsd_semantic_node_ids)
    required_road_id_set = set(required_swsd_road_ids)
    required_node_id_set = set(required_swsd_semantic_node_ids)

    swsd_roads = read_features(swsd_roads_path)
    selected_swsd_roads = [
        feature
        for feature in swsd_roads
        if _feature_id(feature.get("properties") or {}) in required_road_id_set or _intersects_window(feature, window)
    ]
    required_swsd_road_endpoint_node_ids = unique_preserve_order(
        node_id for feature in selected_swsd_roads for node_id in _road_endpoint_ids(feature.get("properties") or {})
    )
    required_node_id_set.update(required_swsd_road_endpoint_node_ids)

    swsd_nodes = read_features(swsd_nodes_path)
    selected_swsd_nodes = [
        feature
        for feature in swsd_nodes
        if _node_has_identity_in(feature.get("properties") or {}, required_node_id_set)
        or _intersects_window(feature, window)
    ]

    relation_features = read_features(intersection_match_path, crs_override=T06_INPUT_SLICE_CRS_TEXT)
    selected_relations = []
    mapped_rcsd_semantic_node_ids: list[str] = []
    for feature in relation_features:
        properties = feature.get("properties") or {}
        target_id = _safe_normalize_id(properties.get("target_id"))
        include = target_id in required_node_id_set or _intersects_window(feature, window)
        if not include:
            continue
        selected_relations.append(feature)
        if target_id in required_node_id_set and _is_status_zero(properties.get("status")):
            base_id = parse_positive_int(properties.get("base_id"))
            if base_id is not None:
                mapped_rcsd_semantic_node_ids.append(str(base_id))
    mapped_rcsd_semantic_node_ids = unique_preserve_order(mapped_rcsd_semantic_node_ids)
    mapped_rcsd_node_id_set = set(mapped_rcsd_semantic_node_ids)

    rcsd_nodes = read_features(rcsdnode_path)
    selected_rcsd_nodes = [
        feature
        for feature in rcsd_nodes
        if _node_has_identity_in(feature.get("properties") or {}, mapped_rcsd_node_id_set)
        or _intersects_window(feature, window)
    ]
    selected_rcsd_node_ids = {
        node_id
        for node_id in (_feature_id(feature.get("properties") or {}) for feature in selected_rcsd_nodes)
        if node_id is not None
    }
    selected_rcsd_node_ids.update(mapped_rcsd_node_id_set)

    rcsd_roads = read_features(rcsdroad_path)
    selected_rcsd_roads = []
    for feature in rcsd_roads:
        properties = feature.get("properties") or {}
        snodeid = _safe_normalize_id(properties.get("snodeid"))
        enodeid = _safe_normalize_id(properties.get("enodeid"))
        touches_selected_node = snodeid in selected_rcsd_node_ids or enodeid in selected_rcsd_node_ids
        if touches_selected_node or _intersects_window(feature, window):
            selected_rcsd_roads.append(feature)
    selected_rcsd_road_endpoint_node_ids = unique_preserve_order(
        node_id for feature in selected_rcsd_roads for node_id in _road_endpoint_ids(feature.get("properties") or {})
    )
    selected_rcsd_node_dependency_id_set = set(selected_rcsd_node_ids).union(selected_rcsd_road_endpoint_node_ids)
    selected_rcsd_nodes = [
        feature
        for feature in rcsd_nodes
        if _node_has_identity_in(feature.get("properties") or {}, selected_rcsd_node_dependency_id_set)
        or _intersects_window(feature, window)
    ]
    dependency_audit = _dependency_audit(
        selected_segments=selected_segments,
        selected_swsd_roads=selected_swsd_roads,
        selected_swsd_nodes=selected_swsd_nodes,
        selected_relations=selected_relations,
        selected_rcsd_roads=selected_rcsd_roads,
        selected_rcsd_nodes=selected_rcsd_nodes,
        required_swsd_road_ids=required_swsd_road_ids,
        required_swsd_semantic_node_ids=required_swsd_semantic_node_ids,
        required_swsd_road_endpoint_node_ids=required_swsd_road_endpoint_node_ids,
        mapped_rcsd_semantic_node_ids=mapped_rcsd_semantic_node_ids,
        selected_rcsd_road_endpoint_node_ids=selected_rcsd_road_endpoint_node_ids,
    )

    files = {
        "slice/swsd/segment.geojson": _feature_collection_bytes("segment", selected_segments),
        "slice/swsd/roads.geojson": _feature_collection_bytes("roads", selected_swsd_roads),
        "slice/swsd/nodes.geojson": _feature_collection_bytes("nodes", selected_swsd_nodes),
        "slice/t05_phase2/intersection_match_all.geojson": _feature_collection_bytes(
            "intersection_match_all",
            selected_relations,
        ),
        "slice/t05_phase2/rcsdroad_out.geojson": _feature_collection_bytes("rcsdroad_out", selected_rcsd_roads),
        "slice/t05_phase2/rcsdnode_out.geojson": _feature_collection_bytes("rcsdnode_out", selected_rcsd_nodes),
    }
    summary = {
        "selection_mode": "centered_square_window",
        "crs_normalized_to": T06_INPUT_SLICE_CRS_TEXT,
        "profile_id": selected_profile_id,
        "size_m": selected_size_m,
        "radius_m": selected_radius_m,
        "center_3857": {"x": float(center_x), "y": float(center_y)},
        "bounds_3857": {
            "minx": float(window.bounds[0]),
            "miny": float(window.bounds[1]),
            "maxx": float(window.bounds[2]),
            "maxy": float(window.bounds[3]),
        },
        "source_paths": {
            "swsd_segment_path": str(swsd_segment_path),
            "swsd_roads_path": str(swsd_roads_path),
            "swsd_nodes_path": str(swsd_nodes_path),
            "intersection_match_path": str(intersection_match_path),
            "rcsdroad_path": str(rcsdroad_path),
            "rcsdnode_path": str(rcsdnode_path),
        },
        "selected_swsd_segment_count": len(selected_segments),
        "selected_swsd_road_count": len(selected_swsd_roads),
        "selected_swsd_node_count": len(selected_swsd_nodes),
        "selected_relation_count": len(selected_relations),
        "selected_rcsdroad_count": len(selected_rcsd_roads),
        "selected_rcsdnode_count": len(selected_rcsd_nodes),
        "selected_swsd_segment_ids": selected_segment_ids,
        "required_swsd_road_ids": required_swsd_road_ids,
        "required_swsd_semantic_node_ids": required_swsd_semantic_node_ids,
        "required_swsd_road_endpoint_node_ids": required_swsd_road_endpoint_node_ids,
        "mapped_rcsd_semantic_node_ids": mapped_rcsd_semantic_node_ids,
        "selected_rcsd_road_endpoint_node_ids": selected_rcsd_road_endpoint_node_ids,
        "dependency_audit": dependency_audit,
    }
    files[f"slice/{T06_INPUT_SLICE_SUMMARY_NAME}"] = json.dumps(
        summary,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return files, summary


def _build_input_slice_text_bundle(
    *,
    files: dict[str, bytes],
    input_manifest: dict[str, Any],
    slice_summary: dict[str, Any],
    include_input_files: bool,
    max_text_size_bytes: int,
) -> tuple[str, int, dict[str, Any]]:
    if include_input_files:
        for key, archive_name in _INPUT_ARCHIVE_NAMES.items():
            _add_file(files, archive_name, Path(input_manifest["input_paths"][key]))
    files[f"audit/{T06_INPUT_MANIFEST_NAME}"] = json.dumps(
        input_manifest,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    files[f"audit/{T06_REPLAY_COMMAND_NAME}"] = _build_replay_command(input_manifest).encode("utf-8")
    files[f"audit/{T06_LOCAL_REPLAY_PRECHECK_NAME}"] = _build_decoded_precheck_replay_script(input_manifest).encode(
        "utf-8"
    )
    files[f"audit/{T06_LOCAL_REPLAY_STEP3_NAME}"] = _build_decoded_step3_replay_script().encode("utf-8")
    files[f"audit/{T06_LOCAL_CASE_MANIFEST_NAME}"] = json.dumps(
        _build_local_case_manifest(input_manifest, slice_summary),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    files[T06_LOCAL_CASE_README_NAME] = _build_local_case_readme(slice_summary).encode("utf-8")

    manifest = {
        "bundle_version": T06_TEXT_BUNDLE_VERSION,
        "bundle_type": T06_TEXT_BUNDLE_TYPE,
        "source_run_root": None,
        "input_manifest": input_manifest,
        "input_slice_summary": slice_summary,
        "file_list": sorted(set(files).union({T06_INTERNAL_MANIFEST_NAME, T06_INTERNAL_SIZE_REPORT_NAME})),
        "checksum": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())},
        "encoder_info": {
            "archive_format": "zip",
            "compression": "deflate",
            "text_encoding": "base85",
            "line_width": T06_TEXT_BUNDLE_LINE_WIDTH,
            "max_text_size_bytes": max_text_size_bytes,
            "selection": "t06-input-centered-spatial-slice",
            "include_input_files": include_input_files,
        },
        "created_at": _now_text(),
    }

    size_report: dict[str, Any] = {}
    bundle_text = ""
    bundle_size_bytes = 0
    for _ in range(4):
        files[T06_INTERNAL_MANIFEST_NAME] = json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        files[T06_INTERNAL_SIZE_REPORT_NAME] = json.dumps(
            size_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        payload_bytes, per_file_compressed = _zip_bytes(files)
        meta = {
            "bundle_version": T06_TEXT_BUNDLE_VERSION,
            "bundle_type": T06_TEXT_BUNDLE_TYPE,
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
            skipped_missing_files=[],
            include_output_vectors=False,
            include_input_files=include_input_files,
            max_text_size_bytes=max_text_size_bytes,
        )
        if next_report == size_report:
            break
        size_report = next_report
    return bundle_text, bundle_size_bytes, size_report


def _write_bundle_outputs(
    *,
    out_txt_path: Path,
    bundle_text: str,
    size_report: dict[str, Any],
    max_text_size_bytes: int,
) -> tuple[tuple[Path, ...], int]:
    if max_text_size_bytes <= 0:
        raise T06TextBundleError("invalid_max_text_size", "max_text_size_bytes must be > 0.")
    _remove_existing_bundle_outputs(out_txt_path)
    bundle_size_bytes = len(bundle_text.encode("utf-8"))
    size_report["within_limit"] = bundle_size_bytes <= max_text_size_bytes
    size_report["limit_bytes"] = max_text_size_bytes
    if bundle_size_bytes <= max_text_size_bytes:
        actual_size_bytes = _write_bundle_text(out_txt_path, bundle_text)
        size_report["split_bundle"] = {"enabled": False, "part_count": 1, "part_files": [str(out_txt_path)]}
        return (out_txt_path,), actual_size_bytes

    meta, payload_bytes = _parse_text_bundle(bundle_text)
    parts = _split_payload_bundle_texts(
        out_txt=out_txt_path,
        meta=meta,
        payload_bytes=payload_bytes,
        max_text_size_bytes=max_text_size_bytes,
    )
    actual_part_sizes: dict[str, int] = {}
    for path, text, _size in parts:
        actual_part_sizes[path.name] = _write_bundle_text(path, text)
    split_report = {
        "enabled": True,
        "part_count": len(parts),
        "part_files": [str(path) for path, _text, _size in parts],
        "part_size_bytes": actual_part_sizes,
        "max_part_size_bytes": max(actual_part_sizes.values()),
    }
    size_report["split_bundle"] = split_report
    return tuple(path for path, _text, _size in parts), int(split_report["max_part_size_bytes"])
