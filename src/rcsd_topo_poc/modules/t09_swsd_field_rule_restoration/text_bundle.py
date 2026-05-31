from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from shapely.geometry import box, mapping
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    VectorFeature,
    read_vector,
    resolve_case_insensitive_field_name,
)


T09_TEXT_BUNDLE_VERSION = "1"
T09_TEXT_BUNDLE_TYPE = "t09_swsd_field_rule_restoration_evidence"
T09_TEXT_BUNDLE_BEGIN = "BEGIN_T09_SWSD_FIELD_RULE_RESTORATION_BUNDLE"
T09_TEXT_BUNDLE_PAYLOAD = "payload:"
T09_TEXT_BUNDLE_META = "meta: "
T09_TEXT_BUNDLE_CHECKSUM = "checksum: "
T09_TEXT_BUNDLE_END = "END_T09_SWSD_FIELD_RULE_RESTORATION_BUNDLE"
T09_TEXT_BUNDLE_LINE_WIDTH = 120
T09_TEXT_BUNDLE_LIMIT_BYTES = 250 * 1024

T09_STEP3_INPUT_SLICE_BUNDLE_NAME = "t09_step3_input_slice_bundle.txt"
T09_STEP3_INPUT_SLICE_SIZE_REPORT_NAME = "t09_step3_input_slice_bundle_size_report.json"
T09_INTERNAL_MANIFEST_NAME = "t09_evidence_manifest.json"
T09_INTERNAL_SIZE_REPORT_NAME = "t09_evidence_size_report.json"
T09_STEP3_INPUT_MANIFEST_NAME = "t09_step3_input_manifest.json"
T09_STEP3_INPUT_SLICE_SUMMARY_NAME = "t09_step3_input_slice_summary.json"
T09_LOCAL_TESTCASE_MANIFEST_NAME = "t09_local_testcase_manifest.json"
T09_LOCAL_TESTCASE_PY_NAME = "test_t09_decoded_bundle.py"

T06_STEP3_FRCSD_ROAD_NAME = "t06_frcsd_road.gpkg"
T06_STEP3_FRCSD_NODE_NAME = "t06_frcsd_node.gpkg"
T06_STEP3_REPLACEMENT_UNITS_NAME = "t06_step3_replacement_units.gpkg"
T06_STEP3_JUNCTION_REBUILD_AUDIT_NAME = "t06_step3_junction_rebuild_audit.gpkg"
T06_STEP3_ID_COLLISION_AUDIT_NAME = "t06_step3_id_collision_audit.gpkg"
T06_STEP3_SUMMARY_NAME = "t06_step3_summary.json"

PROCESS_CRS_TEXT = "EPSG:3857"


class T09TextBundleError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class T09TextBundleExportArtifacts:
    success: bool
    bundle_txt_path: Path
    size_report_path: Path | None
    bundle_size_bytes: int
    included_file_count: int = 0
    failure_reason: str | None = None
    failure_detail: str | None = None
    part_txt_paths: tuple[Path, ...] = ()
    max_part_size_bytes: int = 0


@dataclass(frozen=True)
class T09TextBundleDecodeArtifacts:
    success: bool
    out_dir: Path
    manifest_path: Path


def run_t09_export_step3_input_text_bundle(
    *,
    swnode_path: str | Path,
    swroad_path: str | Path,
    frcsd_road_path: str | Path | None = None,
    frcsd_node_path: str | Path | None = None,
    segment_path: str | Path | None = None,
    restriction_path: str | Path | None = None,
    arrow_path: str | Path | None = None,
    t06_step3_root: str | Path | None = None,
    replacement_units_path: str | Path | None = None,
    junction_rebuild_audit_path: str | Path | None = None,
    id_collision_audit_path: str | Path | None = None,
    step3_summary_path: str | Path | None = None,
    out_txt: str | Path | None = None,
    out_dir: str | Path | None = None,
    center_x: float,
    center_y: float,
    size_m: float | None = None,
    radius_m: float | None = None,
    swnode_layer: str | None = None,
    swroad_layer: str | None = None,
    segment_layer: str | None = None,
    restriction_layer: str | None = None,
    arrow_layer: str | None = None,
    frcsd_road_layer: str | None = None,
    frcsd_node_layer: str | None = None,
    replacement_units_layer: str | None = None,
    junction_rebuild_audit_layer: str | None = None,
    id_collision_audit_layer: str | None = None,
    target_epsg: int = 3857,
    include_raw_inputs: bool = False,
    max_text_size_bytes: int = T09_TEXT_BUNDLE_LIMIT_BYTES,
) -> T09TextBundleExportArtifacts:
    out_txt_path = _resolve_out_txt(out_txt=out_txt, out_dir=out_dir)
    size_report_path = out_txt_path.with_name(T09_STEP3_INPUT_SLICE_SIZE_REPORT_NAME)
    try:
        t06_root = Path(t06_step3_root) if t06_step3_root is not None else None
        resolved_frcsd_road = _resolve_required_step3_file(
            explicit_path=frcsd_road_path,
            t06_step3_root=t06_root,
            filename=T06_STEP3_FRCSD_ROAD_NAME,
            label="FRCSD road",
        )
        resolved_frcsd_node = _resolve_required_step3_file(
            explicit_path=frcsd_node_path,
            t06_step3_root=t06_root,
            filename=T06_STEP3_FRCSD_NODE_NAME,
            label="FRCSD node",
        )
        optional_paths = {
            "segment_path": _optional_file(segment_path),
            "restriction_path": _optional_file(restriction_path),
            "arrow_path": _optional_file(arrow_path),
            "replacement_units_path": _resolve_optional_step3_file(
                explicit_path=replacement_units_path,
                t06_step3_root=t06_root,
                filename=T06_STEP3_REPLACEMENT_UNITS_NAME,
            ),
            "junction_rebuild_audit_path": _resolve_optional_step3_file(
                explicit_path=junction_rebuild_audit_path,
                t06_step3_root=t06_root,
                filename=T06_STEP3_JUNCTION_REBUILD_AUDIT_NAME,
            ),
            "id_collision_audit_path": _resolve_optional_step3_file(
                explicit_path=id_collision_audit_path,
                t06_step3_root=t06_root,
                filename=T06_STEP3_ID_COLLISION_AUDIT_NAME,
            ),
            "step3_summary_path": _resolve_optional_step3_file(
                explicit_path=step3_summary_path,
                t06_step3_root=t06_root,
                filename=T06_STEP3_SUMMARY_NAME,
            ),
        }
        required_paths = {
            "swnode_path": _require_file(swnode_path),
            "swroad_path": _require_file(swroad_path),
            "frcsd_road_path": resolved_frcsd_road,
            "frcsd_node_path": resolved_frcsd_node,
        }
        files, slice_summary = _select_t09_step3_input_slice(
            swnode_path=required_paths["swnode_path"],
            swroad_path=required_paths["swroad_path"],
            segment_path=optional_paths["segment_path"],
            restriction_path=optional_paths["restriction_path"],
            arrow_path=optional_paths["arrow_path"],
            frcsd_road_path=resolved_frcsd_road,
            frcsd_node_path=resolved_frcsd_node,
            replacement_units_path=optional_paths["replacement_units_path"],
            junction_rebuild_audit_path=optional_paths["junction_rebuild_audit_path"],
            id_collision_audit_path=optional_paths["id_collision_audit_path"],
            center_x=center_x,
            center_y=center_y,
            size_m=size_m,
            radius_m=radius_m,
            swnode_layer=swnode_layer,
            swroad_layer=swroad_layer,
            segment_layer=segment_layer,
            restriction_layer=restriction_layer,
            arrow_layer=arrow_layer,
            frcsd_road_layer=frcsd_road_layer,
            frcsd_node_layer=frcsd_node_layer,
            replacement_units_layer=replacement_units_layer,
            junction_rebuild_audit_layer=junction_rebuild_audit_layer,
            id_collision_audit_layer=id_collision_audit_layer,
            target_epsg=target_epsg,
        )
        if optional_paths["step3_summary_path"] is not None:
            files["reference/t06_step3/t06_step3_summary.json"] = optional_paths["step3_summary_path"].read_bytes()

        input_manifest = _input_manifest(
            required_paths=required_paths,
            optional_paths=optional_paths,
            t06_step3_root=t06_root,
            slice_summary=slice_summary,
            target_epsg=target_epsg,
            include_raw_inputs=include_raw_inputs,
            max_text_size_bytes=max_text_size_bytes,
        )
        if include_raw_inputs:
            for key, path in {**required_paths, **optional_paths}.items():
                if path is not None and key != "step3_summary_path":
                    files[f"inputs/{key}/{path.name}"] = path.read_bytes()

        out_txt_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_text, bundle_size_bytes, size_report = _build_step3_input_slice_text_bundle(
            files=files,
            input_manifest=input_manifest,
            slice_summary=slice_summary,
            include_raw_inputs=include_raw_inputs,
            max_text_size_bytes=max_text_size_bytes,
        )
        part_paths, max_part_size_bytes = _write_bundle_outputs(
            out_txt_path=out_txt_path,
            bundle_text=bundle_text,
            size_report=size_report,
            max_text_size_bytes=max_text_size_bytes,
        )
        size_report_path.write_text(
            json.dumps(size_report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return T09TextBundleExportArtifacts(
            success=True,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path,
            bundle_size_bytes=bundle_size_bytes,
            included_file_count=int(size_report.get("included_file_count") or 0),
            part_txt_paths=part_paths,
            max_part_size_bytes=max_part_size_bytes,
        )
    except Exception as exc:
        reason = getattr(exc, "reason", "bundle_export_failed")
        detail = getattr(exc, "detail", str(exc))
        return T09TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            failure_reason=reason,
            failure_detail=detail,
        )


def run_t09_decode_text_bundle(
    *,
    bundle_txt: str | Path,
    out_dir: str | Path | None = None,
) -> T09TextBundleDecodeArtifacts:
    bundle_path = Path(bundle_txt)
    if not bundle_path.is_file():
        raise T09TextBundleError("bundle_not_found", f"Bundle text file does not exist: {bundle_path}")
    out_dir_path = Path(out_dir) if out_dir is not None else bundle_path.with_suffix("")
    out_dir_path.mkdir(parents=True, exist_ok=True)
    manifest, files = _extract_and_verify_bundle(bundle_path)
    for name, content in files.items():
        target_path = out_dir_path / _assert_safe_bundle_name(name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
    manifest["decoded_output"] = {"decoded_at": _now_text(), "out_dir": str(out_dir_path.resolve())}
    manifest_path = out_dir_path / T09_INTERNAL_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return T09TextBundleDecodeArtifacts(success=True, out_dir=out_dir_path, manifest_path=manifest_path)


def _select_t09_step3_input_slice(
    *,
    swnode_path: Path,
    swroad_path: Path,
    segment_path: Path | None,
    restriction_path: Path | None,
    arrow_path: Path | None,
    frcsd_road_path: Path,
    frcsd_node_path: Path,
    replacement_units_path: Path | None,
    junction_rebuild_audit_path: Path | None,
    id_collision_audit_path: Path | None,
    center_x: float,
    center_y: float,
    size_m: float | None,
    radius_m: float | None,
    swnode_layer: str | None,
    swroad_layer: str | None,
    segment_layer: str | None,
    restriction_layer: str | None,
    arrow_layer: str | None,
    frcsd_road_layer: str | None,
    frcsd_node_layer: str | None,
    replacement_units_layer: str | None,
    junction_rebuild_audit_layer: str | None,
    id_collision_audit_layer: str | None,
    target_epsg: int,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    selected_size_m, selected_radius_m = _resolve_slice_size(size_m=size_m, radius_m=radius_m)
    window = box(
        float(center_x) - selected_radius_m,
        float(center_y) - selected_radius_m,
        float(center_x) + selected_radius_m,
        float(center_y) + selected_radius_m,
    )
    crs_text = f"EPSG:{target_epsg}"

    swsd_nodes = _read_feature_dicts(swnode_path, layer_name=swnode_layer, target_epsg=target_epsg)
    swsd_roads = _read_feature_dicts(swroad_path, layer_name=swroad_layer, target_epsg=target_epsg)
    segments = (
        _read_feature_dicts(segment_path, layer_name=segment_layer, target_epsg=target_epsg)
        if segment_path is not None
        else []
    )
    restrictions = (
        _read_feature_dicts(restriction_path, layer_name=restriction_layer, target_epsg=target_epsg)
        if restriction_path is not None
        else []
    )
    arrows = (
        _read_feature_dicts(arrow_path, layer_name=arrow_layer, target_epsg=target_epsg)
        if arrow_path is not None
        else []
    )
    frcsd_roads = _read_feature_dicts(frcsd_road_path, layer_name=frcsd_road_layer, target_epsg=target_epsg)
    frcsd_nodes = _read_feature_dicts(frcsd_node_path, layer_name=frcsd_node_layer, target_epsg=target_epsg)

    selected_segments = [feature for feature in segments if _intersects_window(feature, window)]
    selected_segment_ids = _ids_from_features(selected_segments)
    required_swsd_road_ids: list[str] = []
    required_swsd_node_ids: list[str] = []
    for feature in selected_segments:
        props = feature.get("properties") or {}
        required_swsd_road_ids.extend(_parse_id_list(_case_prop(props, ("roads", "road_ids", "swsd_road_ids"))))
        required_swsd_node_ids.extend(_parse_id_list(_case_prop(props, ("pair_nodes", "swsd_pair_nodes"))))
        required_swsd_node_ids.extend(_parse_id_list(_case_prop(props, ("junc_nodes", "swsd_junc_nodes"))))
    required_swsd_road_ids = _unique_preserve_order(required_swsd_road_ids)
    selected_swsd_roads = _select_swsd_roads(swsd_roads, window, set(required_swsd_road_ids))
    selected_swsd_road_ids = _ids_from_features(selected_swsd_roads, candidates=("id", "linkid", "LinkID"))
    required_swsd_node_ids.extend(
        node_id for feature in selected_swsd_roads for node_id in _road_endpoint_ids(feature.get("properties") or {})
    )
    required_swsd_node_ids = _unique_preserve_order(required_swsd_node_ids)
    selected_swsd_nodes = _select_nodes(swsd_nodes, window, set(required_swsd_node_ids))

    selected_frcsd_nodes, selected_frcsd_roads = _select_frcsd_features(
        frcsd_nodes=frcsd_nodes,
        frcsd_roads=frcsd_roads,
        window=window,
    )
    selected_frcsd_node_ids = _ids_from_features(selected_frcsd_nodes)
    selected_frcsd_road_ids = _ids_from_features(selected_frcsd_roads, candidates=("id", "linkid", "LinkID"))

    selected_restrictions = _select_restrictions(restrictions, window, set(selected_swsd_road_ids))
    selected_arrows = _select_arrows(arrows, window, set(selected_swsd_road_ids))

    files = {
        "slice/swsd/nodes.geojson": _feature_collection_bytes("swsd_nodes", selected_swsd_nodes, crs_text=crs_text),
        "slice/swsd/roads.geojson": _feature_collection_bytes("swsd_roads", selected_swsd_roads, crs_text=crs_text),
        "slice/frcsd/frcsd_road.geojson": _feature_collection_bytes(
            "frcsd_road",
            selected_frcsd_roads,
            crs_text=crs_text,
        ),
        "slice/frcsd/frcsd_node.geojson": _feature_collection_bytes(
            "frcsd_node",
            selected_frcsd_nodes,
            crs_text=crs_text,
        ),
    }
    if segment_path is not None:
        files["slice/swsd/segment.geojson"] = _feature_collection_bytes("segment", selected_segments, crs_text=crs_text)
    if restriction_path is not None:
        files["slice/t08_tool7/sw_restriction_tool7.geojson"] = _feature_collection_bytes(
            "sw_restriction_tool7",
            selected_restrictions,
            crs_text=crs_text,
        )
    if arrow_path is not None:
        files["slice/t08_tool8/sw_arrow_tool8.geojson"] = _feature_collection_bytes(
            "sw_arrow_tool8",
            selected_arrows,
            crs_text=crs_text,
        )

    optional_vector_outputs: dict[str, tuple[Path | None, str | None, str]] = {
        "slice/t06_step3/t06_step3_replacement_units.geojson": (
            replacement_units_path,
            replacement_units_layer,
            "t06_step3_replacement_units",
        ),
        "slice/t06_step3/t06_step3_junction_rebuild_audit.geojson": (
            junction_rebuild_audit_path,
            junction_rebuild_audit_layer,
            "t06_step3_junction_rebuild_audit",
        ),
        "slice/t06_step3/t06_step3_id_collision_audit.geojson": (
            id_collision_audit_path,
            id_collision_audit_layer,
            "t06_step3_id_collision_audit",
        ),
    }
    optional_counts: dict[str, int] = {}
    for archive_name, (path, layer_name, output_name) in optional_vector_outputs.items():
        if path is None:
            continue
        features = _read_feature_dicts(path, layer_name=layer_name, target_epsg=target_epsg)
        selected = [feature for feature in features if _intersects_window(feature, window)]
        files[archive_name] = _feature_collection_bytes(output_name, selected, crs_text=crs_text)
        optional_counts[output_name] = len(selected)

    summary = {
        "selection_mode": "centered_square_window",
        "crs_normalized_to": crs_text,
        "center": {"x": float(center_x), "y": float(center_y)},
        "size_m": selected_size_m,
        "radius_m": selected_radius_m,
        "bounds": {
            "minx": float(window.bounds[0]),
            "miny": float(window.bounds[1]),
            "maxx": float(window.bounds[2]),
            "maxy": float(window.bounds[3]),
        },
        "selected_swsd_segment_count": len(selected_segments),
        "selected_swsd_road_count": len(selected_swsd_roads),
        "selected_swsd_node_count": len(selected_swsd_nodes),
        "selected_restriction_count": len(selected_restrictions),
        "selected_arrow_count": len(selected_arrows),
        "selected_frcsd_road_count": len(selected_frcsd_roads),
        "selected_frcsd_node_count": len(selected_frcsd_nodes),
        "selected_t06_step3_optional_counts": optional_counts,
        "selected_swsd_segment_ids": selected_segment_ids,
        "selected_swsd_road_ids": selected_swsd_road_ids,
        "required_swsd_road_ids_from_segment": required_swsd_road_ids,
        "required_swsd_node_ids": required_swsd_node_ids,
        "selected_frcsd_road_ids": selected_frcsd_road_ids,
        "selected_frcsd_node_ids": selected_frcsd_node_ids,
        "source_paths": {
            "swnode_path": str(swnode_path),
            "swroad_path": str(swroad_path),
            "segment_path": str(segment_path) if segment_path is not None else None,
            "restriction_path": str(restriction_path) if restriction_path is not None else None,
            "arrow_path": str(arrow_path) if arrow_path is not None else None,
            "frcsd_road_path": str(frcsd_road_path),
            "frcsd_node_path": str(frcsd_node_path),
            "replacement_units_path": str(replacement_units_path) if replacement_units_path is not None else None,
            "junction_rebuild_audit_path": (
                str(junction_rebuild_audit_path) if junction_rebuild_audit_path is not None else None
            ),
            "id_collision_audit_path": str(id_collision_audit_path) if id_collision_audit_path is not None else None,
        },
        "qa": {
            "crs_transform_executed": "all vector inputs were read through vector_io with target EPSG",
            "topology_silent_fix": False,
            "geometry_semantics": "features are retained when their geometry intersects the window; SWSD and FRCSD road/node dependencies are retained by explicit endpoint ids",
            "audit_traceability": "input paths, file hashes, selection bounds, selected ids and part sizes are written to bundle audit files",
            "performance_verifiable": "input and selected feature counts are recorded in the slice summary",
        },
    }
    files[f"slice/{T09_STEP3_INPUT_SLICE_SUMMARY_NAME}"] = json.dumps(
        summary,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return files, summary


def _build_step3_input_slice_text_bundle(
    *,
    files: dict[str, bytes],
    input_manifest: dict[str, Any],
    slice_summary: dict[str, Any],
    include_raw_inputs: bool,
    max_text_size_bytes: int,
) -> tuple[str, int, dict[str, Any]]:
    files[f"local_testcase/{T09_LOCAL_TESTCASE_PY_NAME}"] = _local_testcase_py_bytes()
    files[f"audit/{T09_STEP3_INPUT_MANIFEST_NAME}"] = json.dumps(
        input_manifest,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    files[f"audit/{T09_LOCAL_TESTCASE_MANIFEST_NAME}"] = json.dumps(
        _local_testcase_manifest(
            files=files,
            input_manifest=input_manifest,
            slice_summary=slice_summary,
        ),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    manifest = {
        "bundle_version": T09_TEXT_BUNDLE_VERSION,
        "bundle_type": T09_TEXT_BUNDLE_TYPE,
        "input_manifest": input_manifest,
        "input_slice_summary": slice_summary,
        "file_list": sorted(set(files).union({T09_INTERNAL_MANIFEST_NAME, T09_INTERNAL_SIZE_REPORT_NAME})),
        "checksum": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())},
        "encoder_info": {
            "archive_format": "zip",
            "compression": "deflate",
            "text_encoding": "base85",
            "line_width": T09_TEXT_BUNDLE_LINE_WIDTH,
            "max_text_size_bytes": max_text_size_bytes,
            "selection": "t09-step3-input-centered-spatial-slice",
            "include_raw_inputs": include_raw_inputs,
        },
        "created_at": _now_text(),
    }

    size_report: dict[str, Any] = {}
    bundle_text = ""
    bundle_size_bytes = 0
    for _ in range(4):
        files[T09_INTERNAL_MANIFEST_NAME] = json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        files[T09_INTERNAL_SIZE_REPORT_NAME] = json.dumps(
            size_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        payload_bytes, per_file_compressed = _zip_bytes(files)
        meta = {
            "bundle_version": T09_TEXT_BUNDLE_VERSION,
            "bundle_type": T09_TEXT_BUNDLE_TYPE,
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
            include_raw_inputs=include_raw_inputs,
            max_text_size_bytes=max_text_size_bytes,
        )
        if next_report == size_report:
            break
        size_report = next_report
    return bundle_text, bundle_size_bytes, size_report


def _build_bundle_text(*, meta: dict[str, Any], payload_bytes: bytes) -> tuple[str, int]:
    payload_text = base64.b85encode(payload_bytes).decode("ascii")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    lines = [
        T09_TEXT_BUNDLE_BEGIN,
        T09_TEXT_BUNDLE_META + json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        T09_TEXT_BUNDLE_PAYLOAD,
        _wrap_payload_text(payload_text),
        T09_TEXT_BUNDLE_CHECKSUM + checksum,
        T09_TEXT_BUNDLE_END,
        "",
    ]
    text = "\n".join(lines)
    return text, len(text.encode("utf-8"))


def _write_bundle_outputs(
    *,
    out_txt_path: Path,
    bundle_text: str,
    size_report: dict[str, Any],
    max_text_size_bytes: int,
) -> tuple[tuple[Path, ...], int]:
    if max_text_size_bytes <= 0:
        raise T09TextBundleError("invalid_max_text_size", "max_text_size_bytes must be > 0.")
    _remove_existing_bundle_outputs(out_txt_path)
    bundle_size_bytes = len(bundle_text.encode("utf-8"))
    size_report["within_limit"] = bundle_size_bytes <= max_text_size_bytes
    size_report["limit_bytes"] = max_text_size_bytes
    if bundle_size_bytes <= max_text_size_bytes:
        out_txt_path.write_text(bundle_text, encoding="utf-8")
        size_report["split_bundle"] = {"enabled": False, "part_count": 1, "part_files": [str(out_txt_path)]}
        return (out_txt_path,), bundle_size_bytes

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


def _split_payload_bundle_texts(
    *,
    out_txt: Path,
    meta: dict[str, Any],
    payload_bytes: bytes,
    max_text_size_bytes: int,
) -> tuple[tuple[Path, str, int], ...]:
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
        if max(size for _path, _text, size in parts) <= max_text_size_bytes:
            best = parts
            low = mid + 1
        else:
            high = mid - 1
    if best is None:
        raise T09TextBundleError(
            "bundle_part_too_large",
            f"Bundle part metadata cannot fit limit {max_text_size_bytes}.",
        )
    return best


def _parse_text_bundle(bundle_text: str) -> tuple[dict[str, Any], bytes]:
    lines = bundle_text.splitlines()
    if not lines or lines[0].strip() != T09_TEXT_BUNDLE_BEGIN:
        raise T09TextBundleError("invalid_bundle_format", "Bundle header not found.")
    try:
        meta_index = next(index for index, line in enumerate(lines) if line.startswith(T09_TEXT_BUNDLE_META))
        payload_index = next(index for index, line in enumerate(lines) if line.strip() == T09_TEXT_BUNDLE_PAYLOAD)
        checksum_index = next(index for index, line in enumerate(lines) if line.startswith(T09_TEXT_BUNDLE_CHECKSUM))
        end_index = next(index for index, line in enumerate(lines) if line.strip() == T09_TEXT_BUNDLE_END)
    except StopIteration as exc:
        raise T09TextBundleError("invalid_bundle_format", "Bundle markers are incomplete.") from exc
    if not (meta_index < payload_index < checksum_index < end_index):
        raise T09TextBundleError("invalid_bundle_format", "Bundle section order is invalid.")

    meta = json.loads(lines[meta_index][len(T09_TEXT_BUNDLE_META) :])
    payload_text = "".join(lines[payload_index + 1 : checksum_index]).strip()
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = lines[checksum_index][len(T09_TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise T09TextBundleError("checksum_mismatch", "Bundle payload checksum validation failed.")
    if str(meta.get("bundle_version")) != T09_TEXT_BUNDLE_VERSION:
        raise T09TextBundleError("bundle_version_mismatch", f"Unsupported bundle version: {meta.get('bundle_version')}")
    if str(meta.get("bundle_type")) != T09_TEXT_BUNDLE_TYPE:
        raise T09TextBundleError("bundle_type_mismatch", f"Unsupported bundle type: {meta.get('bundle_type')}")
    return meta, payload_bytes


def _bundle_payload_from_text_file(bundle_txt: Path) -> tuple[bytes, dict[str, Any] | None]:
    meta, payload_bytes = _parse_text_bundle(bundle_txt.read_text(encoding="utf-8"))
    split_meta = meta.get("split_bundle") or {}
    if not split_meta.get("enabled"):
        if hashlib.sha256(payload_bytes).hexdigest() != str(meta.get("payload_sha256")):
            raise T09TextBundleError("checksum_mismatch", "Payload sha256 metadata does not match.")
        return payload_bytes, None

    part_count = int(split_meta.get("part_count") or 0)
    part_filenames = [str(name) for name in split_meta.get("part_filenames") or ()]
    full_payload_sha256 = str(split_meta.get("full_payload_sha256") or split_meta.get("bundle_id") or "")
    if part_count <= 0 or len(part_filenames) != part_count or not full_payload_sha256:
        raise T09TextBundleError("invalid_split_bundle", "Split bundle metadata is incomplete.")

    chunks: dict[int, bytes] = {}
    for filename in part_filenames:
        part_path = bundle_txt.parent / filename
        if not part_path.is_file():
            raise T09TextBundleError("bundle_part_missing", f"Split bundle part missing: {part_path}")
        part_meta, part_payload = _parse_text_bundle(part_path.read_text(encoding="utf-8"))
        part_split = part_meta.get("split_bundle") or {}
        if str(part_split.get("full_payload_sha256") or part_split.get("bundle_id") or "") != full_payload_sha256:
            raise T09TextBundleError("split_bundle_mismatch", f"Split bundle id mismatch: {part_path}")
        if int(part_split.get("part_count") or 0) != part_count:
            raise T09TextBundleError("split_bundle_mismatch", f"Split bundle part count mismatch: {part_path}")
        part_index = int(part_split.get("part_index") or 0)
        if part_index < 1 or part_index > part_count or part_index in chunks:
            raise T09TextBundleError("invalid_split_bundle", f"Invalid split bundle part index: {part_path}")
        chunks[part_index] = part_payload

    if len(chunks) != part_count:
        raise T09TextBundleError("bundle_part_missing", "Split bundle parts are incomplete.")
    full_payload = b"".join(chunks[index] for index in range(1, part_count + 1))
    if hashlib.sha256(full_payload).hexdigest() != full_payload_sha256:
        raise T09TextBundleError("checksum_mismatch", "Split bundle full payload checksum validation failed.")
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
    if T09_INTERNAL_MANIFEST_NAME not in files:
        raise T09TextBundleError("bundle_missing_files", f"Bundle is missing {T09_INTERNAL_MANIFEST_NAME}.")
    manifest = json.loads(files[T09_INTERNAL_MANIFEST_NAME])
    if str(manifest.get("bundle_version")) != T09_TEXT_BUNDLE_VERSION:
        raise T09TextBundleError(
            "bundle_version_mismatch",
            f"Unsupported bundle version: {manifest.get('bundle_version')}",
        )
    if str(manifest.get("bundle_type")) != T09_TEXT_BUNDLE_TYPE:
        raise T09TextBundleError("bundle_type_mismatch", f"Unsupported bundle type: {manifest.get('bundle_type')}")
    for name, expected in dict(manifest.get("checksum") or {}).items():
        if name not in files:
            raise T09TextBundleError("bundle_missing_files", f"Bundle is missing checksummed file: {name}")
        if hashlib.sha256(files[name]).hexdigest() != expected:
            raise T09TextBundleError("checksum_mismatch", f"Checksum mismatch for {name}.")
    if split_report is not None and T09_INTERNAL_SIZE_REPORT_NAME in files:
        size_report = json.loads(files[T09_INTERNAL_SIZE_REPORT_NAME])
        size_report["split_bundle"] = split_report
        files[T09_INTERNAL_SIZE_REPORT_NAME] = json.dumps(
            size_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
    return manifest, files


def _build_size_report(
    *,
    bundle_size_bytes: int,
    payload_size_bytes: int,
    per_file_raw_size_bytes: dict[str, int],
    per_file_compressed_size_bytes: dict[str, int],
    include_raw_inputs: bool,
    max_text_size_bytes: int,
) -> dict[str, Any]:
    evidence_file_names = [
        name
        for name in per_file_raw_size_bytes
        if name not in {T09_INTERNAL_MANIFEST_NAME, T09_INTERNAL_SIZE_REPORT_NAME}
    ]
    dominant_size_source = max(evidence_file_names, key=lambda name: per_file_raw_size_bytes[name], default=None)
    return {
        "bundle_version": T09_TEXT_BUNDLE_VERSION,
        "bundle_type": T09_TEXT_BUNDLE_TYPE,
        "total_text_size_bytes": bundle_size_bytes,
        "payload_size_bytes": payload_size_bytes,
        "within_limit": bundle_size_bytes <= max_text_size_bytes,
        "limit_bytes": max_text_size_bytes,
        "included_file_count": len(evidence_file_names),
        "include_raw_inputs": include_raw_inputs,
        "split_bundle": {"enabled": False, "part_count": 1},
        "dominant_size_source": dominant_size_source,
        "per_file_raw_size_bytes": per_file_raw_size_bytes,
        "per_file_compressed_size_bytes": per_file_compressed_size_bytes,
    }


def _zip_bytes(files: dict[str, bytes]) -> tuple[bytes, dict[str, int]]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue()), "r") as zf:
        per_file_compressed = {info.filename: int(info.compress_size) for info in zf.infolist()}
    return buffer.getvalue(), per_file_compressed


def _local_testcase_py_bytes() -> bytes:
    return f'''from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import run_t09_swsd_field_rule_restoration


def _decoded_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _optional_path(root: Path, value: str | None) -> Path | None:
    return root / value if value else None


def test_t09_decoded_bundle_runs_current_module(tmp_path: Path) -> None:
    root = _decoded_root()
    testcase_manifest = json.loads((root / "audit" / "{T09_LOCAL_TESTCASE_MANIFEST_NAME}").read_text(encoding="utf-8"))
    slice_summary = json.loads((root / "slice" / "{T09_STEP3_INPUT_SLICE_SUMMARY_NAME}").read_text(encoding="utf-8"))
    kwargs = testcase_manifest["recommended_t09_step1_step2_kwargs"]

    swnode_path = root / kwargs["swnode_gpkg"]
    swroad_path = root / kwargs["swroad_gpkg"]
    segment_path = _optional_path(root, kwargs.get("segment_gpkg"))
    restriction_path = _optional_path(root, kwargs.get("restriction_gpkg"))
    arrow_path = _optional_path(root, kwargs.get("arrow_gpkg"))

    assert swnode_path.is_file()
    assert swroad_path.is_file()
    assert slice_summary["selected_swsd_node_count"] > 0
    assert slice_summary["selected_swsd_road_count"] > 0
    assert slice_summary["selected_frcsd_node_count"] > 0
    assert slice_summary["selected_frcsd_road_count"] > 0

    result = run_t09_swsd_field_rule_restoration(
        swnode_gpkg=swnode_path,
        swroad_gpkg=swroad_path,
        segment_gpkg=segment_path,
        restriction_gpkg=restriction_path,
        arrow_gpkg=arrow_path,
        output_dir=tmp_path / "t09_output",
        run_id="decoded_bundle_case",
    )

    assert result.artifacts.summary_json.is_file()
    assert result.result.summary["qa"]["topology_silent_fix"] is False
    assert result.result.summary["input_audit"]["nodes"]["kind_2_4_junction_count"] >= 1
'''.encode("utf-8")


def _local_testcase_manifest(
    *,
    files: dict[str, bytes],
    input_manifest: dict[str, Any],
    slice_summary: dict[str, Any],
) -> dict[str, Any]:
    fixture_paths = {
        "swsd_nodes": "slice/swsd/nodes.geojson",
        "swsd_roads": "slice/swsd/roads.geojson",
        "frcsd_road": "slice/frcsd/frcsd_road.geojson",
        "frcsd_node": "slice/frcsd/frcsd_node.geojson",
        "swsd_segment": "slice/swsd/segment.geojson",
        "restriction_tool7": "slice/t08_tool7/sw_restriction_tool7.geojson",
        "arrow_tool8": "slice/t08_tool8/sw_arrow_tool8.geojson",
        "t06_step3_replacement_units": "slice/t06_step3/t06_step3_replacement_units.geojson",
        "t06_step3_junction_rebuild_audit": "slice/t06_step3/t06_step3_junction_rebuild_audit.geojson",
        "t06_step3_id_collision_audit": "slice/t06_step3/t06_step3_id_collision_audit.geojson",
        "t06_step3_summary": "reference/t06_step3/t06_step3_summary.json",
        "slice_summary": f"slice/{T09_STEP3_INPUT_SLICE_SUMMARY_NAME}",
        "input_manifest": f"audit/{T09_STEP3_INPUT_MANIFEST_NAME}",
        "pytest_file": f"local_testcase/{T09_LOCAL_TESTCASE_PY_NAME}",
    }
    existing_fixture_paths = {key: path for key, path in fixture_paths.items() if path in files}
    return {
        "purpose": "small real-data local fixture for T09 Step1/2 and later Step3 FRCSD work",
        "path_semantics": "all fixture paths are relative to the decoded bundle directory",
        "source_input_paths": dict(input_manifest.get("input_paths") or {}),
        "source_input_files": input_manifest.get("input_files"),
        "selection": {
            "mode": slice_summary.get("selection_mode"),
            "center": slice_summary.get("center"),
            "size_m": slice_summary.get("size_m"),
            "radius_m": slice_summary.get("radius_m"),
            "bounds": slice_summary.get("bounds"),
            "crs_normalized_to": slice_summary.get("crs_normalized_to"),
        },
        "fixture_paths": existing_fixture_paths,
        "pytest_command_from_repo_root": (
            ".venv/bin/python -m pytest --rootdir <decoded_bundle_dir> "
            f"<decoded_bundle_dir>/local_testcase/{T09_LOCAL_TESTCASE_PY_NAME} -q"
        ),
        "recommended_t09_step1_step2_kwargs": {
            "swnode_gpkg": existing_fixture_paths.get("swsd_nodes"),
            "swroad_gpkg": existing_fixture_paths.get("swsd_roads"),
            "segment_gpkg": existing_fixture_paths.get("swsd_segment"),
            "restriction_gpkg": existing_fixture_paths.get("restriction_tool7"),
            "arrow_gpkg": existing_fixture_paths.get("arrow_tool8"),
        },
        "recommended_t09_step3_inputs": {
            "frcsd_road_path": existing_fixture_paths.get("frcsd_road"),
            "frcsd_node_path": existing_fixture_paths.get("frcsd_node"),
            "t06_step3_replacement_units_path": existing_fixture_paths.get("t06_step3_replacement_units"),
            "t06_step3_junction_rebuild_audit_path": existing_fixture_paths.get("t06_step3_junction_rebuild_audit"),
            "t06_step3_id_collision_audit_path": existing_fixture_paths.get("t06_step3_id_collision_audit"),
        },
        "handoff": {
            "provide_to_codex": "send every bundle .txt part from the same directory; decoding any part reconstructs the same fixture",
            "no_internal_path_required_after_decode": True,
        },
    }


def _input_manifest(
    *,
    required_paths: dict[str, Path],
    optional_paths: dict[str, Path | None],
    t06_step3_root: Path | None,
    slice_summary: dict[str, Any],
    target_epsg: int,
    include_raw_inputs: bool,
    max_text_size_bytes: int,
) -> dict[str, Any]:
    input_paths = {key: str(path) for key, path in required_paths.items()}
    input_paths.update({key: str(path) for key, path in optional_paths.items() if path is not None})
    return {
        "input_paths": input_paths,
        "input_files": {key: _file_info(path) for key, path in {**required_paths, **optional_paths}.items()},
        "t06_step3_root": str(t06_step3_root) if t06_step3_root is not None else None,
        "params": {
            "target_epsg": target_epsg,
            "include_raw_inputs": include_raw_inputs,
            "max_text_size_bytes": max_text_size_bytes,
        },
        "input_slice": slice_summary,
        "created_at": _now_text(),
    }


def _select_swsd_roads(
    features: Sequence[dict[str, Any]],
    window: BaseGeometry,
    required_road_ids: set[str],
) -> list[dict[str, Any]]:
    selected = []
    for feature in features:
        props = feature.get("properties") or {}
        road_id = _feature_id(props, candidates=("id", "linkid", "LinkID"))
        if road_id in required_road_ids or _intersects_window(feature, window):
            selected.append(feature)
    return selected


def _select_nodes(
    features: Sequence[dict[str, Any]],
    window: BaseGeometry,
    required_node_ids: set[str],
) -> list[dict[str, Any]]:
    selected = []
    for feature in features:
        props = feature.get("properties") or {}
        node_id = _feature_id(props)
        mainnode_id = _mainnode_id(props)
        if node_id in required_node_ids or mainnode_id in required_node_ids or _intersects_window(feature, window):
            selected.append(feature)
    return selected


def _select_frcsd_features(
    *,
    frcsd_nodes: Sequence[dict[str, Any]],
    frcsd_roads: Sequence[dict[str, Any]],
    window: BaseGeometry,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    spatial_nodes = [feature for feature in frcsd_nodes if _intersects_window(feature, window)]
    selected_node_ids = set(_ids_from_features(spatial_nodes))
    selected_roads = [
        feature
        for feature in frcsd_roads
        if _intersects_window(feature, window)
        or any(node_id in selected_node_ids for node_id in _road_endpoint_ids(feature.get("properties") or {}))
    ]
    endpoint_ids = {
        node_id for feature in selected_roads for node_id in _road_endpoint_ids(feature.get("properties") or {})
    }
    selected_node_ids.update(endpoint_ids)
    selected_nodes = _select_nodes(frcsd_nodes, window, selected_node_ids)
    selected_node_ids.update(_ids_from_features(selected_nodes))
    selected_roads = [
        feature
        for feature in frcsd_roads
        if _intersects_window(feature, window)
        or any(node_id in selected_node_ids for node_id in _road_endpoint_ids(feature.get("properties") or {}))
    ]
    return selected_nodes, selected_roads


def _select_restrictions(
    features: Sequence[dict[str, Any]],
    window: BaseGeometry,
    selected_swsd_road_ids: set[str],
) -> list[dict[str, Any]]:
    selected = []
    for feature in features:
        props = feature.get("properties") or {}
        in_link = _normalize_id(_case_prop(props, ("inLinkID", "in_link_id", "in_linkid", "inlinkid")))
        out_link = _normalize_id(_case_prop(props, ("outLinkID", "out_link_id", "out_linkid", "outlinkid")))
        if in_link in selected_swsd_road_ids or out_link in selected_swsd_road_ids or _intersects_window(feature, window):
            selected.append(feature)
    return selected


def _select_arrows(
    features: Sequence[dict[str, Any]],
    window: BaseGeometry,
    selected_swsd_road_ids: set[str],
) -> list[dict[str, Any]]:
    selected = []
    for feature in features:
        props = feature.get("properties") or {}
        road_id = _normalize_id(_case_prop(props, ("linkid", "LinkID", "road_id", "roadid", "id")))
        if road_id in selected_swsd_road_ids or _intersects_window(feature, window):
            selected.append(feature)
    return selected


def _read_feature_dicts(
    path: Path,
    *,
    layer_name: str | None,
    target_epsg: int,
) -> list[dict[str, Any]]:
    result = read_vector(path, layer_name=layer_name, target_epsg=target_epsg)
    return [_vector_feature_to_dict(feature) for feature in result.features]


def _vector_feature_to_dict(feature: VectorFeature) -> dict[str, Any]:
    return {"properties": dict(feature.properties), "geometry": feature.geometry}


def _feature_collection_bytes(
    name: str,
    features: Sequence[dict[str, Any]],
    *,
    crs_text: str,
) -> bytes:
    payload = {
        "type": "FeatureCollection",
        "name": name,
        "crs": {"type": "name", "properties": {"name": crs_text}},
        "features": [
            {
                "type": "Feature",
                "properties": _plain_value(feature.get("properties") or {}),
                "geometry": mapping(feature["geometry"]) if feature.get("geometry") is not None else None,
            }
            for feature in features
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _resolve_slice_size(*, size_m: float | None, radius_m: float | None) -> tuple[float, float]:
    if radius_m is not None:
        if radius_m <= 0:
            raise T09TextBundleError("invalid_radius_m", "radius_m must be > 0.")
        side = float(radius_m) * 2.0
        return side, float(radius_m)
    if size_m is None:
        raise T09TextBundleError("missing_slice_size", "Either size_m or radius_m must be provided.")
    if size_m <= 0:
        raise T09TextBundleError("invalid_size_m", "size_m must be > 0.")
    return float(size_m), float(size_m) / 2.0


def _resolve_out_txt(*, out_txt: str | Path | None, out_dir: str | Path | None) -> Path:
    if out_txt is not None:
        return Path(out_txt)
    if out_dir is not None:
        return Path(out_dir) / T09_STEP3_INPUT_SLICE_BUNDLE_NAME
    return Path(T09_STEP3_INPUT_SLICE_BUNDLE_NAME)


def _resolve_required_step3_file(
    *,
    explicit_path: str | Path | None,
    t06_step3_root: Path | None,
    filename: str,
    label: str,
) -> Path:
    resolved = _resolve_optional_step3_file(
        explicit_path=explicit_path,
        t06_step3_root=t06_step3_root,
        filename=filename,
    )
    if resolved is None:
        raise T09TextBundleError("input_file_missing", f"{label} path is required or missing under t06_step3_root.")
    return resolved


def _resolve_optional_step3_file(
    *,
    explicit_path: str | Path | None,
    t06_step3_root: Path | None,
    filename: str,
) -> Path | None:
    if explicit_path is not None:
        return _require_file(explicit_path)
    if t06_step3_root is None:
        return None
    direct = t06_step3_root / filename
    if direct.is_file():
        return direct
    matches = sorted(t06_step3_root.rglob(filename)) if t06_step3_root.is_dir() else []
    return matches[0] if matches else None


def _require_file(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_file():
        return resolved
    raise T09TextBundleError("input_file_missing", f"Input file does not exist: {resolved}")


def _optional_file(path: str | Path | None) -> Path | None:
    return _require_file(path) if path is not None else None


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


def _assert_safe_bundle_name(name: str) -> str:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise T09TextBundleError("invalid_bundle_path", f"Bundle file path is not safe: {name}")
    return path.as_posix()


def _wrap_payload_text(text: str, *, width: int = T09_TEXT_BUNDLE_LINE_WIDTH) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def _file_info(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.is_file():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "sha256": _sha256_file(path),
        "mtime_ns": stat.st_mtime_ns,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseGeometry):
        return mapping(value)
    return value


def _case_prop(properties: dict[str, Any], candidates: Iterable[str]) -> Any:
    resolved = resolve_case_insensitive_field_name(properties, candidates)
    return properties.get(resolved) if resolved is not None else None


def _feature_id(properties: dict[str, Any], candidates: Iterable[str] = ("id", "nodeid", "node_id")) -> str | None:
    return _normalize_id(_case_prop(properties, candidates))


def _mainnode_id(properties: dict[str, Any]) -> str | None:
    value = _normalize_id(_case_prop(properties, ("mainnodeid", "main_node_id")))
    if value in {None, "", "0", "-1"}:
        return None
    return value


def _road_endpoint_ids(properties: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        item
        for item in (
            _normalize_id(_case_prop(properties, ("snodeid", "snode_id", "startnodeid"))),
            _normalize_id(_case_prop(properties, ("enodeid", "enode_id", "endnodeid"))),
        )
        if item is not None
    )


def _ids_from_features(
    features: Sequence[dict[str, Any]],
    candidates: Iterable[str] = ("id", "nodeid", "node_id"),
) -> list[str]:
    return _unique_preserve_order(
        item
        for item in (_feature_id(feature.get("properties") or {}, candidates=candidates) for feature in features)
        if item is not None
    )


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    text = str(value).strip()
    if not text:
        return None
    return text


def _parse_id_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in (_normalize_id(part) for part in value) if item is not None]
    text = str(value).strip()
    if not text:
        return []
    parsed = _parse_json_list(text)
    if parsed is not None:
        return _parse_id_list(parsed)
    normalized = text.replace("|", ",").replace(";", ",")
    return [item for item in (_normalize_id(part) for part in normalized.split(",")) if item is not None]


def _parse_json_list(text: str) -> Any | None:
    if not ((text.startswith("[") and text.endswith("]")) or (text.startswith("(") and text.endswith(")"))):
        return None
    candidate = "[" + text[1:-1] + "]" if text.startswith("(") else text
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def _intersects_window(feature: dict[str, Any], window: BaseGeometry) -> bool:
    geometry = feature.get("geometry")
    return bool(geometry is not None and geometry.intersects(window))
