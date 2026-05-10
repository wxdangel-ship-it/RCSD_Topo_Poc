from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import fiona
from shapely.affinity import translate
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset, normalise_id
from rcsd_topo_poc.modules.p01_arm_build.models import DATASETS, DatasetInput, LoadedDataset, NodeRecord, RoadRecord
from rcsd_topo_poc.modules.p01_arm_build.topology import build_node_groups, resolve_junction_members, semantic_group_id
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector


P01_TEXT_BUNDLE_VERSION = "1"
P01_TEXT_BUNDLE_LIMIT_BYTES = 250 * 1024
P01_TEXT_BUNDLE_BEGIN = "BEGIN_P01_ARM_BUNDLE"
P01_TEXT_BUNDLE_PAYLOAD = "payload:"
P01_TEXT_BUNDLE_META = "meta: "
P01_TEXT_BUNDLE_CHECKSUM = "checksum: "
P01_TEXT_BUNDLE_END = "END_P01_ARM_BUNDLE"
P01_TEXT_BUNDLE_LINE_WIDTH = 120
P01_BUNDLE_FILES = (
    "manifest.json",
    "size_report.json",
    "SWSD/nodes.gpkg",
    "SWSD/roads.gpkg",
    "RCSD/nodes.gpkg",
    "RCSD/roads.gpkg",
    "FRCSD/nodes.gpkg",
    "FRCSD/roads.gpkg",
)
P01_OPTIONAL_RELATION_BUNDLE_NAMES = {
    "swsd_road_node_road": ("SWSD", "SWSD/RoadNodeRoad.json"),
    "swsd_road_next_road": ("SWSD", "SWSD/RoadNextRoad.json"),
    "rcsd_road_next_road": ("RCSD", "RCSD/RoadNextRoad.geojson"),
}


class P01TextBundleError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class P01TextBundleExportArtifacts:
    success: bool
    bundle_txt_path: Path
    size_report_path: Path | None
    bundle_size_bytes: int
    failure_reason: str | None = None
    failure_detail: str | None = None
    selected_bfs_depth: int | None = None
    part_txt_paths: tuple[Path, ...] = ()
    max_part_size_bytes: int = 0


@dataclass(frozen=True)
class P01TextBundleDecodeArtifacts:
    success: bool
    out_dir: Path
    manifest_path: Path


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _wrap_payload_text(text: str, *, width: int = P01_TEXT_BUNDLE_LINE_WIDTH) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def _build_bundle_text(*, meta: dict[str, Any], payload_bytes: bytes) -> tuple[str, int]:
    payload_text = base64.b85encode(payload_bytes).decode("ascii")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    lines = [
        P01_TEXT_BUNDLE_BEGIN,
        P01_TEXT_BUNDLE_META + json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        P01_TEXT_BUNDLE_PAYLOAD,
        _wrap_payload_text(payload_text),
        P01_TEXT_BUNDLE_CHECKSUM + checksum,
        P01_TEXT_BUNDLE_END,
        "",
    ]
    text = "\n".join(lines)
    return text, len(text.encode("utf-8"))


def _zip_bytes(files: dict[str, bytes]) -> tuple[bytes, dict[str, int]]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue()), "r") as zf:
        per_file_compressed = {info.filename: int(info.compress_size) for info in zf.infolist()}
    return buffer.getvalue(), per_file_compressed


def _parse_text_bundle(bundle_text: str) -> tuple[dict[str, Any], bytes]:
    lines = bundle_text.splitlines()
    if not lines or lines[0].strip() != P01_TEXT_BUNDLE_BEGIN:
        raise P01TextBundleError("invalid_bundle_format", "Bundle header not found.")
    try:
        meta_index = next(index for index, line in enumerate(lines) if line.startswith(P01_TEXT_BUNDLE_META))
        payload_index = next(index for index, line in enumerate(lines) if line.strip() == P01_TEXT_BUNDLE_PAYLOAD)
        checksum_index = next(index for index, line in enumerate(lines) if line.startswith(P01_TEXT_BUNDLE_CHECKSUM))
        end_index = next(index for index, line in enumerate(lines) if line.strip() == P01_TEXT_BUNDLE_END)
    except StopIteration as exc:
        raise P01TextBundleError("invalid_bundle_format", "Bundle markers are incomplete.") from exc
    if not (meta_index < payload_index < checksum_index < end_index):
        raise P01TextBundleError("invalid_bundle_format", "Bundle section order is invalid.")

    meta = json.loads(lines[meta_index][len(P01_TEXT_BUNDLE_META) :])
    payload_text = "".join(lines[payload_index + 1 : checksum_index]).strip()
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = lines[checksum_index][len(P01_TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise P01TextBundleError("checksum_mismatch", "Bundle payload checksum validation failed.")
    if str(meta.get("bundle_version")) != P01_TEXT_BUNDLE_VERSION:
        raise P01TextBundleError("bundle_version_mismatch", f"Unsupported bundle version: {meta.get('bundle_version')}")
    return meta, payload_bytes


def _parse_junction_group(value: str) -> dict[str, str]:
    parts = [normalise_id(part) for part in value.split(",")]
    if len(parts) != 3 or any(not part for part in parts):
        raise P01TextBundleError("invalid_junction_group", f"Invalid junction group: {value}")
    return {"SWSD": parts[0], "RCSD": parts[1], "FRCSD": parts[2]}


def _dataset_inputs_from_paths(
    *,
    swsd_nodes: str | Path,
    swsd_roads: str | Path,
    rcsd_nodes: str | Path,
    rcsd_roads: str | Path,
    frcsd_nodes: str | Path,
    frcsd_roads: str | Path,
) -> dict[str, DatasetInput]:
    return {
        "SWSD": DatasetInput("SWSD", Path(swsd_nodes), Path(swsd_roads)),
        "RCSD": DatasetInput("RCSD", Path(rcsd_nodes), Path(rcsd_roads)),
        "FRCSD": DatasetInput("FRCSD", Path(frcsd_nodes), Path(frcsd_roads)),
    }


def _crs_text(layer: Any) -> str | None:
    if layer.crs_wkt:
        return str(layer.crs_wkt)
    if layer.crs:
        return str(layer.crs)
    return None


def _road_endpoint_groups(loaded: LoadedDataset, road: RoadRecord) -> tuple[str, str]:
    return semantic_group_id(loaded.nodes.get(road.snodeid), road.snodeid), semantic_group_id(loaded.nodes.get(road.enodeid), road.enodeid)


def _select_bfs_context(
    loaded: LoadedDataset,
    *,
    junction_id: str,
    bfs_depth: int,
) -> tuple[set[str], set[str], dict[str, Any]]:
    resolved_group_id, member_node_ids, input_flags = resolve_junction_members(
        loaded.nodes,
        junction_id=junction_id,
        dataset=loaded.dataset,
    )
    groups, _ = build_node_groups(loaded.nodes)
    adjacency: dict[str, list[tuple[str, str]]] = {}
    road_groups: dict[str, tuple[str, str]] = {}
    for road in loaded.roads.values():
        start_group, end_group = _road_endpoint_groups(loaded, road)
        road_groups[road.road_id] = (start_group, end_group)
        if start_group == end_group:
            continue
        adjacency.setdefault(start_group, []).append((end_group, road.road_id))
        adjacency.setdefault(end_group, []).append((start_group, road.road_id))

    group_depths: dict[str, int] = {resolved_group_id: 0}
    queue: deque[str] = deque([resolved_group_id])
    while queue:
        group_id = queue.popleft()
        current_depth = group_depths[group_id]
        if current_depth >= bfs_depth:
            continue
        for next_group_id, _road_id in adjacency.get(group_id, []):
            if next_group_id in group_depths:
                continue
            group_depths[next_group_id] = current_depth + 1
            queue.append(next_group_id)

    selected_road_ids: set[str] = set()
    selected_node_ids: set[str] = set(member_node_ids)
    for group_id in group_depths:
        selected_node_ids.update(groups.get(group_id, (group_id,)))

    for road_id, (start_group, end_group) in road_groups.items():
        if start_group in group_depths or end_group in group_depths:
            selected_road_ids.add(road_id)
            selected_node_ids.update(groups.get(start_group, (start_group,)))
            selected_node_ids.update(groups.get(end_group, (end_group,)))
            road = loaded.roads[road_id]
            selected_node_ids.add(road.snodeid)
            selected_node_ids.add(road.enodeid)

    selected_node_ids = {node_id for node_id in selected_node_ids if node_id in loaded.nodes}
    audit = {
        "junction_id": junction_id,
        "resolved_group_id": resolved_group_id,
        "input_issue_flags": tuple(sorted(set(input_flags))),
        "bfs_depth": bfs_depth,
        "visited_group_count": len(group_depths),
        "selected_node_count": len(selected_node_ids),
        "selected_road_count": len(selected_road_ids),
        "group_depths": dict(sorted(group_depths.items(), key=lambda item: (item[1], item[0]))),
    }
    return selected_node_ids, selected_road_ids, audit


def _geometry_origin(geometries: Iterable[BaseGeometry]) -> tuple[float, float]:
    non_empty = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not non_empty:
        return 0.0, 0.0
    min_x = min(float(geometry.bounds[0]) for geometry in non_empty)
    min_y = min(float(geometry.bounds[1]) for geometry in non_empty)
    return round(min_x, 1), round(min_y, 1)


def _localized_geometry(geometry: BaseGeometry, *, origin_x: float, origin_y: float) -> BaseGeometry:
    return translate(geometry, xoff=-origin_x, yoff=-origin_y)


def _node_feature(node: NodeRecord, *, origin_x: float, origin_y: float) -> dict[str, Any]:
    properties = dict(node.properties)
    properties.update(
        {
            "id": node.node_id,
            "mainnodeid": node.mainnodeid,
            "kind": node.kind,
        }
    )
    return {
        "properties": properties,
        "geometry": _localized_geometry(node.geometry, origin_x=origin_x, origin_y=origin_y),
    }


def _road_feature(road: RoadRecord, *, origin_x: float, origin_y: float) -> dict[str, Any]:
    properties = dict(road.properties)
    properties.update(
        {
            "id": road.road_id,
            "snodeid": road.snodeid,
            "enodeid": road.enodeid,
            "direction": road.direction,
            "formway": road.formway,
        }
    )
    return {
        "properties": properties,
        "geometry": _localized_geometry(road.geometry, origin_x=origin_x, origin_y=origin_y),
    }


def _first_present_payload(properties: dict[str, Any], names: tuple[str, ...]) -> Any:
    lower = {str(key).lower(): value for key, value in properties.items()}
    for name in names:
        if name in properties:
            return properties[name]
        value = lower.get(name.lower())
        if value is not None:
            return value
    return None


def _relation_properties(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    if isinstance(record.get("properties"), dict):
        properties = dict(record["properties"])
        if "id" not in properties and record.get("id") is not None:
            properties["id"] = record.get("id")
        return properties
    return dict(record)


def _relation_record_count(payload: Any) -> int:
    if isinstance(payload, list):
        return sum(1 for item in payload if isinstance(item, dict))
    if not isinstance(payload, dict):
        return 0
    if isinstance(payload.get("features"), list):
        return sum(1 for item in payload["features"] if isinstance(item, dict))
    for key in ("records", "data", "items", "roadNodeRoads", "road_next_roads", "RoadNextRoad"):
        if isinstance(payload.get(key), list):
            return sum(1 for item in payload[key] if isinstance(item, dict))
    return 1


def _relation_touches_selected_road(record: Any, selected_road_ids: set[str]) -> bool:
    properties = _relation_properties(record)
    road_id = normalise_id(_first_present_payload(properties, ("road_id", "roadId", "roadid")))
    next_road_id = normalise_id(
        _first_present_payload(properties, ("next_road_id", "nextRoadId", "nextroadid"))
    )
    return bool((road_id and road_id in selected_road_ids) or (next_road_id and next_road_id in selected_road_ids))


def _filter_relation_payload(payload: Any, *, selected_road_ids: set[str]) -> tuple[Any, int, int]:
    raw_count = _relation_record_count(payload)
    if isinstance(payload, list):
        filtered = [
            item for item in payload if isinstance(item, dict) and _relation_touches_selected_road(item, selected_road_ids)
        ]
        return filtered, raw_count, len(filtered)
    if not isinstance(payload, dict):
        return [], raw_count, 0
    if isinstance(payload.get("features"), list):
        filtered_features = [
            item
            for item in payload["features"]
            if isinstance(item, dict) and _relation_touches_selected_road(item, selected_road_ids)
        ]
        filtered_payload = dict(payload)
        filtered_payload["features"] = filtered_features
        return filtered_payload, raw_count, len(filtered_features)
    for key in ("records", "data", "items", "roadNodeRoads", "road_next_roads", "RoadNextRoad"):
        if isinstance(payload.get(key), list):
            filtered_items = [
                item
                for item in payload[key]
                if isinstance(item, dict) and _relation_touches_selected_road(item, selected_road_ids)
            ]
            filtered_payload = dict(payload)
            filtered_payload[key] = filtered_items
            return filtered_payload, raw_count, len(filtered_items)
    if _relation_touches_selected_road(payload, selected_road_ids):
        return payload, raw_count, 1
    return {}, raw_count, 0


def _prepare_optional_relation_file(
    *,
    source_path: Path,
    selected_road_ids: set[str],
) -> tuple[bytes, dict[str, Any]]:
    if not source_path.is_file():
        raise P01TextBundleError("optional_relation_input_missing", f"Optional relation file missing: {source_path}")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    filtered_payload, raw_count, included_count = _filter_relation_payload(
        payload,
        selected_road_ids=selected_road_ids,
    )
    content = json.dumps(filtered_payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return content, {
        "input_path": str(source_path),
        "raw_record_count": raw_count,
        "included_record_count": included_count,
        "filter": "road_id_or_next_road_id_intersects_selected_bfs_roads",
    }


def _vector_bytes(filename: str, features: list[dict[str, Any]], *, crs_text: str | None) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        vector_path = Path(temp_dir) / filename
        write_vector(vector_path, features, crs_text=crs_text, layer_name=vector_path.stem)
        return vector_path.read_bytes()


def _prepare_dataset_files(
    loaded: LoadedDataset,
    *,
    junction_id: str,
    bfs_depth: int,
) -> tuple[dict[str, bytes], dict[str, Any], set[str]]:
    node_ids, road_ids, audit = _select_bfs_context(loaded, junction_id=junction_id, bfs_depth=bfs_depth)
    selected_nodes = [loaded.nodes[node_id] for node_id in sorted(node_ids)]
    selected_roads = [loaded.roads[road_id] for road_id in sorted(road_ids)]
    origin_x, origin_y = _geometry_origin(
        [node.geometry for node in selected_nodes] + [road.geometry for road in selected_roads]
    )
    node_features = [_node_feature(node, origin_x=origin_x, origin_y=origin_y) for node in selected_nodes]
    road_features = [_road_feature(road, origin_x=origin_x, origin_y=origin_y) for road in selected_roads]
    files = {
        f"{loaded.dataset}/nodes.gpkg": _vector_bytes("nodes.gpkg", node_features, crs_text=_crs_text(loaded.node_layer)),
        f"{loaded.dataset}/roads.gpkg": _vector_bytes("roads.gpkg", road_features, crs_text=_crs_text(loaded.road_layer)),
    }
    audit.update(
        {
            "local_origin": {"x": origin_x, "y": origin_y},
            "node_crs": _crs_text(loaded.node_layer),
            "road_crs": _crs_text(loaded.road_layer),
        }
    )
    return files, audit, set(road_ids)


def _build_size_report(
    *,
    total_text_size_bytes: int,
    payload_size_bytes: int,
    per_file_raw_size_bytes: dict[str, int],
    per_file_compressed_size_bytes: dict[str, int],
    dataset_audits: dict[str, Any],
    limit_bytes: int,
) -> dict[str, Any]:
    dominant_size_source = None
    if per_file_compressed_size_bytes:
        dominant_size_source = max(per_file_compressed_size_bytes.items(), key=lambda item: item[1])[0]
    return {
        "total_text_size_bytes": total_text_size_bytes,
        "payload_size_bytes": payload_size_bytes,
        "per_file_raw_size_bytes": per_file_raw_size_bytes,
        "per_file_compressed_size_bytes": per_file_compressed_size_bytes,
        "dominant_size_source": dominant_size_source,
        "dataset_audits": dataset_audits,
        "within_limit": total_text_size_bytes <= limit_bytes,
        "limit_bytes": limit_bytes,
    }


def _out_size_report_path(out_txt: Path) -> Path:
    return out_txt.with_suffix(out_txt.suffix + ".size_report.json")


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
        raise P01TextBundleError("invalid_max_text_size", "max_text_size_bytes must be > 0.")

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
        raise P01TextBundleError("bundle_part_too_large", f"Bundle part metadata cannot fit limit {max_text_size_bytes}.")
    return best


def _build_text_bundle_for_depth(
    *,
    dataset_inputs: dict[str, DatasetInput],
    loaded_by_dataset: dict[str, LoadedDataset],
    junction_ids: dict[str, str],
    bfs_depth: int,
    max_text_size_bytes: int,
    optional_relation_paths: dict[str, Path] | None = None,
    auto_fit_attempts: list[dict[str, Any]] | None = None,
) -> tuple[str, int, dict[str, Any]]:
    files: dict[str, bytes] = {}
    dataset_audits: dict[str, Any] = {}
    selected_roads_by_dataset: dict[str, set[str]] = {}
    for dataset in DATASETS:
        loaded = loaded_by_dataset[dataset]
        dataset_files, audit, selected_road_ids = _prepare_dataset_files(
            loaded,
            junction_id=junction_ids[dataset],
            bfs_depth=bfs_depth,
        )
        files.update(dataset_files)
        selected_roads_by_dataset[dataset] = selected_road_ids
        dataset_audits[dataset] = {
            **audit,
            "input_nodes_path": str(dataset_inputs[dataset].nodes_path),
            "input_roads_path": str(dataset_inputs[dataset].roads_path),
        }

    optional_relation_paths = optional_relation_paths or {}
    for bundle_name, source_path in optional_relation_paths.items():
        dataset = bundle_name.split("/", 1)[0]
        content, relation_audit = _prepare_optional_relation_file(
            source_path=source_path,
            selected_road_ids=selected_roads_by_dataset.get(dataset, set()),
        )
        files[bundle_name] = content
        dataset_audits.setdefault(dataset, {}).setdefault("optional_relation_inputs", {})[Path(bundle_name).name] = relation_audit

    auto_fit_payload = None
    if auto_fit_attempts is not None:
        auto_fit_payload = {
            "enabled": True,
            "selected_bfs_depth": bfs_depth,
            "attempts": auto_fit_attempts,
        }

    manifest = {
        "bundle_version": P01_TEXT_BUNDLE_VERSION,
        "bundle_type": "p01_arm_build_single_junction_bfs_context",
        "junction_group": junction_ids,
        "bfs_depth": bfs_depth,
        "auto_fit": auto_fit_payload or {"enabled": False},
        "datasets": dataset_audits,
        "file_list": sorted(set(P01_BUNDLE_FILES).union(files)),
        "checksum": {},
        "encoder_info": {
            "archive_format": "zip",
            "compression": "deflate",
            "text_encoding": "base85",
            "line_width": P01_TEXT_BUNDLE_LINE_WIDTH,
            "max_text_size_bytes": max_text_size_bytes,
            "selection": "semantic-road-topology-bfs",
            "decoded_vector_format": "GeoPackage",
        },
        "created_at": _now_text(),
    }

    files["size_report.json"] = b"{}"
    files["manifest.json"] = b"{}"
    bundle_text = ""
    bundle_size_bytes = 0
    size_report: dict[str, Any] | None = None
    for _ in range(4):
        manifest["checksum"] = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in files.items()
            if name != "manifest.json"
        }
        files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        payload_bytes, per_file_compressed = _zip_bytes(files)
        meta = {
            "bundle_version": P01_TEXT_BUNDLE_VERSION,
            "bundle_type": manifest["bundle_type"],
            "junction_group": junction_ids,
            "bfs_depth": bfs_depth,
            "archive_format": "zip",
            "encoding": "base85",
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "created_at": _now_text(),
        }
        bundle_text, bundle_size_bytes = _build_bundle_text(meta=meta, payload_bytes=payload_bytes)
        next_size_report = _build_size_report(
            total_text_size_bytes=bundle_size_bytes,
            payload_size_bytes=len(payload_bytes),
            per_file_raw_size_bytes={name: len(content) for name, content in files.items()},
            per_file_compressed_size_bytes=per_file_compressed,
            dataset_audits=dataset_audits,
            limit_bytes=max_text_size_bytes,
        )
        if auto_fit_payload is not None:
            next_size_report["auto_fit"] = auto_fit_payload
        next_bytes = json.dumps(next_size_report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        if next_size_report == size_report:
            break
        size_report = next_size_report
        files["size_report.json"] = next_bytes

    assert size_report is not None
    return bundle_text, bundle_size_bytes, size_report


def _payload_and_meta_from_bundle_text(bundle_text: str) -> tuple[dict[str, Any], bytes]:
    return _parse_text_bundle(bundle_text)


def _write_split_bundle(
    *,
    out_txt_path: Path,
    bundle_text: str,
    size_report: dict[str, Any],
    max_text_size_bytes: int,
) -> tuple[tuple[Path, ...], int]:
    meta, payload_bytes = _payload_and_meta_from_bundle_text(bundle_text)
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


def _attempt_summary(
    *,
    bfs_depth: int,
    bundle_size_bytes: int,
    size_report: dict[str, Any],
    max_text_size_bytes: int,
) -> dict[str, Any]:
    dataset_counts = {}
    for dataset, audit in (size_report.get("dataset_audits") or {}).items():
        dataset_counts[dataset] = {
            "selected_node_count": audit.get("selected_node_count"),
            "selected_road_count": audit.get("selected_road_count"),
            "visited_group_count": audit.get("visited_group_count"),
        }
    return {
        "bfs_depth": bfs_depth,
        "bundle_size_bytes": bundle_size_bytes,
        "within_limit": bundle_size_bytes <= max_text_size_bytes,
        "dataset_counts": dataset_counts,
        "dominant_size_source": size_report.get("dominant_size_source"),
    }


def _print_attempt(attempt: dict[str, Any]) -> None:
    dataset_bits = []
    for dataset in DATASETS:
        counts = attempt.get("dataset_counts", {}).get(dataset, {})
        dataset_bits.append(
            f"{dataset}:roads={counts.get('selected_road_count')} nodes={counts.get('selected_node_count')}"
        )
    print(
        "[p01-bundle] "
        f"depth={attempt['bfs_depth']} size={attempt['bundle_size_bytes']} "
        f"within_limit={attempt['within_limit']} {'; '.join(dataset_bits)}",
        file=sys.stderr,
        flush=True,
    )


def run_p01_export_text_bundle(
    *,
    swsd_nodes: str | Path,
    swsd_roads: str | Path,
    rcsd_nodes: str | Path,
    rcsd_roads: str | Path,
    frcsd_nodes: str | Path,
    frcsd_roads: str | Path,
    swsd_road_node_road: str | Path | None = None,
    swsd_road_next_road: str | Path | None = None,
    rcsd_road_next_road: str | Path | None = None,
    junction_group: str,
    out_txt: str | Path,
    bfs_depth: int = 2,
    auto_fit: bool = False,
    max_bfs_depth: int = 8,
    max_text_size_bytes: int = P01_TEXT_BUNDLE_LIMIT_BYTES,
    verbose: bool = False,
) -> P01TextBundleExportArtifacts:
    out_txt_path = Path(out_txt)
    out_txt_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_existing_bundle_outputs(out_txt_path)
    size_report_path = _out_size_report_path(out_txt_path)
    if size_report_path.exists():
        size_report_path.unlink()

    try:
        if bfs_depth < 0:
            raise P01TextBundleError("invalid_bfs_depth", "bfs_depth must be >= 0.")
        if max_bfs_depth < bfs_depth:
            raise P01TextBundleError("invalid_bfs_depth", "max_bfs_depth must be >= bfs_depth.")
        junction_ids = _parse_junction_group(junction_group)
        dataset_inputs = _dataset_inputs_from_paths(
            swsd_nodes=swsd_nodes,
            swsd_roads=swsd_roads,
            rcsd_nodes=rcsd_nodes,
            rcsd_roads=rcsd_roads,
            frcsd_nodes=frcsd_nodes,
            frcsd_roads=frcsd_roads,
        )
        optional_relation_paths = {
            P01_OPTIONAL_RELATION_BUNDLE_NAMES[key][1]: Path(value)
            for key, value in {
                "swsd_road_node_road": swsd_road_node_road,
                "swsd_road_next_road": swsd_road_next_road,
                "rcsd_road_next_road": rcsd_road_next_road,
            }.items()
            if value is not None
        }
        loaded_by_dataset = {
            dataset: load_dataset(dataset_inputs[dataset])
            for dataset in DATASETS
        }

        attempts: list[dict[str, Any]] = []
        selected_depth = bfs_depth
        selected_text = ""
        selected_size = 0
        selected_report: dict[str, Any] | None = None
        last_report: dict[str, Any] | None = None
        last_text = ""
        last_size = 0
        last_depth = bfs_depth
        depths = range(bfs_depth, max_bfs_depth + 1) if auto_fit else (bfs_depth,)
        for current_depth in depths:
            bundle_text, bundle_size_bytes, size_report = _build_text_bundle_for_depth(
                dataset_inputs=dataset_inputs,
                loaded_by_dataset=loaded_by_dataset,
                junction_ids=junction_ids,
                bfs_depth=current_depth,
                max_text_size_bytes=max_text_size_bytes,
                optional_relation_paths=optional_relation_paths,
            )
            attempt = _attempt_summary(
                bfs_depth=current_depth,
                bundle_size_bytes=bundle_size_bytes,
                size_report=size_report,
                max_text_size_bytes=max_text_size_bytes,
            )
            last_report = size_report
            last_text = bundle_text
            last_size = bundle_size_bytes
            last_depth = current_depth
            attempts.append(attempt)
            if verbose:
                _print_attempt(attempt)
            if bundle_size_bytes <= max_text_size_bytes:
                selected_depth = current_depth
                selected_text = bundle_text
                selected_size = bundle_size_bytes
                selected_report = size_report

        if auto_fit and selected_report is not None:
            base_selected_text = selected_text
            base_selected_size = selected_size
            rebuilt_text, rebuilt_size, rebuilt_report = _build_text_bundle_for_depth(
                dataset_inputs=dataset_inputs,
                loaded_by_dataset=loaded_by_dataset,
                junction_ids=junction_ids,
                bfs_depth=selected_depth,
                max_text_size_bytes=max_text_size_bytes,
                optional_relation_paths=optional_relation_paths,
                auto_fit_attempts=attempts,
            )
            if rebuilt_size <= max_text_size_bytes:
                selected_text = rebuilt_text
                selected_size = rebuilt_size
                selected_report = rebuilt_report
            else:
                selected_text = base_selected_text
                selected_size = base_selected_size
                sidecar_report = {
                    "auto_fit_selected_depth": selected_depth,
                    "auto_fit_attempts": attempts,
                    "note": "auto_fit attempt details kept outside bundle because embedding them would exceed the text size limit",
                }
                size_report_path.write_text(json.dumps(sidecar_report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

        if last_report is not None and last_text and (selected_report is None or (auto_fit and last_size > max_text_size_bytes)):
            selected_depth = last_depth
            selected_text = last_text
            selected_size = last_size
            selected_report = last_report

        if selected_report is None:
            detail_report = dict(last_report or {})
            detail_report["auto_fit_attempts"] = attempts
            return P01TextBundleExportArtifacts(
                success=False,
                bundle_txt_path=out_txt_path,
                size_report_path=size_report_path if size_report_path.exists() else None,
                bundle_size_bytes=0,
                failure_reason="bundle_build_failed",
                failure_detail="No bundle payload was generated.",
            )

        part_paths: tuple[Path, ...] = ()
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
            size_report_path.write_text(json.dumps(selected_report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return P01TextBundleExportArtifacts(
            success=True,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=selected_size,
            selected_bfs_depth=selected_depth,
            part_txt_paths=part_paths,
            max_part_size_bytes=max_part_size_bytes,
        )
    except Exception as exc:
        reason = getattr(exc, "reason", "bundle_export_failed")
        detail = getattr(exc, "detail", str(exc))
        return P01TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            failure_reason=reason,
            failure_detail=detail,
        )


def _restore_vector_file(
    *,
    source_path: Path,
    target_path: Path,
    origin_x: float,
    origin_y: float,
    crs_text: str | None,
) -> None:
    features: list[dict[str, Any]] = []
    with fiona.open(source_path) as src:
        for feature in src:
            geometry_payload = feature.get("geometry")
            geometry = None if geometry_payload is None else translate(shape(geometry_payload), xoff=origin_x, yoff=origin_y)
            features.append({"properties": dict(feature.get("properties") or {}), "geometry": geometry})
    write_vector(target_path, features, crs_text=crs_text, layer_name=target_path.stem)


def _bundle_payload_from_text_file(bundle_txt: Path) -> tuple[bytes, dict[str, Any] | None]:
    meta, payload_bytes = _parse_text_bundle(bundle_txt.read_text(encoding="utf-8"))
    split_meta = meta.get("split_bundle") or {}
    if not split_meta.get("enabled"):
        return payload_bytes, None

    part_count = int(split_meta.get("part_count") or 0)
    part_filenames = [str(name) for name in split_meta.get("part_filenames") or ()]
    full_payload_sha256 = str(split_meta.get("full_payload_sha256") or split_meta.get("bundle_id") or "")
    if part_count <= 0 or len(part_filenames) != part_count or not full_payload_sha256:
        raise P01TextBundleError("invalid_split_bundle", "Split bundle metadata is incomplete.")

    chunks: dict[int, bytes] = {}
    for filename in part_filenames:
        part_path = bundle_txt.parent / filename
        if not part_path.is_file():
            raise P01TextBundleError("bundle_part_missing", f"Split bundle part missing: {part_path}")
        part_meta, part_payload = _parse_text_bundle(part_path.read_text(encoding="utf-8"))
        part_split = part_meta.get("split_bundle") or {}
        if str(part_split.get("full_payload_sha256") or part_split.get("bundle_id") or "") != full_payload_sha256:
            raise P01TextBundleError("split_bundle_mismatch", f"Split bundle id mismatch: {part_path}")
        if int(part_split.get("part_count") or 0) != part_count:
            raise P01TextBundleError("split_bundle_mismatch", f"Split bundle part count mismatch: {part_path}")
        part_index = int(part_split.get("part_index") or 0)
        if part_index < 1 or part_index > part_count or part_index in chunks:
            raise P01TextBundleError("invalid_split_bundle", f"Invalid split bundle part index: {part_path}")
        chunks[part_index] = part_payload

    if len(chunks) != part_count:
        raise P01TextBundleError("bundle_part_missing", "Split bundle parts are incomplete.")
    full_payload = b"".join(chunks[index] for index in range(1, part_count + 1))
    if hashlib.sha256(full_payload).hexdigest() != full_payload_sha256:
        raise P01TextBundleError("checksum_mismatch", "Split bundle full payload checksum validation failed.")
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
        missing = [name for name in P01_BUNDLE_FILES if name not in names]
        if missing:
            raise P01TextBundleError("bundle_missing_files", f"Bundle is missing required files: {','.join(missing)}")
        for name in names:
            parts = Path(name).parts
            if Path(name).is_absolute() or ".." in parts:
                raise P01TextBundleError("invalid_bundle_path", f"Bundle file path is not safe: {name}")
        files = {name: zf.read(name) for name in names}
    manifest = json.loads(files["manifest.json"])
    checksums = dict(manifest.get("checksum") or {})
    for name, content in files.items():
        if name == "manifest.json":
            continue
        expected = checksums.get(name)
        if expected and hashlib.sha256(content).hexdigest() != expected:
            raise P01TextBundleError("checksum_mismatch", f"Checksum mismatch for {name}.")
    if split_report is not None:
        size_report = json.loads(files["size_report.json"])
        size_report["split_bundle"] = split_report
        files["size_report.json"] = json.dumps(size_report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    return manifest, files


def run_p01_decode_text_bundle(
    *,
    bundle_txt: str | Path,
    out_dir: str | Path | None = None,
) -> P01TextBundleDecodeArtifacts:
    bundle_path = Path(bundle_txt)
    if not bundle_path.is_file():
        raise P01TextBundleError("bundle_not_found", f"Bundle text file does not exist: {bundle_path}")
    out_dir_path = Path(out_dir) if out_dir is not None else bundle_path.with_suffix("")
    out_dir_path.mkdir(parents=True, exist_ok=True)
    manifest, files = _extract_and_verify_bundle(bundle_path)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        for name, content in files.items():
            temp_path = temp_root / name
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(content)
        for dataset in DATASETS:
            dataset_meta = manifest["datasets"][dataset]
            origin = dataset_meta["local_origin"]
            dataset_dir = out_dir_path / dataset
            dataset_dir.mkdir(parents=True, exist_ok=True)
            _restore_vector_file(
                source_path=temp_root / dataset / "nodes.gpkg",
                target_path=dataset_dir / "nodes.gpkg",
                origin_x=float(origin["x"]),
                origin_y=float(origin["y"]),
                crs_text=dataset_meta.get("node_crs"),
            )
            _restore_vector_file(
                source_path=temp_root / dataset / "roads.gpkg",
                target_path=dataset_dir / "roads.gpkg",
                origin_x=float(origin["x"]),
                origin_y=float(origin["y"]),
                crs_text=dataset_meta.get("road_crs"),
            )
        for name, content in files.items():
            if name in P01_BUNDLE_FILES:
                continue
            target_path = out_dir_path / name
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)

    manifest["decoded_output"] = {
        "vector_coordinates": "absolute_source_coordinates",
        "bundle_internal_vectors_localized": True,
        "decoded_at": _now_text(),
    }
    manifest_path = out_dir_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir_path / "size_report.json").write_bytes(files["size_report.json"])
    return P01TextBundleDecodeArtifacts(success=True, out_dir=out_dir_path, manifest_path=manifest_path)


def _build_export_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p01-export-text-bundle-dev")
    parser.add_argument("--swsd-nodes", required=True)
    parser.add_argument("--swsd-roads", required=True)
    parser.add_argument("--rcsd-nodes", required=True)
    parser.add_argument("--rcsd-roads", required=True)
    parser.add_argument("--frcsd-nodes", required=True)
    parser.add_argument("--frcsd-roads", required=True)
    parser.add_argument("--swsd-road-node-road")
    parser.add_argument("--swsd-road-next-road")
    parser.add_argument("--rcsd-road-next-road")
    parser.add_argument("--junction-group", required=True)
    parser.add_argument("--out-txt", required=True)
    parser.add_argument("--bfs-depth", type=int, default=2)
    parser.add_argument("--auto-fit", action="store_true")
    parser.add_argument("--max-bfs-depth", type=int, default=8)
    parser.add_argument("--max-text-size-bytes", type=int, default=P01_TEXT_BUNDLE_LIMIT_BYTES)
    return parser


def _build_decode_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p01-decode-text-bundle-dev")
    parser.add_argument("--bundle-txt", required=True)
    parser.add_argument("--out-dir")
    return parser


def run_p01_export_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_export_arg_parser().parse_args(argv)
    artifacts = run_p01_export_text_bundle(
        swsd_nodes=args.swsd_nodes,
        swsd_roads=args.swsd_roads,
        rcsd_nodes=args.rcsd_nodes,
        rcsd_roads=args.rcsd_roads,
        frcsd_nodes=args.frcsd_nodes,
        frcsd_roads=args.frcsd_roads,
        swsd_road_node_road=args.swsd_road_node_road,
        swsd_road_next_road=args.swsd_road_next_road,
        rcsd_road_next_road=args.rcsd_road_next_road,
        junction_group=args.junction_group,
        out_txt=args.out_txt,
        bfs_depth=args.bfs_depth,
        auto_fit=args.auto_fit,
        max_bfs_depth=args.max_bfs_depth,
        max_text_size_bytes=args.max_text_size_bytes,
        verbose=True,
    )
    if not artifacts.success:
        print(f"P01 text bundle export failed: {artifacts.failure_detail}", file=sys.stderr)
        if artifacts.size_report_path is not None:
            print(f"size_report={artifacts.size_report_path}", file=sys.stderr)
        return 1
    print(f"P01 text bundle written to: {artifacts.bundle_txt_path}")
    print(f"bundle_size_bytes={artifacts.bundle_size_bytes}")
    if artifacts.part_txt_paths:
        print(f"bundle_part_count={len(artifacts.part_txt_paths)}")
        print(f"max_part_size_bytes={artifacts.max_part_size_bytes}")
        for path in artifacts.part_txt_paths:
            print(f"bundle_part={path}")
    if artifacts.selected_bfs_depth is not None:
        print(f"selected_bfs_depth={artifacts.selected_bfs_depth}")
    if artifacts.size_report_path is not None:
        print(f"size_report={artifacts.size_report_path}")
    return 0


def run_p01_decode_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_decode_arg_parser().parse_args(argv)
    artifacts = run_p01_decode_text_bundle(bundle_txt=args.bundle_txt, out_dir=args.out_dir)
    print(f"P01 text bundle decoded to: {artifacts.out_dir}")
    print(f"manifest={artifacts.manifest_path}")
    return 0
