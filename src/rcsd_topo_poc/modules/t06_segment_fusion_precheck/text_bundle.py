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


class T06TextBundleError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class T06TextBundleExportArtifacts:
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
class T06TextBundleDecodeArtifacts:
    success: bool
    out_dir: Path
    manifest_path: Path


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _wrap_payload_text(text: str, *, width: int = T06_TEXT_BUNDLE_LINE_WIDTH) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def _build_bundle_text(*, meta: dict[str, Any], payload_bytes: bytes) -> tuple[str, int]:
    payload_text = base64.b85encode(payload_bytes).decode("ascii")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    lines = [
        T06_TEXT_BUNDLE_BEGIN,
        T06_TEXT_BUNDLE_META + json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        T06_TEXT_BUNDLE_PAYLOAD,
        _wrap_payload_text(payload_text),
        T06_TEXT_BUNDLE_CHECKSUM + checksum,
        T06_TEXT_BUNDLE_END,
        "",
    ]
    text = "\n".join(lines)
    return text, len(text.encode("utf-8"))


def _write_bundle_text(path: Path, text: str) -> int:
    payload = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return len(payload)


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
        raise T06TextBundleError("invalid_max_text_size", "max_text_size_bytes must be > 0.")

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
        raise T06TextBundleError(
            "bundle_part_too_large",
            f"Bundle part metadata cannot fit limit {max_text_size_bytes}.",
        )
    return best


def _parse_text_bundle(bundle_text: str) -> tuple[dict[str, Any], bytes]:
    lines = bundle_text.splitlines()
    if not lines or lines[0].strip() != T06_TEXT_BUNDLE_BEGIN:
        raise T06TextBundleError("invalid_bundle_format", "Bundle header not found.")
    try:
        meta_index = next(index for index, line in enumerate(lines) if line.startswith(T06_TEXT_BUNDLE_META))
        payload_index = next(index for index, line in enumerate(lines) if line.strip() == T06_TEXT_BUNDLE_PAYLOAD)
        checksum_index = next(index for index, line in enumerate(lines) if line.startswith(T06_TEXT_BUNDLE_CHECKSUM))
        end_index = next(index for index, line in enumerate(lines) if line.strip() == T06_TEXT_BUNDLE_END)
    except StopIteration as exc:
        raise T06TextBundleError("invalid_bundle_format", "Bundle markers are incomplete.") from exc
    if not (meta_index < payload_index < checksum_index < end_index):
        raise T06TextBundleError("invalid_bundle_format", "Bundle section order is invalid.")

    meta = json.loads(lines[meta_index][len(T06_TEXT_BUNDLE_META) :])
    payload_text = "".join(lines[payload_index + 1 : checksum_index]).strip()
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = lines[checksum_index][len(T06_TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise T06TextBundleError("checksum_mismatch", "Bundle payload checksum validation failed.")
    if str(meta.get("bundle_version")) != T06_TEXT_BUNDLE_VERSION:
        raise T06TextBundleError("bundle_version_mismatch", f"Unsupported bundle version: {meta.get('bundle_version')}")
    if str(meta.get("bundle_type")) != T06_TEXT_BUNDLE_TYPE:
        raise T06TextBundleError("bundle_type_mismatch", f"Unsupported bundle type: {meta.get('bundle_type')}")
    return meta, payload_bytes


def _assert_safe_bundle_name(name: str) -> str:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise T06TextBundleError("invalid_bundle_path", f"Bundle file path is not safe: {name}")
    return path.as_posix()


def _zip_bytes(files: dict[str, bytes]) -> tuple[bytes, dict[str, int]]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue()), "r") as zf:
        per_file_compressed = {info.filename: int(info.compress_size) for info in zf.infolist()}
    return buffer.getvalue(), per_file_compressed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_info(path: Path) -> dict[str, Any]:
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


def _feature_collection_bytes(name: str, features: Sequence[dict[str, Any]]) -> bytes:
    payload = {
        "type": "FeatureCollection",
        "name": name,
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
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


def _safe_normalize_id(value: Any) -> str | None:
    try:
        return normalize_id(value)
    except ParseError:
        return None


def _safe_parse_id_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value)
    except ParseError:
        return []


def _main_or_id(properties: dict[str, Any]) -> str | None:
    mainnodeid = parse_positive_int(properties.get("mainnodeid"))
    if mainnodeid is not None:
        return str(mainnodeid)
    return _safe_normalize_id(properties.get("id"))


def _is_status_zero(value: Any) -> bool:
    try:
        return normalize_id(value) == "0"
    except ParseError:
        return False


def _feature_id(properties: dict[str, Any]) -> str | None:
    return _safe_normalize_id(properties.get("id"))


def _road_endpoint_ids(properties: dict[str, Any]) -> list[str]:
    return [
        node_id
        for node_id in (
            _safe_normalize_id(properties.get("snodeid")),
            _safe_normalize_id(properties.get("enodeid")),
        )
        if node_id is not None
    ]


def _node_identity_ids(properties: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for field in ("id", "mainnodeid"):
        node_id = _safe_normalize_id(properties.get(field))
        if node_id is not None and node_id != "0":
            ids.append(node_id)
    ids.extend(_safe_parse_id_list(properties.get("subnodeid")))
    return unique_preserve_order(ids)


def _node_has_identity_in(properties: dict[str, Any], required_ids: set[str]) -> bool:
    return any(node_id in required_ids for node_id in _node_identity_ids(properties))


def _feature_id_set(features: Sequence[dict[str, Any]]) -> set[str]:
    return {
        feature_id
        for feature_id in (_feature_id(feature.get("properties") or {}) for feature in features)
        if feature_id is not None
    }


def _node_identity_set(features: Sequence[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for feature in features:
        result.update(_node_identity_ids(feature.get("properties") or {}))
    return result


def _relation_target_id_set(features: Sequence[dict[str, Any]]) -> set[str]:
    return {
        target_id
        for target_id in (_safe_normalize_id((feature.get("properties") or {}).get("target_id")) for feature in features)
        if target_id is not None
    }


def _dependency_audit(
    *,
    selected_segments: Sequence[dict[str, Any]],
    selected_swsd_roads: Sequence[dict[str, Any]],
    selected_swsd_nodes: Sequence[dict[str, Any]],
    selected_relations: Sequence[dict[str, Any]],
    selected_rcsd_roads: Sequence[dict[str, Any]],
    selected_rcsd_nodes: Sequence[dict[str, Any]],
    required_swsd_road_ids: Sequence[str],
    required_swsd_semantic_node_ids: Sequence[str],
    required_swsd_road_endpoint_node_ids: Sequence[str],
    mapped_rcsd_semantic_node_ids: Sequence[str],
    selected_rcsd_road_endpoint_node_ids: Sequence[str],
) -> dict[str, Any]:
    selected_swsd_road_ids = _feature_id_set(selected_swsd_roads)
    selected_swsd_node_ids = _node_identity_set(selected_swsd_nodes)
    selected_relation_target_ids = _relation_target_id_set(selected_relations)
    selected_rcsd_road_ids = _feature_id_set(selected_rcsd_roads)
    selected_rcsd_node_ids = _node_identity_set(selected_rcsd_nodes)

    missing_required_swsd_road_ids = [item for item in required_swsd_road_ids if item not in selected_swsd_road_ids]
    missing_required_swsd_semantic_node_ids = [
        item for item in required_swsd_semantic_node_ids if item not in selected_swsd_node_ids
    ]
    missing_required_swsd_road_endpoint_node_ids = [
        item for item in required_swsd_road_endpoint_node_ids if item not in selected_swsd_node_ids
    ]
    source_relation_missing_required_target_ids = [
        item for item in required_swsd_semantic_node_ids if item not in selected_relation_target_ids
    ]
    missing_mapped_rcsd_semantic_node_ids = [
        item for item in mapped_rcsd_semantic_node_ids if item not in selected_rcsd_node_ids
    ]
    missing_selected_rcsd_road_endpoint_node_ids = [
        item for item in selected_rcsd_road_endpoint_node_ids if item not in selected_rcsd_node_ids
    ]
    packaging_missing_dependencies = {
        "missing_required_swsd_road_ids": missing_required_swsd_road_ids,
        "missing_required_swsd_semantic_node_ids": missing_required_swsd_semantic_node_ids,
        "missing_required_swsd_road_endpoint_node_ids": missing_required_swsd_road_endpoint_node_ids,
        "missing_mapped_rcsd_semantic_node_ids": missing_mapped_rcsd_semantic_node_ids,
        "missing_selected_rcsd_road_endpoint_node_ids": missing_selected_rcsd_road_endpoint_node_ids,
    }
    packaging_dependency_complete = all(not values for values in packaging_missing_dependencies.values())
    has_selected_segments = bool(selected_segments)
    return {
        "has_selected_segments": has_selected_segments,
        "packaging_dependency_complete": packaging_dependency_complete,
        "local_case_ready": has_selected_segments and packaging_dependency_complete,
        "selected_swsd_road_ids": sorted(selected_swsd_road_ids),
        "selected_swsd_node_identity_ids": sorted(selected_swsd_node_ids),
        "selected_relation_target_ids": sorted(selected_relation_target_ids),
        "selected_rcsd_road_ids": sorted(selected_rcsd_road_ids),
        "selected_rcsd_node_identity_ids": sorted(selected_rcsd_node_ids),
        **packaging_missing_dependencies,
        "source_relation_missing_required_target_ids": source_relation_missing_required_target_ids,
    }


def _build_local_case_manifest(input_manifest: dict[str, Any], slice_summary: dict[str, Any]) -> dict[str, Any]:
    dependency_audit = dict(slice_summary.get("dependency_audit") or {})
    return {
        "case_type": "t06_decoded_input_slice",
        "purpose": "small real-data local test case for T06 Step1/Step2 and optional Step3 replay",
        "bundle_version": T06_TEXT_BUNDLE_VERSION,
        "crs": {
            "slice_files_normalized_to": T06_INPUT_SLICE_CRS_TEXT,
            "center_3857": slice_summary.get("center_3857"),
            "bounds_3857": slice_summary.get("bounds_3857"),
        },
        "decoded_input_paths": {
            "swsd_segment_path": "slice/swsd/segment.geojson",
            "swsd_roads_path": "slice/swsd/roads.geojson",
            "swsd_nodes_path": "slice/swsd/nodes.geojson",
            "intersection_match_path": "slice/t05_phase2/intersection_match_all.geojson",
            "rcsdroad_path": "slice/t05_phase2/rcsdroad_out.geojson",
            "rcsdnode_path": "slice/t05_phase2/rcsdnode_out.geojson",
        },
        "replay_scripts": {
            "step1_step2": f"audit/{T06_LOCAL_REPLAY_PRECHECK_NAME}",
            "step3_after_step1_step2": f"audit/{T06_LOCAL_REPLAY_STEP3_NAME}",
        },
        "source_paths": slice_summary.get("source_paths"),
        "selection": {
            "mode": slice_summary.get("selection_mode"),
            "profile_id": slice_summary.get("profile_id"),
            "size_m": slice_summary.get("size_m"),
            "radius_m": slice_summary.get("radius_m"),
            "selected_swsd_segment_count": slice_summary.get("selected_swsd_segment_count"),
            "selected_swsd_road_count": slice_summary.get("selected_swsd_road_count"),
            "selected_swsd_node_count": slice_summary.get("selected_swsd_node_count"),
            "selected_relation_count": slice_summary.get("selected_relation_count"),
            "selected_rcsdroad_count": slice_summary.get("selected_rcsdroad_count"),
            "selected_rcsdnode_count": slice_summary.get("selected_rcsdnode_count"),
        },
        "params": input_manifest.get("params"),
        "dependency_audit": dependency_audit,
        "local_case_ready": bool(dependency_audit.get("local_case_ready")),
        "known_limits": [
            "The slice is intentionally small and contains only selected local data plus explicit road/node dependencies.",
            "source_relation_missing_required_target_ids means the source relation data has no selected target relation; it is not a packaging omission.",
            "Step3 replay requires Step1/Step2 replay output unless STEP2_REPLACEABLE is provided.",
        ],
    }


def _build_local_case_readme(slice_summary: dict[str, Any]) -> str:
    selected_count = slice_summary.get("selected_swsd_segment_count")
    size_m = slice_summary.get("size_m")
    center = slice_summary.get("center_3857") or {}
    return f"""# T06 Local Input Slice Case

This decoded directory is a small real-data test case for T06.

## Inputs

- `slice/swsd/segment.geojson`
- `slice/swsd/roads.geojson`
- `slice/swsd/nodes.geojson`
- `slice/t05_phase2/intersection_match_all.geojson`
- `slice/t05_phase2/rcsdroad_out.geojson`
- `slice/t05_phase2/rcsdnode_out.geojson`

## Selection

- CRS: `EPSG:3857`
- center: `{center.get("x")}, {center.get("y")}`
- size_m: `{size_m}`
- selected_swsd_segment_count: `{selected_count}`

## Replay

Run Step1 + Step2 from the repository root or set `REPO_DIR` explicitly:

```bash
REPO_DIR=/path/to/RCSD_Topo_Poc bash audit/replay_t06_decoded_precheck.sh
```

Run Step3 after Step1 + Step2:

```bash
REPO_DIR=/path/to/RCSD_Topo_Poc bash audit/replay_t06_decoded_step3_segment_replacement.sh
```

Detailed source paths, counts and dependency checks are recorded in
`audit/t06_local_case_manifest.json` and `slice/t06_input_slice_summary.json`.
"""


def _intersects_window(feature: dict[str, Any], window: BaseGeometry) -> bool:
    geometry = feature.get("geometry")
    return bool(geometry is not None and geometry.intersects(window))


def _require_file(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_file():
        return resolved
    raise T06TextBundleError("input_file_missing", f"Input file does not exist: {resolved}")


def _resolve_file(explicit_path: str | Path | None, root: Path, filename: str) -> Path:
    if explicit_path:
        return _require_file(explicit_path)
    direct = root / filename
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(filename)) if root.is_dir() else []
    if matches:
        return matches[0]
    raise T06TextBundleError("input_file_missing", f"Missing {filename} under {root}")


def _read_json_if_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _add_file(files: dict[str, bytes], archive_name: str, path: Path) -> None:
    safe_name = _assert_safe_bundle_name(archive_name)
    if not path.is_file():
        raise T06TextBundleError("bundle_input_missing", f"Bundle input file is missing: {path}")
    files[safe_name] = path.read_bytes()


def _collect_run_outputs(
    *,
    run_root: Path,
    include_output_vectors: bool,
) -> tuple[dict[str, bytes], list[str], dict[str, dict[str, Any]]]:
    if not run_root.is_dir():
        raise T06TextBundleError("run_root_not_found", f"T06 run root does not exist: {run_root}")

    files: dict[str, bytes] = {}
    skipped_missing: list[str] = []
    output_file_info: dict[str, dict[str, Any]] = {}
    suffixes = (*_COMPACT_OUTPUT_SUFFIXES, *_VECTOR_OUTPUT_SUFFIXES) if include_output_vectors else _COMPACT_OUTPUT_SUFFIXES

    for step_dir, summary_name in _SUMMARY_BY_STEP_DIR.items():
        summary_path = run_root / step_dir / summary_name
        if not summary_path.is_file():
            raise T06TextBundleError("run_summary_missing", f"Required T06 summary is missing: {summary_path}")
        archive_name = f"run/{step_dir}/{summary_name}"
        _add_file(files, archive_name, summary_path)
        output_file_info[archive_name] = _file_info(summary_path)

    for step_dir, stems in _OUTPUT_STEMS_BY_STEP_DIR.items():
        for stem in stems:
            for suffix in suffixes:
                path = run_root / step_dir / f"{stem}{suffix}"
                archive_name = f"run/{step_dir}/{stem}{suffix}"
                if path.is_file():
                    _add_file(files, archive_name, path)
                    output_file_info[archive_name] = _file_info(path)
                else:
                    skipped_missing.append(archive_name)
    for step_dir, filenames in _OUTPUT_FILES_BY_STEP_DIR.items():
        for filename in filenames:
            path = run_root / step_dir / filename
            archive_name = f"run/{step_dir}/{filename}"
            if path.is_file():
                _add_file(files, archive_name, path)
                output_file_info[archive_name] = _file_info(path)
            else:
                skipped_missing.append(archive_name)
    return files, sorted(skipped_missing), output_file_info


def _resolve_extra_file(run_root: Path, value: str | Path) -> tuple[str, bytes]:
    root_resolved = run_root.resolve()
    path = Path(value)
    source_path = path if path.is_absolute() else run_root / path
    source_resolved = source_path.resolve()
    try:
        relative_name = source_resolved.relative_to(root_resolved).as_posix()
    except ValueError as exc:
        raise T06TextBundleError(
            "extra_path_outside_run_root",
            f"Extra path is outside T06 run root: {source_path}",
        ) from exc
    if not source_resolved.is_file():
        raise T06TextBundleError("extra_path_not_file", f"Extra path is not a file: {source_path}")
    return _assert_safe_bundle_name(f"run/{relative_name}"), source_resolved.read_bytes()


def _params_manifest(
    *,
    max_main_axis_angle_diff_deg: float,
    min_coarse_length_ratio: float,
    max_coarse_length_ratio: float,
    buffer_distance_m: float,
    min_buffer_road_overlap_ratio: float,
    min_buffer_road_overlap_length_m: float,
    advance_right_formway_bit: int,
) -> dict[str, Any]:
    return {
        "max_main_axis_angle_diff_deg": float(max_main_axis_angle_diff_deg),
        "min_coarse_length_ratio": float(min_coarse_length_ratio),
        "max_coarse_length_ratio": float(max_coarse_length_ratio),
        "buffer_distance_m": float(buffer_distance_m),
        "min_buffer_road_overlap_ratio": float(min_buffer_road_overlap_ratio),
        "min_buffer_road_overlap_length_m": float(min_buffer_road_overlap_length_m),
        "advance_right_formway_bit": int(advance_right_formway_bit),
    }


def _input_args_manifest(
    *,
    swsd_segment_path: Path,
    swsd_roads_path: Path,
    swsd_nodes_path: Path,
    t05_phase2_root: Path,
    intersection_match_path: Path,
    rcsdroad_path: Path,
    rcsdnode_path: Path,
    out_root: Path,
    run_id: str,
    params: dict[str, Any],
    include_intersection_match_override: bool,
    include_rcsdroad_override: bool,
    include_rcsdnode_override: bool,
) -> dict[str, Any]:
    input_paths = {
        "swsd_segment_path": str(swsd_segment_path),
        "swsd_roads_path": str(swsd_roads_path),
        "swsd_nodes_path": str(swsd_nodes_path),
        "intersection_match_path": str(intersection_match_path),
        "rcsdroad_path": str(rcsdroad_path),
        "rcsdnode_path": str(rcsdnode_path),
    }
    explicit_input_overrides = {}
    if include_intersection_match_override:
        explicit_input_overrides["--intersection-match"] = str(intersection_match_path)
    if include_rcsdroad_override:
        explicit_input_overrides["--rcsdroad"] = str(rcsdroad_path)
    if include_rcsdnode_override:
        explicit_input_overrides["--rcsdnode"] = str(rcsdnode_path)
    return {
        "input_paths": input_paths,
        "input_files": {key: _file_info(Path(value)) for key, value in input_paths.items()},
        "t05_phase2_root": str(t05_phase2_root),
        "out_root": str(out_root),
        "run_id": run_id,
        "run_root": str(out_root / run_id),
        "params": params,
        "explicit_input_overrides": explicit_input_overrides,
        "cli_args": {
            "--swsd-segment": str(swsd_segment_path),
            "--swsd-roads": str(swsd_roads_path),
            "--swsd-nodes": str(swsd_nodes_path),
            "--t05-phase2-root": str(t05_phase2_root),
            "--out-root": str(out_root),
            "--run-id": run_id,
            "--max-main-axis-angle-diff-deg": params["max_main_axis_angle_diff_deg"],
            "--min-coarse-length-ratio": params["min_coarse_length_ratio"],
            "--max-coarse-length-ratio": params["max_coarse_length_ratio"],
            "--buffer-distance-m": params["buffer_distance_m"],
            "--min-buffer-road-overlap-ratio": params["min_buffer_road_overlap_ratio"],
            "--min-buffer-road-overlap-length-m": params["min_buffer_road_overlap_length_m"],
            "--advance-right-formway-bit": params["advance_right_formway_bit"],
        },
    }


def _build_replay_command(input_manifest: dict[str, Any]) -> str:
    args = input_manifest["cli_args"]
    ordered = [
        ".venv/bin/python",
        "scripts/t06_run_innernet_precheck.py",
        "--swsd-segment",
        str(args["--swsd-segment"]),
        "--swsd-roads",
        str(args["--swsd-roads"]),
        "--swsd-nodes",
        str(args["--swsd-nodes"]),
        "--t05-phase2-root",
        str(args["--t05-phase2-root"]),
    ]
    explicit_overrides = input_manifest.get("explicit_input_overrides") or {}
    for flag in ("--intersection-match", "--rcsdroad", "--rcsdnode"):
        if flag in explicit_overrides:
            ordered.extend([flag, str(explicit_overrides[flag])])
    ordered.extend(
        [
            "--out-root",
            str(args["--out-root"]),
            "--run-id",
            str(args["--run-id"]),
            "--max-main-axis-angle-diff-deg",
            str(args["--max-main-axis-angle-diff-deg"]),
            "--min-coarse-length-ratio",
            str(args["--min-coarse-length-ratio"]),
            "--max-coarse-length-ratio",
            str(args["--max-coarse-length-ratio"]),
            "--buffer-distance-m",
            str(args["--buffer-distance-m"]),
            "--min-buffer-road-overlap-ratio",
            str(args["--min-buffer-road-overlap-ratio"]),
            "--min-buffer-road-overlap-length-m",
            str(args["--min-buffer-road-overlap-length-m"]),
            "--advance-right-formway-bit",
            str(args["--advance-right-formway-bit"]),
        ]
    )
    return " \\\n  ".join(shlex.quote(part) for part in ordered) + "\n"


def _build_decoded_precheck_replay_script(input_manifest: dict[str, Any]) -> str:
    params = input_manifest["params"]
    return f"""#!/usr/bin/env bash
set -euo pipefail

CASE_ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
REPO_DIR="${{REPO_DIR:-$(pwd)}}"
PYTHON_BIN="${{PYTHON_BIN:-$REPO_DIR/.venv/bin/python}}"
OUT_ROOT="${{OUT_ROOT:-$CASE_ROOT/run_outputs}}"
RUN_ID="${{RUN_ID:-t06_local_precheck}}"

if [[ ! -f "$REPO_DIR/scripts/t06_run_innernet_precheck.py" ]]; then
  echo "[BLOCK] Set REPO_DIR to the RCSD_Topo_Poc repository root." >&2
  exit 2
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[BLOCK] Python runtime not found or not executable: $PYTHON_BIN" >&2
  exit 2
fi

"$PYTHON_BIN" "$REPO_DIR/scripts/t06_run_innernet_precheck.py" \\
  --swsd-segment "$CASE_ROOT/slice/swsd/segment.geojson" \\
  --swsd-roads "$CASE_ROOT/slice/swsd/roads.geojson" \\
  --swsd-nodes "$CASE_ROOT/slice/swsd/nodes.geojson" \\
  --t05-phase2-root "$CASE_ROOT/slice/t05_phase2" \\
  --intersection-match "$CASE_ROOT/slice/t05_phase2/intersection_match_all.geojson" \\
  --rcsdroad "$CASE_ROOT/slice/t05_phase2/rcsdroad_out.geojson" \\
  --rcsdnode "$CASE_ROOT/slice/t05_phase2/rcsdnode_out.geojson" \\
  --out-root "$OUT_ROOT" \\
  --run-id "$RUN_ID" \\
  --max-main-axis-angle-diff-deg {params["max_main_axis_angle_diff_deg"]} \\
  --min-coarse-length-ratio {params["min_coarse_length_ratio"]} \\
  --max-coarse-length-ratio {params["max_coarse_length_ratio"]} \\
  --buffer-distance-m {params["buffer_distance_m"]} \\
  --min-buffer-road-overlap-ratio {params["min_buffer_road_overlap_ratio"]} \\
  --min-buffer-road-overlap-length-m {params["min_buffer_road_overlap_length_m"]} \\
  --advance-right-formway-bit {params["advance_right_formway_bit"]}
"""


def _build_decoded_step3_replay_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

CASE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="${REPO_DIR:-$(pwd)}"
PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
OUT_ROOT="${OUT_ROOT:-$CASE_ROOT/run_outputs}"
RUN_ID="${RUN_ID:-t06_local_precheck}"
T06_RUN_ROOT="${T06_RUN_ROOT:-$OUT_ROOT/$RUN_ID}"
STEP2_REPLACEABLE="${STEP2_REPLACEABLE:-$T06_RUN_ROOT/step2_extract_rcsd_segments/t06_rcsd_segment_replaceable.gpkg}"

if [[ ! -f "$REPO_DIR/scripts/t06_run_step3_segment_replacement.py" ]]; then
  echo "[BLOCK] Set REPO_DIR to the RCSD_Topo_Poc repository root." >&2
  exit 2
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[BLOCK] Python runtime not found or not executable: $PYTHON_BIN" >&2
  exit 2
fi
if [[ ! -f "$STEP2_REPLACEABLE" ]]; then
  echo "[BLOCK] Step2 replaceable output not found: $STEP2_REPLACEABLE" >&2
  echo "[TIP] Run audit/replay_t06_decoded_precheck.sh first, or set STEP2_REPLACEABLE." >&2
  exit 2
fi

"$PYTHON_BIN" "$REPO_DIR/scripts/t06_run_step3_segment_replacement.py" \\
  --t06-run-root "$T06_RUN_ROOT" \\
  --step2-replaceable "$STEP2_REPLACEABLE" \\
  --swsd-segment "$CASE_ROOT/slice/swsd/segment.geojson" \\
  --swsd-roads "$CASE_ROOT/slice/swsd/roads.geojson" \\
  --swsd-nodes "$CASE_ROOT/slice/swsd/nodes.geojson" \\
  --t05-phase2-root "$CASE_ROOT/slice/t05_phase2" \\
  --rcsdroad "$CASE_ROOT/slice/t05_phase2/rcsdroad_out.geojson" \\
  --rcsdnode "$CASE_ROOT/slice/t05_phase2/rcsdnode_out.geojson" \\
  --out-root "$OUT_ROOT" \\
  --run-id "$RUN_ID"
"""


def _build_size_report(
    *,
    bundle_size_bytes: int,
    payload_size_bytes: int,
    per_file_raw_size_bytes: dict[str, int],
    per_file_compressed_size_bytes: dict[str, int],
    skipped_missing_files: list[str],
    include_output_vectors: bool,
    include_input_files: bool,
    max_text_size_bytes: int,
) -> dict[str, Any]:
    evidence_file_names = [
        name
        for name in per_file_raw_size_bytes
        if name not in {T06_INTERNAL_MANIFEST_NAME, T06_INTERNAL_SIZE_REPORT_NAME}
    ]
    dominant_size_source = None
    if evidence_file_names:
        dominant_size_source = max(evidence_file_names, key=lambda name: per_file_raw_size_bytes[name])
    return {
        "bundle_version": T06_TEXT_BUNDLE_VERSION,
        "bundle_type": T06_TEXT_BUNDLE_TYPE,
        "total_text_size_bytes": bundle_size_bytes,
        "payload_size_bytes": payload_size_bytes,
        "within_limit": bundle_size_bytes <= max_text_size_bytes,
        "limit_bytes": max_text_size_bytes,
        "included_file_count": len(evidence_file_names),
        "include_output_vectors": include_output_vectors,
        "include_input_files": include_input_files,
        "split_bundle": {"enabled": False, "part_count": 1},
        "dominant_size_source": dominant_size_source,
        "per_file_raw_size_bytes": per_file_raw_size_bytes,
        "per_file_compressed_size_bytes": per_file_compressed_size_bytes,
        "skipped_missing_files": skipped_missing_files,
    }


def _build_text_bundle(
    *,
    run_root: Path,
    input_manifest: dict[str, Any],
    include_output_vectors: bool,
    include_input_files: bool,
    extra_relative_paths: Sequence[str | Path],
    max_text_size_bytes: int,
) -> tuple[str, int, dict[str, Any]]:
    files, skipped_missing, output_file_info = _collect_run_outputs(
        run_root=run_root,
        include_output_vectors=include_output_vectors,
    )

    if include_input_files:
        for key, archive_name in _INPUT_ARCHIVE_NAMES.items():
            source_path = Path(input_manifest["input_paths"][key])
            _add_file(files, archive_name, source_path)

    for value in extra_relative_paths:
        archive_name, content = _resolve_extra_file(run_root, value)
        files[archive_name] = content

    files[f"audit/{T06_INPUT_MANIFEST_NAME}"] = json.dumps(
        input_manifest,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    files[f"audit/{T06_REPLAY_COMMAND_NAME}"] = _build_replay_command(input_manifest).encode("utf-8")

    step1_summary_path = run_root / STEP1_DIR / STEP1_SUMMARY
    step2_summary_path = run_root / STEP2_DIR / STEP2_SUMMARY
    manifest = {
        "bundle_version": T06_TEXT_BUNDLE_VERSION,
        "bundle_type": T06_TEXT_BUNDLE_TYPE,
        "source_run_root": str(run_root.resolve()),
        "input_manifest": input_manifest,
        "step1_summary": _read_json_if_file(step1_summary_path),
        "step2_summary": _read_json_if_file(step2_summary_path),
        "run_output_files": output_file_info,
        "file_list": sorted(set(files).union({T06_INTERNAL_MANIFEST_NAME, T06_INTERNAL_SIZE_REPORT_NAME})),
        "checksum": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())},
        "encoder_info": {
            "archive_format": "zip",
            "compression": "deflate",
            "text_encoding": "base85",
            "line_width": T06_TEXT_BUNDLE_LINE_WIDTH,
            "max_text_size_bytes": max_text_size_bytes,
            "selection": "t06-segment-fusion-precheck-compact-evidence",
            "include_output_vectors": include_output_vectors,
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
            skipped_missing_files=skipped_missing,
            include_output_vectors=include_output_vectors,
            include_input_files=include_input_files,
            max_text_size_bytes=max_text_size_bytes,
        )
        if next_report == size_report:
            break
        size_report = next_report
    return bundle_text, bundle_size_bytes, size_report


def _resolve_slice_size_m(*, profile_id: str, size_m: float | None, radius_m: float | None) -> tuple[str, float, float]:
    from .text_bundle_input import _resolve_slice_size_m as _impl
    return _impl(profile_id=profile_id, size_m=size_m, radius_m=radius_m)


def _select_t06_input_slice(**kwargs):
    from .text_bundle_input import _select_t06_input_slice as _impl
    return _impl(**kwargs)


def _build_input_slice_text_bundle(**kwargs):
    from .text_bundle_input import _build_input_slice_text_bundle as _impl
    return _impl(**kwargs)


def _write_bundle_outputs(**kwargs):
    from .text_bundle_input import _write_bundle_outputs as _impl
    return _impl(**kwargs)


def run_t06_export_text_bundle(
    *,
    swsd_segment_path: str | Path = DEFAULT_SWSD_SEGMENT,
    swsd_roads_path: str | Path = DEFAULT_SWSD_ROADS,
    swsd_nodes_path: str | Path = DEFAULT_SWSD_NODES,
    t05_phase2_root: str | Path = DEFAULT_T05_PHASE2_ROOT,
    out_root: str | Path = DEFAULT_OUT_ROOT,
    run_id: str = DEFAULT_RUN_ID,
    out_txt: str | Path | None = None,
    intersection_match_path: str | Path | None = None,
    rcsdroad_path: str | Path | None = None,
    rcsdnode_path: str | Path | None = None,
    max_main_axis_angle_diff_deg: float = 60.0,
    min_coarse_length_ratio: float = 0.4,
    max_coarse_length_ratio: float = 2.5,
    buffer_distance_m: float = 50.0,
    min_buffer_road_overlap_ratio: float = 0.2,
    min_buffer_road_overlap_length_m: float = 1.0,
    advance_right_formway_bit: int = 128,
    include_output_vectors: bool = False,
    include_input_files: bool = False,
    extra_relative_paths: Sequence[str | Path] = (),
    max_text_size_bytes: int = T06_TEXT_BUNDLE_LIMIT_BYTES,
) -> T06TextBundleExportArtifacts:
    out_root_path = Path(out_root)
    run_root = out_root_path / run_id
    out_txt_path = Path(out_txt) if out_txt is not None else run_root / T06_TEXT_BUNDLE_NAME
    size_report_path = out_txt_path.with_name(T06_TEXT_BUNDLE_SIZE_REPORT_NAME)
    try:
        t05_root = Path(t05_phase2_root)
        params = _params_manifest(
            max_main_axis_angle_diff_deg=max_main_axis_angle_diff_deg,
            min_coarse_length_ratio=min_coarse_length_ratio,
            max_coarse_length_ratio=max_coarse_length_ratio,
            buffer_distance_m=buffer_distance_m,
            min_buffer_road_overlap_ratio=min_buffer_road_overlap_ratio,
            min_buffer_road_overlap_length_m=min_buffer_road_overlap_length_m,
            advance_right_formway_bit=advance_right_formway_bit,
        )
        input_manifest = _input_args_manifest(
            swsd_segment_path=_require_file(swsd_segment_path),
            swsd_roads_path=_require_file(swsd_roads_path),
            swsd_nodes_path=_require_file(swsd_nodes_path),
            t05_phase2_root=t05_root,
            intersection_match_path=_resolve_file(intersection_match_path, t05_root, "intersection_match_all.geojson"),
            rcsdroad_path=_resolve_file(rcsdroad_path, t05_root, "rcsdroad_out.gpkg"),
            rcsdnode_path=_resolve_file(rcsdnode_path, t05_root, "rcsdnode_out.gpkg"),
            out_root=out_root_path,
            run_id=run_id,
            params=params,
            include_intersection_match_override=intersection_match_path is not None,
            include_rcsdroad_override=rcsdroad_path is not None,
            include_rcsdnode_override=rcsdnode_path is not None,
        )
        out_txt_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_text, bundle_size_bytes, size_report = _build_text_bundle(
            run_root=run_root,
            input_manifest=input_manifest,
            include_output_vectors=include_output_vectors,
            include_input_files=include_input_files,
            extra_relative_paths=extra_relative_paths,
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
        return T06TextBundleExportArtifacts(
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
        return T06TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            failure_reason=reason,
            failure_detail=detail,
        )


def run_t06_export_input_text_bundle(
    *,
    swsd_segment_path: str | Path = DEFAULT_SWSD_SEGMENT,
    swsd_roads_path: str | Path = DEFAULT_SWSD_ROADS,
    swsd_nodes_path: str | Path = DEFAULT_SWSD_NODES,
    t05_phase2_root: str | Path = DEFAULT_T05_PHASE2_ROOT,
    out_root: str | Path = DEFAULT_OUT_ROOT,
    run_id: str = DEFAULT_RUN_ID,
    out_txt: str | Path | None = None,
    center_x: float,
    center_y: float,
    profile_id: str = T06_INPUT_SLICE_DEFAULT_PROFILE_ID,
    size_m: float | None = None,
    radius_m: float | None = None,
    intersection_match_path: str | Path | None = None,
    rcsdroad_path: str | Path | None = None,
    rcsdnode_path: str | Path | None = None,
    max_main_axis_angle_diff_deg: float = 60.0,
    min_coarse_length_ratio: float = 0.4,
    max_coarse_length_ratio: float = 2.5,
    buffer_distance_m: float = 50.0,
    min_buffer_road_overlap_ratio: float = 0.2,
    min_buffer_road_overlap_length_m: float = 1.0,
    advance_right_formway_bit: int = 128,
    include_input_files: bool = False,
    max_text_size_bytes: int = T06_TEXT_BUNDLE_LIMIT_BYTES,
) -> T06TextBundleExportArtifacts:
    out_root_path = Path(out_root)
    out_txt_path = (
        Path(out_txt)
        if out_txt is not None
        else out_root_path / run_id / f"{Path(T06_INPUT_SLICE_BUNDLE_NAME).stem}_{profile_id.upper()}.txt"
    )
    size_report_path = out_txt_path.with_name(T06_INPUT_SLICE_SIZE_REPORT_NAME)
    try:
        t05_root = Path(t05_phase2_root)
        params = _params_manifest(
            max_main_axis_angle_diff_deg=max_main_axis_angle_diff_deg,
            min_coarse_length_ratio=min_coarse_length_ratio,
            max_coarse_length_ratio=max_coarse_length_ratio,
            buffer_distance_m=buffer_distance_m,
            min_buffer_road_overlap_ratio=min_buffer_road_overlap_ratio,
            min_buffer_road_overlap_length_m=min_buffer_road_overlap_length_m,
            advance_right_formway_bit=advance_right_formway_bit,
        )
        resolved_segment = _require_file(swsd_segment_path)
        resolved_roads = _require_file(swsd_roads_path)
        resolved_nodes = _require_file(swsd_nodes_path)
        resolved_intersection = _resolve_file(intersection_match_path, t05_root, "intersection_match_all.geojson")
        resolved_rcsdroad = _resolve_file(rcsdroad_path, t05_root, "rcsdroad_out.gpkg")
        resolved_rcsdnode = _resolve_file(rcsdnode_path, t05_root, "rcsdnode_out.gpkg")
        input_manifest = _input_args_manifest(
            swsd_segment_path=resolved_segment,
            swsd_roads_path=resolved_roads,
            swsd_nodes_path=resolved_nodes,
            t05_phase2_root=t05_root,
            intersection_match_path=resolved_intersection,
            rcsdroad_path=resolved_rcsdroad,
            rcsdnode_path=resolved_rcsdnode,
            out_root=out_root_path,
            run_id=run_id,
            params=params,
            include_intersection_match_override=intersection_match_path is not None,
            include_rcsdroad_override=rcsdroad_path is not None,
            include_rcsdnode_override=rcsdnode_path is not None,
        )
        files, slice_summary = _select_t06_input_slice(
            swsd_segment_path=resolved_segment,
            swsd_roads_path=resolved_roads,
            swsd_nodes_path=resolved_nodes,
            intersection_match_path=resolved_intersection,
            rcsdroad_path=resolved_rcsdroad,
            rcsdnode_path=resolved_rcsdnode,
            center_x=center_x,
            center_y=center_y,
            profile_id=profile_id,
            size_m=size_m,
            radius_m=radius_m,
        )
        input_manifest["input_slice"] = slice_summary
        out_txt_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_text, bundle_size_bytes, size_report = _build_input_slice_text_bundle(
            files=files,
            input_manifest=input_manifest,
            slice_summary=slice_summary,
            include_input_files=include_input_files,
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
        return T06TextBundleExportArtifacts(
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
        return T06TextBundleExportArtifacts(
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
        if hashlib.sha256(payload_bytes).hexdigest() != str(meta.get("payload_sha256")):
            raise T06TextBundleError("checksum_mismatch", "Payload sha256 metadata does not match.")
        return payload_bytes, None

    part_count = int(split_meta.get("part_count") or 0)
    part_filenames = [str(name) for name in split_meta.get("part_filenames") or ()]
    full_payload_sha256 = str(split_meta.get("full_payload_sha256") or split_meta.get("bundle_id") or "")
    if part_count <= 0 or len(part_filenames) != part_count or not full_payload_sha256:
        raise T06TextBundleError("invalid_split_bundle", "Split bundle metadata is incomplete.")

    chunks: dict[int, bytes] = {}
    for filename in part_filenames:
        part_path = bundle_txt.parent / filename
        if not part_path.is_file():
            raise T06TextBundleError("bundle_part_missing", f"Split bundle part missing: {part_path}")
        part_meta, part_payload = _parse_text_bundle(part_path.read_text(encoding="utf-8"))
        part_split = part_meta.get("split_bundle") or {}
        if str(part_split.get("full_payload_sha256") or part_split.get("bundle_id") or "") != full_payload_sha256:
            raise T06TextBundleError("split_bundle_mismatch", f"Split bundle id mismatch: {part_path}")
        if int(part_split.get("part_count") or 0) != part_count:
            raise T06TextBundleError("split_bundle_mismatch", f"Split bundle part count mismatch: {part_path}")
        part_index = int(part_split.get("part_index") or 0)
        if part_index < 1 or part_index > part_count or part_index in chunks:
            raise T06TextBundleError("invalid_split_bundle", f"Invalid split bundle part index: {part_path}")
        chunks[part_index] = part_payload

    if len(chunks) != part_count:
        raise T06TextBundleError("bundle_part_missing", "Split bundle parts are incomplete.")
    full_payload = b"".join(chunks[index] for index in range(1, part_count + 1))
    if hashlib.sha256(full_payload).hexdigest() != full_payload_sha256:
        raise T06TextBundleError("checksum_mismatch", "Split bundle full payload checksum validation failed.")
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
    if T06_INTERNAL_MANIFEST_NAME not in files:
        raise T06TextBundleError("bundle_missing_files", f"Bundle is missing {T06_INTERNAL_MANIFEST_NAME}.")
    manifest = json.loads(files[T06_INTERNAL_MANIFEST_NAME])
    if str(manifest.get("bundle_version")) != T06_TEXT_BUNDLE_VERSION:
        raise T06TextBundleError(
            "bundle_version_mismatch",
            f"Unsupported bundle version: {manifest.get('bundle_version')}",
        )
    if str(manifest.get("bundle_type")) != T06_TEXT_BUNDLE_TYPE:
        raise T06TextBundleError("bundle_type_mismatch", f"Unsupported bundle type: {manifest.get('bundle_type')}")
    for name, expected in dict(manifest.get("checksum") or {}).items():
        if name not in files:
            raise T06TextBundleError("bundle_missing_files", f"Bundle is missing checksummed file: {name}")
        if hashlib.sha256(files[name]).hexdigest() != expected:
            raise T06TextBundleError("checksum_mismatch", f"Checksum mismatch for {name}.")
    if split_report is not None and T06_INTERNAL_SIZE_REPORT_NAME in files:
        size_report = json.loads(files[T06_INTERNAL_SIZE_REPORT_NAME])
        size_report["split_bundle"] = split_report
        files[T06_INTERNAL_SIZE_REPORT_NAME] = json.dumps(
            size_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
    return manifest, files


def run_t06_decode_text_bundle(
    *,
    bundle_txt: str | Path,
    out_dir: str | Path | None = None,
) -> T06TextBundleDecodeArtifacts:
    bundle_path = Path(bundle_txt)
    if not bundle_path.is_file():
        raise T06TextBundleError("bundle_not_found", f"Bundle text file does not exist: {bundle_path}")
    out_dir_path = Path(out_dir) if out_dir is not None else bundle_path.with_suffix("")
    out_dir_path.mkdir(parents=True, exist_ok=True)
    manifest, files = _extract_and_verify_bundle(bundle_path)
    for name, content in files.items():
        target_path = out_dir_path / _assert_safe_bundle_name(name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
    manifest["decoded_output"] = {
        "decoded_at": _now_text(),
        "out_dir": str(out_dir_path.resolve()),
    }
    manifest_path = out_dir_path / T06_INTERNAL_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return T06TextBundleDecodeArtifacts(success=True, out_dir=out_dir_path, manifest_path=manifest_path)


def _build_export_arg_parser() -> argparse.ArgumentParser:
    from .text_bundle_cli import _build_export_arg_parser as _impl
    return _impl()


def _build_decode_arg_parser() -> argparse.ArgumentParser:
    from .text_bundle_cli import _build_decode_arg_parser as _impl
    return _impl()


def _build_input_export_arg_parser() -> argparse.ArgumentParser:
    from .text_bundle_cli import _build_input_export_arg_parser as _impl
    return _impl()


def run_t06_export_text_bundle_from_args(argv: list[str] | None = None) -> int:
    from .text_bundle_cli import run_t06_export_text_bundle_from_args as _impl
    return _impl(argv)


def run_t06_decode_text_bundle_from_args(argv: list[str] | None = None) -> int:
    from .text_bundle_cli import run_t06_decode_text_bundle_from_args as _impl
    return _impl(argv)


def run_t06_export_input_text_bundle_from_args(argv: list[str] | None = None) -> int:
    from .text_bundle_cli import run_t06_export_input_text_bundle_from_args as _impl
    return _impl(argv)
